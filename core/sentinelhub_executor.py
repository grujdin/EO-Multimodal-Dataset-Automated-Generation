import requests
import json
import pandas as pd
from core.openapi_parser import build_full_url
import tempfile


def execute_sentinel_query(swagger, method, path_template, query_params=None, post_body=None, path_vals=None, token=None):
    url = build_full_url(swagger, path_template, path_vals, query_params)

    try:
        print("📤 RAW JSON sent to SentinelHub:", json.dumps(post_body, indent=2), flush=True)

        if method.upper() == "GET":
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            response = requests.get(url, headers=headers)

        elif method.upper() == "POST" and "/process" in path_template:
            evalscript = post_body.get("evalscript")
            evalscript_type = post_body.get("evalscriptType")

            # Remove evalscript from JSON and send separately
            cleaned_body = {k: v for k, v in post_body.items() if k not in ("evalscript", "evalscriptType")}
            files = {
                "request": (None, json.dumps(cleaned_body), "application/json"),
                "evalscript": (None, evalscript, "application/javascript")
            }
            if evalscript_type:
                files["evalscriptType"] = (None, evalscript_type, "text/plain")

            headers = {
                "Authorization": f"Bearer {token}"
            }
            response = requests.post(url, headers=headers, files=files)

        elif method.upper() == "POST":
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            response = requests.post(url, headers=headers, data=json.dumps(post_body))

        else:
            return url, {"error": "Unsupported method"}, None

        # Detect content type
        content_type = response.headers.get("Content-Type", "")

        # Handle binary image (e.g., TIFF)
        if "image" in content_type or "application/octet-stream" in content_type:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tiff")
            temp_file.write(response.content)
            temp_file.flush()
            return url, {"download_url": temp_file.name}, None

        # Handle JSON
        try:
            data = response.json()
        except Exception:
            return url, {"error": "Received non-JSON response"}, None

        # Try to parse as GeoJSON FeatureCollection or fallback
        if isinstance(data, dict) and "features" in data:
            features = data["features"]
            flattened = []
            for feat in features:
                props = feat.get("properties", {})
                props["id"] = feat.get("id")
                props["collection"] = feat.get("collection")
                flattened.append(props)
            df = pd.DataFrame(flattened)
            return url, data, df

        elif isinstance(data, list):
            df = pd.DataFrame(data)
            return url, data, df

        elif isinstance(data, dict):
            df = pd.json_normalize(data)
            return url, data, df

        return url, data, None

    except Exception as e:
        print("Query failed:", e)
        return url, {"error": str(e)}, None
