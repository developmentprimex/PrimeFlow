import asyncio
import os
import unittest
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'm2-approvals-tests')
from fastapi import HTTPException
from app.services import discord_m2_postponements as rules
from app.services.primeflow_report import report_timezone
from app.services import m2_reporting_points as reports
from app.api.routers import discord_m2_postponements as api


class ProposalRulesTests(unittest.TestCase):
    def test_frozen_migration_contains_every_model_column(self):
        from io import StringIO
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        from tests.test_migration_graph import migration_scripts
        from app.models.discord_m2_postponement import DiscordM2Postponement
        migration = migration_scripts().get_revision('0163_discord_m2_approvals').module
        output = StringIO()
        operation = Operations(MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output}))
        with patch.object(migration, 'op', operation):
            migration.upgrade()
        for column in DiscordM2Postponement.__table__.c:
            self.assertIn(column.name, output.getvalue())
        self.assertIn('uq_discord_m2_pending_task', output.getvalue())

    def test_only_selected_date_moves_and_invalid_ranges_are_rejected(self):
        today = datetime.now(report_timezone()).replace(hour=8, minute=0, second=0, microsecond=0)
        task = SimpleNamespace(start_date=today, due_date=today + timedelta(days=4))
        result = rules.proposed_dates(task, 'start', {'start_date': today + timedelta(days=1)}, 'OTHER', 'Why')
        self.assertEqual(set(result), {'start_date'})
        with self.assertRaises(HTTPException):
            rules.proposed_dates(task, 'start', {'start_date': today + timedelta(days=5)}, 'OTHER', 'Why')
        for values in ({}, {'due_date': today + timedelta(days=1)}, {'start_date': today}):
            with self.assertRaises(HTTPException):
                rules.proposed_dates(task, 'start', values, 'OTHER', 'Why')
        with self.assertRaises(HTTPException):
            rules.proposed_dates(task, 'due', {'due_date': today + timedelta(days=5)}, 'OTHER', ' ')

    def test_stale_dates_owners_or_completed_work_cannot_be_approved(self):
        row = {'id': 'a', 'start_date': 'old', 'due_date': 'old', 'owners': ['u'], 'status': 'TODO', 'active': True}
        rules.assert_snapshot_unchanged([row], [row])
        for changed in ({**row, 'due_date': 'new'}, {**row, 'owners': ['other']}, {**row, 'status': 'DONE'}, {**row, 'active': False}):
            with self.assertRaises(HTTPException):
                rules.assert_snapshot_unchanged([row], [changed])

    def test_pm_continuation_uses_pm_tasks_in_today_range(self):
        day = date(2026, 10, 6)
        # Keep unittest deployment checks independent of pytest test modules.
        items = [SimpleNamespace(
            id=uuid.uuid4(), title='EF: Detyre', status=status, progress_percentage=0,
            created_at=day, start_date=day, due_date=day, completed_at=None,
            is_deadline_important=False, one_h_marker=None, finish_period=period,
        ) for period, status in [('AM', 'TODO'), ('PM', 'TODO'), ('PM', 'DONE')]]
        rows = reports.select_task_sections(items, [], day)['pm_continuation']
        self.assertEqual([row['task_id'] for row in rows], [str(items[1].id)])

    def test_date_form_preserves_time_and_only_asks_selected_fields(self):
        import discord_m2_approvals as client
        async def check():
            job = {'id': str(uuid.uuid4()), 'live_dates': {}}
            for kind, count in [('start', 1), ('due', 1), ('start_due', 2)]:
                modal = client.ProposalModal(None, job, kind, 'OTHER')
                self.assertEqual(len(modal.dates), count)
                self.assertTrue(modal.comment.required)
            self.assertEqual(datetime.fromisoformat(client.parse_date('27.10.2026', '2026-10-26T14:20:00+01:00')).hour, 14)
        asyncio.run(check())


from tests import test_discord_m2_database as fixtures
from sqlalchemy import select, func
from app.models.discord_m2_postponement import DiscordM2Postponement as Request
from app.models.task import Task
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_planner_exclusion import TaskPlannerExclusion
from app.models.task_alignment_user import TaskAlignmentUser


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Set M2_TEST_DATABASE_URL for isolated PostgreSQL schemas')
class ApprovalDatabaseTests(unittest.IsolatedAsyncioTestCase):
    extra_tables = {DailyPlanAdjustment.__table__, TaskDailyProgress.__table__, TaskPlannerExclusion.__table__, TaskAlignmentUser.__table__}
    asyncTearDown = fixtures.M2DatabaseTests.asyncTearDown
    fresh_data = fixtures.M2DatabaseTests.fresh_data
    claim = fixtures.M2DatabaseTests.claim

    async def asyncSetUp(self):
        await fixtures.M2DatabaseTests.asyncSetUp(self)
        async with self.sessions() as db:
            approver = await db.get(User, self.uid2)
            approver.username, approver.full_name = 'diellza.veliu', 'Diellza Veliu'
            task = await db.get(Task, self.task_id)
            task.finish_period = 'PM'
            await db.commit()
        self.data = {'pm_continuation': [{'task_id': str(self.task_id), 'title': 'PM test', 'status': 'TODO'}]}
        self.qid = (await self.claim())[0]['id']
        self.reviewer = {'discord_user_id': '44', 'guild_id': '22', 'channel_id': '55'}

    async def request(self, request_id='100'):
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            return await api.propose(uuid.UUID(self.qid), api.Proposal(**self.actor.model_dump(), request_id=request_id,
                change_kind='start_due', start_date=task.start_date + timedelta(days=1), due_date=task.due_date + timedelta(days=1),
                reason_code='MISSING_INFORMATION', comment='Waiting for information'), db)

    async def decide(self, rid, decision='APPROVED', actor=None):
        async with self.sessions() as db:
            from app.api.routers import tasks
            # Baseline capture is covered separately; retain the actual normal task
            # mutation, date validation, semantic events, and one atomic commit.
            with patch.object(tasks, 'ensure_daily_baselines_for_departments', AsyncMock()), \
                 patch.object(reports, 'refresh_report', AsyncMock()):
                return await api.decide(uuid.UUID(rid), api.Decision(**(actor or self.reviewer), decision=decision), db)

    async def test_pending_and_rejected_requests_do_not_change_task_dates(self):
        async with self.sessions() as db:
            original = (await db.get(Task, self.task_id)).due_date
        request = await self.request()
        self.assertEqual(request['status'], 'PENDING')
        with self.assertRaises(HTTPException) as raised:
            await self.decide(request['id'], actor=self.actor.model_dump())
        self.assertEqual(raised.exception.status_code, 403)
        result = await self.decide(request['id'], 'REJECTED')
        self.assertEqual(result['status'], 'REJECTED')
        async with self.sessions() as db:
            self.assertEqual((await db.get(Task, self.task_id)).due_date, original)
            self.assertEqual((await db.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == 'task.due_date_changed'))).scalar_one(), 0)

    async def test_approval_applies_once_through_normal_task_flow(self):
        request = await self.request()
        result = await self.decide(request['id'])
        self.assertEqual(result['status'], 'APPROVED')
        self.assertEqual((await self.decide(request['id']))['status'], 'APPROVED')
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            self.assertEqual(rules.iso(task.due_date), request['proposed_dates']['due_date'])
            events = (await db.execute(select(AuditLog).where(AuditLog.entity_id == self.task_id,
                AuditLog.action.in_(['task.due_date_changed', 'task.start_date_changed'])))).scalars().all()
            self.assertEqual(len(events), 2)
            self.assertTrue(all(event.after['comment'] == 'Waiting for information' for event in events))
            adjustments = (await db.execute(select(DailyPlanAdjustment).where(DailyPlanAdjustment.task_id == self.task_id))).scalars().all()
            self.assertTrue(adjustments)
            self.assertTrue(all(item.status == 'APPROVED' for item in adjustments))

    async def test_external_date_edit_makes_approval_stale_without_overwriting_it(self):
        request = await self.request()
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.due_date += timedelta(days=3)
            external = task.due_date
            await db.commit()
        result = await self.decide(request['id'])
        self.assertEqual(result['status'], 'STALE')
        async with self.sessions() as db:
            self.assertEqual((await db.get(Task, self.task_id)).due_date, external)

    async def test_notification_queue_routes_review_and_updates_existing_question(self):
        request = await self.request()
        async with self.sessions() as db:
            jobs = (await api.claim_notifications(db))['jobs']
        self.assertEqual([(job['role'], job['discord_user_id']) for job in jobs], [('review', '44')])
        async with self.sessions() as db:
            await api.acknowledge(uuid.UUID(request['id']), api.NotificationReceipt(
                **self.reviewer, role='review', message_id='12345'), db)
        await self.decide(request['id'], 'REJECTED')
        async with self.sessions() as db:
            jobs = (await api.claim_notifications(db))['jobs']
        self.assertEqual([(job['role'], job['discord_user_id']) for job in jobs], [('requester', '11')])
        self.assertEqual(jobs[0]['question']['postponement']['status'], 'REJECTED')
        async with self.sessions() as db:
            await api.acknowledge(uuid.UUID(request['id']), api.NotificationReceipt(
                **self.actor.model_dump(), role='requester', message_id='67890'), db)
        async with self.sessions() as db:
            jobs = (await api.claim_notifications(db))['jobs']
        self.assertEqual([(job['role'], job['message_id']) for job in jobs], [('review_update', '12345')])

    async def test_pm_answer_saves_separately_without_changing_dates(self):
        from app.api.routers import discord_m2 as questions
        from app.models.m2_reporting_points import M2ReportingPointsReport
        from app.models.task_daily_rlz_state import TaskDailyRlzState
        async with self.sessions() as db:
            original = (await db.get(Task, self.task_id)).due_date
            await questions.answer(uuid.UUID(self.qid), questions.Answer(
                **self.actor.model_dump(), choice='PO', comment=''), db)
        async with self.sessions() as db:
            report = (await db.execute(select(M2ReportingPointsReport))).scalar_one()
            self.assertEqual(report.manual_answers[f'pm_choice:{self.task_id}'], 'PO')
            self.assertNotIn(f'delivery_choice:{self.task_id}', report.manual_answers)
            self.assertEqual((await db.get(Task, self.task_id)).due_date, original)
            self.assertEqual((await db.execute(select(func.count()).select_from(TaskDailyRlzState))).scalar_one(), 0)
