import os
import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "voice-test-secret")

import httpx
from fastapi import FastAPI, HTTPException
from app.api.deps import get_current_user
from app.db import get_db
from app.api.routers import voice_assistant as api
from app.services import voice_assistant as voice

TASK_ID = str(uuid.uuid4())
ITEM_ID = str(uuid.uuid4())
USER = SimpleNamespace(id=uuid.uuid4(), username="Arta", full_name="Arta Test")


def task():
    return {"id": TASK_ID, "title": "Raporti", "description": "1. Hulumto\n2. Dërgo", "status": "IN_PROGRESS", "user_comment": None}


class VoiceToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_version_prevents_every_write(self):
        with patch.object(voice, "read_task", AsyncMock(return_value=(task(), []))), patch.object(voice.tasks, "user_api", AsyncMock()) as request:
            result = await voice.execute_tool(USER, "set_task_status", {"task_id": TASK_ID, "expected_version": "0" * 64, "status": "DONE"})
        self.assertFalse(result["changed"])
        request.assert_not_awaited()

    async def test_close_uses_normal_api_and_strikes_points_before_done(self):
        before = task()
        with patch.object(voice, "read_task", AsyncMock(return_value=(before, []))), patch.object(voice.tasks, "user_api", AsyncMock()) as request:
            result = await voice.execute_tool(USER, "set_task_status", {"task_id": TASK_ID, "expected_version": voice.task_detail(before, [])["expected_version"], "status": "DONE"})
        self.assertTrue(result["success"])
        calls = request.await_args_list
        self.assertTrue(all(call.args[0] is USER for call in calls))
        self.assertEqual(calls[0].args[2], f"/api/tasks/{TASK_ID}/comment")
        self.assertEqual(calls[-1].kwargs["body"]["status"], "DONE")
        self.assertIn("[[done]]", calls[-1].kwargs["body"]["description"])

    async def test_partial_completion_is_reported(self):
        before = task()
        with patch.object(voice, "read_task", AsyncMock(return_value=(before, []))), patch.object(voice.tasks, "user_api", AsyncMock(side_effect=[{}, HTTPException(403, "Nuk lejohet")])):
            result = await voice.execute_tool(USER, "set_task_status", {"task_id": TASK_ID, "expected_version": voice.task_detail(before, [])["expected_version"], "status": "DONE"})
        self.assertFalse(result["success"])
        self.assertTrue(result["changed"])
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(result["error"], "Nuk lejohet")

    async def test_strike_preserves_other_points(self):
        before = task()
        with patch.object(voice, "read_task", AsyncMock(return_value=(before, []))), patch.object(voice.tasks, "user_api", AsyncMock()) as request:
            await voice.execute_tool(USER, "set_task_points", {"task_id": TASK_ID, "expected_version": voice.task_detail(before, [])["expected_version"], "field": "description", "numbers": [2], "done": True})
        changed = request.await_args.kwargs["body"]["description"]
        self.assertEqual([p["done"] for p in voice.tasks.text_points(changed, "description")], [False, True])

    async def test_foreign_checklist_item_is_rejected_without_write(self):
        before = task()
        with patch.object(voice, "read_task", AsyncMock(return_value=(before, []))), patch.object(voice.tasks, "user_api", AsyncMock()) as request:
            with self.assertRaises(ValueError):
                await voice.execute_tool(USER, "set_checklist_item", {"task_id": TASK_ID, "expected_version": voice.task_detail(before, [])["expected_version"], "item_id": ITEM_ID, "done": True})
        request.assert_not_awaited()

    async def test_schedule_filters_owner_date_and_explicit_slot_override(self):
        rows = [
            {"id": TASK_ID, "title": "Moved to 11", "one_h_report_slot": "10:00"},
            {"id": ITEM_ID, "title": "Moved to 10", "one_h_report_slot": "11:00"},
        ]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(uuid.UUID(TASK_ID), "11:00"), (uuid.UUID(ITEM_ID), "10:00")])))
        with patch.object(voice.tasks, "user_api", AsyncMock(return_value=rows)) as request:
            result = await voice.execute_tool(USER, "list_my_schedule", {"day": "2026-10-19", "slot": "10:00", "include_done": False, "offset": 0}, db=db)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["tasks"][0]["id"], ITEM_ID)
        params = request.await_args.kwargs["params"]
        self.assertEqual(params["assigned_to"], str(USER.id))
        self.assertEqual(params["window_from"], "2026-10-19T00:00:00+02:00")
        self.assertIn(date(2026, 10, 19), db.execute.await_args.args[0].compile().params.values())

    async def test_null_override_removes_task_from_slot(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(uuid.UUID(TASK_ID), None)])))
        with patch.object(voice.tasks, "user_api", AsyncMock(return_value=[{**task(), "one_h_report_slot": "10:00"}])):
            result = await voice.execute_tool(USER, "list_my_schedule", {"day": "2026-10-19", "slot": "10:00", "include_done": False, "offset": 0}, db=db)
        self.assertEqual(result["tasks"], [])

    async def test_search_paginates_and_never_defaults_to_another_user(self):
        rows = [{"id": str(uuid.uuid4()), "title": str(i)} for i in range(11)]
        with patch.object(voice.tasks, "user_api", AsyncMock(return_value=rows)) as request:
            result = await voice.execute_tool(USER, "search_tasks", {"query": "raport", "mine": True, "include_done": False, "offset": 10})
        self.assertEqual(len(result["tasks"]), 10)
        self.assertEqual(result["next_offset"], 20)
        self.assertEqual(request.await_args.kwargs["params"]["assigned_to"], str(USER.id))


class VoiceRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(api.router)
        self.app.dependency_overrides[get_current_user] = lambda: USER
        self.app.dependency_overrides[get_db] = lambda: Mock()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_session_and_tools_require_authentication(self):
        self.app.dependency_overrides.pop(get_current_user)
        for path, payload in [("/session", {"sdp": "a" * 20}), ("/tools/search_tasks", {})]:
            response = await self.client.post(path, json=payload)
            self.assertEqual(response.status_code, 401)

    async def test_unknown_tools_and_extra_arguments_are_rejected(self):
        for path, payload in [("delete_task", {}), ("search_tasks", {"query": "a", "mine": True, "include_done": False, "offset": 0, "user_id": "other"})]:
            result = await self.client.post("/tools/" + path, json=payload)
            self.assertEqual(result.status_code, 422)

    async def test_provider_credentials_stay_server_side(self):
        response = httpx.Response(201, text="v=0\nsdp-answer")
        mocked = AsyncMock()
        mocked.__aenter__.return_value.post.return_value = response
        with patch.object(api.settings, "OPENAI_API_KEY", "secret-test-key"), patch.object(api.httpx, "AsyncClient", return_value=mocked):
            result = await api.create_session(api.SessionRequest(sdp="v=0\nsdp-offer"), USER)
        self.assertEqual(result.body, b"v=0\nsdp-answer")
        self.assertEqual(result.headers["cache-control"], "no-store")
        payload = mocked.__aenter__.return_value.post.call_args.kwargs
        self.assertEqual(payload["headers"]["Authorization"], "Bearer secret-test-key")
        self.assertNotIn(str(USER.id), payload["headers"]["OpenAI-Safety-Identifier"])

    async def test_provider_error_does_not_expose_credentials(self):
        mocked = AsyncMock()
        mocked.__aenter__.return_value.post.return_value = httpx.Response(401, text="secret-test-key")
        with patch.object(api.settings, "OPENAI_API_KEY", "secret-test-key"), patch.object(api.httpx, "AsyncClient", return_value=mocked):
            with self.assertRaises(HTTPException) as error:
                await api.create_session(api.SessionRequest(sdp="v=0\nsdp-offer"), USER)
        self.assertNotIn("secret-test-key", error.exception.detail)

    async def test_notes_session_exposes_only_editor_tools_and_preserves_the_default_task_mode(self):
        import json
        mocked = AsyncMock()
        mocked.__aenter__.return_value.post.return_value = httpx.Response(201, text="v=0\nsdp-answer")
        with patch.object(api.settings, "OPENAI_API_KEY", "secret-test-key"), patch.object(api.httpx, "AsyncClient", return_value=mocked):
            await api.create_session(api.SessionRequest(sdp="v=0\nsdp-offer", mode="px_notes"), USER)
        config = json.loads(mocked.__aenter__.return_value.post.call_args.kwargs["files"]["session"][1])
        names = {tool["name"] for tool in config["tools"]}
        self.assertIn("notes_edit", names)
        self.assertIn("notes_save", names)
        self.assertNotIn("set_task_status", names)
        self.assertIn("set_task_status", {tool["name"] for tool in voice.session_config(USER)["tools"]})


if __name__ == "__main__":
    unittest.main()
