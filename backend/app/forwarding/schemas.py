"""Pydantic schemas for the email forwarding rules module."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator


class SmtpForwardConfig(BaseModel):
    """Action configuration for SMTP forwarding."""

    to_address: str


class WebhookConfig(BaseModel):
    """Action configuration for webhook delivery."""

    url: str
    method: str = "POST"
    headers: dict[str, str] = {}


class ForwardingRuleCreateRequest(BaseModel):
    """Request body for creating a forwarding rule."""

    name: str
    enabled: bool = True
    match_from: str | None = None
    match_to: str | None = None
    match_subject: str | None = None
    match_mailbox: str | None = None
    action_type: Literal["smtp_forward", "webhook"]
    action_config: dict[str, Any]

    @field_validator("match_from", "match_to", "match_subject", mode="before")
    @classmethod
    def validate_regex_pattern(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return v

    @model_validator(mode="after")
    def validate_action_config(self) -> ForwardingRuleCreateRequest:
        """Validate action_config matches action_type."""
        if self.action_type == "smtp_forward":
            SmtpForwardConfig(**self.action_config)
        elif self.action_type == "webhook":
            WebhookConfig(**self.action_config)
        return self


class ForwardingRuleUpdateRequest(BaseModel):
    """Request body for updating a forwarding rule (all fields optional)."""

    name: str | None = None
    enabled: bool | None = None
    match_from: str | None = None
    match_to: str | None = None
    match_subject: str | None = None
    match_mailbox: str | None = None
    action_type: Literal["smtp_forward", "webhook"] | None = None
    action_config: dict[str, Any] | None = None

    @field_validator("match_from", "match_to", "match_subject", mode="before")
    @classmethod
    def validate_regex_pattern(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return v

    @model_validator(mode="after")
    def validate_action_config(self) -> ForwardingRuleUpdateRequest:
        """Validate action_config when both action_type and action_config are provided."""
        if self.action_type is not None and self.action_config is not None:
            if self.action_type == "smtp_forward":
                SmtpForwardConfig(**self.action_config)
            elif self.action_type == "webhook":
                WebhookConfig(**self.action_config)
        return self


class ForwardingRuleResponse(BaseModel):
    """Public representation of a forwarding rule."""

    id: str
    name: str
    enabled: bool
    match_from: str | None
    match_to: str | None
    match_subject: str | None
    match_mailbox: str | None
    action_type: str
    action_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class ForwardingRuleListResponse(BaseModel):
    """Wrapper for the forwarding rules listing endpoint."""

    rules: list[ForwardingRuleResponse]
    total: int


class TestRuleRequest(BaseModel):
    """Sample email data for dry-run testing a forwarding rule."""

    from_address: str = "sender@example.com"
    to_address: str = "recipient@example.com"
    subject: str = "Test subject"
    mailbox: str = ""


class TestRuleResponse(BaseModel):
    """Result of a dry-run test of a forwarding rule."""

    matched: bool
    rule_id: str
    rule_name: str
    match_details: dict[str, bool]
