# modules/sparql_engine.py
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS
import pandas as pd

API = Namespace("http://example.org/api#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
GN = Namespace("http://sws.geonames.org/")


def load_graph(path) -> Graph:
    g = Graph()
    if hasattr(path, "name"):  # UploadedFile
        format = "turtle" if path.name.endswith(".ttl") else "xml"
    else:  # str or Path
        format = "turtle" if str(path).endswith(".ttl") else "xml"
    g.parse(path, format=format)
    return g




def run_query(graph: Graph, query: str) -> pd.DataFrame:
    """Execute a SPARQL query and return results as a DataFrame."""
    results = graph.query(query)
    return pd.DataFrame(results.bindings)


def get_fields_for_endpoint(graph: Graph, endpoint: str, lang: str = "en") -> list:
    """
    Returns a list of (field name, label) tuples for the given endpoint and language.
    """
    endpoint_uri = API[endpoint.strip("/")]
    results = []
    for field in graph.objects(endpoint_uri, API.hasField):
        name = graph.value(field, API.name)
        label = graph.value(field, SKOS.prefLabel, lang=lang) or name
        if name:
            results.append((str(name), str(label)))
    return results


def get_country_labels(graph: Graph, lang: str = "en") -> list:
    """Return a list of (geoname URI, label) for countries in the given language."""
    query = f"""
    SELECT ?country ?label WHERE {{
      ?country a skos:Concept ;
               skos:prefLabel ?label .
      FILTER(lang(?label) = "{lang}")
    }}
    ORDER BY ?label
    """
    return run_query(graph, query).values.tolist()
