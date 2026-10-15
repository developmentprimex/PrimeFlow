"""Run separately: python discord_bot.py (see docs/discord-assistant.md)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
import httpx
from discord import app_commands
from discord.ext import tasks

from app.config import settings

log = logging.getLogger("primeflow.discord")
ACTION_CHOICES = [
    ("Udhëzim i lirë", ""), ("Strike pika", "Bëji strike pikat "),
    ("Hiq strike", "Hiq strike nga pikat "), ("Në progres", "Lëre në progres."),
    ("Mbylle", "Mbylle detyrën."), ("WFE", "Bëje WFE."),
    ("Në pritje konfirmimi", "Dërgoje për konfirmim."), ("To Do / Rihap", "Ktheje në To Do."),
    ("Shto koment", "Shto komentin: "), ("Ndrysho progresin", "Ndrysho progresin në "),
    ("Afati / AM / PM", "Ndrysho "), ("Sloti 1H", "Ndrysho slotin në "),
    ("Kontrolli 1 / 2", "Ndrysho personin e kontrollit "), ("Marker / Prioritet", "Ndrysho "),
    ("Ndryshime të tjera", ""),
]


def actor(user_id: int, guild_id: int, channel_id: int) -> dict:
    return {"discord_user_id": str(user_id), "guild_id": str(guild_id), "channel_id": str(channel_id)}


def overwrite_signature(overwrites) -> dict:
    """Compare Discord identities and bits, independent of the member cache.

    Without the privileged members intent, channel overwrites can be keyed by
    Object(type=User) while fetch_member returns Member. Those Python objects
    compare unequal despite representing the same Discord user.
    """
    result = {}
    for target, overwrite in overwrites.items():
        is_role = isinstance(target, discord.Role) or (isinstance(target, discord.Object) and target.type is discord.Role)
        allow, deny = overwrite.pair()
        result[("role" if is_role else "member", target.id)] = (allow.value, deny.value)
    return result


def task_label(title: str) -> str:
    plain = re.sub(r"\[\[.*?\]\]", "", title, flags=re.S)
    return (re.sub(r"\s+", " ", plain).strip() or "Detyrë")[:100]


def task_view(task_id: str, fingerprint: str = "") -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(custom_id=f"pf:action:{task_id}:{fingerprint}", placeholder="Çfarë dëshiron të bësh?",
        options=[discord.SelectOption(label=label, value=str(i)) for i, (label, _) in enumerate(ACTION_CHOICES)]))
    return view


def task_pages(task_list: list[dict], title: str):
    if not task_list:
        return [(f"{title}\nNuk ke detyra të hapura për këtë periudhë.", None)]
    pages = []
    for offset in range(0, len(task_list), 25):
        chunk = task_list[offset:offset + 25]
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Select(custom_id="pf:task", placeholder="Zgjidh detyrën për raportim",
            options=[discord.SelectOption(label=task_label(task["title"]), value=task["id"],
                description=f"{task.get('status', '')} · 1H {task.get('one_h_report_slot') or '—'} · {task.get('finish_period') or '—'}"[:100]) for task in chunk]))
        names = [re.sub(r"\s+", " ", task["title"])[:100] for task in chunk]
        lines = [f"{offset + i}. {name} — {task.get('status')}" for i, (name, task) in enumerate(zip(names, chunk), 1)]
        # Full titles and points are displayed after selection; keep each panel
        # within Discord's content limit even when there are 25 long task names.
        content = f"{title} · {offset + 1}–{offset + len(chunk)} / {len(task_list)}\nZgjidh detyrën nga dropdown."
        if len("\n".join(lines)) + len(content) < 1900:
            content += "\n" + "\n".join(lines)
        pages.append((content, view))
    return pages


def chunks(text: str, limit: int = 1800):
    while text:
        split = text.rfind("\n", 0, limit)
        split = split if split > 0 and len(text) > limit else min(len(text), limit)
        yield text[:split]
        text = text[split:].lstrip("\n")


class InstructionModal(discord.ui.Modal):
    def __init__(self, bot, task_id: str, action_index: int, fingerprint: str = ""):
        super().__init__(title=ACTION_CHOICES[action_index][0][:45], timeout=600)
        self.bot, self.task_id = bot, task_id
        self.fingerprint = fingerprint
        self.instruction = discord.ui.TextInput(label="Udhëzimi për këtë detyrë", style=discord.TextStyle.paragraph,
            default=ACTION_CHOICES[action_index][1] or None, max_length=4000, required=True)
        self.add_item(self.instruction)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            await self.bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
            result = await self.bot.bridge("/bot/command", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id),
                "request_id": str(interaction.id), "task_id": self.task_id, "instruction": str(self.instruction),
                "expected_fingerprint": self.fingerprint or None})
            await self.bot.show_result(interaction, result)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)


class PrimeFlowBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = settings.DISCORD_MESSAGE_CONTENT_ENABLED
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.http_bridge = httpx.AsyncClient(base_url=settings.PRIMEFLOW_API_BASE_URL.rstrip("/") + "/api/discord",
            timeout=90, headers={"X-Primeflow-Discord-Secret": settings.DISCORD_BRIDGE_SECRET})

    async def bridge(self, path: str, payload: dict):
        response = await self.http_bridge.post(path, json=payload)
        if response.is_error:
            try:
                detail = response.json().get("detail", "PrimeFlow e refuzoi kërkesën.")
            except ValueError:
                detail = "PrimeFlow nuk është i disponueshëm."
            raise ValueError(str(detail)[:1500])
        return response.json()

    def clear_ready_status(self):
        path = Path(__file__).with_name(".discord-worker-status.json")
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def publish_ready_status(self):
        if not self.get_guild(int(settings.DISCORD_GUILD_ID)):
            self.clear_ready_status()
            log.error("Bot connected but is not a member of the configured Discord server")
            return
        path = Path(__file__).with_name(".discord-worker-status.json")
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"guild_id": settings.DISCORD_GUILD_ID,
            "pid": os.getpid(), "build": os.getenv("APP_BUILD_SHA", "unknown"),
            "connected_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        temporary.replace(path)
        log.info("Discord bot connected; slash commands registered")

    async def on_ready(self):
        self.publish_ready_status()

    async def on_resumed(self):
        self.publish_ready_status()

    async def on_disconnect(self):
        self.clear_ready_status()

    @staticmethod
    def error_message(exc, *, read_only=False):
        if isinstance(exc, ValueError):
            return str(exc)[:1800]
        log.error("Discord operation failed: %s status=%s code=%s", type(exc).__name__, getattr(exc, "status", None), getattr(exc, "code", None))
        if isinstance(exc, discord.Forbidden):
            return "Discord e refuzoi veprimin për shkak të lejeve të botit. Administratori duhet të kontrollojë lejet e kanalit privat."
        if isinstance(exc, discord.HTTPException) and exc.code == 50035:
            return "Discord e refuzoi formatin e mesazhit. Administratori duhet të kontrollojë formatimin e listës së detyrave."
        if isinstance(exc, httpx.TimeoutException):
            return "PrimeFlow nuk u përgjigj në kohë. Provo /detyrat përsëri." if read_only else "PrimeFlow nuk u përgjigj në kohë. Kontrollo detyrën para se ta ridërgosh komandën."
        if read_only:
            return "Lista e detyrave nuk u shfaq. Nuk u kërkua asnjë ndryshim në detyra; provo përsëri ose njofto administratorin."
        return "Veprimi nuk u përfundua. Kontrollo PrimeFlow para se ta ridërgosh."

    async def private_channel(self, guild_id, channel_id, user_id):
        if not guild_id or str(guild_id) != settings.DISCORD_GUILD_ID:
            raise ValueError("Përdor serverin Discord të PrimeFlow.")
        guild = self.get_guild(int(guild_id))
        if not guild:
            raise ValueError("Serveri nuk u gjet.")
        member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
        channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel) or channel.topic != f"PrimeFlow personal workspace: {user_id}":
            raise ValueError("Përdor kanalin tënd privat të krijuar nga /lidh.")
        # Repair unexpected grants before displaying task data. Server owners
        # and Administrators retain Discord's built-in access.
        expected = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)}
        if overwrite_signature(channel.overwrites) != overwrite_signature(expected):
            if not channel.permissions_for(guild.me).manage_roles:
                raise ValueError("Lejet e kanalit privat kanë ndryshuar. Për t'i korrigjuar, botit i duhet leja Manage Roles në Discord.")
            await channel.edit(overwrites=expected, reason="PrimeFlow personal channel privacy")
        return channel

    async def setup_hook(self):
        guild = discord.Object(id=int(settings.DISCORD_GUILD_ID))

        @self.tree.command(name="lidh", description="Lidhe llogarinë personale PrimeFlow me kod njëpërdorimësh", guild=guild)
        async def link(interaction: discord.Interaction, kodi: str):
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                if str(interaction.guild_id) != settings.DISCORD_GUILD_ID:
                    raise ValueError("Server i palejuar.")
                result = await self.bridge("/bot/link", {"code": kodi, "discord_user_id": str(interaction.user.id), "guild_id": str(interaction.guild_id)})
                server = interaction.guild
                channel = None
                if result.get("channel_id"):
                    channel = await self.private_channel(server.id, int(result["channel_id"]), interaction.user.id)
                else:
                    # If the previous attempt created a channel but lost the
                    # bind response, reuse the marked channel on the next link.
                    channel = next((c for c in server.text_channels if c.topic == f"PrimeFlow personal workspace: {interaction.user.id}"), None)
                    if channel:
                        channel = await self.private_channel(server.id, channel.id, interaction.user.id)
                    else:
                        category = None
                        if settings.DISCORD_CATEGORY_ID:
                            category = server.get_channel(int(settings.DISCORD_CATEGORY_ID))
                            if not isinstance(category, discord.CategoryChannel):
                                raise ValueError("Kategoria Discord e konfiguruar nuk u gjet.")
                        channel = await server.create_text_channel(f"primeflow-{interaction.user.id}", category=category,
                            topic=f"PrimeFlow personal workspace: {interaction.user.id}",
                            overwrites={server.default_role: discord.PermissionOverwrite(view_channel=False),
                                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                                server.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)})
                    await self.bridge("/bot/bind-channel", actor(interaction.user.id, server.id, channel.id))
                await interaction.followup.send(f"Llogaria u lidh. Kanali yt: {channel.mention}. Përdor /detyrat atje.", ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(self.error_message(exc), ephemeral=True)

        @self.tree.command(name="detyrat", description="Shfaq detyrat e tua të hapura për sot", guild=guild)
        async def show_tasks(interaction: discord.Interaction):
            await interaction.response.defer(thinking=True)
            try:
                await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
                data = await self.bridge("/bot/tasks", actor(interaction.user.id, interaction.guild_id, interaction.channel_id))
                for text, view in task_pages(data["tasks"], "Detyrat e tua për sot"):
                    await interaction.followup.send(text, view=view or discord.utils.MISSING)
            except Exception as exc:
                await interaction.followup.send(self.error_message(exc, read_only=True), ephemeral=True)

        @self.tree.command(name="pyet", description="Jep udhëzim për detyrën që ke zgjedhur", guild=guild)
        async def ask(interaction: discord.Interaction, udhezimi: str):
            await interaction.response.defer(thinking=True)
            try:
                await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
                result = await self.bridge("/bot/command", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id),
                    "request_id": str(interaction.id), "instruction": udhezimi})
                await self.show_result(interaction, result)
            except Exception as exc:
                await interaction.followup.send(self.error_message(exc), ephemeral=True)

        await self.tree.sync(guild=guild)
        self.reminders.start()

    async def show_result(self, interaction, result):
        text = result["message"]
        if result.get("applied"):
            text += "\nU zbatuan: " + "; ".join(result["applied"])
        task = result.get("task")
        if task:
            text += f"\nStatusi: {task['status']} · Progresi: {task['progress_percentage']}%"
        if result.get("url"):
            text += f"\n{result['url']}"
        for part in chunks(text):
            await interaction.followup.send(part)
        if task and result.get("fingerprint"):
            await interaction.followup.send("Veprimi tjetër për këtë detyrë:", view=task_view(task["id"], result["fingerprint"]))

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        custom_id = data.get("custom_id", "")
        if not custom_id.startswith("pf:"):
            return
        try:
            if custom_id.startswith("pf:action:"):
                index = int(data["values"][0])
                if index < 0 or index >= len(ACTION_CHOICES):
                    raise ValueError("Veprim i panjohur.")
                parts = custom_id.split(":")
                await interaction.response.send_modal(InstructionModal(self, parts[2], index, parts[3] if len(parts) > 3 else ""))
            elif custom_id == "pf:task":
                await interaction.response.defer(thinking=True)
                await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
                result = await self.bridge("/bot/select", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": data["values"][0]})
                task = result["task"]
                lines = [task["title"], f"Statusi: {task['status']} · Sloti: {task.get('one_h_report_slot') or '—'} · {task.get('finish_period') or '—'}"]
                for label, field in (("Pikat e titullit", "title_points"), ("Pikat e përshkrimit", "description_points")):
                    if result[field]:
                        lines.append(label + ":")
                        lines.extend(f"{p['number']}. {'✓' if p['done'] else '○'} {p['text']}" for p in result[field])
                lines.append(result["url"])
                for part in chunks("\n".join(lines)):
                    await interaction.followup.send(part)
                await interaction.followup.send("Zgjidh veprimin, përdor /pyet, ose shkruaj udhëzimin në këtë kanal.", view=task_view(task["id"], result["fingerprint"]))
        except Exception as exc:
            if interaction.response.is_done():
                await interaction.followup.send(self.error_message(exc), ephemeral=True)
            else:
                await interaction.response.send_message(self.error_message(exc), ephemeral=True)

    async def on_message(self, message: discord.Message):
        if not settings.DISCORD_MESSAGE_CONTENT_ENABLED or message.author.bot or not message.guild or not message.content.strip():
            return
        if str(message.guild.id) != settings.DISCORD_GUILD_ID or getattr(message.channel, "topic", None) != f"PrimeFlow personal workspace: {message.author.id}":
            return
        try:
            channel = await self.private_channel(message.guild.id, message.channel.id, message.author.id)
            async with channel.typing():
                result = await self.bridge("/bot/command", {**actor(message.author.id, message.guild.id, channel.id),
                    "request_id": str(message.id), "instruction": message.content[:4000]})
            text = result["message"]
            if result.get("applied"):
                text += "\nU zbatuan: " + "; ".join(result["applied"])
            if result.get("task"):
                text += f"\nStatusi: {result['task']['status']} · Progresi: {result['task']['progress_percentage']}%"
            if result.get("url"):
                text += "\n" + result["url"]
            for part in chunks(text):
                await channel.send(part)
        except Exception as exc:
            # Never publish an error (which can contain task context) into a
            # channel whose privacy check failed.
            log.warning("Message %s failed: %s", message.id, type(exc).__name__)
            if isinstance(exc, ValueError) and "channel" in locals():
                await channel.send(self.error_message(exc))

    @tasks.loop(seconds=30)
    async def reminders(self):
        try:
            jobs = (await self.bridge("/bot/reminders/claim", {}))["jobs"]
            semaphore = asyncio.Semaphore(4)
            async def deliver(job):
                async with semaphore:
                    try:
                        channel = await self.private_channel(job["guild_id"], job["channel_id"], job["discord_user_id"])
                        identity = {key: job[key] for key in ("discord_user_id", "guild_id", "channel_id")}
                        data = await self.bridge(f"/bot/reminders/{job['id']}/tasks", identity)
                        message_ids = []
                        for page, (text, view) in enumerate(task_pages(data["tasks"], f"Raportimi {job['bucket']} — si kanë ecur këto detyra?")):
                            # Discord deduplicates the same nonce on a retried
                            # send. The key survives worker/API restarts.
                            nonce = hashlib.sha256(f"{job['id']}:{page}".encode()).hexdigest()[:24]
                            message = await self.http.request(discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
                                json={"content": text, "components": view.to_components() if view else [],
                                    "allowed_mentions": {"parse": []}, "nonce": nonce, "enforce_nonce": True})
                            message_ids.append(str(message["id"]))
                        await self.bridge(f"/bot/reminders/{job['id']}/ack", {**identity, "message_ids": message_ids})
                    except Exception as exc:
                        log.warning("Reminder %s failed: %s", job["id"], type(exc).__name__)
            await asyncio.gather(*(deliver(job) for job in jobs))
        except Exception as exc:
            log.warning("Reminder polling failed: %s", type(exc).__name__)

    @reminders.before_loop
    async def before_reminders(self):
        await self.wait_until_ready()

    async def close(self):
        self.clear_ready_status()
        self.reminders.cancel()
        await self.http_bridge.aclose()
        await super().close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not all((settings.DISCORD_ASSISTANT_ENABLED, settings.DISCORD_BOT_TOKEN, settings.DISCORD_BRIDGE_SECRET, settings.DISCORD_GUILD_ID)):
        raise SystemExit("Configure DISCORD_ASSISTANT_ENABLED, DISCORD_BOT_TOKEN, DISCORD_BRIDGE_SECRET and DISCORD_GUILD_ID first.")
    PrimeFlowBot().run(settings.DISCORD_BOT_TOKEN, log_handler=None)
