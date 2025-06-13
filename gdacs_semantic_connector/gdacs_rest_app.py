import streamlit as st                     # Streamlit for interactive UI
import pandas as pd                        # pandas for DataFrame handling & export
import os                                  # filesystem operations
import requests                            # HTTP API calls
import json                                # JSON parsing
import urllib.parse                        # URL parsing for episode IDs
import folium                              # map rendering
from streamlit_folium import st_folium     # embed Folium in Streamlit
from io import BytesIO                     # in-memory buffer for Excel downloads
from rdflib import Graph, Namespace        # OWL/RDF parsing
from rdflib.namespace import RDF, RDFS     # RDF vocabularies
from gdacs.api import EVENT_TYPES          # valid GDACS event_type codes

# --------------------------------------------------
# Namespace for your OWL
# --------------------------------------------------
DIS = Namespace("http://example.org/disaster#")

# --------------------------------------------------
# Helper: parse OWL & extract hazard definitions
# --------------------------------------------------
@st.cache_data(show_spinner=False)
def load_hazard_ontology(file_obj):
    g = Graph()
    g.parse(file_obj)
    hazards = []
    for subj in g.subjects(RDF.type, DIS.GDACSHazardType):
        lbl  = g.value(subj, RDFS.label)
        code = g.value(subj, DIS.gdacsCode)
        hazards.append({
            "label": str(lbl)  if lbl  else None,
            "code":  str(code) if code else None
        })
    return sorted(hazards, key=lambda h: (h["label"] or ""))

# --------------------------------------------------
# Utility: extract a representative lon/lat from GeoJSON
# --------------------------------------------------
def first_lon_lat(geom):
    t = geom.get("type", "")
    c = geom.get("coordinates", [])
    try:
        if t == "Polygon":
            return c[0][0][0:2]
        if t == "MultiPolygon":
            return c[0][0][0][0:2]
        if t == "Point":
            return c[0:2]
    except:
        pass
    return 0, 0

# --------------------------------------------------
# Sidebar: Ontology upload & hazard selection
# --------------------------------------------------
st.set_page_config(page_title="GDACS Semantic Connector", layout="wide")
st.sidebar.title("🌐 GDACS Semantic Query")

owl_file = st.sidebar.file_uploader("Upload Hazard Ontology (.owl)", type=["owl"])
if not owl_file:
    st.sidebar.info("Please upload an OWL file to proceed.")
    st.stop()

hazards   = load_hazard_ontology(owl_file)
supported = [c for c in EVENT_TYPES if c]
valid     = [h for h in hazards if h["code"] in supported]
invalid   = [h for h in hazards if h["code"] not in supported]

if invalid:
    st.sidebar.warning(
        "Skipped (no GDACS code): " + ", ".join(h["label"] for h in invalid if h["label"])
    )
if not valid:
    st.sidebar.error("No valid hazards found in your ontology.")
    st.stop()

labels    = [h["label"] for h in valid]
sel_label = st.sidebar.selectbox("Select Hazard Type", labels)
sel_code  = next(h["code"] for h in valid if h["label"] == sel_label)
limit     = st.sidebar.selectbox("Limit number of results", [10,20,50,100,200,500,1000], 0)

# --------------------------------------------------
# Main: Summary of GDACS events
# --------------------------------------------------
st.title("🌍 GDACS Semantic Connector")
st.caption("Ontology-driven hazard selection → event summary → detail & episode footprints")

st.header("🗂️ Summary Events")
if st.sidebar.button("🔍 Fetch GDACS Events"):
    from gdacs.api import GDACSAPIReader
    client = GDACSAPIReader()
    with st.spinner(f"Loading latest {sel_label} events…"):
        try:
            gj = client.latest_events(event_type=sel_code, limit=limit)
        except Exception as e:
            st.error(f"Failed to fetch events: {e}")
            gj = None

    if not gj or not getattr(gj, "features", []):
        st.warning("No events returned.")
    else:
        rows = []
        for feat in gj.features:
            p    = feat.get("properties", {})
            geom = feat.get("geometry", {}) or {}
            lon, lat = geom.get("coordinates", [None,None])[0:2]
            et, eid = p.get("eventtype"), p.get("eventid")
            rows.append({
                "event_type":   et,
                "event_id":     eid,
                "name":         p.get("name"),
                "alert":        p.get("alertlevel"),
                "from_date":    p.get("fromdate"),
                "to_date":      p.get("todate"),
                "country":      p.get("country"),
                "severity":     p.get("severitydata",{}).get("severity"),
                "latitude":     lat,
                "longitude":    lon,
                "report_url":   p.get("url",{}).get("report"),
                "geometry_url": p.get("url",{}).get("geometry"),
                "detail_url":   (
                    f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?"
                    f"eventtype={et}&eventid={eid}"
                )
            })
        df = pd.DataFrame(rows)
        st.session_state["summary_df"] = df
        st.dataframe(df, use_container_width=True)

        # Download CSV
        st.download_button(
            "📥 Download Summary CSV",
            data=df.to_csv(index=False),
            file_name="gdacs_summary.csv",
            mime="text/csv",
            key="download_summary_csv"
        )
        # Download Excel (in-memory)
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        excel_buffer.seek(0)
        st.download_button(
            "🗕️ Download Summary Excel",
            data=excel_buffer.getvalue(),
            file_name="gdacs_summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_summary_excel"
        )

# --------------------------------------------------
# Detail fetch: Sendai data per event
# --------------------------------------------------
if "summary_df" in st.session_state:
    st.markdown("---")
    st.subheader("📋 GDACS Event Details")
    if st.button("📥 Fetch Details for Each Event"):
        details_dir = "gdacs_event_details"
        os.makedirs(details_dir, exist_ok=True)
        detail_files = []
        for _, row in st.session_state["summary_df"].iterrows():
            url, et, eid = row["detail_url"], row["event_type"], row["event_id"]
            try:
                r = requests.get(url); r.raise_for_status()
                props = r.json().get("properties", {})
                if not props:
                    st.warning(f"No properties for {et} {eid}")
                    continue
                df_det = pd.json_normalize([props])
                fn = f"{et}_{eid}_details.xlsx"
                fp = os.path.join(details_dir, fn)
                df_det.to_excel(fp, index=False)
                detail_files.append((fn, fp))
                st.success(f"Saved details → {fn}")
            except Exception as e:
                st.error(f"Failed details {et} {eid}: {e}")
        st.session_state["detail_files"] = detail_files

    if st.session_state.get("detail_files"):
        st.markdown("### 📎 Download Detailed Files")
        for fn, fp in st.session_state["detail_files"]:
            with open(fp, "rb") as f:
                st.download_button(
                    label=fn,
                    data=f.read(),
                    file_name=fn,
                    key=f"download_detail_{fn}"
                )

# --------------------------------------------------
# Episode footprints: fetch & save per-episode geometry
# --------------------------------------------------
if "summary_df" in st.session_state:
    st.markdown("---")
    st.subheader("⌛ Fetch & Save All Episode Footprints")
    if st.button("🌐 Fetch Episodes & Geometry"):
        base_dir = "gdacs_event_geometry"
        os.makedirs(base_dir, exist_ok=True)
        evolution = {}
        for _, row in st.session_state["summary_df"].iterrows():
            et, eid, name = row["event_type"], row["event_id"], row["name"]
            ev_dir = os.path.join(base_dir, f"{et}_{eid}")
            os.makedirs(ev_dir, exist_ok=True)

            # Get episodes
            try:
                r  = requests.get(row["detail_url"]); r.raise_for_status()
                eps = r.json().get("properties", {}).get("episodes", [])
            except:
                eps = []
            episode_ids = []
            for ep in eps:
                q = urllib.parse.urlparse(ep.get("details","")).query
                params = urllib.parse.parse_qs(q)
                if "episodeid" in params:
                    episode_ids.append(int(params["episodeid"][0]))

            # Fetch each episode's geometry
            footprints = []
            for ep_id in sorted(episode_ids):
                geom_url = (
                    f"https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
                    f"?eventtype={et}&eventid={eid}&episodeid={ep_id}"
                )
                try:
                    r2    = requests.get(geom_url); r2.raise_for_status()
                    gj_ep = r2.json()
                    poly  = next(
                        (f for f in gj_ep["features"]
                         if f["geometry"]["type"] in ("Polygon","MultiPolygon")),
                        None
                    )
                    ts    = poly["properties"].get("polygondate") if poly else "N/A"
                    fn    = f"episode_{ep_id}.geojson"
                    fp    = os.path.join(ev_dir, fn)
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(gj_ep, f)
                    footprints.append({
                        "episode":   ep_id,
                        "timestamp": ts,
                        "geojson":   gj_ep,
                        "path":      fp
                    })
                except:
                    continue

            evolution[f"{et}_{eid}"] = {
                "meta":       {"event_type":et, "event_id":eid, "name":name},
                "footprints": footprints
            }

        st.session_state["evolution"] = evolution
        st.success("Fetched & saved all episode geometries.")

    # --------------------------------------------------
    # Display evolution: maps + download links (on-demand)
    # --------------------------------------------------
    if st.session_state.get("evolution"):
        st.markdown("---")
        st.header("📈 Evolution of Event Footprints")
        for event_key, info in st.session_state["evolution"].items():
            meta = info["meta"]
            ecode = meta["event_type"]
            eid = meta["event_id"]
            ename = meta["name"]

            st.subheader(f"{ecode} {eid} – {ename}")
            # for each episode, only render map & button if user ticks the box
            for fp in info["footprints"]:
                ep = fp["episode"]
                ts = fp["timestamp"]
                gj = fp["geojson"]
                geo_fp = fp["path"]
                chk_key = f"show_ep_{ecode}_{eid}_{ep}"

                # this checkbox replaces the always-on st_folium calls
                if st.checkbox(f"Episode {ep} — {ts}", key=chk_key):
                    # compute center (use point if available)
                    pt = next((f for f in gj["features"]
                               if f["geometry"]["type"] == "Point"), None)
                    if pt:
                        lon0, lat0 = pt["geometry"]["coordinates"][:2]
                    else:
                        lon0, lat0 = first_lon_lat(gj["features"][0]["geometry"])

                    # render the Folium map
                    m = folium.Map(
                        location=[lat0, lon0],
                        zoom_start=6,
                        tiles="CartoDB positron"
                    )
                    folium.GeoJson(
                        gj,
                        style_function=lambda feat: {
                            "fillColor": "#228B22",
                            "color": "#222",
                            "weight": 1,
                            "fillOpacity": 0.6
                        }
                    ).add_to(m)
                    folium.CircleMarker(
                        location=(lat0, lon0),
                        radius=5,
                        color="crimson",
                        fill=True,
                        fill_color="crimson",
                        fill_opacity=0.9
                    ).add_to(m)

                    st_folium(m, width=700, height=400)

                    # unique download key per episode
                    st.download_button(
                        label=f"⬇️ Download Episode {ep} GeoJSON",
                        data=open(geo_fp, "rb").read(),
                        file_name=os.path.basename(geo_fp),
                        key=f"download_ep_{ecode}_{eid}_{ep}"
                    )
            # small spacer between events
            st.markdown("—" * 10)
# --------------------------------------------------
# Footer: explanation of GDACS polygons
# --------------------------------------------------
st.markdown(
    "> **What do these polygons represent?**  \n"
    "> GDACS publishes an *event-footprint* layer derived from satellite and model analysis.  "
    "> • **Flood (FL)** polygons outline the estimated inundated area.  "
    "> • **Wildfire (WF)** polygons show the hot-spot / burned-area perimeter.  "
    "> • For earthquakes, polygons approximate the affected region based on shaking intensity.  "
    "> They are **not** administrative boundaries but hazard-specific footprints generated by GDACS."
)
