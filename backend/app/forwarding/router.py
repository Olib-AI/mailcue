"""Forwarding rules router -- full CRUD plus dry-run test endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import scopes
from app.database import get_db
from app.dependencies import AuthContext, get_auth, require_scope
from app.forwarding.schemas import (
    ForwardingRuleCreateRequest,
    ForwardingRuleListResponse,
    ForwardingRuleResponse,
    ForwardingRuleUpdateRequest,
    TestRuleRequest,
    TestRuleResponse,
)
from app.forwarding.service import (
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    rule_to_response,
    test_rule,
    update_rule,
)

logger = logging.getLogger("mailcue.forwarding")

router = APIRouter(prefix="/forwarding-rules", tags=["Forwarding Rules"])


def _require_unrestricted_mailbox_context(auth: AuthContext) -> None:
    """Forwarding regex rules are not safely reducible to an API-key allow-list."""
    if auth.allowed_mailboxes is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mailbox-restricted API keys cannot manage forwarding rules",
        )


@router.get(
    "",
    response_model=ForwardingRuleListResponse,
    dependencies=[Depends(require_scope(scopes.FORWARDING_READ))],
)
async def list_forwarding_rules(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleListResponse:
    """List all forwarding rules for the authenticated user."""
    _require_unrestricted_mailbox_context(auth)
    rules = await list_rules(auth.user.id, db)
    responses = [rule_to_response(r) for r in rules]
    return ForwardingRuleListResponse(rules=responses, total=len(responses))


@router.post(
    "",
    response_model=ForwardingRuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope(scopes.FORWARDING_MANAGE))],
)
async def create_forwarding_rule(
    body: ForwardingRuleCreateRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleResponse:
    """Create a new forwarding rule.

    The rule begins matching immediately when ``enabled`` is ``True``
    (the default).
    """
    _require_unrestricted_mailbox_context(auth)
    rule = await create_rule(body, auth.user.id, db)
    return rule_to_response(rule)


@router.get(
    "/{rule_id}",
    response_model=ForwardingRuleResponse,
    dependencies=[Depends(require_scope(scopes.FORWARDING_READ))],
)
async def get_forwarding_rule(
    rule_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleResponse:
    """Fetch a single forwarding rule by ID."""
    _require_unrestricted_mailbox_context(auth)
    rule = await get_rule(rule_id, auth.user.id, db)
    return rule_to_response(rule)


@router.put(
    "/{rule_id}",
    response_model=ForwardingRuleResponse,
    dependencies=[Depends(require_scope(scopes.FORWARDING_MANAGE))],
)
async def update_forwarding_rule(
    rule_id: str,
    body: ForwardingRuleUpdateRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleResponse:
    """Update an existing forwarding rule (partial update).

    Only fields present in the request body are modified.
    """
    _require_unrestricted_mailbox_context(auth)
    rule = await update_rule(rule_id, body, auth.user.id, db)
    return rule_to_response(rule)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_scope(scopes.FORWARDING_MANAGE))],
)
async def delete_forwarding_rule(
    rule_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a forwarding rule."""
    _require_unrestricted_mailbox_context(auth)
    await delete_rule(rule_id, auth.user.id, db)


@router.post(
    "/{rule_id}/test",
    response_model=TestRuleResponse,
    dependencies=[Depends(require_scope(scopes.FORWARDING_MANAGE))],
)
async def test_forwarding_rule(
    rule_id: str,
    body: TestRuleRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> TestRuleResponse:
    """Dry-run test a forwarding rule against sample email data.

    No action is actually executed -- the response indicates whether
    the rule would have matched and which patterns contributed.
    """
    _require_unrestricted_mailbox_context(auth)
    return await test_rule(rule_id, auth.user.id, body, db)
