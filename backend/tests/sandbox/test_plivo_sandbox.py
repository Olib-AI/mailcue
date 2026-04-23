"""End-to-end tests for Plivo sandbox."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient

from tests.conftest import basic_auth_header


def _auth(provider: dict) -> dict[str, str]:
    creds = provider["credentials"]
    return {"Authorization": basic_auth_header(creds["auth_id"], creds["auth_token"])}


def _acc(provider: dict) -> str:
    return provider["credentials"]["auth_id"]


# ── Messages ─────────────────────────────────────────────────────────


async def test_send_message(client: AsyncClient, plivo_provider: dict):
    resp = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Message/",
        data={"src": "+15559876543", "dst": "+15551234567", "text": "Hi"},
        headers=_auth(plivo_provider),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["message"] == "message(s) queued"
    assert len(data["message_uuid"]) == 1


async def test_list_and_fetch_message(client: AsyncClient, plivo_provider: dict):
    send = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Message/",
        data={"src": "+15559876543", "dst": "+15551234567", "text": "ping"},
        headers=_auth(plivo_provider),
    )
    uuid = send.json()["message_uuid"][0]
    fetch = await client.get(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Message/{uuid}/",
        headers=_auth(plivo_provider),
    )
    assert fetch.status_code == 200
    assert fetch.json()["message_uuid"] == uuid


# ── Calls ────────────────────────────────────────────────────────────


async def test_create_call(client: AsyncClient, plivo_provider: dict):
    resp = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Call/",
        data={
            "from": "+15559999999",
            "to": "+15558888888",
            "answer_url": "https://app.example.com/xml/answer",
            "answer_method": "POST",
        },
        headers=_auth(plivo_provider),
    )
    assert resp.status_code == 201
    assert resp.json()["message"] == "call fired"


# ── Numbers ──────────────────────────────────────────────────────────


async def test_available_numbers(client: AsyncClient, plivo_provider: dict):
    resp = await client.get(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/PhoneNumber/",
        params={"country_iso": "US", "type": "local", "limit": 10},
        headers=_auth(plivo_provider),
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["total_count"] >= 1


async def test_buy_list_release(client: AsyncClient, plivo_provider: dict):
    search = await client.get(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/PhoneNumber/",
        params={"country_iso": "US", "type": "local", "limit": 1},
        headers=_auth(plivo_provider),
    )
    number = search.json()["objects"][0]["number"]
    buy = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/PhoneNumber/{number}/",
        headers=_auth(plivo_provider),
    )
    assert buy.status_code == 201

    lst = await client.get(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Number/",
        headers=_auth(plivo_provider),
    )
    assert any(n["number"] == number for n in lst.json()["objects"])

    rel = await client.delete(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Number/{number}/",
        headers=_auth(plivo_provider),
    )
    assert rel.status_code == 204


# ── 10DLC ────────────────────────────────────────────────────────────


async def test_brand_and_campaign(client: AsyncClient, plivo_provider: dict):
    brand = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/10dlc/Brand/",
        data={
            "brand_name": "ACME",
            "company_name": "ACME Inc",
            "ein": "12-3456789",
            "vertical": "TECHNOLOGY",
        },
        headers=_auth(plivo_provider),
    )
    assert brand.status_code == 201
    bid = brand.json()["brand_id"]
    await asyncio.sleep(0.2)
    fetch = await client.get(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/10dlc/Brand/{bid}/",
        headers=_auth(plivo_provider),
    )
    assert fetch.json()["status"] in {"PENDING", "APPROVED"}

    camp = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/10dlc/Campaign/",
        data={
            "brand_id": bid,
            "usecase": "MARKETING",
            "description": "Promotions",
            "sample_messages": ["msg1", "msg2"],
        },
        headers=_auth(plivo_provider),
    )
    assert camp.status_code == 201


# ── Port ─────────────────────────────────────────────────────────────


async def test_port_lifecycle(client: AsyncClient, plivo_provider: dict):
    port = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Port/",
        data={"phone_numbers": ["+15551234567"], "loa_type": "CARRIER"},
        headers=_auth(plivo_provider),
    )
    assert port.status_code == 201
    pid = port.json()["port_id"]
    await asyncio.sleep(0.25)
    fetch = await client.get(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Port/{pid}/",
        headers=_auth(plivo_provider),
    )
    assert fetch.status_code == 200
    assert fetch.json()["status"] in {"SUBMITTED", "APPROVED", "FOC_SCHEDULED", "COMPLETED"}


async def test_invalid_auth(client: AsyncClient, plivo_provider: dict):
    resp = await client.post(
        f"/sandbox/plivo/v1/Account/{_acc(plivo_provider)}/Message/",
        data={"src": "+1", "dst": "+1", "text": "x"},
        headers={"Authorization": basic_auth_header("wrong", "wrong")},
    )
    assert resp.status_code == 401
