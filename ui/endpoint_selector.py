import streamlit as st

def select_endpoint(swagger_spec):
    """
    Renders a dropdown of all endpoints in the given swagger_spec,
    returning (method, path, endpoint_object) for the user selection.
    """

    # 1. Gather all endpoints from swagger_spec
    paths = swagger_spec.get("paths", {})
    endpoint_list = []
    for path, methods in paths.items():
        for method, operation in methods.items():
            endpoint_list.append({
                "method": method.upper(),
                "path": path,
                "summary": operation.get("summary", ""),
                "raw": operation
            })

    # 2. If no endpoints found, warn and return None
    if not endpoint_list:
        st.warning("No endpoints found in the loaded Swagger/OpenAPI spec.")
        return None, None, None

    # 3. Create a label for each endpoint in the selectbox
    label_func = lambda e: f"{e['method']} {e['path']} – {e['summary']}"
    # 4. Render the dropdown
    selected_index = st.selectbox(
        "Choose an endpoint:",
        options=range(len(endpoint_list)),
        format_func=lambda i: label_func(endpoint_list[i]),
        key="endpoint_selectbox"
    )

    # 5. Retrieve the user's selected endpoint
    selected = endpoint_list[selected_index]
    return selected["method"], selected["path"], selected
