import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routers import tasks
from app.models.enums import TaskStatus, UserRole
from app.models.task import Task
from app.schemas.task import TaskUpdate
from app.services import m2_reporting_points as m2, m3_reporting_points as m3
from app.services.daily_realization_events import record_task_semantic_events
from app.services.task_postponement import require_postponement_explanation, save_postponement_daily_explanation
from app.api.routers import system_tasks
from app.services import m1_reporting_points as m1
from app.services.daily_realization_live import timeline_from_events
from app.services.meetings_report import _postponed_tasks_for_m3_day


@pytest.mark.parametrize("field", ["start_date", "due_date"])
@pytest.mark.parametrize("task_status", list(TaskStatus))
@pytest.mark.parametrize("progress", [0, 50, 100])
@pytest.mark.parametrize("explanation", [{}, {"postponement_reason_code": "OTHER"},
    {"postponement_comment": "Waiting for approval"},
    {"postponement_reason_code": "OTHER", "postponement_comment": "   "}])
def test_date_postponement_is_rejected_before_any_task_mutation(field, explanation, task_status, progress):
    item = Task(id=uuid.uuid4(), title="DT: Test", start_date=datetime(2026, 10, 20, tzinfo=timezone.utc),
                due_date=datetime(2026, 10, 22, tzinfo=timezone.utc), status=task_status, progress_percentage=progress,
                department_id=uuid.uuid4(), assigned_to=uuid.uuid4())
    old_dates = (item.start_date, item.due_date)
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: item)
    db.execute.return_value.scalars.return_value.all.return_value = [item]
    payload = TaskUpdate(**{field: datetime(2026, 10, 23, tzinfo=timezone.utc), **explanation})
    with patch.object(tasks, "_is_user_assigned_to_task", new=AsyncMock(return_value=True)), \
         patch.object(tasks, "_ensure_system_task_instance_integrity", new=AsyncMock(
             side_effect=AssertionError("Date update passed validation without its explanation"))):
        with pytest.raises(HTTPException) as error:
            asyncio.run(tasks.update_task(item.id, payload, db, SimpleNamespace(id=item.assigned_to, role=UserRole.ADMIN)))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    assert error.value.detail["changes"][0]["field"] == field
    assert (item.start_date, item.due_date) == old_dates
    db.commit.assert_not_awaited()


def test_semantic_date_events_preserve_reason_and_comment_for_each_change():
    db = MagicMock()
    events = record_task_semantic_events(db=db, task_id=uuid.uuid4(), actor_user_id=uuid.uuid4(),
        before={"start_date": "2026-10-20", "due_date": "2026-10-20"},
        after={"start_date": "2026-10-21", "due_date": "2026-10-22"},
        reason="Mungesë informacioni", reason_code="MISSING_INFORMATION", comment="Duhet përgjigjja e klientit")
    assert len(events) == 2
    for event in events:
        assert event.after["reason"] == "Mungesë informacioni"
        assert event.after["reason_code"] == "MISSING_INFORMATION"
        assert event.after["comment"] == "Duhet përgjigjja e klientit"


def test_reporting_rows_keep_the_explanation_of_their_own_am_or_pm_postponement():
    day = date(2026, 10, 20)
    item = Task(id=uuid.uuid4(), title="DT: Test", status=TaskStatus.TODO, progress_percentage=0,
                created_at=datetime(2026, 10, 19, tzinfo=timezone.utc), start_date=day,
                due_date=date(2026, 10, 22), is_deadline_important=True)
    events = [SimpleNamespace(id=uuid.uuid4(), entity_id=item.id, action="task.due_date_changed",
                before={"value": old}, after={"value": new, "reason": reason, "comment": comment},
                created_at=datetime(2026, 10, 20, hour, tzinfo=timezone.utc))
              for old, new, reason, comment, hour in [
                ("2026-10-20", "2026-10-21", "AM reason", "AM comment", 7),
                ("2026-10-21", "2026-10-22", "PM reason", "PM comment", 13)]]
    rows = m3.select_task_sections([item], events, day)["postponed_today"]
    assert [(row.get("reason"), row.get("comment")) for row in rows] == [
        ("AM reason", "AM comment"), ("PM reason", "PM comment")]


def test_m2_postponement_explanations_appear_in_html_text_and_exports():
    row = {"task_id": str(uuid.uuid4()), "title": "Task", "status": "TODO", "postponement_kind": "due",
           "reason": "Saved reason", "comment": "Saved comment", "risk": "OK"}
    report = {"report_date": "2026-10-20", "manual_answers": {}, "data": {"postponed": [row]}}
    assert "Saved reason" in m2.render_html(report)
    assert "Saved comment" in m2.render_plain_text(report)
    table = next(block for block in m2.export_blocks(report) if block["kind"] == "table")
    assert "Saved reason" in [cell["text"] for cell in table["rows"][0]]
    assert "Saved comment" in [cell["text"] for cell in table["rows"][0]]


@pytest.mark.parametrize("new", [None, "2026-10-19", "2026-10-20T15:00:00+02:00"])
def test_initial_unchanged_earlier_and_same_local_day_dates_need_no_explanation(new):
    item = SimpleNamespace(start_date=None, due_date="2026-10-20T10:00:00+02:00")
    assert require_postponement_explanation(task=item, updates={"start_date": "2026-10-25", "due_date": new}, reason_code=None, comment=None) == {}


def test_valid_explanation_is_trimmed_and_daily_state_upsert_targets_each_assignee():
    task_id = uuid.uuid4()
    item = SimpleNamespace(id=task_id, title="Task", start_date=date(2026, 10, 20), due_date=date(2026, 10, 20))
    explanation = require_postponement_explanation(task=item, updates={"due_date": "2026-10-21"},
        reason_code=" OTHER ", comment="  Await approval  ")
    assert explanation["reason_code"] == "OTHER"
    assert explanation["comment"] == "Await approval"
    db = AsyncMock()
    owners = {uuid.uuid4(), uuid.uuid4()}
    asyncio.run(save_postponement_daily_explanation(db, task_id=task_id, user_ids=owners, explanation=explanation))
    statement = db.execute.await_args.args[0]
    params = statement.compile().params
    assert {params["user_id_m0"], params["user_id_m1"]} == owners
    assert params["task_id_m0"] == task_id and params["comment_m1"] == "Await approval"
    assert "ON CONFLICT ON CONSTRAINT uq_task_daily_rlz_state_task_user_day DO UPDATE" in str(statement)


def test_system_occurrence_postponement_requires_explanation_before_baseline_or_mutation():
    user_id = uuid.uuid4()
    template = SimpleNamespace(id=uuid.uuid4(), assignee_ids=[user_id], timezone="Europe/Tirane")
    item = Task(id=uuid.uuid4(), title="System task", assigned_to=user_id, status=TaskStatus.TODO,
                due_date=datetime(2026, 10, 20, 10, tzinfo=timezone.utc))
    db = AsyncMock()
    template_result = MagicMock(scalar_one_or_none=lambda: template)
    task_result = MagicMock()
    task_result.scalars.return_value.first.return_value = item
    db.execute.side_effect = [template_result, task_result, MagicMock()]
    payload = system_tasks.SystemTaskOccurrenceDateOverrideIn(template_id=template.id,
        source_occurrence_date=date(2026, 10, 20), target_occurrence_date=date(2026, 10, 21))
    with patch.object(system_tasks, "ensure_daily_baselines_for_departments", new=AsyncMock(
            side_effect=AssertionError("System task date validation was bypassed"))):
        with pytest.raises(HTTPException) as error:
            asyncio.run(system_tasks.override_system_task_occurrence_date(payload, db, SimpleNamespace(id=user_id, role=UserRole.STAFF)))
    assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    assert item.due_date.day == 20
    db.commit.assert_not_awaited()


def test_m1_plan_changes_include_postponement_explanations_in_all_export_formats():
    report = {"report_date": "2026-10-20", "manual_answers": {}, "data": {"postponed": [
        {"task_id": str(uuid.uuid4()), "title": "Moved task", "status": "TODO", "postponement_kind": "start",
         "postponement_period": "AM", "reason": "M1 reason", "comment": "M1 comment"}]}}
    assert "M1 reason" in m1.render_html(report)
    assert "M1 comment" in m1.render_plain_text(report)
    rows = [row for block in m1.export_blocks(report) if block["kind"] == "table" for row in block["rows"]]
    assert any(cell["text"] == "M1 comment" for row in rows for cell in row)


def test_realization_timeline_retains_postponement_comment():
    event = SimpleNamespace(id=uuid.uuid4(), actor_user_id=uuid.uuid4(), action="task.due_date_changed",
        created_at=datetime(2026, 10, 20, 10, tzinfo=timezone.utc), before={"value": "2026-10-20"},
        after={"value": "2026-10-21", "reason": "Other", "reason_code": "OTHER", "comment": "Original explanation"})
    row = timeline_from_events(day=date(2026, 10, 20), baseline_task=None, events=[event])[0]
    assert row["metadata"]["comment"] == "Original explanation"


def test_meeting_postponements_include_start_only_moves_and_event_explanation():
    day = date(2026, 10, 20)
    item = Task(id=uuid.uuid4(), title="Start only", status=TaskStatus.TODO,
        start_date=date(2026, 10, 21), due_date=date(2026, 10, 23))
    snapshot = SimpleNamespace(payload={"people": [{"tasks": [{"task_id": str(item.id)}]}]})
    event = SimpleNamespace(id=uuid.uuid4(), entity_id=item.id, action="task.start_date_changed",
        created_at=datetime(2026, 10, 20, 9, tzinfo=timezone.utc), before={"value": "2026-10-20"},
        after={"value": "2026-10-21", "reason": "Meeting reason", "comment": "Meeting comment"})
    def result(values):
        output = MagicMock()
        output.scalars.return_value.all.return_value = values
        return output
    db = AsyncMock()
    db.execute.side_effect = [result([snapshot]), result([event])]
    moved, ranges, both, _ = asyncio.run(_postponed_tasks_for_m3_day(db, day, [item]))
    assert moved == [item] and both == []
    assert ranges[item.id] == ("START: 20.10.2026", "START: 21.10.2026")
    assert item._report_postponement_explanation == ("Meeting reason", "Meeting comment")


def test_repeated_same_day_postponements_remain_in_meeting_reports_with_latest_explanation():
    day = date(2026, 10, 20)
    item = Task(id=uuid.uuid4(), title="Twice moved", status=TaskStatus.TODO, due_date=date(2026, 10, 22))
    events = [SimpleNamespace(id=uuid.uuid4(), entity_id=item.id, action="task.due_date_changed",
        created_at=datetime(2026, 10, 20, hour, tzinfo=timezone.utc), before={"value": old},
        after={"value": new, "reason": "OTHER", "comment": comment})
        for old, new, comment, hour in [("2026-10-20", "2026-10-21", "First explanation", 7),
                                       ("2026-10-21", "2026-10-22", "Latest explanation", 13)]]
    snapshot = SimpleNamespace(payload={"people": [{"tasks": [{"task_id": str(item.id)}]}]})
    def result(values):
        output = MagicMock()
        output.scalars.return_value.all.return_value = values
        return output
    db = AsyncMock()
    db.execute.side_effect = [result([snapshot]), result(events)]
    moved, ranges, _, _ = asyncio.run(_postponed_tasks_for_m3_day(db, day, [item]))
    assert moved == [item]
    assert ranges[item.id] == ("20.10.2026", "22.10.2026")
    assert item._report_postponement_explanation == ("OTHER", "Latest explanation")


def test_date_update_takes_baseline_before_lock_then_validates_the_locked_dates():
    task_id = uuid.uuid4()
    def item(due):
        return Task(id=task_id, title="DT: Concurrent update", status=TaskStatus.TODO,
                    due_date=datetime(2026, 10, due, tzinfo=timezone.utc), department_id=uuid.uuid4())
    initial, committed = item(22), item(20)
    committed.department_id = initial.department_id
    sequence = []
    async def execute(query):
        result = MagicMock()
        if "FOR UPDATE" in str(query):
            sequence.append("lock")
            assert "ORDER BY tasks.id" in str(query)
            assert query.get_execution_options()["populate_existing"]
            result.scalars.return_value.all.return_value = [committed]
        elif query.column_descriptions[0].get("entity") is Task:
            result.scalar_one_or_none.return_value = initial
        else:
            result.scalars.return_value.all.return_value = []
        return result
    async def baseline(**kwargs):
        sequence.append("baseline")
    db = AsyncMock()
    db.execute.side_effect = execute
    with patch.object(tasks, "_is_user_assigned_to_task", new=AsyncMock(return_value=True)), \
         patch.object(tasks, "ensure_daily_baselines_for_departments", new=AsyncMock(side_effect=baseline)), \
         patch.object(tasks, "_ensure_system_task_instance_integrity", new=AsyncMock()):
        with pytest.raises(HTTPException) as error:
            asyncio.run(tasks.update_task(task_id, TaskUpdate(due_date="2026-10-21"), db,
                SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)))
    assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    assert sequence[:2] == ["baseline", "lock"]
    assert committed.due_date.day == 20
    db.commit.assert_not_awaited()


def test_report_enrichment_keeps_event_explanation_after_daily_comment_changes():
    from app.models.audit_log import AuditLog
    from app.models.department import Department
    from app.models.user import User
    from app.models.task_assignee import TaskAssignee
    from app.models.task_daily_rlz_state import TaskDailyRlzState
    day = date(2026, 10, 20)
    user_id, department_id = uuid.uuid4(), uuid.uuid4()
    item = Task(id=uuid.uuid4(), title="DT: Immutable explanation", status=TaskStatus.TODO, progress_percentage=0,
        is_deadline_important=False, completed_at=None,
        start_date=datetime(2026, 10, 20, tzinfo=timezone.utc), due_date=datetime(2026, 10, 21, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc), assigned_to=user_id, department_id=department_id)
    event = SimpleNamespace(id=uuid.uuid4(), entity_id=item.id, action="task.due_date_changed",
        created_at=datetime(2026, 10, 20, 7, tzinfo=timezone.utc), before={"value": "2026-10-20"},
        after={"value": "2026-10-21", "reason": "Original reason", "comment": "Original comment"})
    values = {
        Task: [item], AuditLog: [event], TaskAssignee: [(item.id, user_id)],
        Department: [SimpleNamespace(id=department_id, code="DEV")],
        User: [SimpleNamespace(id=user_id, full_name="Test User", username=None, email=None)],
        TaskDailyRlzState: [SimpleNamespace(task_id=item.id, user_id=user_id, reason_code="OTHER", comment="Later daily comment")],
    }
    async def execute(query):
        output = MagicMock()
        rows = values.get(query.column_descriptions[0].get("entity"), [])
        output.scalars.return_value.all.return_value = rows
        output.all.return_value = rows
        return output
    db = AsyncMock()
    db.execute.side_effect = execute
    with patch.object(m3, "apply_weekly_planner_task_order", new=AsyncMock()):
        data = asyncio.run(m3.build_task_data(db, day))
    assert data["postponed_today"][0]["reason"] == "Original reason"
    assert data["postponed_today"][0]["comment"] == "Original comment"
    assert data["untouched"][0]["comment"] == "Later daily comment"
