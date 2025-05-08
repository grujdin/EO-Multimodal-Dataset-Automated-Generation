import rdflib
from rdflib import Namespace, RDF, RDFS, URIRef
from rdflib.namespace import SKOS

# Define namespaces for semantic roles
EX = Namespace("http://example.org/semui#")
ML = Namespace("http://example.org/ml#")
HAZ = Namespace("http://example.org/hazard#")

# Create ontology-backed goal frame
class SemanticGoal:
    def __init__(self, text):
        self.text = text
        self.graph = rdflib.Graph()
        self.graph.bind("ex", EX)
        self.graph.bind("ml", ML)
        self.graph.bind("haz", HAZ)
        self.task = URIRef("http://example.org/goal/Task1")
        self._parse_text_to_graph()

    def _parse_text_to_graph(self):
        """Mock parser for demo purposes. In practice, use NLP + concept matching."""
        if "generate" in self.text.lower():
            self.graph.add((self.task, RDF.type, EX.DatasetGenerationTask))

        if "multimodal" in self.text.lower():
            self.graph.add((self.task, EX.produces, EX.MultimodalDataset))
            self.graph.add((EX.MultimodalDataset, RDF.type, EX.Dataset))

        if "model" in self.text.lower():
            self.graph.add((self.task, EX.supports, ML.ModelTrainingObjective))

        if "flood" in self.text.lower():
            self.graph.add((self.task, EX.relatedToHazard, HAZ.RiverineFlood))
            self.graph.add((HAZ.RiverineFlood, SKOS.broader, HAZ.Flood))
            self.graph.add((HAZ.Flood, RDF.type, HAZ.HydroHazard))

    def serialize(self, format="turtle"):
        return self.graph.serialize(format=format, encoding="utf-8").decode("utf-8")

    def get_api_recommendations(self):
        apis = set()
        if (self.task, EX.produces, EX.MultimodalDataset) in self.graph:
            apis.update(["sentinelhub", "reliefweb"])
        if (self.task, EX.relatedToHazard, HAZ.RiverineFlood) in self.graph:
            apis.add("gdacs")
        return sorted(apis)


# Example usage (temporary CLI test)
if __name__ == "__main__":
    goal_text = "Generate a multimodal dataset to train a deep learning model to detect river floods."
    goal = SemanticGoal(goal_text)
    print("\n📌 RDF Frame:")
    print(goal.serialize())
    print("\n🔌 Recommended APIs:", goal.get_api_recommendations())
