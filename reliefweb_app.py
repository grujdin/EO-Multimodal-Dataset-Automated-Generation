import streamlit as st

# ---- Page setup
st.set_page_config(page_title="API ReliefWebSemantic Connector", layout="wide")
st.title("🌍 API ReliefWeb Semantic Connector")

# UI imports
from ui.sidebar import render_sidebar
from ui.endpoint_selector import select_endpoint
from ui.parameter_ui import render_parameter_input
from ui.request_executor import execute_request
from ui.response_display import show_results

# ---- Sidebar UI: Load API
render_sidebar()

# ---- Load Swagger/OpenAPI spec
swagger_spec = st.session_state.get("swagger")
if not swagger_spec:
    st.warning("Please upload a Swagger (OpenAPI) description file to begin.")
    st.stop()

st.session_state["swagger_spec"] = swagger_spec

# ---- Always show the endpoint dropdown
method, path_template, chosen_endpoint = select_endpoint(swagger_spec)
st.session_state["chosen_endpoint"] = chosen_endpoint
st.session_state["method"] = method
st.session_state["path_template"] = path_template

st.write("🔎 Selected endpoint:", f"{method} {path_template}")

# ---- Render parameter input widgets based on endpoint + method
params = render_parameter_input(chosen_endpoint, method)
query_params = params.get("query_params", {})
post_body = params.get("post_body", {})
path_vals = params.get("path_vals", {})

# ---- Execute request on button press
if st.button("🚀 Execute Request"):
    url, raw_json, df = execute_request(
        swagger=swagger_spec,
        method=method,
        path_template=path_template,
        query_params=query_params,
        post_body=post_body,
        path_vals=path_vals
    )
    show_results(df, raw_json)