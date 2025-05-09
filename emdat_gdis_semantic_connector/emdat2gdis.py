#--------------------- Align EM-DAT database format to GDIS database ----------------------
#
# This script processes EM-DAT disaster event data to align its format with the GDIS database.
# Key tasks include:
# - Splitting multi-location events into separate observations for each named location.
# - Normalizing and cleaning location names for consistency.
# - Expanding province-prefecture mappings when applicable.
# - Matching locations to administrative units using fuzzy matching.
# - Assigning unique serial codes to processed events.
# - Saving the cleaned and structured data into a new Excel file.
#
# ----------------------------------------------------------------------------------------

import pandas as pd  # Import pandas for data handling
import unicodedata  # For Unicode normalization
import re  # For regular expressions
import json  # For handling JSON data
from fuzzywuzzy import fuzz  # For fuzzy string matching
import os

# ----------------------- Helper Functions -----------------------

# Normalize Unicode characters in a string to their closest ASCII equivalents
def normalize_string(s):
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')

# Remove predefined keywords (e.g., "province", "city") and normalize the location string
def clean_location(location):
    ignore_keywords = [
        'province', 'provinces', 'distrito capital', 'city', 'cities', 'district', 'districts',
        'county', 'counties', 'municipalities', 'municipality', 'region', 'regions',
        'department', 'state', 'village', 'airport', 'borough'
    ]
    location = normalize_string(location.lower())  # Convert to lowercase and normalize Unicode
    words = location.split()  # Split into individual words
    cleaned_words = [word for word in words if word not in ignore_keywords]  # Remove ignored keywords
    return ' '.join(cleaned_words)  # Reassemble the cleaned location string

# Split a location string at commas that are not enclosed in parentheses
def parse_locations(location_string):
    matches = re.finditer(r',\s*(?![^\(\)]*\))', location_string)  # Match commas outside parentheses
    last_pos = 0
    parts = []
    for match in matches:
        parts.append(location_string[last_pos:match.start()])  # Extract each part before a comma
        last_pos = match.end()
    parts.append(location_string[last_pos:])  # Add the last part after the final comma
    return parts

# Expand province-prefecture mappings where multiple provinces share a common prefecture
def expand_province_prefecture_mapping(location_entries):
    expanded_locations = []
    pattern = re.compile(r'(.+)\s+\((.+)\)')  # Match "Province (Prefecture)" format
    for entry in location_entries:
        match = pattern.match(entry)
        if match:
            provinces = match.group(1).split(', ')  # Split multiple province names
            prefecture = match.group(2).strip()
            expanded_locations.extend([f"{province} ({prefecture})" for province in provinces])  # Expand mapping
        else:
            expanded_locations.append(entry)  # Keep the original if no mapping exists
    return expanded_locations

# Match a given location to the best-fitting administrative unit using fuzzy string matching
def find_best_matching_admin_units_v3(location, admin_units_string):
    try:
        admin_units = json.loads(admin_units_string) if admin_units_string else []  # Load admin unit data from JSON
    except json.JSONDecodeError:
        return None  # Return None if JSON decoding fails

    location_cleaned = clean_location(location)  # Normalize and clean location name
    location_parts = location_cleaned.split()  # Split into individual words
    best_match = None
    max_score = 0  # Track the highest similarity score

    for unit in admin_units:
        names_to_compare = []  # List of potential matching names
        if 'adm1_name' in unit:
            names_to_compare.append(unit['adm1_name'])  # Add administrative level 1 name
        if 'adm2_name' in unit:
            names_to_compare.append(unit['adm2_name'])  # Add administrative level 2 name

        for name in names_to_compare:
            score = fuzz.ratio(name, location_cleaned)  # Compute similarity score
            if score > max_score:  # Update best match if a higher score is found
                max_score = score
                best_match = unit

    return best_match  # Return the best-matching administrative unit

# ----------------------- Data Processing -----------------------

# Load the Excel file containing EM-DAT disaster data
HOME_DIR = r"path/to/your/home/directory"
excel_file = os.path.join(HOME_DIR, "Data", "public_emdat_reduced.xlsx")
df = pd.read_excel(excel_file)  # Read data into a Pandas DataFrame

# Prepare a list to store processed event records
rows_list = []
serial_number = 1  # Initialize unique event serial number

# Iterate through each row in the dataset
for index, row in df.iterrows():
    admin_units_string = row['Admin Units'] if isinstance(row['Admin Units'], str) else ""  # Extract admin units
    location_entries = parse_locations(row['Location']) if pd.notna(row['Location']) else []  # Split multi-location entries

    # Expand province-prefecture mappings where necessary
    expanded_location_entries = expand_province_prefecture_mapping(location_entries)

    # Process each parsed location separately
    for loc_entry in expanded_location_entries:
        match = find_best_matching_admin_units_v3(loc_entry, admin_units_string)  # Find the best admin unit match
        new_row = row.to_dict()  # Convert row to dictionary
        new_row['Location'] = loc_entry  # Update location field
        new_row['Admin Units'] = json.dumps([match]) if match else "[]"  # Store matched admin unit(s) as JSON
        new_row['Unique Code'] = f"MMR-{serial_number}"  # Assign a unique serial code
        serial_number += 1  # Increment serial number
        rows_list.append(new_row)  # Append the processed row to the list

# Convert the processed data into a new DataFrame
reshaped_data = pd.DataFrame(rows_list)

# ----------------------- Save to Excel -----------------------

# Define the path for the output Excel file
new_excel_path = os.path.join(HOME_DIR, "Data", "public_emdat_gdis_aligned.xlsx")

# Create an Excel writer object using the 'xlsxwriter' engine
writer = pd.ExcelWriter(new_excel_path, engine='xlsxwriter')
reshaped_data.to_excel(writer, index=False, sheet_name='Sheet1')  # Write data to the first sheet

# Apply formatting to highlight rows where admin units were not matched
workbook = writer.book
worksheet = writer.sheets['Sheet1']
red_font_format = workbook.add_format({'font_color': 'red'})  # Define red font format

# Iterate over rows to apply conditional formatting
for idx, row in reshaped_data.iterrows():
    if "[]" in row['Admin Units']:  # Check if no admin unit was matched
        worksheet.set_row(idx + 1, None, red_font_format)  # Highlight row in red

writer.close()  # Finalize and save the Excel file

# Print confirmation message
print(f"Reshaped data saved to {new_excel_path}")
