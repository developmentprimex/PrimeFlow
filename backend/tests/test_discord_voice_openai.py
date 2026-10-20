import io
import os
import wave
import unittest
from unittest.mock import AsyncMock, patch
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','voice-tests-not-a-production-secret')
from app.services import discord_voice_openai as provider
from app.config import settings

def wav(pcm=b'\x20\x10\x20\x10'*480):
    f=io.BytesIO()
    with wave.open(f,'wb') as w:w.setnchannels(2);w.setsampwidth(2);w.setframerate(48000);w.writeframes(pcm)
    return f.getvalue()

class VoiceProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_silence_is_empty_and_invalid_wav_never_calls_provider(self):
        with patch.object(provider,'request',AsyncMock()) as call:
            self.assertEqual(await provider.transcribe_segment(wav(bytes(1920))), '')
            with self.assertRaises(ValueError):await provider.transcribe_segment(b'not audio')
            call.assert_not_awaited()

    async def test_albanian_model_prompt_and_transcript(self):
        with patch.object(provider,'request',AsyncMock(return_value={'text':'Kontrollo raportin.'})) as call:
            self.assertEqual(await provider.transcribe_segment(wav()),'Kontrollo raportin.')
            data=call.call_args.kwargs['data'];self.assertEqual(data['model'],'gpt-transcribe')
            self.assertIn('shqip',data['prompt']);self.assertNotIn('language',data)

    async def test_summary_is_text_only_and_retains_speaker_references(self):
        response={'output':[{'type':'message','content':[{'type':'output_text','text':'Vendimet\nKontrollo.'}]}]}
        with patch.object(provider,'request',AsyncMock(return_value=response)) as call:
            result=await provider.summarize_meeting('Staff',[{'sequence':0,'speaker_id':'12','speaker_name':'Ana','start_ms':0,'end_ms':1000,'transcript':'Kontrollo.'}],partial=True)
            self.assertIn('PJESSHME',result)
            payload=call.call_args.kwargs['json'];self.assertNotIn('tools',payload);self.assertFalse(payload['store'])
            self.assertIn('Ana',payload['input'][1]['content']);self.assertIn('Mos shpik',payload['input'][0]['content'])

    async def test_long_transcript_reduces_all_batches_including_last(self):
        seen=[]
        async def respond(path,**kwargs):
            seen.append(kwargs['json']['input'][1]['content'])
            return {'output':[{'type':'message','content':[{'type':'output_text','text':'Përmbledhje me burime [0,1,2].'}]}]}
        with patch.object(provider,'request',respond):
            await provider.summarize_meeting('Staff',[{'sequence':i,'transcript':('x'*12000 if i<2 else 'LAST_DECISION')} for i in range(3)],partial=False)
        self.assertGreater(len(seen),1);self.assertTrue(any('LAST_DECISION' in item for item in seen))
