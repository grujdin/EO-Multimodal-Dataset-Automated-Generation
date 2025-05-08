
import os
from datetime import datetime
import pandas as pd
from typing import Dict, Any

def build_request_url(swagger: Dict[str, Any], path: str) -> str:
    base_url = swagger.get("_base_url")
    if not base_url:
        host = swagger.get("host", "api.reliefweb.int")
        base_path = swagger.get("basePath", "/v1")
        base_url = f"https://{host}{base_path}"
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url.rstrip('/')}{path}"

def save_dataframe_to_csv(df: pd.DataFrame, label: str = "results", output_dir: str = "output") -> str:
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{label}_{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    return filepath
