"""API contracts for report history, baselines, and comparisons."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.emails.schemas import DeliverabilityCategory


def _default_blocked_statuses() -> list[Literal["warning", "fail"]]:
    return ["fail"]


type DeliverabilityRunCheck = Literal[
    "dns",
    "reputation",
    "links",
    "visual",
    "placement",
    "client_previews",
    "ai_analysis",
]


def _default_run_checks() -> list[DeliverabilityRunCheck]:
    return ["dns", "reputation"]


class DeliverabilityReportSummary(BaseModel):
    id: str
    mailbox: str
    uid: str
    folder: str
    message_id: str
    raw_sha256: str
    score_version: str
    score: int
    verdict: str
    is_baseline: bool
    created_at: datetime


class DeliverabilityReportList(BaseModel):
    reports: list[DeliverabilityReportSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class BaselineUpdateRequest(BaseModel):
    is_baseline: bool = True


class DeliverabilityCheckChange(BaseModel):
    id: str
    title: str
    before_status: str | None = None
    after_status: str | None = None
    before_points: float | None = None
    after_points: float | None = None
    points_delta: float


class DeliverabilityCategoryChange(BaseModel):
    id: str
    title: str
    before_score: int | None = None
    after_score: int | None = None
    score_delta: int | None = None
    check_changes: list[DeliverabilityCheckChange] = Field(default_factory=list)


class DeliverabilityComparison(BaseModel):
    before_report_id: str
    after_report_id: str
    before_score: int
    after_score: int
    score_delta: int
    improved: int
    regressed: int
    unchanged: int
    categories: list[DeliverabilityCategoryChange]


class DeliverabilityCapability(BaseModel):
    id: str
    title: str
    description: str
    mode: Literal["local", "network", "provider"]
    status: Literal["available", "disabled", "not_configured", "unavailable"]
    reason: str | None = None


class DeliverabilityCapabilities(BaseModel):
    capabilities: list[DeliverabilityCapability]


class DeliverabilityPolicyWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mailbox: str = Field(min_length=3, max_length=320)
    enabled: bool = True
    minimum_score: int = Field(default=80, ge=0, le=100)
    maximum_regression: int = Field(default=5, ge=0, le=100)
    fail_on_statuses: list[Literal["warning", "fail"]] = Field(
        default_factory=_default_blocked_statuses
    )
    required_check_ids: list[str] = Field(default_factory=list, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("name", "mailbox")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("required_check_ids", "required_capabilities")
    @classmethod
    def _normalize_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("values must be unique")
        return normalized


class DeliverabilityPolicyResponse(BaseModel):
    id: str
    name: str
    mailbox: str
    enabled: bool
    minimum_score: int
    maximum_regression: int
    fail_on_statuses: list[str]
    required_check_ids: list[str]
    required_capabilities: list[str]
    created_at: datetime
    updated_at: datetime


class DeliverabilityPolicyEvaluationResponse(BaseModel):
    id: str
    policy_id: str
    report_id: str
    passed: bool
    score: int
    score_delta: int | None = None
    reasons: list[str]
    created_at: datetime


class DeliverabilityRunRequest(BaseModel):
    checks: list[DeliverabilityRunCheck] = Field(
        default_factory=_default_run_checks, min_length=1, max_length=7
    )

    @field_validator("checks")
    @classmethod
    def _unique_checks(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("checks must be unique")
        return values


class DeliverabilityRunResponse(BaseModel):
    id: str
    report_id: str
    status: Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
    requested_checks: list[str]
    capabilities: DeliverabilityCapabilities
    categories: list[DeliverabilityCategory] = Field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DeliverabilityTrendPoint(BaseModel):
    report_id: str
    score: int
    verdict: str
    created_at: datetime


class DeliverabilityTrend(BaseModel):
    mailbox: str
    points: list[DeliverabilityTrendPoint]
    count: int
    average_score: float | None
    minimum_score: int | None
    maximum_score: int | None
    score_delta: int | None


class DeliverabilityProviderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["preview", "placement", "analysis"]
    adapter: Literal["generic_http_preview", "seed_imap", "generic_http_analysis"]
    enabled: bool = True
    config: dict[str, str | int | bool | list[str]] = Field(default_factory=dict)
    secret: str | None = Field(default=None, max_length=8192)

    @field_validator("name")
    @classmethod
    def _provider_name(cls, value: str) -> str:
        return value.strip()


class DeliverabilityProviderResponse(BaseModel):
    id: str
    name: str
    kind: str
    adapter: str
    enabled: bool
    config: dict[str, str | int | bool | list[str]]
    has_secret: bool
    last_status: str
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeliverabilityScheduleWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mailbox: str = Field(min_length=3, max_length=320)
    enabled: bool = True
    interval_minutes: int = Field(default=60, ge=5, le=43_200)
    checks: list[DeliverabilityRunCheck] = Field(default_factory=list, max_length=7)
    policy_id: str | None = Field(default=None, max_length=36)

    @field_validator("name", "mailbox")
    @classmethod
    def _schedule_required(cls, value: str) -> str:
        return value.strip()

    @field_validator("checks")
    @classmethod
    def _schedule_unique_checks(
        cls, values: list[DeliverabilityRunCheck]
    ) -> list[DeliverabilityRunCheck]:
        if len(values) != len(set(values)):
            raise ValueError("checks must be unique")
        return values


class DeliverabilityScheduleResponse(BaseModel):
    id: str
    name: str
    mailbox: str
    enabled: bool
    interval_minutes: int
    checks: list[str]
    policy_id: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeliverabilityAlertResponse(BaseModel):
    id: str
    mailbox: str
    report_id: str | None
    run_id: str | None
    policy_id: str | None
    alert_type: str
    severity: str
    title: str
    detail: str
    acknowledged: bool
    created_at: datetime
    acknowledged_at: datetime | None


class DeliverabilityAlertList(BaseModel):
    alerts: list[DeliverabilityAlertResponse]
    total: int
