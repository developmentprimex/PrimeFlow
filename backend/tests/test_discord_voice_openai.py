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
    async def test_short_speech_tail_is_padded_to_provider_minimum_without_changing_samples(self):
        pcm=b'\x20\x10\x20\x10'*960
        with patch.object(provider,'request',AsyncMock(return_value={'text':'Po.'})) as call:
            self.assertEqual(await provider.transcribe_segment(wav(pcm)),'Po.')
        audio=call.call_args.kwargs['files']['file'][1]
        with wave.open(io.BytesIO(audio),'rb') as w:
            self.assertGreaterEqual(w.getnframes(),4800)
            self.assertEqual(w.readframes(960),pcm)

    def openai(self,*responses):
        """Route provider HTTP calls to canned responses; returns the list of seen requests."""
        import httpx
        seen=[];queue=list(responses);real=httpx.AsyncClient
        def handler(request):
            seen.append(request);status,headers,body=queue.pop(0)
            return httpx.Response(status,headers=headers,json=body)
        transport=httpx.MockTransport(handler)
        return seen,patch.object(provider.httpx,'AsyncClient',lambda **kw:real(transport=transport,**kw))

    async def test_rate_limited_transcription_waits_and_retries_the_same_segment(self):
        seen,client=self.openai((429,{'retry-after':'3'},{'error':{}}),(503,{},{'error':{}}),(200,{},{'text':'Po.'}))
        with patch.object(settings,'OPENAI_API_KEY','test'),client,patch.object(provider.asyncio,'sleep',AsyncMock()) as sleep:
            self.assertEqual(await provider.transcribe_segment(wav()),'Po.')
        self.assertEqual(len(seen),3)
        self.assertEqual([c.args[0] for c in sleep.await_args_list],[3.0,4])

    async def test_rejected_transcription_is_not_retried_and_keeps_the_http_status(self):
        seen,client=self.openai((400,{},{'error':{}}))
        with patch.object(settings,'OPENAI_API_KEY','test'),client,patch.object(provider.asyncio,'sleep',AsyncMock()):
            with self.assertRaises(provider.ProviderError) as caught:await provider.transcribe_segment(wav())
        self.assertEqual(len(seen),1);self.assertEqual(caught.exception.status,400)
        # Other callers match on this message, so it must not change.
        self.assertEqual(str(caught.exception),'meeting_provider_failed');self.assertIsInstance(caught.exception,ValueError)

    async def test_persistent_rate_limit_gives_up_within_the_bot_upload_timeout(self):
        seen,client=self.openai(*[(429,{'retry-after':'120'},{'error':{}})]*5)
        with patch.object(settings,'OPENAI_API_KEY','test'),client,patch.object(provider.asyncio,'sleep',AsyncMock()) as sleep:
            with self.assertRaises(provider.ProviderError) as caught:await provider.transcribe_segment(wav())
        self.assertEqual(caught.exception.status,429);self.assertEqual(len(seen),3)
        self.assertLessEqual(sum(c.args[0] for c in sleep.await_args_list)+3*provider.TRANSCRIBE_TIMEOUT,90)

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
            result=await provider.summarize_meeting('Staff',[{'sequence':0,'speaker_id':'12','speaker_name':'Ana','start_ms':0,'end_ms':1000,'transcript':'Kontrollo.'}])
            # Notes carry no partial-audio banner, and the model is not told to write one.
            self.assertNotIn('PJESSHME',result);self.assertNotIn('partial',call.call_args.kwargs['json']['input'][1]['content'])
            payload=call.call_args.kwargs['json'];self.assertNotIn('tools',payload);self.assertFalse(payload['store'])
            self.assertIn('Ana',payload['input'][1]['content']);self.assertIn('Mos shpik',payload['input'][0]['content'])

    async def test_final_notes_follow_the_ga_meeting_structure_with_albanian_date(self):
        from datetime import datetime, timezone
        response={'output':[{'type':'message','content':[{'type':'output_text','text':'Përmbledhja:\nU rishikua plani.'}]}]}
        with patch.object(provider,'request',AsyncMock(return_value=response)) as call:
            result=await provider.summarize_meeting('Staff',[{'sequence':0,'speaker_name':'Ana','transcript':'Ana dërgon raportin të premten.'}],
                meeting_date=datetime(2026,6,26,8,0,tzinfo=timezone.utc))
        system=call.call_args.kwargs['json']['input'][0]['content']
        for heading in ('Përmbledhja:','Kapitujt & Temat:','Detyrat e Takimit:','Pyetjet Kryesore:','Shënime:'):
            self.assertIn(heading,system)
        self.assertIn('E pazgjidhur',system)
        # Short meetings get short notes: empty sections are dropped, nothing is repeated.
        self.assertIn('hiq të tjerat fare',system);self.assertIn('mos e përsërit',system)
        self.assertNotIn('Nuk u identifikuan detyra.',system)
        self.assertIn('[segmenti 0, Emri i folësit, 00:02–00:07]',system)
        self.assertTrue(result.startswith('E premte, 26 qershor 2026\nStaff\n\nPërmbledhja:'))

    async def test_default_title_with_channel_and_time_is_kept_without_a_second_date(self):
        from datetime import datetime, timezone
        response={'output':[{'type':'message','content':[{'type':'output_text','text':'**Përmbledhja:** Takimi nis.'}]}]}
        title='1H 820/10/11/1150/1420/16 · 20.10.2026 10:32'
        with patch.object(provider,'request',AsyncMock(return_value=response)):
            result=await provider.summarize_meeting(title,[{'sequence':0,'transcript':'Përshëndetje.'}],
                meeting_date=datetime(2026,10,20,8,32,tzinfo=timezone.utc))
        self.assertTrue(result.startswith(title+'\n\n**Përmbledhja:**'))

    async def test_partial_batches_keep_tasks_and_questions_and_only_the_last_pass_uses_the_template(self):
        systems=[]
        async def respond(path,**kwargs):
            systems.append(kwargs['json']['input'][0]['content'])
            return {'output':[{'type':'message','content':[{'type':'output_text','text':'Pjesë [0].'}]}]}
        with patch.object(provider,'request',respond):
            await provider.summarize_meeting('Staff',[{'sequence':i,'transcript':'x'*12000} for i in range(3)])
        self.assertGreater(len(systems),1)
        self.assertTrue(all('Detyrat e Takimit:' not in s and 'pyetjet' in s for s in systems[:-1]))
        self.assertIn('Detyrat e Takimit:',systems[-1])

    async def test_long_transcript_reduces_all_batches_including_last(self):
        seen=[]
        async def respond(path,**kwargs):
            seen.append(kwargs['json']['input'][1]['content'])
            return {'output':[{'type':'message','content':[{'type':'output_text','text':'Përmbledhje me burime [0,1,2].'}]}]}
        with patch.object(provider,'request',respond):
            await provider.summarize_meeting('Staff',[{'sequence':i,'transcript':('x'*12000 if i<2 else 'LAST_DECISION')} for i in range(3)])
        self.assertGreater(len(seen),1);self.assertTrue(any('LAST_DECISION' in item for item in seen))
