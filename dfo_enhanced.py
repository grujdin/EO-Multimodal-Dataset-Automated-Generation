# Enhanced script to visualize Flood Events individually focused on each affected area (optimized basemap)

import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx
from datetime import datetime

# ────────────────────────────
# Step 1: Load and Inspect Data
# ────────────────────────────

flood_data = pd.read_csv('C:/Users/grujd/OneDrive/ProjDB/DFO/FloodArchive.txt', sep='\t', encoding='latin1')

# ────────────────────────────
# Step 2: Data Cleaning
# ────────────────────────────

flood_data['Began'] = pd.to_datetime(flood_data['Began'], format='%Y%m%d', errors='coerce')
flood_data['Ended'] = pd.to_datetime(flood_data['Ended'], format='%Y%m%d', errors='coerce')
flood_data.dropna(subset=['long', 'lat', 'Began', 'Ended'], inplace=True)

# ────────────────────────────
# Step 3: Filter Data by Date Interval
# ────────────────────────────

start_date_str = input("Enter start date (YYYYMMDD): ")
end_date_str = input("Enter end date (YYYYMMDD): ")
start_date = datetime.strptime(start_date_str, '%Y%m%d')
end_date = datetime.strptime(end_date_str, '%Y%m%d')

flood_data_filtered = flood_data.loc[(flood_data['Began'] >= start_date) & (flood_data['Ended'] <= end_date)].copy()

# ────────────────────────────
# Step 4: Geographic Data Preparation
# ────────────────────────────

polygon_type = None
try:
    shapefile_path = 'C:/Users/grujd/OneDrive/ProjDB/DFO/FloodArchive_region.shp'
    gdf_polygons = gpd.read_file(shapefile_path).to_crs(epsg=3857)

    # Convert date columns in polygons for filtering
    gdf_polygons['BEGAN'] = pd.to_datetime(gdf_polygons['BEGAN'], errors='coerce')
    gdf_polygons['ENDED'] = pd.to_datetime(gdf_polygons['ENDED'], errors='coerce')

    # Filter polygons based on dates
    gdf_polygons_filtered = gdf_polygons.loc[(gdf_polygons['BEGAN'] >= start_date) & (gdf_polygons['ENDED'] <= end_date)].copy()

    polygon_type = 'Event Area'
    gdf_polygons_filtered['PolyType'] = polygon_type

    # Merge geometries into flood_data_filtered
    flood_data_filtered = flood_data_filtered.merge(gdf_polygons_filtered[['ID', 'geometry']], on='ID', how='left')

except Exception as e:
    print("Polygon shapefile not loaded:", e)

# ────────────────────────────
# Step 5: Individual Map Visualization per Affected Area
# ────────────────────────────

for idx, row in gdf_polygons_filtered.iterrows():
    fig, ax = plt.subplots(figsize=(8, 8))

    single_polygon = gpd.GeoDataFrame([row], crs="EPSG:3857")
    single_polygon.plot(ax=ax, facecolor='none', edgecolor='red', linewidth=2)

    centroid = single_polygon.geometry.centroid
    centroid.plot(ax=ax, color='green', markersize=100, marker='x')

    # Get bounds for focused view
    bounds = single_polygon.total_bounds
    x_min, y_min, x_max, y_max = bounds

    # Add padding around bounds
    padding_factor = 0.2
    x_pad = (x_max - x_min) * padding_factor
    y_pad = (y_max - y_min) * padding_factor
    ax.set_xlim(x_min - x_pad, x_max + x_pad)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    # Add simplified basemap (less detailed for better performance)
    ctx.add_basemap(ax, source=ctx.providers.CartoDB.Positron, zoom='auto')

    event_title = f"Flood Event {row['ID']} ({row['COUNTRY']})"
    ax.set_title(event_title, fontsize=14)
    ax.set_axis_off()

    plt.tight_layout()
    plt.show()

# ────────────────────────────
# Step 6: Save Processed Data
# ────────────────────────────

flood_data_filtered.to_csv('Processed_FloodArchive_filtered.csv', index=False)
if polygon_type:
    gdf_polygons_filtered.to_file('Processed_FloodArchive_polygons_filtered.shp')

print("Data processing and visualization completed successfully.")
