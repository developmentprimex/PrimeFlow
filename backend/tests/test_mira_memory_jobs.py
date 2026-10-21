import uuid
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import select, func
from tests.test_mira_memory_model import MemoryTests
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event
from app.services import discord_voice_meetings as voice
from app.jobs import discord_voice_meetings as finalization
from app.jobs import mira_memory as jobs


def add(title):
    return [{'action': 'add', 'item_id': None, 'title': title, 'description': 'Gjendja.', 'kind': 'TASK',
        'people': [], 'said': 'U tha.', 'segments': [0]}]


class MemoryJobTests(MemoryTests):
    def enabled(self, on=True):
        stack = ExitStack()
        stack.enter_context(patch.object(settings, 'MIRA_MEMORY_ENABLED', on))
        stack.enter_context(patch.object(jobs, 'SessionLocal', self.sessions))
        stack.enter_context(patch.object(finalization, 'SessionLocal', self.sessions))
        return stack

    async def meeting(self, title='1H', *, started_minutes_ago=10, status='READY', memory_status='PENDING',
            transcript='Ana dërgon raportin.', **values):
        sid = uuid.uuid4()
        async with self.sessions() as db:
            db.add(Meeting(id=sid, user_id=self.uid, link_id=self.lid, department_id=self.did, guild_id='123',
                voice_channel_id='55', private_channel_id='44', request_id=uuid.uuid4().hex[:20], instance_id=uuid.uuid4(),
                capture_token_hash='h', title=title, status=status, partial=False, stop_authorized=True,
                started_at=voice.now()-timedelta(minutes=started_minutes_ago), memory_status=memory_status,
                draft_text='Shënimet.' if status == 'READY' else None, **values))
            await db.flush()
            if transcript:
                db.add(Segment(id=uuid.uuid4(), session_id=sid, sequence=0, speaker_id='12', speaker_name='Ana',
                    start_ms=0, end_ms=1000, content_hash='h', status='DONE', transcript=transcript))
            await db.commit()
        return sid

    async def finalizing(self, transcript='Ana dërgon raportin.'):
        return await self.meeting(status='FINALIZING', memory_status=None, transcript=transcript,
            expected_segments=1 if transcript else 0, stopped_at=voice.now()-timedelta(seconds=120))

    async def get(self, sid):
        async with self.sessions() as db:
            return await db.get(Meeting, sid)

    async def titles(self):
        async with self.sessions() as db:
            return set((await db.execute(select(Item.title))).scalars())

    async def test_flag_off_finalization_marks_skipped_and_job_does_nothing(self):
        sid = await self.finalizing()
        extract = AsyncMock(return_value=[])
        with self.enabled(False), patch('app.services.discord_voice_openai.summarize_meeting', AsyncMock(return_value='Shënimet.')), \
                patch('app.services.discord_voice_openai.extract_memory_operations', extract):
            await finalization.process_voice_meetings()
            await jobs.process_mira_memory()
        self.assertEqual(((await self.get(sid)).status, (await self.get(sid)).memory_status), ('READY', 'SKIPPED'))
        extract.assert_not_awaited()

    async def test_flag_on_notes_get_snapshot_and_meeting_becomes_pending(self):
        async with self.sessions() as db:
            db.add(Item(id=uuid.uuid4(), title='Oferta', description='Arta.', kind='TASK', status='OPEN', people=[],
                version=1, mention_count=1, human_edited=False, last_mentioned_at=voice.now()))
            await db.commit()
        sid = await self.finalizing()
        summary = AsyncMock(return_value='Shënimet.')
        with self.enabled(), patch('app.services.discord_voice_openai.summarize_meeting', summary):
            await finalization.process_voice_meetings()
        self.assertEqual([i['title'] for i in summary.call_args.kwargs['memory']['items']], ['Oferta'])
        row = await self.get(sid)
        self.assertEqual((row.status, row.memory_status), ('READY', 'PENDING'))

    async def test_failed_summary_with_transcript_is_pending_no_speech_is_skipped(self):
        spoken, silent = await self.finalizing(), await self.finalizing(transcript=None)
        with self.enabled(), patch('app.services.discord_voice_openai.summarize_meeting', AsyncMock(side_effect=ValueError('x'))):
            await finalization.process_voice_meetings()
        self.assertEqual(((await self.get(spoken)).status, (await self.get(spoken)).memory_status), ('FAILED', 'PENDING'))
        self.assertEqual(((await self.get(silent)).status, (await self.get(silent)).memory_status), ('FAILED', 'SKIPPED'))

    async def test_pending_meeting_is_applied_in_start_order(self):
        later = await self.meeting('Më vonë', started_minutes_ago=5)
        earlier = await self.meeting('Më herët', started_minutes_ago=50)
        async def extract(title, segments, **kwargs):
            return add(title)
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations', extract):
            await jobs.process_mira_memory()
            self.assertEqual(await self.titles(), {'Më herët'})
            self.assertEqual(((await self.get(earlier)).memory_status, (await self.get(later)).memory_status), ('APPLIED', 'PENDING'))
            await jobs.process_mira_memory()
        self.assertEqual(await self.titles(), {'Më herët', 'Më vonë'})

    async def test_later_meeting_waits_for_earlier_at_most_15_minutes(self):
        earlier = await self.meeting('Ende', started_minutes_ago=60, status='FINALIZING', memory_status=None,
            stopped_at=voice.now()-timedelta(minutes=5))
        later = await self.meeting('Gati', started_minutes_ago=30)
        extract = AsyncMock(return_value=add('Gati'))
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations', extract):
            self.assertTrue((await jobs.process_mira_memory())['waiting'])
            extract.assert_not_awaited()
            async with self.sessions() as db:
                (await db.get(Meeting, earlier)).stopped_at = voice.now()-timedelta(minutes=16)
                await db.commit()
            await jobs.process_mira_memory()
        self.assertEqual((await self.get(later)).memory_status, 'APPLIED')

    async def test_failure_retries_then_fails_after_5_attempts_and_notes_untouched(self):
        first = await self.meeting('Dështon', started_minutes_ago=50)
        before = await self.get(first)
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations',
                AsyncMock(side_effect=ValueError('invalid_memory_response'))):
            for attempt in range(1, 6):
                await jobs.process_mira_memory()
                row = await self.get(first)
                self.assertEqual((row.memory_attempts, row.memory_status), (attempt, 'FAILED' if attempt == 5 else 'PENDING'))
        self.assertEqual(row.memory_error, 'invalid_memory_response')
        self.assertEqual((row.status, row.draft_text, row.delivered_at, row.error), (before.status, before.draft_text, before.delivered_at, before.error))
        second = await self.meeting('Tjetri', started_minutes_ago=5)
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations', AsyncMock(return_value=add('Tjetri'))):
            await jobs.process_mira_memory()
        self.assertEqual((await self.get(second)).memory_status, 'APPLIED')

    async def test_applying_twice_does_not_duplicate_events(self):
        sid = await self.meeting()
        extract = AsyncMock(return_value=add('Një herë'))
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations', extract):
            await jobs.process_mira_memory()
            await jobs.process_mira_memory()
        self.assertEqual(extract.await_count, 1)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(Event))).scalar_one(), 1)
        # A run whose claim was taken over while it waited on OpenAI discards its result.
        stale = await self.meeting('E vjetruar', started_minutes_ago=1)
        async def taken_over(title, segments, **kwargs):
            async with self.sessions() as db:
                (await db.get(Meeting, stale)).memory_attempts += 1
                await db.commit()
            return add('E vjetruar')
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations', taken_over):
            await jobs.process_mira_memory()
        self.assertNotIn('E vjetruar', await self.titles())

    async def test_unsaved_takimi_fillo_meeting_is_included(self):
        sid = await self.meeting('Takim pa ruajtur')
        self.assertIsNone((await self.get(sid)).saved_note_id)
        with self.enabled(), patch('app.services.discord_voice_openai.extract_memory_operations', AsyncMock(return_value=add('Pa ruajtur'))):
            await jobs.process_mira_memory()
        self.assertEqual((await self.get(sid)).memory_status, 'APPLIED')
        self.assertIn('Pa ruajtur', await self.titles())

    async def test_snapshot_database_error_does_not_block_notes(self):
        from sqlalchemy import text
        sid = await self.finalizing()
        async def broken(db):
            await db.execute(text('SELECT * FROM missing_memory_table'))
        summary = AsyncMock(return_value='Shënimet.')
        with self.enabled(), patch('app.services.mira_memory.snapshot', broken), \
                patch('app.services.discord_voice_openai.summarize_meeting', summary):
            await finalization.process_voice_meetings()
        self.assertIsNone(summary.call_args.kwargs['memory'])
        self.assertEqual((await self.get(sid)).status, 'READY')
