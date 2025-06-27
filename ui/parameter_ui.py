"""
parameter_ui.py  –  Streamlit widgets for any OpenAPI endpoint.

Key points in this version
--------------------------
1. For every **path parameter** (e.g. `{collectionId}`) we always render a
   required text-input. The user can type `sentinel-2-l2a`, `sentinel-1-grd`,
   UUIDs, etc.

2. `/process` POST still gets a free-form JSON textarea with a sensible
   template, because that endpoint’s body is too complex for individual
   widgets.

3. Query and body parameters keep the opt-in checkbox logic from the original
   code.

The function returns a single dictionary with three keys:
    • query_params
    • post_body
    • path_vals
so `sentinel_app.py` can keep doing::

    params = render_parameter_input(...)
    url, raw_json, df = execute_sentinel_query(..., **params)
"""

import json
import re
import textwrap
import streamlit as st

from core.openapi_parser import get_parameters_for_endpoint, get_enum_options
from core.semantic_model import extract_disaster_types              # kept for future use
from core.user_defined_concepts import store_tentative_concept      # idem
from core.field_selector import render_field_selector                # idem


# ────────────────────────────────────────────────────────────
def render_parameter_input(chosen_endpoint: dict, method: str):
    """Return dict(query_params, post_body, path_vals) ready for the executor."""
    if not chosen_endpoint:
        return {"query_params": {}, "post_body": {}, "path_vals": {}}

    # ── Special case: POST /process – free-form JSON textarea ───────────
    if method.upper() == "POST" and "/process" in chosen_endpoint.get("path", ""):
        st.markdown("### 📝 Provide full JSON payload for `/process`")

        default_payload = textwrap.dedent(
            """
            {
              "input": {
                "bounds": {
                  "bbox": [13.822, 45.85, 14.559, 46.291],
                  "properties": { "crs": "http://www.opengis.net/def/crs/EPSG/0/4326" }
                },
                "data": [{
                  "type": "sentinel-2-l2a",
                  "dataFilter": {
                    "timeRange": {
                      "from": "2023-10-01T00:00:00Z",
                      "to":   "2023-12-31T00:00:00Z"
                    }
                  }
                }]
              },
              "output": {
                "responses": [{
                  "identifier": "default",
                  "format": { "type": "image/tiff" }
                }]
              },
              "evalscript": "//VERSION=3\\nfunction setup(){return{input:['B04'],output:{bands:1}};}\\nfunction evaluatePixel(s){return[s.B04];}\\n",
              "evalscriptType": "JS"
            }
            """
        ).strip()

        raw = st.text_area("Raw JSON", value=default_payload, height=400)
        try:
            body = json.loads(raw)
            if not isinstance(body.get("evalscript"), str):
                st.error("❌ 'evalscript' must be a JSON string")
                return {"query_params": {}, "post_body": {}, "path_vals": {}}
            return {"query_params": {}, "post_body": body, "path_vals": {}}
        except json.JSONDecodeError as exc:
            st.error(f"❌ Invalid JSON: {exc}")
            return {"query_params": {}, "post_body": {}, "path_vals": {}}

    # ── Generic parameter handling ──────────────────────────────────────
    swagger = st.session_state.get("sentinel_swagger") or st.session_state.get("swagger")
    param_defs = get_parameters_for_endpoint(swagger, chosen_endpoint)

    # ── If the OpenAPI spec forgot path params, auto-detect them ─────────
    placeholders = re.findall(r"{([^}]+)}", chosen_endpoint["path"])
    present_names = {p.get("name") for p in param_defs}
    for var in placeholders:
        if var not in present_names:
            param_defs.append({"name": var, "in": "path", "description": f"(auto-detected '{var}')"})
            present_names.add(var)

    query_params: dict = {}
    post_body: dict = {}
    path_vals: dict = {}

    for p in param_defs:
        name = p.get("name", "")
        location = p.get("in", "")
        description = p.get("description", "")
        enum = get_enum_options(p, swagger)

        # ── Path parameters (always required; manual text-input) ────────
        if location == "path":
            val = st.text_input(f"Path Param `{name}`", help=description)
            if val:
                path_vals[name] = val
            else:
                st.warning(f"⚠️ `{name}` is required")

        # ── Query parameters ────────────────────────────────────────────
        elif location == "query":
            if st.checkbox(f"Use `{name}`?", key=f"use_{name}_query"):
                if enum:
                    val = st.selectbox(name, enum, help=description)
                else:
                    val = st.text_input(name, help=description)
                if val:
                    query_params[name] = val

        # ── Body parameters (simple scalar) ─────────────────────────────
        elif location == "body":
            if st.checkbox(f"Use `{name}`?", key=f"use_{name}_body"):
                val = st.text_input(name, help=description)
                if val:
                    post_body[name] = val

        # (You can add more `elif location == "header": …` blocks if needed)

    return {
        "query_params": query_params,
        "post_body":   post_body,
        "path_vals":   path_vals,
    }
