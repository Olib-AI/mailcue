"""Validated API shapes for email warmup administration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Security = Literal["ssl", "starttls", "plain"]


class WarmupAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    provider: str = Field(default="custom", max_length=40)
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Security = "starttls"
    imap_host: str = Field(min_length=1, max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_security: Security = "ssl"
    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    enabled: bool = True
    ownership_confirmed: bool

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid email address")
        return value

    @model_validator(mode="after")
    def confirm_ownership(self) -> WarmupAccountCreate:
        if not self.ownership_confirmed:
            raise ValueError("You must confirm that you own or are authorized to use this account")
        return self


class WarmupAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=1024)


class WarmupAccountResponse(BaseModel):
    id: str
    name: str
    email: str
    provider: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    imap_host: str
    imap_port: int
    imap_security: str
    username: str
    enabled: bool
    verified: bool
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WarmupCampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    local_address: str
    account_ids: list[str] = Field(min_length=1)
    start_daily_volume: int = Field(default=3, ge=1, le=100)
    daily_ramp: int = Field(default=1, ge=0, le=50)
    max_daily_volume: int = Field(default=20, ge=1, le=200)
    min_delay_minutes: int = Field(default=30, ge=5, le=1440)
    max_delay_minutes: int = Field(default=120, ge=5, le=1440)
    reply_rate: int = Field(default=70, ge=0, le=100)
    active_hour_start: int = Field(default=8, ge=0, le=23)
    active_hour_end: int = Field(default=20, ge=1, le=24)
    timezone: str = Field(default="UTC", max_length=64)
    auto_clean_local_mailbox: bool = False

    @field_validator("local_address")
    @classmethod
    def validate_local_address(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid local sender address")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> WarmupCampaignCreate:
        if self.max_daily_volume < self.start_daily_volume:
            raise ValueError("max_daily_volume must be at least start_daily_volume")
        if self.max_delay_minutes < self.min_delay_minutes:
            raise ValueError("max_delay_minutes must be at least min_delay_minutes")
        if self.active_hour_end <= self.active_hour_start:
            raise ValueError("active_hour_end must be after active_hour_start")
        return self


class WarmupCampaignResponse(BaseModel):
    id: str
    name: str
    local_address: str
    account_ids: list[str]
    status: str
    start_daily_volume: int
    daily_ramp: int
    max_daily_volume: int
    min_delay_minutes: int
    max_delay_minutes: int
    reply_rate: int
    active_hour_start: int
    active_hour_end: int
    timezone: str
    auto_clean_local_mailbox: bool
    messages_sent_today: int
    total_sent: int
    total_failed: int
    started_at: datetime | None
    stopped_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WarmupEventResponse(BaseModel):
    id: str
    campaign_id: str
    account_id: str | None
    provider: str | None
    direction: str
    status: str
    subject: str
    message_id: str | None
    error: str | None
    smtp_code: int | None
    enhanced_status: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WarmupProviderStateResponse(BaseModel):
    id: str
    campaign_id: str
    provider: str
    status: str
    sent_today: int
    failed_today: int
    total_sent: int
    total_failed: int
    consecutive_failures: int
    next_attempt_at: datetime | None
    paused_until: datetime | None
    last_sent_at: datetime | None
    last_failure_at: datetime | None
    last_smtp_code: int | None
    last_enhanced_status: str | None
    last_response: str | None

    model_config = ConfigDict(from_attributes=True)
