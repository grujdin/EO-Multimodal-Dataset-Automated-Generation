# Import necessary libraries
import pandas as pd
from calendar import monthrange

# Load the Excel file containing disaster data into a pandas DataFrame
df = pd.read_excel('D:/ProjDB/GAUL/public_emdat_GDIS_GAUL_FIDs.xlsx')

# Define a function to format the start and end dates into ISO 8601 format
def format_dates(row):
    """
    Extracts Start Date and End Date as separate string columns in ISO 8601 format.
    """
    # If 'Start Day' is missing, default to the 1st day of the month
    start_day = int(row['Start Day']) if not pd.isna(row['Start Day']) else 1
    start_date = f"{row['Start Year']}-{row['Start Month']:02d}-{start_day:02d}T00:00:00Z"

    # If 'End Day' is missing, determine the last day of the 'End Month'
    if pd.isna(row['End Day']):
        last_day = monthrange(row['End Year'], row['End Month'])[1]
        end_day = last_day
    else:
        end_day = int(row['End Day'])

    end_date = f"{row['End Year']}-{row['End Month']:02d}-{end_day:02d}T00:00:00Z"

    # Return start_date and end_date as a tuple
    return pd.Series([start_date, end_date])


# Apply the function to each row and create two new columns
df[['Start Date', 'End Date']] = df.apply(format_dates, axis=1)

# Select specific columns for the output DataFrame, including the new 'Start Date' and 'End Date' columns
output_df = df[['Unique Code', 'DisNo.', 'Classification Key', 'Start Date', 'End Date',
                'External IDs', 'FID_1', 'adm1_code', 'adm1_name', 'FID_2', 'adm2_code', 'adm2_name']]

# Rename columns to match required names if needed
output_df.columns = ['Unique Code', 'DisNo.', 'Classification Key', 'Start Date', 'End Date',
                'External IDs', 'FID_1', 'adm1_code', 'adm1_name', 'FID_2', 'adm2_code', 'adm2_name']

# Write the processed data to a new Excel file without including row indices
output_df.to_excel('D:/ProjDB/API/API_Request_Data.xlsx', index=False)

print("Data successfully saved to 'API_Request_Data.xlsx'.")
