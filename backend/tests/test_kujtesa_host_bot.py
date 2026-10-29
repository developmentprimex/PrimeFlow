"""Synthetic voice/HTTP/process boundaries; never connects to Discord."""
import asyncio
import copy
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import discord
from integrations.kujtesa import primeflow_bot


class WiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_commands_are_optional_and_never_start_at_construction(self):
        disabled = primeflow_bot.KujtesaBridge("http://localhost/api", "synthetic")
        enabled = primeflow_bot.KujtesaBridge("http://localhost/api", "synthetic", host_enabled=True,
                                             host_worker=str(Path(__file__).resolve()))
        self.assertIsNone(disabled.host)
        self.assertIsNone(enabled.host.session)
        group = enabled.tree.get_command("kujtesa")
        self.assertEqual({command.name for command in group.commands}, {"fillo", "ndalo"})
        self.assertTrue(enabled.intents.voice_states)
        self.assertFalse(enabled.reminders_enabled)
        await disabled.close()
        await enabled.close()

    async def test_commands_defer_ephemeral_and_sanitize_errors(self):
        bot = primeflow_bot.KujtesaBridge("http://localhost/api", "synthetic", host_enabled=True)
        interaction = NS(response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        bot.host.start = AsyncMock(side_effect=RuntimeError("secret-token private-task"))
        await bot.tree.get_command("kujtesa").get_command("fillo").callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        sent = interaction.followup.send.call_args
        self.assertTrue(sent.kwargs["ephemeral"])
        self.assertNotIn("secret-token", sent.args[0])
        await bot.close()

    async def test_component_handler_does_not_consume_application_commands(self):
        bot = primeflow_bot.KujtesaBridge("http://localhost/api", "synthetic", host_enabled=True)
        interaction = NS(type=discord.InteractionType.application_command, response=NS(defer=AsyncMock()))
        await bot.on_interaction(interaction)
        interaction.response.defer.assert_not_awaited()
        await bot.close()


def room():
    default = Mock(spec=discord.Role)
    default.id = 1
    guild = NS(id=1, default_role=default)
    channel = Mock(spec=discord.VoiceChannel)
    channel.id, channel.guild, channel.overwrites, channel._overwrites = 55, guild, {}, []
    channel.permissions_for.side_effect = lambda principal: NS(view_channel=principal is not default,
                                                               connect=True, speak=True)
    actor = NS(id=11, bot=False, voice=NS(channel=channel))
    girl = NS(id=22, bot=False, voice=NS(channel=channel))
    channel.members = [actor, girl]
    channel.voice_states = {11: NS(), 22: NS()}
    interaction = NS(guild=guild, guild_id=1, user=actor)
    guild.me = NS(id=99)
    return channel, interaction


CONTEXT = {
    "guild_id": "1", "allowed_user_ids": ["11", "22"], "grant_version": "synthetic-v1",
    "participants": [{"person": "gane", "name": "Gane", "discord_user_id": "11", "tasks": []},
                     {"person": "girl", "name": "Girl", "discord_user_id": "22",
                      "tasks": [{"title": "Read", "status": "pending", "due_at": None}]}],
    "instructions": "Fol shqip dhe pyet me radhe.", "model": "synthetic-realtime",
    "client_secret": "synthetic-ephemeral",
}


class ProcessDouble:
    instances = []
    ready = True

    def __init__(self, worker, node, on_message):
        self.worker, self.node, self.on_message = worker, node, on_message
        self.starts, self.messages, self.closed = [], [], False
        self.sent = asyncio.Queue()
        self.instances.append(self)

    async def start(self, **payload):
        self.starts.append(payload)
        if self.ready:
            await self.on_message({"type": "ready"})
            await self.on_message({"type": "realtime_ready"})

    async def send(self, message):
        self.messages.append(message)
        self.sent.put_nowait(message)

    async def close(self):
        self.closed = True


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from integrations.kujtesa import voice_host
        self.m = voice_host
        ProcessDouble.instances = []
        ProcessDouble.ready = True
        self.process_patch = patch.object(voice_host, "HostProcess", ProcessDouble)
        self.process_patch.start()
        self.channel, self.interaction = room()
        self.calls = []

        async def api(path, body):
            self.calls.append((path, body))
            return copy.deepcopy(CONTEXT)

        self.bot = NS(user=NS(id=99), http=NS(token="synthetic-discord"), api=api)
        self.host = voice_host.KujtesaHost(self.bot, worker=str(Path(__file__).resolve()), node="node")

    async def asyncTearDown(self):
        await self.host.stop()
        self.process_patch.stop()

    async def test_start_sends_authorized_humans_and_ephemeral_credentials_only_to_worker(self):
        await self.host.start(self.interaction)
        self.assertEqual(self.calls, [(path, {"actor_id": "11", "guild_id": "1", "channel_id": "55",
                                              "present_user_ids": ["11", "22"]})
                                     for path in ("/host/start", "/host/context")])
        process = ProcessDouble.instances[0]
        self.assertEqual(process.starts, [{"guild_id": "1", "channel_id": "55", "token": "synthetic-discord",
                                          "client_secret": "synthetic-ephemeral", "model": "synthetic-realtime"}])
        self.assertEqual(process.messages[0]["type"], "say")
        self.assertIn("Read", process.messages[0]["text"])
        self.assertNotIn("client_secret", process.messages[0]["text"])

    async def test_brief_waits_for_realtime_even_when_discord_is_ready_first(self):
        ProcessDouble.ready = False
        starting = asyncio.create_task(self.host.start(self.interaction))
        while not ProcessDouble.instances:
            await asyncio.sleep(0)
        process = ProcessDouble.instances[0]
        await process.on_message({"type": "ready"})
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertFalse(process.messages)
        await process.on_message({"type": "realtime_ready"})
        await starting
        self.assertEqual(process.messages[0]["type"], "say")

    async def test_start_requires_voice_and_private_channel_before_spawning(self):
        self.interaction.user.voice = None
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.interaction.user.voice = NS(channel=self.channel)
        self.channel.permissions_for.side_effect = lambda principal: NS(view_channel=True, connect=True, speak=True)
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertFalse(ProcessDouble.instances)

    async def test_broad_role_unmapped_member_and_other_bot_access_rejected(self):
        role = Mock(spec=discord.Role)
        role.managed = False
        member = Mock(spec=discord.Member)
        member.id = 33
        for principal in (role, member):
            self.channel.overwrites = {principal: NS(view_channel=True)}
            with self.assertRaises(self.m.HostError):
                await self.host.start(self.interaction)
        self.channel.overwrites = {}
        self.channel.members.append(NS(id=44, bot=True))
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertFalse(ProcessDouble.instances)

    async def test_own_managed_bot_role_is_allowed_but_unknown_human_is_not(self):
        role = Mock(spec=discord.Role)
        role.managed, role.tags = True, NS(bot_id=99)
        self.channel.overwrites = {role: NS(view_channel=True)}
        self.channel.members.append(NS(id=99, bot=True))
        await self.host.start(self.interaction)
        self.assertEqual(self.calls[0][1]["present_user_ids"], ["11", "22"])
        await self.host.stop()
        self.channel.members.append(NS(id=33, bot=False))
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertEqual(len(ProcessDouble.instances), 1)

    async def test_server_denial_does_not_join(self):
        self.bot.api = AsyncMock(side_effect=RuntimeError("synthetic-key"))
        with self.assertRaises(self.m.HostError) as error:
            await self.host.start(self.interaction)
        self.assertNotIn("synthetic-key", str(error.exception))
        self.assertFalse(ProcessDouble.instances)

    async def test_revocation_while_connecting_prevents_first_family_audio(self):
        self.bot.api = AsyncMock(side_effect=[copy.deepcopy(CONTEXT), RuntimeError("revoked")])
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertTrue(ProcessDouble.instances[0].closed)
        self.assertFalse(ProcessDouble.instances[0].messages)

    async def test_duplicate_start_never_spawns_a_second_worker(self):
        await self.host.start(self.interaction)
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertEqual(len(ProcessDouble.instances), 1)

    async def test_stop_while_authorizing_prevents_late_start(self):
        entered = asyncio.Event()
        async def slow_api(path, body):
            entered.set()
            await asyncio.Event().wait()
        self.bot.api = slow_api
        starting = asyncio.create_task(self.host.start(self.interaction))
        await entered.wait()
        await self.host.stop()
        with self.assertRaises(self.m.HostError):
            await starting
        self.assertFalse(ProcessDouble.instances)
        self.assertIsNone(self.host.session)

    async def test_stop_before_runner_starts_releases_waiting_command_and_session(self):
        starting = asyncio.create_task(self.host.start(self.interaction))
        await asyncio.sleep(0)
        await self.host.stop()
        with self.assertRaises(self.m.HostError):
            await asyncio.wait_for(starting, .2)
        self.assertIsNone(self.host.session)
        self.assertFalse(ProcessDouble.instances)

    async def test_uncached_member_permission_grant_is_rejected(self):
        self.channel._overwrites = [NS(id=33, allow=discord.Permissions(view_channel=True).value,
                                      deny=0, is_member=lambda: True)]
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertFalse(ProcessDouble.instances)
        self.assertEqual(len(self.calls), 1)

    async def test_uncached_voice_listener_is_not_hidden_by_members_list(self):
        self.channel.voice_states[33] = NS()
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertFalse(ProcessDouble.instances)

    async def test_uncached_mapped_member_grant_can_be_validated_by_server(self):
        self.channel._overwrites = [NS(id=23, allow=discord.Permissions(view_channel=True).value,
                                      deny=0, is_member=lambda: True)]
        self.bot.api = AsyncMock(return_value={**CONTEXT, "allowed_user_ids": ["11", "22", "23"]})
        await self.host.start(self.interaction)
        self.assertEqual(len(ProcessDouble.instances), 1)

    async def test_hard_deadline_cancels_a_stalled_context_refresh(self):
        self.host.MAX_SECONDS, self.host.REFRESH_SECONDS = .04, .01
        await self.host.start(self.interaction)
        async def stalled(path, body):
            await asyncio.Event().wait()
        self.bot.api = stalled
        await asyncio.wait_for(self.host.session["finished"].wait(), .3)
        self.assertTrue(ProcessDouble.instances[0].closed)

    async def test_concurrent_stop_does_not_cancel_child_cleanup(self):
        await self.host.start(self.interaction)
        process = ProcessDouble.instances[0]
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_close():
            entered.set()
            await release.wait()
            process.closed = True
        process.close = slow_close
        first = asyncio.create_task(self.host.stop())
        await entered.wait()
        second = asyncio.create_task(self.host.stop())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)
        self.assertTrue(process.closed)

    async def test_stop_during_ready_wait_closes_child(self):
        ProcessDouble.ready = False
        starting = asyncio.create_task(self.host.start(self.interaction))
        while not ProcessDouble.instances:
            await asyncio.sleep(0)
        await self.host.stop()
        with self.assertRaises(self.m.HostError):
            await starting
        self.assertTrue(ProcessDouble.instances[0].closed)

    async def test_unknown_voice_join_immediately_closes_worker(self):
        await self.host.start(self.interaction)
        member = NS(id=33, bot=False)
        await self.host.on_voice_state_update(member, NS(channel=None), NS(channel=self.channel))
        self.assertTrue(ProcessDouble.instances[0].closed)
        self.assertIsNone(self.host.session)

    async def test_initiating_admin_departure_stops_immediately(self):
        await self.host.start(self.interaction)
        await self.host.on_voice_state_update(self.interaction.user, NS(channel=self.channel), NS(channel=None))
        self.assertTrue(ProcessDouble.instances[0].closed)

    async def test_channel_privacy_change_closes_worker_immediately(self):
        await self.host.start(self.interaction)
        self.channel.permissions_for.side_effect = lambda principal: NS(view_channel=True, connect=True, speak=True)
        await self.host.on_channel_update(self.channel, self.channel)
        self.assertTrue(ProcessDouble.instances[0].closed)

    async def test_process_exit_and_connect_timeout_close_worker(self):
        await self.host.start(self.interaction)
        finished = self.host.session["finished"]
        await ProcessDouble.instances[0].on_message({"type": "process_exit"})
        await asyncio.wait_for(finished.wait(), 1)
        self.assertTrue(ProcessDouble.instances[0].closed)
        ProcessDouble.ready, self.host.CONNECT_SECONDS = False, .01
        with self.assertRaises(self.m.HostError):
            await self.host.start(self.interaction)
        self.assertTrue(ProcessDouble.instances[1].closed)

    async def test_refresh_rechecks_admin_and_stops_on_grant_change(self):
        self.host.REFRESH_SECONDS = .01
        await self.host.start(self.interaction)
        changed = {**CONTEXT, "grant_version": "synthetic-v2"}
        self.bot.api = AsyncMock(return_value=changed)
        await asyncio.wait_for(self.host.session["finished"].wait(), 1)
        self.bot.api.assert_awaited_once_with("/host/context", {"actor_id": "11", "guild_id": "1", "channel_id": "55",
                                                               "present_user_ids": ["11", "22"]})
        self.assertTrue(ProcessDouble.instances[0].closed)

    async def test_changed_tasks_and_new_family_member_refresh_silently(self):
        self.host.REFRESH_SECONDS = .01
        initial = copy.deepcopy(CONTEXT)
        initial["allowed_user_ids"].append("23")
        self.bot.api = AsyncMock(return_value=initial)
        await self.host.start(self.interaction)
        process = ProcessDouble.instances[0]
        await process.sent.get()
        changed = copy.deepcopy(initial)
        changed["instructions"] = "Udhëzimet e përditësuara."
        changed["participants"][1]["tasks"][0]["status"] = "done"
        changed["participants"].append({"person": "sister", "name": "Sister", "discord_user_id": "23",
                                         "tasks": [{"title": "Brush", "status": "pending", "due_at": None}]})
        sister = NS(id=23, bot=False, voice=NS(channel=self.channel))
        self.channel.members.append(sister)
        self.channel.voice_states[23] = NS()
        self.bot.api = AsyncMock(return_value=changed)
        await self.host.on_voice_state_update(sister, NS(channel=None), NS(channel=self.channel))
        update = await asyncio.wait_for(process.sent.get(), 1)
        self.assertEqual(update["type"], "say")
        self.assertIs(update["respond"], False)
        self.assertIn("PËRDITËSIM", update["text"])
        self.assertIn('"status": "done"', update["text"])
        self.assertIn('"name": "Sister"', update["text"])
        self.assertIn("Brush", update["text"])
        self.assertIn("Udhëzimet e përditësuara.", update["text"])
        self.bot.api.assert_awaited_once_with("/host/context", {"actor_id": "11", "guild_id": "1", "channel_id": "55",
                                                               "present_user_ids": ["11", "22", "23"]})
        polled_again = asyncio.Event()
        async def same_context(path, body):
            self.assertEqual(path, "/host/context")
            polled_again.set()
            return copy.deepcopy(changed)
        self.bot.api = same_context
        await asyncio.wait_for(polled_again.wait(), 1)
        self.assertEqual(len(process.messages), 2)

    async def test_departed_family_member_is_removed_from_next_context_update(self):
        self.host.REFRESH_SECONDS = .01
        await self.host.start(self.interaction)
        process = ProcessDouble.instances[0]
        await process.sent.get()
        departed = self.channel.members.pop()
        self.channel.voice_states.pop(22)
        changed = copy.deepcopy(CONTEXT)
        changed["participants"] = changed["participants"][:1]
        self.bot.api = AsyncMock(return_value=changed)
        await self.host.on_voice_state_update(departed, NS(channel=self.channel), NS(channel=None))
        update = await asyncio.wait_for(process.sent.get(), 1)
        self.assertIs(update["respond"], False)
        self.assertIn("zëvendësojnë", update["text"])
        self.assertNotIn('"discord_user_id": "22"', update["text"])
        self.assertNotIn("Read", update["text"])
        self.bot.api.assert_awaited_once_with("/host/context", {"actor_id": "11", "guild_id": "1", "channel_id": "55",
                                                               "present_user_ids": ["11"]})

    async def test_unchanged_polls_do_not_send_duplicate_briefs(self):
        self.host.REFRESH_SECONDS = .01
        await self.host.start(self.interaction)
        polled = asyncio.Event()
        polls = 0
        async def context(path, body):
            nonlocal polls
            self.assertEqual(path, "/host/context")
            polls += 1
            if polls == 2:
                polled.set()
            return copy.deepcopy(CONTEXT)
        self.bot.api = context
        await asyncio.wait_for(polled.wait(), 1)
        self.assertEqual(len(ProcessDouble.instances[0].messages), 1)

    async def test_refresh_denial_and_timeout_close_worker(self):
        self.host.REFRESH_SECONDS = .01
        await self.host.start(self.interaction)
        self.bot.api = AsyncMock(side_effect=RuntimeError("revoked"))
        await asyncio.wait_for(self.host.session["finished"].wait(), 1)
        self.assertTrue(ProcessDouble.instances[0].closed)
        self.bot.api = AsyncMock(return_value=copy.deepcopy(CONTEXT))
        self.host.MAX_SECONDS = .02
        await self.host.start(self.interaction)
        await asyncio.wait_for(self.host.session["finished"].wait(), 1)
        self.assertTrue(ProcessDouble.instances[1].closed)

    async def test_interrupt_and_finish_close_but_task_mutations_are_never_forwarded(self):
        await self.host.start(self.interaction)
        process = ProcessDouble.instances[0]
        await process.on_message({"type": "tool_call", "name": "complete_task", "call_id": "c1", "arguments": "{}"})
        self.assertEqual(len(self.calls), 2)
        self.assertIn("error", process.messages[-1]["output"])
        await process.on_message({"type": "tool_call", "name": "wait_for_user", "call_id": "c2"})
        self.assertEqual(process.messages[-1], {"type": "tool_result", "call_id": "c2", "output": {"ok": True}})
        finished = self.host.session["finished"]
        await process.on_message({"type": "tool_call", "name": "finish_meeting", "call_id": "c3"})
        await asyncio.wait_for(finished.wait(), 1)
        self.assertTrue(process.closed)
        await self.host.start(self.interaction)
        process = ProcessDouble.instances[1]
        finished = self.host.session["finished"]
        await process.on_message({"type": "interrupted", "reason": "synthetic-private-value"})
        await asyncio.wait_for(finished.wait(), 1)
        self.assertTrue(process.closed)

    async def test_stop_command_requires_server_authorization_for_its_actor(self):
        await self.host.start(self.interaction)
        other = NS(user=NS(id=22), guild_id=1)
        self.bot.api = AsyncMock(side_effect=RuntimeError("not-admin"))
        with self.assertRaises(self.m.HostError):
            await self.host.stop_by(other)
        self.assertFalse(ProcessDouble.instances[0].closed)
        self.bot.api = AsyncMock(return_value=copy.deepcopy(CONTEXT))
        await self.host.stop_by(self.interaction)
        self.assertEqual(self.bot.api.call_args.args[1]["actor_id"], "11")
        self.assertTrue(ProcessDouble.instances[0].closed)


class Child:
    def __init__(self):
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.exit = asyncio.Event()
        self.messages = []
        self.killed = False
        self.stdin = NS(write=self.write, drain=AsyncMock())

    def write(self, line):
        message = json.loads(line)
        self.messages.append(message)
        if message["type"] == "shutdown":
            self.returncode = 0
            self.exit.set()
            self.stdout.feed_eof()

    async def wait(self):
        await self.exit.wait()
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -1
        self.exit.set()
        self.stdout.feed_eof()


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_receives_token_via_stdin_and_has_no_inherited_credentials(self):
        from integrations.kujtesa import voice_host as m
        child = Child()
        worker = str(Path(__file__).resolve())
        process = m.HostProcess(worker, "node", AsyncMock())
        with patch.dict(os.environ, {"DISCORD_TOKEN": "synthetic-discord", "OPENAI_API_KEY": "synthetic-openai"}), \
                patch.object(m.asyncio, "create_subprocess_exec", AsyncMock(return_value=child)) as spawn:
            await process.start(guild_id="1", channel_id="55", token="synthetic-discord",
                                client_secret="synthetic-ephemeral", model="synthetic-realtime")
            self.assertEqual(spawn.call_args.args, ("node", worker))
            self.assertNotIn("DISCORD_TOKEN", spawn.call_args.kwargs["env"])
            self.assertNotIn("OPENAI_API_KEY", spawn.call_args.kwargs["env"])
            self.assertEqual(child.messages[0]["token"], "synthetic-discord")
            await process.close()
        self.assertEqual(child.messages[-1], {"type": "shutdown"})
        self.assertIsNotNone(child.returncode)

    async def test_cancellation_during_spawn_waits_for_child_and_closes_it(self):
        from integrations.kujtesa import voice_host as m
        child, entered, release = Child(), asyncio.Event(), asyncio.Event()
        async def spawn(*args, **kwargs):
            entered.set()
            await release.wait()
            return child
        process = m.HostProcess(str(Path(__file__).resolve()), "node", AsyncMock())
        with patch.object(m.asyncio, "create_subprocess_exec", spawn):
            starting = asyncio.create_task(process.start(guild_id="1", channel_id="55", token="synthetic",
                                                        client_secret="synthetic", model="synthetic"))
            await entered.wait()
            starting.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await starting
        self.assertIsNotNone(child.returncode)
