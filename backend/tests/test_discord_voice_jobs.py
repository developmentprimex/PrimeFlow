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
