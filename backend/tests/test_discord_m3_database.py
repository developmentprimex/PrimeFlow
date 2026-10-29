"""Transactional checks in a disposable PostgreSQL schema; never contacts Discord."""
import os
import unittest
import uuid
from datetime import datetime, time, timedelta, timezone
from unittest.mock import patch, AsyncMock
from sqlalchemy import select, func
from fastapi import HTTPException
from tests import test_discord_m2_database as fixtures
from app.api.routers import discord_m3 as api
from app.models.discord_m3_question import DiscordM3Question as Question
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_user_comment import TaskUserComment
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.user import User
from app.services.primeflow_report import report_timezone


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Set M2_TEST_DATABASE_URL for isolated PostgreSQL checks')
class M3DatabaseTests(unittest.IsolatedAsyncioTestCase):
    full_schema = True
    fresh_data = fixtures.M2DatabaseTests.fresh_data
    asyncTearDown = fixtures.M2DatabaseTests.asyncTearDown

    async def asyncSetUp(self):
        await fixtures.M2DatabaseTests.asyncSetUp(self)
        notify = patch('app.api.routers.tasks.publish_notification', new=AsyncMock())
        notify.start()
        self.patchers.append(notify)
        original_lock = api.reports.locked_report

        async def isolated_lock(db, day, *, wait=True):
            # Advisory locks are global across disposable schemas. A concurrent
            # test must wait instead of mistaking contention for an empty plan.
            return await original_lock(db, day, wait=True)

        report_lock = patch.object(api.reports, 'locked_report', new=isolated_lock)
        report_lock.start()
        self.patchers.append(report_lock)
        async with self.sessions() as db:
            for uid, email in ((self.uid, 'm3one@example.com'), (self.uid2, 'm3two@example.com')):
                user = await db.get(User, uid)
                user.email = email
            task = await db.get(Task, self.task_id)
            task.one_h_marker = 'M3'
            await db.commit()

    async def claim(self, phase='m3'):
        now = datetime.combine(self.day, time(15, 50) if phase == 'm3' else time(16, 10), report_timezone())
        async with self.sessions() as db:
            jobs = (await api.collect_questions(db, now=now, phase=phase))['jobs']
            if phase == 'tomorrow':
                self.assertFalse(any(job['kind'] == 'tomorrow' and job['snapshot']['tasks'] for job in jobs))
                for job in jobs:
                    question = await db.get(Question, uuid.UUID(job['id']))
                    question.sent_at = now
                    question.message_id = str(1000 + len(job['id']))
                await db.commit()
                jobs += (await api.collect_questions(db, now=now, phase=phase))['jobs']
            return jobs

    async def test_all_tasks_get_cards_and_bulk_preserves_individual_no_and_comment(self):
        target = await self.setup_tomorrow()
        extra_id = uuid.uuid4()
        async with self.sessions() as db:
            db.add(Task(id=extra_id, title='Continues beyond tomorrow', assigned_to=self.uid,
                status='TODO', start_date=datetime.combine(target, time(8), report_timezone()),
                due_date=datetime.combine(target + timedelta(days=3), time(16), report_timezone())))
            await db.commit()
        jobs = [job for job in await self.claim('tomorrow') if job['discord_user_id'] == '11']
        cards = [job for job in jobs if job['kind'] == 'tomorrow_task']
        self.assertEqual(len(cards), 2)
        self.assertEqual(jobs[-1]['kind'], 'tomorrow')
        first = next(job for job in cards if job['task_id'] == str(self.task_id))
        second = next(job for job in cards if job['task_id'] == str(extra_id))
        await self.reply(first, 'JO', comment='Not ready')
        await self.reply(second, 'comment', comment='Will work in the afternoon')
        self.assertFalse((await self.opened(second))['answered'])
        footer = jobs[-1]
        live = await self.opened(footer)
        await self.reply(footer, 'PO', plan_key=live['plan_key'])
        one, two = await self.opened(first), await self.opened(second)
        self.assertEqual((one['answer']['action'], one['comment']), ('JO', 'Not ready'))
        self.assertEqual((two['answer']['action'], two['comment']), ('PO', 'Will work in the afternoon'))

    async def opened(self, job, actor=None):
        async with self.sessions() as db:
            return await api.open_question(uuid.UUID(job['id']), actor or self.actor, db)

    async def reply(self, job, action, actor=None, **fields):
        async with self.sessions() as db:
            return await api.answer(uuid.UUID(job['id']), api.Answer(**(actor or self.actor).model_dump(),
                action=action, **fields), db)

    async def setup_tomorrow(self, shared=False):
        target = api.rules.target_day(self.day)
        group = uuid.uuid4()
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.due_date = datetime.combine(target, time(16), report_timezone())
            task.is_1h_report = True
            task.fast_task_group_id = group
            task.one_h_report_slot = '11:00'
            if shared:
                self.peer_id = uuid.uuid4()
                db.add(Task(id=self.peer_id, title=task.title, assigned_to=self.uid2, fast_task_group_id=group,
                    status='TODO', is_1h_report=True, one_h_report_slot='10:00', start_date=task.start_date,
                    due_date=task.due_date, department_id=task.department_id))
            await db.commit()
        return target

    async def test_collection_deduplicates_and_includes_system_tasks(self):
        # A system slot origin is enough to exercise the report's SYS selector.
        from app.models.system_task_template import SystemTaskTemplate
        async with self.sessions() as db:
            template = SystemTaskTemplate(title='SYS test', frequency='DAILY', created_by_user_id=self.uid)
            db.add(template)
            await db.flush()
            task = await db.get(Task, self.task_id)
            task.system_template_origin_id = template.id
            await db.commit()
        jobs = await self.claim()
        self.assertEqual({job['kind'] for job in jobs}, {'untouched', 'delivery'})
        self.assertTrue(all(job['snapshot']['is_system_task'] for job in jobs))
        self.assertEqual(await self.claim(), [])
        with patch.object(api.rules, 'collection_phase', return_value=None):
            async with self.sessions() as db:
                self.assertEqual(await api.claim(db), {'jobs': []})

    async def test_early_trials_are_reissued_once_for_the_regular_window(self):
        jobs = await self.claim()
        early = datetime.combine(self.day, time(11, 25), report_timezone())
        async with self.sessions() as db:
            for job in jobs:
                q = await db.get(Question, uuid.UUID(job['id']))
                q.sent_at, q.message_id = early, '555'
            await db.commit()
        real = await self.claim()
        self.assertEqual(len(real), len(jobs))
        self.assertTrue(all(job['previous_test_message_id'] == '555' for job in real))
        self.assertEqual(await self.claim(), [])
        regular = datetime.combine(self.day, time(15, 51), report_timezone())
        async with self.sessions() as db:
            for job in real:
                q = await db.get(Question, uuid.UUID(job['id']))
                q.sent_at, q.message_id = regular, '666'
            await db.commit()
        self.assertEqual(await self.claim(), [])

    async def test_shared_delivery_waits_for_every_person_and_keeps_comments(self):
        async with self.sessions() as db:
            db.add(TaskAssignee(task_id=self.task_id, user_id=self.uid2))
            await db.commit()
        jobs = [job for job in await self.claim() if job['kind'] == 'delivery']
        one = next(job for job in jobs if job['discord_user_id'] == '11')
        two = next(job for job in jobs if job['discord_user_id'] == '44')
        await self.reply(one, 'PO', comment='Done')
        async with self.sessions() as db:
            report = (await db.execute(select(M3ReportingPointsReport))).scalar_one()
            self.assertEqual(report.manual_answers[f'delivery_choice:{self.task_id}'], '')
        other = api.Actor(discord_user_id='44', guild_id='22', channel_id='55')
        await self.reply(two, 'JO', actor=other, comment='Waiting review')
        async with self.sessions() as db:
            report = (await db.execute(select(M3ReportingPointsReport))).scalar_one()
            self.assertEqual(report.manual_answers[f'delivery_choice:{self.task_id}'], 'JO')
            self.assertIn('Second Person: Waiting review', report.manual_answers[f'delivery:{self.task_id}'])
            self.assertIn('First Person: Done', report.manual_answers[f'delivery:{self.task_id}'])
        await self.reply(one, 'PO', comment='Done')
        async with self.sessions() as db:
            comment = (await db.execute(select(TaskUserComment.comment).where(TaskUserComment.user_id == self.uid))).scalar_one()
            self.assertEqual(comment.count('Done'), 1)

    async def test_comment_updates_daily_evidence_and_reassignment_rejects(self):
        job = next(job for job in await self.claim() if job['kind'] == 'untouched')
        await self.reply(job, 'comment', comment='Pres klientin')
        async with self.sessions() as db:
            state = (await db.execute(select(TaskDailyRlzState))).scalar_one()
            self.assertEqual(state.comment, 'Pres klientin')
            task = await db.get(Task, self.task_id)
            task.assigned_to = self.uid2
            await db.commit()
        with self.assertRaises(HTTPException) as raised:
            await self.reply(job, 'comment', comment='Not mine now')
        self.assertEqual(raised.exception.status_code, 403)

    async def test_tomorrow_summary_due_question_and_missing_slot(self):
        target = await self.setup_tomorrow()
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.one_h_report_slot = None
            await db.commit()
        jobs = await self.claim('tomorrow')
        own = [job for job in jobs if job['discord_user_id'] == '11']
        self.assertEqual({job['kind'] for job in own}, {'tomorrow', 'tomorrow_task', 'slot'})
        summary = next(job for job in own if job['kind'] == 'tomorrow')
        live = await self.opened(summary)
        self.assertEqual(live['target_date'], target.isoformat())
        self.assertEqual(len(live['snapshot']['tasks']), 1)
        due = next(job for job in own if job['kind'] == 'tomorrow_task')
        async with self.sessions() as db:
            await api.acknowledge(uuid.UUID(due['id']), api.Receipt(**self.actor.model_dump(), message_id='12345'), db)
        result = await self.reply(summary, 'PO', plan_key=live['plan_key'])
        self.assertEqual([update['message_id'] for update in result['updates']], ['12345'])
        self.assertEqual((await self.opened(due))['answer']['action'], 'PO')
        slot = next(job for job in own if job['kind'] == 'slot')
        live = await self.opened(slot)
        await self.reply(slot, 'slot', slot='14:20', expected_slot_key=api.rules.context_key('slot', live['snapshot']))
        async with self.sessions() as db:
            saved = (await db.execute(select(TaskOneHReportSlot))).scalar_one()
            self.assertEqual((saved.report_date, saved.one_h_report_slot), (target, '14:20'))
            q = await db.get(Question, uuid.UUID(slot['id']))
            self.assertTrue(q.answered_at)
        self.assertFalse((await self.opened(summary))['plan_changed'])

    async def test_slot_conflict_keeps_own_then_can_align_with_peer(self):
        await self.setup_tomorrow(shared=True)
        jobs = await self.claim('tomorrow')
        slot = next(job for job in jobs if job['kind'] == 'slot' and job['discord_user_id'] == '11')
        live = await self.opened(slot)
        self.assertEqual(live['snapshot']['peers'][0]['slot'], '10:00')
        await self.reply(slot, 'slot', slot='11:00', expected_slot_key=api.rules.context_key('slot', live['snapshot']))
        live = await self.opened(slot)
        await self.reply(slot, 'slot', slot='10:00', expected_slot_key=api.rules.context_key('slot', live['snapshot']), expected_answered_at=live['answered_at'])
        self.assertTrue((await self.opened(slot)).get('resolved'))

    async def test_stale_plan_and_dates_cannot_overwrite_platform_changes(self):
        await self.setup_tomorrow()
        jobs = await self.claim('tomorrow')
        summary = next(job for job in jobs if job['kind'] == 'tomorrow' and job['discord_user_id'] == '11')
        due = next(job for job in jobs if job['kind'] == 'tomorrow_task' and job['discord_user_id'] == '11')
        old_plan, old_task = await self.opened(summary), await self.opened(due)
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            task.due_date += timedelta(days=1)
            changed_due = task.due_date
            await db.commit()
        with self.assertRaises(HTTPException) as raised:
            await self.reply(summary, 'PO', plan_key=old_plan['plan_key'])
        self.assertEqual(raised.exception.status_code, 409)
        with self.assertRaises(HTTPException) as raised:
            await self.reply(due, 'postpone', comment='Move', start_date=datetime.fromisoformat(old_task['live_dates']['start_date']),
                due_date=changed_due + timedelta(days=1), expected_dates=old_task['live_dates'])
        self.assertEqual(raised.exception.status_code, 409)

    async def test_progress_and_done_use_normal_updates_and_preserve_report_comment(self):
        jobs = await self.claim()
        job = next(job for job in jobs if job['kind'] == 'untouched')
        await self.reply(job, 'progress', progress=35, comment='Po punoj')
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            self.assertEqual((task.status, task.progress_percentage), ('IN_PROGRESS', 35))
            report = (await db.execute(select(M3ReportingPointsReport))).scalar_one()
            self.assertIn('Po punoj', report.manual_answers[f'untouched_comment:{self.task_id}'])
            self.assertEqual(report.data['untouched'], [])
            task.status, task.progress_percentage = 'TODO', 0
            await db.commit()
        live = await self.opened(job)
        await self.reply(job, 'done', comment='E përfundova', expected_answered_at=live['answered_at'])
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            self.assertEqual((task.status, task.progress_percentage), ('DONE', 100))

    async def test_postpone_only_due_commits_dates_comment_and_question_together(self):
        await self.setup_tomorrow()
        job = next(job for job in await self.claim('tomorrow') if job['kind'] == 'tomorrow_task' and job['discord_user_id'] == '11')
        live = await self.opened(job)
        start, due = (datetime.fromisoformat(live['live_dates'][field]) for field in ('start_date', 'due_date'))
        await self.reply(job, 'postpone', comment='Pres të dhëna', start_date=start,
            due_date=due + timedelta(days=1), expected_dates=live['live_dates'])
        async with self.sessions() as db:
            task = await db.get(Task, self.task_id)
            self.assertEqual(task.start_date, start)
            self.assertEqual(task.due_date, due + timedelta(days=1))
            question = await db.get(Question, uuid.UUID(job['id']))
            self.assertEqual(question.answer['action'], 'postpone')
            self.assertEqual(question.comment, 'Pres të dhëna')
            comment = (await db.execute(select(TaskUserComment.comment).where(TaskUserComment.user_id == self.uid))).scalar_one()
            self.assertIn('Existing task comment', comment)
            self.assertIn('Pres të dhëna', comment)

    async def test_meetings_route_to_assignees_or_diellza_and_store_status(self):
        async with self.sessions() as db:
            user = await db.get(User, self.uid2)
            user.username = 'diellza.veliu'
            owner = await db.get(User, self.uid)
            starts = datetime.combine(self.day, time(14), report_timezone())
            assigned = Meeting(title='Assigned', department_id=owner.department_id, starts_at=starts, meeting_type='internal')
            fallback = Meeting(title='Unassigned', department_id=owner.department_id, starts_at=starts, meeting_type='external')
            future = Meeting(title='Not finished', department_id=owner.department_id,
                starts_at=starts.replace(hour=15, minute=45), ends_at=starts.replace(hour=16), meeting_type='external')
            db.add_all([assigned, fallback, future])
            await db.flush()
            db.add(MeetingParticipant(meeting_id=assigned.id, user_id=self.uid))
            await db.commit()
        jobs = [job for job in await self.claim() if job['kind'] == 'meeting']
        self.assertEqual({(job['snapshot']['title'], job['discord_user_id']) for job in jobs}, {('Assigned', '11'), ('Unassigned', '44')})
        job = next(job for job in jobs if job['discord_user_id'] == '11')
        await self.reply(job, 'held', comment='U mbajt')
        async with self.sessions() as db:
            status = (await db.execute(select(MeetingOccurrenceStatus))).scalar_one()
            self.assertEqual((status.status, status.checked_by_user_id), ('held', self.uid))
