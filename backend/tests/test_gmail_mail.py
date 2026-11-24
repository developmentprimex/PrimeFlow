import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import microsoft_mail as api
from app.integrations import gmail_mail
from app.models.enums import UserRole


def test_gmail_authorization_is_read_only_and_bound_to_its_callback(monkeypatch):
    monkeypatch.setattr(api.settings, "GMAIL_PX_EU_CLIENT_ID", "gmail-web-client")
    monkeypatch.setattr(api.settings, "GMAIL_PX_EU_CLIENT_SECRET", "gmail-secret")
    monkeypatch.setattr(api.settings, "GMAIL_PX_EU_REDIRECT_URI", "https://example.test/api/gmail-mail/callback")
    monkeypatch.setattr(api.settings, "MS_MAIL_SIGNING_KEY", "test-signing-material-at-least-32-bytes")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/microsoft-mail")
    app.include_router(api.gmail_router, prefix="/api/gmail-mail")
    user = SimpleNamespace(id=uuid4(), role=UserRole.ADMIN, is_active=True)
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_db] = lambda: SimpleNamespace(get=lambda *_: None)
    client = TestClient(app, base_url="https://example.test")

    response = client.post("/api/microsoft-mail/authorize-url?source=px-eu")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Path=/api/gmail-mail/callback" in cookie
    assert all(attribute in cookie for attribute in ("HttpOnly", "Secure"))
    url = urlsplit(response.json()["url"])
    params = parse_qs(url.query)
    assert url.hostname == "accounts.google.com"
    assert params["scope"] == [gmail_mail.SCOPE]
    assert params["access_type"] == ["offline"]
    assert params["login_hint"] == ["primex.eu@gmail.com"]
    assert params["code_challenge_method"] == ["S256"]
    assert "gmail-secret" not in url.geturl()
    state = {"state": params["state"][0]}
    assert client.get("/api/microsoft-mail/callback", params=state).status_code == 400
    assert TestClient(app, base_url="https://example.test").get("/api/gmail-mail/callback", params=state).status_code == 400


def test_gmail_validates_address_and_reads_only_the_report_days_inbox():
    day = date(2026, 11, 23)
    tz = ZoneInfo("Europe/Tirane")
    midnight = int(datetime.combine(day, datetime.min.time(), tz).timestamp())

    def respond(request):
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer sample"
        path = request.url.path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "primexeu@gmail.com"})
        if path.endswith("/messages"):
            assert request.url.params["labelIds"] == "INBOX"
            assert f"after:{midnight - 1} " in request.url.params["q"]
            if request.url.params.get("pageToken"):
                return httpx.Response(200, json={"messages": [{"id": "one"}, {"id": "archived"}, {"id": "old"}]})
            return httpx.Response(200, json={"messages": [{"id": "one"}], "nextPageToken": "page-two"})
        if path.endswith("/attachments/text-part"):
            return httpx.Response(200, json={"data": "TWVzc2FnZSBib2R5"})
        return httpx.Response(200, json={
            "internalDate": str(midnight * 1000 - int(path.endswith("/old"))),
            "threadId": "thread-1",
            "labelIds": [] if path.endswith("/archived") else ["INBOX"],
            "payload": {
                "mimeType": "text/plain", "body": {"attachmentId": "text-part"},
                "headers": [{"name": "Subject", "value": "Hello"}, {"name": "From", "value": "sender@example.test"}],
            },
        })

    async def read():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await gmail_mail.validate_mailbox(client, "sample", gmail_mail.mailbox_for_px_eu())
            with pytest.raises(ValueError):
                await gmail_mail.validate_mailbox(client, "sample", api._mailbox("info-px"))
            return await gmail_mail.read_inbox(client, "sample", day, tz)

    assert asyncio.run(read()) == [{
        "id": "one", "subject": "Hello", "sender": "sender@example.test", "received_at": "00:00",
        "received_datetime": "2026-11-23T00:00:00+01:00", "body": "Message body",
        "original_email_url": "https://mail.google.com/mail/?authuser=primex.eu%40gmail.com#all/thread-1",
    }]
