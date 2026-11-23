"""Authorize and display the INFO PX Inbox without writing to it."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

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
from app.integrations import microsoft_mail as graph
from app.models.enums import UserRole
from app.models.microsoft_mail_token import MicrosoftMailToken
from app.models.user import User
from app.services.info_px_notes import save_info_px_notes
from app.services.primeflow_report import report_timezone


router = APIRouter()
_COOKIE = "primeflow_info_px_oauth"
_CALLBACK_PATH = "/api/microsoft-mail/callback"
_TOKEN_ID = 1


def _configured() -> bool:
    return all((settings.MS_MAIL_CLIENT_ID, settings.MS_MAIL_CLIENT_SECRET, settings.MS_MAIL_TENANT_ID,
                settings.MS_MAIL_REDIRECT_URI)) and len(settings.MS_MAIL_SIGNING_KEY or "") >= 32


def _derive_key(purpose: str) -> bytes:
    digest = hmac.digest((settings.MS_MAIL_SIGNING_KEY or "").encode(), f"primeflow-info-px:{purpose}".encode(), "sha256")
    return base64.urlsafe_b64encode(digest)


def _verifier(nonce: str) -> str:
    return _derive_key("pkce:" + nonce).decode().rstrip("=")


def _cipher() -> Fernet:
    return Fernet(_derive_key("token-encryption"))


def _token_fields(token: dict) -> dict:
    cipher = _cipher()
    fields = {
        "access_token": cipher.encrypt(token["access_token"].encode()).decode(),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600))),
    }
    if token.get("refresh_token"):
        fields["refresh_token"] = cipher.encrypt(token["refresh_token"].encode()).decode()
    return fields


@router.post("/authorize-url")
async def authorize(response: Response, user: User = Depends(require_admin)) -> dict:
    if not _configured():
        raise HTTPException(503, "INFO PX Outlook is not configured.")
    nonce = secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    state = jwt.encode({
        "type": "ms_mail_oauth", "sub": str(user.id), "nonce": nonce, "exp": int(expiry.timestamp()),
    }, _derive_key("state"), algorithm=ALGORITHM)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        _COOKIE, nonce, max_age=600, httponly=True, samesite="lax", path=_CALLBACK_PATH,
        secure=(settings.MS_MAIL_REDIRECT_URI or "").startswith("https://"),
    )
    return {"url": graph.authorization_url(state, _verifier(nonce))}


@router.get("/callback")
async def callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not _configured():
        raise HTTPException(503, "INFO PX Outlook is not configured.")
    try:
        claims = jwt.decode(state or "", _derive_key("state"), algorithms=[ALGORITHM])
        nonce = claims["nonce"]
        user_id = uuid.UUID(claims["sub"])
        if claims.get("type") != "ms_mail_oauth" or not secrets.compare_digest(nonce, request.cookies.get(_COOKIE, "")):
            raise ValueError
    except (JWTError, KeyError, ValueError, TypeError):
        raise HTTPException(400, "Invalid Microsoft mail authorization.") from None

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Only a PrimeFlow administrator can connect INFO PX Outlook.")
    result = "error"
    if code and not error:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                token = await graph.request_token(client, {
                    "grant_type": "authorization_code", "code": code, "code_verifier": _verifier(nonce),
                })
                await graph.validate_mailbox(client, token["access_token"])
            fields = _token_fields(token)
            if "refresh_token" not in fields:
                raise ValueError("Microsoft did not grant offline access.")
            statement = insert(MicrosoftMailToken).values(id=_TOKEN_ID, **fields)
            await db.execute(statement.on_conflict_do_update(index_elements=["id"], set_=fields))
            await db.commit()
        except (httpx.HTTPError, KeyError, ValueError):
            await db.rollback()
        else:
            result = "connected"
    response = RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/morning-report?outlook_mail={result}",
        status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.delete_cookie(_COOKIE, path=_CALLBACK_PATH)
    return response


async def _access_token(db: AsyncSession, client: httpx.AsyncClient, row: MicrosoftMailToken) -> str:
    refresh_by = datetime.now(timezone.utc) + timedelta(seconds=45)
    if row.expires_at <= refresh_by:
        await db.refresh(row, with_for_update=True)
        if row.expires_at <= refresh_by:
            token = await graph.request_token(client, {
                "grant_type": "refresh_token",
                "refresh_token": _cipher().decrypt(row.refresh_token.encode()).decode(),
            })
            for field, value in _token_fields(token).items():
                setattr(row, field, value)
        access_token = row.access_token
        await db.commit()
    else:
        access_token = row.access_token
    return _cipher().decrypt(access_token.encode()).decode()


@router.post("/sync")
async def messages(
    report_date: date, response: Response, _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    payload = {"configured": _configured(), "connected": False, "messages": []}
    if not payload["configured"]:
        return payload
    row = await db.get(MicrosoftMailToken, _TOKEN_ID)
    if row is None:
        return payload
    payload["connected"] = True
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            access_token = await _access_token(db, client, row)
            outlook_messages = await graph.read_inbox(
                client, access_token, report_date, report_timezone(),
            )
        payload["messages"] = outlook_messages
        await save_info_px_notes(db, outlook_messages)
    except SQLAlchemyError:
        await db.rollback()
        payload["notes_error"] = "Email-et u lexuan, por shënimet nuk u ruajtën në PX Notes."
    except (httpx.HTTPError, InvalidToken, KeyError, ValueError):
        await db.rollback()
        payload["error"] = "Email-et e INFO PX nuk mund të lexohen."
    return payload
