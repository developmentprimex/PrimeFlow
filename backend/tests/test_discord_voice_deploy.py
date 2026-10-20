import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','voice-tests-not-a-production-secret')
from scripts import configure_discord
from app.config import settings
from scripts.check_discord_voice import supported_node
import discord_bot
import discord

class VoiceDeployTests(unittest.IsolatedAsyncioTestCase):
    def test_voice_is_explicitly_opt_in_and_configuration_is_preserved(self):
        base=configure_discord.build_config({})
        self.assertEqual(base['DISCORD_MEETING_NOTES_ENABLED'],'false')
        with self.assertRaises(ValueError):configure_discord.build_config({'DISCORD_MEETING_NOTES_ENABLED':'sometimes'})

    async def test_commands_only_registered_when_enabled_without_logging_in(self):
        with patch.object(settings,'DISCORD_MEETING_NOTES_ENABLED',True),patch.object(settings,'DISCORD_GUILD_ID','123'),patch.object(settings,'DISCORD_BRIDGE_SECRET','x'*32),patch.object(discord_bot.app_commands.CommandTree,'sync',AsyncMock()),patch.object(discord_bot.tasks.Loop,'start'):
            bot=discord_bot.PrimeFlowBot()
            try:
                await bot.setup_hook()
                group=bot.tree.get_command('takimi',guild=discord.Object(id=123))
                self.assertEqual({c.name for c in group.commands},{'fillo','mbaro'})
            finally:await bot.close()

    def test_workflow_has_isolated_locked_install_and_preflight(self):
        workflow=(Path(__file__).resolve().parents[2]/'.github/workflows/deploy.yml').read_text()
        self.assertIn('DISCORD_MEETING_NOTES_ENABLED',workflow)
        self.assertIn('check_discord_voice.py',workflow)

    def test_node_version_floor_is_checked_before_install(self):
        for version in ['v20.19.0','v22.11.0','unknown']:self.assertFalse(supported_node(version))
        for version in ['v22.12.0','v24.13.0']:self.assertTrue(supported_node(version))
