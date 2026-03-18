#!/usr/bin/env python3
"""Convert an OpenAPI 3.x spec into a Postman Collection v2.1.

Zero external dependencies -- uses only the Python standard library.
Reads ``openapi.json`` from the repo root and writes
``postman_collection.json`` alongside it.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPO_ROOT / "openapi.json"
OUTPUT_PATH = REPO_ROOT / "postman_collection.json"

# Postman uses {{variable}} placeholders; we default the base URL.
BASE_URL_VAR = "{{baseUrl}}"


def _make_id() -> str:
    return str(uuid.uuid4())


def _openapi_path_to_postman(path: str) -> list[str]:
    """Convert ``/api/v1/emails/{uid}`` to Postman path segments.

    OpenAPI uses ``{param}``; Postman uses ``:param``.
    """
    segments: list[str] = []
    for seg in path.strip("/").split("/"):
        match = re.fullmatch(r"\{(.+)\}", seg)
        if match:
            segments.append(f":{match.group(1)}")
        else:
            segments.append(seg)
    return segments


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a simple ``$ref`` pointer like ``#/components/schemas/Foo``."""
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for part in parts:
        node = node[part]
    return node  # type: ignore[no-any-return]


def _build_example_body(
    spec: dict[str, Any],
    schema: dict[str, Any],
    depth: int = 0,
) -> Any:
    """Produce a minimal example JSON value from an OpenAPI schema."""
    if depth > 6:
        return {}

    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])

    if "example" in schema:
        return schema["example"]

    schema_type = schema.get("type", "object")

    if schema_type == "object":
        props: dict[str, Any] = schema.get("properties", {})
        return {
            key: _build_example_body(spec, prop_schema, depth + 1)
            for key, prop_schema in props.items()
        }

    if schema_type == "array":
        items = schema.get("items", {})
        return [_build_example_body(spec, items, depth + 1)]

    # Scalars
    type_defaults: dict[str, Any] = {
        "string": "string",
        "integer": 0,
        "number": 0.0,
        "boolean": True,
    }
    return schema.get("default", type_defaults.get(schema_type, ""))


def _extract_request_body(
    spec: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any] | None:
    """Build Postman ``body`` from the OpenAPI requestBody (JSON only)."""
    req_body = operation.get("requestBody")
    if not req_body:
        return None

    if "$ref" in req_body:
        req_body = _resolve_ref(spec, req_body["$ref"])

    content: dict[str, Any] = req_body.get("content", {})

    # Prefer application/json
    json_content = content.get("application/json")
    if not json_content:
        return None

    schema = json_content.get("schema", {})
    example = _build_example_body(spec, schema)

    return {
        "mode": "raw",
        "raw": json.dumps(example, indent=2),
        "options": {"raw": {"language": "json"}},
    }


def _build_items(
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Group OpenAPI paths into Postman folder items by tag."""
    folders: dict[str, list[dict[str, Any]]] = {}

    paths: dict[str, Any] = spec.get("paths", {})
    for path, path_item in paths.items():
        for method in ("get", "post", "put", "patch", "delete", "options", "head"):
            operation: dict[str, Any] | None = path_item.get(method)
            if operation is None:
                continue

            tags = operation.get("tags", ["Other"])
            tag = tags[0] if tags else "Other"
            summary = operation.get("summary", f"{method.upper()} {path}")

            # Path segments for Postman URL
            segments = _openapi_path_to_postman(path)

            # Query parameters
            query_params: list[dict[str, str]] = []
            path_vars: list[dict[str, str]] = []
            for param in operation.get("parameters", []):
                if "$ref" in param:
                    param = _resolve_ref(spec, param["$ref"])
                loc = param.get("in", "query")
                if loc == "query":
                    query_params.append(
                        {
                            "key": param["name"],
                            "value": "",
                            "description": param.get("description", ""),
                        }
                    )
                elif loc == "path":
                    path_vars.append(
                        {
                            "key": param["name"],
                            "value": "",
                            "description": param.get("description", ""),
                        }
                    )

            url: dict[str, Any] = {
                "raw": f"{BASE_URL_VAR}/{'/'.join(segments)}",
                "host": [BASE_URL_VAR],
                "path": segments,
            }
            if query_params:
                url["query"] = query_params
            if path_vars:
                url["variable"] = path_vars

            request: dict[str, Any] = {
                "method": method.upper(),
                "header": [],
                "url": url,
                "description": operation.get("description", ""),
            }

            body = _extract_request_body(spec, operation)
            if body:
                request["header"].append(
                    {
                        "key": "Content-Type",
                        "value": "application/json",
                    }
                )
                request["body"] = body

            item: dict[str, Any] = {
                "name": summary,
                "request": request,
                "response": [],
            }

            folders.setdefault(tag, []).append(item)

    # Convert folder dict to Postman folder items
    result: list[dict[str, Any]] = []
    for tag_name, items in folders.items():
        result.append(
            {
                "name": tag_name,
                "item": items,
            }
        )
    return result


def convert(spec: dict[str, Any]) -> dict[str, Any]:
    """Convert a full OpenAPI spec dict to a Postman Collection v2.1 dict."""
    info = spec.get("info", {})
    collection: dict[str, Any] = {
        "info": {
            "_postman_id": _make_id(),
            "name": info.get("title", "API Collection"),
            "description": info.get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": _build_items(spec),
        "variable": [
            {
                "key": "baseUrl",
                "value": "http://localhost:8088",
                "type": "string",
            },
        ],
        "auth": {
            "type": "bearer",
            "bearer": [
                {
                    "key": "token",
                    "value": "{{accessToken}}",
                    "type": "string",
                }
            ],
        },
    }
    return collection


def main() -> None:
    if not OPENAPI_PATH.exists():
        raise SystemExit(
            f"ERROR: {OPENAPI_PATH} not found. Run export_openapi.py first."
        )

    spec: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    collection = convert(spec)

    OUTPUT_PATH.write_text(
        json.dumps(collection, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Postman collection written to {OUTPUT_PATH} "
        f"({OUTPUT_PATH.stat().st_size:,} bytes)"
    )


if __name__ == "__main__":
    main()
