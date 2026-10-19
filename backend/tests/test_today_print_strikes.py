import asyncio
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.primeflow_report import report_timezone
from app.services.task_strike_events import count_struck_points_for_interval, point_key
from app.services.today_print_strikes import payload_task_ids, task_strike_summary, with_report_strikes


DAY = date(2026, 10, 19)


def clock(hour, minute=0, *, day=19):
    return datetime(2026, 10, day, hour, minute, tzinfo=report_timezone())


def event(text, hour, minute=0, *, field="DESCRIPTION", action="STRUCK", day=19):
    return SimpleNamespace(id=uuid.uuid4(), point_key=point_key(text, field_name=field),
                           point_text=text, field_name=field, action=action, occurred_at=clock(hour, minute, day=day))


def count(text, events, start=clock(10), end=clock(11), field="DESCRIPTION"):
    return count_struck_points_for_interval(text, events, interval_start=start, interval_end=end, field_name=field)


def test_interval_count_excludes_previous_strikes_and_uses_report_boundaries():
    text = "[[done]]1. Earlier[[/done]]\n[[done]]2. At start[[/done]]\n[[done]]3. In interval[[/done]]\n[[done]]4. At end[[/done]]"
    events = [event("1. Earlier", 9, 30), event("2. At start", 10), event("3. In interval", 10, 30), event("4. At end", 11)]
    assert count(text, events) == 2
    assert count(text, events, start=clock(8), end=clock(10)) == 2


def test_reopening_and_restriking_count_a_point_once_and_do_not_count_open_points():
    events = [event("1. Work", 10, 10), event("1. Work", 10, 20, action="REOPENED"), event("1. Work", 10, 30)]
    assert count("[[done]]1. Work[[/done]]", events) == 1
    assert count("1. Work", events) == 0
    assert count("[[done]]1. Work[[/done]]", events[:2]) == 0


def test_legacy_timestamps_and_field_identity_match_hourly_reports():
    assert count("[[done]]1. Work[[/done]] 10:30 19.10", []) == 1
    assert count("[[done]]1. Work[[/done]] 10:30 18.10", []) == 0
    assert count("[[done]]1. Work[[/done]]", []) == 0
    assert count("[[done]]1. Work[[/done]]", [event("1. Work", 10, 30, field="TITLE")]) == 0
    assert count("Heading\n[[done]]1. Work[[/done]]", [event("1. Work", 10, 30, field="TITLE")], field="TITLE") == 1


def test_summary_uses_authoritative_note_text_and_separates_each_slot_and_task():
    task_id, empty_id = uuid.uuid4(), uuid.uuid4()
    title = "Note heading\n[[done]]1. Note point[[/done]]"
    description = "[[done]]1. Description point[[/done]]"
    rows = [(task_id, "Stale title", description, title, None, event("1. Note point", 9, 30, field="TITLE")),
            (task_id, "Stale title", description, title, None, event("1. Description point", 10, 30)),
            (empty_id, "Other task", "1. Open", None, None, None)]
    db = AsyncMock()
    db.execute.return_value = MagicMock(all=lambda: rows)
    summary = asyncio.run(task_strike_summary(db, DAY, {task_id, empty_id}, now=clock(10, 45)))
    assert summary["active_slot"] == "10:00"
    assert summary["active_interval"] == {"start": "08:00", "end": "10:00"}
    assert summary["intervals"]["10:00"] == {"start": "08:00", "end": "10:00"}
    assert summary["tasks"][str(task_id)] == {"10:00": 1}
    assert all(value == 0 for value in summary["tasks"][str(empty_id)].values())
    db.execute.assert_awaited_once()
    query = db.execute.await_args.args[0]
    assert clock(10) in query.compile().params.values()
    assert clock(10, 45) not in query.compile().params.values()


def test_payload_and_saved_html_use_real_task_ids_and_deduplicate_cards():
    task_id = uuid.uuid4()
    payload = {"items": {"oneH": [{"id": "display-id", "task_id": str(task_id)}, {"taskId": str(task_id)}],
                         "meetings": [{"id": "meeting-not-task"}]}}
    assert payload_task_ids(payload) == {task_id}
    report = {"html": f'<td data-task-id="{task_id}">Task</td><td data-task-id="{task_id}">Again</td>'}
    with patch("app.services.today_print_strikes.task_strike_summary", new=AsyncMock(return_value={"tasks": {}})) as summary:
        enriched = asyncio.run(with_report_strikes(AsyncMock(), report, DAY))
    assert summary.await_args.args[2] == {task_id}
    assert enriched["html"] == report["html"] and "one_h_strikes" not in report


def test_no_task_cards_avoids_a_database_query():
    db = AsyncMock()
    result = asyncio.run(task_strike_summary(db, DAY, set(), now=clock(9)))
    assert result["tasks"] == {}
    db.execute.assert_not_awaited()


def test_at_1438_only_the_last_finished_interval_is_selected():
    task_id = uuid.uuid4()
    text = "[[done]]1. Morning[[/done]]\n[[done]]2. Current[[/done]]\n[[done]]3. Previous interval[[/done]]"
    rows = [(task_id, "Task", text, None, None, strike) for strike in (
        event("1. Morning", 9), event("2. Current", 14, 30), event("3. Previous interval", 14, 10),
    )]
    db = AsyncMock()
    db.execute.return_value = MagicMock(all=lambda: rows)
    summary = asyncio.run(task_strike_summary(db, DAY, {task_id}, now=clock(14, 38)))
    assert summary["active_slot"] == "14:20"
    assert summary["active_interval"] == {"start": "11:50", "end": "14:20"}
    assert summary["tasks"][str(task_id)][summary["active_slot"]] == 1
    assert summary["tasks"][str(task_id)]["10:00"] == 1
    assert "16:00" not in summary["tasks"][str(task_id)]


@pytest.mark.parametrize("hour,minute,slot,start,end", [
    (9, 30, None, None, None),
    (10, 0, "10:00", "08:00", "10:00"),
    (10, 59, "10:00", "08:00", "10:00"),
    (11, 0, "11:00", "10:00", "11:00"),
    (11, 30, "11:00", "10:00", "11:00"),
    (11, 50, "11:50", "11:00", "11:50"),
    (14, 19, "11:50", "11:00", "11:50"),
    (14, 20, "14:20", "11:50", "14:20"),
    (14, 38, "14:20", "11:50", "14:20"),
    (16, 0, "16:00", "14:20", "16:00"),
])
def test_finished_interval_selection_at_report_boundaries(hour, minute, slot, start, end):
    summary = asyncio.run(task_strike_summary(AsyncMock(), DAY, set(), now=clock(hour, minute)))
    assert summary["active_slot"] == slot
    assert summary["active_interval"] == ({"start": start, "end": end} if slot else None)


def test_1130_counts_1000_to_1100_and_excludes_1115_strikes():
    task_id = uuid.uuid4()
    text = "[[done]]1. Finished hour[[/done]]\n[[done]]2. Incomplete hour[[/done]]"
    db = AsyncMock()
    db.execute.return_value = MagicMock(all=lambda: [
        (task_id, "Task", text, None, None, event("1. Finished hour", 10, 30)),
        (task_id, "Task", text, None, None, event("2. Incomplete hour", 11, 15)),
    ])
    summary = asyncio.run(task_strike_summary(db, DAY, {task_id}, now=clock(11, 30)))
    assert summary["tasks"][str(task_id)][summary["active_slot"]] == 1
    assert "11:50" not in summary["tasks"][str(task_id)]


def test_freeze_selects_the_1600_report_using_only_precutoff_evidence():
    task_id = uuid.uuid4()
    db = AsyncMock()
    db.execute.return_value = MagicMock(all=lambda: [(task_id, "Task", "1. Open", None, None, None)])
    captured = clock(15, 59).replace(second=59)
    summary = asyncio.run(task_strike_summary(db, DAY, {task_id}, now=captured, completed_through=clock(16)))
    assert summary["active_slot"] == "16:00"
    assert summary["active_interval"] == {"start": "14:20", "end": "16:00"}
    assert captured in db.execute.await_args.args[0].compile().params.values()
