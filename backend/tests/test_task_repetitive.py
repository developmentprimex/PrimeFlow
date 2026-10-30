import unittest
import uuid
from types import SimpleNamespace

from app.models.task import Task
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.ga_note_task_instances import _copy_for_new_assignee, _copy_for_new_plan_assignee


class TestTaskRepetitive(unittest.TestCase):
    def test_existing_tasks_default_to_unchecked(self):
        column = Task.__table__.c.is_repetitive
        self.assertFalse(column.nullable)
        self.assertEqual(str(column.server_default.arg), "false")

    def test_update_preserves_omitted_flag_and_can_uncheck_it(self):
        self.assertNotIn("is_repetitive", TaskUpdate(title="Changed title").model_dump(exclude_unset=True))
        self.assertEqual(TaskUpdate(is_repetitive=False).model_dump(exclude_unset=True), {"is_repetitive": False})
        self.assertTrue(TaskCreate(title="Repeated work", is_repetitive=True).is_repetitive)

    def test_new_assignee_copies_preserve_flag_without_changing_schedule(self):
        for copy_task in (_copy_for_new_assignee, _copy_for_new_plan_assignee):
            for flag in (True, False):
                with self.subTest(copy=copy_task.__name__, flag=flag):
                    template = Task(title="Repeated work", is_repetitive=flag)
                    result = copy_task(
                        template=template,
                        note=SimpleNamespace(id=uuid.uuid4(), department_id=None),
                        assignee=SimpleNamespace(id=uuid.uuid4(), department_id=None),
                        actor_user_id=uuid.uuid4(),
                    )
                    self.assertEqual(result.is_repetitive, flag)
                    self.assertIsNone(result.due_date)
                    self.assertIsNone(result.system_template_origin_id)
