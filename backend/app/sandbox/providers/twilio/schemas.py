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
    num_media: str = "0"
    price: str | None = None
    price_unit: str = "USD"
    uri: str


class SendSMSRequest(BaseModel):
    """Request body for sending an SMS.

    Accepts both JSON bodies (tests) and form-encoded bodies (Twilio SDK).
    ``MediaUrl`` may be a single URL or a list when form-encoded with
    repeated ``MediaUrl`` params.
    """

    model_config = {"from_attributes": True, "populate_by_name": True, "extra": "ignore"}

    To: str
    From: str | None = None
    MessagingServiceSid: str | None = None
    Body: str = ""
    MediaUrl: list[str] | str | None = None
    StatusCallback: str | None = None
    ApplicationSid: str | None = None
    MaxPrice: str | None = None
    ProvideFeedback: bool | None = None
    ValidityPeriod: int | None = None


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


class CreateCallRequest(BaseModel):
    """Request body for POST /Calls.json."""

    model_config = {"extra": "ignore"}

    To: str
    From: str
    Url: str | None = None
    ApplicationSid: str | None = None
    Method: str = "POST"
    StatusCallback: str | None = None
    StatusCallbackMethod: str = "POST"
    StatusCallbackEvent: list[str] | None = None
    SendDigits: str | None = None
    Timeout: int = 60
    Record: bool = False
    RecordingStatusCallback: str | None = None
    Machine_Detection: str | None = Field(default=None, alias="MachineDetection")


class UpdateCallRequest(BaseModel):
    """Request body for POST /Calls/{Sid}.json."""

    model_config = {"extra": "ignore"}

    Status: str | None = None
    Url: str | None = None
    Method: str | None = None


class PurchaseNumberRequest(BaseModel):
    """Request body for POST /IncomingPhoneNumbers.json."""

    model_config = {"extra": "ignore"}

    PhoneNumber: str | None = None
    AreaCode: str | None = None
    FriendlyName: str | None = None
    SmsUrl: str | None = None
    SmsMethod: str = "POST"
    VoiceUrl: str | None = None
    VoiceMethod: str = "POST"
    StatusCallback: str | None = None


class UpdateIncomingNumberRequest(BaseModel):
    model_config = {"extra": "ignore"}

    FriendlyName: str | None = None
    SmsUrl: str | None = None
    SmsMethod: str | None = None
    VoiceUrl: str | None = None
    VoiceMethod: str | None = None
    StatusCallback: str | None = None


class PortingOrderRequest(BaseModel):
    model_config = {"extra": "ignore"}

    phone_numbers: list[str] = []
    target_account_sid: str | None = None
    notification_emails: list[str] = []
    loa_info: dict[str, str] = {}


class BrandRegistrationRequest(BaseModel):
    model_config = {"extra": "ignore"}

    CustomerProfileBundleSid: str | None = None
    A2PProfileBundleSid: str | None = None
    BrandType: str = "STANDARD"
    Mock: bool = False


class UsAppToPersonRequest(BaseModel):
    model_config = {"extra": "ignore"}

    BrandRegistrationSid: str
    Description: str = ""
    MessageSamples: list[str] = []
    UsAppToPersonUsecase: str = "MIXED"
    HasEmbeddedLinks: bool = False
    HasEmbeddedPhone: bool = False


class CustomerProfileRequest(BaseModel):
    model_config = {"extra": "ignore"}

    FriendlyName: str
    Email: str
    PolicySid: str | None = None
    StatusCallback: str | None = None
