import streamlit as st
import pandas as pd
from core.semantic_model import load_ontology, extract_endpoint_fields

# ----------------------------------------------
# 🧠 This module renders a dynamic field selector
# powered by an OWL ontology
# ----------------------------------------------

# 🔄 Load the ontology (once) and extract the field mapping
# result: FIELDS_INCLUDE = {"/reports": [...], "/disasters": [...], ...}
g = load_ontology("data/api_semantics.owl")
FIELDS_INCLUDE = extract_endpoint_fields(g)

def render_field_selector(endpoint_path="/disasters"):
    """
    🧩 Renders a multiselect dropdown for fields[include][]
    for the given endpoint using the ontology as source of truth.

    Parameters:
        endpoint_path (str): API endpoint path (e.g., /reports, /disasters)

    Returns:
        List[str]: Selected fields for this endpoint
    """

    # 🎯 Get valid field names for this endpoint from the ontology
    field_options = FIELDS_INCLUDE.get(endpoint_path, [])

    # 🔽 Show UI multiselect to choose which fields to include
    selected_fields = st.multiselect(
        "Select fields to include in the API response:",
        options=field_options,
        default=[],  # no pre-selected defaults
        format_func=lambda x: x  # display as-is
    )

    return selected_fields

