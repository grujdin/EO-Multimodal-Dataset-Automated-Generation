# graphdb_loader_multi.py  — reload multiple files/graphs (hard-coded)
# Clears only the named graphs listed in LOADS, then reloads those files.
# Version 1.0 Date 08/14/2025

import os
from pathlib import Path
import requests
import sys

# ── Hard-coded repo/server ────────────────────────────────────────────────
REPO_ID = "eo_nh_kg"
BASE    = "http://localhost:7200"

# Optional basic auth via env (leave unset if GraphDB is open)
AUTH = None
if os.environ.get("GRAPHDB_USER") and os.environ.get("GRAPHDB_PASS"):
    AUTH = (os.environ["GRAPHDB_USER"], os.environ["GRAPHDB_PASS"])

GEO_ENABLE = True  # set False to skip

def sparql_update(update: str):
    # Try normal SPARQL Update; fall back to form-encoded
    r = requests.post(
        STATEMENTS,
        headers={"Content-Type": "application/sparql-update"},
        data=update, auth=AUTH,
    )
    if r.status_code in (200, 204):
        return
    r = requests.post(
        STATEMENTS,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"update": update}, auth=AUTH,
    )
    if r.status_code in (200, 204):
        return
    raise RuntimeError(f"SPARQL update failed: {r.status_code} {r.text[:300]}")

def enable_geosparql():
    if not GEO_ENABLE:
        print("ℹ️  Skipping GeoSPARQL enable.")
        return
    print("→ Enabling GeoSPARQL plugin …")
    prefix = "PREFIX geosparql: <http://www.ontotext.com/plugins/geosparql#>\n"
    # Enable
    sparql_update(prefix + 'INSERT DATA { [] geosparql:enabled "true" . }')
    # Optional speed-ups / tuning (comment out if you don’t want them)
    # sparql_update(prefix + 'INSERT DATA { [] geosparql:ramBufferSizeMB "256.0" . }')
    # sparql_update(prefix + 'INSERT DATA { [] geosparql:maxBufferedDocs "3000" . }')
    # sparql_update(prefix + 'INSERT DATA { [] geosparql:prefixTree "geohash" . }')
    # sparql_update(prefix + 'INSERT DATA { [] geosparql:precision "20" . }')
    print("✅ GeoSPARQL enabled (and will index data as it’s loaded).")


###########################################################
# Set WIPE_MODE to:
# "graphs" – clear only the graphs in LOADS (default),
# "repo"   – wipe the whole repository (rarely needed),
# "none"   – just load (useful for incremental adds).
###########################################################
WIPE_MODE = "repo"

# Stop on the first loading error?
STOP_ON_ERROR = True

# ── Files & target graphs (edit this list) ────────────────────────────────
# For each entry: ("path/to/file.ext", "named-graph-IRI")
# Use graph=None to load into the default graph (no CLEAR done for None).
LOADS = [
    (r"data/graphdb_import/eomdg_ontology.ttl",
     "http://example.org/kg/eomdg/ontology"),

    # Use TriG for taxonomy
    (r"data/graphdb_import/hazard_taxonomy.trig",
     "http://example.org/kg/hazard/taxonomy"),

    # Use TriG for EM-DAT events
    (r"data/graphdb_import/emdat_events_all.trig",
     "http://example.org/kg/emdat/events/all"),

    # Use TriG for GDACS wildfire events
    (r"data/graphdb_import/gdacs_events_wildfire.trig",
     "http://example.org/kg/gdacs/events/wildfire"),

    # Use TriG for GDACS flood events
    (r"data/graphdb_import/gdacs_events_flood.trig",
     "http://example.org/kg/gdacs/events/flood"),

    (r"data/graphdb_import/hazard_taxonomy_shapes.ttl", # GraphDB’s SHACL engine will check your taxonomy graph each time you load/update it and list any violations.
     "http://rdf4j.org/schema/shacl#ShapesGraph")  # GraphDB’s default shapes IRI
]

# ── Endpoints & MIME map ─────────────────────────────────────────────────
REST_LIST     = f"{BASE}/rest/repositories"
REST_ONE      = f"{BASE}/rest/repositories/{REPO_ID}"
STATEMENTS    = f"{BASE}/repositories/{REPO_ID}/statements"
SIZE_ENDPOINT = f"{BASE}/repositories/{REPO_ID}/size"

MIME_BY_EXT = {
    ".ttl":   "text/turtle",
    ".trig":  "application/trig",
    ".nq":    "application/n-quads",
    ".nt":    "application/n-triples",
    ".rdf":   "application/rdf+xml",
    ".owl":   "application/rdf+xml",
    ".jsonld":"application/ld+json",
    ".n3":    "text/n3",
}

# ── Helpers ───────────────────────────────────────────────────────────────
def repo_exists() -> bool:
    try:
        r = requests.get(REST_ONE, auth=AUTH, timeout=5)
        if r.status_code == 200:
            return True
    except Exception:
        pass
    try:
        r = requests.get(REST_LIST, auth=AUTH, timeout=5)
        if r.status_code == 200:
            for item in r.json():
                if item.get("id") == REPO_ID:
                    return True
    except Exception:
        pass
    try:
        r = requests.get(SIZE_ENDPOINT, auth=AUTH, headers={"Accept": "text/plain"}, timeout=5)
        if r.status_code == 200:
            return True
    except Exception:
        pass
    return False

def wipe_repo():
    print(f"→ Wiping entire repo {REPO_ID} ...")
    for body in ("CLEAR ALL", "DROP ALL", "DELETE WHERE { ?s ?p ?o }"):
        r = requests.post(STATEMENTS,
                          headers={"Content-Type": "application/sparql-update"},
                          data=body, auth=AUTH)
        if r.status_code in (200, 204):
            print(f"✅ Repo wipe ok: {body}")
            return
        if r.status_code == 415:
            r = requests.post(STATEMENTS,
                              headers={"Content-Type": "application/x-www-form-urlencoded"},
                              data={"update": body}, auth=AUTH)
            if r.status_code in (200, 204):
                print(f"✅ Repo wipe (form) ok: {body}")
                return
        print(f"… {body} → {r.status_code}: {r.text[:200]}")
    raise RuntimeError("Failed to wipe repository.")

def clear_graph(graph_iri: str):
    print(f"→ Clearing graph <{graph_iri}> ...")
    update = f"CLEAR GRAPH <{graph_iri}>"
    r = requests.post(STATEMENTS,
                      headers={"Content-Type": "application/sparql-update"},
                      data=update, auth=AUTH)
    if r.status_code in (200, 204):
        print("✅ Cleared")
        return
    # Fallback (form)
    r = requests.post(STATEMENTS,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"update": update}, auth=AUTH)
    if r.status_code in (200, 204):
        print("✅ Cleared (form)")
        return
    raise RuntimeError(f"Failed to clear <{graph_iri}>: {r.status_code} {r.text[:200]}")

def load_file(path: Path, graph_iri: str | None):
    ext = path.suffix.lower()
    mime = MIME_BY_EXT.get(ext)
    if not mime:
        raise ValueError(f"No MIME mapping for {ext} ({path})")

    # TriG/N-Quads carry contexts themselves: do NOT pass a context param
    trig_like = ext in (".trig", ".nq")

    params = {}
    if graph_iri and not trig_like:
        # For Turtle and friends, load into this named context
        params["context"] = f"<{graph_iri}>"

    target_txt = (f" into <{graph_iri}>" if (graph_iri and not trig_like) else
                  " (contexts from file)" if trig_like else
                  " into default graph")

    print(f"→ Loading {path} (as {mime}){target_txt}")
    with open(path, "rb") as fh:
        r = requests.post(STATEMENTS,
                          headers={"Content-Type": mime},
                          params=params,
                          data=fh, auth=AUTH)
    if r.status_code == 204:
        print(f"✅ Loaded: {path.name}")
    else:
        print(f"❌ Failed: {path.name} ({r.status_code})\n{r.text}")
        r.raise_for_status()

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    print(f"→ Checking repository {REPO_ID} at {BASE} ...")
    if not repo_exists():
        print("❌ Repository not found or server unreachable.")
        print(f"   Check {BASE}/rest/repositories or {SIZE_ENDPOINT}")
        sys.exit(1)

    # Validate files before any wipe
    for f, _g in LOADS:
        p = Path(f)
        if not p.exists():
            print(f"❌ File not found: {p}")
            sys.exit(1)

    # Wipe strategy
    if WIPE_MODE == "repo":
        wipe_repo()
    elif WIPE_MODE == "graphs":
        # Clear each unique non-None graph once
        to_clear = {g for _, g in LOADS if g}
        for g in to_clear:
            clear_graph(g)
    else:
        print("ℹ️  No wipe requested (WIPE_MODE='none').")

    # Ensure GeoSPARQL is on before loading data
    enable_geosparql()

    # Load in order
    for f, g in LOADS:
        try:
            load_file(Path(f), g)
        except Exception as e:
            if STOP_ON_ERROR:
                raise
            else:
                print(f"[WARN] Continuing after error: {e}")

    print("✅ Done.")

if __name__ == "__main__":
    main()
