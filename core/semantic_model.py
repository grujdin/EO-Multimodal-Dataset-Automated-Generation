from rdflib import Graph, Namespace, RDF, RDFS, URIRef, Literal
from typing import Dict, List, Optional

# Namespaces for two semantic modules
DISASTER_NS = Namespace("http://example.org/disaster#")
API_NS = Namespace("http://example.org/api#")

# ------------------------
# Generic API OWL Support
# ------------------------

def load_ontology(path: str) -> Graph:
    g = Graph()
    g.parse(path)
    return g

def extract_endpoint_fields(g: Graph) -> Dict[str, List[str]]:
    """
    Returns a mapping: {"/endpoint": ["field1", "field2", ...]}
    Derived from api:hasField relationships in the OWL model.
    """
    endpoints = {}
    for endpoint_uri in g.subjects(RDF.type, API_NS.Endpoint):
        endpoint_path = "/" + str(endpoint_uri).split("#")[-1]
        fields = []
        for field_uri in g.objects(endpoint_uri, API_NS.hasField):
            field_name = g.value(field_uri, API_NS.name)
            if field_name:
                fields.append(str(field_name))
        endpoints[endpoint_path] = sorted(fields)
    return endpoints

# ------------------------
# ReliefWeb Disaster Ontology Support
# ------------------------

def extract_disaster_types(g: Graph) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Returns a dictionary: {label: {reliefweb_id, glide_code, copernicus_link}}
    """
    disaster_types = {}
    for s in g.subjects(RDF.type, DISASTER_NS.DisasterType):
        label = str(g.value(s, RDFS.label))
        reliefweb_id = g.value(s, DISASTER_NS.reliefwebTypeId)
        glide_code = g.value(s, DISASTER_NS.glideCode)
        copernicus = g.value(s, DISASTER_NS.relatedToCopernicus)

        disaster_types[label] = {
            "reliefweb_id": str(reliefweb_id) if reliefweb_id else None,
            "glide_code": str(glide_code) if glide_code else None,
            "copernicus_link": str(copernicus) if copernicus else None
        }
    return disaster_types

def extract_gdacs_codes(g: Graph) -> Dict[str, str]:
    """
    Returns a dictionary of GDACS hazard labels to codes.
    """
    codes = {}
    for s in g.subjects(RDF.type, DISASTER_NS.GDACSHazardType):
        label = g.value(s, RDFS.label)
        code = g.value(s, DISASTER_NS.gdacsCode)
        if label and code:
            codes[str(label)] = str(code)
    return codes

def extract_themes(g: Graph) -> Dict[str, int]:
    """
    Extracts themes (e.g., Water Sanitation, Health) and their IDs.
    """
    themes = {}
    for s in g.subjects(RDF.type, DISASTER_NS.HumanitarianTheme):
        label = g.value(s, RDFS.label)
        theme_id = g.value(s, DISASTER_NS.themeId)
        if label and theme_id:
            themes[str(label)] = int(theme_id)
    return themes
