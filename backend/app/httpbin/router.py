"""Routers for the built-in HTTP Bin feature.

Two routers:
  - management_router: authenticated CRUD under /api/v1/httpbin/
  - catch_all_router: unauthenticated capture at /httpbin/{bin_id}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import get_current_user
from app.httpbin.schemas import (
    BinCreateRequest,
    BinResponse,
    BinUpdateRequest,
    CapturedRequestListResponse,
    CapturedRequestResponse,
)
from app.httpbin.service import (
    capture_request,
    clear_requests,
    create_bin,
    delete_bin,
    delete_request,
    get_bin_by_id,
    get_bin_by_id_public,
    get_bins,
    get_request_count,
    get_requests,
    update_bin,
)

# ── Management API (authenticated) ──────────────────────────────

management_router = APIRouter(prefix="/httpbin", tags=["HTTP Bin"])


async def _bin_response(db: AsyncSession, bin_obj) -> BinResponse:
    count = await get_request_count(db, bin_obj.id)
    data = BinResponse.model_validate(bin_obj)
    data.request_count = count
    return data


@management_router.get("/bins", response_model=list[BinResponse])
async def list_bins(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BinResponse]:
    bins = await get_bins(db, current_user.id)
    return [await _bin_response(db, b) for b in bins]


@management_router.post("/bins", response_model=BinResponse, status_code=201)
async def create_bin_endpoint(
    body: BinCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BinResponse:
    bin_obj = await create_bin(db, current_user.id, body)
    return await _bin_response(db, bin_obj)


@management_router.get("/bins/{bin_id}", response_model=BinResponse)
async def get_bin_endpoint(
    bin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BinResponse:
    bin_obj = await get_bin_by_id(db, bin_id, current_user.id)
    if bin_obj is None:
        raise HTTPException(status_code=404, detail="Bin not found")
    return await _bin_response(db, bin_obj)


@management_router.put("/bins/{bin_id}", response_model=BinResponse)
async def update_bin_endpoint(
    bin_id: str,
    body: BinUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BinResponse:
    bin_obj = await update_bin(db, bin_id, current_user.id, body)
    if bin_obj is None:
        raise HTTPException(status_code=404, detail="Bin not found")
    return await _bin_response(db, bin_obj)


@management_router.delete("/bins/{bin_id}", status_code=204, response_model=None)
async def delete_bin_endpoint(
    bin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await delete_bin(db, bin_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Bin not found")


@management_router.get("/bins/{bin_id}/requests", response_model=CapturedRequestListResponse)
async def list_bin_requests(
    bin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CapturedRequestListResponse:
    bin_obj = await get_bin_by_id(db, bin_id, current_user.id)
    if bin_obj is None:
        raise HTTPException(status_code=404, detail="Bin not found")
    requests, total = await get_requests(db, bin_id, limit=limit, offset=offset)
    return CapturedRequestListResponse(
        requests=[CapturedRequestResponse.model_validate(r) for r in requests],
        total=total,
    )


@management_router.delete("/bins/{bin_id}/requests", status_code=204, response_model=None)
async def clear_bin_requests(
    bin_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    bin_obj = await get_bin_by_id(db, bin_id, current_user.id)
    if bin_obj is None:
        raise HTTPException(status_code=404, detail="Bin not found")
    await clear_requests(db, bin_id)


@management_router.delete("/requests/{request_id}", status_code=204, response_model=None)
async def delete_request_endpoint(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await delete_request(db, request_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Request not found")


# ── Catch-all (unauthenticated) ─────────────────────────────────

catch_all_router = APIRouter(tags=["HTTP Bin Catch-All"])

_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


async def _handle_capture(bin_id: str, request: Request, path: str, db: AsyncSession) -> Response:
    bin_obj = await get_bin_by_id_public(db, bin_id)
    if bin_obj is None:
        raise HTTPException(status_code=404, detail="Bin not found")

    raw_body = await request.body()
    body_str = raw_body.decode("utf-8", errors="replace") if raw_body else None
    headers = dict(request.headers)
    query_params = dict(request.query_params)

    await capture_request(
        db,
        bin_id,
        request.method,
        f"/{path}" if path else "/",
        headers,
        query_params,
        body_str,
        request.headers.get("content-type"),
        request.client.host if request.client else None,
    )

    return Response(
        content=bin_obj.response_body or "",
        status_code=bin_obj.response_status_code,
        media_type=bin_obj.response_content_type,
    )


@catch_all_router.api_route("/{bin_id}", methods=_ALL_METHODS)
async def capture_root(
    bin_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _handle_capture(bin_id, request, "", db)


@catch_all_router.api_route("/{bin_id}/{path:path}", methods=_ALL_METHODS)
async def capture_path(
    bin_id: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _handle_capture(bin_id, request, path, db)
