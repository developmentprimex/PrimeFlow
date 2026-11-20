"""GA assistant agenda rules that need no database: windows, timezone, late days, To Do bodies."""
import os
import unittest
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.integrations import microsoft_todo as todo  # noqa: E402
from app.integrations import microsoft_todo as todo_mod  # noqa: E402
from app.services import ga_assistant as svc  # noqa: E402
from app.services.ga_identity import is_ga_user  # noqa: E402

TZ = ZoneInfo("Europe/Belgrade")


def item(kind="GA_TASK", day=date(2026, 11, 19), start=None, is_open=True, title="x", key=None, am_pm=None):
    return svc.AgendaItem(
        id=key or f"pf_task:{title}", item_key=key or f"pf_task:{title}", source="primeflow", kind=kind,
        title=title, day=day, start=start, is_open=is_open, am_pm=am_pm,
    )


class TaskDateRulesTests(unittest.TestCase):
    def test_plan_day_uses_local_timezone_not_utc(self) -> None:
        # 23:30 UTC on the 18th is already the 19th in Belgrade.
        task = SimpleNamespace(system_template_origin_id=None, status="TODO", completed_at=None,
                               due_date=datetime(2026, 11, 18, 23, 30, tzinfo=ZoneInfo("UTC")), start_date=None)
        self.assertEqual(svc.task_plan_day(task, TZ), date(2026, 11, 19))

    def test_done_system_task_keeps_original_planned_day(self) -> None:
        task = SimpleNamespace(
            system_template_origin_id="tpl", status="DONE", completed_at=datetime(2026, 11, 20, 9, tzinfo=TZ),
            original_due_date=datetime(2026, 11, 18, 9, tzinfo=TZ), origin_run_at=None, start_date=None,
            due_date=datetime(2026, 11, 20, 9, tzinfo=TZ),
        )
        self.assertEqual(svc.task_plan_day(task, TZ), date(2026, 11, 18))

    def test_due_time_ignores_date_only_placeholders(self) -> None:
        def at(h, m):
            return SimpleNamespace(due_date=datetime(2026, 11, 19, h, m, tzinfo=TZ))
        self.assertIsNone(svc.due_time_of(at(0, 0), TZ))
        self.assertIsNone(svc.due_time_of(at(23, 59), TZ))
        self.assertEqual(svc.due_time_of(at(9, 0), TZ), time(9, 0))

    def test_business_days_late_skip_weekend(self) -> None:
        # Friday 2026-11-13 -> Monday 2026-11-16 is one working day late.
        self.assertEqual(svc.business_days_late(date(2026, 11, 13), date(2026, 11, 16)), 1)
        self.assertIsNone(svc.business_days_late(date(2026, 11, 16), date(2026, 11, 16)))

    def test_f_marker_parsing_handles_two_symbols(self) -> None:
        self.assertEqual(svc.markers_of(SimpleNamespace(one_h_marker="M2,F")), ["M2", "F"])
        self.assertEqual(svc.markers_of(SimpleNamespace(one_h_marker=None)), [])


class SelectionTests(unittest.TestCase):
    def test_agenda_window_is_half_open_and_untimed_optional(self) -> None:
        at = lambda h, m=0: datetime(2026, 11, 19, h, m, tzinfo=TZ)  # noqa: E731
        items = [item(start=at(8), title="a"), item(start=at(9), title="b"), item(title="untimed"),
                 item(start=at(8, 30), is_open=False, title="done-but-timed")]
        names = [i.title for i in svc.select_agenda(items, at(8), at(9), include_untimed=False)]
        self.assertEqual(names, ["a", "done-but-timed"])
        names = [i.title for i in svc.select_agenda(items, at(8), at(9), include_untimed=True)]
        self.assertIn("untimed", names)
        self.assertNotIn("b", names)

    def test_window_ending_at_midnight_does_not_pull_next_day_untimed(self) -> None:
        items = [item(day=date(2026, 11, 20), title="tomorrow")]
        start = datetime(2026, 11, 19, 0, 0, tzinfo=TZ)
        end = datetime(2026, 11, 20, 0, 0, tzinfo=TZ)
        self.assertEqual(svc.select_agenda(items, start, end, include_untimed=True), [])

    def test_leftovers_oldest_first_and_meetings_only_today(self) -> None:
        as_of = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)
        items = [
            item(day=date(2026, 11, 19), start=datetime(2026, 11, 19, 10, tzinfo=TZ), title="today-earlier"),
            item(day=date(2026, 11, 19), start=datetime(2026, 11, 19, 14, tzinfo=TZ), title="today-later"),
            item(day=date(2026, 11, 17), title="two-days-ago"),
            item(day=date(2026, 11, 18), is_open=False, title="done"),
            item(kind="MEETING", day=date(2026, 11, 18), start=datetime(2026, 11, 18, 9, tzinfo=TZ), title="old-meeting"),
            item(kind="MEETING", day=date(2026, 11, 19), start=datetime(2026, 11, 19, 9, tzinfo=TZ), title="meeting-today"),
            item(kind="EVENT", day=date(2026, 11, 18), title="event"),
        ]
        result = svc.select_leftovers(items, as_of)
        self.assertEqual([i.title for i in result], ["two-days-ago", "meeting-today", "today-earlier"])
        self.assertEqual(result[0].days_late, 2)

    def test_untimed_today_only_open_untimed_tasks_and_reminders(self) -> None:
        items = [item(title="t"), item(kind="REMINDER", title="r"), item(kind="MEETING", title="m"),
                 item(start=datetime(2026, 11, 19, 9, tzinfo=TZ), title="timed"), item(is_open=False, title="closed")]
        self.assertEqual({i.title for i in svc.select_untimed(items, date(2026, 11, 19))}, {"t", "r"})

    def test_day_state_override_and_soft_removal(self) -> None:
        day = date(2026, 11, 19)
        timed = item(title="timed", start=datetime(2026, 11, 19, 9, tzinfo=TZ))
        cleared = item(title="cleared", start=datetime(2026, 11, 19, 9, tzinfo=TZ), am_pm="PM")
        removed = item(title="removed")
        moved = item(title="moved")
        meeting = item(kind="MEETING", title="meeting", key="pf_meeting:m@2026-11-19", start=datetime(2026, 11, 19, 9, tzinfo=TZ))
        states = {
            (moved.item_key, day): svc.DayState(time_override=True, time_value=time(11, 0)),
            (cleared.item_key, day): svc.DayState(time_override=True, time_value=None),
            (removed.item_key, day): svc.DayState(removed=True),
            (meeting.item_key, day): svc.DayState(time_override=True, time_value=time(15, 0)),
        }
        result = {i.title: i for i in svc.apply_day_states([timed, cleared, removed, moved, meeting], states, TZ)}
        self.assertNotIn("removed", result)
        self.assertEqual(result["moved"].start, datetime(2026, 11, 19, 11, tzinfo=TZ))
        self.assertEqual(result["moved"].time_basis, "assistant")
        self.assertIsNone(result["cleared"].start)
        self.assertEqual(result["cleared"].time_basis, "ampm")
        self.assertEqual(result["meeting"].start, datetime(2026, 11, 19, 9, tzinfo=TZ))  # calendar time wins


class TodoBodyTests(unittest.TestCase):
    def test_steps_round_trip_through_text_body(self) -> None:
        body = todo.join_body("Shënim", [todo.Step("Hapi 1", True), todo.Step("Hapi 2")])
        self.assertEqual(body, "Shënim\n\n☑ Hapi 1\n☐ Hapi 2")
        notes, steps = todo.split_body(body)
        self.assertEqual(notes, "Shënim")
        self.assertEqual([(s.text, s.done) for s in steps], [("Hapi 1", True), ("Hapi 2", False)])

    def test_scope_check(self) -> None:
        todo.ensure_todo_scope("openid https://graph.microsoft.com/Tasks.ReadWrite User.Read")
        with self.assertRaises(todo.TodoScopeMissing):
            todo.ensure_todo_scope("https://graph.microsoft.com/Calendars.ReadWrite")

    def test_todo_item_time_comes_from_reminder(self) -> None:
        raw = {
            "id": "T1", "title": "Thirr", "status": "notStarted", "isReminderOn": True,
            "dueDateTime": {"dateTime": "2026-11-19T00:00:00.0000000", "timeZone": "UTC"},
            "reminderDateTime": {"dateTime": "2026-11-19T10:00:00.0000000", "timeZone": "UTC"},
            "body": {"content": "shënim\n☐ hap", "contentType": "text"},
        }
        result = svc.todo_to_item(raw, {"id": "L1", "displayName": "Tasks"}, tz=TZ, parse_due_date=todo.parse_due_date,
                                  parse_graph_dt=todo.parse_graph_dt, split_body=todo.split_body)
        self.assertEqual(result.id, "todo:L1::T1")
        self.assertEqual(result.day, date(2026, 11, 19))
        self.assertEqual(result.start, datetime(2026, 11, 19, 11, 0, tzinfo=TZ))  # 10:00 UTC = 11:00 Belgrade
        self.assertEqual(result.time_basis, "reminder")
        self.assertEqual(result.comment, "shënim")
        raw["isReminderOn"] = False
        untimed = svc.todo_to_item(raw, {"id": "L1"}, tz=TZ, parse_due_date=todo.parse_due_date,
                                   parse_graph_dt=todo.parse_graph_dt, split_body=todo.split_body)
        self.assertIsNone(untimed.start)

    def test_due_and_reminder_payloads(self) -> None:
        self.assertEqual(todo.due_payload(date(2026, 11, 19)), {"dateTime": "2026-11-19T00:00:00", "timeZone": "UTC"})
        self.assertEqual(
            todo.graph_datetime(date(2026, 11, 19), time(11, 0), TZ), {"dateTime": "2026-11-19T10:00:00", "timeZone": "UTC"}
        )


class IphoneReminderTests(unittest.TestCase):
    """Real-world shapes of iPhone Reminders synced through Exchange into To Do."""

    def item(self, **todo):
        raw = {"id": "T", "title": "Kujtese", "status": "notStarted", **todo}
        return svc.todo_to_item(raw, {"id": "L", "displayName": "Reminders"}, tz=TZ, parse_due_date=todo_mod.parse_due_date,
                                parse_graph_dt=todo_mod.parse_graph_dt, split_body=todo_mod.split_body)

    def test_local_midnight_due_returned_in_utc_keeps_its_day(self) -> None:
        # 20 Nov 00:00 in Belgrade comes back as 19 Nov 23:00 UTC.
        due = {"dateTime": "2026-11-19T23:00:00.0000000", "timeZone": "UTC"}
        self.assertEqual(todo_mod.parse_due_date(due, TZ), date(2026, 11, 20))
        untimed = self.item(dueDateTime=due, isReminderOn=False)
        self.assertEqual(untimed.day, date(2026, 11, 20))
        self.assertIsNone(untimed.start)
        self.assertIsNone(untimed.time_basis)

    def test_windows_zone_names_are_resolved(self) -> None:
        due = {"dateTime": "2026-11-20T00:00:00.0000000", "timeZone": "W. Europe Standard Time"}
        self.assertEqual(todo_mod.parse_due_date(due, TZ), date(2026, 11, 20))
        at = todo_mod.parse_graph_dt({"dateTime": "2026-11-20T09:30:00", "timeZone": "Central Europe Standard Time"}, TZ)
        self.assertEqual(at, datetime(2026, 11, 20, 9, 30, tzinfo=TZ))

    def test_timed_reminder_starts_at_reminder_time(self) -> None:
        timed = self.item(
            dueDateTime={"dateTime": "2026-11-19T23:00:00.0000000", "timeZone": "UTC"},
            reminderDateTime={"dateTime": "2026-11-20T08:15:00.0000000", "timeZone": "UTC"}, isReminderOn=True,
        )
        self.assertEqual(timed.day, date(2026, 11, 20))
        self.assertEqual(timed.start, datetime(2026, 11, 20, 9, 15, tzinfo=TZ))
        self.assertEqual(timed.time_basis, "reminder")
        self.assertTrue(timed.id.startswith("todo:"))

    def test_reminder_without_due_date_uses_reminder_day(self) -> None:
        timed = self.item(reminderDateTime={"dateTime": "2026-11-20T15:00:00", "timeZone": "UTC"}, isReminderOn=True)
        self.assertEqual(timed.day, date(2026, 11, 20))
        self.assertEqual(timed.start.hour, 16)

    def test_completed_reminders_are_not_open_and_old_open_ones_are_leftovers(self) -> None:
        done = self.item(status="completed", dueDateTime={"dateTime": "2026-11-18T23:00:00", "timeZone": "UTC"})
        self.assertFalse(done.is_open)
        self.assertFalse(done.can_complete)
        late = self.item(dueDateTime={"dateTime": "2026-11-16T23:00:00", "timeZone": "UTC"})  # 17 Nov
        result = svc.select_leftovers([done, late], datetime(2026, 11, 20, 8, 0, tzinfo=TZ))
        self.assertEqual([i.id for i in result], [late.id])
        self.assertEqual(result[0].days_late, 3)
        self.assertEqual(svc.select_untimed([late], date(2026, 11, 20)), [])  # only on its own day

    def test_refresh_keeps_todo_scope_only_when_already_granted(self) -> None:
        from app.integrations import microsoft

        self.assertNotIn("Tasks", microsoft.refresh_scope_str("offline_access Calendars.ReadWrite"))
        self.assertIn("Tasks.ReadWrite", microsoft.refresh_scope_str(
            "https://graph.microsoft.com/Calendars.ReadWrite https://graph.microsoft.com/Tasks.ReadWrite"))
        self.assertEqual(microsoft.refresh_scope_str(None), microsoft.SCOPE_STR)


class TodoListChoiceTests(unittest.IsolatedAsyncioTestCase):
    """info@ has two lists called "Tasks": the empty default one and the one iPhone syncs into."""

    def client(self):
        from unittest.mock import AsyncMock

        c = todo_mod.TodoClient("token")
        lists = [
            {"id": "DEFAULT", "displayName": "Tasks", "wellknownListName": "defaultList"},
            {"id": "IPHONE", "displayName": "Tasks", "wellknownListName": "none"},
            {"id": "OTHER", "displayName": "Blerje", "wellknownListName": "none"},
        ]
        tasks = {
            "DEFAULT": [],
            "IPHONE": [{"id": "t1", "lastModifiedDateTime": "2026-11-20T07:01:00Z"}],
            "OTHER": [{"id": "t2", "lastModifiedDateTime": "2026-11-18T10:00:00Z"}],
        }
        c.lists = AsyncMock(return_value=lists)
        c.tasks = AsyncMock(side_effect=lambda list_id, include_completed: tasks[list_id])
        return c

    async def test_new_reminders_go_to_the_list_iphone_uses(self) -> None:
        self.assertEqual((await self.client().create_list(""))["id"], "IPHONE")

    async def test_duplicate_names_resolve_to_the_active_list(self) -> None:
        self.assertEqual((await self.client().resolve_list("Tasks"))["id"], "IPHONE")
        self.assertEqual((await self.client().resolve_list("Blerje"))["id"], "OTHER")
        self.assertEqual((await self.client().resolve_list(None))["id"], "DEFAULT")

    async def test_override_by_id_or_unique_name(self) -> None:
        self.assertEqual((await self.client().create_list("DEFAULT"))["id"], "DEFAULT")
        self.assertEqual((await self.client().create_list("Blerje"))["id"], "OTHER")
        with self.assertRaises(ValueError):
            await self.client().create_list("Tasks")  # ambiguous name: use the id


class MicrosoftScopeTests(unittest.TestCase):
    def test_connect_flow_is_unchanged_unless_todo_is_enabled(self) -> None:
        from unittest.mock import patch

        from app.config import settings
        from app.integrations import microsoft

        with patch.object(settings, "MS_TODO_ENABLED", False):
            self.assertEqual(microsoft.authorize_scope_str(), microsoft.SCOPE_STR)
            self.assertNotIn("Tasks.ReadWrite", microsoft.build_authorize_url("c", "https://x/cb", "s"))
        with patch.object(settings, "MS_TODO_ENABLED", True):
            self.assertIn("Tasks.ReadWrite", microsoft.authorize_scope_str())
        self.assertNotIn("Tasks", microsoft.SCOPE_STR)  # refreshes never ask for To Do


class GaIdentityTests(unittest.TestCase):
    def test_ga_identity_uses_settings_defaults(self) -> None:
        self.assertTrue(is_ga_user(SimpleNamespace(username="Gane.Arifaj", email=None)))
        self.assertTrue(is_ga_user(SimpleNamespace(username=None, email=" GA@primexeu.com ")))
        self.assertFalse(is_ga_user(SimpleNamespace(username="someone", email="someone@primexeu.com")))


if __name__ == "__main__":
    unittest.main()
