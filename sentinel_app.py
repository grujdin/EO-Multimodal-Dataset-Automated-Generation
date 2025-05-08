import streamlit as st
import os
from core.openapi_parser import load_swagger
from core.sentinelhub_auth import get_sentinelhub_token
from ui.endpoint_selector import select_endpoint
from ui.parameter_ui import render_parameter_input
from core.sentinelhub_executor import execute_sentinel_query

# ---- Page setup
st.set_page_config(page_title="API SentinelHub Semantic Connector", layout="wide")

st.title("🛰️ API SentinelHub Semantic Connector")

# ---- Automatically retrieve token using environment or inline credentials
client_id = os.getenv("SENTINELHUB_CLIENT_ID", "edc4e00d-7ecb-4baf-8e33-03e90abbb504")
client_secret = os.getenv("SENTINELHUB_CLIENT_SECRET", "9OgD9zMKQtWrIw62vDCyngFTKBoyiuEI")

if not client_id or not client_secret:
    st.error("❌ SentinelHub credentials not set. Please define them in code or via environment.")
    st.stop()

token = get_sentinelhub_token(client_id, client_secret)
print("🔑 Retrieved token:", token is not None, flush=True)

if token:
    st.session_state["copernicus_token"] = token
    st.success("✅ Token retrieved successfully")
    st.code(f"Token starts with: {token[:10]}...", language='text')
else:
    st.error("❌ Failed to retrieve token")
    st.stop()

# ---- Swagger file uploader
swagger_file = st.file_uploader("SentinelHub OpenAPI (YAML or JSON)", type=["yaml", "json"])
if swagger_file:
    st.session_state.sentinel_swagger = load_swagger(swagger_file)
    st.success("✅ SentinelHub API spec loaded")

swagger = st.session_state.get("sentinel_swagger")
if not swagger:
    st.warning("Please upload the SentinelHub OpenAPI file.")
    st.stop()

# ---- Endpoint selector
method, path_template, chosen_endpoint = select_endpoint(swagger)
if not chosen_endpoint:
    st.stop()

# ---- Parameter input rendering
params = render_parameter_input(chosen_endpoint, method)
query_params = params.get("query_params", {})
post_body = params.get("post_body", {})
path_vals = params.get("path_vals", {})

# ---- Execute button
if st.button("🔍 Execute SentinelHub Request"):
    url, raw_json, df = execute_sentinel_query(
        swagger=swagger,
        method=method,
        path_template=path_template,
        query_params=query_params,
        post_body=post_body,
        path_vals=path_vals,
        token=token
    )
    if "download_url" in raw_json:
        with open(raw_json["download_url"], "rb") as f:
            st.download_button("📥 Download Image", f, file_name="sentinel_image.tiff")
    elif df is not None:
        st.success(f"✅ Query returned {len(df)} results")
        st.dataframe(df)
    elif raw_json:
        st.json(raw_json)

# ---- Debug (optional)
if "url" in locals():
    with st.expander("🧪 Debug Info"):
        st.write("URL", url)
        st.write("Method", method)
        st.write("Path", path_template)
        st.write("Query Params", query_params)
        st.write("POST Body", post_body)
        st.write("Path Params", path_vals)