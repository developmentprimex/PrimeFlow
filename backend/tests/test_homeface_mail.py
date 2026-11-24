import asyncio
from datetime import date
from imaplib import IMAP4
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from fastapi import Response
from pydantic import SecretStr

from app.api.routers import microsoft_mail
from app.integrations import homeface_mail


def test_homeface_reads_only_messages_for_the_report_day_without_marking_seen(monkeypatch):
    connection = MagicMock()
    inbox = connection.__enter__.return_value
    inbox.select.return_value = ("OK", [b"2"])
    inbox.response.return_value = ("UIDVALIDITY", [b"42"])
    inbox.uid.side_effect = [
        ("OK", [b"10 11"]),
        ("OK", [b'1 (INTERNALDATE "23-Nov-2026 23:30:00 +0000")']),
        ("OK", [
            (b"1 (BODY[] {100}", b"Subject: Test\r\nFrom: Test <test@example.com>\r\n"
             b"Content-Type: text/html\r\n\r\n<style>hidden</style><p>Body</p>"),
            b")",
        ]),
        ("OK", [b'2 (INTERNALDATE "24-Nov-2026 23:30:00 +0000")']),
    ]
    monkeypatch.setattr(homeface_mail, "IMAP4_SSL", lambda *args, **kwargs: connection)

    messages = homeface_mail.read_inbox("app-password", date(2026, 11, 24), ZoneInfo("Europe/Budapest"))

    inbox.login.assert_called_once_with("info@homeface.de", "app-password")
    inbox.select.assert_called_once_with("INBOX", readonly=True)
    assert inbox.uid.call_args_list[2].args == ("FETCH", b"10", "(BODY.PEEK[])")
    assert len(messages) == 1
    assert messages[0] == {
        "id": "42:10",
        "subject": "Test",
        "sender": "Test <test@example.com>",
        "received_at": "00:30",
        "received_datetime": "2026-11-24T00:30:00+01:00",
        "body": "Body",
    }


def test_homeface_sync_imports_to_px_notes(monkeypatch):
    monkeypatch.setattr(microsoft_mail.settings, "HOMEFACE_MAIL_APP_PASSWORD", SecretStr("app-password"))
    inbox_messages = [{"id": "42:10"}]
    monkeypatch.setattr(homeface_mail, "read_inbox", lambda *_: inbox_messages)
    save_notes = AsyncMock()
    monkeypatch.setattr(microsoft_mail, "save_mailbox_notes", save_notes)
    db = AsyncMock()

    result = asyncio.run(microsoft_mail.messages(date(2026, 11, 24), Response(), "hf", None, db))

    assert result == {"configured": True, "connected": True, "messages": inbox_messages}
    save_notes.assert_awaited_once_with(db, inbox_messages, homeface_mail.MAILBOX)
    db.get.assert_not_awaited()


def test_homeface_does_not_report_connected_when_yandex_rejects_login(monkeypatch):
    monkeypatch.setattr(microsoft_mail.settings, "HOMEFACE_MAIL_APP_PASSWORD", SecretStr("app-password"))
    monkeypatch.setattr(homeface_mail, "read_inbox", MagicMock(side_effect=IMAP4.error("Login refused")))
    save_notes = AsyncMock()
    monkeypatch.setattr(microsoft_mail, "save_mailbox_notes", save_notes)

    result = asyncio.run(microsoft_mail.messages(date(2026, 11, 24), Response(), "hf", None, AsyncMock()))

    assert result["configured"]
    assert not result["connected"]
    assert "EM HF" in result["error"]
    save_notes.assert_not_awaited()
