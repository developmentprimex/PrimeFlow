from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskUpdate
from app.services.task_pause import pause_until_on_day, update_pause_periods
from app.services.tomorrow_print_report import render_marked_tomorrow_tasks


def test_single_day_pause_expires_tomorrow():
    today = date(2026, 11, 25)
    periods = update_pause_periods(None, today, 1)

    assert pause_until_on_day(periods, date(2026, 11, 24)) is None
    assert pause_until_on_day(periods, today) == today
    assert pause_until_on_day(periods, date(2026, 11, 26)) is None


def test_changing_the_duration_preserves_prior_days():
    periods = update_pause_periods(None, date(2026, 11, 25), 4)
    updated = update_pause_periods(periods, date(2026, 11, 26), 2)

    for day in (25, 26, 27):
        assert pause_until_on_day(updated, date(2026, 11, day)) is not None
    assert pause_until_on_day(updated, date(2026, 11, 28)) is None


def test_resuming_early_and_pausing_again_keeps_history():
    periods = update_pause_periods(None, date(2026, 11, 25), 4)
    resumed = update_pause_periods(periods, date(2026, 11, 26), None)
    restarted = update_pause_periods(resumed, date(2026, 11, 28), 2)

    assert pause_until_on_day(restarted, date(2026, 11, 25)) == date(2026, 11, 25)
    assert pause_until_on_day(restarted, date(2026, 11, 26)) is None
    assert pause_until_on_day(restarted, date(2026, 11, 27)) is None
    assert pause_until_on_day(restarted, date(2026, 11, 28)) == date(2026, 11, 29)


def test_pause_update_is_independent_of_status_and_distinguishes_clear():
    paused = TaskUpdate(pause_days=1)
    cleared = TaskUpdate(pause_days=None)

    assert paused.status is None
    assert cleared.model_fields_set == {"pause_days"}
    assert TaskUpdate().model_fields_set == set()
    for value in (0, -1, 366, 1.5, True):
        with pytest.raises(ValidationError):
            TaskUpdate(pause_days=value)


def test_print_marks_only_the_paused_day_and_keeps_the_work_status():
    common_task = {
        "task_id": "task-1",
        "title": "Test task",
        "person": "GA",
        "status": "IN_PROGRESS",
        "one_h_report_slot": "10:00",
        "one_h_marker": "FLAG",
    }
    payload = {"items": {"oneH": [
        {**common_task, "date": "2026-11-25", "is_paused": True},
        {**common_task, "date": "2026-11-26", "is_paused": False},
    ]}}

    paused, _ = render_marked_tomorrow_tasks(payload, date(2026, 11, 25))
    resumed, _ = render_marked_tomorrow_tasks(payload, date(2026, 11, 26))

    assert "IN_PROGRESS" in paused and "IN_PROGRESS" in resumed
    assert "[Pauzë]" in paused
    assert "[Pauzë]" not in resumed
