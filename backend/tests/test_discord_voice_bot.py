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

    def test_mira_joins_1h_two_minutes_before_each_weekday_slot(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from discord_voice_meetings import auto_join_slot
        tz=ZoneInfo('Europe/Tirane');times='09:58,10:58,11:48,14:18,15:58'
        monday=lambda h,m,s=0:datetime(2026,10,19,h,m,s,tzinfo=tz)
        self.assertEqual(auto_join_slot(monday(9,58,30),times),monday(9,58))
        self.assertEqual(auto_join_slot(monday(11,49,59),times),monday(11,48))
        self.assertIsNone(auto_join_slot(monday(9,57,59),times))
        # Failed connections are retried until 2 minutes after the 1H starts.
        self.assertEqual(auto_join_slot(monday(10,1,59),times),monday(9,58))
        self.assertIsNone(auto_join_slot(monday(10,2,0),times))
        self.assertIsNone(auto_join_slot(datetime(2026,10,24,9,58,tzinfo=tz),times))  # Saturday

    def auto_fixture(self):
        from types import SimpleNamespace
        bot,c,i=self.fixture()
        voice=Mock(spec=discord.VoiceChannel);voice.id=55;voice.name='1H 820';voice.members=[]
        private=Mock(spec=discord.TextChannel);private.id=44;private.topic='PrimeFlow personal workspace: 77';private.send=AsyncMock()
        guild=SimpleNamespace(id=123,voice_channels=[voice],text_channels=[private],get_channel=lambda cid:voice if cid==55 else None)
        bot.get_guild=Mock(return_value=guild)
        return bot,c,voice,private,guild

    async def test_scheduled_slot_starts_one_meeting_as_the_owner_in_their_private_channel(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        bot,c,voice,private,guild=self.auto_fixture()
        when=datetime(2026,10,19,9,58,tzinfo=ZoneInfo('Europe/Tirane'))
        with patch('discord_voice_meetings.settings') as s,patch.object(c,'begin',AsyncMock()) as begin:
            s.DISCORD_GUILD_ID='123';s.DISCORD_1H_VOICE_CHANNEL_ID='55';s.DISCORD_1H_AUTO_OWNER_DISCORD_ID='77'
            s.DISCORD_1H_AUTO_JOIN_TIMES='09:58';s.APP_TIMEZONE='Europe/Tirane'
            await c.tick(when);await c.tick(when)
        begin.assert_awaited_once()
        kwargs=begin.await_args.kwargs
        self.assertEqual(kwargs['actor'],{'discord_user_id':'77','guild_id':'123','channel_id':'44','voice_channel_id':'55'})
        self.assertEqual(kwargs['request_id'],'auto1h-202610190958');self.assertIs(kwargs['voice'],voice)

    async def test_failed_join_is_retried_in_the_slot_and_the_organizer_hears_when_mira_gives_up(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        bot,c,voice,private,guild=self.auto_fixture()
        when=datetime(2026,10,19,9,58,tzinfo=ZoneInfo('Europe/Tirane'))
        with patch('discord_voice_meetings.settings') as s,patch.object(c,'begin',AsyncMock(side_effect=ValueError('connect_timeout'))) as begin:
            s.DISCORD_GUILD_ID='123';s.DISCORD_1H_VOICE_CHANNEL_ID='55';s.DISCORD_1H_AUTO_OWNER_DISCORD_ID='77'
            s.DISCORD_1H_AUTO_JOIN_TIMES='09:58'
            for second in (0,40,80,120,160):await c.tick(when+timedelta(seconds=second))
        self.assertEqual([x.kwargs['request_id'] for x in begin.await_args_list],
            ['auto1h-202610190958','auto1h-202610190958-2','auto1h-202610190958-3'])
        private.send.assert_awaited_once()
        self.assertIn('nuk po regjistrohet',private.send.await_args.args[0])

    async def test_a_retry_that_connects_ends_the_attempts_for_the_slot(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        bot,c,voice,private,guild=self.auto_fixture()
        when=datetime(2026,10,19,9,58,tzinfo=ZoneInfo('Europe/Tirane'))
        with patch('discord_voice_meetings.settings') as s,patch.object(c,'begin',AsyncMock(side_effect=[ValueError('connect_timeout'),None])) as begin:
            s.DISCORD_GUILD_ID='123';s.DISCORD_1H_VOICE_CHANNEL_ID='55';s.DISCORD_1H_AUTO_OWNER_DISCORD_ID='77'
            s.DISCORD_1H_AUTO_JOIN_TIMES='09:58'
            # Everyone already left by 09:59:40 (no active meeting), yet Mira does not rejoin the slot.
            for second in (0,30,100):await c.tick(when+timedelta(seconds=second))
        self.assertEqual(begin.await_count,2);private.send.assert_not_awaited()

    async def test_meeting_already_running_is_not_replaced_by_the_schedule(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        bot,c,voice,private,guild=self.auto_fixture()
        c.active={'id':'s','finishing':False,'voice_channel':voice,'seen_people':True,'empty_since':None}
        voice.members=[SimpleNamespace(bot=False)]
        with patch('discord_voice_meetings.settings') as s,patch.object(c,'begin',AsyncMock()) as begin:
            s.DISCORD_1H_AUTO_OWNER_DISCORD_ID='77';s.DISCORD_1H_AUTO_JOIN_TIMES='09:58'
            await c.tick(datetime(2026,10,19,9,58,tzinfo=ZoneInfo('Europe/Tirane')))
        begin.assert_not_awaited()

    async def test_mira_leaves_30_seconds_after_the_last_person_leaves(self):
        from datetime import datetime, timedelta
        bot,c,voice,private,guild=self.auto_fixture();t=datetime(2026,10,19,10,0)
        c.active={'id':'s','finishing':False,'voice_channel':voice,'seen_people':False,'empty_since':None,'listening':True}
        with patch.object(c,'auto_stop',AsyncMock()) as stop:
            voice.members=[SimpleNamespace(bot=False),SimpleNamespace(bot=True)];await c.check_presence(t)
            voice.members=[SimpleNamespace(bot=True)];await c.check_presence(t+timedelta(seconds=5))
            await c.check_presence(t+timedelta(seconds=30));stop.assert_not_awaited()
            await c.check_presence(t+timedelta(seconds=36))
        stop.assert_awaited_once_with('everyone_left')

    async def test_mira_leaves_if_nobody_comes_within_ten_minutes(self):
        from datetime import datetime, timedelta
        bot,c,voice,private,guild=self.auto_fixture();t=datetime(2026,10,19,9,58)
        c.active={'id':'s','finishing':False,'voice_channel':voice,'seen_people':False,'empty_since':None,'listening':True}
        with patch.object(c,'auto_stop',AsyncMock()) as stop:
            await c.check_presence(t);await c.check_presence(t+timedelta(minutes=9));stop.assert_not_awaited()
            await c.check_presence(t+timedelta(minutes=10))
        stop.assert_awaited_once_with('nobody_came')

    async def test_automatic_stop_uses_the_organizer_authorization_and_finalizes(self):
        bot,c,voice,private,guild=self.auto_fixture()
        capture=SimpleNamespace(stop=AsyncMock(return_value={'last_sequence':2,'partial':False}),drain=AsyncMock(),failed=False,close=AsyncMock())
        actor={'discord_user_id':'77','guild_id':'123','channel_id':'44','voice_channel_id':'55'}
        c.active={'id':'s','capture':capture,'worker':{},'actor':actor,'partial':False,'heartbeat':None,'finishing':False}
        await c.auto_stop('everyone_left');await c.finalization
        bot.bridge.assert_any_await('/bot/voice-meetings/s/authorize-stop',actor)
        capture.stop.assert_awaited_once()
        self.assertTrue(any(x.args[0].endswith('/finish') for x in bot.bridge.await_args_list))

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
