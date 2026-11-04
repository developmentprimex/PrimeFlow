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
import time as monotonic_time
import uuid
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from app.config import settings
from app.services.mira_host_speech import speech_text
from discord_voice_client import VOICE_DIR, VoiceCaptureClient

PREFIX = "/bot/mira-host"
MAX_LINE = 2_000_000
# OpenAI Realtime sessions end after 60 minutes; a 1H never needs that long.
MAX_MEETING_MINUTES = 55
CONNECT_ATTEMPTS = 3
LOOKUP_TIMEOUT_SECONDS = 8
WRITE_TIMEOUT_SECONDS = 12
WORKER_SHUTDOWN_SECONDS = 3
LOOKUP_TOOLS = {"list_ga_tasks", "list_new_px_notes", "list_new_done_and_strikes", "get_person_brief", "find_user", "search_knowledge"}
# Notes and progress are read before the slot; staff starts at its official time.
SLOTS = ("10:00", "11:00", "11:50", "14:20", "16:00")
log = logging.getLogger("primeflow.discord.mira_host")
RECOVERY_DIR = Path(__file__).with_name(".mira-host-recovery")


def tz():
    return ZoneInfo(settings.APP_TIMEZONE)


def task_lines(tasks: list[dict]) -> str:
    def line(t):
        # The Albanian label, so Mira never says "IN_PROGRESS" aloud; the colour decides her question.
        parts = [t.get("read_aloud") or t.get("spoken") or t["title"], t.get("status_label") or t["status"], t["period"]]
        if t.get("color"):
            parts.append("ngjyra " + t["color"])
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
    strikes = {t["task_id"]: [p["text"] for p in t["points"]]
               for t in progress.get("strikes", []) if t.get("task_id")}
    done = {t["task_id"] for t in progress.get("done", []) if t.get("task_id")}
    percentages = brief.get("progress_percentages") or {}
    followup_tasks = brief.get("continuation_check_tasks", [*brief.get("current", []), *brief.get("previous_open", [])])
    all_todo = bool(followup_tasks) and all(task["status"] == "TODO" for task in followup_tasks)
    discussion, seen = [], set()
    for group, label in (("current", "AKTUAL"), ("previous_open", "PARAPRAK"), ("blocked", "BLLOK")):
        for task in brief.get(group, []):
            task_id = task.get("task_id")
            key = task_id or task["title"]
            if key in seen:
                continue
            seen.add(key)
            percentage = percentages.get(task_id)
            points = strikes.get(task_id, [])
            discussion.append({
                "task_id": task_id, "grupi": label, "detyra": task.get("read_aloud") or task.get("spoken") or task["title"],
                "status": task.get("status_label") or task["status"], "kryer": task["status"] == "DONE",
                "progres_perqindje": percentage, "strike_ne_interval": points,
                "ka_progres_te_regjistruar": bool(points or task_id in done or task["status"] == "DONE"
                                                 or (percentage is not None and percentage > 0)),
                "diskutuar": (brief.get("discussion") or {}).get(task_id, {}),
                "pershkrimi": task.get("description"), "komenti_simbolit": task.get("symbol_comment"),
                "simboli": task.get("symbol"), "afati": task.get("due"), "deadline": bool(task.get("deadline")),
            })
    result = {
        "turn_id": current.get("id"),
        "person": current["name"], "initials": current["initials"],
        "initials_read_aloud": speech_text(current["initials"], [current["initials"]]),
        "plan_discutimi": discussion, "progres_nga": brief.get("progress_since"),
        "aktual_dhe_paraprak_todo": all_todo,
        "pyetja_vazhdimit": "Me çka ke vazhduar?" if all_todo else None,
        "detyrat_e_slotit": task_lines(brief["current"]),
        "te_gjitha_kryer": bool(discussion) and all(task["kryer"] for task in discussion),
        "slotet_paraprake": brief.get("previous_slot"),
        "nga_slotet_paraprake_ne_proces_ose_pa_progres": task_lines(brief["previous_open"]),
        "progres_i_ri": {"done": [d.get("spoken") or d["title"] for d in progress.get("done", [])],
                          "strikes": [{"detyra": s.get("spoken") or s["title"], "pikat": [p["text"] for p in s["points"]]}
                                      for s in progress.get("strikes", [])]},
    }
    if brief.get("blocked"):
        result["bllok"] = task_lines(brief["blocked"])
    return result


class HostProcess:
    """JSON-lines bridge to host-worker.mjs; the Mira Host token goes only through stdin."""

    def __init__(self, on_message):
        self.on_message = on_message
        self.process = None
        self.reader = None
        self.lifecycle_lock = asyncio.Lock()
        self.closed = False

    async def start(self, **start):
        async with self.lifecycle_lock:
            if self.closed:
                raise ValueError("host_process_closed")
            await self._start()
        # A blocked initial write must not prevent close() from killing the child.
        await self.send({"type": "start", **start})

    async def _start(self):
        self.process = await asyncio.create_subprocess_exec(settings.DISCORD_VOICE_NODE_BINARY, str(VOICE_DIR / "host-worker.mjs"),
            cwd=str(VOICE_DIR), env=VoiceCaptureClient.child_env(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=MAX_LINE + 1)
        self.reader = asyncio.create_task(self._read())

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
        async with self.lifecycle_lock:
            self.closed = True
            await self._close()

    async def _close(self):
        if not self.process:
            return
        async def shutdown():
            with suppress(Exception):
                await self.send({"type": "shutdown"})
            await self.process.wait()
        try:
            await asyncio.wait_for(shutdown(), WORKER_SHUTDOWN_SECONDS)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
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
        self.starting = False
        self.pending_test_mode = False
        self.start_generation = 0
        self.startup_task = None
        self.preempt_lock = asyncio.Lock()
        self.retiring_tasks = set()
        self.retiring_meetings = set()
        self.recovery_task = None
        self.notification_receipts = set()

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

    def running(self) -> bool:
        return self.preempt_lock.locked() or self.starting or self.session is not None or bool(self.task and not self.task.done())

    async def preempt_test(self):
        """Release the voice worker; test-only history uploads may finish in the background."""
        async with self.preempt_lock:
            if self.session and not self.session.get("test_mode"):
                return
            active = self.session if self.session and self.session.get("test_mode") else None
            if not active and not self.pending_test_mode:
                return
            old_task, startup = self.task, self.startup_task
            self.start_generation += 1
            if active:
                active["reason"] = "test_preempted_for_real_meeting"
                active["closed"].set()
            if startup and startup is not asyncio.current_task() and not startup.done():
                startup.cancel()
            if old_task and not old_task.done():
                self.retiring_tasks.add(old_task)
                meeting_id = active.get("meeting") if active else None
                if meeting_id:
                    self.retiring_meetings.add(meeting_id)
                def retired(task):
                    self.retiring_tasks.discard(task)
                    self.retiring_meetings.discard(meeting_id)
                    if not task.cancelled():
                        with suppress(Exception):
                            task.exception()
                old_task.add_done_callback(retired)
            if active and active.get("process"):
                await active["process"].close()
            if self.session is active:
                self.session = None
            if self.task is old_task:
                self.task = None
            if self.startup_task is startup:
                self.startup_task = None
                self.starting = False
                self.pending_test_mode = False

    async def join_now(self, guild, slot: str, discord_user_id: str, *, command_context: dict | None = None, test_mode: bool = False):
        """One explicit meeting; do not enable the daily automatic schedule."""
        if not guild or str(guild.id) != str(settings.DISCORD_GUILD_ID):
            raise ValueError("Përdore komandën në serverin Discord të Primex.")
        if slot not in SLOTS:
            raise ValueError("Zgjidh një slot 1H nga lista.")
        voice = self.voice_channel(guild)
        if not voice:
            raise ValueError("Kanali zanor 1H nuk u gjet në server.")
        if self.running() and not test_mode and (self.pending_test_mode or (self.session or {}).get("test_mode")):
            await asyncio.wait_for(self.bot.bridge(PREFIX + "/authorize", {"discord_user_id": discord_user_id,
                **(command_context or {})}), timeout=LOOKUP_TIMEOUT_SECONDS)
            await self.preempt_test()
        if self.running():
            raise ValueError("Mira është duke u kyçur ose po e mban një takim. Përdor /mira ndalo fillimisht.")
        self.starting = True
        self.pending_test_mode = test_mode
        self.start_generation += 1
        generation = self.start_generation
        owner = self.startup_task = asyncio.current_task()
        try:
            await self.preflight()
            if generation != self.start_generation:
                raise ValueError("Kyçja e Mira-s u anulua me /mira ndalo.")
            # Authorize and prepare before confirming anything to the caller.
            prepared = await self.bot.bridge(PREFIX + "/session/start", {"slot": slot, "discord_user_id": discord_user_id,
                **({"test_mode": True} if test_mode else {}), **(command_context or {})})
            if generation != self.start_generation:
                await self.bot.bridge(PREFIX + f"/meetings/{prepared['meeting']['id']}/finish", {"reason": "stopped_by_command"})
                raise ValueError("Kyçja e Mira-s u anulua me /mira ndalo.")
            ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(self.run(slot, guild, voice, manual_by=discord_user_id,
                                                     prepared=prepared, ready=ready, start_generation=generation,
                                                     command_context=command_context, **({"test_mode": True} if test_mode else {})))
        except asyncio.CancelledError:
            if test_mode and generation != self.start_generation:
                raise ValueError("Testi u ndërpre sepse takimi real me stafin ka përparësi.") from None
            raise
        finally:
            if self.startup_task is owner:
                self.starting = False
                if not self.task or self.task.done():
                    self.pending_test_mode = False
                    self.startup_task = None
        try:
            await ready
        except asyncio.CancelledError:
            if test_mode and generation != self.start_generation:
                raise ValueError("Testi u ndërpre sepse takimi real me stafin ka përparësi.") from None
            raise
        finally:
            if self.startup_task is owner:
                self.startup_task = None
            if generation == self.start_generation:
                self.pending_test_mode = False

    # ------------------------------------------------------------ scheduler

    async def tick(self, now: datetime):
        if self.ticking:
            return
        self.ticking = True
        try:
            if not self.recovery_task or self.recovery_task.done():
                self.recovery_task = asyncio.create_task(self.recover_transcripts())
                def recovered(task):
                    if not task.cancelled() and task.exception():
                        log.warning("MIRA_HOST transcript recovery failed: %s", type(task.exception()).__name__)
                self.recovery_task.add_done_callback(recovered)
            result = await self.bot.bridge(PREFIX + "/tick", {})
            if self.session and self.session.get("meeting") in result.get("stop_meetings", []):
                await self.stop("stopped_by_command")
            guild = self.bot.get_guild(int(settings.DISCORD_GUILD_ID))
            voice = self.voice_channel(guild) if guild else None
            link = self.join_url(settings.DISCORD_GUILD_ID, voice)
            for job in result["jobs"]:
                try:
                    key = job.get("notification_key")
                    if key and key in self.notification_receipts:
                        await self.bot.bridge(PREFIX + "/notifications/result", {"key": key, "delivered": True})
                        continue
                    if job["kind"] == "brief":
                        await self.notify(job, job["text"])
                    elif job["kind"] == "ga_call":
                        await self.notify(job, f"📞 **1H {job['slot']}** – kyçu tani. Mira përmend Notes e reja, pastaj Done/Strikes nga raporti i slotit dhe vazhdon me stafin. {link}")
                    elif job["kind"] == "ga_fallback":
                        if guild and not self.in_voice(guild, voice, job["primary_discord_user_id"]):
                            await self.notify(job, f"📞 **1H {job['slot']}** – mungon kolegia jote GA, të lutem kyçu në vend të saj. {link}")
                    elif job["kind"] == "join" and guild and voice:
                        if self.pending_test_mode or (self.session or {}).get("test_mode"):
                            await self.preempt_test()
                        if not self.running():
                            talk_at = datetime.fromisoformat(job["talk_at"]) if job.get("talk_at") else None
                            self.task = asyncio.create_task(self.run(job["slot"], guild, voice, talk_at))
                    if key:
                        self.notification_receipts.add(key)
                        await self.bot.bridge(PREFIX + "/notifications/result", {"key": key, "delivered": True})
                except Exception as exc:
                    log.warning("MIRA_HOST job %s failed: %s", job.get("kind"), type(exc).__name__)
                    if job.get("notification_key") and job["notification_key"] not in self.notification_receipts:
                        with suppress(Exception):
                            await self.bot.bridge(PREFIX + "/notifications/result", {"key": job["notification_key"], "delivered": False})
        finally:
            self.ticking = False

    # ------------------------------------------------------------ one meeting

    async def connect(self, session, slot: str, guild, voice, prepared: dict | None = None) -> dict:
        """Join silently, retrying a failed Discord/OpenAI connection; returns the started session."""
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            if session["closed"].is_set():
                raise ValueError("stopped")
            payload = {"slot": slot}
            if session.get("test_mode"):
                payload["test_mode"] = True
                if session.get("meeting"):
                    payload["test_meeting_id"] = session["meeting"]
            if session.get("manual_by"):
                payload["discord_user_id"] = session["manual_by"]
                payload.update(session.get('command_context') or {})
            started = prepared if prepared is not None and attempt == 1 else await self.bot.bridge(PREFIX + "/session/start", payload)
            session["meeting"] = started["meeting"]["id"]
            session["join_attempt"] = started.get("join_attempt")
            session["test_mode"] = bool(started["meeting"].get("is_test", session.get("test_mode", False)))
            # A stop may arrive while the API prepares the session. Preserve its ID
            # for cleanup, but never start a voice worker after that cancellation.
            if session["closed"].is_set():
                raise ValueError("stopped")
            session["target"] = started.get("target_minutes") or 4
            session["attempt"], session["ready"], session["failed"] = attempt, asyncio.Event(), asyncio.Event()
            # Each attempt has its own process; events of an earlier one are ignored by on_worker.
            process = HostProcess(lambda message, number=attempt: self.on_worker(session, message, number))
            session["process"] = process
            await process.start(guild_id=str(guild.id), channel_id=str(voice.id), token=settings.MIRA_HOST_BOT_TOKEN,
                                client_secret=started["client_secret"], model=started["model"], toolsets=started.get("toolsets", {}),
                                instructions_by_phase=started.get("instructions_by_phase", {}))
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
            await process.close()
            if session.get("process") is process:
                session["process"] = None
            await asyncio.sleep(3)
        raise ValueError("connect_failed")

    async def run(self, slot: str, guild, voice, talk_at: datetime | None = None, *, manual_by: str | None = None,
                  prepared: dict | None = None, ready: asyncio.Future | None = None, start_generation: int | None = None,
                  command_context: dict | None = None, test_mode: bool = False):
        session = {"slot": slot, "guild": guild, "voice": voice, "lines": [], "ready": asyncio.Event(),
                   "failed": asyncio.Event(), "closed": asyncio.Event(), "attempt": 0, "turn_started": None,
                   "turn_nudged": False, "upcoming": None, "finished": False, "ending": False, "meeting": None,
                   "process": None, "reason": "completed", "ga_done": asyncio.Event(), "staff_started": False,
                   "starts_at": None, "pm_reviewed": False, "pm_pending": False, "manual_by": manual_by,
                   "ga_checks": {}, "ga_results": {},
                   "command_context": command_context, "test_mode": test_mode}
        if start_generation is None or start_generation == self.start_generation:
            self.session = session
            self.pending_test_mode = False
        try:
            if prepared:
                session["meeting"] = prepared["meeting"]["id"]
            if start_generation is not None and start_generation != self.start_generation:
                session["reason"] = "stopped_by_command"
                return
            # Mira joins a few minutes early and stays silent, so a failed connection is retried
            # before the GA team arrives; she starts talking exactly at talk_at.
            started = await self.connect(session, slot, guild, voice, prepared=prepared)
            starts_at = session["starts_at"] = datetime.fromisoformat(started["starts_at"])
            if ready is not None and not ready.done():
                ready.set_result(None)
            await self.wait_until(session, talk_at or datetime.now(tz()))
            if session["closed"].is_set():
                raise ValueError("stopped")
            await self.say(session, f"SISTEMI: Je në kanalin e 1H {slot}. Përshëndet shkurt dhe fillo menjëherë me list_new_px_notes. Pastaj Strike dhe Done nga raporti i këtij sloti, edhe para fillimit zyrtar; pa pyetje për aprovim. Detyrat e stafit dhe kontrolli kush mungon fillojnë vetëm në starts_at sipas sistemit.")
            deadline = datetime.now(tz()) + timedelta(minutes=MAX_MEETING_MINUTES)
            # Do not classify staff joining at the official time as absent during the early opening.
            # The clock, rather than a model tool call or unfinished opening, controls the handoff.
            await self.wait_until(session, starts_at)
            if not session["closed"].is_set() and not session["staff_started"]:
                for attempt in range(CONNECT_ATTEMPTS):
                    try:
                        await self.start_staff(session, announce=True)
                        break
                    except (asyncio.TimeoutError, ValueError):
                        if attempt == CONNECT_ATTEMPTS - 1:
                            raise
                        log.warning("MIRA_HOST staff initialization retry=%s", attempt + 1)
                        await self.wait_until(session, datetime.now(tz()) + timedelta(seconds=1))
                        if session["closed"].is_set():
                            break
            # Staff turns run through tool calls; this loop only watches time.
            while not session["closed"].is_set() and datetime.now(tz()) < deadline:
                try:
                    await self.watch_turn(session)
                    session["watch_failures"] = 0
                except (asyncio.TimeoutError, ValueError) as exc:
                    if isinstance(exc, ValueError) and not str(exc).startswith(("Radha ka ndryshuar", "Radha PM ka ndryshuar",
                            "Kalimi nuk u konfirmua", "Kalimi PM nuk u konfirmua")):
                        raise
                    if isinstance(exc, ValueError) and str(exc).startswith(("Radha ka ndryshuar", "Radha PM ka ndryshuar")):
                        log.info("MIRA_HOST watcher handoff superseded")
                    else:
                        session["watch_failures"] = session.get("watch_failures", 0) + 1
                        if session["watch_failures"] >= CONNECT_ATTEMPTS:
                            raise
                        log.warning("MIRA_HOST watcher transition deferred attempt=%s", session["watch_failures"])
                if session["ending"] and session.get("ending_at") and datetime.now(tz()) > session["ending_at"]:
                    break
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(session["closed"].wait(), 5)
                self.schedule_upload(session)
            if not session["closed"].is_set() and not session["ending"]:
                session["reason"] = "timeout"
        except Exception as exc:
            if session["reason"] == "completed":
                session["reason"] = f"error:{type(exc).__name__}"
            log.warning("MIRA_HOST meeting %s failed: %s (%s)", slot, exc, session["reason"])
        finally:
            if ready is not None and not ready.done():
                ready.set_exception(ValueError("Mira Host nuk u lidh në 1H. Kontrollo lidhjen dhe lejet e botit."))
            await self.finish(session)

    async def wait_until(self, session, at: datetime, *, until: asyncio.Event | None = None):
        """Wait for `at`, or less when the meeting closes or `until` is set (checked every second)."""
        while not session["closed"].is_set() and datetime.now(tz()) < at and not (until and until.is_set()):
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(session["closed"].wait(),
                                       min(1 if until else 5, max(0.001, (at - datetime.now(tz())).total_seconds())))
            self.schedule_upload(session)

    def schedule_upload(self, session):
        """One bounded upload job; presence checks and deadlines never await it."""
        upload = session.get("timed_upload")
        if session["closed"].is_set() or (upload and not upload.done()):
            return
        async def flush():
            try:
                await asyncio.wait_for(self.flush_lines(session), WRITE_TIMEOUT_SECONDS)
            except Exception as exc:
                self.persist_transcript(session)
                log.warning("MIRA_HOST timed upload deferred error=%s", type(exc).__name__)
        session["timed_upload"] = asyncio.create_task(flush())

    async def start_staff(self, session, *, announce: bool) -> dict:
        async with session.setdefault("staff_lock", asyncio.Lock()):
            if not session.get("test_mode") and session.get("starts_at") and datetime.now(tz()) < session["starts_at"]:
                return {"prit": True, "udhezim": "Hyrja përfundoi. Prit në heshtje fillimin zyrtar; mos kontrollo mungesat dhe mos thirr stafin ende."}
            if session.get("staff_started"):
                current = session.get("current_turn")
                return {"RADHA": turn_brief(current)} if current else {"prit": True}
            return await self._start_staff(session, announce=announce)

    async def _start_staff(self, session, *, announce: bool) -> dict:
        """Freeze the reporting order and hand Mira the first person (or the end, when nobody has 1H tasks)."""
        turns = (await asyncio.wait_for(
            self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/staff", {}),
            timeout=LOOKUP_TIMEOUT_SECONDS))["turns"]
        session["turns"] = turns
        if turns or session["slot"] == "11:50":
            try:
                if session.get("staff_start_uncertain"):
                    snapshot = await asyncio.wait_for(
                        self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/turns/current", {}), LOOKUP_TIMEOUT_SECONDS)
                    if snapshot.get("current") or not snapshot.get("upcoming"):
                        output = await self.present_turn(session, snapshot, announce=announce)
                    else:
                        session["current_turn"] = None
                        output = await self.advance(session, None, announce=announce)
                else:
                    output = await self.advance(session, None, announce=announce)
            except Exception:
                session["staff_start_uncertain"] = True
                raise
            session["staff_started"] = True
            session.pop("staff_start_uncertain", None)
            return output
        session["staff_started"] = True
        session["ending"] = True
        session["ending_at"] = datetime.now(tz()) + timedelta(seconds=60)
        output = {"FUNDI": True, "udhezim": "Askush nuk ka detyra 1H në këtë slot. Falënderoji me një fjali dhe mbyll."}
        if session.get("process"):
            await session["process"].send({"type": "configure", "phase": "ENDING", "turn_id": None, "speaker_id": None})
        if announce:
            await self.say(session, "SISTEMI: " + json.dumps(output, ensure_ascii=False))
        return output

    async def watch_turn(self, session):
        """Invite the next person shortly before the current one ends, and nudge a long turn once."""
        if session.get("pm_pending") and not session.get("ending"):
            async with session.setdefault("transition_lock", asyncio.Lock()):
                if session.get("pm_pending"):
                    await self._advance_pm(session, None, announce=True, outcome="DONE")
            return
        if session.get("deferred") and not (session.get("current_turn") or session.get("pm_current")) and not session.get("ending"):
            self.invite_deferred(session)
            available = self.available_people(session)
            if any(t.get("user_id") in available for t in session["deferred"]):
                await self.advance(session, None, announce=True)
            elif (datetime.now(tz()) - session["missing_since"]).total_seconds() >= settings.MIRA_HOST_MISSING_STAFF_GRACE_SECONDS:
                session["reason"], session["ending"] = "missing_staff", True
                session["ending_at"] = datetime.now(tz()) + timedelta(seconds=15)
                await self.say(session, "SISTEMI: Personat e mbetur mungojnë. Mbyll shkurt; mos thuaj se kanë raportuar.")
            return
        current = session.get("current_turn") or session.get("pm_current") or {}
        target = current.get("discord")
        if not session.get("test_mode") and target and not self.in_voice(session["guild"], session["voice"], target["discord_user_id"]):
            await self.advance(session, None, announce=True, outcome="DEFERRED", expected_turn_id=current["id"])
            return
        else:
            session.pop("missing_since", None)
        started = session.get("turn_started")
        if not started:
            return
        failed_at = (session.get("audio_failures") or {}).get((target or {}).get("discord_user_id"))
        if failed_at:
            await self.warn_audio(session, current)
            if (datetime.now(tz()) - max(failed_at, started)).total_seconds() >= 30:
                await self.advance(session, "Raportimi u ndërpre nga problem teknik i audios; kërkon sqarim pas takimit.",
                    announce=True, outcome="TIMEOUT", expected_turn_id=current["id"])
            return
        elapsed = (datetime.now(tz()) - started).total_seconds() / 60
        minutes = min(session["target"], 2) if session.get("pm_current") else session["target"]
        if session.get("upcoming") and elapsed >= max(1, session["target"] - 1):
            if not session["upcoming"].get("invited"):
                self.background_notification(session, lambda upcoming=session["upcoming"]: self.invite_upcoming(session, upcoming))
        if elapsed >= minutes + 0.5 and current.get("id"):
            await self.advance(session, "Koha përfundoi; çështjet e hapura kërkojnë sqarim pas takimit.",
                               announce=True, outcome="TIMEOUT", expected_turn_id=current["id"])
            return
        if not session["turn_nudged"] and elapsed >= max(0.25, minutes - 0.25):
            session["turn_nudged"] = True
            await self.say(session, "SISTEMI: Mbeten 15 sekonda për këtë person. Pyet vetëm çështjen kryesore të hapur; "
                           "çështjet e gjata lëri për pas takimit. Pastaj thirr end_person_turn me turn_id aktual.")

    async def warn_audio(self, session, current):
        speaker_id = (current.get("discord") or {}).get("discord_user_id")
        key = (current.get("id"), speaker_id)
        warned = session.setdefault("audio_warned", set())
        if not speaker_id or key in warned:
            return
        warned.add(key)
        await self.say(session, "SISTEMI: Ka problem teknik me marrjen e zërit të personit aktual. Kërko shkurt të rilidhet mikrofoni; mos e quaj mungesë raportimi.")

    def background_notification(self, session, operation):
        if session["closed"].is_set() or session.get("test_mode"):
            return
        async def run():
            if session["closed"].is_set():
                return
            try:
                await asyncio.wait_for(operation(), timeout=LOOKUP_TIMEOUT_SECONDS)
            except Exception as exc:
                log.warning("MIRA_HOST notification deferred error=%s", type(exc).__name__)
        tasks = session.setdefault("notification_tasks", set())
        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def invite_deferred(self, session):
        invited = session.setdefault("deferred_invited", set())
        for turn in session.get("deferred", []):
            if not turn.get("discord") or turn["id"] in invited:
                continue
            invited.add(turn["id"])
            async def send(target=turn):
                delivered = False
                try:
                    await self.notify(target["discord"], f"🎙️ **1H {session['slot']}** – po të presim për raportim. Kyçu: "
                                      f"{self.join_url(settings.DISCORD_GUILD_ID, session['voice'])}")
                    delivered = True
                finally:
                    if not delivered:
                        invited.discard(target["id"])
            self.background_notification(session, send)

    async def invite_upcoming(self, session, upcoming=None):
        if session.get("test_mode"):
            return None
        upcoming = upcoming or session.get("upcoming")
        if not upcoming or upcoming.get("invited"):
            return None
        upcoming["invited"] = True
        if upcoming.get("discord"):
            sent = False
            try:
                await self.notify(upcoming["discord"], f"⏳ **1H {session['slot']}** – ti je i/e radhës pas pak. Kyçu tani: "
                                  f"{self.join_url(settings.DISCORD_GUILD_ID, session['voice'])}")
                sent = True
                await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/turns/invited", {"turn_id": upcoming["id"]})
            finally:
                upcoming["invited"] = sent
        return upcoming["name"]

    def available_people(self, session):
        turns = session.get("pm_turns", []) if session.get("pm_reviewed") else session.get("turns", [])
        return [t["user_id"] for t in turns if t.get("discord") and
                self.in_voice(session["guild"], session["voice"], t["discord"]["discord_user_id"])]

    async def advance(self, session, summary: str | None, *, announce: bool, outcome: str = "DONE", expected_turn_id: str | None = None) -> dict:
        async with session.setdefault("transition_lock", asyncio.Lock()):
            active_id = (session.get("current_turn") or session.get("pm_current") or {}).get("id")
            if expected_turn_id is not None and expected_turn_id != active_id:
                raise ValueError("Radha ka ndryshuar; mos e përfundo personin e ri.")
            return await self._advance(session, summary, announce=announce, outcome=outcome)

    async def _advance(self, session, summary: str | None, *, announce: bool, outcome: str) -> dict:
        if session.get("pm_reviewed") or session.get("pm_pending"):
            return await self._advance_pm(session, summary, announce=announce, outcome=outcome)
        expected = (session.get("current_turn") or {}).get("id")
        payload = {"summary": summary, "expected_turn_id": expected, "outcome": outcome}
        if "turns" in session and not session.get("test_mode"):
            # An unlinked identity cannot be verified as absent. Keep that turn;
            # only known Discord identities outside this channel are deferred.
            payload["available_user_ids"] = self.available_people(session) + [
                turn["user_id"] for turn in session["turns"] if not turn.get("discord")]
        if session.get("pm_reviewed") and not expected and not session.get("deferred"):
            result = {"current": None}
        else:
            try:
                result = await asyncio.wait_for(
                    self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/turns/next", payload),
                    timeout=LOOKUP_TIMEOUT_SECONDS)
            except (asyncio.TimeoutError, ValueError) as exc:
                if isinstance(exc, ValueError) and not str(exc).startswith("Radha ka ndryshuar"):
                    raise
                # The server may have committed before the reply was lost. Read its state;
                # never replay a transition and risk consuming the next person.
                result = await asyncio.wait_for(
                    self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/turns/current", {}),
                    timeout=LOOKUP_TIMEOUT_SECONDS)
                same_active = expected is not None and (result.get("current") or {}).get("id") == expected
                if same_active or (not result.get("current") and result.get("upcoming")):
                    raise ValueError("Kalimi nuk u konfirmua; radha aktuale mbetet e njëjtë. Mos e shëno si të përfunduar.") from None
                result["ended"] = next((turn for turn in result.get("turns", []) if turn["id"] == expected), None)
        return await self.present_turn(session, result, announce=announce)

    async def present_turn(self, session, result, *, announce):
        """Adopt a confirmed server state without advancing another person."""
        current, upcoming = result.get("current"), result.get("upcoming")
        absent = list(result.get("skipped", []))
        previous_deferred = {turn["id"] for turn in session.get("deferred", [])}
        absent_ids = {turn["id"] for turn in absent}
        for turn in result.get("deferred", []):
            if turn["id"] not in previous_deferred and turn["id"] not in absent_ids:
                absent.append(turn)
                absent_ids.add(turn["id"])
        if (result.get("ended") or {}).get("status") == "DEFERRED":
            if result["ended"]["id"] not in absent_ids:
                absent.append(result["ended"])
        if (result.get("ended") or {}).get("status") == "TIMEOUT":
            session.setdefault("incomplete_turns", []).append(result["ended"].get("id"))
        session["current_turn"], session["deferred"] = current, result.get("deferred", [])
        session["upcoming"] = upcoming and {**upcoming, "invited": bool(upcoming.get("invited_at"))}
        session["turn_started"], session["turn_nudged"] = (datetime.now(tz()) if current else None), False
        if not current and session["deferred"]:
            session.setdefault("missing_since", datetime.now(tz()))
            self.invite_deferred(session)
            output = {"prit": True, "mungojne": [t.get("name") for t in session["deferred"]],
                      "udhezim": "Prit personat që mungojnë; mos i shëno si të raportuar."}
        elif not current and ("pm_review" in result or session.get("pm_pending")) and not session.get("pm_reviewed"):
            session["pm_pending"] = True
            return await self._advance_pm(session, None, announce=announce, outcome="DONE")
        elif not current:
            session["ending"] = True
            session["ending_at"] = datetime.now(tz()) + timedelta(seconds=40)
            output = {"FUNDI": True, "udhezim": (
                "Raportimi përfundoi; disa çështje mbetën për sqarim pas takimit. Mbyll me një fjali."
                if session.get("incomplete_turns") else "Të gjithë kanë raportuar. Falënderoji shkurt dhe mbyll takimin.")}
        else:
            session.pop("missing_since", None)
            if current.get("discord") and not self.in_voice(session["guild"], session["voice"], current["discord"]["discord_user_id"]):
                self.background_notification(session, lambda: self.notify(current["discord"],
                    f"🎙️ **1H {session['slot']}** – radha jote tani. Kyçu: "
                    f"{self.join_url(settings.DISCORD_GUILD_ID, session['voice'])}"))
            brief = turn_brief(current)
            first_open = next((task for task in brief["plan_discutimi"] if not task["kryer"]), None)
            group = first_open["grupi"] if first_open else "AKTUAL"
            opening = (f"{current['name']}: të gjitha detyrat e slotit aktual dhe atij paraprak janë To Do. "
                       "Nëse personi s'e ka sqaruar ende çfarë ka punuar, pyet shkurt 'Me çka ke vazhduar?' vetëm një herë për personin. "
                       "Mungesa e përditësimit nuk provon se s'ka punuar. Pastaj sqaro detyrat sipas plan_discutimi. "
                       if brief["aktual_dhe_paraprak_todo"] else
                       f"{current['name']}: hyr direkt te detyra e parë {group} në plan_discutimi. ")
            output = {"RADHA": brief,
                      "udhezim": opening +
                                 "Pyet shkurt vetëm çka mungon për progresin, vazhdimin ose përfundimin; "
                                 "pastaj trajto PARAPRAK dhe BLLOK. Mos përsërit përgjigjet apo hyrjet."}
        if absent:
            output["mungojne"] = [turn["name"] for turn in absent]
            missing = "; ".join(f"{turn['name']} nuk është në kanalin zanor" for turn in absent)
            output["udhezim"] = f"Thuaj shkurt: '{missing}.' Mos prit; " + output["udhezim"]
        phase = "ENDING" if session.get("ending") else "PM_REVIEW" if session.get("pm_reviewed") else "STAFF_PHASE"
        if session.get("process"):
            await session["process"].send({"type": "configure", "phase": phase,
                "turn_id": (current or {}).get("id"),
                "speaker_id": session.get("manual_by") if session.get("test_mode") else
                    ((current or {}).get("discord") or {}).get("discord_user_id")})
        if announce:
            await self.say(session, "SISTEMI: Vazhdo sipas radhës aktuale. " + json.dumps(output, ensure_ascii=False))
        return output

    async def _advance_pm(self, session, summary, *, announce, outcome):
        expected = (session.get("pm_current") or {}).get("id")
        payload = {"expected_turn_id": expected, "outcome": outcome, "summary": summary}
        members = getattr(session["voice"], "members", None)
        if members is not None and not session.get("test_mode"):
            payload["available_discord_ids"] = [str(member.id) for member in members]
        try:
            result = await asyncio.wait_for(self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/pm/next", payload), LOOKUP_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, ValueError) as exc:
            if isinstance(exc, ValueError) and not str(exc).startswith("Radha PM ka ndryshuar"):
                raise
            result = await asyncio.wait_for(self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/pm/current", {}), LOOKUP_TIMEOUT_SECONDS)
            if (expected and (result.get("current") or {}).get("id") == expected) or (
                    not expected and not result.get("current") and not result.get("initialized")):
                raise ValueError("Kalimi PM nuk u konfirmua; radha mbetet e njëjtë.") from None
        if not result.get("current") and any(turn.get("status") == "WAITING" for turn in result.get("turns", [])):
            raise ValueError("Kalimi PM nuk u konfirmua; ende ka persona në pritje.")
        session["pm_reviewed"], session["pm_pending"] = True, False
        current = session["pm_current"] = result.get("current")
        session["pm_turns"], session["deferred"] = result.get("turns", []), result.get("deferred", [])
        session["turn_started"], session["turn_nudged"] = (datetime.now(tz()) if current else None), False
        if (result.get("ended") or {}).get("status") == "TIMEOUT":
            session.setdefault("incomplete_turns", []).append(result["ended"]["id"])
        if current:
            session.pop("missing_since", None)
            output = {"PM_RISHIKIMI": [current], "turn_id": current["id"],
                "udhezim": "Pyet vetëm personin PM aktual për vazhdimin ose shtyrjet. Ruaj record_pm_review dhe pastaj end_person_turn me këtë turn_id."}
        elif session["deferred"]:
            session.setdefault("missing_since", datetime.now(tz()))
            self.invite_deferred(session)
            output = {"prit": True, "udhezim": "Personat e mbetur PM mungojnë; prit kthimin e tyre ose udhëzimin e sistemit."}
        else:
            session["ending"], session["ending_at"] = True, datetime.now(tz()) + timedelta(seconds=40)
            output = {"FUNDI": True, "udhezim": "Mbyll shkurt. Mos i quaj radhët me timeout ose probleme teknike të raportuara."}
        await session["process"].send({"type": "configure", "phase": "ENDING" if session.get("ending") else "PM_REVIEW",
            "turn_id": (current or {}).get("id"), "speaker_id": session.get("manual_by") if session.get("test_mode") else
                ((current or {}).get("discord") or {}).get("discord_user_id")})
        if announce:
            await self.say(session, "SISTEMI: " + json.dumps(output, ensure_ascii=False))
        return output

    async def say(self, session, text: str):
        if session.get("process"):
            with suppress(Exception):
                # A handoff contains JSON; slicing it loses tasks and can cut a string
                # in half. The worker already validates the complete IPC frame size.
                await session["process"].send({"type": "say", "text": text})

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
            try:
                spoken_at = datetime.fromisoformat(message.get("started_at") or "")
                if spoken_at.tzinfo is None:
                    raise ValueError("missing_timezone")
            except (ValueError, TypeError):
                spoken_at = datetime.now(tz())
            session["lines"].append({"id": str(uuid.uuid4()), "at": spoken_at.isoformat(), "role": message.get("role"),
                                     "speech_id": message.get("speech_id"), "turn_id": message.get("turn_id"),
                                     "started_at": message.get("started_at"), "ended_at": message.get("ended_at"),
                                     "speaker": speaker, "text": message.get("text", "")})
            self.persist_transcript(session)
            if session["ending"] and message.get("role") == "mira":
                # Mira said goodbye; leave a moment later so the last words are heard.
                session["ending_at"] = datetime.now(tz()) + timedelta(seconds=4)
        elif kind == "tool_call":
            asyncio.create_task(self.tool(session, message))
        elif kind == "metric":
            if message.get("kind") == "generated_audio" and isinstance(message.get("duration_ms"), (int, float)):
                self.add_metric(session, "generated_audio", message["duration_ms"])
        elif kind == "progress_played":
            session.setdefault("progress_acks", set()).add(message.get("token"))
            self.persist_transcript(session)
            pending = session.setdefault("pending_progress", set())
            pending.discard(message.get("token"))
            session.setdefault("ga_checks", {})["list_new_done_and_strikes"] = "PENDING" if pending else "DONE"
            if not pending and not session.get("ending") and not session["closed"].is_set():
                instruction = "Vazhdo me RADHA aktuale, pa e përsëritur progresin." if session.get("staff_started") else \
                              "Njoftimi i progresit u dëgjua i plotë. Thirr end_ga_phase dhe ndiq rezultatin."
                await self.say(session, "SISTEMI: " + instruction)
        elif kind == "note_played":
            session.setdefault("notes_acks", set()).add(message.get("token"))
            self.persist_transcript(session)
            session.setdefault("ga_checks", {})["list_new_px_notes"] = "DONE"
        elif kind == "announcement_deferred":
            token = message.get("token")
            session.setdefault("announcement_deferrals", set()).add(token)
            self.persist_transcript(session)
            stage = "list_new_px_notes" if message.get("kind") == "note" else "list_new_done_and_strikes"
            pending = session.setdefault("pending_progress", set())
            pending.discard(token)
            session.setdefault("ga_checks", {})[stage] = "PENDING" if pending and stage.endswith("strikes") else "DEFERRED"
        elif kind == "audio_health":
            failures = session.setdefault("audio_failures", {})
            speaker_id = message.get("speaker_id")
            if message.get("status") == "failed":
                failures.setdefault(speaker_id, datetime.now(tz()))
                current = session.get("current_turn") or session.get("pm_current") or {}
                if (current.get("discord") or {}).get("discord_user_id") == speaker_id:
                    await self.warn_audio(session, current)
            else:
                since = failures.pop(speaker_id, None)
                session["audio_warned"] = {key for key in session.get("audio_warned", set()) if key[1] != speaker_id}
                current = session.get("current_turn") or session.get("pm_current") or {}
                if since and session.get("turn_started") and (current.get("discord") or {}).get("discord_user_id") == speaker_id:
                    session["turn_started"] += datetime.now(tz()) - max(since, session["turn_started"])
        elif kind == "proposal_played":
            session.setdefault("proposal_acks", {})[message.get("token")] = message.get("played_at")
        elif kind in ("interrupted", "process_exit", "stopped"):
            if kind == "interrupted":
                session["reason"] = f"interrupted:{message.get('reason')}"[:100]
                log.warning("MIRA_HOST interrupted reason=%s close_code=%s voice_status=%s", message.get("reason"),
                            message.get("close_code"), message.get("voice_status"))
            if not session["ready"].is_set():
                session["failed"].set()  # still connecting: connect() tries again
            elif not session["closed"].is_set():
                if session["reason"] == "completed":
                    session["reason"] = "interrupted:process_exit"
                session["closed"].set()
        elif kind == "log":
            log.info("MIRA_HOST %s", {k: v for k, v in message.items() if k != "type"})

    async def tool(self, session, message: dict):
        async with session.setdefault("tool_lock", asyncio.Lock()):
            call_id = message.get("call_id")
            results = session.setdefault("tool_results", {})
            effects = session.setdefault("speech_effects", {})
            effect_key = None
            if message.get("speech_id") and message.get("name") in {"save_px_note", "add_meeting_note", "record_task_discussion", "record_pm_review"}:
                try:
                    effect_key = (message["speech_id"], message["name"],
                                  json.dumps(json.loads(message.get("arguments") or "{}"), sort_keys=True, ensure_ascii=False))
                except (ValueError, TypeError):
                    pass
            if call_id in results:
                output = results[call_id]
            elif effect_key is not None and effect_key in effects:
                output = effects[effect_key]
                results[call_id] = output
            elif session["closed"].is_set() or session.get("finished"):
                output = {"error": "Takimi është mbyllur."}
            else:
                started = monotonic_time.monotonic()
                output = await self._tool(session, message)
                self.add_metric(session, "tool", (monotonic_time.monotonic() - started) * 1000, message.get("name"))
                results[call_id] = output
                if effect_key is not None and (output.get("success") or output.get("ok") or output.get("result_unknown")):
                    effects[effect_key] = output
            with suppress(Exception):
                await session["process"].send({"type": "tool_result", "call_id": call_id, "output": output})

    async def _tool(self, session, message: dict):
        name, call_id = message.get("name"), message.get("call_id")
        lookup_turn = (session.get("current_turn") or {}).get("id")
        try:
            arguments = json.loads(message.get("arguments") or "{}")
        except ValueError:
            arguments = {}
        try:
            if name == "end_person_turn":
                expected = (session.get("current_turn") or session.get("pm_current") or {}).get("id")
                if not expected or arguments.get("turn_id") != expected:
                    raise ValueError("Radha ka ndryshuar; përdor turn_id nga RADHA aktuale.")
                output = await self.advance(session, arguments.get("summary"), announce=False, expected_turn_id=expected)
            elif name == "end_ga_phase":
                if "ga_checks" in session and not session.get("staff_started"):
                    needed = next((step for step in ("list_new_px_notes", "list_new_done_and_strikes")
                        if session["ga_checks"].get(step) not in ("DONE", "DEFERRED")), None)
                    if needed:
                        return {"next_step": needed, "udhezim": f"Faza GA ende nuk përfundoi. Vazhdo me {needed}; mos kërko aprovim. Nëse leximi po luhet, prit përfundimin e tij."}
                session["ga_done"].set()
                if session["staff_started"]:
                    output = {"ok": True}
                elif session.get("starts_at") and datetime.now(tz()) >= session["starts_at"]:
                    output = await self.start_staff(session, announce=False)
                else:
                    output = {"prit": True, "udhezim": "Hyrja përfundoi. Prit në heshtje fillimin zyrtar; mos kontrollo mungesat dhe mos thirr stafin ende."}
            elif name == "call_next_person":
                upcoming = session.get("upcoming")
                if upcoming and not upcoming.get("invited"):
                    self.background_notification(session, lambda: self.invite_upcoming(session, upcoming))
                    output = {"ok": True, "njoftim_ne_dergim": upcoming["name"]}
                else:
                    output = {"ok": True, "shenim": "Nuk ka person tjetër ose është ftuar tashmë."}
            else:
                if session.get("staff_started") and name in {"list_ga_tasks", "list_new_px_notes", "list_new_done_and_strikes"}:
                    return {"deferred": True, "udhezim": "Hyrja përfundoi; vazhdo vetëm me RADHA aktuale, pa rilexuar notes ose progresin."}
                if name == "list_new_done_and_strikes" and "ga_checks" in session and session["ga_checks"].get("list_new_px_notes") not in ("DONE", "DEFERRED"):
                    return {"next_step":"list_new_px_notes", "udhezim":"Fillimisht përmend notes e reja. Pastaj lexo progresin e raportit të këtij sloti, pa kërkuar aprovim."}
                if name in session.get("ga_results", {}):
                    completed = session.get("ga_checks", {}).get(name) in ("DONE", "DEFERRED")
                    steps = ("list_ga_tasks", "list_new_px_notes", "list_new_done_and_strikes", "end_ga_phase")
                    return {"already_completed": completed, "pending_playback": not completed,
                            "next_step": steps[steps.index(name)+1] if completed else None,
                            "udhezim": "Mos e përsërit leximin. Vazhdo me next_step pas audios; pa pyetje për aprovim."}
                if name == "create_task_from_note":
                    await self.flush_proposal_acks(session)
                source = {key: message.get(key) for key in ("speaker_id", "speech_id", "speech_text", "speech_started_at")}
                output = await asyncio.wait_for(
                    self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/tools/{name}", {"arguments": arguments, **source}),
                    timeout=LOOKUP_TIMEOUT_SECONDS if name in LOOKUP_TOOLS else WRITE_TIMEOUT_SECONDS)
                if session.get("staff_started") and name in {"list_ga_tasks", "list_new_px_notes", "list_new_done_and_strikes"}:
                    tokens = [p["token"] for p in output.get("announcements", [])]
                    tokens += [output[key] for key in ("notes_token", "progress_token") if output.get(key)]
                    session.setdefault("announcement_deferrals", set()).update(tokens)
                    self.persist_transcript(session)
                    return {"deferred": True, "udhezim": "Hyrja përfundoi; vazhdo vetëm me RADHA aktuale."}
                if name == "get_person_brief" and not output.get("error") and not session.get("pm_reviewed"):
                    current = session.get("current_turn") or {}
                    if current.get("id") != lookup_turn:
                        return {"stale_turn": True, "udhezim": "Radha ndryshoi gjatë leximit. Ndiq vetëm RADHA aktuale."}
                    if output.get("user_id") and output["user_id"] == current.get("user_id"):
                        current["brief"] = output
                        output = {"RADHA": turn_brief(current), "udhezim": "Përdor gjendjen e rifreskuar të personit aktual; mos përsërit pyetje të sqaruara."}
                if name == "record_task_discussion" and output.get("success"):
                    current = session.get("current_turn") or {}
                    facts = output.get("discussion") or {}
                    if current.get("id") == lookup_turn and facts.get("task_id"):
                        current.setdefault("brief", {}).setdefault("discussion", {})[facts["task_id"]] = facts
                if name in ("list_ga_tasks", "list_new_px_notes", "list_new_done_and_strikes") and "ga_checks" in session:
                    pending = bool(output.get("read_aloud"))
                    session["ga_checks"][name] = "DEFERRED" if output.get("error") else "PENDING" if pending else "DONE"
                    session.setdefault("ga_results", {})[name] = output
                    if name == "list_new_done_and_strikes":
                        session["pending_progress"] = {part["token"] for part in output.get("announcements", [])} or (
                            {output["progress_token"]} if pending and output.get("progress_token") else set())
        except asyncio.TimeoutError:
            lookup = name in LOOKUP_TOOLS
            log.warning("MIRA_HOST tool_timeout tool=%s", name)
            output = {"error": "Lidhja me PrimeFlow u vonua. Mos prit në heshtje; vazhdo me të dhënat që janë të konfirmuara.",
                      "retry_safe": lookup, "result_unknown": not lookup,
                      "udhezim": "Kjo nuk është përgjigje bosh. Për shkrime rezultati është i panjohur; mos i përsërit automatikisht."}
        except Exception as exc:
            output = {"error": str(exc)[:300] if isinstance(exc, ValueError) else "Veprimi dështoi."}
        if output.get("error") and name in ("list_ga_tasks", "list_new_px_notes", "list_new_done_and_strikes") and "ga_checks" in session:
            session["ga_checks"][name] = "DEFERRED"
        return output

    def add_metric(self, session, kind, duration_ms, tool=None):
        if 0 <= duration_ms <= 180000:
            session.setdefault("metrics", []).append({"id": str(uuid.uuid4()), "kind": kind,
                "duration_ms": round(duration_ms, 1), "tool": tool})

    async def flush_lines(self, session):
        async with session.setdefault("flush_lock", asyncio.Lock()):
            if not session.get("meeting"):
                return
            self.persist_transcript(session)
            await self.flush_proposal_acks(session)
            for bucket, route in (("notes_acks", "notes/ack"), ("announcement_deferrals", "announcements/defer")):
                for token in list(session.get(bucket, set())):
                    try:
                        await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/{route}", {"token": token})
                        session[bucket].discard(token)
                    except Exception:
                        pass
            for token in list(session.get("progress_acks", set())):
                try:
                    await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/progress/ack", {"token": token})
                    session["progress_acks"].discard(token)
                except Exception:
                    pass  # Unacknowledged batches remain eligible in the next meeting.
            lines, session["lines"] = session["lines"], []
            metrics, session["metrics"] = session.get("metrics", []), []
            session["uploading_lines"] = lines
            session["uploading_metrics"] = metrics
            while lines or metrics:
                try:
                    payload = {"lines": lines[:200]}
                    if metrics:
                        payload["metrics"] = metrics[:200]
                    await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/transcript", payload)
                except (Exception, asyncio.CancelledError) as exc:
                    session["lines"] = lines + session["lines"]
                    session["metrics"] = metrics + session["metrics"]
                    session["uploading_lines"] = []
                    session["uploading_metrics"] = []
                    self.persist_transcript(session)
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    return
                lines = lines[200:]
                metrics = metrics[200:]
                session["uploading_lines"] = lines
                session["uploading_metrics"] = metrics
                self.persist_transcript(session)
            self.persist_transcript(session)

    def persist_transcript(self, session):
        try:
            meeting_id = str(uuid.UUID(session.get("meeting") or ""))
        except ValueError:
            return
        try:
            RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
            target = RECOVERY_DIR / (meeting_id + ".json")
            temporary = target.with_suffix(".tmp")
            record = {"meeting": meeting_id, "lines": [*session.get("uploading_lines", []), *session.get("lines", [])],
                      "metrics": [*session.get("uploading_metrics", []), *session.get("metrics", [])],
                      "acknowledgements": {bucket: list(session.get(bucket, set())) for bucket in
                          ("notes_acks", "progress_acks", "announcement_deferrals")},
                      "finish_reason": session.get("reason") if session.get("finished") else None}
            if session.get("join_attempt") is not None:
                record["join_attempt"] = session["join_attempt"]
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            log.error("MIRA_HOST transcript recovery file could not be saved meeting=%s", meeting_id)

    async def recover_transcripts(self):
        if not RECOVERY_DIR.exists():
            return
        for path in list(RECOVERY_DIR.glob("*.json"))[:20]:
            try:
                meeting_id = str(uuid.UUID(path.stem))
                if meeting_id in self.retiring_meetings or (self.session and self.session.get("meeting") == meeting_id):
                    continue
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("meeting") != meeting_id:
                    continue
                lines = record.get("lines") or []
                metrics = record.get("metrics") or []
                while lines or metrics:
                    await self.bot.bridge(PREFIX + f"/meetings/{meeting_id}/transcript", {"lines": lines[:200], "metrics": metrics[:200]})
                    lines = lines[200:]
                    metrics = metrics[200:]
                acks = record.get("acknowledgements") or {}
                for bucket, route in (("notes_acks", "notes/ack"), ("progress_acks", "progress/ack"), ("announcement_deferrals", "announcements/defer")):
                    for token in acks.get(bucket, []):
                        await self.bot.bridge(PREFIX + f"/meetings/{meeting_id}/{route}", {"token": token})
                await self.bot.bridge(PREFIX + f"/meetings/{meeting_id}/finish",
                    {"reason": record.get("finish_reason") or "interrupted:process_exit",
                     **({"expected_join_attempt": record["join_attempt"]} if record.get("join_attempt") is not None else {})})
                path.unlink()
            except Exception as exc:
                log.warning("MIRA_HOST transcript recovery deferred file=%s error=%s", path.name, type(exc).__name__)

    async def flush_proposal_acks(self, session):
        for token, played_at in list(session.get("proposal_acks", {}).items()):
            try:
                await self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/proposal/ack", {"token": token, "played_at": played_at})
                session["proposal_acks"].pop(token, None)
            except Exception:
                pass  # Creation stays blocked until the presentation is acknowledged.

    async def finish(self, session):
        if session["finished"]:
            return
        session["finished"] = True
        session["closed"].set()
        self.persist_transcript(session)
        notifications = list(session.get("notification_tasks", set()))
        for task in notifications:
            task.cancel()
        if notifications:
            await asyncio.gather(*notifications, return_exceptions=True)
        if session.get("process"):
            await session["process"].close()
        if session.get("timed_upload"):
            session["timed_upload"].cancel()
            await asyncio.gather(session["timed_upload"], return_exceptions=True)
        try:
            await asyncio.wait_for(self.flush_lines(session), WRITE_TIMEOUT_SECONDS)
        except Exception as exc:
            self.persist_transcript(session)
            log.warning("MIRA_HOST final upload deferred error=%s", type(exc).__name__)
        if session.get("meeting"):
            try:
                await asyncio.wait_for(self.bot.bridge(PREFIX + f"/meetings/{session['meeting']}/finish",
                    {"reason": session["reason"], **({"expected_join_attempt": session["join_attempt"]}
                     if session.get("join_attempt") is not None else {})}), WRITE_TIMEOUT_SECONDS)
                if not session["lines"] and not session.get("metrics") and not any(session.get(bucket) for bucket in
                        ("notes_acks", "progress_acks", "announcement_deferrals")):
                    with suppress(OSError, ValueError):
                        (RECOVERY_DIR / (str(uuid.UUID(session["meeting"])) + ".json")).unlink(missing_ok=True)
            except Exception:
                self.persist_transcript(session)
        if self.session is session:
            self.session = None

    async def stop(self, reason: str = "stopped", *, test_generation: int | None = None):
        if test_generation is not None:
            # Authorization can finish after a scheduled real meeting replaced the test.
            # Test cancellation may affect only the test/start it originally targeted.
            if test_generation != self.start_generation:
                return
            if self.session and not self.session.get("test_mode"):
                return
            if not self.session and not self.pending_test_mode:
                return
        self.start_generation += 1
        session = self.session
        if session and not session["closed"].is_set():
            session["reason"] = reason
            session["closed"].set()
            if session.get("process"):
                await session["process"].close()
        if self.task:
            with suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self.task), 15)

    async def preflight(self):
        process = await asyncio.create_subprocess_exec(settings.DISCORD_VOICE_NODE_BINARY, str(VOICE_DIR / "host-worker.mjs"), "--check",
            cwd=str(VOICE_DIR), env=VoiceCaptureClient.child_env(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 20)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ValueError("Shërbimi zanor i Mira-s nuk u nis.") from None
        if process.returncode or b'"host_ready":true' not in output:
            raise ValueError("Shërbimi zanor i Mira-s nuk është gati.")


def status_text(state: dict) -> str:
    live = state.get("live")
    if not state.get("enabled") and not live:
        return "Mira **nuk** po i mban takimet 1H. Thirre tani me `/mira hyr` ose aktivizo orarin me `/mira mbaj-takimet`."
    if state.get("enabled"):
        until = datetime.fromisoformat(state["enabled_until"]).astimezone(tz()).strftime("%H:%M")
        text = f"✅ Mira i mban takimet 1H deri në **{until}** (slotet {', '.join(state['slots'])})."
    else:
        text = "🎙️ Mira po e mban takimin aktual. Orari automatik është joaktiv."
    if live:
        people = " → ".join(f"{p['initials']}{'✓' if p['status'] == 'DONE' else ('🎙️' if p['status'] == 'ACTIVE' else '')}"
                            for p in live["people"])
        text += f"\nTani: {'🧪 **TEST** · ' if live.get('is_test') else ''}**1H {live['slot']}** ({live['status']}) {people}"
    return text


def register_host_commands(bot, guild):
    if not (settings.MIRA_HOST_ENABLED and settings.MIRA_HOST_BOT_TOKEN):
        return
    group = app_commands.Group(name="mira", description="Mira mban takimet 1H (test)")

    def command_scope(interaction):
        gid = getattr(interaction, 'guild_id', None) or getattr(getattr(interaction, 'guild', None), 'id', None)
        cid = getattr(interaction, 'channel_id', None)
        return {'guild_id': str(gid), 'channel_id': str(cid)} if gid and cid else {}

    def shared(interaction):
        scope = command_scope(interaction)
        return bool(settings.DISCORD_MEETING_CONTROL_CHANNEL_ID and scope.get('guild_id') == settings.DISCORD_GUILD_ID
            and scope.get('channel_id') == settings.DISCORD_MEETING_CONTROL_CHANNEL_ID)

    @group.command(name="hyr", description="Mira Host hyn tani në 1H dhe nis takimin e slotit të zgjedhur")
    @app_commands.describe(sloti="Sloti 1H për të cilin do të mbahet takimi tani",
                           test="Test mode: provo slotin pa e zënë takimin real dhe pa ndryshime reale")
    @app_commands.choices(sloti=[app_commands.Choice(name=slot, value=slot) for slot in SLOTS])
    async def join(interaction: discord.Interaction, sloti: str, test: bool = False):
        public = shared(interaction)
        await interaction.response.defer(thinking=True, ephemeral=not public)
        try:
            scope = command_scope(interaction)
            extra = {'command_context': scope} if scope else {}
            if test:
                extra['test_mode'] = True
            await bot.mira_host.join_now(interaction.guild, sloti, str(interaction.user.id), **extra)
            label = "🧪 **TEST MODE** · Takimi real mbetet i lirë. " if test else "🎙️ "
            await interaction.followup.send(f"{label}Mira Host u kyç në **1H** · **{sloti}**.", ephemeral=not public)
        except Exception as exc:
            await interaction.followup.send(bot.error_message(exc), ephemeral=True)

    @group.command(name="mbaj-takimet", description="Mira i mban vetë takimet 1H (test)")
    @app_commands.describe(deri_ne_ore="Deri në cilën orë sot, p.sh. 12:00 (bosh = deri në fund të ditës)")
    async def start(interaction: discord.Interaction, deri_ne_ore: str | None = None):
        public = shared(interaction)
        await interaction.response.defer(thinking=True, ephemeral=not public)
        try:
            await bot.mira_host.preflight()
            state = await bot.bridge(PREFIX + "/enable", {"discord_user_id": str(interaction.user.id), "until": deri_ne_ore,
                **command_scope(interaction)})
            await interaction.followup.send(status_text(state), ephemeral=not public)
        except Exception as exc:
            await interaction.followup.send(bot.error_message(exc), ephemeral=True)

    @group.command(name="ndalo", description="Ndalo Mira-n si mbajtëse e takimeve 1H")
    async def stop(interaction: discord.Interaction):
        public = shared(interaction)
        await interaction.response.defer(thinking=True, ephemeral=not public)
        try:
            test_only = bool((getattr(bot.mira_host, 'session', None) or {}).get('test_mode')
                             or getattr(bot.mira_host, 'pending_test_mode', False))
            test_generation = bot.mira_host.start_generation if test_only else None
            await bot.bridge(PREFIX + "/disable", {"discord_user_id": str(interaction.user.id),
                **({"test_only": True} if test_only else {}), **command_scope(interaction)})
            await bot.mira_host.stop("stopped_by_command", **({"test_generation": test_generation} if test_only else {}))
            await interaction.followup.send("⏹️ Testi i Mira Host u ndal; orari automatik mbetet i pandryshuar." if test_only
                                            else "⏹️ Mira Host u ndal.", ephemeral=not public)
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
