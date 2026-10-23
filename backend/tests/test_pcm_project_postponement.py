import asyncio
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

from app.api.routers import tasks
from app.models.enums import TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.schemas.task import TaskUpdate
from app.services.task_postponement import check_task_postponement_explanation
from tests.test_note_postponement import setup


def result(rows):
    output = MagicMock()
    output.scalar_one_or_none.return_value = rows[0] if rows else None
    output.scalars.return_value.all.return_value = rows
    return output


@pytest.mark.parametrize("project_department", ["PCM", " pcm ", "GD", None])
@pytest.mark.parametrize("field", ["start_date", "due_date"])
def test_exemption_uses_the_project_department_even_for_cross_department_assignees(project_department, field):
    project_id, project_department_id = uuid.uuid4(), uuid.uuid4()
    item = Task(id=uuid.uuid4(), title="Project task", project_id=project_id,
                department_id=uuid.uuid4(), start_date=datetime(2026, 10, 20, tzinfo=timezone.utc),
                due_date=datetime(2026, 10, 22, tzinfo=timezone.utc))
    # Run the classification query against actual tables, including missing departments.
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE departments (id CHAR(32) PRIMARY KEY, code TEXT)")
        connection.exec_driver_sql("CREATE TABLE projects (id CHAR(32) PRIMARY KEY, department_id CHAR(32))")
        connection.exec_driver_sql("INSERT INTO departments VALUES (?, ?)",
                                   (project_department_id.hex, project_department))
        connection.exec_driver_sql("INSERT INTO projects VALUES (?, ?)",
                                   (project_id.hex, project_department_id.hex if project_department else None))
        db = AsyncMock()
        db.execute.side_effect = connection.execute
        call = check_task_postponement_explanation(db, task=item,
            updates={field: datetime(2026, 10, 23, tzinfo=timezone.utc)}, reason_code=None, comment=None)
        if (project_department or "").strip().upper() == "PCM":
            assert asyncio.run(call) == {}
        else:
            with pytest.raises(HTTPException) as error:
                asyncio.run(call)
            assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    engine.dispose()


def test_standalone_pcm_tasks_still_require_an_explanation():
    item = Task(id=uuid.uuid4(), title="PCM standalone", department_id=uuid.uuid4(),
                due_date=datetime(2026, 10, 20, tzinfo=timezone.utc))
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        asyncio.run(check_task_postponement_explanation(db, task=item, updates={"due_date": "2026-10-21"},
                                                       reason_code=None, comment=None))
    assert error.value.detail["code"] == "TASK_POSTPONEMENT_EXPLANATION_REQUIRED"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("field", ["start_date", "due_date"])
@pytest.mark.parametrize("phase", ["MEETINGS", "PRODUCT", "CONTROL", "FINAL"])
def test_pcm_project_date_update_saves_without_dialog_and_keeps_date_history(field, phase):
    project = Project(id=uuid.uuid4(), title="TT - AMAZON MONRAVO PHAEA", department_id=uuid.uuid4())
    item = Task(id=uuid.uuid4(), title="KO PLOTESIMI I PRODUKTEVE AMAZON", project_id=project.id,
                department_id=uuid.uuid4(), assigned_to=uuid.uuid4(), status=TaskStatus.TODO, phase=phase,
                start_date=datetime(2026, 10, 20, tzinfo=timezone.utc),
                due_date=datetime(2026, 10, 22, tzinfo=timezone.utc), is_active=True)
    old_date = getattr(item, field)
    new_date = datetime(2026, 10, 21 if field == "start_date" else 23, tzinfo=timezone.utc)
    db = AsyncMock()
    db.add = MagicMock()

    async def execute(query):
        entity = query.column_descriptions[0].get("entity")
        if entity is Task:
            return result([item])
        if entity is Project:
            return result([project.id] if query.column_descriptions[0]["name"] == "id" else [project])
        return result([])

    db.execute.side_effect = execute
    with ExitStack() as stack:
        for name in ("_is_user_assigned_to_task", "_ensure_system_task_instance_integrity",
                     "ensure_daily_baselines_for_departments", "_clear_task_planner_exclusions_for_current_plan",
                     "_add_task_planner_exclusions", "_validate_pcm_control_origin", "_sync_control_task_owner_from_ko"):
            stack.enter_context(patch.object(tasks, name, new=AsyncMock(return_value=True)))
        stack.enter_context(patch.object(tasks, "_assignees_for_tasks", new=AsyncMock(return_value={})))
        stack.enter_context(patch.object(tasks, "_task_to_out", return_value=SimpleNamespace()))
        asyncio.run(tasks.update_task(item.id, TaskUpdate(**{field: new_date}), db,
                    SimpleNamespace(id=item.assigned_to, role=UserRole.ADMIN)))
    assert getattr(item, field) == new_date
    db.commit.assert_awaited_once()
    events = [call.args[0] for call in db.add.call_args_list
              if getattr(call.args[0], "action", "") == f"task.{field}_changed"]
    assert len(events) == 1
    assert events[0].before["value"] == old_date.isoformat()
    assert events[0].after["value"] == new_date.isoformat()
    if field == "due_date":
        assert item.original_due_date == old_date
    assert not any("INSERT INTO task_daily_rlz_states" in str(call.args[0]) for call in db.execute.await_args_list)


@pytest.mark.parametrize("source", ["ga", "plan"])
def test_pcm_project_notes_can_be_postponed_without_explanation(source):
    module, schema, note, item, db = setup(source)
    item.project_id = note.project_id = uuid.uuid4()
    original_execute = db.execute.side_effect

    async def execute(query):
        if query.column_descriptions[0].get("entity") is Project:
            return result([item.project_id])
        return await original_execute(query)

    db.execute.side_effect = execute
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "_ensure_note_access", new=AsyncMock()))
        stack.enter_context(patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock()))
        stack.enter_context(patch.object(module, "_note_out", return_value=note))
        stack.enter_context(patch.object(module, "GaNoteTaskBundleResponse" if source == "ga" else "PlanNoteTaskBundleResponse"))
        stack.enter_context(patch.object(tasks, "_clear_task_planner_exclusions_for_current_plan", new=AsyncMock()))
        asyncio.run(getattr(module, f"update_{'ga' if source == 'ga' else 'plan'}_note_task_bundle")(
            note.id, schema(assignee_states=[{"assignee_id": item.assigned_to, "status": "IN_PROGRESS",
                "start_date": item.start_date, "due_date": "2026-10-26T00:00:00Z"}]), db,
            SimpleNamespace(id=item.assigned_to, role=UserRole.STAFF)))
    assert item.due_date.day == 26
    db.commit.assert_awaited_once()


def test_voluntary_pcm_project_explanation_is_preserved():
    item = Task(id=uuid.uuid4(), project_id=uuid.uuid4(), due_date=datetime(2026, 10, 20, tzinfo=timezone.utc))
    db = AsyncMock()
    db.execute.return_value = result([item.project_id])
    explanation = asyncio.run(check_task_postponement_explanation(db, task=item, updates={"due_date": "2026-10-21"},
                                reason_code=" OTHER ", comment=" Waiting for approval "))
    assert explanation["reason_code"] == "OTHER"
    assert explanation["comment"] == "Waiting for approval"
