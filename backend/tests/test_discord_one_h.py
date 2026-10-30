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
from app.models.task import Task
from app.models.task_user_comment import TaskUserComment
from app.services import discord_one_h as service, mira_host as host
from app.api.routers import discord_assistant as api

AT = datetime(2026, 10, 27, 10, 0, tzinfo=ZoneInfo('Europe/Budapest'))


def task(status='TODO', slot='10:00', **extra):
    return {'id': str(uuid.uuid4()), 'title': 'Oferta për klientin', 'status': status,
            'one_h_report_slot': slot, 'is_1h_report': True, **extra}


def display(report):
    return service.presentation(SimpleNamespace(id=uuid.uuid4(), day=AT.date(), bucket='10:00', one_h_report=report))


class QuestionTests(unittest.TestCase):
    def test_live_updates_keep_original_answers_and_plan(self):
        original = task('IN_PROGRESS', title='Titulli i vjetër')
        report = service.save_answer(service.snapshot([original], AT), original['id'], 'Vazhdoj', '', '1', AT)
        refreshed = service.refresh(report, [{**original, 'title': 'Titulli i ri', 'status': 'DONE',
            'progress_percentage': 100, 'user_comment': 'Përfunduar'}])
        entry = refreshed['tasks'][0]
        self.assertEqual(entry['status'], 'DONE')
        self.assertEqual(entry['title'], 'Titulli i ri')
        self.assertEqual(entry['planned_title'], 'Titulli i vjetër')
        self.assertEqual(entry['planned_status'], 'IN_PROGRESS')
        self.assertEqual(entry['progress_percentage'], 100)
        self.assertEqual(entry['comment'], 'Përfunduar')
        self.assertEqual(entry['answer'], 'Vazhdoj')
        self.assertEqual(entry['history'], report['tasks'][0]['history'])

    def test_only_appropriate_questions_and_done_is_not_an_empty_plan(self):
        self.assertIsNone(display(service.snapshot([], AT))['current'])
        for status in ('WAITING_CLIENT', 'WAITING_CONFIRMATION'):
            questions = display(service.snapshot([task(status)], AT))['questions']
            self.assertEqual([q['id'] for q in questions], ['next'])
        for status, prefix in [('TODO', 'Pse s’ke vazhdu'), ('IN_PROGRESS', 'A ke me vazhdu')]:
            self.assertTrue(display(service.snapshot([task(status)], AT))['current']['question'].startswith(prefix))
        done = display(service.snapshot([task('DONE'), task('DONE')], AT))
        self.assertEqual(len(done['questions']), 1)
        self.assertIsNone(done['current'])
        self.assertEqual(done['questions'][0]['question'], service.NEXT_QUESTION)

    def test_snapshot_stays_scoped_after_rescheduling_and_new_tasks(self):
        planned, unrelated = task(), task(slot='11:00')
        report = service.snapshot([planned], AT)
        updated = service.refresh(report, [{**planned, 'one_h_report_slot': '11:00'}, unrelated, task()])
        self.assertEqual([t['id'] for t in updated['tasks']], [planned['id']])
        self.assertEqual(updated['tasks'][0]['planned_status'], 'TODO')
        removed = service.refresh(updated, [unrelated])
        self.assertEqual([q['id'] for q in display(removed)['questions']], ['next'])
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

    def test_next_slot_is_available_before_any_task_is_reported(self):
        item = task()
        report = service.snapshot([item], AT)
        self.assertEqual(display(report)['questions'][-1]['id'], 'next')
        report = service.save_answer(report, 'next', 'Vazhdoj me raportin', '', '127', AT)
        self.assertEqual(display(report)['state'], 'PARTIAL')
        self.assertIsNotNone(display(report)['current'])
        report = service.refresh(report, [{**item, 'status': 'DONE'}])
        self.assertIsNone(display(report)['current'])
        self.assertEqual(display(report)['state'], 'DONE')

    def test_completion_time_only_for_due_today_in_application_timezone(self):
        for due, expected in [('2026-10-27', True), ('2026-10-30', False),
                              ('2026-10-26T23:30:00Z', True), ('2026-10-27T23:30:00Z', False),
                              ('2026-10-26', False), (None, False), ('invalid', False)]:
            with self.subTest(due=due):
                report = service.snapshot([task('IN_PROGRESS', due_date=due)], AT)
                item = display(report)['current']
                self.assertEqual('Kur pritet me u kry?' in item['question'], expected)
                self.assertEqual(item['asks_completion'], expected)
        item = task('IN_PROGRESS', due_date='2026-10-27')
        report = service.refresh(service.snapshot([item], AT), [{**item, 'due_date': '2026-10-30'}])
        with self.assertRaises(HTTPException):
            service.save_answer(report, item['id'], 'Po', '', '500', AT, asks_completion=True)

    def test_next_options_include_current_later_and_unfinished_earlier_tasks(self):
        current, later, earlier = task('IN_PROGRESS', '11:00'), task('TODO', '14:20'), task('TODO', '10:00')
        ongoing = task('IN_PROGRESS', '10:00')
        excluded = [task('DONE', '14:20'), task('WAITING_CLIENT', '16:00'), task('TODO', None),
                    task('TODO', '16:00', is_active=False)]
        options = service.next_options([*excluded, earlier, later, current, ongoing, current], '11:00')
        self.assertEqual([t['id'] for t in options], [ongoing['id'], current['id'], later['id'], earlier['id']])
        self.assertEqual([t['group'] for t in options], ['CURRENT', 'CURRENT', 'LATER', 'UNSTARTED'])

    def test_empty_later_slots_offer_earlier_ongoing_work_until_finished(self):
        ongoing = task('IN_PROGRESS', '10:00')
        for slot in service.SLOTS[1:]:
            with self.subTest(slot=slot):
                report = service.refresh(service.snapshot([], AT, slot=slot), [ongoing])
                self.assertEqual(report['tasks'], [])
                self.assertEqual(report['next_options'], [{
                    'id': ongoing['id'], 'title': ongoing['title'], 'slot': '10:00',
                    'status': 'IN_PROGRESS', 'group': 'CURRENT'}])
                selected = service.save_next_choices(report, [ongoing['id']], 'carry-forward', AT,
                    options_key=service.next_options_key(report))
                self.assertEqual(selected['next']['selected_tasks'][0]['id'], ongoing['id'])
                finished = service.refresh(selected, [{**ongoing, 'status': 'DONE'}])
                self.assertEqual(finished['next_options'], [])
                self.assertEqual(len(finished['next']['history']), 1)

    def test_selection_preserves_other_pages_history_and_never_changes_tasks(self):
        tasks = [task(title=f'Task {i:02d}', slot='11:00') for i in range(31)]
        report = service.refresh(service.snapshot([], AT), tasks)
        choices = report['next_options']
        selected = service.save_next_choices(report, [choices[0]['id']], '600', AT)
        selected = service.save_next_choices(selected, [choices[30]['id']], '601', AT, page=1)
        self.assertEqual(len(selected['next']['selected_tasks']), 2)
        self.assertEqual(len(selected['next']['history']), 2)
        self.assertEqual(selected['tasks'], [])
        self.assertTrue(all(t['status'] == 'TODO' and t['one_h_report_slot'] == '11:00' for t in tasks))
        retry = service.save_next_choices(selected, [], '601', AT, page=1)
        self.assertEqual(retry, selected)
        cleared = service.save_next_choices(selected, [], '602', AT, page=1)
        self.assertEqual([t['id'] for t in cleared['next']['selected_tasks']], [choices[0]['id']])
        none = service.save_next_choices(cleared, [], '603', AT, none=True)
        self.assertEqual(none['next']['selection_kind'], 'NONE')
        self.assertEqual(none['next']['selected_tasks'], [])
        other = service.save_answer(none, 'next', 'Telefonatë me klientin', '', '604', AT)
        self.assertEqual(other['next']['selection_kind'], 'OTHER')
        with self.assertRaises(HTTPException):
            service.save_next_choices(report, [str(uuid.uuid4())], '605', AT)
        with self.assertRaises(HTTPException):
            service.save_next_choices(report, [choices[0]['id']], '606', AT, options_key='0' * 16)


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
                  Mira1HMeeting.__table__, Mira1HTurn.__table__, DiscordM2Postponement.__table__,
                  TaskUserComment.__table__, models.TaskAssignee.__table__}
        tables.add(models.TaskOneHReportSlot.__table__)
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
        async with self.sessions() as db:
            for uid, items in self.items.items():
                for item in items:
                    db.add(Task(id=uuid.UUID(item['id']), title=item['title'], assigned_to=uid,
                                status=item['status'], is_active=True))
            await db.commit()
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
        self.assertEqual(len(opened['one_h']['questions']), 2)
        self.assertEqual((await self.open(second, 1))['one_h']['questions'][-1]['id'], 'next')
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
            comment = (await db.execute(select(TaskUserComment).where(
                TaskUserComment.task_id == uuid.UUID(self.items[self.user_ids[0]][0]['id'])))).scalar_one()
            self.assertEqual(comment.comment.count('Pres materialet'), 1)
            self.assertIn('Tani vazhdoj', comment.comment)
            self.assertIn('Sot 14:00', comment.comment)
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

    async def test_combined_report_preserves_comment_and_blank_continuation_keeps_selection(self):
        first = next(j for j in await self.collect() if j['discord_user_id'] == '11')
        await self.open(first)
        tid = uuid.UUID(self.items[self.user_ids[0]][0]['id'])
        async with self.sessions() as db:
            db.add(TaskUserComment(task_id=tid, user_id=self.user_ids[0], comment='Komenti i mëparshëm'))
            await db.commit()
        saved = await self.answer(first, continuation='Pastaj testoj ofertën')
        self.assertEqual(saved['next']['answer'], 'Pastaj testoj ofertën')
        await self.answer(first, '201', 'Vazhdoj tani', continuation='')
        # A delayed retry must leave the later correction and comment untouched.
        retry = await self.answer(first, continuation='Retry')
        self.assertEqual(retry['tasks'][0]['answer'], 'Vazhdoj tani')
        self.assertEqual(retry['next']['answer'], 'Pastaj testoj ofertën')
        async with self.sessions() as db:
            comment = (await db.execute(select(TaskUserComment.comment).where(TaskUserComment.task_id == tid))).scalar_one()
            self.assertTrue(comment.startswith('Komenti i mëparshëm\n\n'))
            self.assertIn('Vazhdimi: Pastaj testoj ofertën', comment)
            self.assertEqual(comment.count('Pres materialet'), 1)
            self.assertNotIn('Retry', comment)

    async def test_comment_failure_rolls_back_both_report_and_comment(self):
        from app.api.routers import tasks as task_api
        first = next(j for j in await self.collect() if j['discord_user_id'] == '11')
        await self.open(first)
        real = task_api.update_task_user_comment_in_session
        async def fail_after_comment(*args, **kwargs):
            await real(*args, **kwargs)
            await args[2].flush()
            raise RuntimeError('Simulated failure before commit')
        with patch.object(task_api, 'update_task_user_comment_in_session', fail_after_comment):
            with self.assertRaises(RuntimeError):
                await self.answer(first, continuation='Pastaj testoj')
        async with self.sessions() as db:
            report = await db.get(DiscordReminder, uuid.UUID(first['id']))
            self.assertIsNone(report.one_h_report['tasks'][0]['answer'])
            self.assertIsNone(report.one_h_report['next']['answer'])
            self.assertEqual((await db.execute(select(TaskUserComment))).scalars().all(), [])

    async def test_task_comment_rechecks_current_assignment(self):
        first = next(j for j in await self.collect() if j['discord_user_id'] == '11')
        await self.open(first)
        async with self.sessions() as db:
            item = await db.get(Task, uuid.UUID(self.items[self.user_ids[0]][0]['id']))
            item.assigned_to = self.user_ids[1]
            await db.commit()
        with self.assertRaises(HTTPException) as error:
            await self.answer(first)
        self.assertEqual(error.exception.status_code, 403)

    async def test_sync_revisions_follow_platform_changes_and_respect_links(self):
        jobs = await self.collect()
        first = next(j for j in jobs if j['discord_user_id'] == '11')
        await self.open(first)
        async with self.sessions() as db:
            row = await db.get(DiscordReminder, uuid.UUID(first['id']))
            row.sent_at, row.message_ids = AT, ['900', '901']
            await db.commit()
        async with self.sessions() as db:
            original = await service.sync_jobs(db, AT)
            self.assertEqual(len(original), 1)
            self.assertEqual(original[0]['message_ids'], ['900', '901'])
            self.assertEqual(await service.sync_jobs(db, AT), original)
            await db.execute(text("UPDATE tasks SET status='DONE', updated_at=now() WHERE id=:id"),
                             {'id': uuid.UUID(self.items[self.user_ids[0]][0]['id'])})
            await db.commit()
        async with self.sessions() as db:
            changed = await service.sync_jobs(db, AT)
            self.assertNotEqual(changed[0]['revision'], original[0]['revision'])
            row = await db.get(DiscordReminder, uuid.UUID(first['id']))
            self.assertEqual(row.one_h_report['tasks'][0]['status'], 'TODO')  # Scan has no writes.
            link = await db.get(DiscordLink, self.links[0].id)
            link.enabled = False
            await db.commit()
        async with self.sessions() as db:
            self.assertEqual(await service.sync_jobs(db, AT), [])

    async def test_no_current_tasks_can_select_future_work_and_archive_it_without_task_writes(self):
        future = task('TODO', '14:20')
        self.items[self.user_ids[0]] = [future]
        first = next(j for j in await self.collect() if j['discord_user_id'] == '11')
        opened = (await self.open(first))['one_h']
        self.assertEqual(opened['tasks'], [])
        self.assertEqual(opened['questions'][0]['id'], 'next')
        async def choose(request_id, ids, key):
            async with self.sessions() as db:
                return await api.answer_one_h(uuid.UUID(first['id']), api.OneHAnswer(
                    **self.actors[0].model_dump(), item_id='next', request_id=request_id, selection_mode='TASKS',
                    next_task_ids=ids, next_options_key=key), db)
        saved = await choose('701', [future['id']], opened['next_options_key'])
        self.assertEqual(saved['state'], 'DONE')
        self.assertEqual(future['status'], 'TODO')
        self.assertEqual(future['one_h_report_slot'], '14:20')
        async with self.sessions() as db:
            detail = await host.meeting_detail(db, service.slot_id(AT.date(), '10:00'))
            self.assertEqual(detail['discord_reports'][0]['next']['selected_tasks'][0]['id'], future['id'])
        with self.assertRaises(HTTPException):
            await choose('702', [str(uuid.uuid4())], opened['next_options_key'])
        future['status'] = 'DONE'
        with self.assertRaises(HTTPException):
            await choose('703', [future['id']], opened['next_options_key'])

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
