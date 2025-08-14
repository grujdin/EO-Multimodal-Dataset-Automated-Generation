import streamlit as st
import numpy as np
import tifffile as tiff
from pathlib import Path
from spectral_loader import SpectralIndexFactory
from io import BytesIO
import tempfile

st.set_page_config(page_title="Local Spectral Index Calculator", layout="wide")
st.title("📊 Local Spectral Index Calculator")

# 0) Sidebar: Upload definitions file
st.sidebar.header("Configuration")
def_file = st.sidebar.file_uploader(
    "Upload spectral-indices-dict.json or .csv",
    type=["json","csv"]
)
def_root = None
if def_file:
    tmp_dir = tempfile.mkdtemp()
    def_path = Path(tmp_dir) / def_file.name
    with open(def_path, "wb") as f:
        f.write(def_file.getbuffer())
    def_root = def_path.parent
    st.sidebar.success(f"Loaded definitions: {def_file.name}")
else:
    st.sidebar.info("Please upload a definitions file (.json or .csv)")

# 1) File upload
uploaded_file = st.file_uploader("Upload Sentinel GeoTIFF cube", type=["tif","tiff"])

if uploaded_file and def_root:
    # Read uploaded bytes into TIFF array
    buf = BytesIO(uploaded_file.read())
    arr = tiff.imread(buf)

    # Ensure shape (C,H,W)
    if arr.ndim == 2:
        arr = arr[np.newaxis, ...]
    elif arr.ndim == 3 and arr.shape[2] <= 16:
        arr = arr.transpose(2, 0, 1)

    st.write(f"Loaded cube with {arr.shape[0]} bands, size {arr.shape[1]}×{arr.shape[2]}")

    # Initialize factory with uploaded definitions path
    factory = SpectralIndexFactory(def_root)

    # Try to build canonical-band map
    try:
        band_map = factory.map_s2_bands(arr)
    except ValueError as exc:
        st.warning(
            "This TIFF does not look like a raw Sentinel-2 stack "
            "— local spectral-indices are unavailable.\n\n"
            f"Details: {exc}"
        )
        band_map = None

    # If we have a valid band map, filter usable indices
    if band_map:
        usable = [
            nm for nm in factory.list_indices()
            if all(b in band_map for b in factory.get(nm)[1])
        ]
        if not usable:
            st.info(
                "No index in the library can be computed "
                "with the bands present in this TIFF."
            )
        else:
            # selecting an index immediately computes it
            idx_name = st.selectbox("Select spectral index", usable)
            if idx_name:
                func, _ = factory.get(idx_name)
                result = func(band_map)

                # normalized display
                disp = (result + 1) / 2
                disp = np.clip(disp, 0.0, 1.0)
                st.image(disp, caption=f"{idx_name} (normalized)")

                # raw result download
                out = result.astype(np.float32)
                buf_out = BytesIO()
                tiff.imwrite(buf_out, out)
                buf_out.seek(0)
                st.download_button(
                    label="Download result as TIFF",
                    data=buf_out,
                    file_name=f"{idx_name}.tif",
                    mime="image/tiff"
                )
else:
    if not def_root:
        st.info("Upload a spectral-indices definitions file to configure.")
    elif not uploaded_file:
        st.info("Upload a Sentinel GeoTIFF cube to begin.")
