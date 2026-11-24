"""Read the company inboxes using their existing read-only connections."""

from __future__ import annotations

import asyncio
import base64
import hmac
from datetime import date, datetime, timedelta, timezone
from imaplib import IMAP4
from typing import Literal

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations import gmail_mail, homeface_mail, microsoft_mail as graph
from app.models.microsoft_mail_token import MicrosoftMailToken
from app.services.primeflow_report import report_timezone

OAuthMailSource = Literal["info-px", "it", "px-eu"]
MailSource = Literal["info-px", "it", "px-eu", "hf"]
REPORT_INBOX_SOURCES: tuple[MailSource, ...] = ("info-px", "it", "hf", "px-eu")


def _mailbox(source: OAuthMailSource) -> graph.Mailbox:
    return gmail_mail.mailbox_for_px_eu() if source == "px-eu" else graph.mailbox_for(source)


def _configured(mailbox: graph.Mailbox) -> bool:
    provider_config = settings.GMAIL_PX_EU_REDIRECT_URI if mailbox.note_origin == gmail_mail.PX_EU_NOTE_ORIGIN else (
        mailbox.tenant_id and settings.MS_MAIL_REDIRECT_URI
    )
    return all((mailbox.client_id, mailbox.client_secret, provider_config)) and len(settings.MS_MAIL_SIGNING_KEY or "") >= 32


def _derive_key(purpose: str) -> bytes:
    digest = hmac.digest((settings.MS_MAIL_SIGNING_KEY or "").encode(), f"primeflow-info-px:{purpose}".encode(), "sha256")
    return base64.urlsafe_b64encode(digest)


def _cipher(mailbox: graph.Mailbox) -> Fernet:
    purpose = "token-encryption" if mailbox.token_id == 1 else f"token-encryption:{mailbox.token_id}"
    return Fernet(_derive_key(purpose))


def _token_fields(token: dict, mailbox: graph.Mailbox) -> dict:
    cipher = _cipher(mailbox)
    fields = {
        "access_token": cipher.encrypt(token["access_token"].encode()).decode(),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600))),
    }
    if token.get("refresh_token"):
        fields["refresh_token"] = cipher.encrypt(token["refresh_token"].encode()).decode()
    return fields


async def _access_token(db: AsyncSession, client: httpx.AsyncClient, row: MicrosoftMailToken, mailbox: graph.Mailbox) -> str:
    refresh_by = datetime.now(timezone.utc) + timedelta(seconds=45)
    if row.expires_at <= refresh_by:
        await db.refresh(row, with_for_update=True)
        if row.expires_at <= refresh_by:
            provider = gmail_mail if mailbox.note_origin == gmail_mail.PX_EU_NOTE_ORIGIN else graph
            token = await provider.request_token(client, {
                "grant_type": "refresh_token",
                "refresh_token": _cipher(mailbox).decrypt(row.refresh_token.encode()).decode(),
            }, mailbox)
            for field, value in _token_fields(token, mailbox).items():
                setattr(row, field, value)
        access_token = row.access_token
        await db.commit()
    else:
        access_token = row.access_token
    return _cipher(mailbox).decrypt(access_token.encode()).decode()


def report_mailbox(source: MailSource) -> graph.Mailbox:
    return homeface_mail.MAILBOX if source == "hf" else _mailbox(source)


def _inbox_configured(source: MailSource, mailbox: graph.Mailbox) -> bool:
    return bool(settings.HOMEFACE_MAIL_APP_PASSWORD) if source == "hf" else _configured(mailbox)


async def report_inbox_statuses(db: AsyncSession) -> dict[MailSource, dict[str, bool | None]]:
    statuses = {}
    for source in REPORT_INBOX_SOURCES:
        mailbox = report_mailbox(source)
        configured = _inbox_configured(source, mailbox)
        if not configured:
            connected = False
        elif source == "hf":
            connected = None  # A configured app password is verified when IMAP is read.
        else:
            connected = await db.get(MicrosoftMailToken, mailbox.token_id) is not None
        statuses[source] = {"configured": configured, "connected": connected}
    return statuses


async def read_report_inbox(
    db: AsyncSession, source: MailSource, report_day: date, *,
    window: tuple[datetime, datetime] | None = None,
) -> dict:
    app_password = settings.HOMEFACE_MAIL_APP_PASSWORD
    mailbox = report_mailbox(source)
    provider = gmail_mail if source == "px-eu" else graph
    configured = _inbox_configured(source, mailbox)
    payload = {"configured": configured, "connected": False, "messages": []}
    if not configured:
        return payload
    read_options = {"window": window} if window is not None else {}
    try:
        if source == "hf":
            assert app_password is not None
            payload["messages"] = await asyncio.to_thread(
                homeface_mail.read_inbox, app_password.get_secret_value(), report_day, report_timezone(), **read_options,
            )
            payload["connected"] = True
        else:
            row = await db.get(MicrosoftMailToken, mailbox.token_id)
            if row is None:
                return payload
            payload["connected"] = True
            async with httpx.AsyncClient(timeout=12) as client:
                access_token = await _access_token(db, client, row, mailbox)
                payload["messages"] = await provider.read_inbox(
                    client, access_token, report_day, report_timezone(), **read_options,
                )
    except (SQLAlchemyError, httpx.HTTPError, IMAP4.error, InvalidToken, KeyError, OSError, ValueError):
        await db.rollback()
        payload["error"] = f"Email-et e {mailbox.label} nuk mund të lexohen."
    return payload
