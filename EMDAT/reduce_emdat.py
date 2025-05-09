#--------------------- Reduce EM-DAT dataset to selected fields ----------------------
#
# Extract the only relevant columns from the original EM-DAT dataset to streamline data
# analysis and reduce file size.
#
# -----------------------------------------------------------------------------------

import pandas as pd  # Import the pandas library for data manipulation

# Define the path to the original Excel file
input_file = 'D:/ProjDB/EMDAT/PublicTable/public_emdat_custom_request_2024-05-12_85ae59a7-afa1-41e3-8642-596f53c2731a.xlsx'

# Load the Excel file into a DataFrame
df = pd.read_excel(input_file)

# Specify the columns to keep from the original dataset
columns_to_keep = [
    'DisNo.', 'Classification Key', 'External IDs', 'Event Name', 'ISO', 'Country', 'Subregion',
    'Region', 'Location', 'Origin', 'Associated Types', 'Latitude', 'Longitude', 'River Basin',
    'Start Year', 'Start Month', 'Start Day', 'End Year', 'End Month', 'End Day',
    'Admin Units', 'Entry Date', 'Last Update'
]

# Create a new DataFrame that only contains the selected columns
new_df = df[columns_to_keep]

# Define the output file path where the modified dataset will be saved
output_file = 'D:/ProjDB/EMDAT/public_emdat_reduced.xlsx'

# Save the filtered DataFrame to a new Excel file without including the index column
new_df.to_excel(output_file, index=False)

# Print a confirmation message with the output file path
print(f'New file saved as {output_file}')
