"""Read-only Gmail OAuth and inbox access for EM PX EU."""

import base64
import hashlib
from datetime import date, datetime, time, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.integrations.microsoft_mail import Mailbox
from app.services.m1_gmail_pilot import extract_gmail_text, fetch_gmail_body_parts


SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
PX_EU_NOTE_ORIGIN = "PX_EU_MAIL"


def mailbox_for_px_eu() -> Mailbox:
    return Mailbox(
        3, "primex.eu@gmail.com", "EM PX EU", PX_EU_NOTE_ORIGIN,
        settings.GMAIL_PX_EU_CLIENT_ID, settings.GMAIL_PX_EU_CLIENT_SECRET, None,
    )


def authorization_url(state: str, verifier: str, mailbox: Mailbox) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": mailbox.client_id,
        "redirect_uri": settings.GMAIL_PX_EU_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "login_hint": mailbox.email,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def request_token(client: httpx.AsyncClient, grant: dict[str, str], mailbox: Mailbox) -> dict:
    data = {"client_id": mailbox.client_id, "client_secret": mailbox.client_secret, **grant}
    exchanging_code = grant["grant_type"] == "authorization_code"
    if exchanging_code:
        data["redirect_uri"] = settings.GMAIL_PX_EU_REDIRECT_URI
    response = await client.post("https://oauth2.googleapis.com/token", data=data)
    response.raise_for_status()
    token = response.json()
    scope = token.get("scope")
    if not token.get("access_token") or ((exchanging_code or scope is not None) and set((scope or "").split()) != {SCOPE}):
        raise ValueError("Google did not grant read-only Gmail access.")
    return token


async def _get(client: httpx.AsyncClient, token: str, path: str, **params) -> dict:
    response = await client.get(f"{API_URL}/{path}", headers={"Authorization": f"Bearer {token}"}, params=params)
    response.raise_for_status()
    return response.json()


def _canonical_address(address: str) -> str:
    local, _, domain = address.strip().casefold().partition("@")
    return f"{local.replace('.', '')}@{domain}" if domain == "gmail.com" else address.strip().casefold()


async def validate_mailbox(client: httpx.AsyncClient, token: str, mailbox: Mailbox) -> None:
    profile = await _get(client, token, "profile", fields="emailAddress")
    if _canonical_address(profile["emailAddress"]) != _canonical_address(mailbox.email):
        raise ValueError("The signed-in Google account does not match EM PX EU.")


async def read_inbox(
    client: httpx.AsyncClient, token: str, report_day: date, tz: ZoneInfo, *,
    window: tuple[datetime, datetime] | None = None,
) -> list[dict]:
    start, end = window or (datetime.combine(report_day, time.min, tz), datetime.combine(report_day, time.max, tz))
    if end < start:
        return []
    # Gmail searches by whole seconds. Filter exact timestamps before reading bodies.
    params = {
        "labelIds": "INBOX",
        "q": f"after:{int(start.timestamp()) - 1} before:{int(end.timestamp()) + 1}",
        "maxResults": 50,
        "fields": "messages(id),nextPageToken",
    }
    rows: list[dict] = []
    seen: set[str] = set()

    async def get(path: str, **query) -> dict:
        return await _get(client, token, path, **query)

    while True:
        page = await get("messages", **params)
        for item in page.get("messages", []):
            message_id = item["id"]
            if message_id in seen:
                continue
            seen.add(message_id)
            message = await get(
                f"messages/{quote(message_id, safe='')}", format="full", fields="internalDate,labelIds,payload,threadId",
            )
            received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc).astimezone(tz)
            if not start <= received_at <= end or "INBOX" not in message.get("labelIds", []):
                continue
            payload = message.get("payload") or {}
            headers = {header["name"].casefold(): header["value"] for header in payload.get("headers", [])}
            await fetch_gmail_body_parts(get, message_id, payload)
            thread_id = message.get("threadId")
            original_url = (
                f"https://mail.google.com/mail/?{urlencode({'authuser': mailbox_for_px_eu().email})}"
                f"#all/{quote(thread_id, safe='')}"
                if thread_id else None
            )
            rows.append({
                "id": message_id,
                "subject": headers.get("subject") or "(Pa subjekt)",
                "sender": headers.get("from") or "-",
                "received_at": received_at.strftime("%H:%M"),
                "received_datetime": received_at.isoformat(),
                "body": extract_gmail_text(payload),
                **({"original_email_url": original_url} if original_url else {}),
            })
        next_page = page.get("nextPageToken")
        if not next_page:
            return sorted(rows, key=lambda row: datetime.fromisoformat(row["received_datetime"]).timestamp(), reverse=True)
        params["pageToken"] = next_page
