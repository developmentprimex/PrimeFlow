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
from app.services.meeting_system_tasks import _reconcile_external_meeting_task_kind, _user_department_map
from app.services.system_task_occurrences import _assignee_ids_for_template


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

    async def test_scheduler_skips_inactive_users_and_consumes_missed_runs(self):
        now = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
        template = SimpleNamespace(id=uuid.uuid4(), department_id=self.work_department.id, duration_days=1)
        slots = [SimpleNamespace(id=uuid.uuid4(), primary_user_id=self.people[key].id, next_run_at=now)
                 for key in ("OLD", "EF", "NONE", "LC")]

        async def run(day):
            async def execute(statement):
                if statement.column_descriptions[0]["entity"] is system_task_instances.SystemTaskTemplateAssigneeSlot:
                    return SimpleNamespace(all=lambda: [(slot, template) for slot in slots])
                return self.session.execute(statement)

            with patch.object(system_task_instances, "ensure_slots_initialized", new=AsyncMock()), \
                 patch.object(system_task_instances, "template_tz", return_value=timezone.utc), \
                 patch.object(system_task_instances, "template_due_time", return_value=time(10)), \
                 patch.object(system_task_instances, "next_occurrence", side_effect=lambda _, value: value + timedelta(days=1)), \
                 patch.object(system_task_instances, "_insert_system_task_instance", new=AsyncMock(return_value=True)) as insert:
                count = await system_task_instances.generate_system_task_instances(
                    SimpleNamespace(execute=execute), now_utc=day, start=day.date(), end=day.date() + timedelta(days=7))
            return count, insert.await_args_list

        count, calls = await run(now)
        self.assertEqual(count, 16)
        self.assertEqual({call.kwargs["assignee_id"] for call in calls},
                         {self.people[key].id for key in ("EF", "NONE")})
        self.assertEqual(slots[0].next_run_at, now + timedelta(days=1))

        self.people["OLD"].is_active = True
        self.session.commit()
        count, calls = await run(now + timedelta(days=1))
        self.assertEqual(count, 10)
        reactivated_calls = [call for call in calls if call.kwargs["assignee_id"] == self.people["OLD"].id]
        self.assertEqual(len(reactivated_calls), 8)
        self.assertEqual(reactivated_calls[0].kwargs["origin_run_at"], now + timedelta(days=1))

    async def test_legacy_occurrences_filter_inactive_users_with_default_fallback(self):
        for assignee_ids, default_id, expected in (
            ([self.people[key].id for key in ("OLD", "EF", "NONE", "LC")], None,
             [self.people[key].id for key in ("EF", "NONE")]),
            ([], self.people["OLD"].id, []),
            ([], self.people["EF"].id, [self.people["EF"].id]),
        ):
            template = SimpleNamespace(assignee_ids=assignee_ids, default_assignee_id=default_id)
            calls = 0

            async def execute(statement):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return SimpleNamespace(scalar_one_or_none=lambda: template)
                return self.session.execute(statement)

            self.assertEqual(await _assignee_ids_for_template(SimpleNamespace(execute=execute), uuid.uuid4()), expected)

    async def test_daily_reconciliation_skips_inactive_replacement_and_preserves_inactive_history(self):
        day = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
        for primary_key in ("EF", "OLD"):
            primary_id = self.people[primary_key].id
            template = SimpleNamespace(id=uuid.uuid4(), timezone="UTC", department_id=self.work_department.id,
                                       zv1_user_id=self.people["OLD"].id, zv2_user_id=self.people["NONE"].id)
            slot = SimpleNamespace(id=uuid.uuid4(), primary_user_id=primary_id, created_at=day)
            task = SimpleNamespace(id=uuid.uuid4(), origin_run_at=day, assigned_to=primary_id,
                                   status="TODO", is_active=True)
            leave = SimpleNamespace(description="Date: 2026-11-03 (Full day)", entry_date=day.date(),
                                    created_at=day, assigned_to_user_id=primary_id, created_by_user_id=primary_id)

            async def execute(statement):
                entity = statement.column_descriptions[0]["entity"]
                if entity is Task:
                    return SimpleNamespace(all=lambda: [(task, template, slot)])
                if entity is User:
                    return self.session.execute(statement)
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [leave]))

            with patch.object(system_task_instances, "_replace_generated_task_assignee", new=AsyncMock()) as replace:
                result = await system_task_instances.reconcile_system_task_assignments_for_day(
                    SimpleNamespace(execute=execute), target_day=day.date(), now_utc=day)
            if primary_key == "EF":
                self.assertEqual(result["reassigned"], 1)
                self.assertEqual(replace.await_args.kwargs["user_id"], self.people["NONE"].id)
            else:
                self.assertEqual(result["skipped"], 1)
                replace.assert_not_awaited()
                self.assertTrue(task.is_active)

    async def test_meeting_system_tasks_skip_inactive_users_without_removing_history(self):
        user_ids = [self.people[key].id for key in ("OLD", "EF", "NONE", "LC")]
        active_map = await _user_department_map(self.db, user_ids, active_only=True)
        self.assertEqual(set(active_map), {self.people[key].id for key in ("EF", "NONE")})
        day = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
        old_task = SimpleNamespace(assigned_to=self.people["OLD"].id, meeting_occurrence_date=day.date(),
                                   status="TODO", is_active=True)
        first_query = True

        async def execute(statement):
            nonlocal first_query
            if first_query:
                first_query = False
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [old_task]))
            return self.session.execute(statement)

        with patch("app.services.meeting_system_tasks._ensure_slot", new=AsyncMock()) as ensure_slot:
            count = await _reconcile_external_meeting_task_kind(
                SimpleNamespace(execute=execute), SimpleNamespace(id=uuid.uuid4(), starts_at=day),
                task_kind="TEST", description="Test", qualifies=True,
                participant_ids=[self.people["OLD"].id], task_title="Test",
                template=SimpleNamespace(id=uuid.uuid4()), now_utc=day)
        self.assertEqual(count, 0)
        ensure_slot.assert_not_awaited()
        self.assertTrue(old_task.is_active)
