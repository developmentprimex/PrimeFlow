"""OAuth 2.1 authorization server for the remote MCP assistant connector.

Implements the parts of the MCP authorization spec (2025-06-18) the connector
needs: RFC 8414 metadata, RFC 7591 dynamic client registration, authorization
code + PKCE (S256), refresh-token rotation, RFC 7009 revocation, and RFC 8707
resource binding. Login and consent happen on the existing PrimeFlow frontend
(``/oauth/consent``), which calls the authenticated ``/api/oauth/requests`` API.

Everything returns 404 unless ``MCP_ASSISTANT_ENABLED`` is true.
"""
from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.security import create_access_token
from app.config import settings
from app.db import get_db
from app.models.oauth import OAuthAuthorizationRequest, OAuthClient, OAuthToken
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.oauth_server import (
    ACCESS_TOKEN_PREFIX,
    CODE_PREFIX,
    REFRESH_TOKEN_PREFIX,
    SUPPORTED_SCOPE,
    authorization_server_metadata,
    email_is_allowed,
    hash_secret,
    issuer,
    new_secret,
    redirect_uri_is_allowed,
    resource_is_allowed,
    verify_pkce,
    with_query,
)

public_router = APIRouter(tags=["oauth"])
api_router = APIRouter(tags=["oauth"])

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_enabled() -> None:
    if not settings.MCP_ASSISTANT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _oauth_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status_code, headers=NO_STORE)


# ---------------------------------------------------------------- discovery


@public_router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata() -> JSONResponse:
    _ensure_enabled()
    return JSONResponse(authorization_server_metadata())


# Some clients probe the OpenID path; serve the same OAuth metadata there.
@public_router.get("/.well-known/openid-configuration")
async def oauth_metadata_openid_alias() -> JSONResponse:
    _ensure_enabled()
    return JSONResponse(authorization_server_metadata())


# ---------------------------------------------------------------- registration


class ClientRegistrationIn(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    client_name: str | None = Field(default=None, max_length=200)
    grant_types: list[str] | None = None
    response_types: list[str] | None = None
    token_endpoint_auth_method: str | None = None
    scope: str | None = None


@public_router.post("/oauth/register", status_code=status.HTTP_201_CREATED)
async def register_client(payload: ClientRegistrationIn, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    _ensure_enabled()
    for uri in payload.redirect_uris:
        if not redirect_uri_is_allowed(uri):
            return _oauth_error("invalid_redirect_uri", "Redirect URI is not allowed for this server.")
    grant_types = payload.grant_types or ["authorization_code", "refresh_token"]
    if not set(grant_types) <= {"authorization_code", "refresh_token"}:
        return _oauth_error("invalid_client_metadata", "Only authorization_code and refresh_token are supported.")
    # Requested scopes are informational (claude.ai sends e.g. "claudeai"); RFC 7591 lets
    # the server replace them, so every client is registered with the single PrimeFlow scope.
    client = OAuthClient(
        client_id="pfm_" + uuid.uuid4().hex,
        client_name=(payload.client_name or "").strip()[:200] or None,
        redirect_uris=list(dict.fromkeys(payload.redirect_uris)),
        grant_types=grant_types,
        scope=SUPPORTED_SCOPE,
    )
    db.add(client)
    await db.commit()
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(_now().timestamp()),
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": client.grant_types,
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SUPPORTED_SCOPE,
        },
        status_code=status.HTTP_201_CREATED,
        headers=NO_STORE,
    )


async def _client(db: AsyncSession, client_id: str | None) -> OAuthClient | None:
    if not client_id:
        return None
    return (await db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id))).scalar_one_or_none()


# ---------------------------------------------------------------- authorize


@public_router.get("/oauth/authorize")
async def authorize(request: Request, db: AsyncSession = Depends(get_db)):
    _ensure_enabled()
    params = request.query_params
    client = await _client(db, params.get("client_id"))
    redirect_uri = params.get("redirect_uri") or ""
    # Never redirect to an unverified URI: report these two errors directly.
    if client is None:
        return _oauth_error("invalid_client", "Unknown client_id.")
    if redirect_uri not in (client.redirect_uris or []) or not redirect_uri_is_allowed(redirect_uri):
        return _oauth_error("invalid_request", "redirect_uri does not match the registered client.")

    state = params.get("state")

    def fail(error: str, description: str) -> RedirectResponse:
        return RedirectResponse(
            with_query(redirect_uri, {"error": error, "error_description": description, "state": state, "iss": issuer()}),
            status_code=status.HTTP_302_FOUND,
        )

    if params.get("response_type") != "code":
        return fail("unsupported_response_type", "Only response_type=code is supported.")
    challenge = params.get("code_challenge") or ""
    if params.get("code_challenge_method") != "S256" or not (43 <= len(challenge) <= 128):
        return fail("invalid_request", "PKCE with code_challenge_method=S256 is required.")
    # Unknown requested scopes are ignored (RFC 6749 3.3): the grant always carries
    # only the PrimeFlow scope, so nothing beyond it can be requested.
    resource = params.get("resource")
    if not resource_is_allowed(resource):
        return fail("invalid_target", "The requested resource is not served by this authorization server.")

    pending = OAuthAuthorizationRequest(
        client_id=client.client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
        scope=SUPPORTED_SCOPE,
        resource=resource or settings.MCP_ASSISTANT_RESOURCE_URL,
        expires_at=_now() + timedelta(seconds=settings.OAUTH_PENDING_REQUEST_SECONDS),
    )
    db.add(pending)
    await db.commit()
    consent_url = f"{settings.FRONTEND_URL.rstrip('/')}/oauth/consent?request_id={pending.id}"
    return RedirectResponse(consent_url, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------- consent (authenticated API)


async def _pending_request(db: AsyncSession, request_id: uuid.UUID) -> OAuthAuthorizationRequest:
    row = (
        await db.execute(
            select(OAuthAuthorizationRequest).where(OAuthAuthorizationRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.code_hash is not None or row.consumed_at is not None or row.expires_at <= _now():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Authorization request expired or not found")
    return row


@api_router.get("/requests/{request_id}")
async def get_authorization_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _ensure_enabled()
    row = await _pending_request(db, request_id)
    client = await _client(db, row.client_id)
    return {
        "request_id": str(row.id),
        "client_name": (client.client_name if client else None) or "MCP client",
        "redirect_host": urlsplit(row.redirect_uri).netloc,
        "scope": row.scope,
        "user_email": user.email,
        "allowed": email_is_allowed(user.email),
    }


@api_router.post("/requests/{request_id}/approve")
async def approve_authorization_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _ensure_enabled()
    row = await _pending_request(db, request_id)
    if not email_is_allowed(user.email):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is not allowed to connect the assistant")
    code = new_secret(CODE_PREFIX)
    row.user_id = user.id
    row.code_hash = hash_secret(code)
    row.code_expires_at = _now() + timedelta(seconds=settings.OAUTH_AUTH_CODE_SECONDS)
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="oauth_client", entity_id=row.id,
        action="MCP_ASSISTANT_AUTHORIZED", after={"client_id": row.client_id, "resource": row.resource},
    )
    await db.commit()
    return {"redirect_url": with_query(row.redirect_uri, {"code": code, "state": row.state, "iss": issuer()})}


@api_router.post("/requests/{request_id}/deny")
async def deny_authorization_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _ensure_enabled()
    row = await _pending_request(db, request_id)
    row.consumed_at = _now()
    await db.commit()
    return {
        "redirect_url": with_query(
            row.redirect_uri,
            {"error": "access_denied", "error_description": "The user denied the request.", "state": row.state, "iss": issuer()},
        )
    }


# ---------------------------------------------------------------- token


async def _issue_tokens(
    db: AsyncSession, *, client_id: str, user_id: uuid.UUID, resource: str | None, family_id: uuid.UUID
) -> dict:
    access = new_secret(ACCESS_TOKEN_PREFIX)
    refresh = new_secret(REFRESH_TOKEN_PREFIX)
    now = _now()
    access_ttl = timedelta(minutes=settings.OAUTH_ACCESS_TOKEN_MINUTES)
    for raw, kind, ttl in (
        (access, "access", access_ttl),
        (refresh, "refresh", timedelta(days=settings.OAUTH_REFRESH_TOKEN_DAYS)),
    ):
        db.add(
            OAuthToken(
                token_hash=hash_secret(raw), token_type=kind, client_id=client_id, user_id=user_id,
                scope=SUPPORTED_SCOPE, resource=resource, family_id=family_id, expires_at=now + ttl,
            )
        )
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(access_ttl.total_seconds()),
        "refresh_token": refresh,
        "scope": SUPPORTED_SCOPE,
    }


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    await db.execute(
        update(OAuthToken)
        .where(OAuthToken.family_id == family_id, OAuthToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def _active_allowed_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active or not email_is_allowed(user.email):
        return None
    return user


@public_router.post("/oauth/token")
async def token(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    _ensure_enabled()
    form = await request.form()
    grant_type = form.get("grant_type")
    client_id = str(form.get("client_id") or "")
    client = await _client(db, client_id)
    if client is None:
        return _oauth_error("invalid_client", "Unknown client_id.", status.HTTP_401_UNAUTHORIZED)
    resource = form.get("resource")
    if resource is not None and not resource_is_allowed(str(resource)):
        return _oauth_error("invalid_target", "The requested resource is not served by this server.")

    if grant_type == "authorization_code":
        code = str(form.get("code") or "")
        row = (
            await db.execute(
                select(OAuthAuthorizationRequest)
                .where(OAuthAuthorizationRequest.code_hash == hash_secret(code))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            row is None
            or row.consumed_at is not None
            or row.client_id != client.client_id
            or row.code_expires_at is None
            or row.code_expires_at <= _now()
            or row.user_id is None
        ):
            return _oauth_error("invalid_grant", "Authorization code is invalid, expired or already used.")
        if str(form.get("redirect_uri") or "") != row.redirect_uri:
            return _oauth_error("invalid_grant", "redirect_uri does not match the authorization request.")
        if not verify_pkce(str(form.get("code_verifier") or ""), row.code_challenge):
            return _oauth_error("invalid_grant", "PKCE verification failed.")
        row.consumed_at = _now()
        if await _active_allowed_user(db, row.user_id) is None:
            await db.commit()
            return _oauth_error("invalid_grant", "The user is no longer allowed to use the assistant.")
        body = await _issue_tokens(
            db, client_id=client.client_id, user_id=row.user_id, resource=row.resource, family_id=uuid.uuid4()
        )
        await db.commit()
        return JSONResponse(body, headers=NO_STORE)

    if grant_type == "refresh_token":
        raw = str(form.get("refresh_token") or "")
        row = (
            await db.execute(
                select(OAuthToken).where(OAuthToken.token_hash == hash_secret(raw), OAuthToken.token_type == "refresh")
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.client_id != client.client_id:
            return _oauth_error("invalid_grant", "Refresh token is invalid.")
        if row.revoked_at is not None:
            # A rotated refresh token was replayed: treat the whole grant as compromised.
            await _revoke_family(db, row.family_id)
            await db.commit()
            return _oauth_error("invalid_grant", "Refresh token was already used; the session has been revoked.")
        if row.expires_at <= _now():
            return _oauth_error("invalid_grant", "Refresh token has expired.")
        if await _active_allowed_user(db, row.user_id) is None:
            await _revoke_family(db, row.family_id)
            await db.commit()
            return _oauth_error("invalid_grant", "The user is no longer allowed to use the assistant.")
        row.revoked_at = _now()
        body = await _issue_tokens(
            db, client_id=client.client_id, user_id=row.user_id, resource=row.resource, family_id=row.family_id
        )
        await db.commit()
        return JSONResponse(body, headers=NO_STORE)

    return _oauth_error("unsupported_grant_type", "Use authorization_code or refresh_token.")


@public_router.post("/oauth/revoke")
async def revoke(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    _ensure_enabled()
    form = await request.form()
    raw = str(form.get("token") or "")
    row = (await db.execute(select(OAuthToken).where(OAuthToken.token_hash == hash_secret(raw)))).scalar_one_or_none()
    if row is not None:
        client_id = str(form.get("client_id") or "")
        if not client_id or client_id == row.client_id:
            await _revoke_family(db, row.family_id)
            add_audit_log(
                db=db, actor_user_id=row.user_id, entity_type="oauth_client", entity_id=row.family_id,
                action="MCP_ASSISTANT_REVOKED", after={"client_id": row.client_id},
            )
            await db.commit()
    # RFC 7009: respond 200 whether or not the token was known.
    return JSONResponse({}, headers=NO_STORE)


# ---------------------------------------------------------------- internal session for the MCP process


class SessionIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@api_router.post("/internal/session")
async def internal_session(
    payload: SessionIn,
    db: AsyncSession = Depends(get_db),
    x_mcp_internal_secret: str | None = Header(default=None, alias="X-MCP-Internal-Secret"),
) -> JSONResponse:
    """Validate an assistant access token and mint a short-lived PrimeFlow API token.

    Only the MCP assistant process can call this (shared secret). The returned
    API token is the normal PrimeFlow JWT for the token's user, so every API
    write is attributed to that user (created_by, audit_logs).
    """
    _ensure_enabled()
    expected = settings.MCP_ASSISTANT_INTERNAL_SECRET or ""
    if not expected or not hmac.compare_digest(x_mcp_internal_secret or "", expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal secret")
    inactive = JSONResponse({"active": False}, headers=NO_STORE)
    if not payload.token.startswith(ACCESS_TOKEN_PREFIX):
        return inactive
    row = (
        await db.execute(
            select(OAuthToken).where(OAuthToken.token_hash == hash_secret(payload.token), OAuthToken.token_type == "access")
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= _now() or not resource_is_allowed(row.resource):
        return inactive
    user = await _active_allowed_user(db, row.user_id)
    if user is None:
        return inactive
    row.last_used_at = _now()
    await db.commit()
    api_token = create_access_token(user_id=user.id, role=user.role.value, department_id=user.department_id)
    return JSONResponse(
        {
            "active": True,
            "sub": str(user.id),
            "email": user.email,
            "client_id": row.client_id,
            "scope": row.scope,
            "resource": row.resource,
            "exp": int(row.expires_at.timestamp()),
            "primeflow_access_token": api_token,
            "primeflow_access_token_expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        },
        headers=NO_STORE,
    )
