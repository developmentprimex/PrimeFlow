import asyncio
import unittest
from unittest.mock import AsyncMock
from discord_voice_client import VoiceCaptureClient

class VoiceClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_reported_packet_gap_is_diagnostic_and_does_not_interrupt_capture(self):
        c=self.client()
        with self.assertLogs('primeflow.discord.voice',level='WARNING') as logs:
            await c.handle({'type':'audio_gap','session_id':'s','instance_id':'i','reason':'decode_invalid_packet'})
        c.on_interruption.assert_not_awaited()
        self.assertFalse(c.failed)
        self.assertIn('decode_invalid_packet',' '.join(logs.output))

    async def test_worker_interruption_preserves_safe_reason_and_numeric_close_code(self):
        c=self.client()
        with self.assertLogs('primeflow.discord.voice',level='WARNING') as logs:
            await c.handle({'type':'interrupted','session_id':'s','instance_id':'i',
                'reason':'voice_disconnected','close_code':4014,'error':'never log raw tokens'})
            await asyncio.sleep(0)
        c.on_interruption.assert_awaited_once_with('voice_disconnected')
        self.assertIn('4014',' '.join(logs.output))
        self.assertNotIn('never log',' '.join(logs.output))

    def client(self):
        c=VoiceCaptureClient(AsyncMock(),AsyncMock(),AsyncMock())
        c.session_id='s';c.instance_id='i';c.guild_id='1';c.channel_id='2'
        return c

    async def test_gateway_payloads_are_strictly_limited_to_silent_voice_state(self):
        c=self.client()
        good={'op':4,'d':{'guild_id':'1','channel_id':'2','self_mute':True,'self_deaf':False}}
        await c.handle({'type':'gateway_send','session_id':'s','instance_id':'i','payload':good})
        c.send_gateway.assert_awaited_once_with(good)
        for bad in [dict(good,op=0), {'op':4,'d':dict(good['d'],guild_id='99')},
                    {'op':4,'d':dict(good['d'],self_mute=False)}, {'op':4,'d':dict(good['d'],channel_id='3')}]:
            with self.assertRaises(ValueError):await c.handle({'type':'gateway_send','session_id':'s','instance_id':'i','payload':bad})

    async def test_stop_is_sent_while_upload_is_pending(self):
        c=self.client();c.send=AsyncMock();c.stopped=asyncio.get_running_loop().create_future()
        c.send.side_effect=lambda _: c.stopped.set_result({'last_sequence':1,'partial':False})
        blocker=asyncio.Event()
        task=asyncio.create_task(blocker.wait());c.uploads.add(task)
        result=await c.stop()
        self.assertEqual(result['last_sequence'],1);c.send.assert_awaited_once_with({'type':'stop'})
        self.assertFalse(task.done());blocker.set();await task

    def test_child_environment_does_not_inherit_credentials(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret','DISCORD_BOT_TOKEN':'secret','DATABASE_URL':'secret'}):
            self.assertNotIn('OPENAI_API_KEY',VoiceCaptureClient.child_env())
            self.assertNotIn('DATABASE_URL',VoiceCaptureClient.child_env())

    async def test_wrong_instance_cannot_inject_segments(self):
        c=self.client()
        with self.assertRaises(ValueError):await c.handle({'type':'segment','session_id':'s','instance_id':'other'})
        c.on_segment.assert_not_awaited()

    async def test_malformed_gateway_payload_is_rejected_as_protocol_error(self):
        c=self.client()
        for payload in [None,[],{'op':4,'d':None}]:
            with self.assertRaises(ValueError):await c.handle({'type':'gateway_send','session_id':'s','instance_id':'i','payload':payload})

    async def test_close_leaves_guild_even_if_child_has_already_died(self):
        c=self.client();await c.close()
        c.send_gateway.assert_awaited_once_with({'op':4,'d':{'guild_id':'1','channel_id':None,'self_mute':True,'self_deaf':False}})

    async def test_close_during_process_spawn_cannot_start_late_capture(self):
        from unittest.mock import Mock, patch
        entered=asyncio.Event();release=asyncio.Event()
        process=Mock(returncode=None);process.wait=AsyncMock();process.stdin=Mock()
        async def spawn(*args,**kwargs):entered.set();await release.wait();return process
        c=self.client()
        with patch('asyncio.create_subprocess_exec',spawn):
            start=asyncio.create_task(c.start(session_id='s',instance_id='i',guild_id='1',channel_id='2',bot_user_id='3'))
            await entered.wait();await c.close();release.set()
            with self.assertRaises(ValueError):await start
            process.kill.assert_called_once();process.stdin.write.assert_not_called()
