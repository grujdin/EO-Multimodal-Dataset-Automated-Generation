# 🌍 Ontology-Driven API Explorer

This project enables dynamic interaction with any OpenAPI/Swagger-based data service (e.g., ReliefWeb, GDACS, NASA, ESA) using:
- ✅ API descriptions (Swagger/OpenAPI 2.0 YAML)
- ✅ Ontologies (OWL/RDF) to enrich parameter values
- ✅ A clean, extensible Streamlit interface

---

## 🗂️ Project Structure

```
project/
├── reliefweb_query_ui.py        # Main Streamlit app
├── modules/
│   ├── swagger_loader.py        # Parses Swagger YAML and extracts endpoints/params
│   ├── ontology_helper.py       # Loads .owl/.rdf files and returns disaster/themes metadata
│   ├── query_executor.py        # Prepares requests and formats results
│   ├── config.py                # Central constants
│   └── history.py               # Saves recent query history to local file
├── output/                      # Generated CSVs
├── swagger.yaml                 # Example Swagger file (ReliefWeb)
├── disaster_types.owl|rdf       # Example ontologies
├── query_history.json           # Optional saved history
```

---

## 🚀 How to Use

### 1. Launch the Streamlit App
```bash
streamlit run reliefweb_query_ui.py
```

### 2. Upload Files
- Swagger YAML: defines the API (e.g., ReliefWeb)
- Ontology: optional .owl/.rdf to enhance suggestions

### 3. Select an Endpoint
- The UI will generate input forms for parameters based on the Swagger definition.

### 4. Fill Parameters
- Suggested values (e.g., themes, disaster types) are auto-filled from ontology.

### 5. Run & Export
- Preview the URL → Send API Request → View Results → Download CSV

---

## 🔌 Plug in Your Own API
Just point the app to your Swagger file:
```bash
streamlit run reliefweb_query_ui.py -- --swagger my_api.yaml
```

To add custom ontologies, ensure they use common RDF/OWL structure with `rdfs:label` and properties like `reliefwebTypeId`, `themeId`, etc.

---

## 🧠 Future Ideas
- Semantic linking across APIs
- Pre-trained mappings from ontologies to API parameter fields
- Visual history dashboard for reproducibility

---

Made with ❤️ for humanitarian and scientific data exploration.

