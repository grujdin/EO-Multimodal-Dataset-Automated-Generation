
import yaml
from typing import Dict, List, Any, Union, IO
import urllib.parse

def load_swagger(file: Union[str, IO]) -> Dict[str, Any]:
    if isinstance(file, str):
        with open(file, 'r', encoding='utf-8') as f:
            swagger = yaml.safe_load(f)
    else:
        swagger = yaml.safe_load(file)

    base_url = ""
    if "servers" in swagger:
        base_url = swagger["servers"][0]["url"].rstrip("/")
    elif "host" in swagger:
        scheme = "https"
        host = swagger["host"]
        base_path = swagger.get("basePath", "")
        base_url = f"{scheme}://{host}{base_path}".rstrip("/")
    swagger["_base_url"] = base_url
    return swagger

def list_api_endpoints(swagger: Dict[str, Any]) -> List[Dict[str, Any]]:
    endpoints = []
    for path, methods in swagger.get("paths", {}).items():
        for method, meta in methods.items():
            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": meta.get("summary", ""),
                "tags": meta.get("tags", []),
                "parameters": meta.get("parameters", [])
            })
    return endpoints

def get_parameters_for_endpoint(swagger: Dict[str, Any], endpoint: Dict[str, Any]) -> List[Dict[str, Any]]:
    param_defs = swagger.get("parameters", {})
    resolved = []

    raw_endpoint = endpoint.get("raw", {})  # ✅ FIX: drill into 'raw' Swagger info

    for param in raw_endpoint.get("parameters", []):
        if "$ref" in param:
            ref_path = param["$ref"].split("/")
            if len(ref_path) >= 3 and ref_path[1] == "parameters":
                ref_key = ref_path[2]
                resolved_param = param_defs.get(ref_key, {}).copy()
                if resolved_param:
                    resolved.append(resolved_param)
        else:
            resolved.append(param)

    return resolved

def get_enum_options(param, swagger=None):
    """Extract enum values from a parameter, resolving $ref if needed."""
    schema = param.get("schema")

    if schema is None:
        # Check for top-level enum (older Swagger 2.0)
        if "enum" in param:
            return param["enum"]
        return []

    if "$ref" in schema and swagger:
        schema = resolve_ref(swagger, schema["$ref"])

    return schema.get("enum", [])


def describe_param(param: Dict[str, Any]) -> str:
    return param.get("description", "") or param.get("summary", "")

# build_full_url() is required by Sentimel App
def build_full_url(swagger, path_template, path_vals=None, query_params=None):
    base_url = ""
    if "servers" in swagger:
        base_url = swagger["servers"][0].get("url", "")
    elif all(k in swagger for k in ("host", "basePath", "schemes")):
        scheme = swagger["schemes"][0]
        base_url = f"{scheme}://{swagger['host']}{swagger['basePath']}"

    # Replace path parameters
    path = path_template
    if path_vals:
        for k, v in path_vals.items():
            path = path.replace(f"{{{k}}}", urllib.parse.quote(str(v)))

    # Build query string
    query_string = ""
    if query_params:
        query_string = urllib.parse.urlencode(query_params, doseq=True)

    full_url = base_url.rstrip("/") + "/" + path.lstrip("/")
    if query_string:
        full_url += f"?{query_string}"

    return full_url

def resolve_ref(swagger, ref_path):
    """
    Resolves $ref like '#/definitions/post-params' into the actual object.
    """
    if not ref_path.startswith("#/"):
        return {}

    parts = ref_path[2:].split("/")  # Remove '#/' and split by '/'
    ref = swagger
    for part in parts:
        ref = ref.get(part)
        if ref is None:
            return {}
    return ref


