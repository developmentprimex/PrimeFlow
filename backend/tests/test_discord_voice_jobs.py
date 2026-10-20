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
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',AsyncMock(return_value='Vendime: kontrollo.')) as summary:
            await jobs.process_voice_meetings()
            self.assertEqual([s['sequence'] for s in summary.call_args.args[1]],[0,1])
            async with self.sessions() as db:self.assertEqual((await db.get(Meeting,sid)).status,'READY')

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
        with patch.object(jobs,'SessionLocal',self.sessions),patch('app.services.discord_voice_openai.summarize_meeting',AsyncMock(return_value='**Përmbledhja:** Raporti.')):
            await jobs.process_voice_meetings()
        async with self.sessions() as db:
            row=await db.get(Meeting,sid)
            self.assertEqual(row.status,'SAVED');self.assertIsNotNone(row.delivered_at)
            note=await db.get(GaNote,row.saved_note_id)
            self.assertEqual(note.content,'**Përmbledhja:** Raporti.');self.assertEqual(note.created_by,self.uid)
        async with self.sessions() as db:
            self.assertEqual((await service.claim_deliveries(db))['jobs'],[])

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
