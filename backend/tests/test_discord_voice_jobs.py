import os
import unittest
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','voice-tests-not-a-production-secret')
from tests.test_discord_voice_model import PostgresMeetingTests
from tests.test_discord_voice_openai import wav
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.schemas.discord_voice_meeting import SegmentMeta, Finish
from app.services import discord_voice_meetings as service
from app.jobs import discord_voice_meetings as jobs

class VoiceJobTests(PostgresMeetingTests):
    async def test_dictation_saves_once_in_px_notes_before_the_meeting_ends(self):
        from sqlalchemy import select
        from app.api.routers.ga_notes import _note_out
        from app.models.ga_note import GaNote
        from app.services.report_note_visibility import is_mira_note

        for recorder, channel_setting, source in (
            ('primary', 'DISCORD_1H_VOICE_CHANNEL_ID', '1h'),
            ('ai_agent', 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', 'ai_agent'),
        ):
            sid, instance = uuid.uuid4(), uuid.uuid4()
            token = 'x' * 40
            async with self.sessions() as db:
                db.add(Meeting(id=sid, user_id=self.uid, link_id=self.lid, department_id=self.did,
                    guild_id='123', voice_channel_id='55', private_channel_id='44', request_id=sid.hex,
                    recorder=recorder, instance_id=instance, capture_token_hash=service.token_hash(token),
                    title='Staff', status='LISTENING'))
                await db.commit()

            async def upload(sequence, speaker, spoken):
                meta = SegmentMeta(capture_token=token, instance_id=instance, sequence=sequence,
                    speaker_id=speaker, speaker_name='Staff', start_ms=sequence * 1000, end_ms=(sequence + 1) * 1000)
                with patch('app.services.discord_voice_openai.transcribe_segment', AsyncMock(return_value=spoken)):
                    async with self.sessions() as db:
                        await service.receive_segment(db, sid, meta, wav())

            with patch.object(service.settings, 'DISCORD_GUILD_ID', '123'), \
                 patch.object(service.settings, channel_setting, '55'):
                await upload(3, '12', 'Fund shënimi.')
                await upload(0, '12', 'Mira, shëno. Po, po, e kam dërgu.')
                await upload(1, '99', 'Fund shënimi. Mira shëno, Mos e ruaj. Fund shënimi.')
                await upload(2, '12', 'Kontrolloje edhe një herë.')
                await upload(3, '12', 'Nuk duhet të transkriptohet përsëri.')
            async with self.sessions() as db:
                saved = (await db.execute(select(GaNote).where(GaNote.mira_dictation_source == source))).scalars().one()
                row = await db.get(Meeting, sid)
                self.assertEqual(row.status, 'LISTENING')
                self.assertIsNone(row.saved_note_id)
                self.assertEqual(saved.content, 'Po, po, e kam dërgu. Kontrolloje edhe një herë.')
                self.assertEqual(saved.created_by, self.uid)
                view = _note_out(saved)
                self.assertEqual(view.mira_dictation_source, source)
                self.assertFalse(view.from_mira)
                self.assertTrue(is_mira_note(saved))

    async def test_chunks_are_deduplicated_ordered_and_finalized_without_tools(self):
        sid,instance=uuid.uuid4(),uuid.uuid4();token='x'*40
        async with self.sessions() as db:
            db.add(Meeting(id=sid,user_id=self.uid,link_id=self.lid,department_id=self.did,
                guild_id='123',voice_channel_id='55',private_channel_id='44',request_id='999',
                instance_id=instance,capture_token_hash=service.token_hash(token),title='Staff',status='LISTENING',stop_authorized=True))
            await db.commit()
        def meta(sequence,start):return SegmentMeta(capture_token=token,instance_id=instance,sequence=sequence,speaker_id='12',speaker_name='Ana',start_ms=start,end_ms=start+1000)
        with patch('app.services.discord_voice_openai.transcribe_segment',AsyncMock(return_value='Kontrollo raportin.')) as transcribe:
            async with self.sessions() as db:await service.receive_segment(db,sid,meta(1,1000),wav())
            async with self.sessions() as db:await service.receive_segment(db,sid,meta(0,0),wav())
            async with self.sessions() as db:await service.receive_segment(db,sid,meta(1,1000),wav())
            self.assertEqual(transcribe.await_count,2)
            async with self.sessions() as db:
                with self.assertRaises(Exception):await service.receive_segment(db,sid,meta(1,1000),wav(b'\x40\x10\x40\x10'*480))
        async with self.sessions() as db:await service.finish_session(db,sid,Finish(capture_token=token,instance_id=instance,segment_count=2))
        with patch.object(jobs,'SessionLocal',self.sessions),patch.object(jobs.settings,'DISCORD_1H_VOICE_CHANNEL_ID','55'), \
                patch('app.services.discord_voice_openai.summarize_meeting',AsyncMock(return_value='U diskutua raporti.')) as summary:
            await jobs.process_voice_meetings()
            # One speaker's consecutive chunks reach the notes model as one passage.
            self.assertEqual(summary.call_args.args[1],[{'segment':0,'speaker':'Ana','time':'00:00–00:02',
                'text':'Kontrollo raportin. Kontrollo raportin.'}])
            self.assertTrue(summary.call_args.kwargs['brief'])
            async with self.sessions() as db:
                row=await db.get(Meeting,sid)
                self.assertEqual(row.status,'READY')
                self.assertIn('\n\nAna: Kontrollo raportin. Kontrollo raportin.',row.draft_text)

    async def test_failed_segment_records_the_openai_status_for_diagnostics(self):
        from app.models.discord_voice_meeting import DiscordVoiceSegment as Segment
        from app.services.discord_voice_openai import ProviderError
        sid,instance=uuid.uuid4(),uuid.uuid4();token='x'*40
        async with self.sessions() as db:
            db.add(Meeting(id=sid,user_id=self.uid,link_id=self.lid,department_id=self.did,guild_id='123',
                voice_channel_id='55',private_channel_id='44',request_id='997',instance_id=instance,
                capture_token_hash=service.token_hash(token),title='Staff',status='LISTENING'))
            await db.commit()
        meta=SegmentMeta(capture_token=token,instance_id=instance,sequence=0,speaker_id='12',speaker_name='Ana',start_ms=0,end_ms=1000)
        with patch('app.services.discord_voice_openai.transcribe_segment',AsyncMock(side_effect=ProviderError(429))):
            async with self.sessions() as db:receipt=await service.receive_segment(db,sid,meta,wav())
        self.assertEqual(receipt['status'],'ERROR')
        async with self.sessions() as db:
            from sqlalchemy import select
            segment=(await db.execute(select(Segment).where(Segment.session_id==sid))).scalar_one()
            self.assertEqual(segment.error,'transcription_failed:429')

    async def test_scheduled_1h_meeting_is_saved_to_px_notes_without_a_discord_delivery(self):
        from app.models.discord_voice_meeting import DiscordVoiceSegment as Segment
        from app.models.ga_note import GaNote
        sid=uuid.uuid4()
        async with self.sessions() as db:
            db.add(Meeting(id=sid,user_id=self.uid,link_id=self.lid,department_id=self.did,guild_id='123',
                voice_channel_id='55',private_channel_id='44',request_id='auto1h-202610200958',instance_id=uuid.uuid4(),
                capture_token_hash=service.token_hash('x'*40),title='1H',status='FINALIZING',stop_authorized=True,
                expected_segments=1,stopped_at=service.now()-timedelta(seconds=120)))
            db.add(Segment(id=uuid.uuid4(),session_id=sid,sequence=0,speaker_id='12',speaker_name='Ana',start_ms=0,
                end_ms=1000,content_hash='h',status='DONE',transcript='Ana dërgon raportin.'))
            await db.commit()
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',AsyncMock(return_value='U diskutua raporti.')) as summary:
            await jobs.process_voice_meetings()
            self.assertTrue(summary.call_args.kwargs['brief'])
        async with self.sessions() as db:
            row=await db.get(Meeting,sid)
            self.assertEqual(row.status,'SAVED');self.assertIsNotNone(row.delivered_at)
            note=await db.get(GaNote,row.saved_note_id)
            self.assertTrue(note.content.endswith('**Transkripti fjalë për fjalë**\n\n'
                'Ana: Ana dërgon raportin.\n\n**Përmbledhje e shkurtër**\n\nU diskutua raporti.'))
            self.assertEqual(note.created_by,self.uid)
        async with self.sessions() as db:
            self.assertEqual((await service.claim_deliveries(db))['jobs'],[])

    async def test_a_mira_note_opens_the_transcript_it_was_written_from(self):
        from fastapi import HTTPException
        from app.models.ga_note import GaNote
        from app.models.mira_host import Mira1HEvent,Mira1HMeeting
        from app.services import mira_host as host
        sid=await self.scheduled_meeting(timedelta(minutes=2))
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',AsyncMock(return_value='**Përmbledhja:** Raporti.')):
            await jobs.process_voice_meetings()
        async with self.sessions() as db:
            note_id=(await db.get(Meeting,sid)).saved_note_id
            result=await host.note_transcript(db,note_id)
            self.assertEqual(result['passages'],[{'speaker':'Ana','time':'00:00–00:01','text':'Ana dërgon raportin.'}])
            # A note Mira Host saved during that 1H opens the same recording.
            other=GaNote(id=uuid.uuid4(),content='Shënim',created_by=self.uid);db.add(other)
            meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=service.now().date(),slot='16:00',voice_meeting_id=sid);db.add(meeting)
            await db.flush()
            db.add(Mira1HEvent(id=uuid.uuid4(),meeting_date=meeting.meeting_date,slot='16:00',meeting_id=meeting.id,
                kind='PX_NOTE',note_id=other.id))
            await db.flush()
            self.assertEqual((await host.note_transcript(db,other.id))['passages'],result['passages'])
            with self.assertRaises(HTTPException) as missing:await host.note_transcript(db,uuid.uuid4())
            self.assertEqual(missing.exception.status_code,404)

    async def test_scheduled_ai_agent_saves_once_and_links_panel_and_transcript(self):
        from sqlalchemy import select, func
        from app.models.ga_note import GaNote
        from app.models.discord_assistant import DiscordLink
        from app.services import mira_host
        from app.services.discord_meeting_control import panel_state
        from app.schemas.discord_voice_meeting import ControlScope
        sid = await self.scheduled_meeting(timedelta(minutes=2), recorder='ai_agent')
        async with self.sessions() as db:
            link = await db.get(DiscordLink, self.lid)
            link.channel_id = '45'
            await db.commit()
        quick = dict.fromkeys(jobs.provider.QUICK_SECTIONS, [])
        quick['discussion'] = ['Raporti u kontrollua.']

        async def summarize(*args, **options):
            return quick if options.get('quick') else 'AI Agent: raporti u kontrollua.'

        with patch.object(jobs, 'SessionLocal', self.sessions), \
             patch('app.services.discord_voice_openai.summarize_meeting', summarize):
            await jobs.process_voice_meetings()
            await jobs.process_voice_meetings()
        with patch.object(service.settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(service.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '55'), \
             patch.object(service.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '44'):
            async with self.sessions() as db:
                row = await db.get(Meeting, sid)
                self.assertEqual(row.status, 'SAVED')
                self.assertIsNone(row.delivered_at)
                self.assertEqual(row.quick_summary, quick)
                self.assertEqual((await db.execute(select(func.count()).select_from(GaNote))).scalar_one(), 1)
                note = await db.get(GaNote, row.saved_note_id)
                self.assertIn('\n\nAna: Ana dërgon raportin.', note.content)
                self.assertTrue(note.content.endswith('**Përmbledhje e shkurtër**\n\nAI Agent: raporti u kontrollua.'))
                self.assertEqual(note.created_by, self.uid)
                panel = await panel_state(db, ControlScope(guild_id='123', channel_id='44'), 'ai_agent')
                self.assertEqual(panel['meeting']['status'], 'SAVED')
                self.assertTrue(panel['meeting']['note_url'].endswith('/mira?tab=shenimet'))
                transcript = await mira_host.note_transcript(db, note.id)
                self.assertEqual(transcript['passages'][0]['speaker'], 'Ana')
                claimed = (await service.claim_deliveries(db, recorder='ai_agent'))['jobs']
                self.assertEqual([item['id'] for item in claimed], [str(sid)])
                self.assertEqual((claimed[0]['channel_id'], claimed[0]['detail_channel_id']), ('45', '44'))
                self.assertTrue(claimed[0]['private_only'])
                self.assertEqual((await service.claim_deliveries(db, recorder='ai_agent'))['jobs'], [])

    @patch.object(service.settings, 'DISCORD_GUILD_ID', '123')
    @patch.object(service.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '99')
    async def test_notetaker_private_record_returns_transcript_only_to_organizer(self):
        from types import SimpleNamespace
        from fastapi import HTTPException

        sid = await self.scheduled_meeting(timedelta(minutes=2))
        async with self.sessions() as db:
            row = await db.get(Meeting, sid)
            row.status, row.partial, row.draft_text = 'READY', True, 'Shënimet e plota.'
            row.request_id = '123456'
            await db.commit()
            other = SimpleNamespace(id=uuid.uuid4())
            with self.assertRaises(HTTPException) as unreadable:
                await service.meeting_record(db, other, sid)
            self.assertEqual(unreadable.exception.status_code, 404)
            self.assertEqual((await service.list_meeting_records(db, other, 30, 0))['items'], [])
            organizer = SimpleNamespace(id=self.uid)
            history = await service.list_meeting_records(db, organizer, 30, 0)
            self.assertEqual([item['id'] for item in history['items']], [str(sid)])
            result = await service.meeting_record(db, organizer, sid)
            self.assertTrue(result['partial'])
            self.assertEqual(result['full_notes'], 'Shënimet e plota.')
            self.assertEqual(result['transcript'][0]['speaker'], 'Ana')
            self.assertEqual(result['transcript'][0]['end_ms'], 1000)

    async def test_notetaker_shared_records_include_list_notes_and_transcript_for_staff(self):
        from types import SimpleNamespace
        from fastapi import HTTPException

        scheduled = await self.scheduled_meeting(timedelta(minutes=2), recorder='ai_agent')
        shared = await self.scheduled_meeting(timedelta(minutes=2))
        async with self.sessions() as db:
            panel_meeting = await db.get(Meeting, shared)
            panel_meeting.request_id, panel_meeting.private_channel_id = '123456', '99'
            quick = dict.fromkeys(jobs.provider.QUICK_SECTIONS, [])
            for sid in (scheduled, shared):
                row = await db.get(Meeting, sid)
                row.status, row.draft_text, row.quick_summary = 'SAVED', 'Shënimet.', quick
            await db.commit()
        staff = SimpleNamespace(id=uuid.uuid4(), role='STAFF')
        with patch.object(service.settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(service.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '99'):
            async with self.sessions() as db:
                history = await service.list_meeting_records(db, staff, 30, 0)
                self.assertEqual({item['id'] for item in history['items']}, {str(scheduled), str(shared)})
                for sid in (scheduled, shared):
                    detail = await service.meeting_record(db, staff, sid)
                    self.assertEqual(detail['full_notes'], 'Shënimet.')
                    self.assertEqual(detail['quick_summary'], quick)
                    self.assertEqual(detail['transcript'][0]['speaker'], 'Ana')
                (await db.get(Meeting, shared)).guild_id = '999'
                (await db.get(Meeting, scheduled)).status = 'LISTENING'
                await db.commit()
                self.assertEqual((await service.list_meeting_records(db, staff, 30, 0))['items'], [])
                for sid in (scheduled, shared):
                    with self.assertRaises(HTTPException) as unreadable:
                        await service.meeting_record(db, staff, sid)
                    self.assertEqual(unreadable.exception.status_code, 404)

    async def test_scheduled_ai_agent_save_failure_preserves_notes_for_manual_save(self):
        sid = await self.scheduled_meeting(timedelta(minutes=2), recorder='ai_agent')
        with patch.object(jobs, 'SessionLocal', self.sessions), \
             patch('app.services.discord_voice_openai.summarize_meeting', AsyncMock(return_value='AI Agent: raporti.')), \
             patch.object(service, 'store_note', AsyncMock(side_effect=RuntimeError('save_failed'))):
            with self.assertLogs(jobs.log, 'WARNING'):
                await jobs.process_voice_meetings()
        async with self.sessions() as db:
            row = await db.get(Meeting, sid)
            self.assertEqual(row.status, 'READY')
            self.assertIn('\n\nAna: Ana dërgon raportin.', row.draft_text)
            self.assertTrue(row.draft_text.endswith('**Përmbledhje e shkurtër**\n\nAI Agent: raporti.'))
            self.assertIsNone(row.delivered_at)
            self.assertIsNone(row.saved_note_id)

    async def scheduled_meeting(self,stopped_ago, *, recorder='primary'):
        from app.models.discord_voice_meeting import DiscordVoiceSegment as Segment
        sid=uuid.uuid4()
        async with self.sessions() as db:
            db.add(Meeting(id=sid,user_id=self.uid,link_id=self.lid,department_id=self.did,guild_id='123',
                voice_channel_id='55',private_channel_id='44',recorder=recorder,
                request_id='autoai-202611100804' if recorder == 'ai_agent' else 'auto1h-202610201558',instance_id=uuid.uuid4(),
                capture_token_hash=service.token_hash('x'*40),title='1H',status='FINALIZING',stop_authorized=True,
                expected_segments=1,stopped_at=service.now()-stopped_ago))
            db.add(Segment(id=uuid.uuid4(),session_id=sid,sequence=0,speaker_id='12',speaker_name='Ana',start_ms=0,
                end_ms=1000,content_hash='h',status='DONE',transcript='Ana dërgon raportin.'))
            await db.commit()
        return sid

    async def test_openai_outage_keeps_the_1h_notes_for_a_later_retry(self):
        from app.services.discord_voice_openai import ProviderError
        sid=await self.scheduled_meeting(timedelta(minutes=2))
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',
                AsyncMock(side_effect=ProviderError(503))),patch.object(jobs.settings,'DISCORD_GUILD_ID','123'):
            stats=await jobs.process_voice_meetings()
            self.assertEqual(stats['retrying'],1)
            async with self.sessions() as db:
                row=await db.get(Meeting,sid)
                self.assertEqual(row.status,'FINALIZING');self.assertGreater(row.lease_until,service.now())
                self.assertEqual((await service.claim_deliveries(db))['jobs'],[])
            # The next tick inside the back-off leaves it alone.
            self.assertEqual((await jobs.process_voice_meetings())['retrying'],0)

    async def test_1h_transcript_is_saved_when_summary_retries_expire(self):
        from app.services.discord_voice_openai import ProviderError
        from app.models.ga_note import GaNote
        sid=await self.scheduled_meeting(timedelta(minutes=40))
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',
                AsyncMock(side_effect=ProviderError(503))),patch.object(service.settings,'DISCORD_GUILD_ID','123'):
            await jobs.process_voice_meetings()
            async with self.sessions() as db:
                row=await db.get(Meeting,sid)
                self.assertEqual(row.status,'SAVED');self.assertIsNotNone(row.delivered_at)
                note=await db.get(GaNote,row.saved_note_id)
                self.assertIn('\n\nAna: Ana dërgon raportin.', note.content)
                self.assertTrue(note.content.endswith('Përmbledhja nuk u gjenerua.'))

    async def test_1h_notes_that_px_notes_refuses_stay_ready_for_the_save_button(self):
        sid=await self.scheduled_meeting(timedelta(minutes=2))
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',
                AsyncMock(return_value='**Përmbledhja:** Raporti.')),patch.object(service,'store_note',AsyncMock(side_effect=RuntimeError('x'))):
            with self.assertLogs(jobs.log,'WARNING') as logs:await jobs.process_voice_meetings()
        self.assertIn('stage=px_notes',logs.output[0])
        async with self.sessions() as db:
            row=await db.get(Meeting,sid)
            self.assertEqual(row.status,'READY');self.assertIsNone(row.delivered_at);self.assertIsNone(row.saved_note_id)

    async def test_stale_capture_recovers_as_partial_without_starting_audio(self):
        sid=uuid.uuid4()
        async with self.sessions() as db:
            db.add(Meeting(id=sid,user_id=self.uid,link_id=self.lid,department_id=self.did,guild_id='123',
                voice_channel_id='55',private_channel_id='44',request_id='998',instance_id=uuid.uuid4(),
                capture_token_hash=service.token_hash('x'*40),title='Staff',status='LISTENING',heartbeat_at=service.now()-timedelta(seconds=120)))
            await db.commit()
        with patch.object(jobs,'SessionLocal',self.sessions):await jobs.process_voice_meetings()
        async with self.sessions() as db:
            row=await db.get(Meeting,sid);self.assertTrue(row.partial);self.assertNotEqual(row.status,'LISTENING')
