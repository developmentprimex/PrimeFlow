import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','voice-tests-not-a-production-secret')
import discord
from discord_voice_meetings import MeetingCaptureCoordinator
from discord_voice_ui import meeting_view

class VoiceBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_installed_discord_websocket_dispatches_voice_data_to_capture(self):
        import json
        import discord.gateway
        import discord_bot
        import asyncio
        client=object.__new__(discord_bot.PrimeFlowBot)
        client.meeting_capture=SimpleNamespace(gateway=AsyncMock())
        websocket=object.__new__(discord.gateway.DiscordWebSocket)
        pending=[]
        def dispatch(event,data):
            handler=getattr(client,'on_'+event,None)
            if handler:pending.append(asyncio.create_task(handler(data)))
        websocket._dispatch=dispatch
        packet={'op':0,'t':'VOICE_SERVER_UPDATE','d':{'guild_id':'123','endpoint':'voice.example.test','token':'test-only'}}
        with patch('discord_bot.settings.DISCORD_MEETING_NOTES_ENABLED',True):
            # The real library emits socket_raw_receive from its enabled debug hook.
            websocket.debug_log_receive(json.dumps(packet))
            await asyncio.gather(*pending)
        client.meeting_capture.gateway.assert_awaited_once_with(packet)

    async def test_gateway_hook_ignores_non_voice_invalid_and_disabled_events(self):
        import json
        import discord_bot
        client=object.__new__(discord_bot.PrimeFlowBot)
        client.meeting_capture=SimpleNamespace(gateway=AsyncMock())
        with patch('discord_bot.settings.DISCORD_MEETING_NOTES_ENABLED',True):
            for payload in ['not json','[]',json.dumps({'op':0,'t':'MESSAGE_CREATE','d':{}}),json.dumps({'op':0,'t':'VOICE_STATE_UPDATE','d':[]})]:
                await client.on_socket_raw_receive(payload)
        with patch('discord_bot.settings.DISCORD_MEETING_NOTES_ENABLED',False):
            await client.on_socket_raw_receive(json.dumps({'op':0,'t':'VOICE_STATE_UPDATE','d':{}}))
        client.meeting_capture.gateway.assert_not_awaited()

    def fixture(self):
        bot=SimpleNamespace(bridge=AsyncMock(),private_channel=AsyncMock(),user=SimpleNamespace(id=3),
            ws=SimpleNamespace(send_as_json=AsyncMock()),get_guild=Mock(),get_channel=Mock())
        coord=MeetingCaptureCoordinator(bot)
        interaction=SimpleNamespace(user=SimpleNamespace(id=12,voice=None),guild_id=123,channel_id=44,id=99,
            followup=SimpleNamespace(send=AsyncMock()))
        return bot,coord,interaction

    async def test_missing_voice_or_stage_rejected_before_reserving_or_listening(self):
        bot,c,i=self.fixture()
        with self.assertRaises(ValueError):await c.start(i,None,None)
        bot.bridge.assert_not_awaited()
        i.user.voice=SimpleNamespace(channel=Mock(spec=discord.StageChannel))
        with self.assertRaises(ValueError):await c.start(i,None,None)
        bot.bridge.assert_not_awaited()

    async def test_failed_public_notice_never_starts_audio_and_releases_reservation(self):
        bot,c,i=self.fixture();channel=Mock(spec=discord.VoiceChannel)
        channel.id=55;channel.name='Staff';channel.permissions_for.return_value=SimpleNamespace(view_channel=True,connect=True,send_messages=True)
        channel.send=AsyncMock(side_effect=ValueError('notice_failed'));i.user.voice=SimpleNamespace(channel=channel)
        i.guild=SimpleNamespace(me=Mock());bot.bridge.return_value={'id':'11111111-1111-4111-8111-111111111111','status':'STARTING'}
        with patch.object(c,'preflight',AsyncMock()),patch('discord_voice_meetings.VoiceCaptureClient') as capture:
            with self.assertRaises(ValueError):await c.start(i,None,None)
            capture.assert_not_called()
        self.assertTrue(any(call.args[0].endswith('/interrupt') for call in bot.bridge.call_args_list))

    async def test_stop_leaves_before_drain_and_authorizes_first(self):
        import asyncio
        bot,c,i=self.fixture();sequence=[];block=asyncio.Event()
        async def stop():sequence.append('leave');return {'last_sequence':1,'partial':False}
        async def drain():sequence.append('drain');await block.wait()
        capture=SimpleNamespace(stop=stop,drain=drain,failed=False,close=AsyncMock())
        c.active={'id':'s','capture':capture,'worker':{},'actor':{},'partial':False,'heartbeat':None,'finishing':False}
        await c.stop(i,'s');self.assertEqual(sequence,['leave']);bot.bridge.assert_awaited()
        await asyncio.sleep(0);self.assertEqual(sequence,['leave','drain']);block.set()
        await c.finalization

    async def test_one_failed_heartbeat_does_not_interrupt_the_meeting(self):
        bot,c,i=self.fixture()
        active={'id':'s','capture':None,'worker':{},'actor':{},'partial':False,'heartbeat':None,'finishing':False}
        c.active=active;calls=0
        async def bridge(path,payload):
            nonlocal calls;calls+=1
            if calls==1:raise ValueError('temporary')
            c.active=None
        bot.bridge.side_effect=bridge
        with patch('discord_voice_meetings.asyncio.sleep',AsyncMock()),patch.object(c,'interrupt',AsyncMock()) as interrupt:
            await c.heartbeat(active)
        interrupt.assert_not_awaited();self.assertEqual(calls,2)

    async def test_heartbeat_that_keeps_failing_interrupts(self):
        bot,c,i=self.fixture()
        active={'id':'s','capture':None,'worker':{},'actor':{},'partial':False,'heartbeat':None,'finishing':False}
        c.active=active;bot.bridge.side_effect=ValueError('down')
        with patch('discord_voice_meetings.asyncio.sleep',AsyncMock()),patch.object(c,'interrupt',AsyncMock()) as interrupt:
            await c.heartbeat(active)
        interrupt.assert_awaited_once_with('heartbeat_failed');self.assertEqual(bot.bridge.await_count,3)

    def test_ui_has_only_text_controls_and_stable_ids(self):
        for state in ['LISTENING','READY','SAVED']:
            view=meeting_view({'id':'11111111-1111-4111-8111-111111111111','status':state,'note_url':'https://example.test/ga-ka-notes'})
            self.assertLessEqual(len(view.children),3)
            self.assertTrue(all(getattr(x,'url',None) or x.custom_id.startswith('pf:vm:') for x in view.children))

    async def test_dead_child_during_stop_cannot_wedge_future_meetings(self):
        bot,c,i=self.fixture()
        capture=SimpleNamespace(stop=AsyncMock(side_effect=ValueError('voice_process_unavailable')),
            drain=AsyncMock(),close=AsyncMock(),failed=True,last_sequence=3)
        c.active={'id':'s','capture':capture,'worker':{},'actor':{},'partial':False,'heartbeat':None,'finishing':False}
        await c.stop(i,'s')
        self.assertIsNotNone(c.finalization)
        await c.finalization
        self.assertIsNone(c.active);capture.close.assert_awaited()
        finish=[x for x in bot.bridge.call_args_list if x.args[0].endswith('/finish')]
        self.assertTrue(finish[0].args[1]['partial']);self.assertEqual(finish[0].args[1]['segment_count'],3)

    async def test_stop_while_notice_is_pending_never_starts_audio(self):
        import asyncio
        bot,c,i=self.fixture();channel=Mock(spec=discord.VoiceChannel);channel.id=55;channel.name='Staff'
        channel.permissions_for.return_value=SimpleNamespace(view_channel=True,connect=True,send_messages=True)
        posted=asyncio.Event();release=asyncio.Event()
        async def notice(*args,**kwargs):posted.set();await release.wait()
        channel.send=notice;i.user.voice=SimpleNamespace(channel=channel);i.guild=SimpleNamespace(me=Mock())
        bot.bridge.return_value={'id':'11111111-1111-4111-8111-111111111111','status':'STARTING'}
        with patch.object(c,'preflight',AsyncMock()),patch('discord_voice_meetings.VoiceCaptureClient') as capture:
            start=asyncio.create_task(c.start(i,None,None));await posted.wait()
            await c.stop(i);await c.finalization;release.set()
            with self.assertRaises(ValueError):await start
            capture.assert_not_called();self.assertIsNone(c.active)
