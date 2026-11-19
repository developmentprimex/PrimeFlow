"""Security rules of the MCP assistant OAuth server (no database needed)."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.config import settings  # noqa: E402
from app.services import oauth_server as oauth  # noqa: E402


class PkceTests(unittest.TestCase):
    def test_rfc7636_example_vector(self) -> None:
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertEqual(oauth.pkce_s256(verifier), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        self.assertTrue(oauth.verify_pkce(verifier, "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"))

    def test_rejects_wrong_short_or_missing_verifier(self) -> None:
        challenge = oauth.pkce_s256("a" * 43)
        self.assertFalse(oauth.verify_pkce("b" * 43, challenge))
        self.assertFalse(oauth.verify_pkce("a" * 42, oauth.pkce_s256("a" * 42)))
        self.assertFalse(oauth.verify_pkce(None, challenge))
        self.assertFalse(oauth.verify_pkce("é" * 43, challenge))


class RedirectAndResourceTests(unittest.TestCase):
    def test_redirect_policy(self) -> None:
        with patch.object(settings, "OAUTH_ALLOWED_REDIRECT_URIS", "https://claude.ai/api/mcp/auth_callback"):
            self.assertTrue(oauth.redirect_uri_is_allowed("https://claude.ai/api/mcp/auth_callback"))
            self.assertTrue(oauth.redirect_uri_is_allowed("http://127.0.0.1:33418/callback"))
            self.assertTrue(oauth.redirect_uri_is_allowed("http://localhost:6274/oauth/callback"))
            for uri in (
                "https://claude.ai/api/mcp/auth_callback/extra",
                "https://evil.example.com/callback",
                "http://evil.example.com/callback",
                "https://127.0.0.1/callback",  # loopback exception is for http only (RFC 8252)
                "http://127.0.0.1.evil.com/cb",
                "https://claude.ai/api/mcp/auth_callback#frag",
                "",
            ):
                self.assertFalse(oauth.redirect_uri_is_allowed(uri), uri)

    def test_resource_binding(self) -> None:
        with patch.object(settings, "MCP_ASSISTANT_RESOURCE_URL", "https://mcp-flow.primexeu.com/mcp"):
            self.assertTrue(oauth.resource_is_allowed(None))
            self.assertTrue(oauth.resource_is_allowed("https://mcp-flow.primexeu.com/mcp"))
            self.assertTrue(oauth.resource_is_allowed("https://mcp-flow.primexeu.com/mcp/"))
            self.assertFalse(oauth.resource_is_allowed("https://other.example.com/mcp"))

    def test_scope(self) -> None:
        self.assertTrue(oauth.scope_is_allowed(None))
        self.assertTrue(oauth.scope_is_allowed("primeflow"))
        self.assertFalse(oauth.scope_is_allowed("primeflow admin"))


class AllowlistAndMetadataTests(unittest.TestCase):
    def test_allowlist_is_case_insensitive_and_empty_means_nobody(self) -> None:
        with patch.object(settings, "MCP_ASSISTANT_ALLOWED_EMAILS", " GA@Example.com , other@example.com "):
            self.assertTrue(oauth.email_is_allowed("ga@example.com"))
            self.assertFalse(oauth.email_is_allowed("someone@example.com"))
        with patch.object(settings, "MCP_ASSISTANT_ALLOWED_EMAILS", ""):
            self.assertFalse(oauth.email_is_allowed("ga@example.com"))
            self.assertFalse(oauth.email_is_allowed(None))

    def test_issuer_matches_sdk_normalization_and_endpoints_have_no_double_slash(self) -> None:
        with patch.object(settings, "OAUTH_ISSUER_URL", "https://api-flow.primexeu.com"):
            meta = oauth.authorization_server_metadata()
            self.assertEqual(meta["issuer"], "https://api-flow.primexeu.com/")
            self.assertEqual(meta["token_endpoint"], "https://api-flow.primexeu.com/oauth/token")
            self.assertEqual(meta["code_challenge_methods_supported"], ["S256"])
            self.assertEqual(meta["token_endpoint_auth_methods_supported"], ["none"])

    def test_secrets_are_prefixed_random_and_hashed(self) -> None:
        first, second = oauth.new_secret(oauth.ACCESS_TOKEN_PREFIX), oauth.new_secret(oauth.ACCESS_TOKEN_PREFIX)
        self.assertTrue(first.startswith("pfm_at_"))
        self.assertNotEqual(first, second)
        self.assertEqual(len(oauth.hash_secret(first)), 64)
        self.assertNotIn(first, oauth.hash_secret(first))

    def test_with_query_keeps_existing_params(self) -> None:
        url = oauth.with_query("http://127.0.0.1:1/cb?x=1", {"code": "c", "state": None})
        self.assertEqual(url, "http://127.0.0.1:1/cb?x=1&code=c")


class EnabledFlagTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoints_are_hidden_when_disabled(self) -> None:
        import httpx
        from app.main import app

        with patch.object(settings, "MCP_ASSISTANT_ENABLED", False):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                self.assertEqual((await client.get("/.well-known/oauth-authorization-server")).status_code, 404)
                self.assertEqual((await client.post("/oauth/register", json={"redirect_uris": ["http://127.0.0.1/cb"]})).status_code, 404)
                self.assertEqual(
                    (await client.post("/api/oauth/internal/session", json={"token": "pfm_at_xxxxxxxxxxxx"})).status_code, 404
                )


if __name__ == "__main__":
    unittest.main()
