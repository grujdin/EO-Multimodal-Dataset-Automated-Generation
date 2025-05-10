import gdacs.api
import pandas as pd
from gdacs.api import GDACSAPIReader, GDACSAPIError

# Initialize GDACS API client
client = GDACSAPIReader()

# Define hazard types
hazard_types = ['FL', 'WF', 'VO']  # Flood (FL), Wildfire (WF), Volcano (VO)

def retrieve_hazard_events(hazard_type, limit=10):
    """
    Fetch latest GDACS events for a specific hazard_type (e.g. 'FL' for Flood)
    and return them as a list of dicts with the relevant fields, including
    a custom 'media_url' that references /getemmnewsbykey.
    """
    try:
        print(f"Fetching data for {hazard_type}...")
        geojson_response = client.latest_events(event_type=hazard_type, limit=limit)

        # If no features, skip
        if not hasattr(geojson_response, "features") or not geojson_response.features:
            print(f"No features found in response for {hazard_type}. Skipping.")
            return []

        formatted_events = []
        for feature in geojson_response.features:
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [None, None])
            bbox = feature.get("bbox", [])

            # Primary fields
            event_type_val = props.get('eventtype', hazard_type)
            event_id_val = props.get('eventid', 'Unknown')

            # Build dictionary for each event
            formatted_event = {
                'event_type': event_type_val,
                'event_id': event_id_val,
                'episode_id': props.get('episodeid', 'Unknown'),
                'name': props.get('name', 'No Name Available'),
                'from_date': props.get('fromdate', 'Unknown'),
                'to_date': props.get('todate', 'Unknown'),
                'alert_level': props.get('alertlevel', 'Unknown'),
                'latitude': coords[1] if coords else None,
                'longitude': coords[0] if coords else None,
                'bbox': bbox if bbox else 'No BBOX Available',
                'iso3': props.get('iso3', 'Unknown'),
                'country': props.get('country', 'Unknown'),
                'severity': props.get('severitydata', {}).get('severity', 'Unknown'),
                'description': props.get('description', 'No description available'),
                'source': props.get('source', 'Unknown'),

                # Standard URLs from props['url']
                'report_url': props.get('url', {}).get('report', 'No Report URL'),
                'details_url': props.get('url', {}).get('details', 'No Details URL'),

                # Custom media_url in the desired format
                # e.g.: https://www.gdacs.org/gdacsapi/api/emm/getemmnewsbykey?eventtype=FL&eventid=1103118
                'media_url': f"https://www.gdacs.org/gdacsapi/api/emm/getemmnewsbykey?eventtype={event_type_val}&eventid={event_id_val}",

                # If you want geometry_url from the original 'url' structure, you can keep it or remove it:
                'geometry_url': props.get('url', {}).get('geometry', 'No Geometry URL')
            }

            formatted_events.append(formatted_event)

        return formatted_events

    except GDACSAPIError as e:
        print(f"Error retrieving {hazard_type} events: {e}")
        return []

# -----------------------------------------------------------------------------
# Main script flow
# -----------------------------------------------------------------------------

all_events_data = []

# Retrieve latest events for each hazard type
for hazard in hazard_types:
    events = retrieve_hazard_events(hazard)
    if events:
        print(f"✅ Retrieved {len(events)} events for {hazard}")
    else:
        print(f"❌ No events found for {hazard}")
    all_events_data.extend(events)

# Convert to DataFrame
df_hazards = pd.DataFrame(all_events_data)

print("\nDataFrame Preview:")
print(df_hazards.head())

# Save to Excel if there's data
if not df_hazards.empty:
    excel_filename = 'gdacs_hazards.xlsx'
    df_hazards.to_excel(excel_filename, index=False)
    print(f"✅ Hazard data successfully retrieved and saved to {excel_filename}")
else:
    print("⚠️ No hazard data found. Excel file not created.")
