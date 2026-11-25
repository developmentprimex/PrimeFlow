"""Authorize and read company inboxes with read-only provider permissions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
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
from app.integrations import gmail_mail, microsoft_mail as graph
from app.models.enums import UserRole
from app.models.morning_report_draft import MorningReportDraft
from app.models.microsoft_mail_token import MicrosoftMailToken
from app.models.user import User
from app.services.discord_ga_replies import _report_window, m1_report_cutoff
from app.services.info_px_notes import save_mailbox_notes
from app.services.report_inboxes import (
    MailSource,
    OAuthMailSource,
    _cipher as _cipher,
    _configured,
    _derive_key,
    _mailbox,
    _token_fields,
    read_report_inbox,
    report_inbox_statuses,
    report_mailbox,
)


router = APIRouter()
gmail_router = APIRouter()
_CALLBACK_PATH = "/api/microsoft-mail/callback"
_GMAIL_CALLBACK_PATH = "/api/gmail-mail/callback"


def _cookie_name(source: OAuthMailSource) -> str:
    return f"primeflow_{source.replace('-', '_')}_oauth"


def _verifier(nonce: str) -> str:
    return _derive_key("pkce:" + nonce).decode().rstrip("=")


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


@router.get("/status")
async def mailbox_status(
    response: Response, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return await report_inbox_statuses(db)


@router.post("/sync")
async def messages(
    report_date: date, response: Response, source: MailSource = "info-px", _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db), m1_draft_id: uuid.UUID | None = None,
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    mailbox = report_mailbox(source)
    if m1_draft_id is not None:
        draft = await db.get(MorningReportDraft, m1_draft_id)
        if draft is None or draft.report_date != report_date:
            raise HTTPException(status_code=404, detail="M1 draft not found")
        cutoff = m1_report_cutoff(draft.generated_snapshot, draft.sent_at if draft.status == "SENT" else None)
        payload = await read_report_inbox(db, source, report_date, window=_report_window(report_date, "M1", cutoff))
    else:
        payload = await read_report_inbox(db, source, report_date)
    if not payload["connected"] or payload.get("error"):
        return payload
    try:
        if not await save_mailbox_notes(db, payload["messages"], mailbox):
            payload["notes_error"] = "Email-et u lexuan, por disa përmbledhje për PX Notes nuk u krijuan. Provo përsëri me Rifresko."
    except SQLAlchemyError:
        await db.rollback()
        payload["notes_error"] = "Email-et u lexuan, por shënimet nuk u ruajtën në PX Notes."
    return payload
