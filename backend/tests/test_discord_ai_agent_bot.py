"""The second identity stays separate from both existing bots and never joins on startup."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'ai-agent-bot-test-secret')
import discord
import discord_ai_agent_bot as worker


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
                self.assertFalse(status['recording'])
                self.assertNotIn('token', json.dumps(status).lower())
                channel.connect.assert_not_called()
                await bot.on_disconnect()
                self.assertFalse(worker.STATUS_FILE.exists())
        finally:
            await bot.close()
