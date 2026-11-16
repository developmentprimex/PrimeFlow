"""Read-only Graph operations. No mail/label writes and no task/Note creation."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet

from app.config import settings
from app.integrations.microsoft import GRAPH_BASE_URL, OAUTH_BASE_URL


MAIL_SCOPES = (
    "offline_access",
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/MailboxSettings.Read",
)
REQUIRED_SCOPES = {"user.read", "mail.read", "mailboxsettings.read"}


def granted_scopes(scope: str) -> set[str]:
    return {part.rsplit("/", 1)[-1].lower() for part in scope.split()}


def has_mail_permissions(scope: str) -> bool:
    return REQUIRED_SCOPES.issubset(granted_scopes(scope))


def _token_cipher() -> Fernet:
    # This key is provisioned separately from JWT_SECRET and outside the database.
    # Never generate a replacement implicitly: existing tokens would be lost.
    return Fernet(Path(settings.MS_MAIL_TOKEN_KEY_FILE).read_bytes().strip())


def token_storage_ready() -> bool:
    try:
        _token_cipher()
    except (OSError, ValueError):
        return False
    return True


def encrypt_token(value: str) -> str:
    return _token_cipher().encrypt(value.encode()).decode()


def decrypt_token(value: str) -> str:
    return _token_cipher().decrypt(value.encode()).decode()


def build_mail_authorize_url(redirect_uri: str, state: str) -> str:
    params = {
        'client_id': settings.MS_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'response_mode': 'query',
        'scope': ' '.join(MAIL_SCOPES),
        'state': state,
        'prompt': 'select_account',
        'login_hint': settings.MS_MAILBOX_EMAIL,
    }
    return f"{OAUTH_BASE_URL}/authorize?{urlencode(params)}"


async def mail_token_request(redirect_uri: str, *, code: str | None = None, refresh_token: str | None = None) -> dict:
    data = {
        "client_id": settings.MS_CLIENT_ID,
        "client_secret": settings.MS_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "scope": " ".join(MAIL_SCOPES),
    }
    if code:
        data.update(grant_type="authorization_code", code=code)
    else:
        data.update(grant_type="refresh_token", refresh_token=refresh_token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{OAUTH_BASE_URL}/token", data=data)
    response.raise_for_status()
    return response.json()


async def fetch_mail_preview(access_token: str) -> dict:
    """Read ten newest Inbox messages and all categories; never mark mail read."""
    headers = {"Authorization": f"Bearer {access_token}", "Prefer": 'IdType="ImmutableId"'}
    async with httpx.AsyncClient(timeout=20.0) as client:
        messages_response = await client.get(
            f"{GRAPH_BASE_URL}/me/mailFolders/inbox/messages",
            headers=headers,
            params={
                "$top": "10",
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview,categories,hasAttachments,isRead",
            },
        )
        messages_response.raise_for_status()
        categories = []
        next_url = f"{GRAPH_BASE_URL}/me/outlook/masterCategories"
        seen = set()
        while next_url:
            # Do not forward bearer tokens to an arbitrary pagination destination.
            parts = urlsplit(next_url)
            if parts.scheme != "https" or parts.netloc != "graph.microsoft.com" or next_url in seen:
                raise ValueError("Invalid Microsoft category pagination")
            seen.add(next_url)
            response = await client.get(next_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            categories.extend({"id": str(c["id"]), "name": c.get("displayName", ""), "color": c.get("color")} for c in data.get("value", []))
            next_url = data.get("@odata.nextLink")
    messages = []
    for item in messages_response.json().get("value", []):
        sender = (item.get("from") or {}).get("emailAddress") or {}
        messages.append({
            "id": str(item["id"]),
            "subject": item.get("subject") or "(Pa subjekt)",
            "sender_name": sender.get("name"),
            "sender_email": sender.get("address"),
            "received_at": item.get("receivedDateTime"),
            "preview": item.get("bodyPreview") or "",
            "categories": item.get("categories") or [],
            "has_attachments": bool(item.get("hasAttachments")),
            "is_read": bool(item.get("isRead")),
        })
    return {"categories": categories, "messages": messages}


async def fetch_mailbox_type(access_token: str) -> str:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{GRAPH_BASE_URL}/me/mailboxSettings/userPurpose",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    response.raise_for_status()
    return str(response.json().get("value") or "unknown").lower()
