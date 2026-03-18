#!/usr/bin/env python3
"""Extract the OpenAPI spec from the FastAPI app and write it to openapi.json.

This script imports the FastAPI application directly and calls its
``openapi()`` method -- no running server required.  The output is
written to the repository root as ``openapi.json``.

Workaround
----------
Several router modules use ``from __future__ import annotations`` (PEP 563),
which defers annotation evaluation.  Pydantic v2.11+ cannot resolve the
resulting ``ForwardRef`` objects inside ``TypeAdapter`` instances that
FastAPI creates at import time.  Body parameters are misclassified as
query parameters with unresolved forward references.

This script detects those broken parameters, resolves the forward refs
against the endpoint module's namespace, and moves them back to
``body_params`` before generating the schema.
"""

import inspect
import json
import os
import sys
from pathlib import Path
from typing import get_type_hints

from pydantic import TypeAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("MAILCUE_SANDBOX_ENABLED", "false")

from app.main import app  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "openapi.json"


def _fix_forward_ref_params() -> None:
    """Resolve ForwardRef body params that were misclassified as query params."""
    from fastapi._compat import ModelField
    from fastapi.params import Body as BodyInfo

    for route in app.routes:
        dep = getattr(route, "dependant", None)
        endpoint = getattr(route, "endpoint", None)
        if dep is None or endpoint is None:
            continue

        mod = inspect.getmodule(endpoint)
        if mod is None:
            continue

        to_move: list[tuple[int, object]] = []
        for i, qp in enumerate(dep.query_params):
            if "ForwardRef" not in repr(qp._type_adapter):
                continue
            try:
                hints = get_type_hints(endpoint, globalns=vars(mod))
            except Exception:
                continue
            resolved = hints.get(qp.alias)
            if resolved is None:
                continue
            new_field = ModelField(
                field_info=BodyInfo(),
                name=qp.alias,
                mode="validation",
            )
            new_field._type_adapter = TypeAdapter(resolved)
            to_move.append((i, new_field))

        for idx, new_field in reversed(to_move):
            dep.query_params.pop(idx)
            dep.body_params.append(new_field)


def main() -> None:
    _fix_forward_ref_params()
    spec = app.openapi()
    OUTPUT_PATH.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"OpenAPI spec written to {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)"
    )


if __name__ == "__main__":
    main()
