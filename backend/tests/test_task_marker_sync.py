from types import SimpleNamespace
from datetime import date
from uuid import uuid4
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.ga_note import GaNoteTaskAssigneeStateUpdate, GaNoteTaskBundleUpdate
from app.models.enums import TaskStatus
from app.models.task import Task
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.services.task_marker import historical_marker_for_day, normalize_marker_comment, note_bundle_marker_update, one_h_marker_label, sync_task_marker, sync_note_assignee_markers


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


def test_top_level_note_symbol_edits_the_note():
    assignee_id = uuid4()
    payload = GaNoteTaskBundleUpdate(one_h_marker="QUESTION")
    changed, marker = note_bundle_marker_update(
        SimpleNamespace(one_h_marker=None), payload, [_task(assignee_id, None)]
    )
    assert (changed, marker) == (True, "QUESTION")


def test_assignee_symbol_edit_does_not_update_the_note_symbol():
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
    assert (changed, marker) == (False, None)


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


def test_different_assignee_symbols_are_accepted_without_a_note_edit():
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
    assert note_bundle_marker_update(
        SimpleNamespace(one_h_marker=None), payload, [_task(first, None), _task(second, None)],
    ) == (False, None)


@pytest.mark.parametrize("origin", ["ga_note_origin_id", "plan_note_origin_id", "fast_task_group_id"])
def test_task_symbol_and_comment_changes_do_not_touch_other_assignees_or_source_notes(origin):
    shared = uuid4()
    tasks = [Task(id=uuid4(), assigned_to=uuid4(), title="Work", is_active=True,
                  one_h_marker="QUESTION", one_h_marker_comment=None, **{origin: shared}) for _ in range(3)]
    db = AsyncMock()
    with patch("app.services.marker_comments.record_marker_change", new=AsyncMock()) as notify:
        asyncio.run(sync_task_marker(db, tasks[1], "M3", marker_comment="Only the second owner", actor_email="ga@primexeu.com"))
    assert [task.one_h_marker for task in tasks] == ["QUESTION", "M3", "QUESTION"]
    assert [task.title for task in tasks] == ["Work", "Work\nCOM: Only the second owner", "Work"]
    assert tasks[1].one_h_marker_by_ga is True
    assert notify.await_args.args[1] == [tasks[1]]
    db.execute.assert_not_awaited()
    with patch("app.services.marker_comments.record_marker_change", new=AsyncMock()) as notify:
        asyncio.run(sync_task_marker(db, tasks[1], None, marker_comment=None))
    assert [task.one_h_marker for task in tasks] == ["QUESTION", None, "QUESTION"]
    assert all(task.title == "Work" for task in tasks)
    assert notify.await_args.args[1] == [tasks[1]]


def test_assignee_bundle_preserves_unchanged_comments_and_allows_independent_symbols():
    tasks = [Task(id=uuid4(), assigned_to=uuid4(), title="Work", is_active=True,
                  one_h_marker="QUESTION", one_h_marker_comment="Existing") for _ in range(3)]
    states = [
        GaNoteTaskAssigneeStateUpdate(assignee_id=tasks[0].assigned_to, status=TaskStatus.TODO, one_h_marker="M2"),
        GaNoteTaskAssigneeStateUpdate(assignee_id=tasks[1].assigned_to, status=TaskStatus.TODO, one_h_marker="GENT", one_h_marker_comment="Second only"),
        GaNoteTaskAssigneeStateUpdate(assignee_id=tasks[2].assigned_to, status=TaskStatus.IN_PROGRESS, one_h_marker="QUESTION"),
    ]
    with patch("app.services.marker_comments.record_marker_change", new=AsyncMock()) as notify:
        asyncio.run(sync_note_assignee_markers(AsyncMock(), tasks, states, actor_email="ga@primexeu.com"))
    assert [task.one_h_marker for task in tasks] == ["M2", "GENT", "QUESTION"]
    assert [task.one_h_marker_comment for task in tasks] == ["Existing", "Second only", "Existing"]
    assert notify.await_count == 2


@pytest.mark.parametrize("model,copy_function", [(GaNote, "_copy_for_new_assignee"), (PlanNote, "_copy_for_new_plan_assignee")])
def test_adding_an_assignee_does_not_inherit_someone_elses_marker(model, copy_function):
    from app.services import ga_note_task_instances
    note = model(id=uuid4(), one_h_marker=None, one_h_marker_comment=None)
    template = Task(title="Work\nCOM: Only Alice", one_h_marker="M3", one_h_marker_comment="Only Alice")
    copy = getattr(ga_note_task_instances, copy_function)(template=template, note=note,
        assignee=SimpleNamespace(id=uuid4(), department_id=None), actor_user_id=uuid4())
    assert copy.one_h_marker is None and copy.one_h_marker_comment is None
    assert copy.title == "Work"


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
