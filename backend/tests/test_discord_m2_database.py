"""Exercise M2 transactions in an isolated, disposable PostgreSQL schema."""
import asyncio
import copy
import os
import unittest
import uuid
from datetime import datetime, time, timezone
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'discord-m2-database-tests-not-for-production')

from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app import models
from app.db import Base
from app.config import settings
from app.api.routers import discord_m2 as api
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.discord_assistant import DiscordLink
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_user_comment import TaskUserComment
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.user import User
from app.models.department import Department
from app.models.audit_log import AuditLog
from app.services.primeflow_report import report_timezone


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Set M2_TEST_DATABASE_URL for isolated-schema PostgreSQL checks')
class M2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = 'discord_m2_test_' + uuid.uuid4().hex
        self.engine = create_async_engine(os.environ['M2_TEST_DATABASE_URL'], connect_args={
            'server_settings': {'search_path': self.schema}})
        tables = {Question.__table__, M2ReportingPointsReport.__table__, TaskDailyRlzState.__table__,
                  TaskUserComment.__table__, TaskAssignee.__table__, AuditLog.__table__}
        while True:
            expanded = tables | {fk.column.table for table in tables for fk in table.foreign_keys}
            if expanded == tables:
                break
            tables = expanded
        async with self.engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA {self.schema}'))
            await connection.run_sync(lambda conn: Base.metadata.create_all(conn, tables=list(tables)))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.day = datetime.now(report_timezone()).date()
        self.uid, self.uid2, self.task_id, self.link_id = [uuid.uuid4() for _ in range(4)]
        self.actor = api.Actor(discord_user_id='11', guild_id='22', channel_id='33')
        async with self.sessions() as db:
            department = Department(name='M2 test', code='M2TEST')
            db.add(department)
            await db.flush()
            db.add_all([User(id=self.uid, username='m2one', email='m2one@example.test', password_hash='test',
                             full_name='First Person', department_id=department.id),
                        User(id=self.uid2, username='m2two', email='m2two@example.test', password_hash='test',
                             full_name='Second Person', department_id=department.id)])
            await db.flush()
            db.add(Task(id=self.task_id, title='Test M2', assigned_to=self.uid, status='TODO', is_active=True,
                        start_date=datetime.combine(self.day, time(8), report_timezone()),
                        due_date=datetime.combine(self.day, time(16), report_timezone()),
                        finish_period='AM', one_h_marker='M2'))
            await db.flush()
            db.add(DiscordLink(id=self.link_id, user_id=self.uid, discord_user_id='11', guild_id='22', channel_id='33'))
            db.add(DiscordLink(user_id=self.uid2, discord_user_id='44', guild_id='22', channel_id='55'))
            db.add(TaskUserComment(task_id=self.task_id, user_id=self.uid, comment='Existing task comment'))
            await db.commit()
        self.data = {'unfinished_priority': [{'task_id': str(self.task_id), 'title': 'Test M2', 'status': 'TODO'}]}
        self.patchers = [patch.object(settings, 'DISCORD_GUILD_ID', '22'),
                         patch.object(api.service, 'collection_open', return_value=True),
                         patch.object(api, 'data_with_moves', new=self.fresh_data)]
        for patcher in self.patchers:
            patcher.start()

    async def fresh_data(self, *args):
        return copy.deepcopy(self.data)

    async def asyncTearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        async with self.engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))
        await self.engine.dispose()

    async def claim(self):
        async with self.sessions() as db:
            return (await api.claim(db))['jobs']

    async def reply(self, qid, **fields):
        async with self.sessions() as db:
            return await api.answer(uuid.UUID(qid), api.Answer(**self.actor.model_dump(), **fields), db)

    async def test_claim_is_durable_and_concurrent_replies_append_once(self):
        jobs = await self.claim()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(await self.claim(), [])
        qid = jobs[0]['id']
        await asyncio.gather(*(self.reply(qid, reason_code='MISSING_INFORMATION', comment='Need dimensions') for _ in range(2)))
        async with self.sessions() as db:
            comment = (await db.execute(select(TaskUserComment.comment))).scalar_one()
            self.assertEqual(comment.count('Need dimensions'), 1)
            self.assertTrue(comment.startswith('Existing task comment'))
            evidence = (await db.execute(select(TaskDailyRlzState))).scalar_one()
            self.assertEqual(evidence.reason_code, 'MISSING_INFORMATION')
            report = (await db.execute(select(M2ReportingPointsReport))).scalar_one()
            self.assertIn('First Person: Need dimensions', report.manual_answers[f'unfinished_comment:{self.task_id}'])
            self.assertEqual((await db.execute(select(func.count()).select_from(AuditLog))).scalar_one(), 1)

    async def test_reassignment_and_old_postponement_cannot_receive_a_reply(self):
        self.data = {'postponed': [{'task_id': str(self.task_id), 'title': 'Moved', 'status': 'TODO',
                                  'postponement_kind': 'due', 'old_due_date': str(self.day), 'due_date': '2099-01-01'}]}
        qid = (await self.claim())[0]['id']
        self.data['postponed'][0]['due_date'] = '2099-01-02'
        with self.assertRaises(HTTPException) as raised:
            await self.reply(qid, reason_code='OTHER', comment='Old move')
        self.assertEqual(raised.exception.status_code, 409)
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.assigned_to = self.uid2
            await db.commit()
        with self.assertRaises(HTTPException) as raised:
            await self.reply(qid, reason_code='OTHER', comment='No longer mine')
        self.assertEqual(raised.exception.status_code, 403)

    async def test_shared_delivery_waits_for_every_person_and_no_requires_comment(self):
        self.data = {'delivery': [{'task_id': str(self.task_id), 'title': 'Delivery', 'status': 'TODO'}]}
        async with self.sessions() as db:
            db.add(TaskAssignee(task_id=self.task_id, user_id=self.uid2))
            await db.commit()
        jobs = await self.claim()
        self.assertEqual(len(jobs), 2)
        qid = next(item['id'] for item in jobs if item['discord_user_id'] == '11')
        with self.assertRaises(HTTPException) as raised:
            await self.reply(qid, choice='JO')
        self.assertEqual(raised.exception.status_code, 422)
        await self.reply(qid, choice='PO')
        async with self.sessions() as db:
            report = (await db.execute(select(M2ReportingPointsReport))).scalar_one()
            self.assertEqual(report.manual_answers[f'delivery_choice:{self.task_id}'], '')
        self.actor = api.Actor(discord_user_id='44', guild_id='22', channel_id='55')
        qid = next(item['id'] for item in jobs if item['discord_user_id'] == '44')
        await self.reply(qid, choice='JO', comment='Awaiting review')
        async with self.sessions() as db:
            report = (await db.execute(select(M2ReportingPointsReport))).scalar_one()
            self.assertEqual(report.manual_answers[f'delivery_choice:{self.task_id}'], 'JO')
            self.assertIn('Second Person: Awaiting review', report.manual_answers[f'delivery:{self.task_id}'])

    async def test_delivery_can_change_from_no_to_yes_and_preserves_history(self):
        self.data = {'delivery': [{'task_id': str(self.task_id), 'title': 'Delivery', 'status': 'TODO'}]}
        qid = (await self.claim())[0]['id']
        await self.reply(qid, choice='JO', comment='Not ready yet', expected_answered_at=None)
        async with self.sessions() as db:
            previous_stamp = (await db.get(Question, uuid.UUID(qid))).answered_at
        with patch.object(api, 'data_with_moves', side_effect=AssertionError('Delivery must not rebuild the company report')):
            await self.reply(qid, choice='PO', comment='', expected_answered_at=previous_stamp)
        # A repeated submit is harmless, but an old form cannot undo the newer answer.
        await self.reply(qid, choice='PO', comment='', expected_answered_at=previous_stamp)
        with self.assertRaises(HTTPException) as raised:
            await self.reply(qid, choice='JO', comment='Stale form', expected_answered_at=previous_stamp)
        self.assertEqual(raised.exception.status_code, 409)
        async with self.sessions() as db:
            question = await db.get(Question, uuid.UUID(qid))
            self.assertEqual(question.choice, 'PO')
            report = (await db.execute(select(M2ReportingPointsReport))).scalar_one()
            self.assertEqual(report.manual_answers[f'delivery_choice:{self.task_id}'], 'PO')
            self.assertNotIn('Not ready yet', report.manual_answers[f'delivery:{self.task_id}'])
            comment = (await db.execute(select(TaskUserComment.comment))).scalar_one()
            self.assertIn('Not ready yet', comment)
            self.assertEqual(comment.count('Dorëzuar: PO'), 1)
            events = (await db.execute(select(AuditLog).order_by(AuditLog.created_at))).scalars().all()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[-1].before['choice'], 'JO')
            self.assertEqual(events[-1].after['choice'], 'PO')

    async def test_delivery_rechecks_current_task_membership_without_a_report_rebuild(self):
        self.data = {'delivery': [{'task_id': str(self.task_id), 'title': 'Delivery', 'status': 'TODO'}]}
        qid = (await self.claim())[0]['id']
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.one_h_marker = 'M3'
            await db.commit()
        with patch.object(api, 'data_with_moves', side_effect=AssertionError('Must use current task selector')):
            with self.assertRaises(HTTPException) as raised:
                await self.reply(qid, choice='PO')
        self.assertEqual(raised.exception.status_code, 409)
