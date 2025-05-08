import rdflib
from rdflib.namespace import RDF, RDFS, OWL, SKOS
from pathlib import Path

ONTOLOGY_PATH = Path("ontologies/objectives.owl")

class ReasoningEngine:
    def __init__(self, ontology_path=ONTOLOGY_PATH):
        self.graph = rdflib.Graph()
        self.graph.parse(ontology_path, format="turtle")

    def get_subclasses(self, superclass_uri):
        query = f"""
        SELECT ?subclass ?label WHERE {{
            ?subclass rdfs:subClassOf <{superclass_uri}> .
            OPTIONAL {{ ?subclass rdfs:label ?label }}
        }}
        """
        results = self.graph.query(query)
        return [(str(row.subclass), str(row.label) if row.label else None) for row in results]

    def get_required_apis_for_task(self, task_uri):
        query = f"""
        SELECT ?api ?label WHERE {{
            <{task_uri}> <http://example.org/objectives#usesAPI> ?api .
            OPTIONAL {{ ?api rdfs:label ?label }}
        }}
        """
        results = self.graph.query(query)
        return [(str(row.api), str(row.label) if row.label else None) for row in results]

    def get_modalities_for_dataset(self, dataset_uri):
        query = f"""
        SELECT ?modality ?label WHERE {{
            <{dataset_uri}> <http://example.org/objectives#hasModality> ?modality .
            OPTIONAL {{ ?modality rdfs:label ?label }}
        }}
        """
        results = self.graph.query(query)
        return [(str(row.modality), str(row.label) if row.label else None) for row in results]
