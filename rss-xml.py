import requests
import pandas as pd
import xml.etree.ElementTree as ET

GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"

namespaces = {
    'dc': "http://purl.org/dc/elements/1.1/",
    'geo': "http://www.w3.org/2003/01/geo/wgs84_pos#",
    'gdacs': "http://www.gdacs.org",
    'glide': "http://glidenumber.net",
    'georss': "http://www.georss.org/georss",
    'atom': "http://www.w3.org/2005/Atom"
}

def parse_gdacs_rss(rss_url: str) -> pd.DataFrame:
    print(f"Fetching XML from {rss_url}...")
    response = requests.get(rss_url)
    response.raise_for_status()  # Stop if status != 200

    root = ET.fromstring(response.content)
    channel = root.find('channel')
    if channel is None:
        raise RuntimeError("No <channel> element found in RSS feed.")

    rows = []

    # Iterate through <item> elements
    for item in channel.findall('item'):
        # title
        title_el = item.find('title')
        title = title_el.text if title_el is not None else None

        # description
        desc_el = item.find('description')
        description = desc_el.text if desc_el is not None else None

        # link
        link_el = item.find('link')
        link_val = link_el.text if link_el is not None else None

        # pubDate
        pub_el = item.find('pubDate')
        pub_val = pub_el.text if pub_el is not None else None

        # guid
        guid_el = item.find('guid')
        guid_val = guid_el.text if guid_el is not None else None

        # Example: dc:subject
        dc_subject_el = item.find('dc:subject', namespaces=namespaces)
        dc_subject_val = dc_subject_el.text if dc_subject_el is not None else None

        # geo: lat/long
        geo_point = item.find('geo:Point', namespaces=namespaces)
        lat_val, lon_val = None, None
        if geo_point is not None:
            lat_el = geo_point.find('geo:lat', namespaces=namespaces)
            lon_el = geo_point.find('geo:long', namespaces=namespaces)
            if lat_el is not None:
                lat_val = lat_el.text
            if lon_el is not None:
                lon_val = lon_el.text

        # gdacs:bbox
        bbox_el = item.find('gdacs:bbox', namespaces=namespaces)
        bbox_val = bbox_el.text if bbox_el is not None else None

        # Example: gdacs:eventtype
        eventtype_el = item.find('gdacs:eventtype', namespaces=namespaces)
        eventtype_val = eventtype_el.text if eventtype_el is not None else None

        # Example: gdacs:alertlevel
        alertlevel_el = item.find('gdacs:alertlevel', namespaces=namespaces)
        alertlevel_val = alertlevel_el.text if alertlevel_el is not None else None

        # Example: gdacs:eventid
        eventid_el = item.find('gdacs:eventid', namespaces=namespaces)
        eventid_val = eventid_el.text if eventid_el is not None else None

        # Example: gdacs:country
        country_el = item.find('gdacs:country', namespaces=namespaces)
        country_val = country_el.text if country_el is not None else None

        # iso3
        iso3_el = item.find('gdacs:iso3', namespaces=namespaces)
        iso3_val = iso3_el.text if iso3_el is not None else None

        # Build a row dict
        row = {
            'title': title,
            'description': description,
            'link': link_val,
            'pubDate': pub_val,
            'guid': guid_val,
            'dc_subject': dc_subject_val,
            'lat': lat_val,
            'lon': lon_val,
            'bbox': bbox_val,
            'gdacs_eventtype': eventtype_val,
            'gdacs_alertlevel': alertlevel_val,
            'gdacs_eventid': eventid_val,
            'gdacs_country': country_val,
            'gdacs_iso3': iso3_val,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    return df

def main():
    df_rss = parse_gdacs_rss(GDACS_RSS_URL)
    print(df_rss.head(10))
    print(f"Total items: {len(df_rss)}")

    df_rss.to_csv("gdacs_rss_data.csv", index=False)
    print("CSV saved as gdacs_rss_data.csv")

if __name__ == "__main__":
    main()
