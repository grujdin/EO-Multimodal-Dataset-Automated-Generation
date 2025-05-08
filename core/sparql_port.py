import streamlit as st
from rdflib import Graph
from core.sparql_engine import run_query
import sys
import os

st.title("🔎 SPARQL Console with File Upload (TTL or OWL)")

# -------------------------
# Sidebar: Upload Semantic Model
# -------------------------
semantic_file = st.sidebar.file_uploader("Upload Semantic Model (.ttl or .owl)", type=["ttl", "owl"])
if semantic_file is not None:
    try:
        # Determine the file format based on its extension.
        filename = semantic_file.name
        extension = os.path.splitext(filename)[1].lower()  # e.g., ".ttl" or ".owl"
        if extension == ".ttl":
            file_format = "turtle"
        elif extension == ".owl":
            file_format = "xml"  # OWL files are typically in RDF/XML
        else:
            file_format = "turtle"  # default fallback

        uploaded_graph = Graph()
        # Read the file as raw bytes and decode assuming UTF-8.
        raw_data = semantic_file.read()
        raw_str = raw_data.decode("utf-8")
        uploaded_graph.parse(data=raw_str, format=file_format)
        st.session_state["semantic_graph"] = uploaded_graph
        st.sidebar.success(f"✅ Uploaded semantic graph with {len(uploaded_graph)} triples. (format: {file_format})")
    except Exception as e:
        st.sidebar.error(f"Failed to parse uploaded file: {e}")

# -------------------------
# Load Semantic Graph: Use uploaded file if available, else fallback to local file.
# -------------------------
graph = st.session_state.get("semantic_graph")
if graph is None:
    st.info("No semantic graph found in session. Using local TTL file as fallback...")
    local_graph = Graph()
    try:
        # Adjust this fallback file path if needed. Assuming TTL format for fallback.
        local_graph.parse("file:///<your_home_directory>/data/api_semantics_full_merged.ttl", format="turtle")
        graph = local_graph
        st.session_state["semantic_graph"] = graph
        st.write(f"✅ Fallback loaded graph with {len(graph)} triples.")
    except Exception as e:
        st.error(f"Failed to load fallback file: {e}")
else:
    st.write(f"✅ Semantic graph in session with {len(graph)} triples.")

# -------------------------
# SPARQL Query Section
# -------------------------
default_query = """
SELECT ?s ?p ?o
WHERE { ?s ?p ?o }
LIMIT 10
"""

if "sparql_query" not in st.session_state:
    st.session_state["sparql_query"] = default_query

query = st.text_area("SPARQL Query", value=st.session_state["sparql_query"], height=200)

# -------------------------
# Run Query Button with Debug Info
# -------------------------
if st.button("Run Query", key="run_sparql"):
    st.session_state["sparql_query"] = query  # Update stored query
    st.info("⏳ Executing SPARQL query...")
    st.write("🚀 'Run Query' block triggered!")
    print("Console: 'Run Query' block triggered!", flush=True)
    sys.stdout.flush()

    try:
        st.write("✅ About to run run_query(graph, query)...")
        print("Console: About to run run_query(graph, query)...", flush=True)
        sys.stdout.flush()

        result_df = run_query(graph, query)

        st.write("✅ run_query(...) returned, result_df is:", result_df)
        print("Console: SPARQL result_df:", result_df, flush=True)
        sys.stdout.flush()

        st.session_state["sparql_result"] = result_df
        st.success("✅ Query executed.")
    except Exception as e:
        st.error(f"SPARQL query failed: {e}")
        print("Console: SPARQL query failed:", e, flush=True)
        sys.stdout.flush()
        st.session_state["sparql_result"] = None

# -------------------------
# Button to Display Query Results
# -------------------------
if st.button("Show Query Results", key="show_results"):
    if "sparql_result" in st.session_state and st.session_state["sparql_result"] is not None:
        df = st.session_state["sparql_result"]
        if df.empty:
            st.info("✅ Query ran successfully, but returned no results.")
        else:
            st.write(f"Returned {len(df)} rows.")
            st.dataframe(df)
    else:
        st.info("No query results to display.")

# -------------------------
# Button to Show Full Session State Debug Info
# -------------------------
if st.button("Show Full Session State Debug", key="show_debug"):
    st.write("🪲 Full Session State Debug:", dict(st.session_state))
