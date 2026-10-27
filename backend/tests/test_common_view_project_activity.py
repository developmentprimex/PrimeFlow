import unittest
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request, Response
from sqlalchemy import create_engine, select

from app.api.routers import common_view, projects
from app.models.department import Department
from app.models.enums import UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User


def result(rows):
    output = MagicMock()
    output.scalars.return_value.all.return_value = rows
    output.all.return_value = rows
    return output


class CommonViewProjectActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_inactive_projects_hide_only_prjk_and_preserve_done_1h_history(self):
        for active in (True, False):
            for status in ('TODO', 'DONE'):
                with self.subTest(active=active, status=status):
                    stamp = datetime(2026, 10, 26, tzinfo=timezone.utc)
                    department = Department(id=uuid.uuid4(), code='DEV', name='Development')
                    owner = User(id=uuid.uuid4(), username='l.h', full_name='L H', email='lh@example.test',
                                 department_id=department.id, role=UserRole.ADMIN, is_active=True)
                    project = Project(id=uuid.uuid4(), title='STD', department_id=department.id,
                                      is_active=active, current_phase='TESTING')
                    task = Task(id=uuid.uuid4(), title='LH: STD : EXCEL LIST KRAHASO',
                                project_id=project.id, department_id=department.id, assigned_to=owner.id,
                                is_active=True, status=status, is_1h_report=True, phase='TESTING',
                                created_at=stamp, start_date=stamp, due_date=stamp,
                                completed_at=stamp if status == 'DONE' else None)
                    db = AsyncMock()

                    async def execute(statement):
                        entity = statement.column_descriptions[0].get('entity')
                        if entity is User:
                            return result([owner])
                        if entity is Department:
                            return result([department])
                        if entity is Task:
                            return result([task])
                        if entity is TaskAssignee:
                            return result([(task.id, owner)])
                        if entity is Project:
                            return result([project])
                        return result([])

                    db.execute.side_effect = execute
                    request = Request({'type': 'http', 'headers': [(b'cache-control', b'no-cache')]})
                    with patch.object(common_view, '_compute_etag', AsyncMock(return_value='activity-test')), \
                         patch.object(common_view, 'SERVER_CACHE_TTL_SECONDS', 0):
                        output = await common_view.get_common_view(request, Response(), week_start=stamp.date(),
                            include='tasks', include_all_departments=True, db=db, user=owner)
                    self.assertEqual([row['project'] for row in output.items.priority], ['STD'] if active else [])
                    self.assertEqual(len(output.items.oneH), 1)
                    self.assertEqual(output.items.oneH[0]['task_id'], str(task.id))
                    self.assertEqual(output.items.oneH[0]['status'], status)
                    self.assertTrue(task.is_active)
                    db.commit.assert_not_awaited()

    async def test_lookup_exposes_activity_without_hiding_historical_project_titles(self):
        project = Project(id=uuid.uuid4(), title='STD', is_active=False)
        db = AsyncMock()
        db.execute.return_value = result([project])
        with patch.object(projects, 'build_project_display_title_map', AsyncMock(return_value={})):
            output = await projects.lookup_project_titles([project.id], db=db, user=User(role=UserRole.ADMIN))
        self.assertEqual(output[0].title, 'STD')
        self.assertFalse(output[0].is_active)

    async def test_project_activity_changes_etag_even_when_tasks_are_unchanged(self):
        engine = create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql('CREATE TABLE projects (id CHAR(32), updated_at DATETIME, is_active BOOLEAN)')
                connection.exec_driver_sql('CREATE TABLE tasks (id CHAR(32), project_id CHAR(32), is_active BOOLEAN, '
                    'start_date DATETIME, due_date DATETIME, created_at DATETIME, planned_for DATETIME, phase TEXT)')
                pid = uuid.uuid4().hex
                connection.exec_driver_sql("INSERT INTO projects VALUES (?, '2026-10-26 08:00:00', 1)", (pid,))
                connection.exec_driver_sql("INSERT INTO tasks VALUES (?, ?, 1, '2026-10-26', '2026-10-26', '2026-10-26', NULL, 'TESTING')",
                                           (uuid.uuid4().hex, pid))
                db = AsyncMock()

                async def execute(statement):
                    # Execute the real project fingerprint SQL; unrelated fingerprints stay fixed.
                    values = {column.key: None for column in statement.selected_columns}
                    selected = connection.execute(select(statement.selected_columns.projects_updated,
                                                         statement.selected_columns.active_projects_count)).mappings().one()
                    values.update(selected)
                    output = MagicMock()
                    output.mappings.return_value.one.return_value = values
                    return output

                db.execute.side_effect = execute
                kwargs = dict(db=db, week_start=date(2026, 10, 26), week_end=date(2026, 11, 1), requested=['tasks'],
                    user=User(role=UserRole.ADMIN), department_id=None, include_all_departments=True,
                    freeze_one_h_slots=True, one_h_slot_report_dates=[date(2026, 10, 26)],
                    one_h_slot_report_start=date(2026, 10, 26), one_h_slot_report_end=date(2026, 10, 26))
                before = await common_view._compute_etag(**kwargs)
                connection.exec_driver_sql('UPDATE projects SET is_active=0')
                after = await common_view._compute_etag(**kwargs)
                self.assertNotEqual(before, after)
        finally:
            engine.dispose()
