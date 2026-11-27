import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.api.routers import today_print_report as routes
from app.services import today_print_plan


DAY = date(2026, 11, 30)


def item(identity, *, slot="10:00", person="Arta", status="TODO"):
    return {
        "task_id": identity, "title": "Katalogu", "date": DAY.isoformat(),
        "one_h_report_slot": slot, "assignees": [person], "status": status,
        "completed_at": f"{DAY}T10:00:00+01:00" if status == "DONE" else None,
    }


class PrintPlanTests(unittest.TestCase):
    def test_friday_boundary_saves_mondays_plan(self):
        tz = ZoneInfo("Europe/Tirane")
        friday = datetime(2026, 11, 27, 16, 59, 59, tzinfo=tz)
        self.assertEqual(today_print_plan.capture_target(friday), DAY)
        self.assertIsNone(today_print_plan.capture_target(friday.replace(hour=17, minute=0, second=0)))
        self.assertIsNone(today_print_plan.capture_target(friday.replace(day=28)))

    def test_uses_task_id_to_compare_same_title_and_excludes_done_tasks(self):
        planned = today_print_plan.report_tasks({"items": {"oneH": [
            item("moved"), item("removed"), item("done"), item("shifted"), item("same"),
        ]}}, DAY)
        actual = today_print_plan.report_tasks({"items": {"oneH": [
            item("moved", slot="14:20", person="Besnik"), item("added"),
            item("done", slot="16:00", status="DONE"), item("added-done", status="DONE"), item("same"),
            dict(item("added-done-flag"), isDone=True),
        ]}}, DAY, include_completed=True)
        changes = today_print_plan.compare_tasks(planned, actual, {
            "shifted": {"kind": "rescheduled", "date": "2026-12-01"},
        })
        self.assertEqual({row["task_id"]: row["kind"] for row in changes}, {
            "moved": "changed", "removed": "missing",
            "shifted": "rescheduled", "added": "added",
        })
        moved = next(row for row in changes if row["task_id"] == "moved")
        self.assertEqual((moved["before"]["slot"], moved["after"]["slot"]), ("10:00", "14:20"))
        self.assertEqual((moved["before"]["assignees"], moved["after"]["assignees"]), (["Arta"], ["Besnik"]))

    def test_start_and_due_dates_use_report_days_and_require_saved_values(self):
        planned = today_print_plan.report_tasks({"items": {"oneH": [
            dict(item("dates"), start_date=None, due_date="2026-11-30T23:30:00Z"),
            item("legacy"),
        ]}}, DAY)
        actual = today_print_plan.report_tasks({"items": {"oneH": [
            dict(item("dates"), start_date="2026-11-30", due_date="2026-12-02"),
            dict(item("legacy"), due_date="2026-12-02"),
        ]}}, DAY)
        changes = today_print_plan.compare_tasks(planned, actual, {})
        self.assertEqual([(row["task_id"], row["kind"]) for row in changes], [("dates", "changed")])
        self.assertIsNone(changes[0]["before"]["start_date"])
        self.assertEqual(changes[0]["before"]["due_date"], "2026-12-01")
        self.assertEqual(changes[0]["after"]["start_date"], "2026-11-30")
        self.assertEqual(changes[0]["after"]["due_date"], "2026-12-02")


class PrintPlanIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_absent_task_marked_done_is_excluded_regardless_of_its_completion_day(self):
        task_id = uuid4()
        plan = SimpleNamespace(report_payload={"saved_at": "2026-11-27T17:00:00+01:00", "tasks": {str(task_id): {}}})
        task = SimpleNamespace(id=task_id, status="DONE", completed_at=datetime(2026, 11, 28))
        db = AsyncMock()
        db.execute.return_value.scalars = MagicMock(return_value=[task])
        comparison = await today_print_plan.compare_plan(db, DAY, plan, {})
        self.assertEqual(comparison["changes"], [])

    async def test_archived_reschedule_recovers_due_date_from_audit_window(self):
        task_id = uuid4()
        start = datetime.fromisoformat("2026-11-27T16:59:59+01:00")
        cutoff = datetime.fromisoformat("2026-11-30T15:59:59+01:00")
        row = {"task_id": str(task_id), "kind": "rescheduled", "date": "2026-12-02", "before": {}, "after": None}
        expected = {"saved_at": "2026-11-27T17:00:00+01:00", "changes": [row]}
        plan = SimpleNamespace(report_payload={"saved_at": expected["saved_at"], "source_captured_at": start.isoformat()})
        archived = SimpleNamespace(report_payload={"plan_comparison": expected, "source_captured_at": cutoff.isoformat()})
        events = [SimpleNamespace(entity_id=task_id, action="task.due_date_changed",
                                  before={"value": old}, after={"value": new})
                  for old, new in [("2026-11-30", "2026-12-01"), ("2026-12-01", "2026-12-02")]]
        db = AsyncMock()
        db.execute.return_value.scalars = MagicMock(return_value=events)
        with patch.object(routes, "local_now", return_value=datetime(2026, 12, 1)), \
             patch.object(routes, "is_closed", return_value=True), \
             patch.object(routes, "get_one_h_print_snapshot", new=AsyncMock(side_effect=[plan, archived])):
            result = await routes.get_plan_comparison(DAY, db, None)
        comparison_row = result["changes"][0]
        self.assertEqual(comparison_row["before"], {"due_date": "2026-11-30"})
        self.assertEqual(comparison_row["current_dates"], {"due_date": "2026-12-02"})
        self.assertEqual(row["before"], {})
        self.assertNotIn("current_dates", row)
        query = db.execute.await_args.args[0].compile()
        self.assertIn("audit_logs.created_at >", str(query))
        self.assertIn("audit_logs.created_at <=", str(query))
        self.assertIn(start, query.params.values())
        self.assertIn(cutoff, query.params.values())

    async def test_rescheduled_task_preserves_new_dates_outside_the_report_day(self):
        task_id = uuid4()
        plan = SimpleNamespace(report_payload={"saved_at": "2026-11-27T17:00:00+01:00", "tasks": {
            str(task_id): {"start_date": "2026-11-30", "due_date": "2026-11-30"},
        }})
        task = SimpleNamespace(id=task_id, status="IN_PROGRESS", phase=None,
                               start_date=datetime(2026, 12, 1), due_date=datetime(2026, 12, 2))
        db = AsyncMock()
        db.execute.return_value.scalars = MagicMock(return_value=[task])
        comparison = await today_print_plan.compare_plan(db, DAY, plan, {})
        self.assertEqual(comparison["changes"][0]["date"], "2026-12-01")
        self.assertEqual(comparison["changes"][0]["current_status"], "IN_PROGRESS")
        self.assertEqual(comparison["changes"][0]["current_dates"], {"start_date": "2026-12-01", "due_date": "2026-12-02"})

    async def test_capture_persists_monday_under_its_target_date_without_overwriting(self):
        friday = datetime(2026, 11, 27, 16, 59, 59, tzinfo=ZoneInfo("Europe/Tirane"))
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.return_value.scalar = MagicMock(return_value=True)
        context = MagicMock()
        context.__aenter__.return_value = db
        with patch.object(today_print_plan, "SessionLocal", return_value=context), \
             patch.object(today_print_plan, "datetime", wraps=datetime) as clock, \
             patch.object(today_print_plan, "get_one_h_print_snapshot", new=AsyncMock(
                 side_effect=lambda *_: db.add.call_args.args[0] if db.add.called else None,
             )), patch("app.api.routers.common_view.load_report_common_view_with_previous_week", new=AsyncMock(
                 return_value={"items": {"oneH": [item("original")]}},
             )) as load:
            clock.now.return_value = friday
            self.assertTrue(await today_print_plan.capture_tomorrow_plan(friday))
            self.assertFalse(await today_print_plan.capture_tomorrow_plan(friday))
        load.assert_awaited_once_with(db, DAY)
        db.commit.assert_awaited_once()
        row = db.add.call_args.args[0]
        self.assertEqual((row.report_date, row.target_date), (DAY, DAY))
        self.assertEqual(row.report_payload["saved_at"], "2026-11-27T17:00:00+01:00")
        self.assertEqual(list(row.report_payload["tasks"]), ["original"])

    async def test_archived_comparison_uses_the_result_captured_at_16_without_reading_live_tasks(self):
        plan = SimpleNamespace(report_payload={"saved_at": "2026-11-27T17:00:00+01:00"})
        expected = {**plan.report_payload, "changes": [{"task_id": "moved", "kind": "changed"}]}
        archived = SimpleNamespace(report_payload={"plan_comparison": expected})
        with patch.object(routes, "local_now", return_value=datetime(2026, 12, 1)), \
             patch.object(routes, "is_closed", return_value=True), \
             patch.object(routes, "get_one_h_print_snapshot", new=AsyncMock(side_effect=[plan, archived])), \
             patch.object(routes, "compare_plan", new=AsyncMock()) as live:
            result = await routes.get_plan_comparison(DAY, AsyncMock(), None)
        live.assert_not_awaited()
        self.assertEqual(result, {**expected, "status": "ready", "report_date": DAY.isoformat(), "is_frozen": True})
