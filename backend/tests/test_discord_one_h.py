"""Conditional 1H reports; no Discord sends or production database connections."""
import asyncio
from datetime import datetime, timedelta
import os
from types import SimpleNamespace
import unittest
import uuid
import importlib.util
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'one-h-test-only-secret')

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app import models
from app.config import settings
from app.db import Base
from app.models.discord_assistant import DiscordLink, DiscordReminder, DiscordAction
from app.models.mira_host import Mira1HMeeting, Mira1HTurn
from app.models.discord_m2_postponement import DiscordM2Postponement
from app.models.user import User
from app.services import discord_one_h as service, mira_host as host
from app.api.routers import discord_assistant as api

AT = datetime(2026, 10, 27, 10, 0, tzinfo=ZoneInfo('Europe/Budapest'))


def task(status='TODO', slot='10:00', **extra):
    return {'id': str(uuid.uuid4()), 'title': 'Oferta për klientin', 'status': status,
            'one_h_report_slot': slot, 'is_1h_report': True, **extra}


def display(report):
    return service.presentation(SimpleNamespace(id=uuid.uuid4(), day=AT.date(), bucket='10:00', one_h_report=report))


class QuestionTests(unittest.TestCase):
    def test_only_appropriate_questions_and_done_is_not_an_empty_plan(self):
        self.assertIsNone(display(service.snapshot([], AT))['current'])
        for status in ('WAITING_CLIENT', 'WAITING_CONFIRMATION'):
            self.assertEqual(display(service.snapshot([task(status)], AT))['questions'], [])
        for status, prefix in [('TODO', 'Pse s’ke vazhdu'), ('IN_PROGRESS', 'A ke me vazhdu')]:
            self.assertTrue(display(service.snapshot([task(status)], AT))['current']['question'].startswith(prefix))
        done = display(service.snapshot([task('DONE'), task('DONE')], AT))
        self.assertEqual(len(done['questions']), 1)
        self.assertEqual(done['current']['question'], service.NEXT_QUESTION)

    def test_snapshot_stays_scoped_after_rescheduling_and_new_tasks(self):
        planned, unrelated = task(), task(slot='11:00')
        report = service.snapshot([planned], AT)
        updated = service.refresh(report, [{**planned, 'one_h_report_slot': '11:00'}, unrelated, task()])
        self.assertEqual([t['id'] for t in updated['tasks']], [planned['id']])
        self.assertEqual(updated['tasks'][0]['planned_status'], 'TODO')
        removed = service.refresh(updated, [unrelated])
        self.assertEqual(display(removed)['questions'], [])
        self.assertFalse(service.all_done(removed))

    def test_answers_idempotency_corrections_skips_and_stale_status(self):
        item = task()
        report = service.snapshot([item], AT)
        answered = service.save_answer(report, item['id'], 'Pres materialet', 'Sot 14:00', '123', AT)
        self.assertEqual(report['tasks'][0]['history'], [])
        self.assertEqual(service.save_answer(answered, item['id'], 'Retry', '', '123', AT), answered)
        corrected = service.save_answer(answered, item['id'], 'Vazhdoj', '15:00', '124', AT)
        self.assertEqual(len(corrected['tasks'][0]['history']), 2)
        self.assertEqual(corrected['tasks'][0]['history'][0]['answer'], 'Pres materialet')
        skipped = service.save_answer(report, item['id'], '', '', '125', AT, skip=True)
        self.assertEqual(display(skipped)['state'], 'PARTIAL')
        self.assertIsNone(display(skipped)['current'])
        changed = service.refresh(report, [{**item, 'status': 'IN_PROGRESS'}])
        with self.assertRaises(HTTPException):
            service.save_answer(changed, item['id'], 'Old question', '', '126', AT, question_status='TODO')

    def test_last_done_task_reveals_next_slot_once(self):
        item = task()
        report = service.snapshot([item], AT)
        report = service.refresh(report, [{**item, 'status': 'DONE'}])
        self.assertEqual(display(report)['current']['id'], 'next')
        report = service.save_answer(report, 'next', 'Vazhdoj me raportin', '', '127', AT)
        self.assertIsNone(display(report)['current'])
        self.assertEqual(display(report)['state'], 'DONE')


URL = os.environ.get('ONE_H_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'Requires explicit disposable local PostgreSQL URL')
class ReportDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        parsed = make_url(URL)
        if parsed.host not in ('localhost', '127.0.0.1') or parsed.database != 'one_h_test':
            raise RuntimeError('Use only the disposable localhost one_h_test database')
        self.schema = 'one_h_' + uuid.uuid4().hex
        self.engine = create_async_engine(URL, connect_args={'server_settings': {'search_path': self.schema}})
        tables = {DiscordLink.__table__, DiscordReminder.__table__, DiscordAction.__table__,
                  Mira1HMeeting.__table__, Mira1HTurn.__table__, DiscordM2Postponement.__table__}
        while True:
            expanded = tables | {fk.column.table for t in tables for fk in t.foreign_keys}
            if expanded == tables:
                break
            tables = expanded
        async with self.engine.begin() as conn:
            await conn.execute(text('CREATE SCHEMA ' + self.schema))
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=list(tables)))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.user_ids = [uuid.uuid4(), uuid.uuid4()]
        self.actors = [api.Actor(discord_user_id=str(i + 11), guild_id='22', channel_id=str(i + 33)) for i in range(2)]
        async with self.sessions() as db:
            for i, uid in enumerate(self.user_ids):
                db.add(User(id=uid, username=f'oneh{i}', email=f'oneh{i}@example.test',
                            full_name=f'Staff {i}', password_hash='test'))
            await db.flush()
            self.links = []
            for uid, actor in zip(self.user_ids, self.actors):
                link = DiscordLink(user_id=uid, **actor.model_dump())
                db.add(link)
                self.links.append(link)
            await db.commit()
        self.items = {self.user_ids[0]: [task(), task('IN_PROGRESS', '11:00'), task('DONE')],
                      self.user_ids[1]: [task('DONE')]}
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return AT.astimezone(tz) if tz else AT.replace(tzinfo=None)
        self.patchers = [patch.object(settings, 'DISCORD_GUILD_ID', '22'),
                         patch.object(api, 'datetime', Clock), patch.object(api, 'daily_tasks', self.daily)]
        for p in self.patchers:
            p.start()

    async def daily(self, db, user, *args, **kwargs):
        return self.items[user.id]

    async def asyncTearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        async with self.engine.begin() as conn:
            await conn.execute(text('DROP SCHEMA ' + self.schema + ' CASCADE'))
        await self.engine.dispose()

    async def collect(self):
        async with self.sessions() as db:
            return (await api.claim_reminders(db))['jobs']

    async def open(self, job, who=0):
        async with self.sessions() as db:
            return await api.reminder_tasks(uuid.UUID(job['id']), self.actors[who], db)

    async def answer(self, job, request='200', text='Pres materialet', who=0, **extra):
        async with self.sessions() as db:
            return await api.answer_one_h(uuid.UUID(job['id']), api.OneHAnswer(
                **self.actors[who].model_dump(), request_id=request,
                item_id=self.items[self.user_ids[who]][0]['id'], answer=text, **extra), db)

    async def test_claim_all_staff_scope_persistence_and_mira_without_host(self):
        jobs = await self.collect()
        self.assertEqual(len(jobs), 2)  # No voice-presence prerequisite.
        self.assertEqual(await self.collect(), [])
        first = next(j for j in jobs if j['discord_user_id'] == '11')
        second = next(j for j in jobs if j['discord_user_id'] == '12')
        opened = await self.open(first)
        self.assertEqual(len(opened['one_h']['tasks']), 2)
        self.assertEqual(len(opened['one_h']['questions']), 1)
        self.assertEqual((await self.open(second, 1))['one_h']['current']['id'], 'next')
        await asyncio.gather(self.answer(first), self.answer(first))
        await self.answer(first, '201', 'Tani vazhdoj', expected_at='Sot 14:00')
        async with self.sessions() as db:
            view = await host.meeting_detail(db, service.slot_id(AT.date(), '10:00'))
            self.assertEqual(view['status'], 'DISCORD_REPORT')
            self.assertEqual(len(view['discord_reports']), 2)
            entry = view['discord_reports'][0]['tasks'][0]
            self.assertEqual(entry['answer'], 'Tani vazhdoj')
            self.assertEqual(len(entry['history']), 2)
            listed = await host.list_meetings(db, 50, 0)
            self.assertEqual(listed['total'], 1)
            self.assertEqual(len(listed['items']), 1)
            db.add(Mira1HMeeting(meeting_date=AT.date(), slot='10:00', status='DONE', host_transcript=[]))
            await db.commit()
        async with self.sessions() as db:
            listed = await host.list_meetings(db, 50, 0)
            self.assertEqual(listed['total'], 1)

    async def test_actor_isolation_reschedule_snapshot_and_action_outcomes(self):
        first = next(j for j in await self.collect() if j['discord_user_id'] == '11')
        await self.open(first)
        with self.assertRaises(HTTPException):
            await self.open(first, 1)
        with self.assertRaises(HTTPException):
            await self.answer(first, who=1)
        item = self.items[self.user_ids[0]][0]
        item['one_h_report_slot'] = '14:20'
        self.items[self.user_ids[0]].append(task())
        opened = await self.open(first)
        self.assertEqual(len(opened['one_h']['tasks']), 2)
        async with self.sessions() as db:
            action = DiscordAction(id='300', link_id=self.links[0].id, task_id=uuid.UUID(item['id']),
                instruction='Shto koment', status='PARTIAL', result={'reply': {'message': 'Shtyrja kërkon konfirmim'},
                'operations': [{'method': 'PATCH', 'path': '/api/tasks/example/comment', 'label': 'Komenti u shtua'}]})
            await service.capture_action(db, self.links[0], action, AT)
            await db.commit()
        async with self.sessions() as db:
            stored = await db.get(DiscordReminder, uuid.UUID(first['id']))
            history = stored.one_h_report['tasks'][0]['history']
            self.assertEqual(history[-1]['status'], 'PARTIAL')
            self.assertIsNone(stored.one_h_report['tasks'][0]['answer'])
            stored.day = AT.date() - timedelta(days=1)
            await db.commit()
        with self.assertRaises(HTTPException):
            await self.answer(first)

    async def test_migration_preserves_existing_reminders_and_accepts_new_answers(self):
        first = next(j for j in await self.collect() if j['discord_user_id'] == '11')
        path = Path(__file__).parents[1] / 'alembic/versions/0170_discord_one_h_reports.py'
        spec = importlib.util.spec_from_file_location('one_h_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def exercise(sync):
            from alembic.migration import MigrationContext
            from alembic.operations import Operations
            sync.execute(text('ALTER TABLE discord_reminders DROP COLUMN one_h_report'))
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()
                row = sync.execute(text('SELECT bucket, one_h_report FROM discord_reminders LIMIT 1')).one()
                self.assertEqual(row.bucket, '10:00')
                self.assertIsNone(row.one_h_report)
                migration.downgrade()
                migration.upgrade()
        async with self.engine.begin() as conn:
            await conn.run_sync(exercise)
        await self.open(first)
        result = await self.answer(first)
        self.assertEqual(result['tasks'][0]['answer'], 'Pres materialet')
