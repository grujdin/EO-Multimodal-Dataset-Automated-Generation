import cdsapi
import xarray as xr
import matplotlib.pyplot as plt
import numpy as np

# Step 1: Retrieve data from CDS
client = cdsapi.Client()

dataset = 'reanalysis-era5-pressure-levels'
request = {
    'product_type': ['reanalysis'],
    'variable': ['geopotential'],
    'year': ['2024'],
    'month': ['03'],
    'day': ['01'],
    'time': ['13:00'],
    'pressure_level': ['1000'],
    'data_format': 'grib',
}
target = 'download.grib'

client.retrieve(dataset, request, target)

# Step 2: Load and interpret GRIB data
print("\nLoading GRIB file...")
ds = xr.open_dataset(target, engine='cfgrib')

# Display dataset structure
print("\nDataset structure:")
print(ds)

# Convert geopotential (z) to geopotential height (in meters)
ds['geopotential_height'] = ds['z'] / 9.80665

# Step 3: Plot Geopotential Height
plt.figure(figsize=(12, 6))
ds['geopotential_height'].plot(
    cmap='terrain',
    cbar_kwargs={'label': 'Geopotential Height (meters)'}
)

# Plot formatting
plt.title('ERA5 Geopotential Height at 1000 hPa (1 March 2024, 13:00 UTC)', fontsize=14)
plt.xlabel('Longitude')
plt.ylabel('Latitude')
plt.grid(linestyle='--', alpha=0.5)

plt.tight_layout()
plt.savefig('geopotential_height.png', dpi=300)
plt.show()
