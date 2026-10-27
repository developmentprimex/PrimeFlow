"""M2 meeting follow-up: status, assignment and fallback routing."""
import asyncio
import os
import unittest
import uuid
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy import select
from fastapi import HTTPException
from app.services import discord_meetings as service
from app.services.primeflow_report import report_timezone
from app.api.routers import discord_assistant as api
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus as Status
from app.models.discord_assistant import DiscordMeetingAlert as Alert
from app.models.user import User
from tests import test_discord_m2_database as fixtures


class MeetingM2RulesTests(unittest.TestCase):
    def test_recipient_fallback_only_when_no_manual_assignees(self):
        self.assertEqual(service.m2_recipients(['a', 'b'], ['a', 'dv'], 'dv'), ['a'])
        self.assertEqual(service.m2_recipients(['unlinked'], ['dv'], 'dv'), [])
        self.assertEqual(service.m2_recipients([], ['dv'], 'dv'), ['dv'])

    def test_m2_only_asks_completed_am_occurrences_in_the_collection_window(self):
        now = datetime(2026, 10, 27, 11, 45, tzinfo=report_timezone())
        meeting = Meeting(meeting_type='external', starts_at=now.replace(hour=8),
            ends_at=now.replace(hour=9), recurrence_type='none')
        self.assertIsNotNone(service.m2_occurrence(meeting, now, report_timezone()))
        self.assertIsNone(service.m2_occurrence(meeting, now.replace(hour=10), report_timezone()))
        meeting.starts_at = now.replace(hour=11, minute=30)
        meeting.ends_at = now.replace(hour=12, minute=30)
        self.assertIsNone(service.m2_occurrence(meeting, now, report_timezone()))
        meeting.starts_at = now.replace(hour=13)
        self.assertIsNone(service.m2_occurrence(meeting, now, report_timezone()))
        meeting.starts_at, meeting.ends_at = now.replace(hour=8, minute=0), now.replace(hour=13, minute=0)
        self.assertIsNone(service.m2_occurrence(meeting, now, report_timezone()))

    def test_m2_question_uses_the_existing_status_buttons(self):
        import discord_ui as ui
        async def check():
            job = {'id': '123', 'kind': 'm2_after', 'discord_user_id': '11',
                'meeting': {'title': 'External follow-up', 'type': 'external', 'starts_at': '2026-10-27T08:00:00+01:00'}}
            content, _, view = ui.meeting_alert(job)
            self.assertIn('M2 · A u mbajt takimi?', content)
            self.assertEqual([item.custom_id for item in view.children], ['pf:mheld:123:held', 'pf:mheld:123:canceled'])
        asyncio.run(check())


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL schema')
class MeetingM2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    extra_tables = {Meeting.__table__, MeetingParticipant.__table__, Status.__table__, Alert.__table__}
    asyncTearDown = fixtures.M2DatabaseTests.asyncTearDown
    fresh_data = fixtures.M2DatabaseTests.fresh_data

    async def asyncSetUp(self):
        await fixtures.M2DatabaseTests.asyncSetUp(self)
        self.now = datetime.combine(self.day, time(11, 45), report_timezone())
        self.internal, self.external = uuid.uuid4(), uuid.uuid4()
        async with self.sessions() as db:
            diellza = await db.get(User, self.uid2)
            diellza.username, diellza.full_name = 'diellza.veliu', 'Diellza Veliu'
            for mid, kind in ((self.internal, 'internal'), (self.external, 'external')):
                db.add(Meeting(id=mid, title='M2 ' + kind, department_id=diellza.department_id,
                    meeting_type=kind, starts_at=self.now.replace(hour=8, minute=0),
                    ends_at=self.now.replace(hour=9, minute=0), reminder_minutes_before=None))
            await db.flush()
            db.add(MeetingParticipant(meeting_id=self.external, user_id=self.uid, assignment_source='manual'))
            await db.commit()

    async def collect(self):
        async with self.sessions() as db:
            return await service.m2_due_alerts(db, self.now, [self.uid, self.uid2])

    async def claim(self):
        clock = Mock(wraps=datetime)
        clock.now.return_value = self.now
        async with self.sessions() as db:
            with patch.object(api, 'datetime', clock), patch.object(service, 'due_alerts', AsyncMock(return_value=[])):
                return (await api.claim_meeting_alerts(db))['jobs']

    async def test_routing_includes_disabled_reminders_and_skips_filled_statuses(self):
        due = await self.collect()
        self.assertEqual({(meeting.id, user) for meeting, user, *_ in due}, {(self.internal, self.uid2), (self.external, self.uid)})
        async with self.sessions() as db:
            db.add(Status(meeting_id=self.internal, occurrence_date=self.day, status='held'))
            db.add(Status(meeting_id=self.external, occurrence_date=self.day, status='canceled'))
            await db.commit()
        self.assertEqual(await self.collect(), [])

    async def test_claim_is_durable_and_first_answer_updates_common_view_without_overwrite(self):
        jobs = await self.claim()
        self.assertEqual(len(jobs), 2)
        self.assertEqual(await self.claim(), [])
        job = next(item for item in jobs if item['meeting']['id'] == str(self.external))
        async with self.sessions() as db:
            result = await api.mark_meeting_held(uuid.UUID(job['id']), api.MeetingHeld(**self.actor.model_dump(), status='held'), db)
            self.assertEqual(result['status'], 'held')
        async with self.sessions() as db:
            result = await api.mark_meeting_held(uuid.UUID(job['id']), api.MeetingHeld(**self.actor.model_dump(), status='canceled'), db)
            self.assertEqual(result['status'], 'held')
            stored = (await db.execute(select(Status).where(Status.meeting_id == self.external))).scalar_one()
            self.assertEqual(stored.checked_by_user_id, self.uid)

    async def test_fallback_response_is_refused_after_someone_is_assigned(self):
        jobs = await self.claim()
        job = next(item for item in jobs if item['meeting']['id'] == str(self.internal))
        async with self.sessions() as db:
            db.add(MeetingParticipant(meeting_id=self.internal, user_id=self.uid, assignment_source='manual'))
            await db.commit()
            with self.assertRaises(HTTPException) as caught:
                await api.mark_meeting_held(uuid.UUID(job['id']), api.MeetingHeld(discord_user_id='44', guild_id='22', channel_id='55', status='held'), db)
            self.assertEqual(caught.exception.status_code, 403)
