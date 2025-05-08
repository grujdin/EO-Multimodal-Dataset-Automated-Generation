# ──────────────────────────────────────────────────────────────
# build_hazard_taxonomy.py
# ──────────────────────────────────────────────────────────────
"""
Create a full hazard hierarchy TTL from the classification_mapping.csv.

CSV REQUIRED COLUMNS
--------------------
key, group, subgroup, type, subtype
Optional: sensor, objective   (pipe-separated lists)

OUTPUT
------
hazard_taxonomy.ttl   (load before any instance data)
"""
import re, csv, pathlib
import rdflib
from rdflib import Namespace, RDF, RDFS, OWL, Literal, URIRef

# ---------------------------------------------------------------------- paths
CSV_FILE = r"C:/Users/JOHN/OneDrive/ProjDB/EMDAT/classification_mapping.csv"
TTL_OUT  = r"C:/Users/JOHN/OneDrive/ProjDB/EMDAT/hazard_taxonomy.ttl"

E = Namespace("http://example.org/eomdg/")

# ---------------------------------------------------------------- CamelCase fn
def camel(txt: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", " ", txt).title().replace(" ", "")

# ------------------------------------------------------------------ rdflib G
g = rdflib.Graph()
g.bind("eomdg", E); g.bind("rdfs", RDFS); g.bind("owl", OWL)

CLS = {
    "group":    E.HazardGroup,
    "subgroup": E.HazardSubgroup,
    "type":     E.HazardType,
    "subtype":  E.HazardSubtype,
}

# keep track to avoid duplicate rdfs:label triples
declared = set()

with open(CSV_FILE, newline="", encoding="utf-8") as fh:
    rdr = csv.DictReader(fh)
    for row in rdr:
        uris = {
            level: URIRef(E[camel(row[level])])
            for level in ("group", "subgroup", "type", "subtype")
        }

        # declare classes + label (only once)
        for lvl, uri in uris.items():
            if uri not in declared:
                g.add((uri, RDF.type, CLS[lvl]))
                g.add((uri, RDFS.label, Literal(row[lvl])))
                declared.add(uri)

        # hierarchy
        # only SUBGROUP ⊑ GROUP
        g.add((uris["subgroup"], RDFS.subClassOf, uris["group"]))

        # TYPE ⊑ SUBGROUP  (not directly under GROUP!)
        g.add((uris["type"],     RDFS.subClassOf, uris["subgroup"]))

        # SUBTYPE ⊑ TYPE
        g.add((uris["subtype"],  RDFS.subClassOf, uris["type"]))

        # optional sensor / objective links
        if row.get("sensor"):
            for s in row["sensor"].split("|"):
                g.add((uris["type"], E.isMonitoredBy, URIRef(E[camel(s)])))
        if row.get("objective"):
            for o in row["objective"].split("|"):
                g.add((uris["type"], E.hasRelatedObjective, URIRef(E[camel(o)])))

# --------------------------------------------------------------- write TTL
path = pathlib.Path(TTL_OUT)

g.serialize(destination=str(path), format="turtle")
print("✅  taxonomy written to:", path)
