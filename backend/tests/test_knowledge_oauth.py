"""OAuth grant and validation boundaries for the Knowledge PX MCP pilot."""

import os
import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from pydantic import SecretStr

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")

from app.api.deps import get_current_user  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.oauth import OAuthAuthorizationRequest, OAuthToken  # noqa: E402
from app.services.oauth_server import pkce_s256  # noqa: E402

ASSISTANT = "https://flow.example.test/mcp"
KNOWLEDGE = "https://knowledge.example.test/mcp"
CALLBACK = "https://client.example.test/callback"
KNOWLEDGE_SCOPE = "knowledge.read"
KNOWLEDGE_SECRET = "test-only-knowledge-introspection-secret"


class KnowledgeOAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        for name, value in {
            "MCP_ASSISTANT_ENABLED": True,
            "MCP_ASSISTANT_RESOURCE_URL": ASSISTANT,
            "MCP_ASSISTANT_ALLOWED_EMAILS": "assistant@example.test",
            "MCP_ASSISTANT_INTERNAL_SECRET": "test-only-assistant-secret",
            "MCP_KNOWLEDGE_ENABLED": True,
            "MCP_KNOWLEDGE_RESOURCE_URL": KNOWLEDGE,
            "MCP_KNOWLEDGE_ALLOWED_EMAILS": "staff@example.test",
            "MCP_KNOWLEDGE_ALLOWED_REDIRECT_URIS": CALLBACK,
            "MCP_KNOWLEDGE_INTROSPECTION_SECRET": SecretStr(KNOWLEDGE_SECRET),
            "OAUTH_ALLOWED_REDIRECT_URIS": CALLBACK,
        }.items():
            self.patches.enter_context(patch.object(settings, name, value, create=True))

        self.user = SimpleNamespace(id=uuid.uuid4(), email="staff@example.test", is_active=True)
        self.db = MagicMock()
        self.db.commit = AsyncMock()
        self.db.execute = AsyncMock()
        self.db.add.side_effect = self._assign_pending_id
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.addCleanup(app.dependency_overrides.pop, get_db, None)
        self.addCleanup(app.dependency_overrides.pop, get_current_user, None)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.http.aclose)
        self.client = SimpleNamespace(
            client_id="client", client_name="Test connector", redirect_uris=[CALLBACK],
            scope=KNOWLEDGE_SCOPE, grant_types=["authorization_code", "refresh_token"],
        )

    @staticmethod
    def _assign_pending_id(row):
        if isinstance(row, OAuthAuthorizationRequest):
            row.id = uuid.uuid4()

    def returns(self, *rows):
        results = []
        for row in rows:
            result = MagicMock()
            result.scalar_one_or_none.return_value = row
            results.append(result)
        self.db.execute.side_effect = results

    def oauth_grant(self, **changes):
        row = {
            "client_id": self.client.client_id, "user_id": self.user.id,
            "scope": KNOWLEDGE_SCOPE, "resource": KNOWLEDGE,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "revoked_at": None, "family_id": uuid.uuid4(),
        }
        row.update(changes)
        return SimpleNamespace(**row)

    async def introspect(self, secret=KNOWLEDGE_SECRET):
        return await self.http.post(
            "/api/oauth/internal/knowledge/introspect",
            headers={"X-MCP-Knowledge-Secret": secret},
            json={"token": "pfm_at_test-token-value"},
        )

    async def test_discovery_and_registration_are_opt_in(self):
        path = "/.well-known/oauth-authorization-server"
        self.assertIn(KNOWLEDGE_SCOPE, (await self.http.get(path)).json()["scopes_supported"])
        registration = await self.http.post("/oauth/register", json={
            "redirect_uris": [CALLBACK], "scope": KNOWLEDGE_SCOPE,
        })
        self.assertEqual(registration.status_code, 201, registration.text)
        self.assertEqual(registration.json()["scope"], KNOWLEDGE_SCOPE)
        with patch.object(settings, "MCP_KNOWLEDGE_ENABLED", False):
            self.assertEqual((await self.http.get(path)).json()["scopes_supported"], ["primeflow"])
            self.assertEqual((await self.introspect()).status_code, 404)

    async def test_consent_and_pkce_issue_only_knowledge_access(self):
        verifier = "x" * 43
        self.returns(self.client)
        response = await self.http.get("/oauth/authorize", params={
            "client_id": self.client.client_id, "redirect_uri": CALLBACK,
            "response_type": "code", "code_challenge": pkce_s256(verifier),
            "code_challenge_method": "S256", "state": "test", "resource": KNOWLEDGE,
            "scope": "primeflow knowledge.read",
        })
        self.assertEqual(response.status_code, 302, response.text)
        pending = self.db.add.call_args.args[0]
        self.assertEqual((pending.scope, pending.resource), (KNOWLEDGE_SCOPE, KNOWLEDGE))
        path = f"/api/oauth/requests/{pending.id}"
        self.returns(pending, self.client)
        consent = (await self.http.get(path)).json()
        self.assertTrue(consent["allowed"])
        self.assertEqual(consent["scope"], KNOWLEDGE_SCOPE)
        self.returns(pending)
        with patch.object(settings, "MCP_KNOWLEDGE_ALLOWED_EMAILS", ""):
            self.assertEqual((await self.http.post(path + "/approve")).status_code, 403)
        self.returns(pending)
        approval = await self.http.post(path + "/approve")
        self.assertEqual(approval.status_code, 200, approval.text)
        code = parse_qs(urlsplit(approval.json()["redirect_url"]).query)["code"][0]
        form = {
            "grant_type": "authorization_code", "client_id": self.client.client_id,
            "code": code, "redirect_uri": CALLBACK, "code_verifier": verifier,
        }

        self.returns(self.client, pending)
        response = await self.http.post("/oauth/token", data={**form, "resource": ASSISTANT})
        self.assertEqual(response.json()["error"], "invalid_target")
        self.assertIsNone(pending.consumed_at)
        self.returns(self.client, pending)
        self.assertEqual(
            (await self.http.post("/oauth/token", data={**form, "code_verifier": "y" * 43})).json()["error"],
            "invalid_grant",
        )
        self.returns(self.client, pending, self.user)
        response = await self.http.post("/oauth/token", data=form)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scope"], KNOWLEDGE_SCOPE)
        issued = [call.args[0] for call in self.db.add.call_args_list if isinstance(call.args[0], OAuthToken)]
        self.assertEqual({(token.scope, token.resource, token.token_type) for token in issued}, {
            (KNOWLEDGE_SCOPE, KNOWLEDGE, "access"), (KNOWLEDGE_SCOPE, KNOWLEDGE, "refresh"),
        })

    async def test_refresh_cannot_switch_resources_and_keeps_scope(self):
        row = self.oauth_grant()
        form = {"grant_type": "refresh_token", "client_id": self.client.client_id, "refresh_token": "pfm_rt_test"}
        self.returns(self.client, row)
        rejected = await self.http.post("/oauth/token", data={**form, "resource": ASSISTANT})
        self.assertEqual(rejected.json()["error"], "invalid_target")
        self.assertIsNone(row.revoked_at)
        self.returns(self.client, row, self.user)
        refreshed = await self.http.post("/oauth/token", data=form)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["scope"], KNOWLEDGE_SCOPE)
        self.assertEqual(self.db.add.call_args.args[0].resource, KNOWLEDGE)
        self.assertIsNotNone(row.revoked_at)

    async def test_introspection_is_separate_read_only_and_rechecks_access(self):
        self.assertEqual((await self.introspect(secret=settings.MCP_ASSISTANT_INTERNAL_SECRET)).status_code, 401)
        self.db.execute.assert_not_awaited()
        for row in (
            None,
            self.oauth_grant(resource=ASSISTANT, scope="primeflow"),
            self.oauth_grant(resource=None),
            self.oauth_grant(scope="primeflow"),
            self.oauth_grant(revoked_at=datetime.now(timezone.utc)),
            self.oauth_grant(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
        ):
            self.returns(row)
            response = await self.introspect()
            self.assertEqual(response.json(), {"active": False}, response.text)
        self.returns(self.oauth_grant(), self.user)
        with patch.object(settings, "MCP_KNOWLEDGE_ALLOWED_EMAILS", ""):
            self.assertEqual((await self.introspect()).json(), {"active": False})
        self.returns(self.oauth_grant(), self.user)
        response = await self.introspect()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(set(response.json()), {"active", "scope", "resource", "client_id", "sub", "exp"})
        self.assertEqual(response.json()["scope"], KNOWLEDGE_SCOPE)
        self.assertEqual(response.json()["resource"], KNOWLEDGE)
        self.db.commit.assert_not_awaited()

        # Even a valid assistant service credential cannot exchange a Knowledge grant for an API JWT.
        self.returns(self.oauth_grant())
        response = await self.http.post("/api/oauth/internal/session",
            headers={"X-MCP-Internal-Secret": settings.MCP_ASSISTANT_INTERNAL_SECRET},
            json={"token": "pfm_at_test-token-value"})
        self.assertEqual(response.json(), {"active": False})



    async def test_inactive_or_colliding_configuration_never_publishes_knowledge(self):
        path = "/.well-known/oauth-authorization-server"
        with patch.object(settings, "MCP_KNOWLEDGE_RESOURCE_URL", "https://FLOW.example.test:443/mcp/"):
            self.assertEqual((await self.http.get(path)).json()["scopes_supported"], ["primeflow"])
        with patch.object(settings, "MCP_KNOWLEDGE_INTROSPECTION_SECRET", SecretStr(settings.MCP_ASSISTANT_INTERNAL_SECRET)):
            self.assertEqual((await self.http.get(path)).json()["scopes_supported"], ["primeflow"])

    async def test_existing_assistant_token_still_gets_primeflow_session(self):
        assistant = SimpleNamespace(
            id=self.user.id, email="assistant@example.test", is_active=True,
            role=SimpleNamespace(value="admin"), department_id=None,
        )
        self.returns(self.oauth_grant(resource=ASSISTANT, scope="primeflow"), assistant)
        with patch("app.api.routers.oauth.create_access_token", return_value="mock-assistant-jwt") as mint:
            response = await self.http.post(
                "/api/oauth/internal/session",
                headers={"X-MCP-Internal-Secret": settings.MCP_ASSISTANT_INTERNAL_SECRET},
                json={"token": "pfm_at_assistant-fixture"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["primeflow_access_token"], "mock-assistant-jwt")
        mint.assert_called_once()

    async def test_oauth_request_must_select_one_resource(self):
        self.returns(self.client)
        params = [("client_id", self.client.client_id), ("redirect_uri", CALLBACK),
                  ("response_type", "code"), ("code_challenge", pkce_s256("x" * 43)),
                  ("code_challenge_method", "S256"), ("resource", KNOWLEDGE), ("resource", ASSISTANT)]
        response = await self.http.get("/oauth/authorize", params=params)
        self.assertEqual(parse_qs(urlsplit(response.headers["Location"]).query)["error"], ["invalid_target"])
        self.db.add.assert_not_called()



    async def test_knowledge_scope_cannot_default_to_assistant(self):
        self.client.scope = "primeflow knowledge.read"
        common = {
            "client_id": self.client.client_id, "redirect_uri": CALLBACK, "response_type": "code",
            "code_challenge_method": "S256", "code_challenge": pkce_s256("x" * 43),
        }
        for scope, resource in ((KNOWLEDGE_SCOPE, None), (KNOWLEDGE_SCOPE, ASSISTANT),
                                ("primeflow", KNOWLEDGE), ("primeflow knowledge.read", None)):
            self.returns(self.client)
            params = {**common, "scope": scope}
            if resource:
                params["resource"] = resource
            response = await self.http.get("/oauth/authorize", params=params)
            self.assertEqual(parse_qs(urlsplit(response.headers["Location"]).query).get("error"), ["invalid_scope"])
        self.db.add.assert_not_called()



    async def test_knowledge_only_callback_cannot_grant_assistant_scope(self):
        callback = "https://knowledge-client.example.test/callback"
        with patch.object(settings, "MCP_KNOWLEDGE_ALLOWED_REDIRECT_URIS", callback):
            registered = await self.http.post("/oauth/register", json={
                "redirect_uris": [callback], "scope": "client-hint",
            })
            self.assertEqual(registered.json()["scope"], KNOWLEDGE_SCOPE)
            self.client.scope = "primeflow knowledge.read"
            self.client.redirect_uris = [callback]
            self.returns(self.client)
            response = await self.http.get("/oauth/authorize", params={
                "client_id": self.client.client_id, "redirect_uri": callback, "response_type": "code",
                "code_challenge_method": "S256", "code_challenge": pkce_s256("x" * 43), "resource": ASSISTANT,
            })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"], "invalid_request")

    async def test_blank_legacy_resource_preserves_assistant_default(self):
        self.client.scope = "primeflow"
        with patch.object(settings, "MCP_KNOWLEDGE_ENABLED", False):
            self.returns(self.client)
            response = await self.http.get("/oauth/authorize", params={
                "client_id": self.client.client_id, "redirect_uri": CALLBACK, "response_type": "code",
                "code_challenge_method": "S256", "code_challenge": pkce_s256("x" * 43), "resource": "",
                "scope": "claudeai",
            })
        self.assertEqual(response.status_code, 302)
        pending = self.db.add.call_args.args[0]
        self.assertEqual((pending.resource, pending.scope), (ASSISTANT, "primeflow"))

    async def test_only_assistant_keeps_historical_loopback_callback_rule(self):
        callback = "http://127.0.0.1:33418/callback"
        with patch.object(settings, "MCP_KNOWLEDGE_ALLOWED_REDIRECT_URIS", callback):
            registered = await self.http.post("/oauth/register", json={
                "redirect_uris": [callback], "scope": "client-hint",
            })
            self.assertEqual(registered.json()["scope"], "primeflow")
            rejected = await self.http.post("/oauth/register", json={
                "redirect_uris": [callback], "scope": KNOWLEDGE_SCOPE,
            })
            self.assertEqual(rejected.json()["error"], "invalid_client_metadata")
