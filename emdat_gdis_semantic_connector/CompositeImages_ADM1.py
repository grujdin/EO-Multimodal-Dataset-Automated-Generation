import os
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union
import matplotlib.patches as mpatches

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

def save_adm1_composite_images(xml_file, output_folder, dpi=500, figsize=(40, 30)):
    """
    Parses the XML file, groups features by their ADM1 code, and for each ADM1 region creates a
    high-resolution composite map that displays all component ADM2 areas.

    For each ADM1 group:
      1. Extract each feature’s ADM2 code, ADM2 name, and polygon geometry.
      2. Group polygons by unique ADM2 unit (using union if multiple parts exist), fixing invalid geometries.
      3. Compute an adjacency graph (using .touches()) to detect neighboring areas.
      4. Apply a greedy algorithm (with 4 available colours) to assign a colour to each ADM2 unit so that
         adjacent polygons tend to receive different colours. If none is available, a fallback default is used.
      5. The map is then plotted: each ADM2 area is filled with its assigned colour; its ADM2 code is annotated
         at its centroid (in black), and a legend (sorted in descending order) is added.
         If there are more than 40 ADM2 units, the legend is arranged in 2 columns.
    """
    # Define namespaces
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

    # Group features by ADM1 code.
    groups = {}  # key: adm1_code; value: dict with 'adm1_name' and 'features'
    for feature in root.findall('.//gaul:g2015_2014_2', namespaces):
        adm1_code_el = feature.find('gaul:adm1_code', namespaces)
        adm1_name_el = feature.find('gaul:adm1_name', namespaces)
        adm2_code_el = feature.find('gaul:adm2_code', namespaces)
        adm2_name_el = feature.find('gaul:adm2_name', namespaces)

        if adm1_code_el is None:
            continue
        adm1_code = adm1_code_el.text.strip()
        adm1_name = adm1_name_el.text.strip() if adm1_name_el is not None else "Unknown_ADM1"
        adm2_code = adm2_code_el.text.strip() if adm2_code_el is not None else "Unknown_ADM2"
        adm2_name = adm2_name_el.text.strip() if adm2_name_el is not None else "Unknown_ADM2_Name"

        polygon_elements = feature.findall('.//gml:Polygon', namespaces)
        for polygon_element in polygon_elements:
            posList_el = polygon_element.find('.//gml:posList', namespaces)
            if posList_el is None or not posList_el.text.strip():
                continue
            polygon, n_points = poslist_to_polygon(posList_el.text)
            if polygon is None:
                continue

            if adm1_code not in groups:
                groups[adm1_code] = {'adm1_name': adm1_name, 'features': []}
            groups[adm1_code]['features'].append({
                'adm2_code': adm2_code,
                'adm2_name': adm2_name,
                'polygon': polygon
            })

    # For each ADM1 group, create a composite map.
    for adm1_code, group in groups.items():
        features = group['features']
        if not features:
            print(f"⚠️ No polygons for ADM1 {adm1_code}. Skipping...")
            continue

        # Group polygons by unique ADM2 unit.
        adm2_groups = {}  # key: (adm2_code, adm2_name); value: list of polygons
        for item in features:
            key = (item['adm2_code'], item['adm2_name'])
            if key not in adm2_groups:
                adm2_groups[key] = []
            adm2_groups[key].append(item['polygon'])

        unique_polygons = []  # one unioned polygon per ADM2 unit
        adm2_keys = []  # corresponding keys (adm2_code, adm2_name)
        for key, poly_list in adm2_groups.items():
            # Fix invalid geometries using buffer(0)
            fixed_poly_list = [poly if poly.is_valid else poly.buffer(0) for poly in poly_list]
            try:
                if len(fixed_poly_list) == 1:
                    merged = fixed_poly_list[0]
                else:
                    merged = unary_union(fixed_poly_list)
            except Exception as e:
                print(f"⚠️ Error unioning polygons for ADM2 {key}: {e}")
                merged = fixed_poly_list[0]
            unique_polygons.append(merged)
            adm2_keys.append(key)

        # Compute centroids for annotation.
        centroids = [poly.centroid for poly in unique_polygons]

        # Build an adjacency graph (neighbors if polygons touch).
        n = len(unique_polygons)
        adjacency = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i+1, n):
                if unique_polygons[i].touches(unique_polygons[j]):
                    adjacency[i].add(j)
                    adjacency[j].add(i)

        # Apply a greedy algorithm to assign colors so that neighboring polygons tend to have different colours.
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
                # Fallback: assign default color if none available.
                assigned_colors[i] = available_colors[0]

        # Create a GeoDataFrame with unioned ADM2 geometries and their assigned colours.
        import pandas as pd
        data = {
            'adm2_code': [key[0] for key in adm2_keys],
            'adm2_name': [key[1] for key in adm2_keys],
            'color': assigned_colors,
            'geometry': unique_polygons
        }
        gdf = gpd.GeoDataFrame(data)

        # Create a high-resolution composite map.
        fig, ax = plt.subplots(figsize=figsize)
        gdf.plot(ax=ax, color=gdf['color'], edgecolor='black', alpha=0.7)

        # Annotate each ADM2 unit with its ADM2 code (in black).
        for idx, row in gdf.iterrows():
            centroid = row['geometry'].centroid
            ax.annotate(row['adm2_code'], (centroid.x, centroid.y), fontsize=10, color='black', ha='center')

        # Build legend entries.
        # Sort the ADM2 codes in descending order.
        sorted_df = gdf.sort_values(by='adm2_code', ascending=False)
        legend_handles = []
        for idx, row in sorted_df.iterrows():
            patch = mpatches.Patch(color=row['color'], label=f"{row['adm2_code']} = {row['adm2_name']}")
            legend_handles.append(patch)
        # If more than 40 labels, arrange legend in 2 columns.
        ncol = 2 if len(legend_handles) > 40 else 1
        ax.legend(handles=legend_handles, loc='lower left', title="ADM2 Mapping",
                  fontsize=10, title_fontsize=12, ncol=ncol)

        ax.set_title(f"ADM1 Code: {adm1_code} - {group['adm1_name']}", fontsize=16)
        ax.set_xlabel("Longitude", fontsize=14)
        ax.set_ylabel("Latitude", fontsize=14)

        # Save the composite image with high resolution.
        output_path = os.path.join(output_folder, f"{adm1_code}.png")
        plt.savefig(output_path, dpi=dpi)
        plt.close(fig)

        print(f"🖼️ Saved composite map for ADM1 {adm1_code}: {output_path}")


# Example usage:
xml_file = 'D:/ProjDB/GAUL/g2015_2014_2.xml'  # Path to your GAUL XML file
output_folder = 'D:/ProjDB/GAUL/ADM1_Composite_Images'  # Folder where composite images will be saved

save_adm1_composite_images(xml_file, output_folder)
