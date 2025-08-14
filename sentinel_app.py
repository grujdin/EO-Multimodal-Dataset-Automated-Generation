#!/usr/bin/env python3
# sentinel_app.py – bulk /process downloader + GeoTIFF viewer
# Ver 1.0 Date 08/14/2025
# ══════════════════════════════════════════════════════════════

from __future__ import annotations

# ── std lib ────────────────────────────────────────────────────
import io, json, re, math
from datetime import datetime
from pathlib import Path
from typing import Iterable

# ── third‑party ────────────────────────────────────────────────
import numpy as np
import requests
import streamlit as st
import tifffile as tiff
import yaml
import rasterio                                 # NEW
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
from sentinelhub import SHConfig

# ── project helpers ────────────────────────────────────────────
from core.openapi_parser import load_swagger, get_parameters_for_endpoint, get_enum_options
from ui.endpoint_selector import select_endpoint
from core.sentinelhub_executor import execute_sentinel_query
from spectral_loader import SpectralIndexFactory

# ── Streamlit page settings ───────────────────────────────────
st.set_page_config("SH Semantic Connector", layout="wide")
DBG = st.sidebar.checkbox("🪲 debug mode", value=False)

# ═════════════════════ OAuth token helper ═════════════════════
def sh_token() -> str | None:
    cfg = SHConfig()
    if not (cfg.sh_client_id and cfg.sh_client_secret):
        st.error("Set SH_CLIENT_ID / SH_CLIENT_SECRET first")
        return None
    try:
        sess = OAuth2Session(client=BackendApplicationClient(cfg.sh_client_id))
        tok = sess.fetch_token(
            "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token",
            client_id=cfg.sh_client_id,
            client_secret=cfg.sh_client_secret,
            include_client_id=True,
        )
        return tok["access_token"]
    except Exception as exc:
        st.exception(exc)
        return None

# ═════════════════════ OpenAPI loader (cached) ════════════════
@st.cache_data(show_spinner=False)
def load_api(buf: bytes):
    for fn in (lambda b: load_swagger(io.BytesIO(b)),
               lambda b: json.loads(b.decode()),
               lambda b: yaml.safe_load(b.decode())):
        try:
            return fn(buf)
        except Exception:
            continue
    raise RuntimeError("Cannot parse supplied API spec")

# ═════════════════════ NumPy / preview helpers ════════════════
def to_hwc(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return arr[..., None]
    if arr.ndim != 3:
        raise ValueError(f"Unexpected array shape: {arr.shape}")
    if arr.shape[0] < 25 < arr.shape[1]:
        return arr.transpose(1, 2, 0)
    if arr.shape[1] < 25 < arr.shape[0]:
        return arr.transpose(0, 2, 1)
    return arr

def preview_cube(cube: np.ndarray,
                 labels: Iterable[str] | None = None,
                 title: str = "") -> None:
    hwc = to_hwc(cube)
    if hwc.shape[2] >= 3:
        rgb = np.clip(hwc[..., :3] / (hwc[..., :3].max() or 1), 0, 1)
        st.image((rgb * 255).astype(np.uint8),
                 caption=f"{title}Raw RGB (bands 1–3)")
    if hwc.shape[2] >= 15:
        synth = np.clip(hwc[..., 12:15] / (hwc[..., 12:15].max() or 1), 0, 1)
        st.image((synth * 255).astype(np.uint8),
                 caption=f"{title}Synthetic RGB (bands 13–15)")
    for i in range(min(hwc.shape[2], 15)):
        band = hwc[..., i]
        img = (band / (band.max() or 1) * 255).astype(np.uint8)
        cap = labels[i] if labels and i < len(labels) else f"Band {i+1}"
        st.image(img, caption=f"{title}{cap}")

# ═════════════════════ GeoTIFF helpers (NEW) ═════════════════
def tiff_metadata(path: Path) -> dict:
    with rasterio.open(path) as ds:
        res_x, res_y = ds.res
        return {
            "Size (px)": f"{ds.width} × {ds.height}",
            "CRS": ds.crs.to_string(),
            "Bounds": tuple(round(v, 6) for v in ds.bounds),
            "Resolution": f"{res_x:.2f} × {res_y:.2f}",
            "Band count": ds.count,
            "Data type": str(ds.dtypes[0]),
        }

def show_geotiff(path: Path):
    cube = tiff.imread(path)
    st.subheader(path.name)
    preview_cube(cube)
    st.write("**GeoTIFF metadata**")
    st.json(tiff_metadata(path))

# ═════════════════════ Bulk /process helper ═════════════════
PROCESS_EU = "https://services.sentinel-hub.com/api/v1/process"
PROCESS_US = "https://services-uswest2.sentinel-hub.com/api/v1/process"

def batch_download_chips(root: Path, token: str,
                         force: bool = False) -> list[tuple[Path, str]]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    reports: list[tuple[Path, str]] = []

    for jf in sorted(root.rglob("*_request_224.json")):
        base = jf.with_suffix("")
        jsf = base.with_name(base.name.replace("_request_224", "_evalscript")).with_suffix(".js")
        if not jsf.exists():
            reports.append((jf, "⚠️ missing evalscript – skipped"))
            continue

        out_tif = base.with_name(base.name.replace("_request_224", "_result")).with_suffix(".tif")
        if out_tif.exists() and not force:
            reports.append((out_tif, "✅ already exists – skipped"))
            continue

        body = json.loads(jf.read_text(encoding="utf-8"))
        endpoint = PROCESS_US if any(
            d.get("type", "").startswith("landsat") for d in body["input"]["data"]
        ) else PROCESS_EU
        body["evalscript"] = jsf.read_text(encoding="utf-8")

        try:
            r = requests.post(endpoint, headers=headers, json=body, timeout=120)
            if r.ok:
                out_tif.write_bytes(r.content)
                reports.append((out_tif, "✅ downloaded"))
            else:
                try:
                    msg = r.json().get("error", {}).get("message") or r.text
                except ValueError:
                    msg = r.text
                reports.append((out_tif, f"❌ {msg.strip()}"))
        except Exception as exc:
            reports.append((out_tif, f"❌ {exc!s}"))

    return reports

# ═════════════════════ Param‑widget builder ═════════════════
def param_widgets(endpoint: dict, method: str):
    if not endpoint:
        return dict(query_params={}, post_body={}, path_vals={})

    if method.upper() == "POST" and "/process" in endpoint["path"]:
        st.markdown("### JSON body + Evalscript")
        up_json = st.file_uploader("JSON body", ["json"])
        if up_json:
            st.session_state["json_buf"] = up_json.read().decode()
        json_txt = st.text_area("JSON (without evalscript)",
                                st.session_state.get("json_buf", "{}"), height=240)

        up_js = st.file_uploader("Evalscript", ["js"])
        if up_js:
            st.session_state["js_buf"] = up_js.read().decode()
        js_txt = st.text_area("Evalscript",
                              st.session_state.get("js_buf", ""), height=240)

        if DBG:
            st.sidebar.code(js_txt or "// <empty script>", language="javascript")

        try:
            body = json.loads(json_txt or "{}")
        except json.JSONDecodeError as e:
            st.error(e)
            return dict(query_params={}, post_body={}, path_vals={})

        body["evalscript"] = js_txt.strip()
        return dict(query_params={}, post_body=body, path_vals={})

    swagger = st.session_state["sentinel_swagger"]
    defs = get_parameters_for_endpoint(swagger, endpoint)
    for ph in re.findall(r"{([^}]+)}", endpoint["path"]):
        if ph not in {d["name"] for d in defs}:
            defs.append({"name": ph, "in": "path", "description": "(auto)"})

    q, b, p = {}, {}, {}
    for prm in defs:
        name, loc = prm["name"], prm["in"]
        enum = get_enum_options(prm, swagger)
        if loc == "path":
            if v := st.text_input(f"[path] {name}"):
                p[name] = v
        elif loc == "query" and st.checkbox(f"query {name}"):
            v = st.selectbox(name, enum) if enum else st.text_input(name)
            if v:
                q[name] = v
        elif loc == "body" and st.checkbox(f"body {name}"):
            if v := st.text_input(name):
                b[name] = v
    return dict(query_params=q, post_body=b, path_vals=p)

# ═══════════════════ UI LAYOUT & LOGIC ═══════════════════════
st.title("🛰️ Sentinel‑Hub Semantic Connector")

# 1  OAuth
token = sh_token()
if not token:
    st.stop()
st.success("OAuth token fetched")

# 2  OpenAPI spec
spec_file = st.file_uploader("OpenAPI spec (yaml / json)", ["yaml", "yml", "json"])
if not spec_file:
    st.stop()
swagger = load_api(spec_file.read())
st.session_state["sentinel_swagger"] = swagger

# 3  Endpoint selection
method, path_tpl, endpoint = select_endpoint(swagger)
if not endpoint:
    st.stop()

# 4  Parameter widgets
params = param_widgets(endpoint, method)

# 5  Spectral‑indices root
for _root in (Path.cwd(), Path("awesome-spectral-indices-main/output")):
    if (_root / "spectral-indices-dict.json").exists() or \
       (_root / "spectral-indices-table.csv").exists():
        INDICES_ROOT = _root
        break
else:
    INDICES_ROOT = Path.cwd()

factory = SpectralIndexFactory(INDICES_ROOT)
if DBG:
    st.sidebar.write(f"Loaded {len(factory.list_indices())} spectral indices")

# ═══════════ Sidebar bulk‑download block ═══════════════════
st.sidebar.markdown("### 📦 Batch /process downloader")
root_dir_str = st.sidebar.text_input(
    "Root directory with *_request_224.json", value=str((Path.cwd() / "FL").resolve()))
force_dl = st.sidebar.checkbox("Force re‑download (overwrite)")

if st.sidebar.button("🚀 Run batch download"):
    root_dir = Path(root_dir_str)
    if not root_dir.exists():
        st.sidebar.error(f"{root_dir} does not exist")
    else:
        with st.spinner("Contacting Sentinel‑Hub…"):
            log = batch_download_chips(root_dir, token, force=force_dl)
        st.sidebar.write(f"**{len(log)} files processed "
                         f"({datetime.utcnow():%H:%M:%S} UTC)**")
        for path, msg in log:
            st.sidebar.write(f"* {path.name}: {msg}")

# ═══════════ Local chip browser (NEW) ══════════════════════
root_dir = Path(root_dir_str)
if root_dir.exists():
    tiffs = sorted(root_dir.rglob("*_result.tif"))
    if tiffs:
        sel = st.selectbox("📂 View a downloaded chip",
                           ["<choose>"] + [p.name for p in tiffs])
        if sel and sel != "<choose>":
            show_geotiff(next(p for p in tiffs if p.name == sel))

# ═══════════ Execute single request ════════════════════════
if st.button("🔍 Execute request"):
    url, raw_resp, df = execute_sentinel_query(
        swagger, method, path_tpl,
        params["query_params"], params["post_body"], params["path_vals"], token
    )
    if isinstance(raw_resp, dict) and "download_url" in raw_resp:
        show_geotiff(Path(raw_resp["download_url"]))  # NEW richer preview
        with open(raw_resp["download_url"], "rb") as fh:
            st.download_button("📥 TIFF", fh,
                               file_name=Path(raw_resp["download_url"]).name)
    elif df is not None:
        st.dataframe(df)
    elif raw_resp:
        st.json(raw_resp)

# ═══════════ Cube preview (legacy) ═════════════════════════
if "cube" in st.session_state and st.checkbox("👁️ Preview TIFF (legacy)"):
    preview_cube(st.session_state["cube"])

# ═══════════ Local spectral‑index computation ══════════════
if "cube" in st.session_state and st.checkbox("📈 Compute local index (legacy)"):
    cube = st.session_state["cube"].astype(np.float32)
    if cube.dtype == np.uint16 or cube.max() > 1.1:
        cube /= 1e4
    try:
        band_map = factory.map_s2_bands(cube)
    except ValueError as exc:
        st.warning("Not a raw Sentinel‑2 stack.\n\n"
                   f"Details: {exc}")
        band_map = None
    if band_map:
        usable = [
            nm for nm in factory.list_indices()
            if all(b in band_map for b in factory.get(nm)[1])
        ]
        if usable:
            idx = st.selectbox("Index", usable)
            func, _ = factory.get(idx)
            img = func(band_map)
            if DBG:
                st.sidebar.write({idx: dict(min=float(np.nanmin(img)),
                                            max=float(np.nanmax(img)))})
            st.image(img, clamp=True, caption=f"{idx} (local)")
        else:
            st.info("No spectral index can be computed with these bands.")
