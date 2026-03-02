#!/usr/bin/env python3
# Convert GDACS flood *episode* files (FL_<eventid>_<episode>.geojson/.json)
# to TriG, one TriG per input file (no "overall" files used).
#
# • Recursively scans IN_ROOT (flat or nested event folders)
# • Accepts both .geojson and .json when they actually contain GeoJSON
# • Robust date parsing → ISO 8601 (fixes 08/Jul/2019 15:00:00Z, etc.)
# • Defensive geometry handling: make_valid/buffer(0)/simplify/bbox fallback
# • Named graph per episode: GRAPH_TEMPLATE = ".../FL/{event}/{episode}"
#
# Requirements: pip install rdflib shapely
# Optional (Windows): if locales fail to parse month abbreviations, set
#   locale to English in your shell or use the MONTHS map below.

import json
import pathlib
import re
from typing import Optional, Tuple, Set, Dict, Any, List

from rdflib import Graph, Dataset, Namespace, URIRef, BNode, Literal
from rdflib.namespace import RDF, XSD
from rdflib.namespace import NamespaceManager

import shapely
from shapely.geometry import shape
from shapely.wkt import dumps as wkt_dumps

# =========================
# CONFIG (merged output)
# =========================
# 1) Where your flood episodes live (recursively scanned)
IN_ROOT = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/FL"

# 2) Write a single TriG that contains all events/episodes
MERGE_OUTPUT = True
MERGED_OUT_PATH = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/data/graphdb_import/gdacs_events_flood.trig"

# 3) Named graph IRI to use for every episode (single graph).
#    If you want per-episode graphs, switch to: "…/FL/{event}/{episode}"
GRAPH_TEMPLATE = "http://example.org/kg/gdacs/events/flood"

# 4) Hazard taxonomy (only used to attach Group/Subgroup if present)
TAXONOMY_TTL = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/data/graphdb_import/hazard_taxonomy.ttl"

# 5) Map GDACS code -> your taxonomy class (flood-only)
HAZARD_CODE_TO_TYPE = {
    "FL": "Flood",
}

# 6) Geometry safety knobs (used when building WKT)
MAX_COORD_PAIRS = 250_000     # simplify if a geometry is massive
SIMPLIFY_TOL    = 0.00005     # ~5 m at equator
FALLBACK_TO_BBOX= True        # last resort if geometry is invalid

# =========================
# Namespaces
# =========================
EOMDG_NS = "http://example.org/eomdg/"
KG_NS    = "http://example.org/kg/"
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


# ── Date parsing ────────────────────────────────────────────────────────────
# Normalize weird GDACS dates to ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)
import datetime as _dt

_MONTHS = {
    "Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
    "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"
}

def _try_strptime(s: str, fmt: str) -> Optional[_dt.datetime]:
    try:
        return _dt.datetime.strptime(s, fmt)
    except Exception:
        return None

def _dd_mon_yyyy_hmsz(s: str) -> Optional[_dt.datetime]:
    # e.g., 08/Jul/2019 15:00:00Z   or without trailing Z
    m = re.match(r"^(\d{1,2})/([A-Za-z]{3})/(\d{4})[ T](\d{2}):(\d{2})(?::(\d{2}))?Z?$", s.strip())
    if not m:
        return None
    d, mon, y, hh, mm, ss = m.groups()
    mon_num = _MONTHS.get(mon[:3].title())
    if not mon_num:
        return None
    ss = ss or "00"
    return _dt.datetime(int(y), int(mon_num), int(d), int(hh), int(mm), int(ss))

def to_dt_literal(s: Optional[str]) -> Optional[Literal]:
    """Return xsd:dateTime literal with canonical Zulu form."""
    if not s:
        return None
    s = str(s).strip()

    # Try common ISO-ish forms first
    for fmt in ("%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d"):
        dt = _try_strptime(s.rstrip("Z"), fmt)
        if dt:
            if fmt == "%Y-%m-%d":  # date only
                dt = dt.replace(hour=0, minute=0, second=0)
            return Literal(dt.strftime("%Y-%m-%dT%H:%M:%SZ"), datatype=XSD.dateTime)

    # Try dd/Mon/yyyy HH:MM(:SS)Z
    dt = _dd_mon_yyyy_hmsz(s)
    if dt:
        return Literal(dt.strftime("%Y-%m-%dT%H:%M:%SZ"), datatype=XSD.dateTime)

    # Last resort: keep as-is but ensure trailing Z; still xsd:dateTime
    if not s.endswith("Z"):
        s += "Z"
    return Literal(s, datatype=XSD.dateTime)


def add_time_inst(g: Graph, pred: URIRef, parent: URIRef, dt_lit: Optional[Literal]):
    if not dt_lit:
        return
    inst = BNode()
    g.add((parent, pred, inst))
    g.add((inst, RDF.type, TIME.Instant))
    g.add((inst, TIME.inXSDDateTime, dt_lit))


def bbox_to_envelope_wkt(bbox) -> Optional[Literal]:
    if not bbox or len(bbox) != 4:
        return None
    minx, miny, maxx, maxy = bbox
    wkt = f"SRID=4326; POLYGON(({minx} {miny}, {maxx} {miny}, {maxx} {maxy}, {minx} {maxy}, {minx} {miny}))"
    return Literal(wkt, datatype=GEO.wktLiteral)


def wkt_with_srid(shp) -> Literal:
    try:
        wkt = wkt_dumps(shp, rounding_precision=15, trim=False)  # Shapely < 2
    except TypeError:
        wkt = shapely.to_wkt(shp, rounding_precision=15, trim=False)  # Shapely 2
    return Literal(f"SRID=4326; {wkt}", datatype=GEO.wktLiteral)


def code_to_hazard_uri(code: Optional[str]) -> Optional[URIRef]:
    if not code:
        return None
    local = HAZARD_CODE_TO_TYPE.get(str(code).upper())
    return (EOMDG[local] if local else None)


# ── Taxonomy (optional) ─────────────────────────────────────────────────────
def load_taxonomy() -> Graph:
    T = Graph()
    try:
        p = pathlib.Path(TAXONOMY_TTL)
        if p.exists():
            T.parse(str(p), format="turtle"); ensure_prefixes(T)
        else:
            print(f"[WARN] Taxonomy file not found: {p}")
    except Exception as ex:
        print(f"[WARN] Failed to parse taxonomy: {ex}")
    return T

def find_group_subgroup(T: Graph, hazard_type_uri: Optional[URIRef]) -> Tuple[Optional[URIRef], Optional[URIRef]]:
    if hazard_type_uri is None or len(T) == 0:
        return (None, None)
    g = next(T.objects(hazard_type_uri, EOMDG.inHazardGroup), None)
    sg = next(T.objects(hazard_type_uri, EOMDG.inHazardSubgroup), None)
    return (g, sg)


# ── File & JSON helpers ─────────────────────────────────────────────────────
FNAME_RX = re.compile(r'^(?P<etype>FL)_(?P<eid>\d+)_(?P<epid>\d+)\.(?:geo)?json$', re.IGNORECASE)

def parse_ids_from_filename(name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    m = FNAME_RX.match(name)
    if not m:
        return (None, None, None)
    return (m.group("etype").upper(), int(m.group("eid")), int(m.group("epid")))

def as_feature_collection(obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    t = str(obj.get("type", "")).lower()
    if t == "featurecollection" and isinstance(obj.get("features"), list):
        return obj
    if t == "feature" and isinstance(obj.get("geometry"), dict):
        return {"type": "FeatureCollection", "features": [obj]}
    if "features" in obj and isinstance(obj["features"], list):
        return {"type": "FeatureCollection", "features": obj["features"]}
    for key in ("data", "result", "geojson", "collection"):
        sub = obj.get(key)
        if isinstance(sub, dict):
            fc = as_feature_collection(sub)
            if fc:
                return fc
    if "geometry" in obj and isinstance(obj["geometry"], dict):
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": obj["geometry"], "properties": obj.get("properties", {})}]}
    return None

def load_geojsonish(path: pathlib.Path) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:
        print(f"[WARN] Failed to parse JSON: {path.name} → {ex}")
        return (None, {})
    fc = as_feature_collection(raw)
    return (fc, raw)

def coord_pairs_count(geom: Dict[str, Any]) -> int:
    cnt = 0
    def walk(c):
        nonlocal cnt
        if isinstance(c, list):
            if c and isinstance(c[0], (int, float)) and len(c) >= 2:
                cnt += 1
            else:
                for x in c: walk(x)
    walk(geom.get("coordinates", []))
    return cnt

def safe_shape(geom: Dict[str, Any], source_name: str):
    """Build a Shapely geometry defensively, simplifying if too dense."""
    # Pre-check density on raw coords (cheap)
    try:
        n = coord_pairs_count(geom)
        too_dense = (n > MAX_COORD_PAIRS)
    except Exception:
        too_dense = False

    # Build shapely
    shp = shape(geom)

    # Simplify if enormous
    if too_dense:
        try:
            shp = shp.simplify(SIMPLIFY_TOL, preserve_topology=True)
        except Exception:
            pass

    # Fix invalids
    try:
        if not shp.is_valid:
            try:
                # Shapely 2.x
                shp = shapely.make_valid(shp)  # type: ignore[attr-defined]
            except Exception:
                shp = shp.buffer(0)            # Shapely 1.8 fallback
    except Exception as ex:
        print(f"[WARN] Geometry validity check failed in {source_name}: {ex}")

    return shp


# =========================
# Core conversion (per file)
# =========================
def feature_collection_to_triples(ds: Dataset, fc: dict, T: Graph, target_graph_iri: str,
                                   source_name: str, filename_ids: Tuple[str,int,int]):
    g = ds.get_context(URIRef(target_graph_iri))
    ensure_prefixes(g)

    feats: List[Dict[str, Any]] = fc.get("features", [])
    if not feats:
        return

    # Pick the richest properties block
    props: Dict[str, Any] = {}
    for f in feats:
        p = f.get("properties") or {}
        if len(p) >= len(props):
            props = p

    # Identify eventtype / eventid / episodeid (prefer filename for consistency)
    et_fn, eid_fn, epid_fn = filename_ids
    eventtype = props.get("eventtype") or et_fn or "FL"
    eventid   = props.get("eventid")   or eid_fn
    episodeid = props.get("episodeid") or epid_fn

    # If props conflict with filename, force the filename (episode-specific truth)
    if (eid_fn is not None and episodeid is not None) and (str(eventid) != str(eid_fn) or str(episodeid) != str(epid_fn)):
        print(f"[INFO] Using IDs from filename for {source_name} (props had {eventtype}-{eventid}-{episodeid}, file has {et_fn}-{eid_fn}-{epid_fn})")
        eventtype, eventid, episodeid = et_fn, eid_fn, epid_fn

    if not (eventtype and eventid is not None and episodeid is not None):
        print(f"[INFO] Missing identifiers for {source_name} – skipped.")
        return

    # Event IRI: include episode id to keep things disjoint
    ev_iri = KG[f"{eventtype}_{eventid}_{episodeid}"]
    g.add((ev_iri, RDF.type, EOMDG.DisasterEvent))

    # Hazard typing
    haz_uri = code_to_hazard_uri(eventtype)
    if haz_uri is not None:
        g.add((ev_iri, EOMDG.hasHazardType, haz_uri))
        grp, subg = find_group_subgroup(T, haz_uri)
        if grp:  g.add((ev_iri, EOMDG.hasHazardGroup, grp))
        if subg: g.add((ev_iri, EOMDG.hasHazardSubgroup, subg))

    # GDACS identifiers
    g.add((ev_iri, EOMDG.eventType, Literal(eventtype)))
    try:
        g.add((ev_iri, EOMDG.eventId,   Literal(int(eventid))))
    except Exception:
        g.add((ev_iri, EOMDG.eventId,   Literal(str(eventid))))
    try:
        g.add((ev_iri, EOMDG.episodeId, Literal(int(episodeid))))
    except Exception:
        g.add((ev_iri, EOMDG.episodeId, Literal(str(episodeid))))

    # Simple string fields
    for key, pred in [
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
    ]:
        v = props.get(key)
        if v:
            g.add((ev_iri, pred, Literal(v)))

    # Icons / URLs
    for key, pred in [
        ("icon",         EOMDG.iconURL),
        ("iconoverall",  EOMDG.iconEventURL),
        ("iconitemlink", EOMDG.iconItemURL),
    ]:
        v = props.get(key)
        if v:
            g.add((ev_iri, pred, URIRef(v)))

    # Nested URL bundle
    url_bundle = props.get("url") or {}
    for key, pred in [("geometry", EOMDG.geometryURL),
                      ("report",   EOMDG.reportURL),
                      ("details",  EOMDG.detailsURL)]:
        v = url_bundle.get(key)
        if v:
            g.add((ev_iri, pred, URIRef(v)))

    # Alert score
    if props.get("alertscore") is not None:
        try:
            g.add((ev_iri, EOMDG.alertScore, Literal(float(props["alertscore"]))))
        except Exception:
            pass

    # Booleans
    for key, pred in [("istemporary", EOMDG.isTemporary),
                      ("iscurrent",   EOMDG.isCurrent)]:
        v = props.get(key)
        if v is not None:
            g.add((ev_iri, pred, Literal(str(v).lower() == "true", datatype=XSD.boolean)))

    # Times
    add_time_inst(g, TIME.hasBeginning, ev_iri, to_dt_literal(props.get("fromdate")))
    add_time_inst(g, TIME.hasEnd,       ev_iri, to_dt_literal(props.get("todate")))
    if props.get("polygondate"):
        g.add((ev_iri, EOMDG.polygonDate, to_dt_literal(props["polygondate"])))

    # Footprints
    wrote_any_geom = False
    for f in feats:
        geom = f.get("geometry")
        if not geom:
            continue

        bbox = f.get("bbox")
        bbox_lit = bbox_to_envelope_wkt(bbox) if bbox else None

        try:
            shp = safe_shape(geom, source_name)
        except Exception as ex:
            print(f"[WARN] Invalid geometry in {source_name}: {ex}")
            shp = None

        # If geometry still unusable, fall back to bbox if allowed
        if shp is None and FALLBACK_TO_BBOX and bbox_lit is not None:
            gnode = BNode()
            g.add((ev_iri, EOMDG.hasFootprint, gnode))
            g.add((gnode, RDF.type, EOMDG.EventFootprint))
            g.add((gnode, EOMDG.bboxEnvelope, bbox_lit))
            wrote_any_geom = True
            continue
        elif shp is None:
            continue

        gnode = BNode()
        g.add((ev_iri, EOMDG.hasFootprint, gnode))
        g.add((gnode, RDF.type, EOMDG.EventFootprint))
        g.add((gnode, GEO.asWKT, wkt_with_srid(shp)))
        wrote_any_geom = True

        props_f = f.get("properties") or {}

        lbl = props_f.get("Class")
        if lbl:
            g.add((gnode, EOMDG.classLabel, Literal(lbl)))

        plbl = props_f.get("polygonlabel")
        if plbl:
            g.add((gnode, EOMDG.polygonLabel, Literal(plbl)))

        if bbox_lit:
            g.add((gnode, EOMDG.bboxEnvelope, bbox_lit))

        if lbl == "Poly_area":
            pdate = to_dt_literal(props_f.get("polygondate"))
            if pdate:
                g.add((gnode, EOMDG.polygonDate, pdate))

        # Time on footprint
        dt = None
        if (f.get("properties") or {}).get("datetime"):
            dt = to_dt_literal(f["properties"]["datetime"])
        elif props.get("polygondate"):
            dt = to_dt_literal(props["polygondate"])
        add_time_inst(g, TIME.atTime, gnode, dt)

    # Provenance & minimal guard
    g.add((ev_iri, PROV.wasDerivedFrom, URIRef("https://www.gdacs.org/")))
    if not wrote_any_geom:
        # still keep the event node + metadata; geometry was missing/invalid
        pass


# =========================
# Runner
# =========================
def main():
    in_root  = pathlib.Path(IN_ROOT)
    out_root = pathlib.Path(OUT_ROOT)

    # Find flood *episode* files anywhere under IN_ROOT
    files = sorted(set(in_root.rglob("FL_*_*.geojson")).union(in_root.rglob("FL_*_*.json")))
    if not files:
        print(f"[INFO] No FL_*_*.geojson/.json files found under {IN_ROOT}")
        return

    T = load_taxonomy()
    converted, skipped = 0, 0

    # One dataset for all episodes if merging; otherwise we'll create per-file
    ds_merged = None
    if MERGE_OUTPUT:
        ds_merged = Dataset()
        ensure_prefixes(ds_merged)

    for f in files:
        et, eid, epid = parse_ids_from_filename(f.name)
        if not (et and eid is not None and epid is not None):
            print(f"[INFO] {f.name}: filename not in FL_<event>_<episode>.* form → skipped")
            skipped += 1
            continue

        fc, _raw = load_geojsonish(f)
        if not fc:
            print(f"[INFO] {f.name}: not GeoJSON → skipped")
            skipped += 1
            continue

        graph_iri = GRAPH_TEMPLATE.format(event=eid, episode=epid)

        if MERGE_OUTPUT:
            # accumulate into one dataset
            feature_collection_to_triples(
                ds_merged, fc, T, graph_iri,
                source_name=f.name, filename_ids=(et, eid, epid)
            )
        else:
            # write a separate TriG per input (previous behavior)
            if WRITE_NEXT_TO_INPUT:
                out_dir = f.parent
            else:
                out_dir = out_root / (f"FL_{eid}" if SPLIT_BY_EVENT else "")
            out_dir.mkdir(parents=True, exist_ok=True)

            ds = Dataset()
            ensure_prefixes(ds)
            feature_collection_to_triples(
                ds, fc, T, graph_iri,
                source_name=f.name, filename_ids=(et, eid, epid)
            )
            out_path = out_dir / f"FL_{eid}_{epid}.trig"
            ds.serialize(destination=str(out_path), format="trig")
            print(f"[OK] Wrote {out_path}")

        converted += 1

    if MERGE_OUTPUT:
        if converted == 0:
            print("[INFO] No GeoJSON features found; nothing written.")
            return
        out_path = pathlib.Path(MERGED_OUT_PATH)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ds_merged.serialize(destination=str(out_path), format="trig")
        print(f"[OK] Wrote {out_path}  (from {converted} file(s)); skipped {skipped}.")
    else:
        print(f"\n✅ Done. Converted {converted} file(s); skipped {skipped}.")


if __name__ == "__main__":
    main()
