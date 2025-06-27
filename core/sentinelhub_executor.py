# sentinelhub_executor.py
# -----------------------------------------------------------
# Executes Sentinel Hub requests, auto-detects binary vs JSON
# replies, converts JSON to a DataFrame, and fully flattens
# nested list/dict columns so they export cleanly to CSV.
# -----------------------------------------------------------

from __future__ import annotations

import json
import tempfile
from typing import Any, Dict, List, Tuple

import pandas as pd
import requests
from core.openapi_parser import build_full_url

# Keys we want to unwrap when first normalising JSON ↓↓↓
_WRAP_KEYS: Tuple[str, ...] = ("collections", "features", "items", "assets")

# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────
def _flatten_geojson_features(features: List[Dict[str, Any]]) -> pd.DataFrame:
    """GeoJSON FeatureCollection → wide DataFrame."""
    rows = []
    for feat in features:
        row = {**feat.get("properties", {})}
        row["id"] = feat.get("id")
        row["collection"] = feat.get("collection")
        rows.append(row)
    return pd.json_normalize(rows)


def _json_to_df(payload: Any) -> pd.DataFrame | None:
    """1st-layer normalisation (collections, features, items …)."""
    if isinstance(payload, dict) and "features" in payload:
        return _flatten_geojson_features(payload["features"])

    if isinstance(payload, dict):
        for key in _WRAP_KEYS:
            if key in payload and isinstance(payload[key], list):
                return pd.json_normalize(payload[key])
        return pd.json_normalize(payload)

    if isinstance(payload, list):
        return pd.json_normalize(payload)

    return None


def _explode_json_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recursively explode columns that still contain lists.
    If the list elements are dicts, normalise them into <col>.<key> columns.
    """
    df = df.copy(deep=True)

    while True:
        list_cols = [c for c in df.columns if df[c].apply(lambda x: isinstance(x, list)).any()]
        if not list_cols:
            break

        col = list_cols[0]
        df = df.explode(col, ignore_index=True)

        # If exploded values are dicts → widen
        if df[col].apply(lambda x: isinstance(x, dict)).any():
            nested = pd.json_normalize(df[col]).add_prefix(f"{col}.")
            df = pd.concat([df.drop(columns=[col]), nested], axis=1)

    return df


def _desired_accept_header(post_body: dict | None) -> str | None:
    """Return mime-type declared in Process API JSON, e.g. 'image/tiff'."""
    try:
        resp = (post_body or {}).get("output", {}).get("responses", [])
        if resp:
            return resp[0].get("format", {}).get("type")
    except Exception:
        pass
    return None


# ────────────────────────────────────────────────────────────
# Main entry point
# ────────────────────────────────────────────────────────────
def execute_sentinel_query(
    swagger: dict,
    method: str,
    path_template: str,
    query_params: dict | None = None,
    post_body: dict | None = None,
    path_vals: dict | None = None,
    token: str | None = None,
):
    """Return (url, raw_json_or_dict, dataframe_or_None)."""
    url = build_full_url(swagger, path_template, path_vals, query_params)

    try:
        method_up = method.upper()
        headers: Dict[str, str] = {"Authorization": f"Bearer {token}"}

        # 1️⃣  Build & send HTTP request
        if method_up == "POST" and "/process" in path_template:
            headers["Content-Type"] = "application/json"
            accept = _desired_accept_header(post_body)
            if accept:
                headers["Accept"] = accept
            response = requests.post(url, headers=headers, data=json.dumps(post_body or {}))

        elif method_up == "GET":
            headers["Accept"] = "application/json"
            response = requests.get(url, headers=headers)

        elif method_up == "POST":
            headers.update({"Content-Type": "application/json", "Accept": "application/json"})
            response = requests.post(url, headers=headers, data=json.dumps(post_body or {}))

        else:
            return url, {"error": f"Unsupported method {method_up}"}, None

        # 2️⃣  Binary payload? (TIFF / PNG / octet-stream)
        ctype = response.headers.get("Content-Type", "")
        if "image" in ctype or "application/octet-stream" in ctype:
            suffix = ".tiff" if "tiff" in ctype or "tif" in ctype else ".bin"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(response.content)
            tmp.flush()
            return url, {"download_url": tmp.name}, None

        # 204 No Content or empty
        if response.status_code == 204 or not response.content:
            return url, {}, None

        # 3️⃣  JSON payload
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            return url, {"error": f"Non-JSON response: {exc}"}, None

        df = _json_to_df(data)
        if df is not None:
            df = _explode_json_columns(df)   # ← fully flatten nested lists
        return url, data, df

    # 4️⃣  Network / parsing errors
    except Exception as exc:  # noqa: BLE001
        print("Query failed:", exc, flush=True)
        return url, {"error": str(exc)}, None
