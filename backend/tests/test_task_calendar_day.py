from datetime import date, datetime

import pytest

from app.services.primeflow_report import _task_date, task_calendar_day
from app.services.tomorrow_print_report import _task_due_day, _task_start_day


@pytest.mark.parametrize("raw, expected", [
    ("2026-10-21T22:00:00+00:00", date(2026, 10, 22)),
    ("2026-10-21T22:00:00Z", date(2026, 10, 22)),
    ("2026-10-22T00:00:00+02:00", date(2026, 10, 22)),
    ("2026-12-21T23:00:00Z", date(2026, 12, 22)),
    (datetime.fromisoformat("2026-10-21T22:00:00+00:00"), date(2026, 10, 22)),
    (date(2026, 10, 22), date(2026, 10, 22)),
    ("2026-10-22", date(2026, 10, 22)),
    ("2026-10-22T00:00:00", date(2026, 10, 22)),
    (None, None),
    ("invalid", None),
])
def test_deadline_calendar_day_agrees_across_reports(raw, expected):
    assert task_calendar_day(raw) == expected
    assert _task_date({"due_date": raw}) == expected
    assert _task_due_day({"due_date": raw}) == expected
    assert _task_start_day({"start_date": raw}) == expected


def test_explicit_report_day_takes_precedence_over_deadline():
    assert _task_date({"report_date": "2026-10-21", "due_date": "2026-10-21T22:00:00Z"}) == date(2026, 10, 21)
