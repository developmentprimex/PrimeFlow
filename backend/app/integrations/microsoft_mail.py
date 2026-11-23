"""OAuth and read-only Microsoft Graph calls for INFO PX."""

from __future__ import annotations

import base64
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.config import settings


MAILBOX = "info@primexeu.com"
SCOPES = "offline_access User.Read Mail.Read"
GRAPH_URL = "https://graph.microsoft.com/v1.0"


def _oauth_endpoint(action: str) -> str:
    tenant = quote(settings.MS_MAIL_TENANT_ID or "", safe="")
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/{action}"


def authorization_url(state: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": settings.MS_MAIL_CLIENT_ID,
        "redirect_uri": settings.MS_MAIL_REDIRECT_URI,
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
        "login_hint": MAILBOX,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{_oauth_endpoint('authorize')}?{urlencode(params)}"


async def request_token(client: httpx.AsyncClient, grant: dict[str, str]) -> dict:
    response = await client.post(_oauth_endpoint("token"), data={
        "client_id": settings.MS_MAIL_CLIENT_ID,
        "client_secret": settings.MS_MAIL_CLIENT_SECRET,
        "redirect_uri": settings.MS_MAIL_REDIRECT_URI,
        "scope": SCOPES,
        **grant,
    })
    response.raise_for_status()
    token = response.json()
    scopes = {value.rsplit("/", 1)[-1].casefold() for value in token.get("scope", "").split()}
    if "mail.read" not in scopes or not token.get("access_token"):
        raise ValueError("Microsoft did not grant Mail.Read.")
    return token


async def _get(client: httpx.AsyncClient, url: str, token: str, **kwargs) -> dict:
    address = httpx.URL(url)
    if address.scheme != "https" or address.host != "graph.microsoft.com" or address.port not in (None, 443):
        raise ValueError("Invalid Microsoft Graph URL.")
    response = await client.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.body-content-type="text", IdType="ImmutableId"',
    }, **kwargs)
    response.raise_for_status()
    return response.json()


async def validate_mailbox(client: httpx.AsyncClient, token: str) -> None:
    profile = await _get(client, f"{GRAPH_URL}/me", token, params={"$select": "mail,userPrincipalName"})
    email = (profile.get("mail") or profile.get("userPrincipalName") or "").strip().casefold()
    if email != MAILBOX:
        raise ValueError("Sign in as info@primexeu.com.")


async def _collection(client: httpx.AsyncClient, url: str, token: str, params: dict):
    while url:
        page = await _get(client, url, token, params=params or None)
        for item in page.get("value", []):
            yield item
        url = page.get("@odata.nextLink")
        params = {}


async def read_inbox(
    client: httpx.AsyncClient, token: str, report_day: date, tz: ZoneInfo,
) -> list[dict]:
    start = datetime.combine(report_day, time.min, tz).astimezone(timezone.utc)
    end = datetime.combine(report_day + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
    filter_by_date = f"receivedDateTime ge {start:%Y-%m-%dT%H:%M:%SZ} and receivedDateTime lt {end:%Y-%m-%dT%H:%M:%SZ}"
    params = {
        "$select": "id,subject,from,receivedDateTime,body",
        "$filter": filter_by_date,
        "$orderby": "receivedDateTime desc",
        "$top": "50",
    }
    rows = []
    url = f"{GRAPH_URL}/me/mailFolders/inbox/messages"
    async for message in _collection(client, url, token, params):
        sender = (message.get("from") or {}).get("emailAddress") or {}
        sender_name, sender_address = sender.get("name"), sender.get("address")
        received_at = datetime.fromisoformat(message["receivedDateTime"]).astimezone(tz)
        body = message.get("body") or {}
        content = body.get("content") or ""
        if (body.get("contentType") or "").casefold() == "html":
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["head", "script", "style", "template"]):
                tag.decompose()
            content = soup.get_text("\n", strip=True)
        rows.append({
            "id": message["id"],
            "subject": message.get("subject") or "(Pa subjekt)",
            "sender": f"{sender_name} <{sender_address}>" if sender_name and sender_address else (
                sender_name or sender_address or "-"
            ),
            "received_at": received_at.strftime("%H:%M"),
            "received_datetime": received_at.isoformat(),
            "body": content,
        })
    return rows
