"""Pydantic schemas mirroring Twilio REST API data structures."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TwilioMessage(BaseModel):
    """Twilio Message resource."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    sid: str
    account_sid: str
    from_: str = Field(alias="from")
    to: str
    body: str
    status: str = "queued"
    direction: str
    date_created: str
    date_updated: str
    date_sent: str | None = None
    num_segments: str = "1"
    price: str | None = None
    price_unit: str = "USD"
    uri: str


class SendSMSRequest(BaseModel):
    """Request body for sending an SMS."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    To: str
    From: str
    Body: str
    StatusCallback: str | None = None


class TwilioMessageListResponse(BaseModel):
    """Twilio message list envelope."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    messages: list[TwilioMessage]
    end: int
    first_page_uri: str
    next_page_uri: str | None = None
    page: int = 0
    page_size: int = 50
    start: int = 0
    uri: str
