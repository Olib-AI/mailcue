"""Forwarding rules router -- full CRUD plus dry-run test endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import get_current_user
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


@router.get("", response_model=ForwardingRuleListResponse)
async def list_forwarding_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleListResponse:
    """List all forwarding rules for the authenticated user."""
    rules = await list_rules(current_user.id, db)
    responses = [rule_to_response(r) for r in rules]
    return ForwardingRuleListResponse(rules=responses, total=len(responses))


@router.post(
    "",
    response_model=ForwardingRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_forwarding_rule(
    body: ForwardingRuleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleResponse:
    """Create a new forwarding rule.

    The rule begins matching immediately when ``enabled`` is ``True``
    (the default).
    """
    rule = await create_rule(body, current_user.id, db)
    return rule_to_response(rule)


@router.get("/{rule_id}", response_model=ForwardingRuleResponse)
async def get_forwarding_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleResponse:
    """Fetch a single forwarding rule by ID."""
    rule = await get_rule(rule_id, current_user.id, db)
    return rule_to_response(rule)


@router.put("/{rule_id}", response_model=ForwardingRuleResponse)
async def update_forwarding_rule(
    rule_id: str,
    body: ForwardingRuleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ForwardingRuleResponse:
    """Update an existing forwarding rule (partial update).

    Only fields present in the request body are modified.
    """
    rule = await update_rule(rule_id, body, current_user.id, db)
    return rule_to_response(rule)


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_forwarding_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a forwarding rule."""
    await delete_rule(rule_id, current_user.id, db)


@router.post("/{rule_id}/test", response_model=TestRuleResponse)
async def test_forwarding_rule(
    rule_id: str,
    body: TestRuleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestRuleResponse:
    """Dry-run test a forwarding rule against sample email data.

    No action is actually executed -- the response indicates whether
    the rule would have matched and which patterns contributed.
    """
    return await test_rule(rule_id, current_user.id, body, db)
