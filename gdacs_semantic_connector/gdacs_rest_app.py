# Import necessary libraries
import os  # Provides a way to interact with the operating system, including file and directory operations
import json  # Used for encoding and decoding JSON data
import urllib.parse  # Provides utilities for parsing URLs
from io import BytesIO  # Used for managing data in bytes, particularly useful for handling binary data in memory

import streamlit as st  # A library for creating web apps with Python, used here for building the interactive interface
import pandas as pd  # Provides data structures and functions needed to manipulate structured data
import requests  # Allows sending HTTP requests easily, used here to fetch data from web APIs
import folium  # A library for visualizing geospatial data, used to create interactive maps
from rdflib import Graph, Namespace  # Used for working with RDF (Resource Description Framework) data
from rdflib.namespace import RDF, RDFS  # Provides predefined RDF and RDFS namespaces
from streamlit_folium import st_folium  # Integrates folium maps into Streamlit apps
from pandas.errors import EmptyDataError  # Exception raised when a DataFrame operation encounters empty data
from gdacs.api import EVENT_TYPES  # Imports event types from the GDACS API, used for hazard data

# Define namespaces and directories for data storage
DIS = Namespace("http://example.org/disaster#")
SUMMARY_DIR = os.path.join(os.getcwd(), "summary")
DETAILS_DIR = "gdacs_event_details"
GEOM_DIR = "gdacs_event_geometry"

# Helper function to load hazard ontology from an OWL file
@st.cache_data(show_spinner=False)
def load_hazard_ontology(file_obj):
    g = Graph()
    g.parse(file_obj)
    out = []
    for subj in g.subjects(RDF.type, DIS.GDACSHazardType):
        lbl = g.value(subj, RDFS.label)
        code = g.value(subj, DIS.gdacsCode)
        out.append({
            "label": str(lbl) if lbl else None,
            "code": str(code) if code else None
        })
    return sorted(out, key=lambda h: (h["label"] or "").lower())

# Helper function to extract longitude and latitude from geometry
def first_lon_lat(geom):
    t = geom.get("type", "")
    c = geom.get("coordinates", [])
    try:
        if t == "Point":
            return c[0], c[1]
        if t == "Polygon":
            return c[0][0][0], c[0][0][1]
        if t == "MultiPolygon":
            return c[0][0][0][0], c[0][0][0][1]
    except:
        pass
    return 0.0, 0.0

# Helper function to append new data to an existing CSV file
def append_new_csv(df_new: pd.DataFrame, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if df_new.empty:
        return
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        df_new.to_csv(path, index=False)
        return
    try:
        df_old = pd.read_csv(path)
    except (EmptyDataError, pd.errors.ParserError):
        df_new.to_csv(path, index=False)
        return
    if not {"event_type", "event_id"}.issubset(df_old.columns):
        df_new.to_csv(path, index=False)
        return
    existing = set(zip(df_old["event_type"], df_old["event_id"]))
    mask = [(et, eid) not in existing for et, eid in zip(df_new["event_type"], df_new["event_id"])]
    df_add = df_new[mask]
    if df_add.empty:
        return
    pd.concat([df_old, df_add], ignore_index=True).to_csv(path, index=False)

# Configure the Streamlit page and sidebar
st.set_page_config(page_title="GDACS Semantic Connector", layout="wide")
st.sidebar.title("🌐 GDACS Semantic Query")

# Upload an OWL file containing hazard ontology
owl_file = st.sidebar.file_uploader(
    "Upload Hazard Ontology (.owl)",
    type=["owl"],
    key="owl_upload"
)
if not owl_file:
    st.sidebar.info("Please upload an OWL file to proceed.")
    st.stop()

# Load and validate hazard types from the ontology
hazards = load_hazard_ontology(owl_file)
supported = [c for c in EVENT_TYPES if c]
valid = [h for h in hazards if h["code"] in supported]
invalid = [h for h in hazards if h["code"] not in supported]

if invalid:
    st.sidebar.warning(
        "Skipped (no GDACS code): " + ", ".join(h["label"] for h in invalid if h["label"])
    )
if not valid:
    st.sidebar.error("No valid hazards found in your ontology.")
    st.stop()

# Create a select box for hazard types and limit the number of results
labels = [h["label"] for h in valid]
sel_label = st.sidebar.selectbox("Select Hazard Type", labels, key="haz")
sel_code = next(h["code"] for h in valid if h["label"] == sel_label)
limit = st.sidebar.selectbox("Limit number of results",
                             [10, 20, 50, 100, 200, 500, 1000],
                             index=0, key="lim")

# Set up the main page title and description
st.title("🌍 GDACS Semantic Connector")
st.caption("Unofficial GDACS API explorer with ontology-driven hazard selection, detail & episode footprints.")

st.header("🗂️ Summary Events")
st.markdown("Using <https://www.gdacs.org/observatory/api/data> (unofficial)")

# Fetch GDACS events based on selected hazard type and limit
if st.sidebar.button("🔍 Fetch GDACS Events", key="fetch_sum"):
    from gdacs.api import GDACSAPIReader
    client = GDACSAPIReader()
    with st.spinner(f"Querying {sel_label} events…"):
        try:
            gj = client.latest_events(event_type=sel_code, limit=limit)
        except Exception as e:
            st.error(f"Failed to fetch: {e}")
            gj = None

    rows = []
    if gj and getattr(gj, "features", []):
        for feat in gj.features:
            p = feat.get("properties", {}) or {}
            g = feat.get("geometry", {}) or {}
            lon, lat = (None, None)
            if "coordinates" in g:
                lon, lat = g["coordinates"][:2]
            et, eid = p.get("eventtype"), p.get("eventid")
            rows.append({
                "event_type": et,
                "event_id": eid,
                "name": p.get("name"),
                "alert": p.get("alertlevel"),
                "from_date": p.get("fromdate"),
                "to_date": p.get("todate"),
                "country": p.get("country"),
                "severity": p.get("severitydata", {}).get("severity"),
                "latitude": lat,
                "longitude": lon,
                "report_url": p.get("url", {}).get("report"),
                "geometry_url": p.get("url", {}).get("geometry"),
                "detail_url": f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={et}&eventid={eid}"
            })
    else:
        st.warning("⚠️ No events returned.")
    st.session_state["summary_df"] = pd.DataFrame(rows)

# Display and persist the summary data
if "summary_df" in st.session_state:
    df = st.session_state["summary_df"]
    st.dataframe(df, use_container_width=True)

    os.makedirs(SUMMARY_DIR, exist_ok=True)
    csv_p = os.path.join(SUMMARY_DIR, "gdacs_summary.csv")
    append_new_csv(df, csv_p)

    with open(csv_p, "rb") as f:
        st.download_button("📥 Download Summary CSV",
                           data=f.read(),
                           file_name="gdacs_summary.csv",
                           mime="text/csv",
                           key="dl_csv")

    df_csv = pd.read_csv(csv_p)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as wr:
        df_csv.to_excel(wr, index=False)
    buf.seek(0)
    st.download_button("⬇️ Download Summary Excel",
                       data=buf.getvalue(),
                       file_name="gdacs_summary.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="dl_xlsx")

# Fetch and save episode-level details for each event
if "summary_df" in st.session_state:
    st.markdown("---")
    st.subheader("📋 GDACS Episode Details")

    if st.button("📥 Fetch Details for Each Event", key="fetch_det"):
        os.makedirs(DETAILS_DIR, exist_ok=True)
        detail_files = []

        for _, row in st.session_state["summary_df"].iterrows():
            et, eid = row["event_type"], row["event_id"]
            evd = os.path.join(DETAILS_DIR, f"{et}_{eid}")
            os.makedirs(evd, exist_ok=True)

            try:
                r = requests.get(row["detail_url"])
                r.raise_for_status()
                props = r.json().get("properties", {}) or {}
            except Exception as e:
                st.error(f"{et} {eid}: failed to fetch event JSON: {e}")
                continue

            for ep in props.get("episodes", []):
                det_url = ep.get("details", "")
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(det_url).query)
                epid = qs.get("episodeid", [None])[0]
                if not epid:
                    continue

                fname = os.path.join(evd, f"episode_{epid}.xlsx")
                if not os.path.exists(fname):
                    try:
                        r2 = requests.get(det_url)
                        r2.raise_for_status()
                        js = r2.json()
                        df_det = pd.json_normalize(js)
                        df_det.to_excel(fname, index=False)
                        st.success(f"Saved → {et}_{eid}/episode_{epid}.xlsx")
                    except Exception as e:
                        st.warning(f"{et} {eid} ep {epid}: failed detail fetch: {e}")
                        continue

                detail_files.append((f"{et}_{eid}", f"episode_{epid}.xlsx", fname))

        st.session_state["detail_files"] = detail_files

    if st.session_state.get("detail_files"):
        st.markdown("### 📎 Download Episode Detail Files")
        for ev_sub, fn, fp in st.session_state["detail_files"]:
            label = f"{ev_sub}/{fn}"
            with open(fp, "rb") as f:
                st.download_button(
                    label=label,
                    data=f.read(),
                    file_name=f"{ev_sub}_{fn}",
                    key=f"dl_det_{ev_sub}_{fn}"
                )

# Fetch and display episode-level geometry
if "summary_df" in st.session_state:
    st.markdown("---")
    st.subheader("⌛ Fetch & Save Episode Footprints")

    if st.button("🌐 Fetch Episodes & Geometry", key="fetch_geo"):
        os.makedirs(GEOM_DIR, exist_ok=True)
        evos = {}
        for _, row in st.session_state["summary_df"].iterrows():
            et, eid, name = row["event_type"], row["event_id"], row["name"]
            evg = os.path.join(GEOM_DIR, f"{et}_{eid}")
            os.makedirs(evg, exist_ok=True)

            try:
                r = requests.get(row["detail_url"])
                r.raise_for_status()
                eps = r.json().get("properties", {}).get("episodes", [])
            except:
                eps = []

            fps = []
            for ep in eps:
                det_url = ep.get("details", "")
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(det_url).query)
                epid = qs.get("episodeid", [None])[0]
                if not epid:
                    continue

                geom_url = (
                    f"https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
                    f"?eventtype={et}&eventid={eid}&episodeid={epid}"
                )
                try:
                    r2 = requests.get(geom_url)
                    r2.raise_for_status()
                    gj = r2.json()
                except:
                    continue

                fn = os.path.join(evg, f"episode_{epid}.geojson")
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(gj, f)

                poly = next((f for f in gj["features"]
                             if f["geometry"]["type"] in ("Polygon", "MultiPolygon")), None)
                ts = poly["properties"].get("polygondate") if poly else "N/A"
                fps.append((epid, ts, fn))

            evos[f"{et}_{eid}"] = fps
        st.success("All episode geometries fetched & saved.")
        st.session_state["evolution"] = evos

    if st.session_state.get("evolution"):
        st.markdown("---")
        st.header("📈 Evolution of Event Footprints")
        for evkey, fps in st.session_state["evolution"].items():
            st.subheader(evkey.replace("_", " "))
            for epid, ts, path in fps:
                chk = st.checkbox(f"Episode {epid} — {ts}", key=f"chk_{evkey}_{epid}")
                if not chk:
                    continue
                gj = json.load(open(path, "r", encoding="utf-8"))
                pt = next((f for f in gj["features"]
                           if f["geometry"]["type"] == "Point"), None)
                if pt:
                    lon0, lat0 = pt["geometry"]["coordinates"][:2]
                else:
                    lon0, lat0 = first_lon_lat(gj["features"][0]["geometry"])

                m = folium.Map(location=[lat0, lon0], zoom_start=6, tiles="CartoDB positron")
                folium.GeoJson(
                    gj,
                    style_function=lambda f: {
                        "fillColor": "#228B22", "color": "#222", "weight": 1, "fillOpacity": 0.6
                    }
                ).add_to(m)
                folium.CircleMarker(
                    location=(lat0, lon0),
                    radius=5, color="crimson",
                    fill=True, fill_color="crimson", fill_opacity=0.9
                ).add_to(m)
                st_folium(m, width=700, height=400)

                with open(path, "rb") as f:
                    st.download_button(
                        f"⬇️ Download GeoJSON Episode {epid}",
                        data=f.read(),
                        file_name=os.path.basename(path),
                        key=f"dl_geo_{evkey}_{epid}"
                    )
            st.markdown("—" * 20)

# Footer with additional information
st.markdown(
    "> **What do these polygons represent?**  \n"
    "> GDACS publishes an *event-footprint* layer derived from satellite and model analysis.  "
    "> • **Flood (FL)** polygons outline the estimated inundated area.  "
    "> • **Wildfire (WF)** polygons show the hot-spot / burned-area perimeter.  "
    "> • For earthquakes, polygons approximate the affected region based on shaking intensity.  "
    "> They are **not** administrative boundaries but hazard-specific footprints generated by GDACS."
)
