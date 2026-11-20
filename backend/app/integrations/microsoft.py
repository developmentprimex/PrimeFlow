from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import settings


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
OAUTH_BASE_URL = f"https://login.microsoftonline.com/{settings.MS_TENANT_ID}/oauth2/v2.0"

SCOPES = ["offline_access", "https://graph.microsoft.com/User.Read", "https://graph.microsoft.com/Calendars.ReadWrite"]
SCOPE_STR = " ".join(SCOPES)
# Tasks.ReadWrite (Microsoft To Do for the GA assistant) is requested only when
# MS_TODO_ENABLED=true AND the mailbox is (re-)authorized. Off by default, so the
# Microsoft connect flow asks for exactly the same permissions as before. Token
# refreshes always keep asking for SCOPE_STR, so calendar sync is unaffected.
TODO_SCOPE = "https://graph.microsoft.com/Tasks.ReadWrite"


def authorize_scope_str() -> str:
    return " ".join([*SCOPES, TODO_SCOPE] if settings.MS_TODO_ENABLED else SCOPES)


def refresh_scope_str(granted_scope: str | None) -> str:
    """Scopes for a token refresh: the calendar scopes, plus To Do only when the stored
    grant already contains Tasks.ReadWrite (so a refresh never asks for anything new
    and never drops the To Do permission after the mailbox was re-authorized)."""
    granted = {item.rsplit("/", 1)[-1].casefold() for item in (granted_scope or "").split()}
    return " ".join([*SCOPES, TODO_SCOPE] if "tasks.readwrite" in granted else SCOPES)


def format_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": authorize_scope_str(),
        "state": state,
        "prompt": "select_account",
    }
    return f"{OAUTH_BASE_URL}/authorize?{urlencode(params)}"


async def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"{OAUTH_BASE_URL}/token",
            data={
                "client_id": settings.MS_CLIENT_ID,
                "client_secret": settings.MS_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "scope": authorize_scope_str(),
            },
        )
    res.raise_for_status()
    return res.json()


async def refresh_access_token(refresh_token: str, redirect_uri: str, granted_scope: str | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"{OAUTH_BASE_URL}/token",
            data={
                "client_id": settings.MS_CLIENT_ID,
                "client_secret": settings.MS_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": redirect_uri,
                "scope": refresh_scope_str(granted_scope),
            },
        )
    res.raise_for_status()
    return res.json()


async def fetch_calendar_events(access_token: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    params = {
        "startDateTime": format_datetime(start),
        "endDateTime": format_datetime(end),
        "$select": (
            "id,iCalUId,changeKey,createdDateTime,subject,start,end,location,categories,isAllDay,isCancelled,isOnlineMeeting,organizer,attendees,"
            "bodyPreview,onlineMeeting,onlineMeetingUrl,webLink,type,seriesMasterId"
        ),
        "$orderby": "start/dateTime",
        "$top": "250",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.timezone="UTC", IdType="ImmutableId"',
    }
    events: list[dict[str, Any]] = []
    url: str | None = f"{GRAPH_BASE_URL}/me/calendarView"
    async with httpx.AsyncClient(timeout=15.0) as client:
        next_params: dict[str, str] | None = params
        while url:
            res = await client.get(url, params=next_params, headers=headers)
            res.raise_for_status()
            data = res.json()
            events.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            next_params = None
    return events


async def update_calendar_event(
    access_token: str,
    event_id: str,
    *,
    subject: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if subject is not None:
        payload["subject"] = subject
    if start is not None:
        payload["start"] = {"dateTime": format_datetime(start).removesuffix("Z"), "timeZone": "UTC"}
    if end is not None:
        payload["end"] = {"dateTime": format_datetime(end).removesuffix("Z"), "timeZone": "UTC"}
    if location is not None:
        payload["location"] = {"displayName": location}
    if not payload:
        return {}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.patch(
            f"{GRAPH_BASE_URL}/me/events/{quote(event_id, safe='')}",
            json=payload,
            headers=headers,
        )
    res.raise_for_status()
    return res.json()


async def delete_calendar_event(access_token: str, event_id: str) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.delete(
            f"{GRAPH_BASE_URL}/me/events/{quote(event_id, safe='')}",
            headers=headers,
        )
    res.raise_for_status()


async def fetch_calendar_schedule(
    access_token: str,
    emails: list[str],
    start: datetime,
    end: datetime,
    *,
    timezone_name: str = "UTC",
) -> list[dict[str, Any]]:
    """Return Microsoft free/busy details for the requested attendees."""
    if not emails:
        return []
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": f'outlook.timezone="{timezone_name}"',
    }
    body = {
        "schedules": emails,
        "startTime": {"dateTime": format_datetime(start).removesuffix("Z"), "timeZone": "UTC"},
        "endTime": {"dateTime": format_datetime(end).removesuffix("Z"), "timeZone": "UTC"},
        "availabilityViewInterval": 15,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(f"{GRAPH_BASE_URL}/me/calendar/getSchedule", json=body, headers=headers)
    res.raise_for_status()
    return res.json().get("value", [])


async def create_calendar_event(
    access_token: str,
    *,
    subject: str,
    start: datetime,
    end: datetime,
    attendees: list[dict[str, str]],
    body_html: str | None,
    transaction_id: str,
    create_online_meeting: bool,
) -> dict[str, Any]:
    """Create an organizer-calendar event; Outlook sends invitations to attendees."""
    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html or ""},
        "start": {"dateTime": format_datetime(start).removesuffix("Z"), "timeZone": "UTC"},
        "end": {"dateTime": format_datetime(end).removesuffix("Z"), "timeZone": "UTC"},
        "attendees": [
            {
                "emailAddress": {"address": item["email"], "name": item.get("name") or item["email"]},
                "type": "required",
            }
            for item in attendees
        ],
        "responseRequested": True,
        "transactionId": transaction_id,
    }
    if create_online_meeting:
        payload["isOnlineMeeting"] = True
        payload["onlineMeetingProvider"] = "teamsForBusiness"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(f"{GRAPH_BASE_URL}/me/events", json=payload, headers=headers)
    res.raise_for_status()
    return res.json()


async def fetch_user_profile(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(
            f"{GRAPH_BASE_URL}/me",
            params={"$select": "displayName,mail,userPrincipalName"},
            headers=headers,
        )
    res.raise_for_status()
    return res.json()


def microsoft_account_email(profile: dict[str, Any]) -> str:
    return str(profile.get("mail") or profile.get("userPrincipalName") or "").strip().casefold()


def compute_expires_at(expires_in: int) -> datetime:
    now = datetime.now(timezone.utc)
    buffer_seconds = 60
    return now + timedelta(seconds=max(expires_in - buffer_seconds, 0))
