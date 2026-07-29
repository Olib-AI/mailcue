"""Admin-only API for controlled email warmup campaigns."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import scopes
from app.auth.models import User
from app.database import get_db
from app.dependencies import require_admin, require_scope
from app.warmup.models import (
    WarmupAccount,
    WarmupCampaign,
    WarmupEvent,
    WarmupProviderState,
)
from app.warmup.schemas import (
    WarmupAccountCreate,
    WarmupAccountResponse,
    WarmupAccountUpdate,
    WarmupCampaignCreate,
    WarmupCampaignResponse,
    WarmupEventResponse,
    WarmupProviderStateResponse,
)
from app.warmup.service import (
    check_account,
    clear_local_warmup_mailbox_sync,
    create_account,
    create_campaign,
    encrypt_password,
    ensure_provider_states,
    provider_defaults,
    set_campaign_status,
    update_campaign,
    validate_sender_domain,
)

router = APIRouter(prefix="/warmup", tags=["Warmup"])


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/providers", dependencies=[Depends(require_scope(scopes.WARMUP_READ))])
async def providers(_admin: User = Depends(require_admin)) -> dict[str, dict[str, object]]:
    return {name: provider_defaults(name) for name in ("gmail", "yahoo", "icloud", "outlook")}


@router.get(
    "/accounts",
    response_model=list[WarmupAccountResponse],
    dependencies=[Depends(require_scope(scopes.WARMUP_READ))],
)
async def list_accounts(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[WarmupAccountResponse]:
    rows = (
        (await db.execute(select(WarmupAccount).order_by(WarmupAccount.created_at)))
        .scalars()
        .all()
    )
    return [WarmupAccountResponse.model_validate(row) for row in rows]


@router.post(
    "/accounts",
    response_model=WarmupAccountResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def add_account(
    body: WarmupAccountCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupAccountResponse:
    try:
        row = await create_account(body, db)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return WarmupAccountResponse.model_validate(row)


@router.patch(
    "/accounts/{account_id}",
    response_model=WarmupAccountResponse,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def update_account(
    account_id: str,
    body: WarmupAccountUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupAccountResponse:
    row = await db.get(WarmupAccount, account_id)
    if row is None:
        raise HTTPException(404, "Warmup account not found")
    values = body.model_dump(exclude_unset=True)
    password = values.pop("password", None)
    for key, value in values.items():
        setattr(row, key, value)
    if password:
        row.password_encrypted = encrypt_password(password)
        row.verified = False
    await db.commit()
    await db.refresh(row)
    return WarmupAccountResponse.model_validate(row)


@router.post(
    "/accounts/{account_id}/check", dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))]
)
async def test_account(
    account_id: str, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    row = await db.get(WarmupAccount, account_id)
    if row is None:
        raise HTTPException(404, "Warmup account not found")
    ok, message = await check_account(row, db)
    return {"ok": ok, "message": message}


@router.delete(
    "/accounts/{account_id}",
    status_code=204,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def remove_account(
    account_id: str, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    row = await db.get(WarmupAccount, account_id)
    if row is None:
        raise HTTPException(404, "Warmup account not found")
    campaigns = (
        (await db.execute(select(WarmupCampaign).where(WarmupCampaign.status == "active")))
        .scalars()
        .all()
    )
    if any(account_id in c.account_ids for c in campaigns):
        raise HTTPException(409, "Stop the active campaign using this account before deleting it")
    await db.delete(row)
    await db.commit()


@router.get(
    "/campaigns",
    response_model=list[WarmupCampaignResponse],
    dependencies=[Depends(require_scope(scopes.WARMUP_READ))],
)
async def list_campaigns(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[WarmupCampaignResponse]:
    rows = (
        (await db.execute(select(WarmupCampaign).order_by(desc(WarmupCampaign.created_at))))
        .scalars()
        .all()
    )
    return [WarmupCampaignResponse.model_validate(row) for row in rows]


@router.post(
    "/campaigns",
    response_model=WarmupCampaignResponse,
    status_code=201,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def add_campaign(
    body: WarmupCampaignCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupCampaignResponse:
    try:
        row = await create_campaign(body, db)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return WarmupCampaignResponse.model_validate(row)


@router.put(
    "/campaigns/{campaign_id}",
    response_model=WarmupCampaignResponse,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def edit_campaign(
    campaign_id: str,
    body: WarmupCampaignCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupCampaignResponse:
    row = await db.get(WarmupCampaign, campaign_id)
    if row is None:
        raise HTTPException(404, "Warmup campaign not found")
    try:
        row = await update_campaign(row, body, db)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return WarmupCampaignResponse.model_validate(row)


# Keep fixed campaign subroutes above the generic ``/{action}`` route.
# Starlette resolves routes in declaration order, so otherwise
# ``clear-mailbox`` is consumed as an action and returns the misleading
# "Action must be start, pause, or stop" response.
@router.post(
    "/campaigns/{campaign_id}/clear-mailbox",
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def clear_campaign_mailbox(
    campaign_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    row = await db.get(WarmupCampaign, campaign_id)
    if row is None:
        raise HTTPException(404, "Warmup campaign not found")
    accounts = (
        (await db.execute(select(WarmupAccount).where(WarmupAccount.id.in_(row.account_ids))))
        .scalars()
        .all()
    )
    external_emails = [a.email for a in accounts]
    try:
        deleted = await asyncio.to_thread(
            clear_local_warmup_mailbox_sync, row.local_address, external_emails
        )
    except Exception as exc:
        raise HTTPException(500, f"Failed to clear local mailbox: {exc}") from exc
    return {"ok": True, "deleted_count": deleted}


@router.post(
    "/campaigns/{campaign_id}/{action}",
    response_model=WarmupCampaignResponse,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def control_campaign(
    campaign_id: str,
    action: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupCampaignResponse:
    row = await db.get(WarmupCampaign, campaign_id)
    if row is None:
        raise HTTPException(404, "Warmup campaign not found")
    if action == "start":
        accounts = (
            (await db.execute(select(WarmupAccount).where(WarmupAccount.id.in_(row.account_ids))))
            .scalars()
            .all()
        )
        if not accounts or any(not a.enabled or not a.verified for a in accounts):
            raise HTTPException(
                409, "Every campaign account must be enabled and connection-tested before starting"
            )
        try:
            await validate_sender_domain(row.local_address, db)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await ensure_provider_states(row, list(accounts), db)
    try:
        row = await set_campaign_status(row, action, db)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    return WarmupCampaignResponse.model_validate(row)


@router.delete(
    "/campaigns/{campaign_id}",
    status_code=204,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def remove_campaign(
    campaign_id: str, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    row = await db.get(WarmupCampaign, campaign_id)
    if row is None:
        raise HTTPException(404, "Warmup campaign not found")
    if row.status == "active":
        raise HTTPException(409, "Stop the campaign before deleting it")
    await db.delete(row)
    states = (
        (
            await db.execute(
                select(WarmupProviderState).where(WarmupProviderState.campaign_id == campaign_id)
            )
        )
        .scalars()
        .all()
    )
    for state in states:
        await db.delete(state)
    await db.commit()


@router.get(
    "/provider-states",
    response_model=list[WarmupProviderStateResponse],
    dependencies=[Depends(require_scope(scopes.WARMUP_READ))],
)
async def list_provider_states(
    campaign_id: str | None = None,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[WarmupProviderStateResponse]:
    stmt = select(WarmupProviderState)
    if campaign_id:
        stmt = stmt.where(WarmupProviderState.campaign_id == campaign_id)
    rows = (
        (
            await db.execute(
                stmt.order_by(WarmupProviderState.campaign_id, WarmupProviderState.provider)
            )
        )
        .scalars()
        .all()
    )
    return [WarmupProviderStateResponse.model_validate(row) for row in rows]


@router.post(
    "/provider-states/{state_id}/resume",
    response_model=WarmupProviderStateResponse,
    dependencies=[Depends(require_scope(scopes.WARMUP_MANAGE))],
)
async def resume_provider(
    state_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> WarmupProviderStateResponse:
    row = await db.get(WarmupProviderState, state_id)
    if row is None:
        raise HTTPException(404, "Warmup provider state not found")
    row.status = "healthy"
    row.consecutive_failures = 0
    row.paused_until = None
    row.next_attempt_at = None
    campaign = await db.get(WarmupCampaign, row.campaign_id)
    if campaign is not None and campaign.status == "active":
        campaign.next_run_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await db.refresh(row)
    return WarmupProviderStateResponse.model_validate(row)


@router.get(
    "/events",
    response_model=list[WarmupEventResponse],
    dependencies=[Depends(require_scope(scopes.WARMUP_READ))],
)
async def list_events(
    campaign_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[WarmupEventResponse]:
    stmt = select(WarmupEvent)
    if campaign_id:
        stmt = stmt.where(WarmupEvent.campaign_id == campaign_id)
    rows = (
        (await db.execute(stmt.order_by(desc(WarmupEvent.created_at)).limit(limit)))
        .scalars()
        .all()
    )
    return [WarmupEventResponse.model_validate(row) for row in rows]
