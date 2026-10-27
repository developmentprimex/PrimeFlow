import asyncio
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.api.routers import discord_answer_sync as api
from app.api.routers import discord_m2 as questions
from app.api.routers import m2_reporting_points as report_api
from app.services import discord_answer_sync as service
from app.models.discord_assistant import DiscordMeetingAlert as Alert
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus as Status
from app.models.m2_reporting_points import M2ReportingPointsReport as Report
from app.models.task_daily_rlz_state import TaskDailyRlzState as State
from app.models.user import User
from tests import test_discord_m2_database as fixtures


class SyncClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_edits_only_existing_message_and_hides_comments(self):
        import discord_answer_sync as client
        job = {'id': str(uuid.uuid4()), 'source': 'm2', 'fingerprint': 'a' * 64,
            'guild_id': '22', 'channel_id': '33', 'discord_user_id': '11', 'message_id': '555',
            'payload': {'id': 'q', 'kind': 'delivery', 'task_id': str(uuid.uuid4()), 'snapshot': {'title': 'Delivery'},
                'platform_status': 'Përgjigjja u plotësua në PrimeFlow.', 'platform_answered': True,
                'choice': 'PO', 'comment': 'private comment'}}
        message = SimpleNamespace(edit=AsyncMock())
        bot = SimpleNamespace(bridge=AsyncMock(side_effect=[{'job': job}, {'ok': True}]),
            private_channel=AsyncMock(return_value=SimpleNamespace(fetch_message=AsyncMock(return_value=message))),
            http=SimpleNamespace(request=AsyncMock()))
        await client.update_one(bot, job)
        result = message.edit.call_args.kwargs
        self.assertIn('Dorëzuar: PO', result['content'])
        self.assertNotIn('private comment', result['content'])
        self.assertTrue(all(getattr(item, 'url', None) for item in result['view'].children))
        bot.http.request.assert_not_called()
        self.assertEqual(bot.bridge.call_args.args[0].split('/')[-1], 'ack')

    def test_migration_adds_every_sync_column(self):
        from io import StringIO
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        from tests.test_migration_graph import migration_scripts
        output = StringIO()
        operation = Operations(MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output}))
        migration = migration_scripts().get_revision('0168_discord_answer_sync').module
        with patch.object(migration, 'op', operation):
            migration.upgrade()
        for column in ('platform_answer', 'platform_answered_at', 'sync_hash', 'sync_pending_hash', 'sync_lease_until'):
            self.assertIn(column, output.getvalue())


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL schema')
class SyncDatabaseTests(unittest.IsolatedAsyncioTestCase):
    extra_tables = {Alert.__table__, Status.__table__, Meeting.__table__}
    asyncTearDown = fixtures.M2DatabaseTests.asyncTearDown
    fresh_data = fixtures.M2DatabaseTests.fresh_data
    claim_questions = fixtures.M2DatabaseTests.claim

    async def asyncSetUp(self):
        await fixtures.M2DatabaseTests.asyncSetUp(self)
        self.qid = uuid.UUID((await self.claim_questions())[0]['id'])
        async with self.sessions() as db:
            q = await db.get(Question, self.qid)
            q.sent_at, q.message_id = datetime.now(timezone.utc) - timedelta(minutes=1), '555'
            self.mid, self.aid = uuid.uuid4(), uuid.uuid4()
            owner = await db.get(User, self.uid)
            db.add(Meeting(id=self.mid, title='AM meeting', department_id=owner.department_id, meeting_type='internal'))
            await db.flush()
            db.add(Alert(id=self.aid, link_id=self.link_id, meeting_id=self.mid, kind='m2_after',
                occurrence_starts_at=q.sent_at, lease_until=q.sent_at, sent_at=q.sent_at, message_id='666'))
            await db.commit()

    async def jobs(self):
        async with self.sessions() as db:
            return (await api.claim(db))['jobs']

    async def acknowledge(self, job):
        async with self.sessions() as db:
            await api.ack(job['source'], uuid.UUID(job['id']), api.Receipt(**self.actor.model_dump(), fingerprint=job['fingerprint']), db)

    async def test_web_report_answer_closes_question_and_clearing_it_restores_controls(self):
        self.assertEqual(await self.jobs(), [])
        key = f'unfinished_comment:{self.task_id}'
        async with self.sessions() as db:
            report = (await db.execute(select(Report))).scalar_one()
            user = await db.get(User, self.uid)
            await report_api.save_answers(report.id, report_api.ManualAnswersPayload(manual_answers={key: 'Waiting for information'}), db, user)
        jobs = await self.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertIn('platform_status', jobs[0]['payload'])
        self.assertEqual(await self.jobs(), [])
        await self.acknowledge(jobs[0])
        self.assertEqual(await self.jobs(), [])
        async with self.sessions() as db:
            report = (await db.execute(select(Report))).scalar_one()
            user = await db.get(User, self.uid)
            await report_api.save_answers(report.id, report_api.ManualAnswersPayload(manual_answers={key: ''}), db, user)
        jobs = await self.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertNotIn('platform_status', jobs[0]['payload'])

    async def test_manual_postponement_note_is_independent_but_real_reason_closes(self):
        async with self.sessions() as db:
            q = await db.get(Question, self.qid)
            q.kind = 'postponed'
            report = (await db.execute(select(Report))).scalar_one()
            key = f'postponed_comment:{self.task_id}'
            report.manual_answers = {key: 'Independent review'}
            await service.capture_report_changes(db, report, {}, report.manual_answers)
            await db.commit()
        self.assertEqual(await self.jobs(), [])
        async with self.sessions() as db:
            db.add(State(task_id=self.task_id, user_id=self.uid, day_date=self.day,
                reason_code='OTHER', comment='Actual task explanation'))
            await db.commit()
        jobs = await self.jobs()
        self.assertIn('Arsyeja dhe komenti', jobs[0]['payload']['platform_status'])

    async def test_platform_meeting_status_changes_and_removed_status_reopen_same_message(self):
        async with self.sessions() as db:
            db.add(Status(meeting_id=self.mid, occurrence_date=self.day, status='held', checked_by_user_id=self.uid))
            await db.commit()
        job = (await self.jobs())[0]
        self.assertEqual(job['source'], 'meeting')
        self.assertEqual(job['payload']['status'], 'held')
        await self.acknowledge(job)
        async with self.sessions() as db:
            status = (await db.execute(select(Status))).scalar_one()
            status.status = 'canceled'
            await db.commit()
        job = (await self.jobs())[0]
        self.assertEqual(job['payload']['status'], 'canceled')
        await self.acknowledge(job)
        async with self.sessions() as db:
            status = (await db.execute(select(Status))).scalar_one()
            status.status = ''
            await db.commit()
        self.assertEqual((await self.jobs())[0]['payload']['status'], '')

    async def test_reassigned_question_is_closed_and_revoked_link_is_never_delivered(self):
        from app.models.task import Task
        from app.models.discord_assistant import DiscordLink
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.assigned_to = self.uid2
            await db.commit()
        job = (await self.jobs())[0]
        self.assertIn('Përgjegjësit', job['payload']['platform_status'])
        async with self.sessions() as db:
            link = await db.get(DiscordLink, self.link_id)
            link.enabled = False
            await db.commit()
        self.assertEqual(await self.jobs(), [])
