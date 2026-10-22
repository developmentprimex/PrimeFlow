from types import SimpleNamespace
from datetime import date
from uuid import uuid4

import pytest

from app.schemas.ga_note import GaNoteTaskAssigneeStateUpdate, GaNoteTaskBundleUpdate
from app.models.enums import TaskStatus
from app.services.task_marker import historical_marker_for_day, normalize_marker_comment, note_bundle_marker_update, one_h_marker_label


def test_comment_can_be_saved_without_a_symbol():
    assert normalize_marker_comment(None, "  Check this task  ") == "Check this task"
    assert normalize_marker_comment(None, " \n ") is None
    payload = GaNoteTaskBundleUpdate(one_h_marker=None, one_h_marker_comment="Check this task")
    assert note_bundle_marker_update(SimpleNamespace(one_h_marker=None, one_h_marker_comment=None), payload, []) == (True, None)
    row = SimpleNamespace(marker_date=date(2026, 10, 22), one_h_marker=None,
        one_h_marker_by_ga=False, one_h_marker_comment="Check this task")
    assert historical_marker_for_day([row], date(2026, 10, 23)) == (None, False, "Check this task")


def _task(assignee_id, marker):
    return SimpleNamespace(assigned_to=assignee_id, one_h_marker=marker, is_active=True)


def test_top_level_note_symbol_is_the_shared_symbol():
    assignee_id = uuid4()
    payload = GaNoteTaskBundleUpdate(one_h_marker="QUESTION")
    changed, marker = note_bundle_marker_update(
        SimpleNamespace(one_h_marker=None), payload, [_task(assignee_id, None)]
    )
    assert (changed, marker) == (True, "QUESTION")


def test_assignee_symbol_edit_updates_the_shared_symbol():
    assignee_id = uuid4()
    payload = GaNoteTaskBundleUpdate(
        assignee_states=[
            GaNoteTaskAssigneeStateUpdate(
                assignee_id=assignee_id,
                status=TaskStatus.TODO,
                one_h_marker="GENT",
            )
        ]
    )
    changed, marker = note_bundle_marker_update(
        SimpleNamespace(one_h_marker=None), payload, [_task(assignee_id, None)]
    )
    assert (changed, marker) == (True, "GENT")


def test_clearing_symbol_is_a_shared_update():
    assignee_id = uuid4()
    payload = GaNoteTaskBundleUpdate(one_h_marker=None)
    changed, marker = note_bundle_marker_update(
        SimpleNamespace(one_h_marker="KA"), payload, [_task(assignee_id, "KA")]
    )
    assert changed is True
    assert marker is None


def test_changing_only_symbol_comment_updates_the_shared_marker_bundle():
    assignee_id = uuid4()
    payload = GaNoteTaskBundleUpdate(
        one_h_marker="MONITOR",
        one_h_marker_comment="Needs a second check",
    )
    changed, marker = note_bundle_marker_update(
        SimpleNamespace(one_h_marker="MONITOR", one_h_marker_comment="Old comment"),
        payload,
        [_task(assignee_id, "MONITOR")],
    )
    assert (changed, marker) == (True, "MONITOR")


def test_conflicting_assignee_symbols_are_rejected():
    first, second = uuid4(), uuid4()
    payload = GaNoteTaskBundleUpdate(
        assignee_states=[
            GaNoteTaskAssigneeStateUpdate(
                assignee_id=first, status=TaskStatus.TODO, one_h_marker="KA"
            ),
            GaNoteTaskAssigneeStateUpdate(
                assignee_id=second, status=TaskStatus.TODO, one_h_marker="GENT"
            ),
        ]
    )
    with pytest.raises(ValueError, match="one symbol"):
        note_bundle_marker_update(
            SimpleNamespace(one_h_marker=None),
            payload,
            [_task(first, None), _task(second, None)],
        )


def test_weekly_planner_marker_label_preserves_ga_parentheses():
    assert one_h_marker_label("M2_M3") == "M2/3"
    assert one_h_marker_label("QUESTION", True) == "(?)"
    assert one_h_marker_label("FLAG") == "GA"
    assert one_h_marker_label("F") == "F"
    assert one_h_marker_label("BZ1N1") == "BZ1N1"
    assert one_h_marker_label("SHARE") == "SHARE"
    assert one_h_marker_label("SHARE", True) == "(SHARE)"


def test_weekly_planner_carries_a_symbol_into_the_next_week():
    rows = [
        SimpleNamespace(
            marker_date=date(2026, 9, 18),
            one_h_marker="M2_M3",
            one_h_marker_by_ga=False,
            one_h_marker_comment="Deliver twice",
        )
    ]
    assert historical_marker_for_day(rows, date(2026, 9, 21)) == (
        "M2_M3",
        False,
        "Deliver twice",
    )


def test_weekly_planner_keeps_old_days_and_applies_manual_changes_forward():
    rows = [
        SimpleNamespace(
            marker_date=date(2026, 9, 14),
            one_h_marker="M2_M3",
            one_h_marker_by_ga=False,
            one_h_marker_comment=None,
        ),
        SimpleNamespace(
            marker_date=date(2026, 9, 16),
            one_h_marker="EXCLAMATION",
            one_h_marker_by_ga=True,
            one_h_marker_comment="Changed Wednesday",
        ),
    ]
    assert historical_marker_for_day(rows, date(2026, 9, 15)) == ("M2_M3", False, None)
    assert historical_marker_for_day(rows, date(2026, 9, 17)) == (
        "EXCLAMATION",
        True,
        "Changed Wednesday",
    )


def test_weekly_planner_manual_clear_stops_symbol_carryover():
    rows = [
        SimpleNamespace(
            marker_date=date(2026, 9, 14),
            one_h_marker="QUESTION",
            one_h_marker_by_ga=False,
            one_h_marker_comment=None,
        ),
        SimpleNamespace(
            marker_date=date(2026, 9, 17),
            one_h_marker=None,
            one_h_marker_by_ga=False,
            one_h_marker_comment=None,
        ),
    ]
    assert historical_marker_for_day(rows, date(2026, 9, 16)) == ("QUESTION", False, None)
    assert historical_marker_for_day(rows, date(2026, 9, 18)) == (None, False, None)
