import asyncio
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.routers import ga_notes, plan_notes
from app.models.enums import TaskStatus, UserRole
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.schemas.ga_note import GaNoteTaskBundleUpdate
from app.schemas.plan_note import PlanNoteTaskBundleUpdate
from app.schemas.plan_note import PlanNoteTaskDeadlineUpdate
from app.services.task_postponement import require_note_postponement_explanations
from app.schemas.task_postponement import PostponementExplanationIn
from tests.test_ga_note_task_instances import _task


def setup(source, status=TaskStatus.IN_PROGRESS):
    note_id, owner = uuid.uuid4(), uuid.uuid4()
    item = _task(note_id, owner, status)
    item.start_date = datetime(2026, 10, 20, tzinfo=timezone.utc)
    item.due_date = datetime(2026, 10, 23, tzinfo=timezone.utc)
    item.created_at = item.updated_at = item.start_date
    if source == "plan":
        item.ga_note_origin_id, item.plan_note_origin_id = None, note_id
    note = SimpleNamespace(id=note_id, content=item.title, project_id=None, department_id=item.department_id,
        updated_at=item.start_date, one_h_marker=None, one_h_marker_date=None, is_converted_to_task=True, knowledge_type=None)
    db = AsyncMock()
    db.add = MagicMock()
    async def execute(statement):
        result = MagicMock()
        entity = statement.column_descriptions[0].get("entity") if hasattr(statement, "column_descriptions") else None
        rows = [item] if entity is Task else [note] if entity in (GaNote, PlanNote) else []
        result.scalar_one_or_none.return_value = rows[0] if rows else None
        result.scalars.return_value.all.return_value = rows
        return result
    db.execute.side_effect = execute
    module, schema = (ga_notes, GaNoteTaskBundleUpdate) if source == "ga" else (plan_notes, PlanNoteTaskBundleUpdate)
    return module, schema, note, item, db


@pytest.mark.parametrize("source", ["ga", "plan"])
@pytest.mark.parametrize("field", ["start_date", "due_date"])
@pytest.mark.parametrize("status", [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.WAITING_CLIENT])
def test_notes_reject_postponement_before_changing_note_or_any_task(source, field, status):
    module, schema, note, item, db = setup(source, status)
    body = {"content": "Must not save", "assignee_states": [{
        "assignee_id": item.assigned_to, "status": status, "start_date": item.start_date, "due_date": item.due_date,
        field: "2026-10-24T00:00:00Z" if field == "due_date" else "2026-10-21T00:00:00Z"}]}
    with patch.object(module, "_ensure_note_access", new=AsyncMock()), \
         patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock()), \
         patch.object(module, "_note_out", return_value=note), \
         patch.object(module, "GaNoteTaskBundleResponse" if source == "ga" else "PlanNoteTaskBundleResponse"):
        with pytest.raises(HTTPException) as error:
            asyncio.run(getattr(module, f"update_{'ga' if source == 'ga' else 'plan'}_note_task_bundle")(
                note.id, schema(**body), db, SimpleNamespace(id=item.assigned_to, role=UserRole.STAFF)))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    assert error.value.detail["postponements"][0]["task_id"] == str(item.id)
    assert note.content == "Shared GA task"
    assert item.start_date.day == 20 and item.due_date.day == 23
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("source", ["ga", "plan"])
def test_notes_save_explanation_on_the_assignee_task_event_and_daily_state(source):
    module, schema, note, item, db = setup(source)
    body = {"assignee_states": [{"assignee_id": item.assigned_to, "status": "IN_PROGRESS",
        "start_date": item.start_date, "due_date": "2026-10-26T00:00:00Z"}],
        "postponement_explanations": {str(item.id): {"postponement_reason_code": "OTHER", "postponement_comment": " Waiting for client "}}}
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "_ensure_note_access", new=AsyncMock()))
        stack.enter_context(patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock()))
        stack.enter_context(patch.object(module, "_note_out", return_value=note))
        stack.enter_context(patch.object(module, "GaNoteTaskBundleResponse" if source == "ga" else "PlanNoteTaskBundleResponse"))
        stack.enter_context(patch("app.api.routers.tasks._clear_task_planner_exclusions_for_current_plan", new=AsyncMock()))
        response = asyncio.run(getattr(module, f"update_{'ga' if source == 'ga' else 'plan'}_note_task_bundle")(
            note.id, schema(**body), db, SimpleNamespace(id=item.assigned_to, role=UserRole.STAFF)))
    assert item.due_date.day == 26
    events = [call.args[0] for call in db.add.call_args_list if getattr(call.args[0], "action", "") == "task.due_date_changed"]
    assert len(events) == 1
    assert events[0].after["comment"] == "Waiting for client"
    assert events[0].after["reason_code"] == "OTHER"
    assert events[0].entity_id == item.id
    statements = [call.args[0] for call in db.execute.await_args_list]
    upsert = next(stmt for stmt in statements if "INSERT INTO task_daily_rlz_states" in str(stmt))
    assert upsert.compile().params["user_id_m0"] == item.assigned_to
    db.commit.assert_awaited_once()


def test_legacy_plan_deadline_requires_explanation_without_mutation():
    module, _, note, item, db = setup("plan")
    with patch.object(module, "_get_note_or_404", new=AsyncMock(return_value=note)), \
         patch.object(module, "_ensure_note_access", new=AsyncMock()), \
         patch.object(module, "ensure_task_editor"), \
         patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock()):
        with pytest.raises(HTTPException) as error:
            asyncio.run(module.update_plan_note_task_deadline(note.id, PlanNoteTaskDeadlineUpdate(due_date="2026-10-26"),
                db, SimpleNamespace(id=item.assigned_to, role=UserRole.STAFF)))
    assert error.value.detail["postponements"][0]["task_id"] == str(item.id)
    assert item.due_date.day == 23
    db.commit.assert_not_awaited()


def test_all_assignee_explanations_are_required_and_cannot_be_reused_for_other_tasks():
    _, _, _, first, _ = setup("ga")
    _, _, _, second, _ = setup("ga")
    updates = {item.assigned_to: {"due_date": datetime(2026, 10, 26, tzinfo=timezone.utc)} for item in (first, second)}
    explanations = {first.id: PostponementExplanationIn(postponement_reason_code="OTHER", postponement_comment="First task only")}
    with pytest.raises(HTTPException) as error:
        require_note_postponement_explanations(tasks=[first, second], updates_by_assignee=updates, explanations=explanations)
    assert [row["task_id"] for row in error.value.detail["postponements"]] == [str(second.id)]
    explanations[second.id] = PostponementExplanationIn(postponement_reason_code="WAITING_CLIENT", postponement_comment="Second task only")
    saved = require_note_postponement_explanations(tasks=[first, second], updates_by_assignee=updates, explanations=explanations)
    assert saved[first.id]["comment"] == "First task only"
    assert saved[second.id]["comment"] == "Second task only"


def test_explanation_dialog_identifies_the_person_for_each_note_task():
    from app.services.task_postponement import check_note_postponement_explanations
    _, _, _, item, db = setup("ga")
    result = MagicMock()
    result.scalars.return_value.all.return_value = [SimpleNamespace(id=item.assigned_to, full_name="Elsa Ferati", username=None, email=None)]
    db.execute.side_effect = None
    db.execute.return_value = result
    with pytest.raises(HTTPException) as error:
        asyncio.run(check_note_postponement_explanations(db, tasks=[item], updates_by_assignee={
            item.assigned_to: {"due_date": datetime(2026, 10, 26, tzinfo=timezone.utc)}}, explanations={}))
    assert error.value.detail["postponements"][0]["assignee_name"] == "Elsa Ferati"


def test_legacy_plan_deadline_records_the_same_report_events_as_notes_editor():
    module, _, note, item, db = setup("plan")
    payload = PlanNoteTaskDeadlineUpdate(due_date="2026-10-26", postponement_explanations={str(item.id): {
        "postponement_reason_code": "WAITING_CLIENT", "postponement_comment": "Legacy editor explanation"}})
    with patch.object(module, "_get_note_or_404", new=AsyncMock(return_value=note)), \
         patch.object(module, "_ensure_note_access", new=AsyncMock()), \
         patch.object(module, "ensure_task_editor"), \
         patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock()):
        asyncio.run(module.update_plan_note_task_deadline(note.id, payload, db, SimpleNamespace(id=item.assigned_to, role=UserRole.STAFF)))
    events = [call.args[0] for call in db.add.call_args_list if getattr(call.args[0], "action", "") == "task.due_date_changed"]
    assert len(events) == 1 and events[0].after["comment"] == "Legacy editor explanation"
    assert events[0].after["reason_code"] == "WAITING_CLIENT"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("source", ["ga", "plan"])
def test_notes_revalidate_committed_task_dates_after_baseline_and_before_mutation(source):
    module, schema, note, item, db = setup(source)
    item.due_date = datetime(2026, 10, 23, tzinfo=timezone.utc)
    sequence = []
    original_execute = db.execute.side_effect
    async def execute(statement):
        if "FOR UPDATE" in str(statement) and statement.column_descriptions[0].get("entity") is Task:
            sequence.append("task_lock")
            item.due_date = datetime(2026, 10, 20, tzinfo=timezone.utc)
        return await original_execute(statement)
    async def baseline(*args, **kwargs):
        sequence.append("baseline")
    db.execute.side_effect = execute
    payload = schema(assignee_states=[{"assignee_id": item.assigned_to, "status": "IN_PROGRESS",
        "start_date": item.start_date, "due_date": "2026-10-21"}])
    with patch.object(module, "_ensure_note_access", new=AsyncMock()), \
         patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock(side_effect=baseline)):
        with pytest.raises(HTTPException) as error:
            asyncio.run(getattr(module, f"update_{'ga' if source == 'ga' else 'plan'}_note_task_bundle")(
                note.id, payload, db, SimpleNamespace(id=item.assigned_to, role=UserRole.STAFF)))
    assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    assert sequence == ["baseline", "task_lock"]
    db.commit.assert_not_awaited()
