# geojson_to_ttl.py (patched)
# Convert GDACS *.geojson files into RDF per the EOMDG ontology.
# This version:
#  • Emits canonical events as eomdg:DisasterEvent (no hazard-named classes)
#  • Adds eomdg:hasHazardType from GDACS eventtype
#  • Auto-materializes eomdg:hasHazardGroup / eomdg:hasHazardSubgroup from taxonomy
#  • Writes a TriG file into a named graph for clean scoping in GraphDB
#  • Uses GeoSPARQL geo:wktLiteral with SRID=4326 and OWL-Time instants
#
# Adjust the CONFIG section (IN_FOLDER, TAXONOMY_TTL, TARGET_GRAPH, OUTPUT_PATH).

import json
import pathlib
from typing import Optional, Tuple, Set

from rdflib import Graph, Dataset, Namespace, URIRef, BNode, Literal
from rdflib.namespace import RDF, RDFS, XSD
from rdflib.namespace import NamespaceManager

import shapely
from shapely.geometry import shape
from shapely.wkt import dumps as wkt_dumps

# =========================
# CONFIG
# =========================
# 1) Folder with your GDACS geojson files (e.g., WF_*.geojson)
IN_FOLDER = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/WF_Compact"

# 2) Write one merged TriG file (False to write one TriG per input file)
ONE_FILE_PER_INPUT = False

# 3) Where to write the merged output (ignored if ONE_FILE_PER_INPUT=True)
MERGED_OUT_PATH = None  # e.g., r"C:\\data\\gdacs_events_v2.trig"

# 4) Namespaces / IRIs
EOMDG_NS = "http://example.org/eomdg/"   # MUST match your ontology IRI (slash form)
# EOMDG_NS = "http://example.org/eomdg#"  # <-- do NOT use this unless your ontology uses '#'
KG_NS    = "http://example.org/kg/"      # base for event IRIs
TARGET_GRAPH = "http://example.org/kg/gdacs/events/wildfire"  # named graph to write

# 5) Taxonomy TTL file (used to resolve Group/Subgroup)
TAXONOMY_TTL = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/data/graphdb_import/hazard_taxonomy.ttl"

# 6) Map GDACS eventtype code -> HazardType local name from your taxonomy
#    Adjust RHS to exactly match local names in hazard_taxonomy_v2.ttl
HAZARD_CODE_TO_TYPE = {
    "WF": "Wildfire",
    "FL": "Flood",
    "EQ": "Earthquake",
    "TC": "TropicalCyclone",
    "TS": "Tsunami",
    "VO": "Volcano",
    "DR": "Drought",
}

# =========================
# Namespaces
# =========================
EOMDG = Namespace(EOMDG_NS)
KG    = Namespace(KG_NS)
GEO   = Namespace("http://www.opengis.net/ont/geosparql#")
TIME  = Namespace("http://www.w3.org/2006/time#")
PROV  = Namespace("http://www.w3.org/ns/prov#")
SKOS  = Namespace("http://www.w3.org/2004/02/skos/core#")

# =========================
# Helpers
# =========================

def ensure_prefixes(g: Graph):
    nm = NamespaceManager(g)
    nm.bind("eomdg", EOMDG, replace=True)
    nm.bind("geo",   GEO,   replace=True)
    nm.bind("time",  TIME,  replace=True)
    nm.bind("prov",  PROV,  replace=True)
    nm.bind("skos",  SKOS,  replace=True)
    nm.bind("xsd",   XSD,   replace=True)
    nm.bind("kg",    KG,    replace=True)
    g.namespace_manager = nm


def to_dt(s: Optional[str]) -> Optional[Literal]:
    """GDACS time string -> xsd:dateTime literal (ensure Z)."""
    if not s:
        return None
    s = str(s)
    if s.endswith("Z"):
        return Literal(s, datatype=XSD.dateTime)
    return Literal(s + "Z", datatype=XSD.dateTime)


def wkt_with_srid(shp) -> Literal:
    """
    Return a GeoSPARQL WKT literal with SRID prefix.
    • Uses full precision (15 decimals ~ double-precision) – no trimming
    • Compatible with Shapely 1.8 and 2.x
    """
    try:
        # Shapely < 2.0  (signature: dumps(obj, rounding_precision=…, trim=…))
        wkt = wkt_dumps(shp, rounding_precision=15, trim=False)
    except TypeError:
        # Shapely 2.x  →  to_wkt(obj, rounding_precision=…, trim=…)
        wkt = shapely.to_wkt(shp, rounding_precision=15, trim=False)

    return Literal(f"SRID=4326; {wkt}", datatype=GEO.wktLiteral)


def add_time_inst(g: Graph, pred: URIRef, parent: URIRef, dt_literal: Optional[Literal]):
    """Attach an OWL-Time Instant node with type + time:inXSDDateTime."""
    if not dt_literal:
        return
    inst = BNode()
    g.add((parent, pred, inst))
    g.add((inst, RDF.type, TIME.Instant))
    g.add((inst, TIME.inXSDDateTime, dt_literal))


def bbox_to_envelope_wkt(bbox) -> Optional[Literal]:
    """GDACS bbox is [minx, miny, maxx, maxy]. Store as WKT envelope polygon."""
    if not bbox or len(bbox) != 4:
        return None
    minx, miny, maxx, maxy = bbox
    wkt = f"SRID=4326; POLYGON(({minx} {miny}, {maxx} {miny}, {maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    return Literal(wkt, datatype=GEO.wktLiteral)


def code_to_hazard_uri(code: Optional[str]) -> Optional[URIRef]:
    """Translate GDACS eventtype code (e.g., 'WF') to an eomdg:HazardType URI."""
    if not code:
        return None
    local = HAZARD_CODE_TO_TYPE.get(str(code).upper())
    return (EOMDG[local] if local else None)


# ===== Taxonomy resolution (Group/Subgroup) =====

def load_taxonomy() -> Graph:
    T = Graph()
    try:
        p = pathlib.Path(TAXONOMY_TTL)
        if p.exists():
            T.parse(str(p), format="turtle")
            ensure_prefixes(T)
        else:
            print(f"[WARN] Taxonomy file not found: {p}")
    except Exception as ex:
        print(f"[WARN] Failed to parse taxonomy: {ex}")
    return T


def find_group_subgroup(T: Graph, hazard_type_uri: Optional[URIRef]) -> Tuple[Optional[URIRef], Optional[URIRef]]:
    """Return (group_uri, subgroup_uri) for a given hazard type.
    Strategy:
      1) Prefer explicit eomdg:inHazardGroup / eomdg:inHazardSubgroup if present
      2) Else walk SKOS broader/narrower (both directions) and pick nodes typed as
         eomdg:HazardGroup / eomdg:HazardSubgroup.
    """
    if hazard_type_uri is None or len(T) == 0:
        return (None, None)

    # 1) explicit links
    g = next(T.objects(hazard_type_uri, EOMDG.inHazardGroup), None)
    sg = next(T.objects(hazard_type_uri, EOMDG.inHazardSubgroup), None)
    if g or sg:
        return (g, sg)

    # 2) SKOS graph walk
    frontier: Set[URIRef] = {hazard_type_uri}
    seen: Set[URIRef] = set()
    group_uri: Optional[URIRef] = None
    subg_uri: Optional[URIRef] = None

    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)

        # follow both directions; taxonomy may encode either way
        for p in (SKOS.broader, SKOS.narrower):
            for nxt in T.objects(cur, p):
                if nxt not in seen:
                    frontier.add(nxt)
            for nxt in T.subjects(p, cur):
                if nxt not in seen:
                    frontier.add(nxt)

        # typed hits
        if (cur, RDF.type, EOMDG.HazardGroup) in T and group_uri is None:
            group_uri = cur
        if (cur, RDF.type, EOMDG.HazardSubgroup) in T and subg_uri is None:
            subg_uri = cur

        if group_uri and subg_uri:
            break

    return (group_uri, subg_uri)


# =========================
# Core conversion
# =========================

def feature_collection_to_triples(ds: Dataset, fc: dict, T: Graph, target_graph_iri: str):
    g = ds.get_context(URIRef(target_graph_iri))
    ensure_prefixes(g)

    feats = fc.get("features", [])
    if not feats:
        return

    # choose the most complete properties block among features
    props = {}
    for f in feats:
        p = f.get("properties") or {}
        if len(p) >= len(props):
            props = p

    eventtype = props.get("eventtype")
    eventid   = props.get("eventid")
    episodeid = props.get("episodeid")

    if not (eventtype and eventid is not None and episodeid is not None):
        return

    # Event IRI
    ev_iri = KG[f"{eventtype}_{eventid}_{episodeid}"]

    # Canonical event typing
    g.add((ev_iri, RDF.type, EOMDG.DisasterEvent))

    # Hazard type
    haz_uri = code_to_hazard_uri(eventtype)
    if haz_uri is not None:
        g.add((ev_iri, EOMDG.hasHazardType, haz_uri))
        # Derive Group/Subgroup from taxonomy
        grp, subg = find_group_subgroup(T, haz_uri)
        if grp:
            g.add((ev_iri, EOMDG.hasHazardGroup, grp))
        if subg:
            g.add((ev_iri, EOMDG.hasHazardSubgroup, subg))

    # Keep original GDACS identifiers / code
    g.add((ev_iri, EOMDG.eventType, Literal(eventtype)))
    try:
        g.add((ev_iri, EOMDG.eventId,   Literal(int(eventid))))
    except Exception:
        g.add((ev_iri, EOMDG.eventId,   Literal(str(eventid))))
    try:
        g.add((ev_iri, EOMDG.episodeId, Literal(int(episodeid))))
    except Exception:
        g.add((ev_iri, EOMDG.episodeId, Literal(str(episodeid))))

    # Strings at event level
    string_map = [
        ("name",          EOMDG.eventName),
        ("description",   EOMDG.description),
        ("alertlevel",    EOMDG.alertLevel),
        ("country",       EOMDG.countryName),
        ("iso3",          EOMDG.countryISO3),
        ("source",        EOMDG.source),
        ("sourceid",      EOMDG.sourceId),
        ("polygonlabel",  EOMDG.polygonLabel),
        ("Class",         EOMDG.classLabel),
        ("glide",         EOMDG.glideId),
    ]
    for key, pred in string_map:
        v = props.get(key)
        if v:
            g.add((ev_iri, pred, Literal(v)))

    # Icon & URL fields → IRIs
    iri_map = [
        ("icon",         EOMDG.iconURL),
        ("iconoverall",  EOMDG.iconEventURL),
        ("iconitemlink", EOMDG.iconItemURL),
    ]
    for key, pred in iri_map:
        v = props.get(key)
        if v:
            g.add((ev_iri, pred, URIRef(v)))

    # Nested URL bundle (geometry/report/details)
    url_bundle = props.get("url") or {}
    for key, pred in [
        ("geometry", EOMDG.geometryURL),
        ("report",   EOMDG.reportURL),
        ("details",  EOMDG.detailsURL),
    ]:
        v = url_bundle.get(key)
        if v:
            g.add((ev_iri, pred, URIRef(v)))

    # Alert score (numeric)
    if props.get("alertscore") is not None:
        try:
            g.add((ev_iri, EOMDG.alertScore, Literal(float(props["alertscore"]))))
        except Exception:
            pass

    # Booleans
    for key, pred in [
        ("istemporary", EOMDG.isTemporary),
        ("iscurrent",   EOMDG.isCurrent),
    ]:
        v = props.get(key)
        if v is not None:
            g.add((ev_iri, pred, Literal(str(v).lower() == "true", datatype=XSD.boolean)))

    # Times
    add_time_inst(g, TIME.hasBeginning, ev_iri, to_dt(props.get("fromdate")))
    add_time_inst(g, TIME.hasEnd,       ev_iri, to_dt(props.get("todate")))
    if props.get("polygondate"):
        g.add((ev_iri, EOMDG.polygonDate, to_dt(props["polygondate"])))

    # Severity block
    sevdata = props.get("severitydata") or {}
    if sevdata:
        sev = BNode()
        g.add((ev_iri, EOMDG.hasSeverity, sev))
        g.add((sev, RDF.type, EOMDG.SeverityAssessment))
        if sevdata.get("severity") is not None:
            g.add((sev, EOMDG.severityValue, Literal(sevdata["severity"], datatype=XSD.decimal)))
        if sevdata.get("severityunit"):
            g.add((sev, EOMDG.severityUnit, Literal(sevdata["severityunit"])))
        if sevdata.get("severitytext"):
            g.add((sev, EOMDG.severityText, Literal(sevdata["severitytext"])))

    # Affected countries (structured nodes)
    for c in props.get("affectedcountries", []):
        node = BNode()
        g.add((ev_iri, EOMDG.hasAffectedCountry, node))
        g.add((node, RDF.type, EOMDG.AffectedCountry))
        if c.get("iso2"):
            g.add((node, EOMDG.iso2, Literal(c["iso2"])))
        if c.get("iso3"):
            g.add((node, EOMDG.iso3, Literal(c["iso3"])))
        if c.get("countryname"):
            g.add((node, EOMDG.countryName, Literal(c["countryname"])))

    # Geometry footprints
    for f in feats:
        geom = f.get("geometry")
        if not geom:
            continue
        bbox = f.get("bbox")
        bbox_lit = bbox_to_envelope_wkt(bbox) if bbox else None

        # ─── build the geometry node ─────────────────────────────────────────
        shp = shape(geom)
        gnode = BNode()
        g.add((ev_iri, EOMDG.hasFootprint, gnode))
        g.add((gnode, RDF.type, EOMDG.EventFootprint))
        g.add((gnode, GEO.asWKT, wkt_with_srid(shp)))

        props_f = f.get("properties") or {}

        # 1) class label
        lbl = props_f.get("Class")  # your source field
        if lbl:
            g.add((gnode, EOMDG.classLabel, Literal(lbl)))

        # 2) polygon label
        plbl = props_f.get("polygonlabel")  # your source field
        if plbl:
            g.add((gnode, EOMDG.polygonLabel, Literal(plbl)))

        # 3) bbox envelope (if you still want it)
        if bbox_lit:
            g.add((gnode, EOMDG.bboxEnvelope, bbox_lit))

        # 4) polygon date – ONLY for polygon footprints
        if lbl == "Poly_area":
            pdate = to_dt(props_f.get("polygondate"))
            if pdate:
                g.add((gnode, EOMDG.polygonDate, pdate))
        # optional: else put an explicit NULL marker if you really need it:
        # elif lbl == "Point_Centroid":
        #     g.add((gnode, EOMDG.polygonDate, Literal("NULL")))

        # ─── time slice ──────────────────────────────────────────────────────
        # 1) try feature-level timestamp (preferred)
        dt = None
        if (f.get("properties") or {}).get("datetime"):
            dt = to_dt(f["properties"]["datetime"])
        # 2) else fall back to collection-level polygondate
        elif props.get("polygondate"):
            dt = to_dt(props["polygondate"])

        # attach the Instant if we found a date
        add_time_inst(g, TIME.atTime, gnode, dt)

    # Provenance
    g.add((ev_iri, PROV.wasDerivedFrom, URIRef("https://www.gdacs.org/")))


# =========================
# Runner
# =========================

def main():
    in_dir = pathlib.Path(IN_FOLDER)
    files = sorted(in_dir.glob("*.geojson"))
    if not files:
        print(f"[INFO] No .geojson files found in {IN_FOLDER}")
        return

    T = load_taxonomy()

    if ONE_FILE_PER_INPUT:
        for f in files:
            ds = Dataset()
            ensure_prefixes(ds)
            fc = json.loads(f.read_text(encoding="utf-8"))
            feature_collection_to_triples(ds, fc, T, TARGET_GRAPH)
            out = f.with_suffix(".trig")
            ds.serialize(destination=str(out), format="trig")
            print(f"[OK] Wrote {out}")
    else:
        ds = Dataset()
        ensure_prefixes(ds)
        for f in files:
            fc = json.loads(f.read_text(encoding="utf-8"))
            feature_collection_to_triples(ds, fc, T, TARGET_GRAPH)

        if MERGED_OUT_PATH:
            out_path = pathlib.Path(MERGED_OUT_PATH)
        else:
            out_path = in_dir.parent / "data/graphdb_import/gdacs_events_wildfire.trig"

        ds.serialize(destination=str(out_path), format="trig")
        print(f"[OK] Wrote {out_path}")


if __name__ == "__main__":
    main()
