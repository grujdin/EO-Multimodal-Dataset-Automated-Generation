import os
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union


def poslist_to_polygon(poslist_str):
    """
    Convert a GML posList string to a Shapely Polygon.
    Returns a tuple (Polygon, number_of_points) or (None, n) if there aren't enough points.
    """
    try:
        coords = poslist_str.strip().split()
        coord_pairs = [(float(coords[i]), float(coords[i + 1])) for i in range(0, len(coords), 2)]
        if len(coord_pairs) < 3:
            return None, len(coord_pairs)
        return Polygon(coord_pairs), len(coord_pairs)
    except Exception as e:
        print(f"⚠️ Error converting posList to Polygon: {e}")
        return None, 0


def save_adm2_composite_images(xml_file, output_folder, dpi=300, figsize=(16, 12)):
    """
    Parses the XML file (assumed to be a GAUL level-2 file, e.g. g2015_2014_2.xml),
    groups features by their ADM2 code (and ADM2 name), and for each ADM2 unit creates a
    high-resolution composite map that displays all component polygons for that ADM2 unit.

    Each composite map is annotated (using the centroid of the merged geometry) with the ADM2 code
    and ADM2 name, and then saved using the ADM2 code as the filename.
    """
    # Define namespaces – adjust if necessary
    namespaces = {
        'gml': 'http://www.opengis.net/gml',
        'gaul': 'http://www.fao.org/tempref/AG/Reserved/PPLPF/ftpOUT/GLiPHA/Gaulmaps/gaul_2008/documentation/GAUL%20Doc01%20Ver16.pdf',
        'wfs': 'http://www.opengis.net/wfs',
    }

    # Parse the XML file
    tree = ET.parse(xml_file)
    root = tree.getroot()

    # Create output folder if needed
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    print(f"🔹 Saving composite images in: {output_folder}")

    # Group features by ADM2 code.
    # For each feature (tag gaul:g2015_2014_2), extract:
    #   ADM2 code and ADM2 name from gaul:adm2_code and gaul:adm2_name,
    #   and the polygon geometry.
    adm2_groups = {}  # key: adm2_code; value: dict with 'adm2_name' and list of polygons.
    for feature in root.findall('.//gaul:g2015_2014_2', namespaces):
        adm2_code_el = feature.find('gaul:adm2_code', namespaces)
        adm2_name_el = feature.find('gaul:adm2_name', namespaces)

        if adm2_code_el is None:
            continue
        adm2_code = adm2_code_el.text.strip()
        adm2_name = adm2_name_el.text.strip() if adm2_name_el is not None else "Unknown_ADM2"

        polygon_elements = feature.findall('.//gml:Polygon', namespaces)
        for polygon_element in polygon_elements:
            posList_el = polygon_element.find('.//gml:posList', namespaces)
            if posList_el is None or not posList_el.text.strip():
                continue
            polygon, n_points = poslist_to_polygon(posList_el.text)
            if polygon is None:
                continue
            if adm2_code not in adm2_groups:
                adm2_groups[adm2_code] = {'adm2_name': adm2_name, 'polygons': []}
            adm2_groups[adm2_code]['polygons'].append(polygon)

    # For each ADM2 unit, create a composite map.
    for adm2_code, group in adm2_groups.items():
        polygons = group['polygons']
        if not polygons:
            print(f"⚠️ No valid polygons found for ADM2 {adm2_code}. Skipping...")
            continue

        # If there is more than one polygon, union them.
        if len(polygons) == 1:
            merged = polygons[0]
        else:
            # Fix invalid geometries with buffer(0) before unioning.
            fixed_polys = [poly if poly.is_valid else poly.buffer(0) for poly in polygons]
            try:
                merged = unary_union(fixed_polys)
            except Exception as e:
                print(f"⚠️ Error unioning polygons for ADM2 {adm2_code}: {e}")
                merged = fixed_polys[0]

        # Create a GeoDataFrame for the unioned polygon.
        gdf = gpd.GeoDataFrame({'geometry': [merged]})

        # Create a high-resolution composite map.
        fig, ax = plt.subplots(figsize=figsize)
        gdf.plot(ax=ax, color='lightblue', edgecolor='black', alpha=0.7)

        # Annotate the composite map using the centroid of the merged polygon.
        centroid = merged.centroid
        ax.annotate(f"{adm2_code}\n{group['adm2_name']}", (centroid.x, centroid.y),
                    fontsize=12, color='red', ha='center')

        ax.set_title(f"Composite Map for ADM2: {adm2_code} - {group['adm2_name']}", fontsize=16)
        ax.set_xlabel("Longitude", fontsize=14)
        ax.set_ylabel("Latitude", fontsize=14)

        output_path = os.path.join(output_folder, f"{adm2_code}.png")
        plt.savefig(output_path, dpi=dpi)
        plt.close(fig)

        print(f"🖼️ Saved composite image for ADM2 {adm2_code}: {output_path}")


# Example usage:
HOME_DIR = r"path/to/your/home/directory"
xml_file = os.path.join(HOME_DIR, "Data", "g2015_2014_2_geom_extract.xml") # Path to your GAUL XML file (ADM2-level data)
output_folder = os.path.join(HOME_DIR, "Data", "adm2_maps")  # Folder for composite images.

save_adm2_composite_images(xml_file, output_folder)
