"""Requires the optional requirements-discord.txt dependencies; never logs in."""
import importlib.util
import os
import json
import tempfile
from pathlib import Path
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
    async def test_personal_channel_names_use_people_and_resolve_name_collisions(self):
        self.assertEqual(bot.personal_channel_name('Rinesa Ahmedi'), 'primeflow-rinesa')
        self.assertEqual(bot.personal_channel_name('Elsa Ferati'), 'primeflow-elsa')
        self.assertEqual(bot.personal_channel_name('Ëndrra Çela'), 'primeflow-endrra')
        self.assertEqual(bot.personal_channel_name('Elsa Ferati', existing_names=['primeflow-elsa']),
            'primeflow-elsa-ferati')
        self.assertEqual(bot.personal_channel_name('', fallback_name='Rinesa Ahmedi'), 'primeflow-rinesa')
        self.assertLessEqual(len(bot.personal_channel_name('A' * 150)), 100)

    async def test_list_pages_have_one_button_per_task_and_keep_every_task(self):
        tasks = [{"id": str(uuid.uuid4()), "title": "x" * 500, "status": "IN_PROGRESS"} for _ in range(63)]
        ids = []
        for page in range(4):
            text, view = bot.ui.list_view(tasks, "Sot", page)
            self.assertLessEqual(len(text), 2000)
            self.assertNotIn("IN_PROGRESS", text)
            buttons = [item for item in view.children if item.custom_id.startswith("pf:open:")]
            self.assertLessEqual(len(buttons), 20)
            self.assertTrue(all(item.row < 4 for item in buttons))
            ids.extend(item.custom_id.split(":")[2] for item in buttons)
            self.assertTrue(all(len(item.custom_id) <= 100 for item in view.children))
        self.assertEqual(ids, [task["id"] for task in tasks])

    async def test_action_menu_persistent_and_modal_defaults(self):
        view = bot.task_view(str(uuid.uuid4()), "a" * 16, "TODO")
        self.assertTrue(view.is_persistent())
        menu = next(item for item in view.children if isinstance(item, discord.ui.Select))
        self.assertLessEqual(len(menu.options), 25)
        modal = bot.InstructionModal(Mock(), str(uuid.uuid4()), 5)
        self.assertEqual(modal.instruction.default, "Bëje WFE.")

    async def test_empty_bucket_and_long_multiline_content(self):
        text, view = bot.ui.list_view([], "PM")
        self.assertIsNone(view)
        self.assertIn("Nuk ke", text)
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
        with patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), patch.object(bot.settings, "DISCORD_MEETING_NOTES_ENABLED", False), patch.object(bot.settings, "DISCORD_BRIDGE_SECRET", "x" * 32), \
             patch.object(bot.settings, "PRIMEFLOW_API_BASE_URL", "http://primeflow.test"), \
             patch.object(bot.settings, "MIRA_HOST_ENABLED", False), \
             patch.object(bot.app_commands.CommandTree, "sync", new_callable=AsyncMock), \
             patch.object(bot.tasks.Loop, "start"):
            instance = bot.PrimeFlowBot()
            try:
                await instance.setup_hook()
                commands = instance.tree.get_commands(guild=discord.Object(id=123))
                self.assertEqual({command.name for command in commands}, {"lidh", "detyrat", "m2", "m3", "pyet", "push"})
                self.assertEqual(str(instance.http_bridge.base_url), "http://primeflow.test/api/discord/")
                request = instance.http_bridge.build_request("POST", "/bot/tasks", json={})
                self.assertEqual(str(request.url), "http://primeflow.test/api/discord/bot/tasks")
                self.assertEqual(request.headers["X-Primeflow-Discord-Secret"], "x" * 32)
            finally:
                await instance.close()

    async def test_ready_status_requires_membership_and_contains_no_credentials(self):
        instance = object.__new__(bot.PrimeFlowBot)
        with tempfile.TemporaryDirectory() as directory:
            module_path = Path(directory) / "discord_bot.py"
            status_path = module_path.with_name(".discord-worker-status.json")
            with patch.object(bot, "Path", return_value=module_path), patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), \
                 patch.dict(os.environ, {"APP_BUILD_SHA": "test-build"}), patch.object(bot.PrimeFlowBot, "get_guild", return_value=Mock()):
                instance.publish_ready_status()
                result = json.loads(status_path.read_text())
                self.assertEqual(result["guild_id"], "123")
                self.assertEqual(result["build"], "test-build")
                self.assertEqual(set(result), {"guild_id", "pid", "build", "connected_at"})
                instance.clear_ready_status()
                self.assertFalse(status_path.exists())
            with patch.object(bot, "Path", return_value=module_path), patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), \
                 patch.object(bot.PrimeFlowBot, "get_guild", return_value=None):
                instance.publish_ready_status()
                self.assertFalse(status_path.exists())

    async def test_privacy_is_repaired_before_returning_channel(self):
        instance = object.__new__(bot.PrimeFlowBot)
        member = Mock(spec=discord.Member, id=20)
        everyone = Mock(spec=discord.Role, id=123)
        me = Mock(spec=discord.Member, id=99)
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

    async def test_uncached_members_do_not_trigger_permission_rewrite(self):
        instance = object.__new__(bot.PrimeFlowBot)
        member = Mock(spec=discord.Member, id=20)
        everyone = Mock(spec=discord.Role, id=123)
        me = Mock(spec=discord.Member, id=99)
        guild = Mock(default_role=everyone, me=me)
        guild.get_member.return_value = None
        guild.fetch_member = AsyncMock(return_value=member)
        channel = Mock(spec=discord.TextChannel)
        channel.topic = "PrimeFlow personal workspace: 20"
        channel.overwrites = {
            everyone: discord.PermissionOverwrite(view_channel=False),
            discord.Object(id=20, type=discord.User): discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            discord.Object(id=99, type=discord.User): discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True),
        }
        channel.edit = AsyncMock(side_effect=AssertionError("Unnecessary overwrite requires extra Discord permissions"))
        guild.get_channel.return_value = channel
        with patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), patch.object(bot.PrimeFlowBot, "get_guild", return_value=guild):
            self.assertIs(await instance.private_channel(123, 10, 20), channel)
        channel.edit.assert_not_called()

    async def test_real_privacy_drift_without_manage_roles_stays_closed(self):
        instance = object.__new__(bot.PrimeFlowBot)
        member = Mock(spec=discord.Member, id=20)
        everyone = Mock(spec=discord.Role, id=123)
        me = Mock(spec=discord.Member, id=99)
        guild = Mock(default_role=everyone, me=me)
        guild.get_member.return_value = member
        channel = Mock(spec=discord.TextChannel)
        channel.topic, channel.overwrites = "PrimeFlow personal workspace: 20", {}
        channel.permissions_for.return_value = discord.Permissions.none()
        channel.edit = AsyncMock()
        guild.get_channel.return_value = channel
        with patch.object(bot.settings, "DISCORD_GUILD_ID", "123"), patch.object(bot.PrimeFlowBot, "get_guild", return_value=guild):
            with self.assertRaisesRegex(ValueError, "Manage Roles"):
                await instance.private_channel(123, 10, 20)
        channel.edit.assert_not_called()

    async def test_multiline_task_labels_are_single_line_and_keep_task_ids(self):
        tasks = [{"id": str(uuid.uuid4()), "title": "Heading\n1. [[done]]Point A[[/done]]\n2. Point B", "status": "TODO"}]
        text, view = bot.ui.list_view(tasks, "Today")
        self.assertIn("`1.` 🟣 Heading\n", text)
        self.assertNotIn("Point A", text)
        self.assertEqual(view.children[0].custom_id, f"pf:open:{tasks[0]['id']}")

    async def test_read_timeout_message_does_not_imply_a_task_was_modified(self):
        import httpx
        message = bot.PrimeFlowBot.error_message(httpx.ReadTimeout("timeout"), read_only=True)
        self.assertIn("Provo /detyrat", message)


if __name__ == "__main__":
    unittest.main()
