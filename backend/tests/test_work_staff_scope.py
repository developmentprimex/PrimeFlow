"""Exercise staff filtering with real SQL in an isolated in-memory database."""
import unittest
import uuid
from types import SimpleNamespace
from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routers.users import list_users, list_users_lookup
from app.db import Base
from app.models.department import Department
from app.models.enums import UserRole
from app.models.user import User
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.services.meeting_participants import replace_manual_participants
from app.services import system_task_instances


class AsyncReader:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)


class WorkStaffScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine, tables=[Department.__table__, User.__table__, Task.__table__, TaskAssignee.__table__])
        self.session = Session(self.engine)
        self.db = AsyncReader(self.session)
        self.admin = SimpleNamespace(role=UserRole.ADMIN, id=uuid.uuid4())
        self.staff = SimpleNamespace(role=UserRole.STAFF)
        self.work_department = Department(id=uuid.uuid4(), name="Development", code="DEV")
        self.home_department = Department(id=uuid.uuid4(), name="GA PERSONAL", code="GAP")
        self.session.add_all([self.work_department, self.home_department])
        self.people = {}
        for key, name, department, active in (
            ("LC", "Lirza C Test", self.home_department.id, True),
            ("MC", "Mrika C Test", self.home_department.id, True),
            ("RC", "Rrita C Test", self.home_department.id, True),
            ("EF", "Elsa Ferati", self.work_department.id, True),
            ("GA", "Gane Arifaj", self.work_department.id, True),
            ("OLD", "Former Staff", self.work_department.id, False),
            ("NONE", "No Department", None, True),
        ):
            person = User(id=uuid.uuid4(), full_name=name, email=f"{key}@example.com",
                          password_hash="unused", department_id=department,
                          is_active=active, role=UserRole.ADMIN if key == "GA" else UserRole.STAFF)
            self.people[key] = person
            self.session.add(person)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def test_default_lists_exclude_household_even_when_inactive_requested(self):
        expected = {self.people[key].id for key in ("EF", "GA", "NONE")}
        for endpoint in (list_users, list_users_lookup):
            result = await endpoint(db=self.db, user=self.admin)
            self.assertEqual({person.id for person in result}, expected)
            result = await endpoint(db=self.db, user=self.admin, include_inactive=True)
            self.assertEqual({person.id for person in result}, expected | {self.people["OLD"].id})

    async def test_admin_can_manage_household_accounts_without_deactivating_them(self):
        result = await list_users(db=self.db, user=self.admin, include_household=True)
        self.assertTrue({self.people[key].id for key in ("LC", "MC", "RC")} <= {person.id for person in result})
        with self.assertRaises(HTTPException) as error:
            await list_users(db=self.db, user=self.staff, include_household=True)
        self.assertEqual(error.exception.status_code, 403)
        # Authentication/private membership use ordinary User lookups.
        household = self.session.scalar(select(User).where(User.id == self.people["LC"].id))
        self.assertTrue(household.is_active)

    async def test_department_controls_membership_and_initials_do_not(self):
        self.people["LC"].department_id = self.work_department.id
        self.people["EF"].department_id = self.home_department.id
        self.session.commit()
        result = await list_users_lookup(db=self.db, user=self.admin)
        self.assertIn(self.people["LC"].id, {person.id for person in result})
        self.assertNotIn(self.people["EF"].id, {person.id for person in result})

    async def test_filter_supports_joined_reports_and_custom_department_ids(self):
        # Code/name comparison is case-insensitive and handles imported IDs.
        self.home_department.code = " gap "
        self.home_department.name = " ga personal "
        self.session.commit()
        result = self.session.scalars(select(User).join(Department).where(User.work_staff_filter())).all()
        self.assertFalse({self.people[key].id for key in ("LC", "MC", "RC")} & {person.id for person in result})

    async def test_work_meeting_rejects_household_assignment(self):
        with self.assertRaises(HTTPException) as error:
            await replace_manual_participants(self.db, meeting_id=uuid.uuid4(),
                participant_ids=[self.people["LC"].id], actor_user_id=self.admin.id)
        self.assertEqual(error.exception.status_code, 400)

    async def test_household_only_tasks_hidden_and_shared_work_preserved(self):
        examples = {}
        for key, primary, links in (
            ("home", "LC", ["LC"]), ("shared", "LC", ["LC", "EF"]),
            ("work", "EF", ["EF"]), ("unassigned", None, []),
            ("home_link_only", None, ["MC"]), ("work_link_only", None, ["GA"]),
        ):
            task = Task(id=uuid.uuid4(), title=key, assigned_to=self.people[primary].id if primary else None)
            self.session.add(task)
            self.session.flush()
            for key_person in links:
                self.session.add(TaskAssignee(task_id=task.id, user_id=self.people[key_person].id))
            examples[key] = task.id
        self.session.commit()
        result = self.session.scalars(select(Task.id).where(Task.work_staff_filter())).all()
        self.assertEqual(set(result), {examples[key] for key in ("shared", "work", "unassigned", "work_link_only")})

    async def test_scheduler_skips_existing_household_slots(self):
        now = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
        template = SimpleNamespace(id=uuid.uuid4(), department_id=self.work_department.id, duration_days=1)
        slots = [SimpleNamespace(id=uuid.uuid4(), primary_user_id=self.people[key].id, next_run_at=now)
                 for key in ("LC", "EF")]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(slot, template) for slot in slots])))
        with patch.object(system_task_instances, "ensure_slots_initialized", new=AsyncMock()), \
             patch.object(system_task_instances, "_system_task_user_maps", new=AsyncMock(return_value=(
                 {self.people["EF"].id: self.work_department.id}, {}))), \
             patch.object(system_task_instances, "template_tz", return_value=timezone.utc), \
             patch.object(system_task_instances, "template_due_time", return_value=time(10)), \
             patch.object(system_task_instances, "next_occurrence", side_effect=lambda _, day: day + timedelta(days=1)), \
             patch.object(system_task_instances, "_insert_system_task_instance", new=AsyncMock(return_value=True)) as insert:
            count = await system_task_instances.generate_system_task_instances(db, now_utc=now, start=now.date(), end=now.date())
        self.assertEqual(count, 1)
        self.assertEqual(insert.await_args.kwargs["assignee_id"], self.people["EF"].id)
