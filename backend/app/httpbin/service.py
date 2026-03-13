"""Core service functions for the HTTP Bin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from app.httpbin.models import HttpBinBin, HttpBinRequest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.httpbin.schemas import BinCreateRequest, BinUpdateRequest


async def get_bins(db: AsyncSession, user_id: str) -> list[HttpBinBin]:
    stmt = select(HttpBinBin).where(HttpBinBin.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_bin_by_id(db: AsyncSession, bin_id: str, user_id: str) -> HttpBinBin | None:
    stmt = select(HttpBinBin).where(HttpBinBin.id == bin_id, HttpBinBin.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_bin_by_id_public(db: AsyncSession, bin_id: str) -> HttpBinBin | None:
    stmt = select(HttpBinBin).where(HttpBinBin.id == bin_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_bin(db: AsyncSession, user_id: str, data: BinCreateRequest) -> HttpBinBin:
    bin_obj = HttpBinBin(
        user_id=user_id,
        name=data.name,
        response_status_code=data.response_status_code,
        response_body=data.response_body,
        response_content_type=data.response_content_type,
    )
    db.add(bin_obj)
    await db.commit()
    await db.refresh(bin_obj)
    return bin_obj


async def update_bin(
    db: AsyncSession, bin_id: str, user_id: str, data: BinUpdateRequest
) -> HttpBinBin | None:
    bin_obj = await get_bin_by_id(db, bin_id, user_id)
    if bin_obj is None:
        return None
    if data.name is not None:
        bin_obj.name = data.name
    if data.response_status_code is not None:
        bin_obj.response_status_code = data.response_status_code
    if data.response_body is not None:
        bin_obj.response_body = data.response_body
    if data.response_content_type is not None:
        bin_obj.response_content_type = data.response_content_type
    await db.commit()
    await db.refresh(bin_obj)
    return bin_obj


async def delete_bin(db: AsyncSession, bin_id: str, user_id: str) -> bool:
    bin_obj = await get_bin_by_id(db, bin_id, user_id)
    if bin_obj is None:
        return False
    await db.delete(bin_obj)
    await db.commit()
    return True


async def get_request_count(db: AsyncSession, bin_id: str) -> int:
    stmt = select(func.count()).select_from(HttpBinRequest).where(HttpBinRequest.bin_id == bin_id)
    result = await db.execute(stmt)
    return result.scalar_one()


async def capture_request(
    db: AsyncSession,
    bin_id: str,
    method: str,
    path: str,
    headers: dict,
    query_params: dict,
    body: str | None,
    content_type: str | None,
    remote_addr: str | None,
) -> HttpBinRequest:
    req = HttpBinRequest(
        bin_id=bin_id,
        method=method,
        path=path,
        headers=headers,
        query_params=query_params,
        body=body,
        content_type=content_type,
        remote_addr=remote_addr,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def get_requests(
    db: AsyncSession, bin_id: str, limit: int = 100, offset: int = 0
) -> tuple[list[HttpBinRequest], int]:
    count_stmt = (
        select(func.count()).select_from(HttpBinRequest).where(HttpBinRequest.bin_id == bin_id)
    )
    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        select(HttpBinRequest)
        .where(HttpBinRequest.bin_id == bin_id)
        .order_by(HttpBinRequest.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def delete_request(db: AsyncSession, request_id: str) -> bool:
    stmt = select(HttpBinRequest).where(HttpBinRequest.id == request_id)
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if req is None:
        return False
    await db.delete(req)
    await db.commit()
    return True


async def clear_requests(db: AsyncSession, bin_id: str) -> int:
    stmt = delete(HttpBinRequest).where(HttpBinRequest.bin_id == bin_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount  # type: ignore[union-attr]
