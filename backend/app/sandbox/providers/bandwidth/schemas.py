"""Pydantic schemas for Bandwidth sandbox endpoints.

Bandwidth's API uses camelCase for JSON field names; these Pydantic field
names mirror the wire protocol, so N815 is silenced file-wide.
"""

# ruff: noqa: N815

from __future__ import annotations

from pydantic import BaseModel


class BandwidthSendMessageRequest(BaseModel):
    model_config = {"extra": "ignore"}

    applicationId: str
    to: list[str]
    from_: str | None = None
    text: str | None = None
    media: list[str] | None = None
    tag: str | None = None
    priority: str | None = None
    expiration: str | None = None

    model_config = {"extra": "ignore", "populate_by_name": True}


class BandwidthCreateCallRequest(BaseModel):
    model_config = {"extra": "ignore"}

    from_: str | None = None
    to: str
    applicationId: str
    answerUrl: str | None = None
    answerMethod: str = "POST"
    disconnectUrl: str | None = None
    disconnectMethod: str = "POST"
    callTimeout: float | None = None
    callbackTimeout: float | None = None
    tag: str | None = None
    machineDetection: dict[str, str | float | int] | None = None

    model_config = {"extra": "ignore", "populate_by_name": True}


class BandwidthBrandRequest(BaseModel):
    model_config = {"extra": "ignore"}

    entityType: str = "PRIVATE_PROFIT"
    displayName: str
    companyName: str | None = None
    ein: str | None = None
    email: str
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    postalCode: str | None = None
    country: str = "US"
    stockSymbol: str | None = None
    stockExchange: str | None = None
    brandRelationship: str = "BASIC_ACCOUNT"
    vertical: str = "TECHNOLOGY"
    altBusinessId: str | None = None
    altBusinessIdType: str | None = None


class BandwidthCampaignRequest(BaseModel):
    model_config = {"extra": "ignore"}

    brandId: str
    usecase: str = "MIXED"
    description: str = ""
    sampleMessages: list[str] = []
    hasEmbeddedLinks: bool = False
    hasEmbeddedPhone: bool = False
    subscriberOptIn: bool = True
    subscriberOptOut: bool = True
    subscriberHelp: bool = True
    numberPool: bool = False
    directLending: bool = False
    embeddedLink: bool = False
    embeddedPhone: bool = False
    affiliateMarketing: bool = False
    ageGated: bool = False
