import streamlit as st
from core.openapi_parser import load_swagger
from core.semantic_model import load_ontology
import os

def render_sidebar():
    st.sidebar.header("Load Description File, Ontologies & Semantic Model")

    # === Swagger Handling ===
    default_swagger_path = "C:/Users/grujd/PycharmProjects/JSTARS_2025-Version1/.venv/data/API_Definition_Files/reliefweb_openapi_31_enhanced_current.yaml"
    if "swagger" not in st.session_state and os.path.exists(default_swagger_path):
        with open(default_swagger_path, "rb") as f:
            st.session_state.swagger = load_swagger(f)

    swagger_file = st.sidebar.file_uploader("Upload Swagger/OpenAPI YAML", type=["yaml"], key="swagger_file")
    if swagger_file:
        st.session_state.swagger = load_swagger(swagger_file)

    if "swagger" in st.session_state:
        st.sidebar.success("✅ OpenAPI file loaded successfully!")

    # === Ontology Handling ===
    default_ontology_path = "C:/Users/grujd/PycharmProjects/JSTARS_2025-Version1/.venv/data/query_value_with_hazards.owl"
    if "ontology" not in st.session_state and os.path.exists(default_ontology_path):
        with open(default_ontology_path, "rb") as f:
            st.session_state.ontology = load_ontology(f)

    ontology_file = st.sidebar.file_uploader("Upload Ontology (.owl or .rdf)", type=["owl", "rdf"], key="ontology_file")
    if ontology_file:
        st.session_state.ontology = load_ontology(ontology_file)

    if "ontology" in st.session_state:
        st.sidebar.success("✅ Ontology file loaded successfully!")
