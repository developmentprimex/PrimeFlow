import asyncio
import json
import uuid
from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from cryptography.fernet import InvalidToken
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import dialect

from app.api.routers import microsoft_mail as api
from app.integrations import gmail_mail, homeface_mail
from app.integrations import microsoft_mail as mail
from app.models.enums import UserRole
from app.services import info_px_notes


def test_authorize_requests_read_only_permissions(monkeypatch):
    monkeypatch.setattr(mail.settings, "MS_MAIL_CLIENT_ID", "pilot")
    monkeypatch.setattr(mail.settings, "MS_MAIL_TENANT_ID", "tenant")
    monkeypatch.setattr(mail.settings, "MS_MAIL_REDIRECT_URI", "https://example.com/api/microsoft-mail/callback")
    url = mail.authorization_url("signed-state", "private-verifier", mail.mailbox_for("info-px"))
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
    monkeypatch.setattr(api, "_configured", lambda mailbox: False)
    endpoint = "/api/microsoft-mail/sync?report_date=2026-11-23"
    client = TestClient(app)
    assert client.post(endpoint).status_code == 401

    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF, is_active=True)
    app.dependency_overrides[api.get_current_user] = lambda: user
    response = client.post(endpoint)
    assert response.json() == {"configured": False, "connected": False, "messages": []}
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/microsoft-mail/authorize-url").status_code == 403


def test_px_note_formats_each_mailbox_and_skips_already_imported_messages(monkeypatch):
    db = AsyncMock()
    message = {
        "id": "immutable-id", "subject": "Kërkesë", "sender": "Drita <drita@example.test>",
        "received_datetime": "2026-11-23T10:50:00+01:00", "body": "Rreshti 1\nRreshti 2",
    }
    draft = AsyncMock(return_value=info_px_notes.MailboxNoteDraft(
        client_or_project="Puris – Home24",
        summary="Klienti kërkon automatizim.",
        steps=["Analizo dokumentet.", "Përgatit mapping."],
    ))
    monkeypatch.setattr(info_px_notes, "_draft_note", draft)
    db.execute.return_value = SimpleNamespace(all=lambda: [])
    mailboxes = [mail.mailbox_for("info-px"), mail.mailbox_for("it"), homeface_mail.MAILBOX, gmail_mail.mailbox_for_px_eu()]
    for mailbox in mailboxes:
        assert asyncio.run(info_px_notes.save_mailbox_notes(db, [message, message], mailbox))

    inserted = [
        call.args[0].compile(dialect=dialect()) for call in db.execute.await_args_list if call.args[0].is_insert
    ]
    assert len({statement.params["id_m0"] for statement in inserted}) == 4
    for mailbox, statement in zip(mailboxes, inserted):
        assert statement.params["content_m0"] == (
            f"{mailbox.label}: 08:00 PURIS – HOME24\n"
            "Klienti kërkon automatizim.\n1) Analizo dokumentet.\n2) Përgatit mapping."
        )
        assert statement.params["knowledge_type_m0"] == mailbox.note_origin
        assert statement.params["email_metadata_m0"] == {"subject": "Kërkesë", "sender": message["sender"]}
        assert statement.params["email_body_m0"] == message["body"]
        assert "ON CONFLICT (id) DO NOTHING" in str(statement)

    db.execute.return_value = SimpleNamespace(all=lambda: [(inserted[0].params["id_m0"], {"subject": "Kërkesë"})])
    assert asyncio.run(info_px_notes.save_mailbox_notes(db, [message], mailboxes[0]))
    assert db.execute.await_count == 9
    assert draft.await_count == 4


def test_failed_mail_summary_stays_available_for_retry(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [])
    inbox = [
        {"id": "bad", "subject": "Unprocessed", "received_datetime": "2026-11-23T10:50:00+01:00", "body": "Text"},
        {"id": "ok", "subject": "Informative", "sender": "sender@example.test", "received_datetime": "2026-11-23T10:51:00+01:00", "body": "Text"},
    ]

    async def draft(_, subject, __):
        if subject == "Unprocessed":
            raise ValueError("formatting failed")
        return info_px_notes.MailboxNoteDraft(client_or_project=None, summary=subject, steps=[])

    monkeypatch.setattr(info_px_notes, "_draft_note", draft)
    assert not asyncio.run(info_px_notes.save_mailbox_notes(db, inbox, mail.mailbox_for("info-px")))
    statement = db.execute.await_args.args[0].compile(dialect=dialect())
    assert statement.params["content_m0"] == "EM INFO PX: 08:00 INFORMATIVE\nInformative"
    assert "content_m1" not in statement.params


def test_mail_summary_requests_structured_output_without_storing_the_response(monkeypatch):
    monkeypatch.setattr(info_px_notes.settings, "OPENAI_API_KEY", "test-key")

    def respond(request):
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert json.loads(payload["input"]) == {"subject": "Kërkesë", "body": "Përgatit një template."}
        assert payload["text"]["format"]["strict"] is True
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "client_or_project": None, "summary": "Kërkohet një template.", "steps": ["Përgatit template-in."],
            })}]}],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await info_px_notes._draft_note(client, "Kërkesë", "Përgatit një template.")

    assert asyncio.run(run()).steps == ["Përgatit template-in."]


def test_authorization_state_is_browser_bound_and_tokens_are_encrypted(monkeypatch):
    monkeypatch.setattr(api.settings, "MS_MAIL_SIGNING_KEY", "test-signing-material-at-least-32-bytes")
    monkeypatch.setattr(api.settings, "MS_MAIL_REDIRECT_URI", "https://example.test/api/microsoft-mail/callback")
    monkeypatch.setattr(api, "_configured", lambda mailbox: True)
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

    mailbox = mail.mailbox_for("info-px")
    fields = api._token_fields({"access_token": "access-example", "refresh_token": "refresh-example"}, mailbox)
    for field, value in (("access_token", "access-example"), ("refresh_token", "refresh-example")):
        assert fields[field] != value
        assert api._cipher(mailbox).decrypt(fields[field].encode()).decode() == value


def test_it_authorization_uses_its_own_application_and_storage(monkeypatch):
    monkeypatch.setattr(mail.settings, "MS_MAIL_IT_CLIENT_ID", "it-client")
    monkeypatch.setattr(mail.settings, "MS_MAIL_IT_TENANT_ID", "it-tenant")
    monkeypatch.setattr(mail.settings, "MS_MAIL_IT_CLIENT_SECRET", "it-test-secret")
    monkeypatch.setattr(mail.settings, "MS_MAIL_REDIRECT_URI", "https://example.test/api/microsoft-mail/callback")
    monkeypatch.setattr(mail.settings, "MS_MAIL_SIGNING_KEY", "test-signing-material-at-least-32-bytes")
    it = mail.mailbox_for("it")
    info = mail.mailbox_for("info-px")
    url = urlsplit(mail.authorization_url("signed-state", "private-verifier", it))
    params = parse_qs(url.query)
    assert url.path == "/it-tenant/oauth2/v2.0/authorize"
    assert params["client_id"] == ["it-client"]
    assert params["login_hint"] == ["it@forestdream.de"]
    assert "it-test-secret" not in url.geturl()
    assert it.token_id != info.token_id
    assert api._cookie_name("it") != api._cookie_name("info-px")
    it_token = api._cipher(it).encrypt(b"it-token")
    with pytest.raises(InvalidToken):
        api._cipher(info).decrypt(it_token)
