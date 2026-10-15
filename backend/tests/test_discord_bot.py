"""Requires the optional requirements-discord.txt dependencies; never logs in."""
import importlib.util
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "test-discord-secret-not-for-production")

AVAILABLE = importlib.util.find_spec("discord") is not None
if AVAILABLE:
    import discord
    import discord_bot as bot


@unittest.skipUnless(AVAILABLE, "Install requirements-discord.txt to test the Discord worker")
class DiscordBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_dropdown_pages_are_valid_and_keep_every_task(self):
        tasks = [{"id": str(uuid.uuid4()), "title": "x" * 500, "status": "IN_PROGRESS"} for _ in range(63)]
        pages = bot.task_pages(tasks, "Raportimi")
        self.assertEqual(len(pages), 3)
        ids = []
        for text, view in pages:
            self.assertLessEqual(len(text), 2000)
            select = view.children[0]
            self.assertLessEqual(len(select.options), 25)
            self.assertTrue(all(len(option.label) <= 100 for option in select.options))
            ids.extend(option.value for option in select.options)
        self.assertEqual(ids, [task["id"] for task in tasks])

    async def test_action_menu_persistent_and_modal_defaults(self):
        view = bot.task_view(str(uuid.uuid4()))
        self.assertTrue(view.is_persistent())
        self.assertLessEqual(len(view.children[0].options), 25)
        modal = bot.InstructionModal(Mock(), str(uuid.uuid4()), 5)
        self.assertEqual(modal.instruction.default, "Bëje WFE.")

    async def test_empty_bucket_and_long_multiline_content(self):
        pages = bot.task_pages([], "PM")
        self.assertIsNone(pages[0][1])
        self.assertIn("Nuk ke", pages[0][0])
        text = ("Pikë e gjatë\n" * 500) + "x" * 4000
        self.assertTrue(all(len(part) <= 1800 for part in bot.chunks(text)))

    async def test_wrong_guild_or_unmarked_channel_is_rejected(self):
        instance = object.__new__(bot.PrimeFlowBot)
        with patch.object(bot.settings, "DISCORD_GUILD_ID", "123"):
            with self.assertRaises(ValueError):
                await instance.private_channel(999, 10, 20)
            guild = Mock()
            guild.get_member.return_value = Mock()
            guild.get_channel.return_value = SimpleNamespace(topic="public")
            with patch.object(bot.PrimeFlowBot, "get_guild", return_value=guild):
                with self.assertRaises(ValueError):
                    await instance.private_channel(123, 10, 20)

    async def test_command_registration_and_bridge_url_without_login(self):
        with patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), patch.object(bot.settings, "DISCORD_BRIDGE_SECRET", "x" * 32), \
             patch.object(bot.settings, "PRIMEFLOW_API_BASE_URL", "http://primeflow.test"), \
             patch.object(bot.app_commands.CommandTree, "sync", new_callable=AsyncMock), \
             patch.object(bot.tasks.Loop, "start"):
            instance = bot.PrimeFlowBot()
            try:
                await instance.setup_hook()
                commands = instance.tree.get_commands(guild=discord.Object(id=123))
                self.assertEqual({command.name for command in commands}, {"lidh", "detyrat", "pyet"})
                self.assertEqual(str(instance.http_bridge.base_url), "http://primeflow.test/api/discord/")
                request = instance.http_bridge.build_request("POST", "/bot/tasks", json={})
                self.assertEqual(str(request.url), "http://primeflow.test/api/discord/bot/tasks")
                self.assertEqual(request.headers["X-Primeflow-Discord-Secret"], "x" * 32)
            finally:
                await instance.close()

    async def test_privacy_is_repaired_before_returning_channel(self):
        instance = object.__new__(bot.PrimeFlowBot)
        member, everyone, me = Mock(), Mock(), Mock()
        guild = Mock(default_role=everyone, me=me)
        guild.get_member.return_value = member
        channel = Mock(spec=discord.TextChannel)
        channel.topic = "PrimeFlow personal workspace: 20"
        channel.overwrites = {}
        channel.edit = AsyncMock()
        guild.get_channel.return_value = channel
        with patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), patch.object(bot.PrimeFlowBot, "get_guild", return_value=guild):
            result = await instance.private_channel(123, 10, 20)
        self.assertIs(result, channel)
        grants = channel.edit.call_args.kwargs["overwrites"]
        self.assertFalse(grants[everyone].view_channel)
        self.assertTrue(grants[member].view_channel)
        self.assertEqual(set(grants), {everyone, member, me})


if __name__ == "__main__":
    unittest.main()
