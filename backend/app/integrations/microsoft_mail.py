"""OAuth and read-only Microsoft Graph calls for company mailboxes."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.config import settings


SCOPES = "offline_access User.Read Mail.Read"
GRAPH_URL = "https://graph.microsoft.com/v1.0"
INFO_PX_NOTE_ORIGIN = "INFO_PX_MAIL"
IT_NOTE_ORIGIN = "IT_MAIL"


MailboxKey = Literal["info-px", "it"]


@dataclass(frozen=True)
class Mailbox:
    token_id: int
    email: str
    label: str
    note_origin: str
    client_id: str | None
    client_secret: str | None
    tenant_id: str | None


def mailbox_for(key: MailboxKey) -> Mailbox:
    if key == "it":
        return Mailbox(2, "it@forestdream.de", "EM IT", IT_NOTE_ORIGIN, settings.MS_MAIL_IT_CLIENT_ID,
                       settings.MS_MAIL_IT_CLIENT_SECRET, settings.MS_MAIL_IT_TENANT_ID)
    return Mailbox(1, "info@primexeu.com", "EM INFO PX", INFO_PX_NOTE_ORIGIN, settings.MS_MAIL_CLIENT_ID,
                   settings.MS_MAIL_CLIENT_SECRET, settings.MS_MAIL_TENANT_ID)


def _oauth_endpoint(action: str, mailbox: Mailbox) -> str:
    tenant = quote(mailbox.tenant_id or "", safe="")
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/{action}"


def authorization_url(state: str, verifier: str, mailbox: Mailbox) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "client_id": mailbox.client_id,
        "redirect_uri": settings.MS_MAIL_REDIRECT_URI,
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
        "login_hint": mailbox.email,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{_oauth_endpoint('authorize', mailbox)}?{urlencode(params)}"


async def request_token(client: httpx.AsyncClient, grant: dict[str, str], mailbox: Mailbox) -> dict:
    response = await client.post(_oauth_endpoint("token", mailbox), data={
        "client_id": mailbox.client_id,
        "client_secret": mailbox.client_secret,
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


async def validate_mailbox(client: httpx.AsyncClient, token: str, mailbox: Mailbox) -> None:
    profile = await _get(client, f"{GRAPH_URL}/me", token, params={"$select": "mail,userPrincipalName"})
    email = (profile.get("mail") or profile.get("userPrincipalName") or "").strip().casefold()
    if email != mailbox.email:
        raise ValueError("The signed-in account does not match the selected mailbox.")


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
