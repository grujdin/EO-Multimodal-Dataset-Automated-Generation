from CEMS import list_activations

import requests, getpass, json

url = "https://services-eu1.arcgis.com/sharing/rest/generateToken"
payload = {
    "f": "json",
    "username": input("ArcGIS username: "),
    "password": getpass.getpass("ArcGIS password: "),
    "referer": "https://services-eu1.arcgis.com",
    "expiration": 60,      # minutes
}
tok = requests.post(url, data=payload, timeout=30).json()
print(json.dumps(tok, indent=2))

acts = list_activations(limit=3, token="<your_token>")
print(acts[0]["name"])
