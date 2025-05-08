import rdflib
from rdflib import Graph, Namespace, RDF, RDFS, Literal, URIRef
import time

def store_tentative_concept(user_input: str, output_file="user_defined_concepts_store.ttl"):
    """
    Store a user free input as a new 'TentativeConcept' in a separate Turtle file,
    checking if an identical rdfs:label already exists (to avoid duplicates).

    Returns:
      - The new concept URIRef if created
      - None if the label already existed
    """

    user_input = user_input.strip()
    if not user_input:
        return None

    g = Graph()
    try:
        g.parse(output_file, format="turtle")
    except FileNotFoundError:
        pass  # If there's no existing file, we'll create it fresh.

    DISASTER_NS = Namespace("http://example.org/disaster#")

    # 1) Check if any resource already has rdfs:label == user_input
    for s, p, o in g.triples((None, RDFS.label, Literal(user_input))):
        # If found, skip adding a duplicate
        print(f"[store_tentative_concept] '{user_input}' already in RDF: {s}")
        return None

    # 2) If not found, create a new resource with a unique IRI
    new_iri = URIRef(f"http://example.org/disaster#Tentative_{int(time.time())}")
    g.add((new_iri, RDF.type, DISASTER_NS.TentativeConcept))
    g.add((new_iri, RDFS.label, Literal(user_input)))

    g.serialize(destination=output_file, format="turtle")
    return new_iri
