"""Mira Host (test): Mira leads the 1H meetings herself.

Started only with /mira mbaj-takimet. The existing silent recorder
(discord_voice_meetings.py + worker.mjs) is not touched; Mira Host is a second
Discord bot driven by discord-voice/host-worker.mjs, while this module sends the
invitations through the existing PrimeFlow bot and moves the meeting from
person to person.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from app.config import settings
from discord_voice_client import VOICE_DIR, VoiceCaptureClient

PREFIX = "/bot/mira-host"
MAX_LINE = 2_000_000
# OpenAI Realtime sessions end after 60 minutes; a 1H never needs that long.
MAX_MEETING_MINUTES = 55
CONNECT_ATTEMPTS = 3
log = logging.getLogger("primeflow.discord.mira_host")


def tz():
    return ZoneInfo(settings.APP_TIMEZONE)


def task_lines(tasks: list[dict]) -> str:
    def line(t):
        # The Albanian label, so Mira never says "IN_PROGRESS" aloud.
        parts = [t.get("spoken") or t["title"], t.get("status_label") or t["status"], t["period"]]
        if t.get("symbol"):
            parts.append("simboli " + t["symbol"])
        if t.get("deadline"):
            parts.append("DEADLINE")
        if t.get("due"):
            parts.append("afati " + t["due"])
        return " · ".join(parts)
    return "\n".join(f"{n}. {line(t)}" for n, t in enumerate(tasks, 1)) or "(asnjë)"


def turn_brief(current: dict) -> dict:
    brief = current["brief"]
    progress = brief.get("new_progress") or {}
    return {
        "person": current["name"], "initials": current["initials"],
        "detyrat_e_slotit": task_lines(brief["current"]),
        "slot_paraprak": brief.get("previous_slot"),
        "nga_sloti_paraprak_ne_proces_ose_pa_progres": task_lines(brief["previous_open"]),
        "progres_i_ri": {"done": [d.get("spoken") or d["title"] for d in progress.get("done", [])],
                          "strikes": [{"detyra": s.get("spoken") or s["title"], "pikat": [p["text"] for p in s["points"]]}
                                      for s in progress.get("strikes", [])]},
    }


class HostProcess:
    """JSON-lines bridge to host-worker.mjs; the Mira Host token goes only through stdin."""

    def __init__(self, on_message):
        self.on_message = on_message
        self.process = None
        self.reader = None

    async def start(self, **start):
        self.process = await asyncio.create_subprocess_exec(settings.DISCORD_VOICE_NODE_BINARY, str(VOICE_DIR / "host-worker.mjs"),
            cwd=str(VOICE_DIR), env=VoiceCaptureClient.child_env(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=MAX_LINE + 1)
        self.reader = asyncio.create_task(self._read())
        await self.send({"type": "start", **start})

    async def send(self, message: dict):
        if not self.process or self.process.returncode is not None:
            raise ValueError("host_process_unavailable")
        self.process.stdin.write((json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        await self.process.stdin.drain()

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                with suppress(ValueError):
                    message = json.loads(line)
                    if isinstance(message, dict):
                        await self.on_message(message)
        except Exception as exc:
            log.warning("MIRA_HOST reader failed: %s", type(exc).__name__)
        await self.on_message({"type": "process_exit"})

    async def close(self):
        if not self.process:
            return
        with suppress(Exception):
            await self.send({"type": "shutdown"})
        try:
            await asyncio.wait_for(self.process.wait(), 3)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)


class MiraHost:
    def __init__(self, bot):
        self.bot = bot
        self.session: dict | None = None
        self.task: asyncio.Task | None = None
        self.ticking = False

    # ------------------------------------------------------------ Discord helpers

    def voice_channel(self, guild):
        voice = guild.get_channel(int(settings.DISCORD_1H_VOICE_CHANNEL_ID or 0))
        if not isinstance(voice, discord.VoiceChannel):
            voice = next((c for c in guild.voice_channels if c.name.upper().startswith("1H")), None)
        return voice

    def join_url(self, guild_id, voice) -> str:
        return f"https://discord.com/channels/{guild_id}/{voice.id}" if voice else ""

    async def notify(self, target: dict, text: str):
        channel = await self.bot.private_channel(target["guild_id"], target["channel_id"], target["discord_user_id"])
        await channel.send(f"<@{target['discord_user_id']}> {text}"[:2000],
            allowed_mentions=discord.AllowedMentions(users=[discord.Object(int(target["discord_user_id"]))]))

    def in_voice(self, guild, voice, discord_user_id: str) -> bool:
        member = guild.get_member(int(discord_user_id))
        return bool(member and member.voice and voice and member.voice.channel and member.voice.channel.id == voice.id)

    # ------------------------------------------------------------ scheduler

    async def tick(self, now: datetime):
        if self.ticking:
            return
        self.ticking = True
        try:
            result = await self.bot.bridge(PREFIX + "/tick", {})
            guild = self.bot.get_guild(int(settings.DISCORD_GUILD_ID))
            voice = self.voice_channel(guild) if guild else None
            link = self.join_url(settings.DISCORD_GUILD_ID, voice)
            for job in result["jobs"]:
                try:
                    if job["kind"] == "brief":
                        await self.notify(job, job["text"])
                    elif job["kind"] == "ga_call":
                        await self.notify(job, f"📞 **1H {job['slot']}** – kyçu tani. Mira fillon me Notes dhe Done/Strikes. {link}")
                    elif job["kind"] == "ga_fallback":
                        if guild and not self.in_voice(guild, voice, job["primary_discord_user_id"]):
                            await self.notify(job, f"📞 **1H {job['slot']}** – mungon kolegia jote GA, të lutem kyçu në vend të saj. {link}")
                    elif job["kind"] == "join" and self.session is None and guild and voice:
                        talk_at = datetime.fromisoformat(job["talk_at"]) if job.get("talk_at") else None
                        self.task = asyncio.create_task(self.run(job["slot"], guild, voice, talk_at))
                except Exception as exc:
                    log.warning("MIRA_HOST job %s failed: %s", job.get("kind"), type(exc).__name__)
        finally:
            self.ticking = False

    # ------------------------------------------------------------ one meeting

    async def connect(self, session, slot: str, guild, voice) -> dict:
        """Join silently, retrying a failed Discord/OpenAI connection; returns the started session."""
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            started = await self.bot.bridge(PREFIX + "/session/start", {"slot": slot})
            session["meeting"] = started["meeting"]["id"]
            session["target"] = started.get("target_minutes") or 4
            session["attempt"], session["ready"], session["failed"] = attempt, asyncio.Event(), asyncio.Event()
            # Each attempt has its own process; events of an earlier one are ignored by on_worker.
            process = HostProcess(lambda message, number=attempt: self.on_worker(session, message, number))
            session["process"] = process
            await process.start(guild_id=str(guild.id), channel_id=str(voice.id), token=settings.MIRA_HOST_BOT_TOKEN,
                                client_secret=started["client_secret"], model=started["model"])
            waiters = [asyncio.create_task(session["ready"].wait()), asyncio.create_task(session["failed"].wait()),
                       asyncio.create_task(session["closed"].wait())]
            await asyncio.wait(waiters, timeout=70, return_when=asyncio.FIRST_COMPLETED)
            for waiter in waiters:
                waiter.cancel()
            if session["closed"].is_set():
                raise ValueError("stopped")
            if session["ready"].is_set() and not session["failed"].is_set():
                session["reason"] = "completed"
                return started
            log.warning("MIRA_HOST connect attempt %s/%s for %s failed: %s", attempt, CONNECT_ATTEMPTS, slot, session["reason"])
            session["process"] = None
            await process.close()
            await asyncio.sleep(3)
        raise ValueError("connect_failed")

    async def run(self, slot: str, guild, voice, talk_at: datetime | None = None):
        session = {"slot": slot, "guild": guild, "voice": voice, "lines": [], "ready": asyncio.Event(),
                   "failed": asyncio.Event(), "closed": asyncio.Event(), "attempt": 0, "turn_started": None,
                   "turn_nudged": False, "upcoming": None, "finished": False, "ending": False, "meeting": None,
                   "process": None, "reason": "completed"}
        self.session = session
        try:
            # Mira joins a few minutes early and stays silent, so a failed connection is retried
            # before the GA team arrives; she starts talking exactly at talk_at.
            started = await self.connect(session, slot, guild, voice)
            await self.wait_until(session, talk_at or datetime.now(tz()))
            if session["closed"].is_set():
                raise ValueError("stopped")
            await self.say(session, f"SISTEMI: Je në kanalin e 1H {slot}. Faza GA: përshëndet shkurt dhe pyet 'Notes të reja?'.")
            starts_at = datetime.fromisoformat(started["starts_at"])
            deadline = datetime.now(tz()) + timedelta(minutes=MAX_MEETING_MINUTES)
            await self.wait_until(session, starts_at)
            if not session["closed"].is_set():
                turns = (await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/staff", {}))["turns"]
                if turns:
                    await self.advance(session, None, announce=True)
                else:
                    session["ending"] = True
                    session["ending_at"] = datetime.now(tz()) + timedelta(seconds=60)
                    await self.say(session, f"SISTEMI: Ora {slot}. Askush nuk ka detyra 1H në këtë slot. Mbyll GA shkurt dhe thuaj FUNDI.")
            # Staff turns run through tool calls; this loop only watches time.
            while not session["closed"].is_set() and datetime.now(tz()) < deadline:
                await self.watch_turn(session)
                if session["ending"] and session.get("ending_at") and datetime.now(tz()) > session["ending_at"]:
                    break
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(session["closed"].wait(), 5)
                await self.flush_lines(session)
        except Exception as exc:
            if session["reason"] == "completed":
                session["reason"] = f"error:{type(exc).__name__}"
            log.warning("MIRA_HOST meeting %s failed: %s (%s)", slot, exc, session["reason"])
        finally:
            await self.finish(session)

    async def wait_until(self, session, at: datetime):
        while not session["closed"].is_set() and datetime.now(tz()) < at:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(session["closed"].wait(), min(5, max(0.2, (at - datetime.now(tz())).total_seconds())))
            await self.flush_lines(session)

    async def watch_turn(self, session):
        """Invite the next person shortly before the current one ends, and nudge a long turn once."""
        started = session.get("turn_started")
        if not started:
            return
        elapsed = (datetime.now(tz()) - started).total_seconds() / 60
        if session.get("upcoming") and elapsed >= max(1, session["target"] - 1):
            await self.invite_upcoming(session)
        if not session["turn_nudged"] and elapsed >= session["target"] * 2:
            session["turn_nudged"] = True
            await self.say(session, "SISTEMI: Koha e këtij personi ka kaluar. Mbyll shkurt dhe kalo te tjetri (end_person_turn).")

    async def invite_upcoming(self, session):
        upcoming = session.get("upcoming")
        if not upcoming or upcoming.get("invited"):
            return None
        upcoming["invited"] = True
        if upcoming.get("discord"):
            with suppress(Exception):
                await self.notify(upcoming["discord"], f"⏳ **1H {session['slot']}** – ti je i/e radhës pas pak. Kyçu tani: "
                                  f"{self.join_url(settings.DISCORD_GUILD_ID, session['voice'])}")
                await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/turns/invited", {"turn_id": upcoming["id"]})
        return upcoming["name"]

    async def advance(self, session, summary: str | None, *, announce: bool) -> dict:
        result = await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/turns/next", {"summary": summary})
        current, upcoming = result.get("current"), result.get("upcoming")
        session["upcoming"] = upcoming and {**upcoming, "invited": bool(upcoming.get("invited_at"))}
        session["turn_started"], session["turn_nudged"] = (datetime.now(tz()) if current else None), False
        if not current:
            session["ending"] = True
            session["ending_at"] = datetime.now(tz()) + timedelta(seconds=40)
            output = {"FUNDI": True, "udhezim": "Të gjithë kanë raportuar. Falënderoji shkurt dhe mbyll takimin."}
        else:
            if current.get("discord") and not self.in_voice(session["guild"], session["voice"], current["discord"]["discord_user_id"]):
                with suppress(Exception):
                    await self.notify(current["discord"], f"🎙️ **1H {session['slot']}** – radha jote tani. Kyçu: "
                                      f"{self.join_url(settings.DISCORD_GUILD_ID, session['voice'])}")
            output = {"RADHA": turn_brief(current),
                      "udhezim": f"Thirre {current['name']} me emër dhe fillo me protokollin. Në fillim pyet për slotin paraprak."}
        if announce:
            text = "SISTEMI: Ora e slotit. Mbyll fazën GA shkurt. " + json.dumps(output, ensure_ascii=False)
            await self.say(session, text)
        return output

    async def say(self, session, text: str):
        if session.get("process"):
            with suppress(Exception):
                await session["process"].send({"type": "say", "text": text[:12000]})

    # ------------------------------------------------------------ worker events

    async def on_worker(self, session, message: dict, attempt: int | None = None):
        if attempt is not None and attempt != session.get("attempt"):
            return
        kind = message.get("type")
        if kind == "ready":
            session["ready"].set()
        elif kind == "transcript":
            speaker = "Mira"
            if message.get("role") != "mira":
                member = session["guild"].get_member(int(message["speaker_id"])) if str(message.get("speaker_id") or "").isdigit() else None
                speaker = member.display_name if member else "Stafi"
            session["lines"].append({"at": datetime.now(tz()).isoformat(), "role": message.get("role"),
                                     "speaker": speaker, "text": message.get("text", "")})
            if session["ending"] and message.get("role") == "mira":
                # Mira said goodbye; leave a moment later so the last words are heard.
                session["ending_at"] = datetime.now(tz()) + timedelta(seconds=4)
        elif kind == "tool_call":
            asyncio.create_task(self.tool(session, message))
        elif kind in ("interrupted", "process_exit", "stopped"):
            if kind == "interrupted":
                session["reason"] = f"interrupted:{message.get('reason')}"[:100]
                log.warning("MIRA_HOST interrupted reason=%s close_code=%s voice_status=%s", message.get("reason"),
                            message.get("close_code"), message.get("voice_status"))
            if not session["ready"].is_set():
                session["failed"].set()  # still connecting: connect() tries again
            elif not session["closed"].is_set():
                session["closed"].set()
        elif kind == "log":
            log.info("MIRA_HOST %s", {k: v for k, v in message.items() if k != "type"})

    async def tool(self, session, message: dict):
        name, call_id = message.get("name"), message.get("call_id")
        try:
            arguments = json.loads(message.get("arguments") or "{}")
        except ValueError:
            arguments = {}
        try:
            if name == "end_person_turn":
                output = await self.advance(session, arguments.get("summary"), announce=False)
            elif name == "call_next_person":
                invited = await self.invite_upcoming(session)
                output = {"ok": True, "u_ftua": invited} if invited else {"ok": True, "shenim": "Nuk ka person tjetër ose është ftuar tashmë."}
            else:
                output = await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/tools/{name}", {"arguments": arguments})
        except Exception as exc:
            output = {"error": str(exc)[:300] if isinstance(exc, ValueError) else "Veprimi dështoi."}
        with suppress(Exception):
            await session["process"].send({"type": "tool_result", "call_id": call_id, "output": output})

    async def flush_lines(self, session):
        lines, session["lines"] = session["lines"], []
        if lines and session.get("meeting"):
            try:
                await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/transcript", {"lines": lines[:200]})
            except Exception:
                session["lines"] = lines + session["lines"]

    async def finish(self, session):
        if session["finished"]:
            return
        session["finished"] = True
        session["closed"].set()
        if session.get("process"):
            await session["process"].close()
        await self.flush_lines(session)
        if session.get("meeting"):
            with suppress(Exception):
                await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/finish", {"reason": session["reason"]})
        if self.session is session:
            self.session = None

    async def stop(self, reason: str = "stopped"):
        session = self.session
        if session and not session["closed"].is_set():
            session["reason"] = reason
            session["closed"].set()
        if self.task:
            with suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self.task), 15)

    async def preflight(self):
        process = await asyncio.create_subprocess_exec(settings.DISCORD_VOICE_NODE_BINARY, str(VOICE_DIR / "host-worker.mjs"), "--check",
            cwd=str(VOICE_DIR), env=VoiceCaptureClient.child_env(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 20)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise ValueError("Shërbimi zanor i Mira-s nuk u nis.") from None
        if process.returncode or b'"host_ready":true' not in output:
            raise ValueError("Shërbimi zanor i Mira-s nuk është gati.")


def status_text(state: dict) -> str:
    if not state.get("enabled"):
        return "Mira **nuk** po i mban takimet 1H. Nise me `/mira mbaj-takimet`."
    until = datetime.fromisoformat(state["enabled_until"]).astimezone(tz()).strftime("%H:%M")
    text = f"✅ Mira i mban takimet 1H deri në **{until}** (slotet {', '.join(state['slots'])})."
    live = state.get("live")
    if live:
        people = " → ".join(f"{p['initials']}{'✓' if p['status'] == 'DONE' else ('🎙️' if p['status'] == 'ACTIVE' else '')}"
                            for p in live["people"])
        text += f"\nTani: **1H {live['slot']}** ({live['status']}) {people}"
    return text


def register_host_commands(bot, guild):
    if not (settings.MIRA_HOST_ENABLED and settings.MIRA_HOST_BOT_TOKEN):
        return
    group = app_commands.Group(name="mira", description="Mira mban takimet 1H (test)")

    @group.command(name="mbaj-takimet", description="Mira i mban vetë takimet 1H (test)")
    @app_commands.describe(deri_ne_ore="Deri në cilën orë sot, p.sh. 12:00 (bosh = deri në fund të ditës)")
    async def start(interaction: discord.Interaction, deri_ne_ore: str | None = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await bot.mira_host.preflight()
            state = await bot.bridge(PREFIX + "/enable", {"discord_user_id": str(interaction.user.id), "until": deri_ne_ore})
            await interaction.followup.send(status_text(state), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(bot.error_message(exc), ephemeral=True)

    @group.command(name="ndalo", description="Ndalo Mira-n si mbajtëse e takimeve 1H")
    async def stop(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await bot.bridge(PREFIX + "/disable", {"discord_user_id": str(interaction.user.id)})
            await bot.mira_host.stop("stopped_by_command")
            await interaction.followup.send("⏹️ Mira nuk i mban më takimet. Regjistrimi i heshtur vazhdon si më parë.", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(bot.error_message(exc), ephemeral=True)

    @group.command(name="statusi", description="A po i mban Mira takimet 1H?")
    async def status(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            await interaction.followup.send(status_text(await bot.bridge(PREFIX + "/status", {})), ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(bot.error_message(exc), ephemeral=True)

    bot.tree.add_command(group, guild=guild)
