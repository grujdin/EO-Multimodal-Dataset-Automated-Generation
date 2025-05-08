"""
Copernicus EMS Rapid‑Mapping Connector • v2.1.0
================================================
Now supports **ArcGIS token authentication** *and* proper 1 000‑record paging.

How token handling works
------------------------
* At runtime the module looks for an **environment variable** called
  `ARCGIS_TOKEN`.  You can also pass `--token …` on the CLI or the
  `token="…"` keyword to the helper functions.
* If the variable / argument is **absent** we fall back to anonymous requests –
  still useful if the service drops auth requirements again.

Public helpers
--------------
```python
list_activations(code_prefix=None, limit=20, offset=0, *,
                 cache:Path|None=None, token:str|None=None) -> List[dict]
activation_by_code(code, *, cache=None, token=None) -> dict|None
```
Other exported names: `OntologyClient`, `ActivationsFetchError`, `run_cli`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
from rdflib import Graph

__all__ = [
    "list_activations",
    "activation_by_code",
    "OntologyClient",
    "ActivationsFetchError",
    "run_cli",
]

# ---------------------------------------------------------------------------
# ArcGIS Feature‑Service settings
# ---------------------------------------------------------------------------
BASE_URL = (
    "https://services-eu1.arcgis.com/0CuUZGoyB9SHyWV8/ArcGIS/rest/services/"
    "Public_Activations/FeatureServer/0/query"
)
COMMON_PARAMS = {
    "where": "1=1",
    "outFields": "*",
    "returnGeometry": "false",
    "f": "json",
}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
PAGE_SIZE = 1000  # ArcGIS max features per page without server-side flows

# ---------------------------------------------------------------------------
# Error & cache
# ---------------------------------------------------------------------------
class ActivationsFetchError(RuntimeError):
    pass

_CACHE: Dict[str, Any] | None = None

# ---------------------------------------------------------------------------
# Internal fetch with token + paging
# ---------------------------------------------------------------------------

def _download_all_features(token: str | None) -> List[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            **COMMON_PARAMS,
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
        }
        if token:
            params["token"] = token
        try:
            r = requests.get(BASE_URL, params=params, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            raise ActivationsFetchError(f"ArcGIS request failed → {e}") from None

        if "error" in data:
            msg = data["error"].get("message", str(data["error"]))
            raise ActivationsFetchError(f"ArcGIS error → {msg}")

        feats = data.get("features", [])
        features.extend(feats)
        if len(feats) < PAGE_SIZE:
            break  # last page reached
        offset += PAGE_SIZE
    return features


def _fetch_activations(cache_path: Path | None = None, token: str | None = None) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if cache_path and cache_path.exists():
        _CACHE = json.loads(cache_path.read_text())
        return _CACHE

    feats = _download_all_features(token)
    _CACHE = {"features": feats}
    if cache_path:
        cache_path.write_text(json.dumps(_CACHE))
    return _CACHE

# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------

def _filter_prefix(feats: List[Dict[str, Any]], prefix: str | None):
    return feats if not prefix else [f for f in feats if f["attributes"].get("code", "").startswith(prefix)]


def list_activations(*, code_prefix: str | None = None, limit: int = 20, offset: int = 0, cache: Path | None = None, token: str | None = None) -> List[Dict[str, Any]]:
    token = token or os.getenv("ARCGIS_TOKEN")
    data = _fetch_activations(cache, token)
    feats = _filter_prefix(data["features"], code_prefix)
    sliced = feats[offset : offset + limit]
    return [f["attributes"] for f in sliced]


def activation_by_code(code: str, *, cache: Path | None = None, token: str | None = None) -> Dict[str, Any] | None:
    token = token or os.getenv("ARCGIS_TOKEN")
    data = _fetch_activations(cache, token)
    for f in data["features"]:
        if f["attributes"].get("code") == code:
            return f["attributes"]
    return None

# ---------------------------------------------------------------------------
# Ontology helper (unchanged)
# ---------------------------------------------------------------------------
DEFAULT_TTL = Path("cems_activations.ttl")

class OntologyClient:
    def __init__(self, ttl_path: Path | str = DEFAULT_TTL):
        ttl_path = Path(ttl_path)
        if not ttl_path.exists():
            raise FileNotFoundError(ttl_path)
        self.graph = Graph().parse(str(ttl_path), format="ttl")

    def run(self, q: str):
        return [{str(k): str(v) for k, v in row.asdict().items()} for row in self.graph.query(q)]

    def pretty(self, q: str):
        rows = self.run(q)
        if not rows:
            print("<no results>")
            return
        print(pd.DataFrame(rows).to_string(index=False))

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
EXAMPLE_LINES = [
    "python CEMS.py list --limit 10",
    "python CEMS.py list --code EMSR56 --limit 5",
    "python CEMS.py get EMSR568",
]


def _build_parser():
    p = argparse.ArgumentParser("cems", description="Copernicus EMS Rapid Mapping (ArcGIS) CLI / library")
    sub = p.add_subparsers(dest="cmd", required=True)

    lst = sub.add_parser("list")
    lst.add_argument("--code", dest="code_prefix")
    lst.add_argument("--limit", type=int, default=20)
    lst.add_argument("--offset", type=int, default=0)

    g = sub.add_parser("get")
    g.add_argument("code")

    s = sub.add_parser("sparql")
    s.add_argument("query")

    p.add_argument("--cache", type=Path)
    p.add_argument("--ontology", type=Path, default=DEFAULT_TTL)
    p.add_argument("--token", help="ArcGIS token (overrides ARCGIS_TOKEN env)")
    p.add_argument("--json", action="store_true")
    return p

# pretty print helper

def _show(rows: List[Dict[str, Any]]):
    if not rows:
        print("<empty>")
        return
    table = pd.DataFrame.from_records([
        {
            "code": r.get("code"),
            "name": r.get("name"),
            "category": r.get("category"),
            "activator": r.get("activator"),
            "activationTime": r.get("activationTime"),
        } for r in rows
    ])
    pd.set_option("display.max_colwidth", None)
    print(table.to_string(index=False))

# ---------------------------------------------------------------------------
# run_cli
# ---------------------------------------------------------------------------

def run_cli(argv: List[str] | None = None):
    args = _build_parser().parse_args(argv)
    token = args.token or os.getenv("ARCGIS_TOKEN")
    try:
        if args.cmd == "list":
            rows = list_activations(code_prefix=args.code_prefix, limit=args.limit, offset=args.offset, cache=args.cache, token=token)
            print(json.dumps(rows, indent=2) if args.json else _show(rows))
        elif args.cmd == "get":
            row = activation_by_code(args.code, cache=args.cache, token=token)
            if not row:
                print("Activation not found")
            else:
                print(json.dumps(row, indent=2) if args.json else _show([row]))
        elif args.cmd == "sparql":
            oc = OntologyClient(args.ontology)
            print(json.dumps(oc.run(args.query), indent=2) if args.json else oc.pretty(args.query))
    except ActivationsFetchError as e:
        sys.exit(f"ArcGIS fetch error: {e}")

# ---------------------------------------------------------------------------
# Entry‑point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("USAGE examples:")
        for ex in EXAMPLE_LINES:
            print("  " + ex)
        sys.exit(0)
    run_cli(sys.argv[1:])