"""Manual family voice host. No work Mira imports, recording, or task mutations."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

import discord
from discord import app_commands

MAX_LINE = 2_000_000
ERROR = "Biseda nuk u nis ose u ndërpre. Kontrollo lejen në PrimeFlow dhe kanalin privat zanor."


class HostError(Exception):
    """Only fixed, user-safe messages may cross the command boundary."""


def family_brief(context):
    return context["instructions"] + "\nPjesëmarrësit dhe detyrat e sotme:\n" + json.dumps(
        context["participants"], ensure_ascii=False, sort_keys=True)


class HostProcess:
    """Own the Node worker; secrets travel only over stdin, never argv or env."""

    def __init__(self, worker, node, on_message):
        self.worker, self.node, self.on_message = Path(worker), node, on_message
        self.process = self.reader = None
        self._close_lock = asyncio.Lock()

    async def start(self, **payload):
        if not self.worker.is_absolute() or not self.worker.is_file():
            raise HostError(ERROR)
        child_env = {key: value for key, value in os.environ.items()
                     if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA"}}
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            self.node, str(self.worker), cwd=str(self.worker.parent), env=child_env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=MAX_LINE + 1))
        try:
            self.process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            # Cancelling subprocess creation can otherwise lose ownership of a
            # child that the OS has already launched.
            self.process = await spawning
            await self.close()
            raise
        self.reader = asyncio.create_task(self._read())
        await self.send({"type": "start", **payload})

    async def send(self, message):
        if self.process is None or self.process.returncode is not None:
            raise HostError(ERROR)
        line = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        if len(line) > MAX_LINE:
            raise HostError(ERROR)
        self.process.stdin.write(line)
        await self.process.stdin.drain()

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if isinstance(message, dict):
                    await self.on_message(message)
        except (ValueError, OSError):
            pass
        finally:
            await self.on_message({"type": "process_exit"})

    async def close(self):
        async with self._close_lock:
            if self.process is None:
                return
            if self.process.returncode is None:
                with suppress(Exception):
                    await asyncio.wait_for(self.send({"type": "shutdown"}), 1)
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError):
                        self.process.kill()
                    await self.process.wait()
            if self.reader and self.reader is not asyncio.current_task():
                self.reader.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self.reader


class KujtesaHost:
    REFRESH_SECONDS = 30
    MAX_SECONDS = 55 * 60
    CONNECT_SECONDS = 30

    def __init__(self, bot, *, worker="", node="node"):
        self.bot, self.worker, self.node = bot, worker, node
        self.session = None

    def _private(self, channel, allowed=None):
        if not isinstance(channel, discord.VoiceChannel):
            raise HostError(ERROR)
        guild, bot_id = channel.guild, self.bot.user.id
        if channel.permissions_for(guild.default_role).view_channel:
            raise HostError(ERROR)
        own_permissions = channel.permissions_for(guild.me)
        if not (own_permissions.view_channel and own_permissions.connect and own_permissions.speak):
            raise HostError(ERROR)
        for principal, overwrite in channel.overwrites.items():
            if overwrite.view_channel is not True:
                continue
            if isinstance(principal, discord.Role):
                if not (principal.managed and principal.tags and principal.tags.bot_id == bot_id):
                    raise HostError(ERROR)
            elif principal.id != bot_id and allowed is not None and str(principal.id) not in allowed:
                raise HostError(ERROR)
        # discord.py's public mapping omits uncached members. Check its raw
        # overwrite IDs too, so an offline stranger's grant cannot disappear
        # from this privacy check merely because the members intent is off.
        known = {principal.id for principal in channel.overwrites}
        for overwrite in channel._overwrites:
            if discord.Permissions(overwrite.allow).view_channel and overwrite.id not in known:
                if not (overwrite.id == bot_id or (overwrite.is_member()
                        and (allowed is None or str(overwrite.id) in allowed))):
                    raise HostError(ERROR)
        present = []
        cached_ids = {member.id for member in channel.members}
        if any(uid != bot_id and uid not in cached_ids for uid in channel.voice_states):
            # A voice state can outlive its Member cache entry. Never silently
            # omit an unidentifiable listener from the authorization payload.
            raise HostError(ERROR)
        for member in channel.members:
            if member.id == bot_id:
                continue
            if member.bot or (allowed is not None and str(member.id) not in allowed):
                raise HostError(ERROR)
            present.append(str(member.id))
        return sorted(set(present))

    def _payload(self, session, actor=None):
        return {"actor_id": str(actor or session["actor"]), "guild_id": str(session["channel"].guild.id),
                "channel_id": str(session["channel"].id),
                "present_user_ids": self._private(session["channel"], session.get("allowed"))}

    def _validate(self, session, context):
        if str(context["guild_id"]) != str(session["channel"].guild.id):
            raise HostError(ERROR)
        allowed = {str(uid) for uid in context["allowed_user_ids"]}
        if str(session["actor"]) not in allowed:
            raise HostError(ERROR)
        self._private(session["channel"], allowed)
        # grant_version is supplied by the private API and changes when the
        # authorizing administrator or family configuration changes.
        signature = (str(context["guild_id"]), tuple(sorted(allowed)), context["grant_version"])
        if session.get("signature") is not None and session["signature"] != signature:
            raise HostError(ERROR)
        session["allowed"], session["signature"] = allowed, signature

    async def start(self, interaction):
        if self.session is not None:
            raise HostError("Një bisedë është duke u nisur ose po vazhdon. Përdor /kujtesa ndalo.")
        voice = getattr(interaction.user, "voice", None)
        channel = getattr(voice, "channel", None)
        if interaction.guild is None or channel is None or channel.guild.id != interaction.guild.id:
            raise HostError(ERROR)
        if str(interaction.user.id) not in self._private(channel):
            raise HostError(ERROR)
        session = {"actor": str(interaction.user.id), "channel": channel, "closed": asyncio.Event(),
                   "ready": asyncio.Event(), "realtime": asyncio.Event(),
                   "wake": asyncio.Event(), "started": asyncio.Event(),
                   "finished": asyncio.Event(), "process": None, "live": False,
                   "deadline": asyncio.get_running_loop().time() + self.MAX_SECONDS}
        self.session = session
        session["task"] = asyncio.create_task(self._run(session))
        session["expiry"] = asyncio.get_running_loop().call_later(self.MAX_SECONDS, session["task"].cancel)
        try:
            await session["started"].wait()
        except asyncio.CancelledError:
            if self.session is session:
                await self.stop()
            raise
        if not session["live"] or session["closed"].is_set():
            raise HostError(ERROR)

    async def _run(self, session):
        try:
            context = await self.bot.api("/host/start", self._payload(session))
            self._validate(session, context)
            if session["closed"].is_set():
                return
            process = HostProcess(self.worker, self.node, lambda message: self._on_worker(session, message))
            session["process"] = process
            await process.start(guild_id=str(session["channel"].guild.id), channel_id=str(session["channel"].id),
                                token=self.bot.http.token, client_secret=context["client_secret"], model=context["model"])
            await asyncio.wait_for(session["wake"].wait(), self.CONNECT_SECONDS)
            if session["closed"].is_set() or not (session["ready"].is_set() and session["realtime"].is_set()):
                return
            # Connecting can take seconds. Recheck the grant before enabling
            # audio rather than speaking from an authorization that aged during
            # the Discord/Realtime handshake.
            context = await self.bot.api("/host/context", self._payload(session))
            self._validate(session, context)
            if session["closed"].is_set():
                return
            brief = family_brief(context)
            await process.send({"type": "say", "text": brief})
            session["live"] = True
            session["started"].set()
            while not session["closed"].is_set():
                remaining = session["deadline"] - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(session["closed"].wait(), min(self.REFRESH_SECONDS, remaining))
                except asyncio.TimeoutError:
                    if asyncio.get_running_loop().time() >= session["deadline"]:
                        break
                    refreshed = await self.bot.api("/host/context", self._payload(session))
                    self._validate(session, refreshed)
                    if session["closed"].is_set():
                        break
                    updated_brief = family_brief(refreshed)
                    if updated_brief != brief:
                        await process.send({"type": "say", "respond": False, "text":
                            "PËRDITËSIM: të dhënat më poshtë zëvendësojnë listën e mëparshme. "
                            "Përdori për pyetjet e ardhshme; mos fol tani.\n" + updated_brief})
                        brief = updated_brief
        except (Exception, asyncio.CancelledError):
            # Neither provider messages nor family task/transcript text is logged.
            pass
        finally:
            session["expiry"].cancel()
            session["stopping"] = True
            session["closed"].set()
            if session["process"]:
                with suppress(Exception):
                    await session["process"].close()
            if self.session is session:
                self.session = None
            session["started"].set()
            session["finished"].set()

    async def _on_worker(self, session, message):
        if session["closed"].is_set():
            return
        kind = message.get("type")
        if kind in {"ready", "realtime_ready"}:
            session["ready" if kind == "ready" else "realtime"].set()
            if session["ready"].is_set() and session["realtime"].is_set():
                session["wake"].set()
        elif kind in {"interrupted", "process_exit", "stopped"}:
            session["closed"].set()
            session["wake"].set()
        elif kind == "tool_call" and isinstance(message.get("call_id"), str):
            name = message.get("name")
            output = {"ok": True} if name in {"wait_for_user", "finish_meeting"} else {"error": "Veprim i palejuar."}
            await session["process"].send({"type": "tool_result", "call_id": message["call_id"], "output": output})
            if name == "finish_meeting":
                session["closed"].set()
                session["wake"].set()
        # Transcripts and worker logs are deliberately not retained or forwarded.

    async def stop(self):
        session = self.session
        if session is None:
            return
        session["closed"].set()
        session["wake"].set()
        task = session["task"]
        if task is not asyncio.current_task():
            if not session.get("stopping"):
                session["stopping"] = True
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.shield(task)
            # A task cancelled before its first instruction never enters the
            # runner's finally block; release the command and timer here too.
            if task.done() and not session["finished"].is_set():
                session["expiry"].cancel()
                if self.session is session:
                    self.session = None
                session["started"].set()
                session["finished"].set()

    async def stop_by(self, interaction):
        session = self.session
        if session is None:
            return
        try:
            if interaction.guild_id != session["channel"].guild.id:
                raise HostError(ERROR)
            context = await self.bot.api("/host/context", self._payload(session, interaction.user.id))
            self._validate(session, context)
        except Exception:
            raise HostError(ERROR) from None
        if self.session is session:
            await self.stop()

    async def on_voice_state_update(self, member, before, after):
        session = self.session
        if session is None:
            return
        channel_id = session["channel"].id
        joined = getattr(after.channel, "id", None) == channel_id
        left = getattr(before.channel, "id", None) == channel_id and not joined
        if (joined and member.id != self.bot.user.id
                and (member.bot or str(member.id) not in session.get("allowed", set()))):
            await self.stop()
        elif left and (member.id == self.bot.user.id or str(member.id) == session["actor"]):
            await self.stop()

    async def on_channel_update(self, before, after):
        session = self.session
        if session and after.id == session["channel"].id:
            session["channel"] = after
            try:
                self._private(after, session.get("allowed"))
            except HostError:
                await self.stop()


def register_commands(bot):
    group = app_commands.Group(name="kujtesa", description="Bisedë private familjare me Kujtesën")

    @group.command(name="fillo", description="Nis bisedën në kanalin tënd privat zanor")
    async def start(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await bot.host.start(interaction)
            text = "Kujtesa u lidh në kanalin privat zanor."
        except Exception:
            text = ERROR
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="ndalo", description="Ndalo bisedën private me Kujtesën")
    async def stop(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await bot.host.stop_by(interaction)
            text = "Biseda me Kujtesën u ndal."
        except Exception:
            text = ERROR
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    bot.tree.add_command(group)
