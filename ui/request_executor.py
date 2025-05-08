import requests
import pandas as pd
import streamlit as st
from core.request_builder import build_request_url

def flatten_fields(fields, prefix=""):
    flat = {}
    for key, val in fields.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(val, dict):
            if set(val.keys()) == {"lat", "lon"}:
                flat[full_key] = f"POINT({val['lon']} {val['lat']})"
            else:
                flat.update(flatten_fields(val, prefix=full_key))

        elif isinstance(val, list):
            if all(isinstance(i, dict) for i in val):
                for i, item in enumerate(val):
                    sub_prefix = f"{full_key}.{i}"
                    flat.update(flatten_fields(item, prefix=sub_prefix))
            else:
                flat[full_key] = ", ".join(str(i) for i in val)

        elif isinstance(val, bool):
            flat[full_key] = str(val).lower()

        else:
            flat[full_key] = val

    return flat

def execute_request(swagger, method, path_template, query_params, post_body, path_vals):
    for k, v in path_vals.items():
        path_template = path_template.replace(f"{{{k}}}", str(v))
    url = build_request_url(swagger, path_template)

    headers = {}

    # Default ReliefWeb appname
    if "appname" not in query_params:
        query_params["appname"] = "rwint-user-2891143"

    if "Accept" in query_params:
        headers["Accept"] = query_params.pop("Accept")

    st.write("🔎 Final Request URL:", url)
    st.write("🔧 Headers:", headers)
    st.write("🔎 Query Params:", query_params)
    st.write("📦 Post Body:", post_body)

    if method == "GET":
        response = requests.get(url, params=query_params, headers=headers)
    else:
        response = requests.post(url, params=query_params, json=post_body, headers=headers)

    response.raise_for_status()
    raw_json = response.json()
    raw_items = raw_json.get("data", [])

    if isinstance(raw_items, list):
        results = []
        for item in raw_items:
            row = {
                "id": item.get("id", ""),
                "score": item.get("score", None),
                "href": item.get("href", "")
            }
            fields = item.get("fields", {})
            flat_fields = flatten_fields(fields)
            row.update(flat_fields)
            results.append(row)
        df = pd.DataFrame(results)
    else:
        df = pd.json_normalize(raw_json)

    return url, raw_json, df
