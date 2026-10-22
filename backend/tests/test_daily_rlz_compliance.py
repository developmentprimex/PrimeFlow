import asyncio
from datetime import date, datetime
import uuid
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.services.daily_rlz_compliance import (
    REASON_LABELS, is_closable_day, is_editable_day, next_working_day, relevant_tasks,
    task_issue_codes,
)
from app.services.daily_rlz_control_delivery import render_html, render_plain, subject_for
from app.api.routers.reports import _daily_rlz_state_out


DAY = date(2026, 8, 12)


@pytest.mark.parametrize(
    "status,reason,comment,due,is_1h,slot,expected",
    [
        ("TODO", None, None, date(2026, 8, 13), False, None, ["REASON_MISSING", "COMMENT_MISSING"]),
        ("IN_PROGRESS", None, None, date(2026, 8, 13), False, None, []),
        ("TODO", "OTHER", "Shpjegim", DAY, False, None, ["DUE_DATE_NOT_MOVED"]),
        ("IN_PROGRESS", "WAITING_CLIENT", None, date(2026, 8, 13), False, None, []),
        ("TODO", "OTHER", "Shpjegim", date(2026, 8, 13), True, None, ["ONE_H_SLOT_MISSING"]),
        ("TODO", "OTHER", "Shpjegim", date(2026, 8, 13), True, "10:00", []),
        ("TODO", "OTHER", "Shpjegim", date(2026, 8, 13), False, None, []),
        ("TODO", "OTHER", None, date(2026, 8, 13), False, None, ["COMMENT_MISSING"]),
        ("DONE", None, None, DAY, True, None, []),
        ("WAITING_CONFIRMATION", None, None, DAY, True, None, []),
        ("TODO", "OTHER", "Shpjegim", date(2026, 8, 11), False, None, ["DUE_DATE_NOT_MOVED"]),
    ],
)
def test_daily_rlz_task_rules(status, reason, comment, due, is_1h, slot, expected):
    assert task_issue_codes(status=status, reason_code=reason, due_date=due,
                            requires_one_h_slot=is_1h, one_h_report_slot=slot,
                            comment=comment, day=DAY) == expected


def test_friday_moves_to_monday():
    assert next_working_day(date(2026, 8, 14)) == date(2026, 8, 17)
    assert task_issue_codes(status="TODO", reason_code="OTHER", due_date=date(2026, 8, 17),
                            requires_one_h_slot=False, one_h_report_slot=None, comment="Shpjegim",
                            day=date(2026, 8, 14)) == []


def test_reason_codes_are_stable_and_complete():
    assert len(REASON_LABELS) == 10
    assert REASON_LABELS["WAITING_CLIENT"] == "Në pritje të klientit"


def test_generic_task_comment_is_not_daily_rlz_evidence():
    state = SimpleNamespace(reason_code=None, comment=None, updated_at=None)
    result = _daily_rlz_state_out(state, DAY, "old generic comment")
    assert result.comment is None


def test_daily_editing_has_no_cutoff_for_today_and_past_workdays():
    tz = ZoneInfo("Europe/Tirane")
    assert is_editable_day(DAY, datetime(2026, 8, 12, 16, 59, tzinfo=tz))
    assert is_editable_day(DAY, datetime(2026, 8, 12, 17, 0, tzinfo=tz))
    assert is_editable_day(DAY, datetime(2026, 8, 13, 9, 0, tzinfo=tz))
    assert not is_editable_day(date(2026, 8, 13), datetime(2026, 8, 12, 18, 0, tzinfo=tz))


def test_close_window_opens_when_slots_roll_over_at_1530():
    tz = ZoneInfo("Europe/Tirane")
    assert not is_closable_day(DAY, datetime(2026, 8, 12, 15, 29, 59, tzinfo=tz))
    assert is_closable_day(DAY, datetime(2026, 8, 12, 15, 30, tzinfo=tz))
    assert is_closable_day(DAY, datetime(2026, 8, 12, 16, 59, 59, tzinfo=tz))
    assert is_closable_day(DAY, datetime(2026, 8, 12, 17, 0, tzinfo=tz))
    assert is_closable_day(DAY, datetime(2026, 8, 12, 23, 59, tzinfo=tz))
    assert is_closable_day(DAY, datetime(2026, 8, 13, 9, 0, tzinfo=tz))


class _EmptyScalars:
    def all(self):
        return []


class _CaptureResult:
    def scalars(self):
        return _EmptyScalars()


class _CaptureDb:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return _CaptureResult()


def test_question_generated_tasks_are_excluded_from_rlz_membership():
    db = _CaptureDb()

    asyncio.run(relevant_tasks(db, user_id=uuid.uuid4(), day=DAY))

    sql = str(db.statement)
    assert "tasks.question_origin_id IS NULL" in " ".join(str(item) for item in getattr(db, "statements", [sql]))
    assert "tasks.question_batch_date IS NULL" in sql


def test_all_good_report_is_still_rendered():
    report = {"day": DAY.isoformat(), "all_good": True, "people": [], "summary": {
        "departments_checked": 5, "employees_checked": 12, "employees_not_saved": 0,
        "employees_stale": 0, "tasks_missing_reason": 0,
        "tasks_deadline_not_moved": 0, "tasks_missing_slot": 0,
    }}
    assert "Kontrolli ditor RLZ përfundoi pa probleme." in render_plain(report)


def test_control_email_contains_task_evidence():
    report = {"day": DAY.isoformat(), "all_good": False, "summary": {
        "departments_checked": 1, "employees_checked": 1, "employees_not_saved": 1,
        "employees_stale": 0, "tasks_missing_reason": 1,
        "tasks_deadline_not_moved": 1, "tasks_missing_slot": 0,
    }, "people": [{"department": "Development", "employee": "Elsa", "rlz_close_state": {"status": "NOT_SAVED"},
        "blockers": [{"title": "Task\nKy shënim i gjatë nuk duhet të shfaqet", "status": "TODO", "due_date": DAY.isoformat(),
                      "one_h_report_slot": None, "reason_label": None, "comment": None,
                      "issues": [{"code": "REASON_MISSING", "message": "Mungon arsyeja"}]}]}]}
    body = render_plain(report)
    assert "Development" in body and "Deadline: 2026-08-12" in body and "Mungon arsyeja" in body


def test_control_html_is_colored_and_explains_why_rlz_was_not_saved():
    report = {"day": DAY.isoformat(), "all_good": False, "summary": {
        "departments_checked": 1, "employees_checked": 1, "employees_not_saved": 1,
        "employees_stale": 0, "tasks_missing_reason": 1,
        "tasks_deadline_not_moved": 1, "tasks_missing_slot": 0,
    }, "people": [{"department": "Development", "employee": "Elsa",
        "rlz_close_state": {"status": "NOT_SAVED"},
        "blockers": [{"title": "Task", "status": "TODO", "due_date": DAY.isoformat(),
                      "one_h_report_slot": None, "reason_label": None, "comment": None,
                      "issues": [{"code": "REASON_MISSING", "message": "Mungon arsyeja"}]}]}]}

    rendered = render_html(report)

    assert 'bgcolor="#2563eb"' in rendered
    assert "Dita është ende e hapur." in rendered
    assert "ÇFARË KA MBETUR" in rendered
    assert "Mungon arsyeja" in rendered
    assert "Empty" in rendered
    assert 'bgcolor="#f9a8d4"' in rendered
    assert "Ky shënim i gjatë nuk duhet të shfaqet" not in rendered


def test_control_html_colors_in_progress_yellow():
    report = {"day": DAY.isoformat(), "all_good": False, "summary": {
        "departments_checked": 1, "employees_checked": 1, "employees_not_saved": 1,
        "employees_stale": 0, "tasks_missing_reason": 0,
        "tasks_deadline_not_moved": 0, "tasks_missing_slot": 1,
    }, "people": [{"department": "Development", "employee": "Elsa",
        "rlz_close_state": {"status": "NOT_SAVED"},
        "blockers": [{"title": "Task", "status": "IN_PROGRESS", "due_date": "2026-08-13",
                      "one_h_report_slot": None, "reason_label": "Tjetër", "comment": None,
                      "issues": [{"code": "ONE_H_SLOT_MISSING", "message": "Mungon 1H sloti"}]}]}]}

    assert 'bgcolor="#ffff00"' in render_html(report)


def test_control_subject_uses_configured_schedule_time():
    assert subject_for(DAY, "15:30").endswith("15:30")
