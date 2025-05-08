import streamlit as st
from semantic_inference import SemanticGoal
from core.reasoning_engine import ReasoningEngine

st.set_page_config(page_title="🌐 Semantic UI - Objective Gateway", layout="wide")
st.title("🎯 Central Semantic Objective Console")

# Step 1: Enter high-level objective
goal_text = st.text_input("📝 Describe your objective in natural language", "Generate a multimodal dataset to train a deep learning model to detect wildfires.")

if goal_text:
    goal = SemanticGoal(goal_text)
    st.success("✅ Semantic frame generated")

    with st.expander("📌 RDF Frame"):
        st.code(goal.serialize(), language="turtle")

    st.markdown("---")
    st.markdown("### 🔍 Inferred API Requirements (from ontology)")

    engine = ReasoningEngine()
    apis = engine.get_required_apis_for_task("http://example.org/objectives#DatasetGenerationTask")

    if apis:
        for uri, label in apis:
            st.write(f"- {label or uri}")
    else:
        st.warning("No API suggestions inferred from ontology.")

    st.markdown("---")
    st.markdown("### 🛰 Modalities for Multimodal Dataset")
    modalities = engine.get_modalities_for_dataset("http://example.org/objectives#MultimodalDataset")
    for uri, label in modalities:
        st.write(f"- {label or uri}")

    st.markdown("---")
    st.markdown("✅ Placeholder: dispatching this semantic goal to the API orchestration layer")
