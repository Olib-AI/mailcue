"""Pydantic v2 schemas for the HTTP Bin API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BinCreateRequest(BaseModel):
    name: str
    response_status_code: int = 200
    response_body: str = ""
    response_content_type: str = "application/json"


class BinUpdateRequest(BaseModel):
    name: str | None = None
    response_status_code: int | None = None
    response_body: str | None = None
    response_content_type: str | None = None


class BinResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    name: str
    response_status_code: int
    response_body: str | None = None
    response_content_type: str
    created_at: datetime
    request_count: int = 0


class CapturedRequestResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    bin_id: str
    method: str
    path: str
    headers: dict  # type: ignore[assignment]
    query_params: dict  # type: ignore[assignment]
    body: str | None = None
    content_type: str | None = None
    remote_addr: str | None = None
    created_at: datetime


class CapturedRequestListResponse(BaseModel):
    requests: list[CapturedRequestResponse]
    total: int
