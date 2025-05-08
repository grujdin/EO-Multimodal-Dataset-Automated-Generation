
import streamlit as st
import os
from core.request_builder import save_dataframe_to_csv

def show_results(df, raw_json):
    if df.empty:
        st.warning("No results returned.")
        return

    st.session_state.results_df = df.copy()
    st.session_state.csv_path = save_dataframe_to_csv(df)

    st.success(f"✅ Returned {len(df)} results.")

    with st.expander("📄 Full Raw JSON (complete response)"):
        st.json(raw_json)

    st.subheader("📊 Retrieved Results")
    st.dataframe(df, use_container_width=True)

    with open(st.session_state.csv_path, "rb") as f:
        st.download_button(
            "Download CSV",
            data=f,
            file_name=os.path.basename(st.session_state.csv_path),
            mime="text/csv"
        )
