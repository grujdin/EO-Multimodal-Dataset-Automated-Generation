import streamlit as st
import pandas as pd
import os
import requests
import json
import pydeck as pdk
from rdflib import Graph
from rdflib.namespace import RDF, RDFS
from rdflib import Namespace

# --------------------------------------------------
# Helper : load the OWL file and extract hazard labels
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def load_hazard_ontology(file_obj):
    g = Graph()
    g.parse(file_obj)

    # the ontology the user gave us might use any namespace – try a few
    candidate_ns = [
        Namespace("http://example.org/hazard#"),
        Namespace("http://example.org/disaster#"),
        Namespace("http://example.org/api#"),
    ]

    hazards = []
    for ns in candidate_ns:
        for s in g.subjects(RDF.type, ns.DisasterType):
            label = g.value(s, RDFS.label)
            if label:
                hazards.append((str(s), str(label)))
        if hazards:
            break

    # Sorted nicely for the dropdown
    return sorted(hazards, key=lambda x: x[1])


# --------------------------------------------------
# Small util: get a rough "centroid" from first coordinate in a geometry
# --------------------------------------------------

def first_lon_lat(geom):
    """Return a (lon, lat) pair from the first coordinate found in GeoJSON geometry."""
    try:
        if geom["type"] == "Polygon":
            return geom["coordinates"][0][0][0:2]
        if geom["type"] == "MultiPolygon":
            return geom["coordinates"][0][0][0][0:2]
        if geom["type"] == "Point":
            return geom["coordinates"][0:2]
    except Exception:
        pass
    return 0, 0


# --------------------------------------------------
# Streamlit – sidebar
# --------------------------------------------------

st.set_page_config(page_title="GDACS API Semantic Connector", layout="wide")

st.sidebar.title("🌐 GDACS Semantic Query")
owl_file = st.sidebar.file_uploader("Upload Hazard Ontology (.owl)", type=["owl"], key="hazard_ontology")
if not owl_file:
    st.stop()

hazard_opts = load_hazard_ontology(owl_file)
labels = [lbl for _uri, lbl in hazard_opts]
sel_label = st.sidebar.selectbox("Select Hazard Type", labels)
limit = st.sidebar.selectbox("Limit number of results", [10, 20, 50, 100, 200, 500, 1000], 0)

# crude mapping → first two letters (works for Flood‑FL, WildFire‑WF, etc.)
sel_code = sel_label[:2].upper()


# --------------------------------------------------
# Main – summary call
# --------------------------------------------------

st.title("GDACS Semantic Connector")
st.caption("Unofficial GDACS API explorer with ontology‑driven hazard selection, detail & geometry fetch plus quick map preview.")

st.header("🗂️ Summary Events")
st.markdown("Using <https://www.gdacs.org/observatory/api/data> (unofficial)")

if st.sidebar.button("🔍 Fetch GDACS Events"):
    from gdacs.api import GDACSAPIReader
    client = GDACSAPIReader()

    with st.spinner(f"Querying latest GDACS events for {sel_label} …"):
        try:
            geojson = client.latest_events(event_type=sel_code, limit=limit)
        except Exception as err:
            st.error(f"❌ Failed to fetch GDACS events: {err}")
            geojson = []

    rows = []
    for feature in getattr(geojson, "features", []):
        props = feature.get("properties", {})
        geom  = feature.get("geometry", {})
        lon, lat = (None, None)
        if geom.get("coordinates"):
            lon, lat = geom["coordinates"][0:2]
        # pre‑build all useful URLs so we never need to reconstruct later
        eventtype = props.get("eventtype")
        eventid   = props.get("eventid")
        rows.append({
            "event_type"   : eventtype,
            "event_id"     : eventid,
            "name"         : props.get("name"),
            "alert_level"  : props.get("alertlevel"),
            "from_date"    : props.get("fromdate"),
            "to_date"      : props.get("todate"),
            "country"      : props.get("country"),
            "severity"     : props.get("severitydata", {}).get("severity"),
            "latitude"     : lat,
            "longitude"    : lon,
            "report_url"   : props.get("url", {}).get("report"),
            "geometry_url" : props.get("url", {}).get("geometry"),
            "detail_url"   : f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={eventtype}&eventid={eventid}",
        })

    if not rows:
        st.warning("⚠️ No events returned.")
    else:
        df_events = pd.DataFrame(rows)
        st.session_state["summary_df"] = df_events
        st.dataframe(df_events, use_container_width=True)
        df_events.to_excel("gdacs_hazards.xlsx", index=False)
        st.download_button("🗕️ Download Events CSV", df_events.to_csv(index=False), file_name="gdacs_hazards.csv")
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
        file_links = []

        for _idx, row in st.session_state["summary_df"].iterrows():
            url = row["detail_url"]  # use the pre‑built link
            ev_type = row["event_type"]
            ev_id   = row["event_id"]
            try:
                resp = requests.get(url)
                resp.raise_for_status()
                js = resp.json()

                sendai_payload = js.get("properties", {}).get("sendai", [])
                if not sendai_payload:
                    st.warning(f"⚠️ No 'sendai' data for {ev_type} {ev_id}")
                    continue

                df_det = pd.json_normalize(sendai_payload)
                out_name = f"{ev_type}_{ev_id}_details.xlsx"
                out_path = os.path.join(details_dir, out_name)
                df_det.to_excel(out_path, index=False)
                file_links.append((out_name, out_path))
                st.success(f"✅ Saved details → {out_name}")
            except Exception as exc:
                st.error(f"❌ Failed to fetch detail for {ev_type} {ev_id}: {exc}")

        if file_links:
            st.session_state["detail_files"] = file_links

    if st.session_state.get("detail_files"):
        st.markdown("### 📎 Download Detailed Files")
        for fname, fpath in st.session_state["detail_files"]:
            with open(fpath, "rb") as fh:
                st.download_button(f"⬇️ {fname}", fh.read(), file_name=fname)

    # --------------------------------------------------
    # Geometry fetch + MAP section (per‑event maps!)
    # --------------------------------------------------
    st.markdown("---")
    st.subheader("🗺️ GDACS Event Geometry (polygons)")

    if st.button("🌐 Fetch Geometry for Each Event"):
        geom_dir = "gdacs_event_geometry"
        os.makedirs(geom_dir, exist_ok=True)
        geom_links = []
        geojson_objs = []  # keep paired with event meta

        for _idx, row in st.session_state["summary_df"].iterrows():
            g_url  = row.get("geometry_url")
            ev_type = row["event_type"]
            ev_id   = row["event_id"]
            ev_name = row["name"]
            if not g_url:
                st.warning(f"⚠️ No geometry URL for {ev_type} {ev_id}")
                continue
            try:
                g_resp = requests.get(g_url)
                g_resp.raise_for_status()
                geojson_text = g_resp.text
                geojson_obj  = json.loads(geojson_text)
                out_name = f"{ev_type}_{ev_id}_geometry.geojson"
                out_path = os.path.join(geom_dir, out_name)
                with open(out_path, "w", encoding="utf-8") as gf:
                    gf.write(geojson_text)
                geom_links.append((out_name, out_path))
                geojson_objs.append({"meta": row.to_dict(), "geojson": geojson_obj})
                st.success(f"✅ Saved geometry → {out_name}")
            except Exception as g_exc:
                st.error(f"❌ Failed to fetch geometry for {ev_type} {ev_id}: {g_exc}")

        # store for later display / download
        if geom_links:
            st.session_state["geom_files"] = geom_links
        if geojson_objs:
            st.session_state["geom_objects"] = geojson_objs

    # download buttons
    if st.session_state.get("geom_files"):
        st.markdown("### 📎 Download Geometry Files")
        for gname, gpath in st.session_state["geom_files"]:
            with open(gpath, "rb") as gh:
                st.download_button(f"⬇️ {gname}", gh.read(), file_name=gname)

    # individual map previews
    if st.session_state.get("geom_objects"):
        alert_colour = {
            "RED":    [220,  20,  60, 80],   # crimson
            "ORANGE": [255, 140,   0, 80],   # dark‑orange
            "GREEN":  [ 34, 139,  34, 80],   # forest‑green
        }

        st.markdown("### 🗺️ Per‑Event Map Preview")
        for entry in st.session_state["geom_objects"]:
            meta = entry["meta"]
            gj   = entry["geojson"]

            # Ensure we always have a FeatureCollection wrapper
            if gj.get("type") != "FeatureCollection":
                gj = {"type": "FeatureCollection", "features": [gj]}

            # colour the polygon based on alert level per feature
            for f in gj["features"]:
                alert = str(f.get("properties", {}).get("alertlevel", "GREEN")).upper()
                f.setdefault("properties", {})["_fill"] = alert_colour.get(alert, [128, 128, 128, 80])

            lon0, lat0 = first_lon_lat(gj["features"][0]["geometry"])

            geo_layer = pdk.Layer(
                "GeoJsonLayer",
                gj,
                stroked=True,
                filled=True,
                extruded=False,
                get_fill_color="properties._fill",
                get_line_color=[60, 60, 60],
                line_width_min_pixels=1,
            )
            deck = pdk.Deck(
                layers=[geo_layer],
                initial_view_state=pdk.ViewState(latitude=lat0, longitude=lon0, zoom=6),
                tooltip={"html": "<b>{properties.name}</b><br>Alert: {properties.alertlevel}"},
            )

            expander_title = f"🗺️ {meta['event_type']} {meta['event_id']} – {meta['name']}"
            with st.expander(expander_title, expanded=False):
                st.pydeck_chart(deck, use_container_width=True)

        # Legend once at the end
        legend_html = """
        <div style='font-size:0.875rem;'>
            <b>Legend</b><br>
            <span style='background:#DC143C;width:12px;height:12px;display:inline-block;border:1px solid #333'></span>&nbsp;Red alert<br>
            <span style='background:#FF8C00;width:12px;height:12px;display:inline-block;border:1px solid #333'></span>&nbsp;Orange alert<br>
            <span style='background:#228B22;width:12px;height:12px;display:inline-block;border:1px solid #333'></span>&nbsp;Green alert<br>
        </div>
        """
        st.markdown(legend_html, unsafe_allow_html=True)

# --------------------------------------------------
# Footer info about polygons
# --------------------------------------------------
st.markdown(
    "> **What do these polygons represent?**  \n> GDACS publishes an *event‑footprint* layer derived from satellite and model analysis.  • **Flood (FL)** polygons outline the estimated inundated area.  • **Wildfire (WF)** polygons show the hot‑spot / burned‑area perimeter.  • For earthquakes, polygons approximate the affected region based on shaking intensity.  They are **not** administrative boundaries but hazard‑specific footprints generated by GDACS."
)