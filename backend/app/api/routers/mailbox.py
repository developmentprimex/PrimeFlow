from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.security import ALGORITHM
from app.config import settings
from app.db import get_db
from app.integrations.microsoft import compute_expires_at, fetch_user_profile, microsoft_account_email
from app.integrations.microsoft_mail import (
    MAIL_SCOPES, build_mail_authorize_url, decrypt_token, encrypt_token,
    fetch_mail_preview, fetch_mailbox_type, has_mail_permissions, mail_token_request, token_storage_ready,
)
from app.models.enums import UserRole
from app.models.mailbox_connection import MailboxConnection
from app.models.user import User

router = APIRouter()
STATE_COOKIE = "primeflow_mailbox_oauth"


def require_mail_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Vetëm administratori mund të lidhë ose lexojë email-in.")
    return user


def configured() -> bool:
    return bool(settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET and settings.MS_TENANT_ID)


def redirect_uri(request: Request) -> str:
    return settings.MS_MAIL_REDIRECT_URI or f"{str(request.base_url).rstrip('/')}/api/mailbox/callback"


def mailbox_email() -> str:
    return settings.MS_MAILBOX_EMAIL.strip().casefold()


def callback_response(result: str) -> RedirectResponse:
    destination = f"{settings.FRONTEND_URL.rstrip('/')}/admin/email?{urlencode({'mailbox': result})}"
    response = RedirectResponse(destination, status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/status")
async def connection_status(
    request: Request, response: Response,
    user: User = Depends(require_mail_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(MailboxConnection, mailbox_email())
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "configured": configured(), "authorized": row is not None,
        "connected": bool(row and row.last_checked_at),
        "encryption_ready": token_storage_ready(),
        "mailbox_email": mailbox_email(), "redirect_uri": redirect_uri(request),
        "requested_scopes": list(MAIL_SCOPES),
        "has_read_permissions": bool(row and has_mail_permissions(row.scope)),
        "connected_at": row.connected_at if row else None,
        "last_checked_at": row.last_checked_at if row else None,
        "mailbox_type": row.mailbox_type if row else None,
    }


@router.post("/authorize-url")
async def authorize_mailbox(
    request: Request, response: Response, user: User = Depends(require_mail_admin),
) -> dict:
    if not configured():
        raise HTTPException(503, "Konfiguro MS_CLIENT_ID, MS_CLIENT_SECRET dhe MS_TENANT_ID në server.")
    if not token_storage_ready():
        raise HTTPException(503, "Administratori duhet të përgatisë çelësin e enkriptimit të email-it në server.")
    now = datetime.now(timezone.utc)
    state = jwt.encode({
        "type": "mailbox_oauth", "sub": str(user.id), "mailbox": mailbox_email(),
        "nonce": secrets.token_urlsafe(32), "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }, settings.JWT_SECRET, algorithm=ALGORITHM)
    response.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True,
        secure=redirect_uri(request).startswith("https://"), samesite="lax", path="/",
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {"url": build_mail_authorize_url(redirect_uri(request), state)}


@router.get("/callback")
async def mailbox_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    cookie = request.cookies.get(STATE_COOKIE)
    if not state or not cookie or not secrets.compare_digest(state, cookie):
        return callback_response("invalid_state")
    try:
        payload = jwt.decode(state, settings.JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("type") != "mailbox_oauth" or payload.get("mailbox") != mailbox_email():
            return callback_response("invalid_state")
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        return callback_response("invalid_state")
    if error or not code:
        return callback_response("denied")
    if not token_storage_ready():
        return callback_response("encryption_not_ready")
    user = await db.get(User, user_id)
    if user is None or user.role != UserRole.ADMIN or not user.is_active:
        return callback_response("denied")
    try:
        token_data = await mail_token_request(redirect_uri(request), code=code)
        if not token_data.get("access_token") or not token_data.get("refresh_token"):
            return callback_response("missing_permissions")
        if not has_mail_permissions(token_data.get("scope", "")):
            return callback_response("missing_permissions")
        profile = await fetch_user_profile(token_data["access_token"])
        if microsoft_account_email(profile) != mailbox_email():
            return callback_response("wrong_account")
        mailbox_type = await fetch_mailbox_type(token_data["access_token"])
        if mailbox_type != "user":
            # Shared mailboxes must use an explicitly designed shared-access flow.
            return callback_response("unsupported_mailbox_type")
    except httpx.HTTPError:
        return callback_response("microsoft_error")
    row = await db.get(MailboxConnection, mailbox_email())
    if row is None:
        row = MailboxConnection(mailbox_email=mailbox_email())
        db.add(row)
    row.connected_by = user_id
    row.mailbox_type = mailbox_type
    row.access_token_encrypted = encrypt_token(token_data["access_token"])
    row.refresh_token_encrypted = encrypt_token(token_data["refresh_token"])
    row.scope = token_data["scope"]
    row.expires_at = compute_expires_at(int(token_data.get("expires_in", 3600)))
    row.connected_at = datetime.now(timezone.utc)
    row.last_checked_at = None
    await db.commit()
    return callback_response("authorized")


async def refresh_mailbox(db: AsyncSession, row: MailboxConnection, callback_uri: str) -> None:
    try:
        data = await mail_token_request(callback_uri, refresh_token=decrypt_token(row.refresh_token_encrypted))
    except InvalidToken as exc:
        raise HTTPException(409, "Lidhe sërish email-in; çelësi i serverit ka ndryshuar.") from exc
    scope = data.get("scope", row.scope)
    if not has_mail_permissions(scope):
        raise HTTPException(409, "Lidhe sërish email-in për të miratuar lejet e leximit.")
    row.access_token_encrypted = encrypt_token(data["access_token"])
    if data.get("refresh_token"):
        row.refresh_token_encrypted = encrypt_token(data["refresh_token"])
    row.scope = scope
    row.expires_at = compute_expires_at(int(data.get("expires_in", 3600)))
    # Persist rotating refresh tokens even if the subsequent preview request fails.
    await db.commit()


@router.post("/test")
async def test_connection(
    request: Request, response: Response,
    user: User = Depends(require_mail_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    if not token_storage_ready():
        raise HTTPException(503, "Çelësi i enkriptimit të email-it mungon ose nuk është i vlefshëm në server.")
    row = (await db.execute(select(MailboxConnection).where(
        MailboxConnection.mailbox_email == mailbox_email()
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(409, "Lidhe fillimisht email-in me Microsoft.")
    if not has_mail_permissions(row.scope):
        raise HTTPException(409, "Lidhe sërish email-in për të miratuar lejet e leximit.")
    try:
        if row.expires_at <= datetime.now(timezone.utc) + timedelta(seconds=30):
            await refresh_mailbox(db, row, redirect_uri(request))
        try:
            preview = await fetch_mail_preview(decrypt_token(row.access_token_encrypted))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            await refresh_mailbox(db, row, redirect_uri(request))
            preview = await fetch_mail_preview(decrypt_token(row.access_token_encrypted))
    except InvalidToken as exc:
        raise HTTPException(409, "Lidhe sërish email-in; çelësi i serverit ka ndryshuar.") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403):
            raise HTTPException(409, "Microsoft nuk lejoi leximin. Lidhe sërish email-in ose kontrollo lejet në Microsoft 365.") from exc
        raise HTTPException(502, "Microsoft nuk e përfundoi provën. Provo përsëri pak më vonë.") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(502, "Nuk u përfundua lidhja me Microsoft. Provo përsëri.") from exc
    row.last_checked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"mailbox_email": mailbox_email(), "checked_at": row.last_checked_at, **preview}


@router.delete("/connection")
async def disconnect_mailbox(
    response: Response, user: User = Depends(require_mail_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(delete(MailboxConnection).where(MailboxConnection.mailbox_email == mailbox_email()))
    await db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return {"connected": False}
