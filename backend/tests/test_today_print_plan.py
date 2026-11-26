import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
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

    def test_uses_task_id_to_compare_same_title_and_counts_completion_separately(self):
        planned = today_print_plan.report_tasks({"items": {"oneH": [
            item("moved"), item("removed"), item("done"), item("shifted"), item("same"),
        ]}}, DAY)
        actual = today_print_plan.report_tasks({"items": {"oneH": [
            item("moved", slot="14:20", person="Besnik"), item("added"),
            item("done", status="DONE"), item("same"),
        ]}}, DAY, include_completed=True)
        changes = today_print_plan.compare_tasks(planned, actual, {
            "shifted": {"kind": "rescheduled", "date": "2026-12-01"},
        })
        self.assertEqual({row["task_id"]: row["kind"] for row in changes}, {
            "moved": "changed", "removed": "missing", "done": "completed",
            "shifted": "rescheduled", "added": "added",
        })
        moved = next(row for row in changes if row["task_id"] == "moved")
        self.assertEqual((moved["before"]["slot"], moved["after"]["slot"]), ("10:00", "14:20"))
        self.assertEqual((moved["before"]["assignees"], moved["after"]["assignees"]), (["Arta"], ["Besnik"]))


class PrintPlanIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
