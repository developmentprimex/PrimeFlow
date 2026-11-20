from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.security import ALGORITHM
from app.config import settings
from app.db import get_db
from app.integrations.microsoft import (
    build_authorize_url,
    compute_expires_at,
    exchange_code_for_token,
    fetch_calendar_events,
    fetch_user_profile,
    microsoft_account_email,
    refresh_access_token,
)
from app.models.enums import UserRole
from app.models.microsoft_token import MicrosoftToken
from app.models.user import User
from app.schemas.microsoft import MicrosoftEvent
from app.services.microsoft_calendar_sync import get_shared_calendar_token


router = APIRouter()


async def fetch_calendar_events_with_retry(
    access_token: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Retry one transient Graph connection failure before reporting it."""
    for attempt in range(2):
        try:
            return await fetch_calendar_events(access_token, start, end)
        except httpx.RequestError:
            if attempt == 1:
                raise
            await asyncio.sleep(0.25)
    return []


def ensure_ms_config() -> None:
    if not settings.MS_CLIENT_ID or not settings.MS_CLIENT_SECRET or not settings.MS_TENANT_ID:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Microsoft integration is not configured.",
        )


def ensure_calendar_admin(user: User) -> None:
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator can connect the shared Microsoft calendar.",
        )


def resolve_redirect_uri(request: Request) -> str:
    if settings.MS_REDIRECT_URI:
        return settings.MS_REDIRECT_URI
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/microsoft/callback"


def create_state_token(user_id: uuid.UUID, redirect_to: str | None) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)
    payload = {
        "type": "ms_oauth",
        "sub": str(user_id),
        "redirect_to": redirect_to,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_state_token(state: str) -> dict:
    try:
        payload = jwt.decode(state, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state token") from exc
    if payload.get("type") != "ms_oauth":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state token")
    return payload


def append_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def upsert_token(db: AsyncSession, user_id: uuid.UUID, token_data: dict) -> MicrosoftToken:
    expires_in = int(token_data.get("expires_in", 3600))
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token or not refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing access token")

    # PrimeFlow uses one shared organizer mailbox. Remove legacy per-user
    # connections so every meeting consistently uses the same calendar.
    await db.execute(delete(MicrosoftToken).where(MicrosoftToken.user_id != user_id))
    row = (await db.execute(select(MicrosoftToken).where(MicrosoftToken.user_id == user_id))).scalar_one_or_none()
    if row is None:
        row = MicrosoftToken(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            scope=token_data.get("scope"),
            expires_at=compute_expires_at(expires_in),
        )
        db.add(row)
    else:
        row.access_token = access_token
        if refresh_token:
            row.refresh_token = refresh_token
        row.scope = token_data.get("scope") or row.scope
        row.expires_at = compute_expires_at(expires_in)

    await db.commit()
    await db.refresh(row)
    return row


async def refresh_token_row(db: AsyncSession, row: MicrosoftToken, redirect_uri: str) -> MicrosoftToken:
    token_data = await refresh_access_token(row.refresh_token, redirect_uri, row.scope)
    expires_in = int(token_data.get("expires_in", 3600))
    row.access_token = token_data["access_token"]
    if token_data.get("refresh_token"):
        row.refresh_token = token_data["refresh_token"]
    row.scope = token_data.get("scope") or row.scope
    row.expires_at = compute_expires_at(expires_in)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/authorize-url")
async def get_authorize_url(
    request: Request,
    redirect_to: str | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    ensure_ms_config()
    ensure_calendar_admin(user)
    state = create_state_token(user.id, redirect_to)
    redirect_uri = resolve_redirect_uri(request)
    url = build_authorize_url(settings.MS_CLIENT_ID, redirect_uri, state)
    return {"url": url}


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    ensure_ms_config()
    if error:
        detail = error_description or error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state")

    payload = decode_state_token(state)
    user_id = uuid.UUID(str(payload.get("sub")))
    redirect_to = payload.get("redirect_to") or settings.FRONTEND_URL
    redirect_uri = resolve_redirect_uri(request)

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ensure_calendar_admin(user)

    token_data = await exchange_code_for_token(code, redirect_uri)
    profile = await fetch_user_profile(token_data["access_token"])
    connected_email = microsoft_account_email(profile)
    expected_email = settings.MS_ORGANIZER_EMAIL.strip().casefold()
    if connected_email != expected_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connect {settings.MS_ORGANIZER_EMAIL}, not {connected_email or 'another Microsoft account'}.",
        )
    await upsert_token(db, user_id, token_data)

    dest = append_query_param(redirect_to, "ms", "connected")
    return RedirectResponse(url=dest, status_code=status.HTTP_302_FOUND)


@router.get("/status")
async def status_check(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
    scope = row.scope if row is not None else None
    return {
        "connected": row is not None,
        "scope": scope,
        "can_write_calendar": bool(scope and "calendars.readwrite" in scope.lower()),
        "account_email": settings.MS_ORGANIZER_EMAIL,
        "can_manage": user.role == UserRole.ADMIN,
    }


@router.delete("/disconnect")
async def disconnect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ensure_calendar_admin(user)
    await db.execute(delete(MicrosoftToken))
    await db.commit()
    return {"connected": False}


@router.get("/events", response_model=list[MicrosoftEvent])
async def get_events(
    request: Request,
    start: datetime | None = None,
    end: datetime | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MicrosoftEvent]:
    ensure_ms_config()
    row = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shared Microsoft calendar {settings.MS_ORGANIZER_EMAIL} is not connected",
        )

    now = datetime.now(timezone.utc)
    if row.expires_at <= now + timedelta(seconds=30):
        row = await refresh_token_row(db, row, resolve_redirect_uri(request))

    if start is None:
        start = now
    if end is None:
        end = start + timedelta(days=30)

    try:
        raw_events = await fetch_calendar_events_with_retry(row.access_token, start, end)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Microsoft API error ({exc.response.status_code})",
            ) from exc
        try:
            row = await refresh_token_row(db, row, resolve_redirect_uri(request))
            raw_events = await fetch_calendar_events_with_retry(row.access_token, start, end)
        except httpx.HTTPError as retry_exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Microsoft authentication or calendar request failed after retry",
            ) from retry_exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Microsoft Calendar is temporarily unavailable after retry",
        ) from exc

    events: list[MicrosoftEvent] = []
    for event in raw_events:
        start_raw = (event.get("start") or {}).get("dateTime")
        end_raw = (event.get("end") or {}).get("dateTime")
        starts_at = None
        ends_at = None
        if start_raw:
            try:
                starts_at = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            except ValueError:
                starts_at = None
        if end_raw:
            try:
                ends_at = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            except ValueError:
                ends_at = None
        organizer = None
        organizer_info = (event.get("organizer") or {}).get("emailAddress") or {}
        if organizer_info:
            organizer = organizer_info.get("name") or organizer_info.get("address")
        location = (event.get("location") or {}).get("displayName")

        events.append(
            MicrosoftEvent(
                id=str(event.get("id")),
                subject=event.get("subject"),
                starts_at=starts_at,
                ends_at=ends_at,
                location=location,
                categories=[str(category) for category in (event.get("categories") or [])],
                is_all_day=bool(event.get("isAllDay") or False),
                organizer=organizer,
                body_preview=event.get("bodyPreview"),
            )
        )
    return events
