# observations2rdf_triples.py
"""
Convert public_emdat_gdis_gaul_fids.xlsx into RDF instances,
ensuring event‐level triples are emitted only once.
"""
import re, calendar, pathlib
import pandas as pd
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, XSD
import os

# 1) CONFIG
HOME_DIR = r"path/to/your/home/directory"
SPREADSHEET = os.path.join(HOME_DIR, "Data", "public_emdat_gdis_gaul_fids.xlsx")
MAP_CSV     = os.path.join(HOME_DIR, "Data", "classification_mapping.csv")
OUT_TTL     = os.path.join(HOME_DIR, "Data", "emdat_gdis_gaul_observations.ttl")

# 2) NAMESPACES
E    = Namespace("http://example.org/eomdg/")
GAUL = Namespace("http://example.org/gaul/")
CONT = Namespace("http://example.org/continent/")
SUBC = Namespace("http://example.org/subcontinent/")
GEO  = Namespace("http://www.opengis.net/ont/geosparql#")
TIME = Namespace("http://www.w3.org/2006/time#")

# 3) HELPERS
def camel(txt: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", " ", txt).title().replace(" ", "")

def safe_date(y, m, d, is_start):
    if pd.isna(y):
        return None
    Y = int(y)
    if pd.isna(m):
        M, q = (1 if is_start else 12), "inferred"
    else:
        M, q = int(m), "reported"
    if pd.isna(d):
        D, q = (1 if is_start else calendar.monthrange(Y, M)[1]), "inferred"
    else:
        D = int(d)
    lit = Literal(f"{Y:04d}-{M:02d}-{D:02d}", datatype=XSD.date)
    return lit, Literal(q)

# 4) LOAD LOOKUPS
map_df = pd.read_csv(MAP_CSV).set_index("key")
df     = pd.read_excel(SPREADSHEET)

# 5) BUILD GRAPH
g = Graph()
for prefix, ns in [
    ("eomdg", E), ("gaul", GAUL),
    ("cont", CONT), ("subc", SUBC),
    ("geo", GEO),  ("time", TIME),
    ("rdfs", RDFS)
]:
    g.bind(prefix, ns)

# quality flags
for p in ("startDateQuality","endDateQuality"):
    g.add((E[p], RDF.type, RDF.Property))
    g.add((E[p], RDFS.label, Literal(p)))

processed_events = set()

for _, row in df.iterrows():
    obs = URIRef(E[f"Observation/{row['Unique Code']}"])
    evt = URIRef(E[f"DisasterEvent/{row['DisNo.']}"])

    # OBSERVATION‐level
    g.add((obs, RDF.type, E.DisasterObservation))
    g.add((obs, E.relatedEvent, evt))
    if pd.notna(row.get("Location")):
        g.add((obs, E.locationName, Literal(row["Location"])))

    if pd.notna(row["FID_1"]):
        a1 = URIRef(GAUL[f"AdminUnit/{int(row['FID_1'])}"])
        g.add((obs, E.adminUnitLevel1, a1))
    if pd.notna(row["FID_2"]):
        a2 = URIRef(GAUL[f"AdminUnit/{int(row['FID_2'])}"])
        g.add((obs, E.adminUnitLevel2, a2))

    # EVENT‐level (once)
    if evt not in processed_events:
        processed_events.add(evt)
        g.add((evt, RDF.type, E.DisasterEvent))
        if pd.notna(row.get("Event Name")):
            g.add((evt, RDFS.label, Literal(row["Event Name"])))

        if pd.notna(row.get("External IDs")):
            for eid in str(row["External IDs"]).split(","):
                g.add((evt, E.externalID, Literal(eid.strip())))

        if pd.notna(row.get("ISO")):
            g.add((evt, E.countryCode, Literal(row["ISO"])))

        for col, p in [("Entry Date","entryDate"),("Last Update","lastUpdate")]:
            if pd.notna(row.get(col)):
                ts = pd.to_datetime(row[col]).isoformat()
                g.add((evt, E[p], Literal(ts, datatype=XSD.dateTime)))

        # hazard hierarchy
        key = str(row["Classification Key"]).strip()
        if key not in map_df.index:
            print("⚠ Unmapped classification key:", key)
        else:
            rec = map_df.loc[key]
            grp  = URIRef(E[camel(rec.group)])
            subg = URIRef(E[camel(rec.subgroup)])
            typ  = URIRef(E[camel(rec.type)])
            sub  = URIRef(E[camel(rec.subtype)])
            for prop, uri in [
                (E.hasHazardGroup, grp),
                (E.hasHazardSubgroup, subg),
                (E.hasHazardType, typ),
                (E.hasHazardSubtype, sub)
            ]:
                g.add((evt, prop, uri))

        # administrative areas
        if pd.notna(row.get("Country")):
            c = URIRef(E[camel(row["Country"])])
            g.add((evt, E.affectedCountry, c))
        if pd.notna(row.get("Region")):
            co = URIRef(CONT[camel(row["Region"])])
            g.add((evt, E.affectedContinent, co))
        if pd.notna(row.get("Subregion")):
            sc = URIRef(SUBC[camel(row["Subregion"])])
            g.add((evt, E.affectedSubregion, sc))

        # point geometry
        lat, lon = row.get("Latitude"), row.get("Longitude")
        if pd.notna(lat) and pd.notna(lon):
            pt = BNode()
            g.add((pt, RDF.type, GEO.Geometry))
            g.add((pt, GEO.asWKT,
                   Literal(f"POINT({lon} {lat})", datatype=GEO.wktLiteral)))
            g.add((evt, E.hasLocationGeometry, pt))

        # temporal
        def add_time(prop, y,m,d, start):
            sd = safe_date(y,m,d,start)
            if not sd:
                return
            dat, qual = sd
            inst = BNode()
            g.add((inst, RDF.type, TIME.Instant))
            g.add((inst, TIME.inXSDDate, dat))
            g.add((evt, prop, inst))
            g.add((evt,
                   E["startDateQuality" if start else "endDateQuality"],
                   qual))

        add_time(TIME.hasBeginning, row["Start Year"], row["Start Month"], row["Start Day"], True)
        add_time(TIME.hasEnd,       row["End Year"],   row["End Month"],   row["End Day"],   False)

# 6) SERIALIZE
pathlib.Path(OUT_TTL).write_text(g.serialize(format="turtle"), encoding="utf-8")
print("✅ Enhanced TTL written to", OUT_TTL)
