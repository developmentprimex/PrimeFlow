import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import dialect

from app.api.routers import microsoft_mail as api
from app.integrations import microsoft_mail as mail
from app.models.enums import UserRole
from app.services.info_px_notes import save_info_px_notes


def test_authorize_requests_read_only_permissions(monkeypatch):
    monkeypatch.setattr(mail.settings, "MS_MAIL_CLIENT_ID", "pilot")
    monkeypatch.setattr(mail.settings, "MS_MAIL_TENANT_ID", "tenant")
    monkeypatch.setattr(mail.settings, "MS_MAIL_REDIRECT_URI", "https://example.com/api/microsoft-mail/callback")
    url = mail.authorization_url("signed-state", "private-verifier")
    params = parse_qs(urlsplit(url).query)
    assert set(params["scope"][0].split()) == {"offline_access", "User.Read", "Mail.Read"}
    assert params["code_challenge_method"] == ["S256"]
    assert params["login_hint"] == ["info@primexeu.com"]
    assert "private-verifier" not in url


def test_graph_reads_inbox_directly_in_report_timezone():
    def respond(request):
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer sample"
        assert request.url.path.endswith("/mailFolders/inbox/messages")
        assert request.headers["Prefer"] == 'outlook.body-content-type="text", IdType="ImmutableId"'
        assert "2026-11-22T23:00:00Z" in request.url.params["$filter"]
        assert "2026-11-23T23:00:00Z" in request.url.params["$filter"]
        return httpx.Response(200, json={"value": [{
            "id": "mail-1", "subject": "A test", "receivedDateTime": "2026-11-23T09:50:00Z",
            "from": {"emailAddress": {"name": "Sender", "address": "sender@example.test"}},
            "body": {"contentType": "text", "content": "The email body"},
        }]})

    async def read():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await mail.read_inbox(client, "sample", date(2026, 11, 23), ZoneInfo("Europe/Tirane"))

    assert asyncio.run(read()) == [{
        "id": "mail-1", "subject": "A test", "sender": "Sender <sender@example.test>",
        "received_at": "10:50", "received_datetime": "2026-11-23T10:50:00+01:00", "body": "The email body",
    }]


def test_signed_in_staff_can_read_but_only_admin_can_authorize(monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix="/api/microsoft-mail")
    app.dependency_overrides[api.get_db] = lambda: None
    monkeypatch.setattr(api, "_configured", lambda: False)
    endpoint = "/api/microsoft-mail/sync?report_date=2026-11-23"
    client = TestClient(app)
    assert client.post(endpoint).status_code == 401

    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, is_active=True)
    app.dependency_overrides[api.get_current_user] = lambda: user
    response = client.post(endpoint)
    assert response.json() == {"configured": False, "connected": False, "messages": []}
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/microsoft-mail/authorize-url").status_code == 403


def test_px_note_preserves_sender_and_reuses_the_same_id():
    db = AsyncMock()
    message = {
        "id": "immutable-id", "subject": "Kërkesë", "sender": "Drita <drita@example.test>",
        "received_datetime": "2026-11-23T10:50:00+01:00", "body": "Rreshti 1\nRreshti 2",
    }
    asyncio.run(save_info_px_notes(db, [message, message]))
    asyncio.run(save_info_px_notes(db, [message]))
    first, second = (
        call.args[0].compile(dialect=dialect()) for call in db.execute.await_args_list
    )
    assert first.params == second.params
    assert first.params["content_m0"] == "EM INFO PX - Kërkesë\nDërguesi: Drita <drita@example.test>\n\nRreshti 1\nRreshti 2"
    assert first.params["knowledge_type_m0"] == "INFO_PX_MAIL"
    assert "ON CONFLICT (id) DO NOTHING" in str(first)
    assert db.commit.await_count == 2


def test_authorization_state_is_browser_bound_and_tokens_are_encrypted(monkeypatch):
    monkeypatch.setattr(api.settings, "MS_MAIL_SIGNING_KEY", "test-signing-material-at-least-32-bytes")
    monkeypatch.setattr(api.settings, "MS_MAIL_REDIRECT_URI", "https://example.test/api/microsoft-mail/callback")
    monkeypatch.setattr(api, "_configured", lambda: True)
    app = FastAPI()
    app.include_router(api.router, prefix="/api/microsoft-mail")
    app.dependency_overrides[api.get_db] = lambda: None
    admin = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, is_active=True)
    app.dependency_overrides[api.get_current_user] = lambda: admin
    client = TestClient(app, base_url="https://example.test")
    response = client.post("/api/microsoft-mail/authorize-url")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    state = parse_qs(urlsplit(response.json()["url"]).query)["state"][0]
    unrelated_browser = TestClient(app, base_url="https://example.test")
    assert unrelated_browser.get("/api/microsoft-mail/callback", params={"state": state, "code": "example"}).status_code == 400

    fields = api._token_fields({"access_token": "access-example", "refresh_token": "refresh-example"})
    for field, value in (("access_token", "access-example"), ("refresh_token", "refresh-example")):
        assert fields[field] != value
        assert api._cipher().decrypt(fields[field].encode()).decode() == value
