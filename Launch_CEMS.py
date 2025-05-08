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

acts = list_activations(limit=3, token="3NKHt6i2urmWtqOuugvr9ZjK4Fbn-AOI3Ib0xSTorPLs_y0M6yUB_sbNEjAf8kRaJH0r5cm7pm3nfUMIK0rEgQ2qN3fJTZ8kJGomTAyIs0DZFHpGj25ablQaVKUZWfBh")
print(acts[0]["name"])