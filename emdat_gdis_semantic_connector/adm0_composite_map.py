import os
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union
import matplotlib.patches as mpatches
import time

def poslist_to_polygon(poslist_str):
    """
    Convert a GML posList string to a Shapely Polygon.
    Returns a tuple (Polygon, number_of_points) or (None, n) if there aren't enough points.
    """
    try:
        coords = poslist_str.strip().split()
        coord_pairs = [(float(coords[i]), float(coords[i+1])) for i in range(0, len(coords), 2)]
        if len(coord_pairs) < 3:
            return None, len(coord_pairs)
        return Polygon(coord_pairs), len(coord_pairs)
    except Exception as e:
        print(f"⚠️ Error converting posList to Polygon: {e}")
        return None, 0

def save_adm0_composite_images(xml_file, output_folder, dpi=500, figsize=(40, 30)):
    """
    Parses the GAUL level-1 XML file (g2015_2014_1.xml), groups features by their ADM0 unit (from
    gaul:adm0_code/adm0_name), and for each ADM0 unit creates a high-resolution composite map that displays
    all inner ADM1 units (from gaul:adm1_code/adm1_name).

    Debug messages are added to track progress.
    """
    # Define namespaces
    namespaces = {
        'gml': 'http://www.opengis.net/gml',
        'gaul': 'http://www.fao.org/tempref/AG/Reserved/PPLPF/ftpOUT/GLiPHA/Gaulmaps/gaul_2008/documentation/GAUL%20Doc01%20Ver16.pdf',
        'wfs': 'http://www.opengis.net/wfs',
    }

    # Parse XML file
    tree = ET.parse(xml_file)
    root = tree.getroot()

    # Create output folder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    print(f"🔹 Saving composite images in: {output_folder}")

    # Group features by ADM0.
    adm0_groups = {}  # key: adm0_code; value: dict with 'adm0_name' and 'features'
    for feature in root.findall('.//gaul:g2015_2014_1', namespaces):
        adm0_code_el = feature.find('gaul:adm0_code', namespaces)
        adm0_name_el = feature.find('gaul:adm0_name', namespaces)
        adm1_code_el = feature.find('gaul:adm1_code', namespaces)
        adm1_name_el = feature.find('gaul:adm1_name', namespaces)

        if adm0_code_el is None or adm1_code_el is None:
            continue
        adm0_code = adm0_code_el.text.strip()
        adm0_name = adm0_name_el.text.strip() if adm0_name_el is not None else "Unknown_ADM0"
        adm1_code = adm1_code_el.text.strip() if adm1_code_el is not None else "Unknown_ADM1"
        adm1_name = adm1_name_el.text.strip() if adm1_name_el is not None else "Unknown_ADM1_Name"

        polygon_elements = feature.findall('.//gml:Polygon', namespaces)
        for polygon_element in polygon_elements:
            posList_el = polygon_element.find('.//gml:posList', namespaces)
            if posList_el is None or not posList_el.text.strip():
                continue
            polygon, n_points = poslist_to_polygon(posList_el.text)
            if polygon is None:
                continue

            if adm0_code not in adm0_groups:
                adm0_groups[adm0_code] = {'adm0_name': adm0_name, 'features': []}
            adm0_groups[adm0_code]['features'].append({
                'adm1_code': adm1_code,
                'adm1_name': adm1_name,
                'polygon': polygon
            })

    # Process each ADM0 group.
    for adm0_code, group in adm0_groups.items():
        start_time = time.time()
        features = group['features']
        print(f"\n🔹 Processing ADM0 {adm0_code} - {group['adm0_name']} with {len(features)} features...")
        if not features:
            print(f"⚠️ No features for ADM0 {adm0_code}. Skipping...")
            continue

        # Group polygons by unique ADM1 unit.
        adm1_groups = {}
        for item in features:
            key = (item['adm1_code'], item['adm1_name'])
            if key not in adm1_groups:
                adm1_groups[key] = []
            adm1_groups[key].append(item['polygon'])
        print(f"   Unique ADM1 units: {len(adm1_groups)}")

        unioned_polygons = []
        adm1_keys = []
        for key, poly_list in adm1_groups.items():
            fixed_poly_list = [poly if poly.is_valid else poly.buffer(0) for poly in poly_list]
            try:
                if len(fixed_poly_list) == 1:
                    merged = fixed_poly_list[0]
                else:
                    merged = unary_union(fixed_poly_list)
            except Exception as e:
                print(f"⚠️ Error unioning polygons for ADM1 {key}: {e}")
                merged = fixed_poly_list[0]
            unioned_polygons.append(merged)
            adm1_keys.append(key)
        print(f"   Completed unioning polygons.")

        centroids = [poly.centroid for poly in unioned_polygons]

        # Build an adjacency graph.
        n = len(unioned_polygons)
        adjacency = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i+1, n):
                if unioned_polygons[i].touches(unioned_polygons[j]):
                    adjacency[i].add(j)
                    adjacency[j].add(i)
        print(f"   Adjacency graph built.")

        # Greedy algorithm for color assignment.
        available_colors = ['red', 'blue', 'green', 'orange']
        assigned_colors = [None] * n
        order = sorted(range(n), key=lambda i: len(adjacency[i]), reverse=True)
        for i in order:
            used = set(assigned_colors[j] for j in adjacency[i] if assigned_colors[j] is not None)
            for color in available_colors:
                if color not in used:
                    assigned_colors[i] = color
                    break
            if assigned_colors[i] is None:
                assigned_colors[i] = available_colors[0]
        print(f"   Color assignment completed: {assigned_colors}")

        # Create GeoDataFrame.
        import pandas as pd
        data = {
            'adm1_code': [key[0] for key in adm1_keys],
            'adm1_name': [key[1] for key in adm1_keys],
            'color': assigned_colors,
            'geometry': unioned_polygons
        }
        gdf = gpd.GeoDataFrame(data)

        # Plot the composite map.
        fig, ax = plt.subplots(figsize=figsize)
        gdf.plot(ax=ax, color=gdf['color'], edgecolor='black', alpha=0.7)

        # Annotate with ADM1 codes.
        for idx, row in gdf.iterrows():
            centroid = row['geometry'].centroid
            ax.annotate(row['adm1_code'], (centroid.x, centroid.y), fontsize=10, color='black', ha='center')

        # Build legend.
        sorted_df = gdf.sort_values(by='adm1_code', ascending=False)
        legend_handles = []
        for idx, row in sorted_df.iterrows():
            patch = mpatches.Patch(color=row['color'], label=f"{row['adm1_code']} = {row['adm1_name']}")
            legend_handles.append(patch)
        ncol = 2 if len(legend_handles) > 40 else 1
        ax.legend(handles=legend_handles, loc='lower left', title="ADM1 Mapping",
                  fontsize=10, title_fontsize=12, ncol=ncol)

        ax.set_title(f"ADM0 Code: {adm0_code} - {group['adm0_name']}\nADM1 Units", fontsize=16)
        ax.set_xlabel("Longitude", fontsize=14)
        ax.set_ylabel("Latitude", fontsize=14)

        output_path = os.path.join(output_folder, f"{adm0_code}.png")
        plt.savefig(output_path, dpi=dpi)
        plt.close(fig)
        elapsed = time.time() - start_time
        print(f"🖼️ Saved composite map for ADM0 {adm0_code}: {output_path} (Elapsed: {elapsed:.2f} sec)")

# Example usage:
HOME_DIR = r"path/to/your/home/directory"
xml_file = os.path.join(HOME_DIR, "Data", "g2015_2014_1_geom_extract.xml")
output_folder = os.path.join(HOME_DIR, "Data", "adm0_composite_maps")  # Folder for composite images.

save_adm0_composite_images(xml_file, output_folder)
