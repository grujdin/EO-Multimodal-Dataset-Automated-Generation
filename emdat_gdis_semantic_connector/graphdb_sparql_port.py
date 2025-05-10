# Integrated SPARQL, Robust Geometry Retrieval & Visualization Script

import pandas as pd
from SPARQLWrapper import SPARQLWrapper, JSON
import xml.etree.ElementTree as ET
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely import wkt
import geopandas as gpd
import matplotlib.pyplot as plt
import os

# SPARQL endpoint query to retrieve FIDs
def get_fids_from_sparql(sparql_endpoint):
    sparql = SPARQLWrapper(sparql_endpoint)
    sparql.setQuery("""
        PREFIX eomdg: <http://example.org/eomdg/>
        PREFIX gaul: <http://example.org/gaul/>

        SELECT DISTINCT ?obs ?fid2
        WHERE {
            ?obs a eomdg:DisasterObservation ;
                 eomdg:adminUnitLevel2 ?adminUnit .
            BIND(REPLACE(STR(?adminUnit), "^.+/", "") AS ?fid2)
        }
    """)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()

    return [result["fid2"]["value"] for result in results["results"]["bindings"]]

# Robust function to convert posList to Polygon
def poslist_to_polygon(poslist_str):
    try:
        coords = poslist_str.strip().split()
        coord_pairs = [(float(coords[i]), float(coords[i + 1])) for i in range(0, len(coords), 2)]
        if len(coord_pairs) < 3:
            return None
        polygon = Polygon(coord_pairs)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        return polygon if polygon.is_valid else None
    except Exception as e:
        print(f"⚠️ Error converting posList to Polygon: {e}")
        return None

# Robust geometry extraction from GAUL XML
def extract_gaul_geometries(xml_file):
    namespaces = {
        'gml': 'http://www.opengis.net/gml',
        'gaul': 'http://www.fao.org/tempref/AG/Reserved/PPLPF/ftpOUT/GLiPHA/Gaulmaps/gaul_2008/documentation/GAUL%20Doc01%20Ver16.pdf',
    }

    tree = ET.parse(xml_file)
    root = tree.getroot()

    gaul_geometries = {}
    adm2_groups = {}

    for feature in root.findall('.//gaul:g2015_2014_2', namespaces):
        adm2_code_el = feature.find('gaul:adm2_code', namespaces)
        if adm2_code_el is None:
            continue
        adm2_code = adm2_code_el.text.strip()

        polygon_elements = feature.findall('.//gml:Polygon', namespaces)
        for polygon_element in polygon_elements:
            posList_el = polygon_element.find('.//gml:posList', namespaces)
            if posList_el is None or not posList_el.text.strip():
                continue
            polygon = poslist_to_polygon(posList_el.text)
            if polygon:
                adm2_groups.setdefault(adm2_code, []).append(polygon)

    for adm2_code, polygons in adm2_groups.items():
        if len(polygons) == 1:
            merged = polygons[0]
        else:
            fixed_polygons = [p if p.is_valid else p.buffer(0) for p in polygons]
            try:
                merged = unary_union(fixed_polygons)
                if not merged.is_valid:
                    merged = merged.buffer(0)
            except Exception as e:
                print(f"⚠️ Error merging polygons for ADM2 {adm2_code}: {e}")
                merged = fixed_polygons[0]

        if merged.is_valid:
            gaul_geometries[adm2_code] = merged.wkt
        else:
            print(f"⚠️ Final merged geometry invalid for ADM2 {adm2_code}")

    return gaul_geometries


# Main execution with debug
if __name__ == "__main__":
    endpoint = "http://localhost:7200/repositories/eo_nh_kg"
    HOME_DIR = r"path/to/your/home/directory"
    gaul_xml_file = os.path.join(HOME_DIR, "data", "g2015_2014_2.xml")

    fids = get_fids_from_sparql(endpoint)
    print(f"✅ Retrieved FIDs from SPARQL ({len(fids)}): {fids[:10]}...")

    gaul_geometries = extract_gaul_geometries(gaul_xml_file)
    print(f"✅ Extracted GAUL geometries ({len(gaul_geometries)}): {list(gaul_geometries.keys())[:10]}...")

    geoms, ids, unmatched_fids = [], [], []
    for fid in fids:
        geom_wkt = gaul_geometries.get(fid)
        if geom_wkt:
            geometry = wkt.loads(geom_wkt)
            geoms.append(geometry)
            ids.append(fid)
        else:
            unmatched_fids.append(fid)

    print(f"✅ Matched geometries: {len(geoms)}")
    print(f"⚠️ Unmatched FIDs: {unmatched_fids}")

    if geoms:
        gdf = gpd.GeoDataFrame({'FID': ids, 'geometry': geoms}, crs="EPSG:4326")

        fig, ax = plt.subplots(figsize=(12, 8))
        gdf.plot(ax=ax, color='lightblue', edgecolor='black', alpha=0.7)
        ax.set_title('Disaster Observations by Administrative Unit (ADM2)', fontsize=15)
        out_png = os.path.join(HOME_DIR, 'disaster_observations.png')
        plt.savefig(out_png, dpi=300)
        plt.show()

       out_geojson = os.path.join(HOME_DIR, "disaster_observations.geojson")
        gdf.to_file(out_geojson, driver="GeoJSON")
        print("✅ Geometries visualized and saved successfully.")
    else:
        print("❌ No geometries matched; visualization skipped.")

