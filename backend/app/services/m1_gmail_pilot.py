"""Read the explicitly labeled Gmail messages for the local M1 pilot."""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import Message
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup


_CREDENTIALS = Path(gettempdir()) / "primeflow-m1-gmail-pilot" / "credentials.json"
_BODY_CREDENTIALS = _CREDENTIALS.with_name("body-credentials.json")
_MAILBOX = "01primex.eu@gmail.com"
_LABEL = "PrimeFlow-M1-Test"
_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/gmail.metadata"
_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@dataclass(frozen=True)
class GmailMessage:
    id: str
    subject: str
    sender: str
    received_at: datetime
    body: str = ""


def _is_attached_part(part: dict) -> bool:
    return bool(part.get("filename")) or any(
        header["name"].casefold() == "content-disposition"
        and header["value"].partition(";")[0].strip().casefold() == "attachment"
        for header in part.get("headers", [])
    )


def extract_gmail_text(part: dict) -> str:
    """Read the displayable MIME body without rendering external HTML."""
    if _is_attached_part(part):
        return ""
    mime = part.get("mimeType")
    children = part.get("parts") or []
    if children:
        if mime in (None, "multipart/alternative"):
            children = sorted(children, key=lambda child: child.get("mimeType") != "text/plain")
            return next((text for child in children if (text := extract_gmail_text(child))), "")
        if mime == "multipart/related":
            return extract_gmail_text(children[0])
        return "\n\n".join(text for child in children if (text := extract_gmail_text(child)))

    data = part.get("body", {}).get("data")
    if mime not in {"text/plain", "text/html"} or not data:
        return ""
    headers = Message()
    for header in part.get("headers", []):
        if header["name"].casefold() == "content-type":
            headers["Content-Type"] = header["value"]
            break
    decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    try:
        text = decoded.decode(headers.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        text = decoded.decode("utf-8", errors="replace")
    if mime == "text/html":
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["head", "script", "style", "template"]):
            tag.decompose()
        for tag in soup(["p", "div", "br", "li", "tr", "blockquote", "pre"]):
            tag.append("\n")
        text = "\n".join(line.strip() for line in soup.get_text().splitlines() if line.strip())
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


async def fetch_gmail_body_parts(get: Callable[..., Awaitable[dict]], message_id: str, part: dict) -> None:
    if _is_attached_part(part):
        return
    body = part.get("body") or {}
    if part.get("mimeType") in {"text/plain", "text/html"} and not body.get("data") and body.get("attachmentId"):
        path = f"messages/{quote(message_id, safe='')}/attachments/{quote(body['attachmentId'], safe='')}"
        part["body"] = await get(path, fields="data")
    for child in part.get("parts") or []:
        await fetch_gmail_body_parts(get, message_id, child)


async def read_m1_gmail_messages(
    report_day: date,
    report_tz: ZoneInfo,
    *,
    window: tuple[datetime, datetime] | None = None,
) -> list[GmailMessage] | None:
    messages = await read_labeled_gmail_messages(include_body=True)
    if messages is None:
        messages = await read_labeled_gmail_messages()
    if messages is None:
        return None
    if window is not None:
        start, end = window
        return [message for message in messages if start <= message.received_at <= end]
    return [
        message
        for message in messages
        if message.received_at.astimezone(report_tz).date() == report_day
    ]


async def read_labeled_gmail_messages(*, include_body: bool = False) -> list[GmailMessage] | None:
    """Return None when the pilot has not been configured on this machine."""
    try:
        credential_path = _BODY_CREDENTIALS if include_body else _CREDENTIALS
        credentials = json.loads(credential_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None

    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.post(_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "refresh_token": credentials["refresh_token"],
        })
        response.raise_for_status()
        token = response.json()
        accepted_scopes = {_READ_SCOPE} if include_body else {_SCOPE, _READ_SCOPE}
        if token.get("scope") and accepted_scopes.isdisjoint(token["scope"].split()):
            raise ValueError("The requested Gmail permission is missing.")
        client.headers["Authorization"] = f"Bearer {token['access_token']}"

        async def get(path: str, **params) -> dict:
            response = await client.get(f"{_API}/{path}", params=params)
            response.raise_for_status()
            return response.json()

        profile = await get("profile", fields="emailAddress")
        if profile["emailAddress"].casefold() != _MAILBOX:
            raise ValueError("The authorized Gmail account does not match the M1 pilot.")
        labels = await get("labels", fields="labels(id,name)")
        label_id = next((label["id"] for label in labels.get("labels", []) if label["name"] == _LABEL), None)
        if not label_id:
            raise ValueError("The M1 pilot label is missing in Gmail.")

        rows = []
        seen = set()
        page_params = {"labelIds": label_id, "maxResults": 50}
        while True:
            page = await get("messages", **page_params)
            for item in page.get("messages", []):
                message_id = item["id"]
                if message_id in seen:
                    continue
                seen.add(message_id)
                if include_body:
                    message = await get(f"messages/{message_id}", format="full", fields="internalDate,payload")
                else:
                    message = await get(
                        f"messages/{message_id}", format="metadata",
                        metadataHeaders=["Subject", "From"], fields="internalDate,payload(headers)",
                    )
                received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000, timezone.utc)
                payload = message.get("payload", {})
                headers = {
                    header["name"].casefold(): header["value"]
                    for header in payload.get("headers", [])
                }
                if include_body:
                    await fetch_gmail_body_parts(get, message_id, payload)
                rows.append(GmailMessage(
                    message_id, headers.get("subject", ""), headers.get("from", ""), received_at,
                    extract_gmail_text(payload) if include_body else "",
                ))
            next_page = page.get("nextPageToken")
            if not next_page:
                return sorted(rows, key=lambda row: row.received_at, reverse=True)
            page_params["pageToken"] = next_page
