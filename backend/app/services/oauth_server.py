"""Pure helpers for the PrimeFlow OAuth 2.1 authorization server (MCP assistant).

Kept free of FastAPI so the security-relevant rules (PKCE, redirect URI policy,
allowlist, token hashing) are unit-testable on their own.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from app.config import settings

ACCESS_TOKEN_PREFIX = "pfm_at_"
REFRESH_TOKEN_PREFIX = "pfm_rt_"
CODE_PREFIX = "pfm_ac_"
SUPPORTED_SCOPE = "primeflow"
KNOWLEDGE_SCOPE = "knowledge.read"
KNOWN_SCOPES = {SUPPORTED_SCOPE, KNOWLEDGE_SCOPE}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def new_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_pkce(verifier: str | None, challenge: str) -> bool:
    if not verifier or not (43 <= len(verifier) <= 128):
        return False
    try:
        return hmac.compare_digest(pkce_s256(verifier), challenge)
    except (UnicodeEncodeError, ValueError):
        return False


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def allowed_emails() -> set[str]:
    return {item.casefold() for item in _csv(settings.MCP_ASSISTANT_ALLOWED_EMAILS)}


def email_is_allowed(email: str | None) -> bool:
    return bool(email) and email.strip().casefold() in allowed_emails()


def redirect_uri_is_allowed(uri: str, configured: str | None = None) -> bool:
    """Exact match against the configured list, or any loopback http URI (RFC 8252)."""
    if not uri or "#" in uri:
        return False
    if uri in _csv(settings.OAUTH_ALLOWED_REDIRECT_URIS if configured is None else configured):
        return True
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    return parts.scheme == "http" and (parts.hostname or "") in LOOPBACK_HOSTS


def resource_is_allowed(resource: str | None) -> bool:
    """RFC 8707: when a resource is requested it must be this MCP server."""
    if not resource:
        return True
    expected = settings.MCP_ASSISTANT_RESOURCE_URL.rstrip("/")
    return resource.rstrip("/") == expected


def granted_scope(requested: str | None) -> str:
    """Every grant carries only the PrimeFlow scope, whatever the client asked for."""
    return SUPPORTED_SCOPE


@dataclass(frozen=True)
class ResourceGrant:
    url: str
    scope: str
    allowed_emails: frozenset[str]
    redirects: str

    def allows_redirect(self, uri: str) -> bool:
        if self.scope == KNOWLEDGE_SCOPE:
            return uri.startswith("https://") and "#" not in uri and uri in _csv(self.redirects)
        return redirect_uri_is_allowed(uri, self.redirects)

    def allows_user(self, email: str | None) -> bool:
        return bool(email) and email.strip().casefold() in self.allowed_emails


def knowledge_resource() -> ResourceGrant | None:
    if not settings.MCP_KNOWLEDGE_ENABLED:
        return None
    url = settings.MCP_KNOWLEDGE_RESOURCE_URL.rstrip("/")
    try:
        parsed = urlsplit(url)
        assistant = urlsplit(settings.MCP_ASSISTANT_RESOURCE_URL.rstrip("/"))
        same_resource = (
            (parsed.scheme, parsed.hostname, parsed.port or 443, parsed.path)
            == (assistant.scheme, assistant.hostname, assistant.port or 443, assistant.path)
        )
    except ValueError:
        return None
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.query or parsed.fragment or same_resource
        or any(character.isspace() for character in url)
    ):
        return None
    secret = settings.MCP_KNOWLEDGE_INTROSPECTION_SECRET
    if not secret or hmac.compare_digest(
        secret.get_secret_value().encode("utf-8"),
        (settings.MCP_ASSISTANT_INTERNAL_SECRET or "").encode("utf-8"),
    ):
        return None
    emails = frozenset(email.casefold() for email in _csv(settings.MCP_KNOWLEDGE_ALLOWED_EMAILS))
    return ResourceGrant(url, KNOWLEDGE_SCOPE, emails, settings.MCP_KNOWLEDGE_ALLOWED_REDIRECT_URIS)


def assistant_resource() -> ResourceGrant | None:
    if not settings.MCP_ASSISTANT_ENABLED:
        return None
    return ResourceGrant(
        settings.MCP_ASSISTANT_RESOURCE_URL.rstrip("/"), SUPPORTED_SCOPE,
        frozenset(allowed_emails()), settings.OAUTH_ALLOWED_REDIRECT_URIS,
    )


def available_resources() -> list[ResourceGrant]:
    return [grant for grant in (assistant_resource(), knowledge_resource()) if grant is not None]


def resolve_resource(resource: str | None) -> ResourceGrant | None:
    """An omitted or empty indicator retains the assistant's historical default."""
    if not resource:
        return assistant_resource()
    return next((grant for grant in available_resources() if grant.url == resource.rstrip("/")), None)


def available_scopes() -> list[str]:
    return [grant.scope for grant in available_resources()]


def registration_scope(requested: str | None, redirect_uris: list[str]) -> str:
    known_requested = KNOWN_SCOPES.intersection((requested or "").split())
    return " ".join(
        grant.scope for grant in available_resources()
        if (not known_requested or grant.scope in known_requested)
        and any(grant.allows_redirect(uri) for uri in redirect_uris)
    )


def authorization_scope_is_allowed(requested: str | None, resource: str | None, grant: ResourceGrant) -> bool:
    known_requested = KNOWN_SCOPES.intersection((requested or "").split())
    # An explicit target can narrow a request listing both advertised scopes.
    return not known_requested or (
        grant.scope in known_requested and (bool(resource) or known_requested == {grant.scope})
    )


def registered_redirect_is_allowed(uri: str) -> bool:
    return any(grant.allows_redirect(uri) for grant in available_resources())


def with_query(uri: str, params: dict[str, str | None]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def issuer_base() -> str:
    """Base URL for building endpoint URLs (no trailing slash)."""
    return settings.OAUTH_ISSUER_URL.rstrip("/")


def issuer() -> str:
    """Issuer identifier, normalized like the MCP SDK publishes it in the protected
    resource metadata (a bare origin gets a trailing slash), so clients that compare
    the two strings (RFC 8414 / RFC 9207 ``iss``) see the same value."""
    base = issuer_base()
    return base if urlsplit(base).path else base + "/"


def authorization_server_metadata() -> dict:
    base = issuer_base()
    return {
        "issuer": issuer(),
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": available_scopes(),
        "authorization_response_iss_parameter_supported": True,
    }
