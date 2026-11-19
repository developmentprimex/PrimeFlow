"""GA assistant agenda rules that need no database: windows, timezone, late days, To Do bodies."""
import os
import unittest
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.integrations import microsoft_todo as todo  # noqa: E402
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


class GaIdentityTests(unittest.TestCase):
    def test_ga_identity_uses_settings_defaults(self) -> None:
        self.assertTrue(is_ga_user(SimpleNamespace(username="Gane.Arifaj", email=None)))
        self.assertTrue(is_ga_user(SimpleNamespace(username=None, email=" GA@primexeu.com ")))
        self.assertFalse(is_ga_user(SimpleNamespace(username="someone", email="someone@primexeu.com")))


if __name__ == "__main__":
    unittest.main()
