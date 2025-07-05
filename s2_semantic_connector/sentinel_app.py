# sentinel_app.py – “no-wrapper” edition with detailed developer comments
# ════════════════════════════════════════════════════════════════════════

from __future__ import annotations  # Enable postponed evaluation of annotations (PEP 563)

# Standard library imports
import io       # For in-memory byte streams when parsing uploaded API specs
import json     # For JSON serialization/deserialization
import re       # For regular expression operations (parameter placeholder detection)
from pathlib import Path  # For filesystem path manipulations
from typing import Iterable  # For type hinting iterables of labels

# Third-party imports
import numpy as np           # Numerical operations and array manipulation
import streamlit as st       # Streamlit for building the web UI
import tifffile as tiff      # TIFF file reading (Sentinel data cubes)
import yaml                  # YAML parsing for API spec fallback
from oauthlib.oauth2 import BackendApplicationClient  # OAuth2 client credentials flow
from requests_oauthlib import OAuth2Session          # OAuth2 session management
from sentinelhub import SHConfig                     # Sentinel Hub configuration helper

# Project-specific imports
from core.openapi_parser import load_swagger, get_parameters_for_endpoint, get_enum_options
#   * load_swagger: parse OpenAPI spec into internal dict
#   * get_parameters_for_endpoint: retrieve param definitions for a given endpoint
#   * get_enum_options: extract enum choices for parameter value widgets
from ui.endpoint_selector import select_endpoint  # UI widget to pick API endpoint and HTTP method
from core.sentinelhub_executor import execute_sentinel_query  # Function to execute API calls
from spectral_loader import SpectralIndexFactory  # Build and compute spectral indices locally

# ── Streamlit page configuration ───────────────────────────────────
st.set_page_config("SH Semantic Connector", layout="wide")

# Debug toggle in sidebar: show internal details if needed
DBG = st.sidebar.checkbox("🪲 debug mode", value=False)

# ═════════════════════════════ OAuth helper ════════════════════════════
def sh_token() -> str | None:
    """
    Acquire OAuth2 access token for Sentinel Hub API using client credentials.
    Returns the token string, or None on failure.
    """
    cfg = SHConfig()  # Load client_id and client_secret from env or config file
    # Ensure credentials are available
    if not (cfg.sh_client_id and cfg.sh_client_secret):
        st.error("Set SH_CLIENT_ID / SH_CLIENT_SECRET (env vars or ~/.config/sentinelhub)")
        return None
    try:
        # Set up OAuth2 session using client credentials grant
        sess = OAuth2Session(client=BackendApplicationClient(cfg.sh_client_id))
        tok = sess.fetch_token(
            "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token",
            client_id=cfg.sh_client_id,
            client_secret=cfg.sh_client_secret,
            include_client_id=True,
        )
        return tok["access_token"]
    except Exception as exc:
        # Display exception details in UI
        st.exception(exc)
        return None

# ═══════════════════════════ OpenAPI cache loader ══════════════════════
@st.cache_data(show_spinner=False)
def load_api(buf: bytes):
    """
    Attempt to parse uploaded API spec bytes as YAML or JSON.
    Caches result to avoid re-parsing on every rerun.
    """
    # Try multiple parsing strategies in order of preference
    for fn in (
        lambda b: load_swagger(io.BytesIO(b)),      # Custom Swagger loader
        lambda b: json.loads(b.decode()),           # JSON parser
        lambda b: yaml.safe_load(b.decode()),       # YAML parser
    ):
        try:
            return fn(buf)
        except Exception:
            continue
    # If all parsing attempts fail, raise a RuntimeError
    raise RuntimeError("Cannot parse supplied API spec")

# ═══════════════════════════ NumPy helpers ══════════════════════
def to_hwc(arr: np.ndarray) -> np.ndarray:
    """
    Normalize a hyperspectral cube array to H x W x C format regardless of input orientation.
    Supports (H,W), (H,C,W), (C,H,W), or already (H,W,C).
    """
    if arr.ndim == 2:
        # Single-band grayscale image: expand channel dimension
        return arr[..., None]
    if arr.ndim != 3:
        # Unexpected array shape
        raise ValueError(f"Unexpected array shape: {arr.shape}")
    # Detect C x H x W ordering if first dim small and second dim large
    if arr.shape[0] < 25 and arr.shape[1] > 25:
        return arr.transpose(1, 2, 0)
    # Detect H x C x W ordering if second dim small
    if arr.shape[1] < 25 and arr.shape[0] > 25:
        return arr.transpose(0, 2, 1)
    # Otherwise assume already H x W x C
    return arr


def preview_cube(cube: np.ndarray,
                 labels: Iterable[str] | None = None,
                 title: str = "") -> None:
    """
    Display thumbnail previews of a hyperspectral cube in the Streamlit app:
      1) Raw RGB (bands 1–3)
      2) Synthetic RGB (bands 13–15), if available
      3) Individual band grayscale thumbnails (up to 15 bands)
    """
    hwc = to_hwc(cube)
    # 1) Raw RGB (first three bands)
    if hwc.shape[2] >= 3:
        # Normalize to [0,1] then scale to 0–255
        rgb = np.clip(hwc[..., :3] / (hwc[..., :3].max() or 1), 0, 1)
        st.image((rgb * 255).astype(np.uint8), caption=f"{title}Raw RGB (bands 1–3)")

    # 2) Synthetic RGB from bands 13–15 (if hyperspectral)
    if hwc.shape[2] >= 15:
        synth = np.clip(hwc[..., 12:15] / (hwc[..., 12:15].max() or 1), 0, 1)
        st.image((synth * 255).astype(np.uint8),
                 caption=f"{title}Synthetic RGB (bands 13–15)")

    # 3) Show up to the first 15 individual band thumbnails
    for i in range(min(hwc.shape[2], 15)):
        band = hwc[..., i]
        img = (band / (band.max() or 1) * 255).astype(np.uint8)
        # Use provided labels or default to 'Band {i+1}'
        cap = labels[i] if labels and i < len(labels) else f"Band {i+1}"
        st.image(img, caption=f"{title}{cap}")

# ═════════════════════ Parameter-widget builder ═════════════════
def param_widgets(endpoint: dict, method: str):
    """
    Dynamically construct Streamlit input widgets for
    path, query, and body parameters of the selected API endpoint.
    Returns a dict with keys: query_params, post_body, path_vals.
    """
    if not endpoint:
        return dict(query_params={}, post_body={}, path_vals={})

    # SPECIAL CASE: POST /process uses raw JSON+Evalscript upload
    if method.upper() == "POST" and "/process" in endpoint["path"]:
        st.markdown("### JSON body + Evalscript")

        # Allow uploading a JSON body file
        up_json = st.file_uploader("JSON body", ["json"])
        if up_json:
            # Store uploaded buffer in session state for persistence
            st.session_state["json_buf"] = up_json.read().decode()
        # Text area for JSON input (pre-populated from session state)
        json_txt = st.text_area("JSON (without evalscript)",
                                st.session_state.get("json_buf", "{}"), height=240)

        # File uploader and text area for uploading/editing the JS evalscript
        up_js = st.file_uploader("Evalscript", ["js"])
        if up_js:
            st.session_state["js_buf"] = up_js.read().decode()
        js_txt = st.text_area("Evalscript", st.session_state.get("js_buf", ""), height=240)

        # Show raw JS in sidebar if in debug mode
        if DBG:
            st.sidebar.code(js_txt or "// <empty script>", language="javascript")

        # Parse JSON body; report errors immediately
        try:
            body = json.loads(json_txt or "{}")
        except json.JSONDecodeError as e:
            st.error(e)
            return dict(query_params={}, post_body={}, path_vals={})

        # Send the exact script without any Streamlit wrapper
        body.update(evalscript=js_txt.strip(), evalscriptType="JS")
        return dict(query_params={}, post_body=body, path_vals={})

    # GENERIC CASE: build widgets from OpenAPI parameter definitions
    swagger = st.session_state["sentinel_swagger"]
    defs = get_parameters_for_endpoint(swagger, endpoint)

    # Ensure any path placeholders not in the spec still get a widget
    for ph in re.findall(r"{([^}]+)}", endpoint["path"]):
        if ph not in {d["name"] for d in defs}:
            defs.append({"name": ph, "in": "path", "description": "(auto)"})

    # Prepare containers for values
    q, b, p = {}, {}, {}
    for prm in defs:
        name, loc = prm["name"], prm["in"]
        enum = get_enum_options(prm, swagger)

        if loc == "path":
            # Always show text input for path parameters
            if v := st.text_input(f"[path] {name}"):
                p[name] = v
        elif loc == "query" and st.checkbox(f"query {name}"):
            # Optional query param: toggle and then input/select
            v = st.selectbox(name, enum) if enum else st.text_input(name)
            if v:
                q[name] = v
        elif loc == "body" and st.checkbox(f"body {name}"):
            if v := st.text_input(name):
                b[name] = v

    return dict(query_params=q, post_body=b, path_vals=p)

# ═════════════════════════════════ UI LAYOUT & LOGIC ═══════════════════════════

st.title("🛰️ Sentinel-Hub Semantic Connector")  # Main app title

# 1) Fetch OAuth token
token = sh_token()
if not token:
    # Stop execution if authentication fails
    st.stop()
st.success("OAuth token fetched")

# 2) Upload and parse OpenAPI spec
spec_file = st.file_uploader("OpenAPI spec (yaml / json)", ["yaml", "yml", "json"])
if not spec_file:
    st.stop()

swagger = load_api(spec_file.read())
# Cache the parsed spec in session state for reuse
st.session_state["sentinel_swagger"] = swagger

# 3) Let user select endpoint and HTTP method
method, path_tpl, endpoint = select_endpoint(swagger)
if not endpoint:
    st.stop()

# 4) Build parameter widgets for the selected endpoint
params = param_widgets(endpoint, method)

# ── Locate the awesome-spectral-indices data root ────────────────────
for _root in (Path.cwd(), Path("awesome-spectral-indices-main/output")):
    if (_root / "spectral-indices-dict.json").exists() or \
       (_root / "spectral-indices-table.csv").exists():
        INDICES_ROOT = _root
        break
else:
    # Default to current working directory if not found
    INDICES_ROOT = Path.cwd()

# Initialize spectral index factory for local computations
factory = SpectralIndexFactory(INDICES_ROOT)
if DBG:
    st.sidebar.write(f"Loaded {len(factory.list_indices())} spectral indices")

# ═════════════════ Execute request and handle response ═══════════════════
if st.button("🔍 Execute request"):
    # Execute the API call using the helper function
    url, raw_resp, df = execute_sentinel_query(
        swagger, method, path_tpl,
        params["query_params"], params["post_body"], params["path_vals"], token
    )

    # 1) If response is a dict with a download URL, assume it's a data cube
    if isinstance(raw_resp, dict) and "download_url" in raw_resp:
        cube = tiff.imread(raw_resp["download_url"])
        if DBG:
            # Show cube metadata in sidebar if debugging
            st.sidebar.write(dict(shape=cube.shape, dtype=str(cube.dtype),
                                  min=int(cube.min()), max=int(cube.max())))
        # Store cube in session state for later preview/indexing
        st.session_state["cube"] = cube

        # Provide a download button for the raw TIFF
        with open(raw_resp["download_url"], "rb") as fh:
            st.download_button("📥 TIFF", fh,
                               file_name=Path(raw_resp["download_url"]).name)

    # 2) If a DataFrame was returned, display it interactively
    elif df is not None:
        st.dataframe(df)
    # 3) Otherwise, show raw JSON response
    elif raw_resp:
        st.json(raw_resp)

# ═════════════════════ Cube preview section ═══════════════════════════─
if "cube" in st.session_state and st.checkbox("👁️ Preview TIFF"):
    # Display RGB and individual band previews
    preview_cube(st.session_state["cube"])

# ═════════════════ Local spectral-index computation ═══════════════════
if "cube" in st.session_state and st.checkbox("📈 Compute local index"):
    cube = st.session_state["cube"].astype(np.float32)
    # Convert raw digital numbers to reflectance if needed
    if cube.dtype == np.uint16 or cube.max() > 1.1:
        cube /= 1e4  # Sentinel-2 reflectance scaling factor

    # Attempt to map cube bands to Sentinel-2 canonical band names
    try:
        band_map = factory.map_s2_bands(cube)
    except ValueError as exc:
        # Warn user if the cube is not a standard Sentinel-2 stack
        st.warning(
            "This TIFF does not look like a raw Sentinel-2 stack "
            "— local spectral-indices are unavailable.\n\n"
            f"Details: {exc}"
        )
        band_map = None

    if band_map:
        # Filter indices to those that can be computed with available bands
        usable = [
            nm for nm in factory.list_indices()
            if all(b in band_map for b in factory.get(nm)[1])
        ]
        if not usable:
            st.info("No index in the library can be computed "
                    "with the bands present in this TIFF.")
        else:
            # Allow user to select and compute one spectral index locally
            idx = st.selectbox("Index", usable)
            func, _ = factory.get(idx)
            img = func(band_map)
            if DBG:
                # Show computed index stats in sidebar
                st.sidebar.write({idx: dict(
                    min=float(np.nanmin(img)), max=float(np.nanmax(img))
                )})
            st.image(img, clamp=True, caption=f"{idx} (local)")

