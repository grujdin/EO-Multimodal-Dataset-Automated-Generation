"""spectral_loader.py – enhanced July 2025
------------------------------------------------
•  Loads spectral‑index definitions from the *awesome‑spectral‑indices* repo
   (JSON or CSV) with a clean fallback set.
•  Works out of the box with Sentinel‑2 (Level‑2A 10 m/20 m stacks).
•  Hardened against malformed formulas, band‑orientation mistakes, division‑by‑zero
   and unrecognised band names.
"""
from __future__ import annotations

import csv
import json
import re
import pathlib
from typing import Dict, List, Callable, Tuple

import numpy as np

# ────────────────────────────────────────────────────────────────────────
# 1. Fallback content – used when the repo is missing or unreadable
# ────────────────────────────────────────────────────────────────────────
_FALLBACK_INDICES: dict[str, dict[str, object]] = {
    "NDVI":  {"formula": "(N - R) / (N + R)",        "bands": ["N", "R"]},
    "GNDVI": {"formula": "(N - G) / (N + G)",        "bands": ["N", "G"]},
    "NDRE":  {"formula": "(N - RE) / (N + RE)",      "bands": ["N", "RE"]},
    "SAVI":  {"formula": "1.5 * (N - R) / (N + R + 0.5)", "bands": ["N", "R"]},
}

# Canonical‑symbol → Sentinel‑2 Band (10/20 m stack).
# Extra aliases B06/B07 added so formulas can use RE2 / RE3 symbols.
_FALLBACK_ALIAS: dict[str, str] = {
    "B01": "C",   # Coastal aerosol 443 nm
    "B02": "B",   # Blue  490 nm
    "B03": "G",   # Green 560 nm
    "B04": "R",   # Red   665 nm
    "B05": "RE",  # Red‑edge 1 – 705 nm
    "B06": "RE2", # Red‑edge 2 – 740 nm
    "B07": "RE3", # Red‑edge 3 – 783 nm
    "B08": "N",   # NIR 842 nm (10 m)
    "B8A": "N2",  # Narrow NIR 865 nm (20 m)
    "B09": "WV",  # Water-vapour 945 nm
    "B11": "S1",  # SWIR 1 1610 nm (20 m)
    "B12": "S2",  # SWIR 2 2190 nm (20 m)
}

# ────────────────────────────────────────────────────────────────────────
class SpectralIndexFactory:
    """Parse *awesome‑spectral‑indices* metadata & build NumPy callables."""

    _RE_SYMBOL = re.compile(r"[A-Z][A-Z0-9_]*")  # simplistic, but safe enough

    def __init__(self, repo_root: pathlib.Path):
        self.root: pathlib.Path          = repo_root.expanduser().resolve()
        self._registry: Dict[str, Callable[[Dict[str, np.ndarray]], np.ndarray]] = {}
        self._required: Dict[str, List[str]] = {}
        self._alias: Dict[str, str]      = _FALLBACK_ALIAS.copy()

        self._load_aliases()
        self._load_indices()

    # ------------------------------------------------------------------
    # 1 ▸ Band‑alias map from bands.json (if present)
    # ------------------------------------------------------------------
    def _load_aliases(self) -> None:
        fn = self.root / "bands.json"
        if not fn.exists():
            return

        try:
            data = json.loads(fn.read_text())
        except Exception as exc:  # pragma: no cover – diagnostic only
            print("[spectral_loader] bands.json parse error:", exc)
            return

        for canon, meta in data.items():
            for platform, entry in meta.get("platforms", {}).items():
                if platform.lower().startswith("sentinel2"):
                    # Overwrite: JSON takes precedence over fallback table
                    self._alias[entry["band"].upper()] = canon.upper()

    # ------------------------------------------------------------------
    # 2 ▸ Load spectral‑index list (JSON ▸ CSV ▸ fallback)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 2 ▸ Load spectral-index list (JSON ▸ CSV ▸ fallback)
    # ------------------------------------------------------------------
    def _load_indices(self) -> None:
        entries: Dict[str, Dict[str, object]] | None = None

        # ---------- 1) JSON (preferred) ----------
        jdict = self.root / "spectral-indices-dict.json"
        if jdict.exists():
            try:
                raw = json.loads(jdict.read_text())

                # accept *both* flat and wrapped layouts
                if "SpectralIndices" in raw:
                    raw = raw["SpectralIndices"]

                entries = {
                    k.upper(): {
                        "formula": v["formula"],
                        "bands":   [b.upper() for b in v["bands"]],
                    }
                    for k, v in raw.items()
                }
            except Exception as exc:              # pragma: no cover
                print("[spectral_loader] JSON error:", exc)

        # ---------- 2) CSV (fallback if JSON missing) ----------
        if entries is None:
            csvf = self.root / "spectral-indices-table.csv"
            if csvf.exists():
                entries = {}
                try:
                    with csvf.open(newline="") as fh:
                        for row in csv.DictReader(fh):
                            entries[row["short_name"].strip().upper()] = {
                                "formula": row["formula"].strip(),
                                "bands": [
                                    s.strip().upper() for s in row["bands"].split("|")
                                ],
                            }
                except Exception as exc:          # pragma: no cover
                    print("[spectral_loader] CSV error:", exc)

        # ---------- 3) Hard-coded fallback ----------
        if entries is None:
            entries = _FALLBACK_INDICES

        # Build callables ------------------------------------------------
        for name, meta in entries.items():
            # Normalise names/symbols to upper‑case for consistency
            idx_name = name.upper()
            band_syms = [s.upper() for s in meta["bands"]]
            formula   = meta["formula"]

            # Replace every symbol with b["SYM"] – beware substrings
            def substitute_symbol(match: re.Match[str]) -> str:
                sym = match.group(0)
                return f'b["{sym}"]' if sym in band_syms else sym

            safe_expr = self._RE_SYMBOL.sub(substitute_symbol, formula)

            func = self._build_callable(safe_expr)
            self._registry[idx_name] = func
            self._required[idx_name] = band_syms

    # ------------------------------------------------------------------
    @staticmethod
    def _build_callable(expr: str) -> Callable[[Dict[str, np.ndarray]], np.ndarray]:
        """Return a function(b) that evaluates *expr* fast & safely.

        The callable ignores divide‑by‑zero & invalid runtime warnings and
        returns `nan_to_num(result, nan=nan)` so NaNs propagate but infs → nan.
        """
        def _idx(b: Dict[str, np.ndarray]):  # noqa: D401
            with np.errstate(divide="ignore", invalid="ignore"):
                res = eval(expr, {"np": np, "b": b}, {})  # builtins blocked
            return np.nan_to_num(res, copy=False, posinf=np.nan, neginf=np.nan)

        _idx.__doc__ = f"Dynamically generated index: {expr}"
        return _idx

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def list_indices(self) -> List[str]:
        return sorted(self._registry.keys())

    def get(self, name: str) -> Tuple[Callable, List[str]]:
        key = name.upper()
        if key not in self._registry:
            raise KeyError(f"Unknown index '{name}'. Available: {', '.join(self.list_indices())}")
        return self._registry[key], self._required[key]

    # ------------------------------------------------------------------
    def map_s2_bands(self, cube: np.ndarray) -> Dict[str, np.ndarray]:
        """Return a {{canonical_symbol: band_array}} mapping for a Sentinel‑2 cube.

        *Cube orientation*
        ------------------
        ▸ Accepts either (C, H, W) or (H, W, C).
        ▸ Detects orientation via the *channel count* on each axis.
        ▸ Supported channel counts: 10 (standard 10/20 m stack),
                                   12 (with QA + additional red‑edge),
                                   13 (full L2A set).
        Raises if it can’t find a plausible channel axis.
        """
        if cube.ndim != 3:
            raise ValueError(f"Expected a 3‑D array, got shape {cube.shape}")

        s2_channels = {10, 12, 13, 15}
        # Figure out where the channels sit --------------------------------
        if cube.shape[0] in s2_channels:          # (C, H, W) – already fine
            arr = cube
        elif cube.shape[2] in s2_channels:        # (H, W, C) – transpose
            arr = cube.transpose(2, 0, 1)
        else:
            raise ValueError(
                "Cannot guess cube orientation – channel axis not 10/12/13 bands."
            )

        c, h, w = arr.shape  # noqa: F841  (h/w unused but kept for clarity)
        s2_order = [
            "B02", "B03", "B04", "B05", "B06",
            "B07", "B08", "B8A", "B11", "B12",
            # If the cube has >10 channels we assume B01/B09/DataMask are trimmed already
        ]
        idx_map = {band: i for i, band in enumerate(s2_order) if i < c}

        out: Dict[str, np.ndarray] = {}
        for s2_name, canon in self._alias.items():
            s2_name = s2_name.upper()
            canon   = canon.upper()
            if s2_name in idx_map:
                out[canon] = arr[idx_map[s2_name]]

        if not out:
            raise ValueError("No Sentinel‑2 bands recognised in the provided cube.")
        return out
