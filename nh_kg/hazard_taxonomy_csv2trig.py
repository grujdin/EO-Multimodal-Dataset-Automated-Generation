"""
Build a hazard taxonomy from a CSV, export TTL + TriG, and emit SHACL shapes.

This version fixes the SHACL writer bug that raised:
  ValueError: too many values to unpack (expected 3)

Cause: the previous script tried to add an entire property-shape structure
as if it were a single triple. Fix: construct each SHACL PropertyShape as a
BNode, add its triples to the shapes graph, and then link it with sh:property
from the NodeShape.

Outputs
  • TTL  → OUT_TTL
  • TriG → OUT_TRIG (named graph TARGET_GRAPH_IRI)
  • SHACL→ OUT_SHACL

Adjust the CONFIG paths below.
"""
from __future__ import annotations

import re
from typing import Dict, Tuple
import pandas as pd

from rdflib import Graph, Dataset, Namespace, URIRef, BNode, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS

# =====================
# CONFIG (edit as needed)
# =====================
CSV_PATH    = r"D:/ProjDB/EMDAT/classification_mapping.csv"
OUT_TTL     = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/data/graphdb_import/hazard_taxonomy.ttl"
OUT_TRIG    = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/data/graphdb_import/hazard_taxonomy.trig"
OUT_SHACL   = r"C:/Users/JOHN/PycharmProjects/JSTARS/.venv/data/graphdb_import/hazard_taxonomy_shapes.ttl"
EOMDG_NS    = "http://example.org/eomdg/"  # slash-form base IRI
TARGET_GRAPH_IRI = "http://example.org/kg/hazard/taxonomy"

# Optional synonym column patterns (case-insensitive). If present, split by | or ;
ALT_COLS = {
    "group":    ["group_alt", "group_synonyms"],
    "subgroup": ["subgroup_alt", "subgroup_synonyms"],
    "type":     ["type_alt", "type_synonyms"],
    "subtype":  ["subtype_alt", "subtype_synonyms"],
}

# =====================
# Namespaces
# =====================
E   = Namespace(EOMDG_NS)
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
SH  = Namespace("http://www.w3.org/ns/shacl#")

# =====================
# Helpers
# =====================

def _camel(txt: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", " ", str(txt)).title().replace(" ", "")


def _local(label: str) -> str:
    return _camel(label)


def _norm_header(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _split_alts(val: str) -> list[str]:
    return [a.strip() for a in re.split(r"[|;]", str(val)) if a and a.strip()]

# =====================
# Core builder
# =====================

def build_taxonomy():
    # Load CSV (as strings, keep empty as empty strings)
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    # Normalize headers
    df.rename(columns={c: _norm_header(c) for c in df.columns}, inplace=True)

    required = {"key", "group", "subgroup", "type", "subtype"}
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    # Main taxonomy graph (Turtle)
    g = Graph()
    g.bind("eomdg", E)
    g.bind("rdfs", RDFS)
    g.bind("owl", OWL)
    g.bind("skos", SKOS)

    # Meta-classes (declared in ontology; we type against them for discovery)
    META = {
        "group": E.HazardGroup,
        "subgroup": E.HazardSubgroup,
        "type": E.HazardType,
        "subtype": E.HazardSubtype,
    }

    nodes: Dict[Tuple[str, str], URIRef] = {}  # (level, label) → URI
    notation_index: Dict[str, URIRef] = {}     # skos:notation → URI (dup check)

    def get_or_create(level: str, label: str) -> URIRef:
        key = (level, label)
        if key in nodes:
            return nodes[key]
        uri = URIRef(E[_local(label)])
        g.add((uri, RDF.type, OWL.Class))
        g.add((uri, RDF.type, META[level]))
        g.add((uri, RDFS.label, Literal(label)))
        g.add((uri, SKOS.prefLabel, Literal(label)))
        nodes[key] = uri
        return uri

    # Build hierarchy and attach notation on leaf
    for _, row in df.iterrows():
        grp_label  = row.get("group", "").strip()
        subg_label = row.get("subgroup", "").strip()
        typ_label  = row.get("type", "").strip()
        sub_label  = row.get("subtype", "").strip()
        key_val    = row.get("key", "").strip()

        if not grp_label or not subg_label or not typ_label:
            # Skip incomplete rows
            continue

        grp  = get_or_create("group", grp_label)
        subg = get_or_create("subgroup", subg_label)
        typ  = get_or_create("type", typ_label)

        # Subclassing + SKOS broader
        g.add((subg, RDFS.subClassOf, grp))
        g.add((subg, SKOS.broader, grp))
        g.add((typ,  RDFS.subClassOf, subg))
        g.add((typ,  SKOS.broader, subg))

        leaf_uri = typ
        if sub_label:
            sub = get_or_create("subtype", sub_label)
            g.add((sub, RDFS.subClassOf, typ))
            g.add((sub, SKOS.broader, typ))
            leaf_uri = sub

        # Attach synonyms/altlabels if present
        for lvl, uri in (("group", grp), ("subgroup", subg), ("type", typ)):
            for col in ALT_COLS.get(lvl, []):
                coln = _norm_header(col)
                if coln in df.columns and row.get(coln):
                    for alt in _split_alts(row[coln]):
                        g.add((uri, SKOS.altLabel, Literal(alt)))
        if sub_label:
            for col in ALT_COLS.get("subtype", []):
                coln = _norm_header(col)
                if coln in df.columns and row.get(coln):
                    for alt in _split_alts(row[coln]):
                        g.add((leaf_uri, SKOS.altLabel, Literal(alt)))

        # Attach skos:notation to the leaf; enforce uniqueness
        if key_val:
            if key_val in notation_index:
                other = notation_index[key_val]
                raise ValueError(
                    f"Duplicate skos:notation '{key_val}' for {leaf_uri} (already used by {other})"
                )
            notation_index[key_val] = leaf_uri
            g.add((leaf_uri, SKOS.notation, Literal(key_val)))
        else:
            # No key provided: continue; SHACL will flag subtypes w/o notation if needed
            pass

    # Write TTL
    g.serialize(destination=OUT_TTL, format="turtle")
    print(f"✅ Wrote taxonomy TTL → {OUT_TTL}")

    # Also export TriG with a named graph
    ds = Dataset()
    ds.bind("eomdg", E)
    ds.bind("rdfs", RDFS)
    ds.bind("owl", OWL)
    ds.bind("skos", SKOS)
    ctx = ds.get_context(URIRef(TARGET_GRAPH_IRI))
    for t in g:
        ctx.add(t)
    ds.serialize(destination=OUT_TRIG, format="trig")
    print(f"✅ Wrote taxonomy TriG → {OUT_TRIG} (graph {TARGET_GRAPH_IRI})")

    # Emit SHACL shapes to validate hierarchy & labels & notation
    shapes = Graph()
    shapes.bind("sh", SH)
    shapes.bind("eomdg", E)
    shapes.bind("rdfs", RDFS)
    shapes.bind("skos", SKOS)

    def prop_shape(path_predicate: URIRef, **constraints) -> BNode:
        """Create a SHACL PropertyShape as a BNode, add its triples, and return it."""
        b = BNode()
        shapes.add((b, RDF.type, SH.PropertyShape))
        shapes.add((b, SH.path, path_predicate))
        for k, v in constraints.items():
            shapes.add((b, getattr(SH, k), v))
        return b

    def add_shape(node_shape_uri: URIRef, target_class: URIRef, property_nodes: list[BNode]):
        """Attach property shapes to a SHACL NodeShape and set target class."""
        shapes.add((node_shape_uri, RDF.type, SH.NodeShape))
        shapes.add((node_shape_uri, SH.targetClass, target_class))
        for pnode in property_nodes:
            shapes.add((node_shape_uri, SH.property, pnode))

    # Common property shapes
    ps_label_required = prop_shape(RDFS.label, minCount=Literal(1))

    # subtype must have rdfs:subClassOf some HazardType, and skos:notation present
    ps_sub_super        = prop_shape(RDFS.subClassOf, minCount=Literal(1))
    ps_sub_super_class  = prop_shape(RDFS.subClassOf, **{"class": E.HazardType})
    ps_sub_notation     = prop_shape(SKOS.notation, minCount=Literal(1))

    # type must have rdfs:subClassOf some HazardSubgroup
    ps_type_super       = prop_shape(RDFS.subClassOf, minCount=Literal(1))
    ps_type_super_class = prop_shape(RDFS.subClassOf, **{"class": E.HazardSubgroup})

    # subgroup must have rdfs:subClassOf some HazardGroup
    ps_subg_super       = prop_shape(RDFS.subClassOf, minCount=Literal(1))
    ps_subg_super_class = prop_shape(RDFS.subClassOf, **{"class": E.HazardGroup})

    # Node shapes
    add_shape(URIRef(E["SH_SubtypeShape"]), E.HazardSubtype,
              [ps_label_required, ps_sub_super, ps_sub_super_class, ps_sub_notation])
    add_shape(URIRef(E["SH_TypeShape"]), E.HazardType,
              [ps_label_required, ps_type_super, ps_type_super_class])
    add_shape(URIRef(E["SH_SubgroupShape"]), E.HazardSubgroup,
              [ps_label_required, ps_subg_super, ps_subg_super_class])
    add_shape(URIRef(E["SH_GroupShape"]), E.HazardGroup,
              [ps_label_required])

    shapes.serialize(destination=OUT_SHACL, format="turtle")
    print(f"✅ Wrote SHACL shapes TTL → {OUT_SHACL}")


if __name__ == "__main__":
    build_taxonomy()
