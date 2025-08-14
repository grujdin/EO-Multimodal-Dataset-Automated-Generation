#!/usr/bin/env python3
"""
Generate Sentinel‑Hub /process payloads for every FL_???????_*.geojson
found under a root directory.

For each episode GeoJSON we create, *in the same folder*:

    S2_FL_<event>_<ep>_request_224.json   /  _evalscript.js
    S1_FL_<event>_<ep>_request_224.json   /  _evalscript.js
    LS_FL_<event>_<ep>_request_224.json   /  _evalscript.js
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from datetime import datetime, timedelta
import math

import shapely.geometry as sgeom          # pip install shapely
import shapely.ops      as sops
import geojson                            # pip install geojson
import argparse

cli = argparse.ArgumentParser(description="Generate SH helper files")
cli.add_argument("--force", action="store_true",
                 help="overwrite existing JSON/JS files")
ARGS = cli.parse_args()

ROOT   = Path("FL")        # root that holds the FL_xxxxxxx folders
OUT_WH = 224               # output pixel size (square)

# ── sensor presets ───────────────────────────────────────────
SENSORS = {
    # Sentinel‑2 L2A native 10 m
    "S2": dict(
        type       = "sentinel-2-l2a",
        bands      = ["B02","B03","B04","B05","B06","B07",
                      "B08","B8A","B09","B11","B12"],
        units      = "REFLECTANCE",
        sampleType = "UINT16",
        fmt        = "image/tiff",
        gsd        = 10          # metres per pixel
    ),
    # Sentinel‑1 GRD 10 m (IW mode)
    "S1": dict(
        type       = "sentinel-1-grd",
        bands      = ["VV","VH"],
        units      = None,
        sampleType = "FLOAT32",
        fmt        = "image/tiff",
        gsd        = 10
    ),
    # Landsat‑8/9 L1 30 m
    "LS": dict(
        type       = "landsat-ot-l1",
        bands      = [f"B0{i}" for i in range(1,8)] + ["B09"],
        units      = "REFLECTANCE",
        sampleType = "UINT16",
        fmt        = "image/tiff",
        gsd        = 30
    ),
    # Landsat thermal brightness‑temperature (30 m)
    "LS_T": dict(
        type="landsat-ot-l1",
        bands=["B10", "B11"],
        units="BRIGHTNESS_TEMPERATURE",
        sampleType="FLOAT32",
        fmt="image/tiff",
        gsd=30
    ),

}


# ══════════════════ helpers ══════════════════════════════════
def _extract_geom(obj) -> sgeom.base.BaseGeometry | None:
    """Return geometry for any GeoJSON structure."""
    if not isinstance(obj, dict):
        return None
    # Bare geometry
    if obj.get("type") in {
        "Point","MultiPoint","LineString","MultiLineString",
        "Polygon","MultiPolygon"
    }:
        return sgeom.shape(obj)
    # Feature
    if obj.get("type") == "Feature" and "geometry" in obj:
        return sgeom.shape(obj["geometry"])
    # FeatureCollection
    if obj.get("type") == "FeatureCollection":
        geoms = [_extract_geom(f) for f in obj.get("features", [])]
        geoms = [g for g in geoms if g and not g.is_empty]
        return sops.unary_union(geoms) if geoms else None
    # GeometryCollection
    if obj.get("type") == "GeometryCollection":
        geoms = [sgeom.shape(g) for g in obj.get("geometries", [])]
        geoms = [g for g in geoms if not g.is_empty]
        return sops.unary_union(geoms) if geoms else None
    return None

def episode_bbox(gj_file: Path) -> tuple[list[float], str]:
    """Return (lon/lat bbox, ISO start date) for an episode GeoJSON."""
    with gj_file.open() as fh:
        gj = geojson.load(fh)

    geom = _extract_geom(gj)
    if geom is None or geom.is_empty:
        raise ValueError(f"{gj_file.name}: no valid geometry found")
    minx, miny, maxx, maxy = geom.bounds
    bbox = [minx, miny, maxx, maxy]

    # ── find a start date ─────────────────────────────────────────────
    def _find_date(obj):
        if isinstance(obj, dict):
            for k in ("fromdate", "begindate", "startdate", "fromDate", "date"):
                if obj.get(k):
                    return obj[k]
            for v in obj.values():
                d = _find_date(v)
                if d:
                    return d
        elif isinstance(obj, list):
            for it in obj:
                d = _find_date(it)
                if d:
                    return d
        return None

    iso_start = _find_date(gj)
    if not iso_start:
        iso_start = datetime.utcfromtimestamp(
            gj_file.stat().st_mtime
        ).strftime("%Y-%m-%dT00:00:00Z")

    # ── normalise to ISO 8601 with explicit timezone ──────────────────
    if len(iso_start) == 10:              # "YYYY‑MM‑DD"
        iso_start += "T00:00:00Z"
    elif not iso_start.endswith("Z") and "+" not in iso_start:
        iso_start += "Z"

    return bbox, iso_start


def make_evalscript(bands: list[str],
                    units: str | None,
                    sample_type: str) -> str:
    """Return an evalscript with all raw bands in original order."""
    band_list  = ", ".join(f'"{b}"' for b in bands)
    out_bands  = len(bands)
    units_part = f', units: "{units}"' if units else ""
    return f"""// auto-generated
function setup() {{
  return {{
    input: [{{ bands: [{band_list}]{units_part} }}],
    output: {{ bands: {out_bands}, sampleType: SampleType.{sample_type} }}
  }};
}}

function evaluatePixel(s) {{
  return [{", ".join(f"s.{b}" for b in bands)}];
}}""".strip()


def make_body(sensor: dict, bbox: list[float], date_from: str) -> dict:
    """
    Build the /process JSON body.
    • 2 240 m footprint centred on episode centroid
    • pixel size = ceil(2240 / native GSD)
    """
    # ----- 30‑day window -------------------------------------------------
    date_to = (datetime.fromisoformat(date_from[:10]) +
               timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")

    # ----- centre box on event centroid ---------------------------------
    minx, miny, maxx, maxy = bbox
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = 2240 / 2 / 111_320          # deg at equator ≈ metres / 111 320
    bbox_fixed = [cx - half, cy - half, cx + half, cy + half]

    # ----- pixel dimensions from native GSD -----------------------------
    width_px  = height_px = math.ceil(2240 / sensor["gsd"])
    # Sentinel‑Hub hard limit
    width_px  = min(width_px, 2500)
    height_px = min(height_px, 2500)

    return {
        "input": {
            "bounds": {
                "bbox": bbox_fixed,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
            },
            "data": [{
                "type": sensor["type"],
                "dataFilter": {"timeRange": {"from": date_from, "to": date_to}}
            }]
        },
        "output": {
            "width":  width_px,
            "height": height_px,
            "responses": [{
                "format": {"type": sensor["fmt"]}
            }]
        }
    }

# ══════════════════ main loop ═══════════════════════════════
generated = 0
for gj in ROOT.rglob("FL_*_*.geojson"):
    try:
        bbox, start = episode_bbox(gj)
    except Exception as exc:
        print(f"⚠️  {exc}", file=sys.stderr)
        continue

    etype, eid, epid = gj.stem.split("_")[0:3]  # "FL", "1100103", "1"

    for tag, spec in SENSORS.items():
        base       = f"{tag}_{etype}_{eid}_{epid}"
        js_path    = gj.with_name(f"{base}_evalscript.js")
        json_path  = gj.with_name(f"{base}_request_{OUT_WH}.json")

        if js_path.exists() and json_path.exists() and not ARGS.force:
            continue

        js_path.write_text(
            make_evalscript(spec["bands"], spec["units"], spec["sampleType"]),
            encoding="utf-8"
        )
        json_path.write_text(
            json.dumps(make_body(spec, bbox, start), indent=2),
            encoding="utf-8"
        )
        generated += 2

print(f"✅ {generated} files written under {ROOT}")
