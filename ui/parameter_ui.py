import streamlit as st
from core.openapi_parser import get_parameters_for_endpoint, get_enum_options
from core.semantic_model import extract_disaster_types
from core.user_defined_concepts import store_tentative_concept
from core.field_selector import render_field_selector
import json
import textwrap

def render_parameter_input(chosen_endpoint, method):
    if not chosen_endpoint:
        return {
            "query_params": {},
            "post_body": {},
            "path_vals": {}
        }

    # Special handling for SentinelHub POST /process endpoint
    if method.upper() == "POST" and "/process" in chosen_endpoint.get("path", ""):
        st.markdown("### 📝 Provide full JSON payload for `/process`")
        default_payload = textwrap.dedent("""
        {
          "input": {
            "bounds": {
              "bbox": [13.822, 45.85, 14.559, 46.291],
              "properties": {
                "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
              }
            },
            "data": [
              {
                "type": "sentinel-2-l2a",
                "dataFilter": {
                  "timeRange": {
                    "from": "2023-10-01T00:00:00Z",
                    "to": "2023-12-31T00:00:00Z"
                  }
                }
              }
            ]
          },
          "output": {
            "responses": [
              {
                "identifier": "default",
                "format": {
                  "type": "image/tiff"
                }
              }
            ]
          },
          "evalscript": "//VERSION=3\\nfunction setup() {\\n  return {\\n    input: [\\\"B04\\\"],\\n    output: { bands: 1 }\\n  };\\n}\\nfunction evaluatePixel(sample) {\\n  return [sample.B04];\\n}",
          "evalscriptType": "JS"
        }
        """).strip()

        user_json = st.text_area("Raw JSON", value=default_payload, height=400)
        try:
            parsed = json.loads(user_json)
            if not isinstance(parsed.get("evalscript"), str):
                st.error("❌ 'evalscript' must be a plain JSON string")
                return {
                    "query_params": {},
                    "post_body": {},
                    "path_vals": {}
                }
            return {
                "query_params": {},
                "post_body": parsed,
                "path_vals": {}
            }
        except json.JSONDecodeError as e:
            st.error(f"❌ Invalid JSON: {e}")
            return {
                "query_params": {},
                "post_body": {},
                "path_vals": {}
            }

    # Standard fallback for ReliefWeb and other endpoints
    query_params, post_body, path_vals = collect_parameters(chosen_endpoint, method)
    return {
        "query_params": query_params,
        "post_body": post_body,
        "path_vals": path_vals
    }


# [collect_parameters remains unchanged below this point] ...

# [collect_parameters remains unchanged below this point] ...


def collect_parameters(chosen_endpoint, method):
    synergy_is_get = method.upper() == "GET"

    # Detect which swagger is in use
    swagger = st.session_state.get("swagger") or st.session_state.get("sentinel_swagger")
    is_reliefweb = "rwint-user" in str(swagger) if swagger else False

    query_params = {"appname": "rwint-user-2891143"} if is_reliefweb and synergy_is_get else {}
    post_body = {"appname": "rwint-user-2891143"} if is_reliefweb and not synergy_is_get else {} if not synergy_is_get else None
    path_vals = {}

    if not chosen_endpoint:
        return query_params, post_body, path_vals

    param_defs = get_parameters_for_endpoint(swagger, chosen_endpoint)
    hazard_map = extract_disaster_types(st.session_state.ontology) if st.session_state.get("ontology") else {}

    for p in param_defs:
        name = p.get("name", f"unnamed_{id(p)}")
        param_in = p.get("in", "")
        description = p.get("description", "")

        st.write(f"🔍 Checking parameter: {name}")
        st.write("🔍 Param Schema:", p.get("schema"))
        enum = get_enum_options(p, st.session_state.swagger)
        st.write("🔍 Resolved Enum:", enum)

        if name == "query[value]":
            p_label = "query[value] (original Swagger)"
            use_chk = st.checkbox(f"Use `{p_label}`?", key=f"use_{name}_{param_in}")
            if use_chk:
                if hazard_map:
                    picks = st.multiselect(p_label, sorted(hazard_map.keys()), help="Hazards from ontology")
                    if picks:
                        value = " OR ".join(picks)
                        if synergy_is_get:
                            query_params[name] = value
                        else:
                            post_body["query"] = {"value": value}
                else:
                    st.info("No hazards found in ontology. Please upload a valid OWL file.")

        elif name == "fields[include][]":
            use_chk = st.checkbox(f"Use `{name}`?", key=f"use_{name}_{param_in}")
            if use_chk:
                selected_fields = render_field_selector(chosen_endpoint.get("path", ""))
                st.session_state["selected_fields"] = selected_fields
                if selected_fields:
                    query_params[name] = selected_fields

        elif param_in == "path":
            use_chk = st.checkbox(f"Use `{name}`?", key=f"use_{name}_{param_in}")
            if use_chk:
                val = None
                if enum:
                    val = st.selectbox(f"Path Param `{name}`", enum, help=description)
                else:
                    val = st.text_input(f"Path Param `{name}`", "")
                if val:
                    path_vals[name] = val

        else:
            use_chk = st.checkbox(f"Use `{name}`?", key=f"use_{name}_{param_in}")
            val = None
            if use_chk:
                if enum:
                    val = st.selectbox(f"{name}", enum, help=description)
                else:
                    val = st.text_input(f"{name}", help=description)

                if val:
                    if synergy_is_get:
                        query_params[name] = val
                    else:
                        post_body[name] = val

    return query_params, post_body, path_vals
