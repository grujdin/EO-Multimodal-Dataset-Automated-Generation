#!/usr/bin/env python3
import json
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import shape
import math

# Path to your GeoJSON file
#GEOJSON_PATH = "getgeometry_all.json"  # Adjust this if needed
GEOJSON_PATH = "WF_Compact/WF_1003984_11.geojson"  # Adjust this if needed
# Load GeoJSON content
with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
    geojson_data = json.load(f)

# Convert to records for GeoDataFrame
features = geojson_data.get("features", [])
records = []
for feat in features:
    try:
        props = feat.get("properties", {})
        geom = shape(feat.get("geometry"))
        records.append({
            "date": props.get("polygondate") or props.get("date") or "Unknown",
            "source": props.get("source") or "Unknown",
            "geometry": geom
        })
    except Exception as e:
        print(f"Skipped feature due to error: {e}")

# Create GeoDataFrame
gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")

# Print metadata
print("\nSummary of polygons:")
print(gdf[["date", "source"]])

# Plot each geometry on a separate subplot
n = len(gdf)
cols = 4
rows = math.ceil(n / cols)
fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 5 * rows))
axes = axes.flatten() if n > 1 else [axes]

for i, (idx, row) in enumerate(gdf.iterrows()):
    gdf.iloc[[idx]].plot(ax=axes[i], edgecolor='black', color='skyblue')
    axes[i].set_title(f"{row['date']}\n{row['source']}", fontsize=8)
    axes[i].set_xlabel("Longitude")
    axes[i].set_ylabel("Latitude")

# Hide any unused subplots
for j in range(i + 1, len(axes)):
    axes[j].axis('off')

plt.tight_layout()
plt.suptitle("Polygon Features by Date and Source", fontsize=14)
plt.subplots_adjust(top=0.92)
plt.show()
