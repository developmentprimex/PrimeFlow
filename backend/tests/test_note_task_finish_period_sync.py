import unittest
import uuid
from contextlib import ExitStack
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.api.routers import ga_notes, plan_notes, tasks
from app.models.enums import TaskFinishPeriod, TaskStatus, UserRole
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.models.task_daily_progress import TaskDailyProgress
from app.schemas.ga_note import GaNoteTaskBundleUpdate
from app.schemas.plan_note import PlanNoteTaskBundleUpdate
from app.schemas.task import TaskUpdate
from tests.test_ga_note_task_instances import _task


class _Result:
    def __init__(self, values):
        self.values = values

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None

    def scalars(self):
        return self

    def all(self):
        return self.values


class TestNoteTaskFinishPeriodSync(unittest.IsolatedAsyncioTestCase):
    async def test_department_and_note_editors_move_the_same_daily_row_to_pm(self):
        for source in ("GA_KA", "PX_JAV"):
            for editor in ("department", "note"):
                for next_status in (None, TaskStatus.TODO, TaskStatus.IN_PROGRESS):
                    if editor == "note" and next_status is None:
                        continue
                    with self.subTest(source=source, editor=editor, status=next_status):
                        await self._edit_and_check(source, editor, next_status)

    async def _edit_and_check(self, source, editor, next_status):
        note_id, owner_id = uuid.uuid4(), uuid.uuid4()
        task = _task(note_id, owner_id, TaskStatus.TODO)
        task.finish_period = TaskFinishPeriod.AM
        now = datetime(2026, 9, 16, tzinfo=timezone.utc)
        task.created_at = task.updated_at = now
        if source == "PX_JAV":
            task.ga_note_origin_id = None
            task.plan_note_origin_id = note_id
        note = SimpleNamespace(
            id=note_id, content=task.title, project_id=None,
            department_id=task.department_id, updated_at=now,
            one_h_marker=None, one_h_marker_date=None, is_converted_to_task=True,
        )
        daily_row = SimpleNamespace(
            daily_status="TODO", finish_period="AM",
            completed_value=2, total_value=5, completed_delta=2,
        )
        requested_days = []

        async def execute(statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is Task:
                return _Result([task])
            if entity in (GaNote, PlanNote):
                return _Result([note])
            if entity is TaskDailyProgress:
                requested_days.extend(
                    value for value in statement.compile().params.values()
                    if isinstance(value, date)
                )
                return _Result([daily_row])
            return _Result([])

        db = SimpleNamespace(
            execute=AsyncMock(side_effect=execute), add=Mock(),
            commit=AsyncMock(), refresh=AsyncMock(),
        )
        user = SimpleNamespace(
            id=owner_id, role=UserRole.STAFF, department_id=task.department_id, email="owner@example.com",
        )
        router = ga_notes if source == "GA_KA" else plan_notes
        with ExitStack() as stack:
            for module in (tasks, router):
                stack.enter_context(patch.object(module, "ensure_daily_baselines_for_departments", new=AsyncMock()))
                stack.enter_context(patch.object(module, "record_task_semantic_events"))
                stack.enter_context(patch.object(module, "add_audit_log"))
            stack.enter_context(patch.object(tasks, "_is_user_assigned_to_task", new=AsyncMock(return_value=True)))
            stack.enter_context(patch.object(tasks, "_clear_task_planner_exclusions_for_current_plan", new=AsyncMock()))
            stack.enter_context(patch.object(tasks, "_validate_pcm_control_origin", new=AsyncMock()))
            stack.enter_context(patch.object(tasks, "_assignees_for_tasks", new=AsyncMock(return_value={})))
            stack.enter_context(patch.object(tasks, "_task_to_out", return_value=SimpleNamespace(finish_period="PM")))
            stack.enter_context(patch.object(tasks, "add_notification"))
            stack.enter_context(patch.object(tasks, "publish_notification", new=AsyncMock()))
            stack.enter_context(patch.object(router, "_ensure_note_access", new=AsyncMock()))
            # Response serialization is covered separately by the summary reload test.
            stack.enter_context(patch.object(router, "_note_out"))
            stack.enter_context(patch.object(router, "GaNoteTaskBundleResponse" if source == "GA_KA" else "PlanNoteTaskBundleResponse"))

            if editor == "department":
                await tasks.update_task(
                    task.id, TaskUpdate(finish_period="PM", status=next_status), db, user,
                )
            else:
                payload_type = GaNoteTaskBundleUpdate if source == "GA_KA" else PlanNoteTaskBundleUpdate
                endpoint = router.update_ga_note_task_bundle if source == "GA_KA" else router.update_plan_note_task_bundle
                await endpoint(note_id, payload_type(assignee_states=[{
                    "assignee_id": owner_id, "status": next_status, "finish_period": "PM",
                }]), db, user)

        self.assertEqual(task.finish_period, "PM")
        self.assertEqual(daily_row.finish_period, "PM")
        self.assertEqual(daily_row.daily_status, (next_status or TaskStatus.TODO).value)
        self.assertEqual((daily_row.completed_value, daily_row.total_value, daily_row.completed_delta), (2, 5, 2))
        self.assertTrue(requested_days)
        db.commit.assert_awaited_once()
