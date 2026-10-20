import asyncio
import unittest
from unittest.mock import AsyncMock
from discord_voice_client import VoiceCaptureClient

class VoiceClientTests(unittest.IsolatedAsyncioTestCase):
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
