"""
Streamlit » API SentinelHub Semantic Connector
---------------------------------------------
A minimal GUI that:
1. Retrieves an OAuth token (via sentinelhub-py config).
2. Lets the user upload an OpenAPI (Swagger) spec in YAML or JSON.
3. Renders endpoint + parameter widgets.
4. Executes the chosen request and displays / downloads results.
"""

import io
import json
import yaml
import streamlit as st
from sentinelhub import SHConfig

# ── Internal modules (your package) ─────────────────────────────────────────
from core.openapi_parser import load_swagger
from core.sentinelhub_auth import get_sentinelhub_token
from ui.endpoint_selector import select_endpoint
from ui.parameter_ui import render_parameter_input
from core.sentinelhub_executor import execute_sentinel_query

# ────────────────────────────────────────────────────────────────────────────
# Page setup
# ────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="API SentinelHub Semantic Connector", layout="wide")
st.title("🛰️ API SentinelHub Semantic Connector")

# ────────────────────────────────────────────────────────────────────────────
# Authentication (sentinelhub-py config or env vars)
# ────────────────────────────────────────────────────────────────────────────
config = SHConfig()

if not config.sh_client_id or not config.sh_client_secret:
    st.error(
        "❌ SentinelHub credentials not configured.\n\n"
        "Add them to `~/.config/sentinelhub/config.toml` or set the "
        "`SH_CLIENT_ID` and `SH_CLIENT_SECRET` environment variables."
    )
    st.stop()

token = get_sentinelhub_token(config.sh_client_id, config.sh_client_secret)

if token:
    st.session_state["copernicus_token"] = token
    st.success("✅ Token retrieved successfully")
    st.code(f"Token starts with: {token[:10]}…", language="text")
else:
    st.error("❌ Failed to retrieve token")
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
# Helper: robust Swagger loader with caching
# ────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_api_spec(file_bytes: bytes, file_name: str):
    """
    Return a dict representing the OpenAPI spec.
    Strategy:
      1. Try the project helper `load_swagger` (may expect BytesIO or str).
      2. If that fails, attempt `json.loads`.
      3. Fallback to `yaml.safe_load`.
    Raises the *last* exception if all parsing attempts fail.
    """
    errors = []

    # 1. Project-specific helper
    try:
        return load_swagger(io.BytesIO(file_bytes))
    except Exception as e:
        errors.append(("load_swagger", e))

    # 2. JSON
    try:
        return json.loads(file_bytes.decode("utf-8"))
    except Exception as e:
        errors.append(("json", e))

    # 3. YAML
    try:
        return yaml.safe_load(file_bytes.decode("utf-8"))
    except Exception as e:
        errors.append(("yaml", e))

    # Nothing worked → raise the most relevant exception (helper one)
    raise RuntimeError(
        "All parsing strategies failed:\n"
        + "\n".join(f"• {src}: {err}" for src, err in errors)
    ) from errors[0][1]

# ────────────────────────────────────────────────────────────────────────────
# Swagger file uploader
# ────────────────────────────────────────────────────────────────────────────
swagger_file = st.file_uploader(
    "SentinelHub OpenAPI definition (YAML or JSON)",
    type=["yaml", "yml", "json"]
)

if swagger_file is None:
    st.info("👈 Upload an OpenAPI spec to continue.")
    st.stop()

# Read bytes once
file_bytes = swagger_file.read()
swagger_file.seek(0)  # rewind so other code can re-read if required

try:
    cache_key = (swagger_file.name, swagger_file.size)
    st.session_state["sentinel_swagger"] = _load_api_spec(file_bytes, cache_key)
    st.success("✅ SentinelHub API spec loaded")
except Exception as e:
    st.exception(e)          # Shows full traceback in UI
    st.stop()

swagger = st.session_state["sentinel_swagger"]

# ────────────────────────────────────────────────────────────────────────────
# Endpoint selector
# ────────────────────────────────────────────────────────────────────────────
method, path_template, chosen_endpoint = select_endpoint(swagger)
if not chosen_endpoint:
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
# Parameter input
# ────────────────────────────────────────────────────────────────────────────
params = render_parameter_input(chosen_endpoint, method)
query_params = params.get("query_params", {})
post_body    = params.get("post_body", {})
path_vals    = params.get("path_vals", {})

# ────────────────────────────────────────────────────────────────────────────
# Execute button
# ────────────────────────────────────────────────────────────────────────────
if st.button("🔍 Execute SentinelHub Request"):
    url, raw_json, df = execute_sentinel_query(
        swagger       = swagger,
        method        = method,
        path_template = path_template,
        query_params  = query_params,
        post_body     = post_body,
        path_vals     = path_vals,
        token         = token,
    )

    # Save debug info
    st.session_state["last_request"] = {
        "url": url,
        "method": method,
        "path": path_template,
        "query": query_params,
        "body": post_body,
        "path_vals": path_vals
    }

    # Handle different response types
    if raw_json and isinstance(raw_json, dict) and "download_url" in raw_json:
        with open(raw_json["download_url"], "rb") as f:
            st.download_button("📥 Download Image", f, file_name="sentinel_image.tiff")
    elif df is not None:
        st.success(f"✅ Query returned {len(df)} results")
        st.dataframe(df)
    elif raw_json:
        st.json(raw_json)
    else:
        st.info("ℹ️ Empty response (204 No Content?)")

# ────────────────────────────────────────────────────────────────────────────
# Debug expander (optional)
# ────────────────────────────────────────────────────────────────────────────
if "last_request" in st.session_state:
    req = st.session_state["last_request"]
    with st.expander("🧪 Debug Info"):
        st.write("URL", req["url"])
        st.write("Method", req["method"])
        st.write("Path", req["path"])
        st.write("Query Params", req["query"])
        st.write("POST Body", req["body"])
        st.write("Path Params", req["path_vals"])
