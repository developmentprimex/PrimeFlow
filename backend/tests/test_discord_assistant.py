import json
import os
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "test-discord-secret-not-for-production")

from fastapi import HTTPException
from app.services import discord_task_tools as tools
from app.api.routers import discord_assistant as api

NOW = datetime(2026, 10, 15, 9, 50, tzinfo=ZoneInfo("Europe/Budapest"))
TASK_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


def plan(*actions):
    return tools.TaskPlan(question=None, actions=[tools.ToolAction(tool=tool, arguments_json=json.dumps(args)) for tool, args in actions])


class ScheduleTests(unittest.TestCase):
    def test_exact_agreed_times(self):
        expected = {"09:50": "10:00", "10:50": "11:00", "11:40": "11:50", "11:50": "AM",
                    "14:10": "14:20", "15:50": "16:00", "16:05": "PM"}
        for at, bucket in expected.items():
            hour, minute = map(int, at.split(":"))
            self.assertEqual(tools.due_buckets(NOW.replace(hour=hour, minute=minute)), [bucket])

    def test_no_early_or_stale_or_weekend_reminders(self):
        for now in (NOW.replace(minute=49), NOW.replace(minute=55), NOW.replace(day=17)):
            self.assertEqual(tools.due_buckets(now), [])
        self.assertEqual(tools.due_buckets(NOW.replace(minute=54, second=59)), ["10:00"])

    def test_explicit_date_slot_overrides_base_slot(self):
        task = {"id": TASK_ID, "status": "IN_PROGRESS", "one_h_report_slot": "10:00", "finish_period": "PM"}
        self.assertFalse(tools.in_bucket(task, "10:00", {TASK_ID: "11:00"}))
        self.assertTrue(tools.in_bucket(task, "11:00", {TASK_ID: "11:00"}))
        self.assertTrue(tools.in_bucket(task, "PM", {}))
        self.assertFalse(tools.in_bucket({**task, "status": "DONE"}, "PM", {}))

    def test_dst_uses_local_wall_clock(self):
        winter = datetime(2026, 10, 26, 9, 50, tzinfo=NOW.tzinfo)
        self.assertNotEqual(winter.utcoffset(), NOW.utcoffset())
        self.assertEqual(tools.due_buckets(winter), ["10:00"])


class PointTests(unittest.TestCase):
    def test_multiple_strikes_and_existing_history_preserved(self):
        original = "Detajet\n1. [[done]]E para[[/done]] 08:00 14.10\n2. E dyta\n3. E treta"
        changed = tools.set_text_points(original, "description", [2, 3], True, NOW)
        points = tools.text_points(changed, "description")
        self.assertEqual([p["done"] for p in points], [True, True, True])
        self.assertIn("08:00 14.10", changed)
        self.assertIn("09:50 15.10", changed)
        self.assertTrue(changed.startswith("Detajet\n"))

    def test_reopen_only_selected_duplicate_bullet(self):
        original = "• Same\n• Same\n• Other"
        changed = tools.set_text_points(original, "description", [1, 2], True, NOW)
        reopened = tools.set_text_points(changed, "description", [2], False, NOW)
        self.assertEqual([p["done"] for p in tools.text_points(reopened, "description")], [True, False, False])
        self.assertEqual(reopened.count("09:50 15.10"), 1)

    def test_strike_is_idempotent_and_keeps_timestamp(self):
        changed = tools.set_text_points("1. A\n2. B", "title", [1], True, NOW)
        self.assertEqual(tools.set_text_points(changed, "title", [1], True, NOW.replace(hour=10)), changed)

    def test_wrapper_across_multiple_points_can_be_reopened(self):
        value = "[[done]]1. A\n2. B[[/done]]\n3. C"
        changed = tools.set_text_points(value, "description", [2], False, NOW)
        self.assertEqual([p["done"] for p in tools.text_points(changed, "description")], [True, False, False])

    def test_added_markers_survive_strike_and_reopen(self):
        original = "Heading\n1. [[added]]New item[[/added]]\n2. Other"
        changed = tools.set_text_points(original, "description", [1], True, NOW)
        reopened = tools.set_text_points(changed, "description", [1], False, NOW)
        self.assertEqual(reopened, original)

    def test_out_of_bounds_or_boolean_is_rejected(self):
        for numbers in ([0], [9], [True], []):
            with self.assertRaises(ValueError):
                tools.set_text_points("1. A", "description", numbers, True, NOW)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.task = {"id": TASK_ID, "title": "Test task", "description": "1. A\n2. B", "user_comment": "Earlier"}

    def compile(self, value, instruction="", **kwargs):
        return tools.compile_actions(value, self.task, [], [{"id": USER_ID}], instruction, NOW, **kwargs)

    def test_strike_and_progress_are_one_normal_task_patch(self):
        ops = self.compile(plan(("set_points", {"field": "description", "numbers": [1], "done": True}),
                                ("update_task", {"status": "IN_PROGRESS"})))
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["path"], f"/api/tasks/{TASK_ID}")
        self.assertEqual(ops[0]["body"]["status"], "IN_PROGRESS")
        self.assertIn("[[done]]", ops[0]["body"]["description"])

    def test_wfe_is_real_backend_status(self):
        ops = self.compile(plan(("update_task", {"status": "WAITING_CLIENT"})))
        self.assertEqual(ops[0]["body"]["status"], "WAITING_CLIENT")

    def test_px_strike_uses_manual_note_endpoint_for_both_sources_and_mirror_fields(self):
        for collection in ("ga-notes", "plan-notes"):
            for field in ("title", "description"):
                self.task.update(title="Heading\n1. A\n2. B", description="Heading\n1. A\n2. B",
                    _px_note={"collection": collection, "id": USER_ID, "content": "Heading\n1. A\n2. B"})
                ops = self.compile(plan(("set_points", {"field": field, "numbers": [2], "done": True})))
                self.assertEqual(len(ops), 1)
                self.assertEqual(ops[0]["path"], f"/api/{collection}/{USER_ID}")
                self.assertEqual([p["done"] for p in tools.text_points(ops[0]["body"]["content"], "title")], [False, True])
                self.assertIn("09:50 15.10", ops[0]["body"]["content"])

    def test_custom_description_still_uses_task_endpoint(self):
        self.task["_px_note"] = {"collection": "ga-notes", "id": USER_ID, "content": "Heading\n1. Note point"}
        ops = self.compile(plan(("set_points", {"field": "description", "numbers": [1], "done": True})))
        self.assertEqual(ops[0]["path"], f"/api/tasks/{TASK_ID}")
        self.assertNotIn("content", ops[0]["body"])

    def test_full_source_note_is_used_when_task_title_is_old(self):
        self.task["_px_note"] = {"collection": "ga-notes", "id": USER_ID, "content": "Heading\n1. Source A\n2. Source B"}
        self.assertEqual(tools.point_text(self.task, "title"), self.task["_px_note"]["content"])
        ops = self.compile(plan(("set_points", {"field": "title", "numbers": [2], "done": True})))
        self.assertIn("Source B[[/done]]", ops[0]["body"]["content"])

    def test_source_note_change_invalidates_displayed_fingerprint(self):
        first = {**self.task, "_px_note": {"content": "1. A"}}
        second = {**self.task, "_px_note": {"content": "1. Changed"}}
        self.assertNotEqual(tools.fingerprint(first), tools.fingerprint(second))

    def test_comment_is_appended_before_completion(self):
        ops = self.compile(plan(("update_task", {"status": "DONE"}), ("comment", {"comment": "Finished"})))
        self.assertTrue(ops[0]["path"].endswith("/comment"))
        self.assertEqual(ops[0]["body"]["comment"], "Earlier\nFinished")

    def test_unknown_fields_and_users_and_steps_are_rejected(self):
        for value in (plan(("update_task", {"completion_override_reason": "bypass"})),
                      plan(("update_task", {"assigned_to": str(uuid.uuid4())})),
                      plan(("checklist_item", {"item_id": str(uuid.uuid4()), "is_checked": True}))):
            with self.assertRaises(ValueError):
                self.compile(value)

    def test_text_overwrite_cannot_conflict_with_strike(self):
        with self.assertRaises(ValueError):
            self.compile(plan(("update_task", {"description": "new"}), ("set_points", {"field": "description", "numbers": [1], "done": True})))

    def test_delete_cannot_be_inferred_from_close(self):
        with self.assertRaises(ValueError):
            self.compile(plan(("delete", {})), "Mbylle detyrën")
        self.assertEqual(self.compile(plan(("delete", {})), "Fshije detyrën")[0]["method"], "DELETE")
        with self.assertRaises(ValueError):
            self.compile(plan(("delete", {})), "Mos fshij detyrën")

    def test_remove_from_day_has_actual_backend_body_and_current_user(self):
        ops = self.compile(plan(("remove_from_day", {"day": "2026-10-15"})), "Hiqe nga dita", user_id=USER_ID)
        self.assertEqual(ops[0]["body"], {"day_date": "2026-10-15", "user_id": USER_ID, "time_slot": "ALL"})

    def test_invalid_later_action_prevents_whole_plan(self):
        with self.assertRaises(ValueError):
            self.compile(plan(("update_task", {"status": "DONE"}), ("slot", {"one_h_report_slot": "99:99"})))


class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def test_bridge_off_and_wrong_secret(self):
        with patch.object(api.settings, "DISCORD_ASSISTANT_ENABLED", False):
            with self.assertRaises(HTTPException) as error:
                api.require_bot("x" * 32)
            self.assertEqual(error.exception.status_code, 503)
        with patch.object(api.settings, "DISCORD_ASSISTANT_ENABLED", True), patch.object(api.settings, "DISCORD_GUILD_ID", "123"), patch.object(api.settings, "DISCORD_BRIDGE_SECRET", "x" * 32):
            with self.assertRaises(HTTPException) as error:
                api.require_bot("y" * 32)
            self.assertEqual(error.exception.status_code, 401)
            api.require_bot("x" * 32)

    async def test_wrong_channel_and_disabled_account_cannot_use_tools(self):
        actor = api.Actor(discord_user_id="12", guild_id="123", channel_id="44")
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock()), get=AsyncMock())
        with patch.object(api.settings, "DISCORD_GUILD_ID", "123"):
            db.execute.return_value.scalar_one_or_none.return_value = None
            with self.assertRaises(HTTPException):
                await api.identity(db, actor)
            db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(user_id=uuid.uuid4())
            db.get.return_value = SimpleNamespace(is_active=False)
            with self.assertRaises(HTTPException):
                await api.identity(db, actor)

    async def test_other_persons_task_rejected_before_api_call(self):
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(assigned_to=uuid.uuid4(), is_active=True)), execute=AsyncMock(return_value=Mock()))
        db.execute.return_value.scalar_one_or_none.return_value = None
        with patch.object(tools, "user_api", new_callable=AsyncMock) as request:
            with self.assertRaises(HTTPException):
                await api.owned_task(db, SimpleNamespace(id=uuid.uuid4()), uuid.uuid4())
            request.assert_not_called()

    async def test_duplicate_command_returns_recorded_result_without_tools(self):
        link = SimpleNamespace(id=uuid.uuid4())
        old = SimpleNamespace(link_id=link.id, result={"status": "DONE", "message": "Already applied"})
        db = SimpleNamespace(get=AsyncMock(return_value=old))
        command = api.Command(discord_user_id="12", guild_id="123", channel_id="44", request_id="555", instruction="Mbylle")
        with patch.object(api, "identity", new_callable=AsyncMock, return_value=(link, SimpleNamespace())):
            with patch.object(tools, "interpret", new_callable=AsyncMock) as ai:
                result = await api.command(command, db)
                self.assertEqual(result, old.result)
                ai.assert_not_called()


class CommandFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_px_note_strike_and_reopen_follow_real_manual_route_and_emit_events(self):
        from app.api.routers import ga_notes
        from app.schemas.ga_note import GaNoteUpdate

        original = "Heading\n1. [[added]]A[[/added]]\n2. B"
        for desired in (True, False):
            old = original if desired else tools.set_text_points(original, "title", [1], True, NOW)
            task = {"id": TASK_ID, "title": old, "description": old,
                    "_px_note": {"collection": "ga-notes", "id": USER_ID, "content": old}}
            operation = tools.compile_actions(plan(("set_points", {"field": "title", "numbers": [1], "done": desired})), task, [], [], "", NOW)[0]
            note = SimpleNamespace(id=uuid.UUID(USER_ID), content=old, knowledge_type=None)
            linked = SimpleNamespace(id=uuid.UUID(TASK_ID), title=old, description=old)
            first, second = Mock(), Mock()
            first.scalar_one_or_none.return_value = note
            second.scalars.return_value.all.return_value = [linked]
            db = SimpleNamespace(execute=AsyncMock(side_effect=[first, second]), add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
            with patch.object(ga_notes, "_note_out", return_value=note):
                await ga_notes.update_ga_note(note.id, GaNoteUpdate(**operation["body"]), db, SimpleNamespace(id=uuid.UUID(USER_ID)))
            self.assertEqual(note.content, linked.title)
            self.assertEqual(note.content, linked.description)
            self.assertEqual([p["done"] for p in tools.text_points(note.content, "title")], [desired, False])
            events = [call.args[0] for call in db.add.call_args_list]
            self.assertEqual(len(events), 2)
            self.assertEqual({event.field_name for event in events}, {"TITLE", "DESCRIPTION"})
            self.assertTrue(all(event.action == ("STRUCK" if desired else "UNSTRUCK") for event in events))
            db.commit.assert_awaited_once()

    async def test_snapshot_fetches_canonical_source_and_keeps_knowledge_titles_independent(self):
        task = {"id": TASK_ID, "title": "Old task copy", "ga_note_origin_id": USER_ID}
        with patch.object(tools, "user_api", new_callable=AsyncMock, return_value={"content": "1. Current PX text"}) as request:
            snapshot = await tools.with_source_note(SimpleNamespace(), task)
            self.assertEqual(request.call_args.args[2], f"/api/ga-notes/{USER_ID}")
            self.assertEqual(tools.point_text(snapshot, "title"), "1. Current PX text")
            self.assertNotIn("_px_note", task)
        with patch.object(tools, "user_api", new_callable=AsyncMock, return_value={"content": "Prompt", "knowledge_type": "PROMPT"}):
            snapshot = await tools.with_source_note(SimpleNamespace(), task)
            self.assertNotIn("_px_note", snapshot)

    async def test_direct_action_without_displayed_version_is_rejected(self):
        payload = api.Command(discord_user_id="12", guild_id="123", channel_id="44", request_id="999", instruction="WFE",
            task_id=uuid.UUID(TASK_ID), direct_actions=plan(("update_task", {"status": "WAITING_CLIENT"})).actions)
        with self.assertRaises(HTTPException) as error:
            await api.command(payload, None)
        self.assertEqual(error.exception.status_code, 422)

    async def run_command(self, parsed_plan, *, fail_comment=False, changed=False, displayed_changed=False, require_comment=False, direct=False):
        self.link = SimpleNamespace(id=uuid.uuid4(), selected_task_id=uuid.UUID(TASK_ID), pending_instruction=None, selected_at=None, selected_fingerprint=None)
        user = SimpleNamespace(id=uuid.UUID(USER_ID))
        self.action = None
        def add(action):
            self.action = action
        query_result = Mock()
        query_result.scalar_one_or_none.return_value = None
        db = SimpleNamespace(get=AsyncMock(return_value=None), add=add, commit=AsyncMock(), execute=AsyncMock(return_value=query_result))
        task = {"id": TASK_ID, "title": "Test task", "description": "1. A\n2. B", "status": "TODO", "user_comment": None}
        if displayed_changed:
            self.link.selected_fingerprint = tools.fingerprint({**task, "description": "1. Original"})
        self.requests = []
        async def request(user, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            if path == "/api/checklists":
                return []
            if path == "/api/users":
                return [{"id": USER_ID, "full_name": "Test User"}]
            if path.endswith("/comment") and fail_comment:
                raise HTTPException(403, "Comment refused")
            if method == "PATCH" and require_comment:
                raise HTTPException(409, {"code": "RLZ_TASK_COMMENT_REQUIRED", "message": "Shto komentin e rezultatit."})
            return task
        payload = api.Command(discord_user_id="12", guild_id="123", channel_id="44", request_id="999", instruction="Lëre në progres dhe shto koment")
        if direct:
            payload.task_id = uuid.UUID(TASK_ID)
            payload.expected_fingerprint = tools.fingerprint(task)[:16]
            payload.direct_actions = parsed_plan.actions
        owned = [task, {**task, "title": "Changed elsewhere"} if changed else task] + [task] * 20
        with patch.object(api, "identity", new_callable=AsyncMock, return_value=(self.link, user)), \
             patch.object(api, "daily_tasks", new_callable=AsyncMock, return_value=[task]), \
             patch.object(api, "owned_task", new_callable=AsyncMock, side_effect=owned), \
             patch.object(tools, "user_api", side_effect=request), \
             patch.object(tools, "interpret", new_callable=AsyncMock, return_value=parsed_plan) as interpret:
            result = await api.command(payload, db)
            if direct:
                interpret.assert_not_called()
            return result

    async def test_direct_buttons_skip_ai_but_use_task_api_and_audit(self):
        result = await self.run_command(plan(("update_task", {"status": "WAITING_CLIENT"})), direct=True)
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(self.action.result["operations"][0]["body"]["status"], "WAITING_CLIENT")

    async def test_direct_points_still_reject_changed_task(self):
        result = await self.run_command(plan(("set_points", {"field": "description", "numbers": [1, 2], "done": True})), direct=True, changed=True)
        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(any(method != "GET" for method, _, _ in self.requests))

    async def test_command_executes_normal_endpoint_and_records_actor_result(self):
        result = await self.run_command(plan(("set_points", {"field": "description", "numbers": [1], "done": True}), ("update_task", {"status": "IN_PROGRESS"})))
        writes = [call for call in self.requests if call[0] != "GET"]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], f"/api/tasks/{TASK_ID}")
        self.assertEqual(result["status"], "DONE")
        self.assertEqual(self.action.link_id, self.link.id)
        self.assertEqual(self.action.status, "DONE")
        self.assertEqual(len(self.action.result["operations"]), 1)

    async def test_clarification_does_not_write_and_keeps_request_context(self):
        result = await self.run_command(tools.TaskPlan(question="Cilat pika?", actions=[]))
        self.assertEqual(result["status"], "QUESTION")
        self.assertFalse(any(method != "GET" for method, _, _ in self.requests))
        self.assertIn("Cilat pika?", self.link.pending_instruction)

    async def test_stale_task_is_rejected_before_first_write(self):
        result = await self.run_command(plan(("update_task", {"status": "IN_PROGRESS"})), changed=True)
        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(any(method != "GET" for method, _, _ in self.requests))

    async def test_changed_points_after_display_are_rejected_before_ai(self):
        result = await self.run_command(plan(("set_points", {"field": "description", "numbers": [1], "done": True})), displayed_changed=True)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(self.requests, [])

    async def test_backend_request_for_comment_keeps_original_intent(self):
        result = await self.run_command(plan(("update_task", {"status": "DONE"})), require_comment=True)
        self.assertEqual(result["status"], "QUESTION")
        self.assertEqual(result["message"], "Shto komentin e rezultatit.")
        self.assertIn("Lëre në progres", self.link.pending_instruction)

    async def test_later_failure_reports_only_applied_operations(self):
        # Two checklist actions: the first succeeds, the second is refused.
        operations = [{"method": "PATCH", "path": f"/api/tasks/{TASK_ID}", "body": {"status": "IN_PROGRESS"}, "label": "Status updated"},
                      {"method": "PATCH", "path": f"/api/tasks/{TASK_ID}/comment", "body": {"comment": "Test"}, "label": "Comment updated"}]
        with patch.object(tools, "compile_actions", return_value=operations):
            result = await self.run_command(plan(("update_task", {"status": "IN_PROGRESS"})), fail_comment=True)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["applied"], ["Status updated"])
        self.assertEqual(self.action.status, "PARTIAL")


class MigrationTests(unittest.TestCase):
    def test_new_migration_extends_existing_head_and_models_match(self):
        import ast
        from pathlib import Path
        from app.models.discord_assistant import DiscordLink, DiscordLinkCode, DiscordReminder, DiscordAction
        versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
        revisions, referenced = set(), set()
        for file in versions.glob("*.py"):
            values = {}
            for node in ast.parse(file.read_text(encoding="utf-8-sig")).body:
                if isinstance(node, ast.Assign):
                    for name in node.targets:
                        if isinstance(name, ast.Name) and name.id in {"revision", "down_revision"}:
                            values[name.id] = ast.literal_eval(node.value)
            if values.get("revision"):
                revisions.add(values["revision"])
                down = values.get("down_revision")
                referenced.update(down if isinstance(down, tuple) else [down] if down else [])
        # Later features may extend the graph; Discord's revision must remain
        # present and there must still be exactly one unambiguous migration head.
        self.assertIn("0151_discord_meeting_alerts", revisions)
        self.assertIn("0152_discord_voice_meetings", revisions)
        self.assertEqual(len(revisions - referenced), 1)
        self.assertEqual(DiscordAction.__table__.c.id.type.length, 32)
        self.assertEqual(DiscordLink.__table__.c.channel_id.type.length, 32)
        self.assertIn("code_hash", DiscordLinkCode.__table__.c)
        self.assertIn("lease_until", DiscordReminder.__table__.c)


if __name__ == "__main__":
    unittest.main()
