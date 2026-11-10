"""The second identity stays separate from both existing bots and never joins on startup."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'ai-agent-bot-test-secret')
import discord
import discord_ai_agent_bot as worker


class AIAgentScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.capture = worker.AIAgentCapture(SimpleNamespace(voice_recorder='ai_agent'))
        self.capture.check_presence = AsyncMock()
        self.capture.auto_start = AsyncMock()
        self.at = datetime(2026, 11, 10, 8, 4, tzinfo=ZoneInfo('Europe/Budapest'))
        for name, value in {
            'DISCORD_AI_AGENT_AUTO_JOIN_TIMES': '08:04,11:59,16:09',
            'DISCORD_AI_AGENT_AUTO_OWNER_DISCORD_ID': '123',
        }.items():
            patcher = patch.object(worker.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_each_requested_slot_starts_once_and_stays_stopped_in_the_same_window(self):
        for hour, minute in ((8, 4), (11, 59), (16, 9)):
            at = self.at.replace(hour=hour, minute=minute)
            await self.capture.tick(at)
            await self.capture.tick(at + timedelta(seconds=15))
        self.assertEqual(self.capture.auto_start.await_count, 3)
        self.assertEqual([call.args[0].strftime('%H:%M') for call in self.capture.auto_start.await_args_list],
                         ['08:04', '11:59', '16:09'])

    async def test_no_weekend_outside_window_or_disabled_schedule_join(self):
        for at in (self.at - timedelta(seconds=1), self.at + timedelta(minutes=4),
                   self.at.replace(day=14), self.at.replace(day=15)):
            await self.capture.tick(at)
        with patch.object(worker.settings, 'DISCORD_AI_AGENT_AUTO_JOIN_TIMES', ''):
            await self.capture.tick(self.at)
        with patch.object(worker.settings, 'DISCORD_AI_AGENT_AUTO_OWNER_DISCORD_ID', None):
            await self.capture.tick(self.at)
        self.capture.auto_start.assert_not_awaited()
        self.assertEqual(self.capture.check_presence.await_count, 6)

    async def test_active_recording_is_preserved_and_next_day_can_join(self):
        self.capture.active = {'id': 'manual-recording'}
        await self.capture.tick(self.at)
        self.capture.auto_start.assert_not_awaited()
        self.capture.active = None
        await self.capture.tick(self.at)
        await self.capture.tick(self.at + timedelta(days=1))
        self.assertEqual(self.capture.auto_start.await_count, 2)

    async def test_connection_failures_retry_at_most_three_times(self):
        self.capture.auto_start.side_effect = ValueError('not_ready')
        for seconds in (0, 15, 30, 45):
            await self.capture.tick(self.at + timedelta(seconds=seconds))
        self.assertEqual(self.capture.auto_start.await_count, 3)
        self.assertEqual([call.args[2] for call in self.capture.auto_start.await_args_list], [1, 2, 3])

    async def test_scheduled_join_targets_only_ai_agent_with_independent_request_ids(self):
        target = Mock(spec=discord.VoiceChannel)
        target.id = 456
        channel = SimpleNamespace(id=77, send=AsyncMock())
        guild = SimpleNamespace(id=123, get_channel=Mock(return_value=target))
        self.capture.organizer_channel = Mock(return_value=(guild, channel))
        self.capture.begin = AsyncMock()
        with patch.object(worker.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '456'):
            for attempt in (1, 2):
                await worker.AIAgentCapture.auto_start(self.capture, self.at, '123', attempt)
        calls = self.capture.begin.await_args_list
        self.assertEqual([call.kwargs['request_id'] for call in calls],
                         ['autoai-202611100804', 'autoai-202611100804-2'])
        for call in calls:
            self.assertIs(call.kwargs['voice'], target)
            self.assertEqual(call.kwargs['actor']['voice_channel_id'], '456')
            self.assertEqual(call.kwargs['actor']['channel_id'], '77')
        guild.get_channel.assert_called_with(456)
        guild.get_channel.return_value = None
        with patch.object(worker.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '456'), self.assertRaises(ValueError):
            await worker.AIAgentCapture.auto_start(self.capture, self.at, '123')
        self.assertEqual(self.capture.begin.await_count, 2)

    async def test_worker_tick_uses_app_local_time(self):
        bot = SimpleNamespace(meeting_capture=SimpleNamespace(tick=AsyncMock(), panel=SimpleNamespace(tick=AsyncMock())),
                              publish_status=Mock())
        with patch.object(worker.settings, 'APP_TIMEZONE', 'Europe/Budapest'), \
             patch.object(worker.voice, 'deliver_meeting_results', AsyncMock()):
            await worker.AIAgentBot.watch_capture.coro(bot)
        at = bot.meeting_capture.tick.await_args.args[0]
        self.assertEqual(str(at.tzinfo), 'Europe/Budapest')


class AIAgentBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_recording_commands_are_separate_and_start_rejects_other_voice_channels(self):
        from unittest.mock import AsyncMock
        with patch.object(worker.settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(worker.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '77'), \
             patch.object(worker.settings, 'DISCORD_MEETING_NOTES_ENABLED', True), \
             patch.object(worker.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '456'), \
             patch.object(worker.app_commands.CommandTree, 'sync', AsyncMock()), \
             patch.object(worker.tasks.Loop, 'start'):
            bot = worker.AIAgentBot()
            try:
                await bot.setup_hook()
                group = bot.tree.get_command('ai-agent', guild=discord.Object(id=123))
                self.assertEqual({command.name for command in group.commands}, {'fillo', 'mbaro', 'statusi'})
                self.assertIsNone(bot.tree.get_command('mira', guild=discord.Object(id=123)))
                self.assertIsNone(bot.tree.get_command('takimi', guild=discord.Object(id=123)))
                interaction = SimpleNamespace(
                    guild_id=123, channel_id=44,
                    user=SimpleNamespace(voice=SimpleNamespace(channel=SimpleNamespace(id=999))))
                with self.assertRaisesRegex(ValueError, 'AI Agent'), patch.object(bot.meeting_capture, 'begin', AsyncMock()) as begin:
                    await bot.meeting_capture.start(interaction, None, None)
                begin.assert_not_awaited()
            finally:
                await bot.close()

    def test_reused_host_or_main_token_is_rejected(self):
        with patch.object(worker.settings, 'DISCORD_BOT_TOKEN', 'main'), \
             patch.object(worker.settings, 'MIRA_HOST_BOT_TOKEN', 'host'), \
             patch.object(worker.settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(worker.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '456'):
            for token in (None, 'main', 'host'):
                with patch.object(worker.settings, 'DISCORD_AI_AGENT_BOT_TOKEN', token), self.assertRaises(ValueError):
                    worker.validate_configuration()
            with patch.object(worker.settings, 'DISCORD_AI_AGENT_BOT_TOKEN', 'new-bot'):
                worker.validate_configuration()

    async def test_ready_status_has_no_token_and_startup_does_not_connect_to_voice(self):
        bot = worker.AIAgentBot()
        channel = Mock(spec=discord.VoiceChannel)
        channel.id, channel.name = 456, 'AI Agent'
        channel.permissions_for.return_value = SimpleNamespace(view_channel=True, connect=True, send_messages=True)
        guild = SimpleNamespace(id=123, me=Mock(), get_channel=Mock(return_value=channel))
        bot._connection.user = SimpleNamespace(id=789)
        try:
            with tempfile.TemporaryDirectory() as directory, \
                 patch.object(worker, 'STATUS_FILE', Path(directory) / 'status.json'), \
                 patch.object(worker.settings, 'DISCORD_GUILD_ID', '123'), \
                 patch.object(worker.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '456'), \
                 patch.object(bot, 'get_guild', return_value=guild):
                await bot.on_ready()
                status = json.loads(worker.STATUS_FILE.read_text(encoding='utf-8'))
                self.assertTrue(status['ready'])
                self.assertEqual(status['bot_user_id'], '789')
                self.assertTrue(status['commands_configured'])
                self.assertTrue(status['recording_enabled'])
                self.assertIn('auto_join_times', status)
                self.assertEqual(status['auto_join_timezone'], worker.settings.APP_TIMEZONE)
                self.assertFalse(status['recording'])
                self.assertNotIn('token', json.dumps(status).lower())
                channel.connect.assert_not_called()
                await bot.on_disconnect()
                self.assertFalse(worker.STATUS_FILE.exists())
        finally:
            await bot.close()
