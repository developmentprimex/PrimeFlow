"""The assistant MCP profile (run with the .venv-mcp-assistant interpreter).

Checks the allowlist, tool annotations, that API calls carry the caller's own
PrimeFlow token (never the service account), and per-user lookup caches.
"""
import importlib
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch


def load_assistant_server():
    os.environ["PRIMEFLOW_MCP_PROFILE"] = "assistant"
    os.environ.setdefault("MCP_ASSISTANT_INTERNAL_SECRET", "test-secret")
    sys.modules.pop("mcp_server", None)
    try:
        return importlib.import_module("mcp_server")
    finally:
        os.environ.pop("PRIMEFLOW_MCP_PROFILE", None)


try:
    from mcp.server.auth.provider import AccessToken

    HAS_NEW_SDK = "subject" in AccessToken.model_fields
except ImportError:  # the shared interpreter keeps the older SDK on purpose
    HAS_NEW_SDK = False


@unittest.skipUnless(HAS_NEW_SDK, "assistant profile needs requirements-mcp-assistant.txt")
class AssistantProfileTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = load_assistant_server()

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("mcp_server", None)

    async def test_exactly_the_allowlist_is_exposed(self) -> None:
        tools = {tool.name: tool for tool in await self.server.mcp.list_tools()}
        self.assertEqual(set(tools), set(self.server.ASSISTANT_TOOLS))
        for excluded in ("primeflow_api_request", "run_readonly_sql", "list_database_tables", "save_weekly_plan",
                         "create_common_entry", "create_internal_note", "create_plan_note", "export_report",
                         "create_meeting", "lock_weekly_realization", "approve_weekly_realization"):
            self.assertNotIn(excluded, tools)

    async def test_annotations(self) -> None:
        tools = {tool.name: tool for tool in await self.server.mcp.list_tools()}
        self.assertTrue(tools["ga_agenda"].annotations.readOnlyHint)
        self.assertTrue(tools["get_task"].annotations.readOnlyHint)
        self.assertFalse(tools["ga_item_done"].annotations.readOnlyHint)
        self.assertFalse(tools["update_task"].annotations.readOnlyHint)
        self.assertTrue(tools["ga_item_remove_from_day"].annotations.destructiveHint)
        self.assertFalse(tools["ga_item_postpone"].annotations.destructiveHint)

    async def test_calls_use_the_callers_token_not_the_service_account(self) -> None:
        caller = self.server.mcp._token_verifier  # noqa: SLF001 - the profile's verifier
        self.assertIsNotNone(caller)
        token_cls = type(caller).__mro__[0]
        from mcp.server.auth.provider import AccessToken

        class Fake(AccessToken):
            api_token: str = "jwt-of-ga"
            api_token_expires_at: float = 0.0
            email: str | None = "ga@example.com"

        import time

        access = Fake(token="pfm_at_x", client_id="c", scopes=["primeflow"], subject="user-1",
                      api_token_expires_at=time.time() + 900)
        with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=access), \
                patch.dict(os.environ, {"PRIMEFLOW_EMAIL": "service@example.com", "PRIMEFLOW_PASSWORD": "x"}):
            self.assertEqual(await self.server._access_token(), "jwt-of-ga")
            self.assertEqual(await self.server._headers(), {"Authorization": "Bearer jwt-of-ga"})
            self.assertEqual(self.server._cache_scope(), "user-1:")
        self.assertIsNotNone(token_cls)

    async def test_api_calls_use_the_current_message_token_not_the_session_one(self) -> None:
        """Regression: after 15 minutes the session's first JWT expired and every API call
        returned 401 "Invalid token". Each message must use its own bearer and a fresh JWT."""
        import time
        from types import SimpleNamespace

        from mcp.server.auth.provider import AccessToken

        class Fake(AccessToken):
            api_token: str = ""
            api_token_expires_at: float = 0.0
            email: str | None = None

        stale = Fake(token="pfm_at_first", client_id="c", scopes=["primeflow"], subject="ga",
                     api_token="expired-jwt", api_token_expires_at=time.time() - 10)
        fresh = Fake(token="pfm_at_current", client_id="c", scopes=["primeflow"], subject="ga",
                     api_token="fresh-jwt", api_token_expires_at=time.time() + 900)
        request = SimpleNamespace(headers={"authorization": "Bearer pfm_at_current"})
        verifier = self.server.ASSISTANT_VERIFIER
        with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=stale),                 patch.object(type(self.server.mcp._mcp_server), "request_context",
                             new=property(lambda _self: SimpleNamespace(request=request))),                 patch.object(verifier, "verify_token", AsyncMock(return_value=fresh)) as verify:
            self.assertEqual(await self.server._access_token(), "fresh-jwt")
            verify.assert_awaited_with("pfm_at_current")

    async def test_api_401_forces_a_new_jwt_once(self) -> None:
        verifier = self.server.ASSISTANT_VERIFIER
        calls = []

        class Resp:
            def __init__(self, code):
                self.status_code = code
                self.content = b"{}"
                self.is_error = code >= 400
                self.headers = {}

            def json(self):
                return {}

        async def fake_request(self_client, method, path, params=None, json=None):
            calls.append(self_client.headers.get("authorization"))
            return Resp(401 if len(calls) == 1 else 200)

        tokens = iter(["old-jwt", "new-jwt"])

        async def fake_current_access(*, force=False):
            from types import SimpleNamespace
            return SimpleNamespace(api_token=next(tokens), force=force)

        with patch.object(self.server, "_current_access", side_effect=fake_current_access) as current,                 patch("httpx.AsyncClient.request", fake_request):
            await self.server._request("GET", "/api/common-view")
        self.assertEqual(calls, ["Bearer old-jwt", "Bearer new-jwt"])
        self.assertTrue(current.call_args_list[1].kwargs["force"])
        self.assertIsNotNone(verifier)

    async def test_unauthenticated_call_is_refused(self) -> None:
        with patch("mcp.server.auth.middleware.auth_context.get_access_token", return_value=None):
            with self.assertRaises(RuntimeError):
                await self.server._access_token()

    async def test_ga_tools_call_the_backend_assistant_api(self) -> None:
        with patch.object(self.server, "_request", AsyncMock(return_value={"ok": True})) as request:
            await self.server.ga_item_done("pf_task:11111111-1111-1111-1111-111111111111")
            request.assert_awaited_with(
                "POST", "/api/ga-assistant/items/done",
                json={"item_id": "pf_task:11111111-1111-1111-1111-111111111111", "comment": None, "override_reason": None},
            )
            await self.server.ga_item_set_time("pf_task:x", "11:00", "2026-11-19")
            self.assertEqual(request.await_args.kwargs["json"], {"item_id": "pf_task:x", "time": "11:00", "day": "2026-11-19"})
            await self.server.todo_complete("todo:LIST/=::TASK=")
            self.assertEqual(request.await_args.args[1], "/api/ga-assistant/todo/todo:LIST%2F%3D::TASK%3D/complete")
            with self.assertRaises(ValueError):
                await self.server.todo_complete("pf_task:x")

    async def test_token_verifier_rejects_inactive_tokens(self) -> None:
        verifier = self.server.mcp._token_verifier  # noqa: SLF001

        class Response:
            status_code = 200

            def json(self):
                return {"active": False}

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=Response())):
            self.assertIsNone(await verifier.verify_token("pfm_at_inactive"))


if __name__ == "__main__":
    unittest.main()
