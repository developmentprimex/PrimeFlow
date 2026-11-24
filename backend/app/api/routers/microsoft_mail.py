"""Authorize and read company inboxes with read-only provider permissions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from imaplib import IMAP4
from typing import Literal

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.auth.security import ALGORITHM
from app.config import settings
from app.db import get_db
from app.integrations import gmail_mail, homeface_mail, microsoft_mail as graph
from app.models.enums import UserRole
from app.models.microsoft_mail_token import MicrosoftMailToken
from app.models.user import User
from app.services.info_px_notes import save_mailbox_notes
from app.services.primeflow_report import report_timezone


router = APIRouter()
gmail_router = APIRouter()
_CALLBACK_PATH = "/api/microsoft-mail/callback"
_GMAIL_CALLBACK_PATH = "/api/gmail-mail/callback"
OAuthMailSource = Literal["info-px", "it", "px-eu"]
MailSource = Literal["info-px", "it", "px-eu", "hf"]


def _cookie_name(source: OAuthMailSource) -> str:
    return f"primeflow_{source.replace('-', '_')}_oauth"


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


def _verifier(nonce: str) -> str:
    return _derive_key("pkce:" + nonce).decode().rstrip("=")


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


@router.post("/authorize-url")
async def authorize(response: Response, source: OAuthMailSource = "info-px", user: User = Depends(require_admin)) -> dict:
    mailbox = _mailbox(source)
    is_gmail = source == "px-eu"
    provider = gmail_mail if is_gmail else graph
    redirect_uri = settings.GMAIL_PX_EU_REDIRECT_URI if is_gmail else settings.MS_MAIL_REDIRECT_URI
    if not _configured(mailbox):
        raise HTTPException(503, "Mailbox is not configured.")
    nonce = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    state = jwt.encode({
        "type": "ms_mail_oauth", "sub": str(user.id), "nonce": nonce, "source": source, "exp": int(expiry.timestamp()),
    }, _derive_key("state"), algorithm=ALGORITHM)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        _cookie_name(source), nonce, max_age=600, httponly=True, samesite="lax",
        path=_GMAIL_CALLBACK_PATH if is_gmail else _CALLBACK_PATH,
        secure=(redirect_uri or "").startswith("https://"),
    )
    return {"url": provider.authorization_url(state, _verifier(nonce), mailbox)}


@router.get("/callback")
async def callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _finish_authorization(request, code, state, error, db, False)


@gmail_router.get("/callback")
async def gmail_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    return await _finish_authorization(request, code, state, error, db, True)


async def _finish_authorization(
    request: Request, code: str | None, state: str | None, error: str | None, db: AsyncSession, is_gmail: bool,
) -> RedirectResponse:
    provider = gmail_mail if is_gmail else graph
    valid_sources = ("px-eu",) if is_gmail else ("info-px", "it")
    try:
        claims = jwt.decode(state or "", _derive_key("state"), algorithms=[ALGORITHM])
        nonce = claims["nonce"]
        user_id = uuid.UUID(claims["sub"])
        source = claims.get("source", "info-px")
        if (claims.get("type") != "ms_mail_oauth" or source not in valid_sources
                or not secrets.compare_digest(nonce, request.cookies.get(_cookie_name(source), ""))):
            raise ValueError
    except (JWTError, KeyError, ValueError, TypeError):
        raise HTTPException(400, "Invalid mail authorization.") from None

    mailbox = _mailbox(source)
    if not _configured(mailbox):
        raise HTTPException(503, "Mailbox is not configured.")
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Only a PrimeFlow administrator can connect a mailbox.")
    result = "error"
    if code and not error:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                token = await provider.request_token(client, {
                    "grant_type": "authorization_code", "code": code, "code_verifier": _verifier(nonce),
                }, mailbox)
                await provider.validate_mailbox(client, token["access_token"], mailbox)
            fields = _token_fields(token, mailbox)
            if "refresh_token" not in fields:
                raise ValueError("The mailbox provider did not grant offline access.")
            statement = insert(MicrosoftMailToken).values(id=mailbox.token_id, **fields)
            await db.execute(statement.on_conflict_do_update(index_elements=["id"], set_=fields))
            await db.commit()
        except (httpx.HTTPError, KeyError, ValueError):
            await db.rollback()
        else:
            result = "connected"
    response = RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/morning-report?outlook_mail={result}&outlook_source={source}",
        status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.delete_cookie(_cookie_name(source), path=_GMAIL_CALLBACK_PATH if is_gmail else _CALLBACK_PATH)
    return response


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


@router.post("/sync")
async def messages(
    report_date: date, response: Response, source: MailSource = "info-px", _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    app_password = settings.HOMEFACE_MAIL_APP_PASSWORD
    mailbox = homeface_mail.MAILBOX if source == "hf" else _mailbox(source)
    provider = gmail_mail if source == "px-eu" else graph
    configured = bool(app_password) if source == "hf" else _configured(mailbox)
    payload = {"configured": configured, "connected": False, "messages": []}
    if not payload["configured"]:
        return payload
    try:
        if source == "hf":
            assert app_password is not None
            inbox_messages = await asyncio.to_thread(
                homeface_mail.read_inbox, app_password.get_secret_value(), report_date, report_timezone(),
            )
            payload["connected"] = True
        else:
            row = await db.get(MicrosoftMailToken, mailbox.token_id)
            if row is None:
                return payload
            payload["connected"] = True
            async with httpx.AsyncClient(timeout=12) as client:
                access_token = await _access_token(db, client, row, mailbox)
                inbox_messages = await provider.read_inbox(
                    client, access_token, report_date, report_timezone(),
                )
        payload["messages"] = inbox_messages
        await save_mailbox_notes(db, inbox_messages, mailbox)
    except SQLAlchemyError:
        await db.rollback()
        payload["notes_error"] = "Email-et u lexuan, por shënimet nuk u ruajtën në PX Notes."
    except (httpx.HTTPError, IMAP4.error, InvalidToken, KeyError, OSError, ValueError):
        await db.rollback()
        payload["error"] = f"Email-et e {mailbox.label} nuk mund të lexohen."
    return payload
