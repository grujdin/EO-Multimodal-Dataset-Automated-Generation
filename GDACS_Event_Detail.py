import pandas as pd
import requests
import os

# Load the input Excel file
input_excel_path = 'gdacs_hazards.xlsx'
df_events = pd.read_excel(input_excel_path)

# Ensure the output directory exists
output_dir = 'gdacs_event_details'
os.makedirs(output_dir, exist_ok=True)


# Function to fetch event details
def fetch_event_details(event_type, event_id):
    url = f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={event_type}&eventid={event_id}"
    print (url)
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to retrieve data for {event_type}-{event_id}")
        return None


# Iterate and save details to Excel
for index, row in df_events.iterrows():
    event_type = row['event_type']
    event_id = row['event_id']
    details = fetch_event_details(event_type, event_id)

    if details:
        sendai_data = details.get('properties', {}).get('sendai', [])
        sendai_df = pd.DataFrame(sendai_data)

        if not sendai_df.empty:
            output_path = os.path.join(output_dir, f"{event_type}_{event_id}_details.xlsx")
            sendai_df.to_excel(output_path, index=False)
            print(f"Saved: {output_path}")
