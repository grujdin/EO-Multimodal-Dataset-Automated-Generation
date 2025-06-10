import streamlit as st                     # Streamlit for building interactive UI
import pandas as pd                        # pandas for DataFrame handling and export
import os                                  # os for filesystem operations (dirs, paths)
import requests                            # requests for HTTP API calls
import json                                # json for parsing GeoJSON & payloads
import pydeck as pdk                       # pydeck for interactive map rendering
from rdflib import Graph, Namespace        # rdflib for parsing OWL/RDF graphs
from rdflib.namespace import RDF, RDFS     # Standard RDF vocabularies
from gdacs.api import EVENT_TYPES         # Valid GDACS event_type codes :contentReference[oaicite:2]{index=2}

# --------------------------------------------------
# Define the namespace used in your OWL file.
# The file binds ':' to 'http://example.org/disaster#',
# so gdacsCode and GDACSHazardType live there.
# --------------------------------------------------
DIS = Namespace("http://example.org/disaster#")


# --------------------------------------------------
# Helper: parse the OWL and extract GDACS‐specific hazards
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def load_hazard_ontology(file_obj):
    """
    Parse the uploaded OWL file and return a list of dicts:
      [ { "uri": str, "label": str, "code": str or None }, ... ]
    for each subject typed as DIS.GDACSHazardType.
    Caches the result to avoid re-parsing on every interaction.
    """
    g = Graph()
    g.parse(file_obj)  # Load RDF/XML from the uploaded file

    hazards = []
    # Find all classes of type DIS.GDACSHazardType in the graph
    for subj in g.subjects(RDF.type, DIS.GDACSHazardType):
        label_literal = g.value(subj, RDFS.label)     # rdfs:label for display
        code_literal  = g.value(subj, DIS.gdacsCode)  # custom annotation for GDACS code
        hazards.append({
            "uri":   str(subj),
            "label": str(label_literal) if label_literal else None,
            # str(code) if present, else None
            "code":  str(code_literal) if code_literal else None
        })

    # Sort alphabetically by the human-readable label
    return sorted(hazards, key=lambda h: (h["label"] or ""))


# --------------------------------------------------
# Small util: get a rough "centroid" from first coordinate in a geometry
# --------------------------------------------------
def first_lon_lat(geom):
    """
    Return a (lon, lat) tuple from the first coordinate found
    in a GeoJSON geometry dict. Supports Polygon, MultiPolygon, Point.
    Returns (0, 0) on any error.
    """
    try:
        t = geom.get("type")
        coords = geom.get("coordinates", [])
        if t == "Polygon":
            # exterior ring first point
            return coords[0][0][0:2]
        if t == "MultiPolygon":
            # first polygon's exterior ring first point
            return coords[0][0][0][0:2]
        if t == "Point":
            # direct point coords
            return coords[0:2]
    except Exception:
        pass
    return 0, 0


# --------------------------------------------------
# Sidebar: upload ontology, select hazard, show codes
# --------------------------------------------------
st.set_page_config(page_title="GDACS Semantic Connector", layout="wide")
st.sidebar.title("🌐 GDACS Semantic Query")

# 1. Ontology uploader
owl_file = st.sidebar.file_uploader(
    "Upload Hazard Ontology (.owl)",
    type=["owl"],
    key="hazard_ontology"
)
if not owl_file:
    st.stop()  # Pause UI until user uploads an OWL file

# 2. Parse ontology to extract (label, code)
hazards_all = load_hazard_ontology(owl_file)

# 3. Inform user of supported GDACS codes
supported = [c for c in EVENT_TYPES if c]  # drop None
st.sidebar.info(f"Supported GDACS codes: {', '.join(supported)}")

# 4. Partition hazards into valid/invalid based on code
valid   = [h for h in hazards_all if h["code"] in supported]
invalid = [h for h in hazards_all if h["code"] not in supported]

if invalid:
    st.sidebar.warning(
        "These ontology hazards have no valid GDACS code and will be skipped: "
        + ", ".join(h["label"] for h in invalid if h["label"])
    )

if not valid:
    st.sidebar.error("No valid hazards found in your ontology.")
    st.stop()

# 5. Build dropdown from valid hazards
labels    = [h["label"] for h in valid]
sel_label = st.sidebar.selectbox("Select Hazard Type", labels)
# Lookup the matching code for the selected label
sel_code  = next(h["code"] for h in valid if h["label"] == sel_label)

# 6. Limit selector for number of summary events
limit = st.sidebar.selectbox(
    "Limit number of results",
    [10, 20, 50, 100, 200, 500, 1000],
    index=0
)


# --------------------------------------------------
# Main: Summary of GDACS events
# --------------------------------------------------
st.title("GDACS Semantic Connector")
st.caption(
    "Unofficial GDACS API explorer with ontology-driven hazard "
    "selection, detail & geometry fetch plus quick map preview."
)

st.header("🗂️ Summary Events")
st.markdown("Using <https://www.gdacs.org/observatory/api/data> (unofficial)")

# Button to trigger fetching summary events
if st.sidebar.button("🔍 Fetch GDACS Events"):
    from gdacs.api import GDACSAPIReader
    client = GDACSAPIReader()

    with st.spinner(f"Querying latest GDACS events for {sel_label} …"):
        try:
            # Fetch GeoJSON summary with selected code & limit
            geojson = client.latest_events(event_type=sel_code, limit=limit)
        except Exception as err:
            st.error(f"❌ Failed to fetch GDACS events: {err}")
            geojson = []

    # Transform features into row dicts
    rows = []
    for feat in getattr(geojson, "features", []):
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})
        lon, lat = (None, None)
        if geom.get("coordinates"):
            lon, lat = geom["coordinates"][0:2]

        etype = props.get("eventtype")
        eid   = props.get("eventid")
        rows.append({
            "event_type":   etype,
            "event_id":     eid,
            "name":         props.get("name"),
            "alert_level":  props.get("alertlevel"),
            "from_date":    props.get("fromdate"),
            "to_date":      props.get("todate"),
            "country":      props.get("country"),
            "severity":     props.get("severitydata", {}).get("severity"),
            "latitude":     lat,
            "longitude":    lon,
            "report_url":   props.get("url", {}).get("report"),
            "geometry_url": props.get("url", {}).get("geometry"),
            # Pre-built detail endpoint for Sendai data
            "detail_url": (
                f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?"
                f"eventtype={etype}&eventid={eid}"
            ),
        })

    if not rows:
        st.warning("⚠️ No events returned.")
    else:
        # Display DataFrame, save to session_state, and offer downloads
        df = pd.DataFrame(rows)
        st.session_state["summary_df"] = df
        st.dataframe(df, use_container_width=True)

        df.to_excel("gdacs_hazards.xlsx", index=False)
        st.download_button(
            "🗕️ Download Events CSV",
            df.to_csv(index=False),
            file_name="gdacs_hazards.csv"
        )
        st.success("✅ Summary saved to gdacs_hazards.xlsx")


# --------------------------------------------------
# Details fetch section
# --------------------------------------------------
if "summary_df" in st.session_state:
    st.markdown("---")
    st.subheader("📋 GDACS Event Details")

    if st.button("📥 Fetch Details for Each Event"):
        details_dir = "gdacs_event_details"
        os.makedirs(details_dir, exist_ok=True)
        links = []

        for _, row in st.session_state["summary_df"].iterrows():
            url   = row["detail_url"]
            etype = row["event_type"]
            eid   = row["event_id"]
            try:
                resp = requests.get(url)
                resp.raise_for_status()
                js   = resp.json()
                sendai = js.get("properties", {}).get("sendai", [])
                if not sendai:
                    st.warning(f"⚠️ No 'sendai' data for {etype} {eid}")
                    continue

                det_df = pd.json_normalize(sendai)
                name = f"{etype}_{eid}_details.xlsx"
                path = os.path.join(details_dir, name)
                det_df.to_excel(path, index=False)
                links.append((name, path))
                st.success(f"✅ Saved details → {name}")
            except Exception as e:
                st.error(f"❌ Failed detail for {etype} {eid}: {e}")

        if links:
            st.session_state["detail_files"] = links

    # Download buttons for detail files
    if st.session_state.get("detail_files"):
        st.markdown("### 📎 Download Detailed Files")
        for name, path in st.session_state["detail_files"]:
            with open(path, "rb") as f:
                st.download_button(f"⬇️ {name}", f.read(), file_name=name)


# --------------------------------------------------
# Geometry fetch & map preview per event
# --------------------------------------------------
if "summary_df" in st.session_state:
    st.markdown("---")
    st.subheader("🗺️ GDACS Event Geometry (polygons)")

    if st.button("🌐 Fetch Geometry for Each Event"):
        geom_dir = "gdacs_event_geometry"
        os.makedirs(geom_dir, exist_ok=True)
        g_links, g_objs = [], []

        for _, row in st.session_state["summary_df"].iterrows():
            url   = row.get("geometry_url")
            etype = row["event_type"]
            eid   = row["event_id"]
            if not url:
                st.warning(f"⚠️ No geometry URL for {etype} {eid}")
                continue
            try:
                r = requests.get(url); r.raise_for_status()
                txt = r.text
                obj = json.loads(txt)
                name = f"{etype}_{eid}_geometry.geojson"
                path = os.path.join(geom_dir, name)
                with open(path, "w", encoding="utf-8") as gf:
                    gf.write(txt)
                g_links.append((name, path))
                g_objs.append({"meta": row.to_dict(), "geojson": obj})
                st.success(f"✅ Saved geometry → {name}")
            except Exception as ge:
                st.error(f"❌ Failed geometry for {etype} {eid}: {ge}")

        if g_links:    st.session_state["geom_files"]   = g_links
        if g_objs:     st.session_state["geom_objects"] = g_objs

    # Download buttons for GeoJSON files
    if st.session_state.get("geom_files"):
        st.markdown("### 📎 Download Geometry Files")
        for name, path in st.session_state["geom_files"]:
            with open(path, "rb") as f:
                st.download_button(f"⬇️ {name}", f.read(), file_name=name)

    # Interactive per-event map previews
    if st.session_state.get("geom_objects"):
        # RGBA colors by alert level
        alert_col = {
            "RED":    [220,  20,  60, 80],
            "ORANGE": [255, 140,   0, 80],
            "GREEN":  [ 34, 139,  34, 80],
        }

        st.markdown("### 🗺️ Per-Event Map Preview")
        for entry in st.session_state["geom_objects"]:
            meta = entry["meta"]
            gj   = entry["geojson"]

            # Wrap single feature in FeatureCollection if needed
            if gj.get("type") != "FeatureCollection":
                gj = {"type": "FeatureCollection", "features": [gj]}

            # Color each polygon by its alert level
            for feat in gj["features"]:
                lvl = str(feat.get("properties", {}).get("alertlevel", "GREEN")).upper()
                feat.setdefault("properties", {})["_fill"] = alert_col.get(lvl, [128,128,128,80])

            lon0, lat0 = first_lon_lat(gj["features"][0]["geometry"])

            layer = pdk.Layer(
                "GeoJsonLayer", gj,
                stroked=True, filled=True, extruded=False,
                get_fill_color="properties._fill",
                get_line_color=[60,60,60],
                line_width_min_pixels=1,
            )
            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=pdk.ViewState(latitude=lat0, longitude=lon0, zoom=6),
                tooltip={"html": "<b>{properties.name}</b><br>Alert: {properties.alertlevel}"}
            )

            with st.expander(f"🗺️ {meta['event_type']} {meta['event_id']} – {meta['name']}"):
                st.pydeck_chart(deck, use_container_width=True)

        # Legend HTML for color codes
        legend = """
        <div style='font-size:0.875rem;'>
          <b>Legend</b><br>
          <span style='background:#DC143C;width:12px;height:12px;display:inline-block;border:1px solid #333'></span>&nbsp;Red alert<br>
          <span style='background:#FF8C00;width:12px;height:12px;display:inline-block;border:1px solid #333'></span>&nbsp;Orange alert<br>
          <span style='background:#228B22;width:12px;height:12px;display:inline-block;border:1px solid #333'></span>&nbsp;Green alert<br>
        </div>
        """
        st.markdown(legend, unsafe_allow_html=True)

# --------------------------------------------------
# Footer: explain what the GDACS polygons represent
# --------------------------------------------------
st.markdown(
    "> **What do these polygons represent?**  \n"
    "> GDACS publishes an *event-footprint* layer derived from satellite and model analysis.  "
    "> • **Flood (FL)** polygons outline the estimated inundated area.  "
    "> • **Wildfire (WF)** polygons show the hot-spot / burned-area perimeter.  "
    "> • For earthquakes, polygons approximate the affected region based on shaking intensity.  "
    "> They are **not** administrative boundaries but hazard-specific footprints generated by GDACS."
)
