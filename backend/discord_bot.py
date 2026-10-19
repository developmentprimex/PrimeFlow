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
import discord_ui as ui
import discord_agent_client as agent_client

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


def display_text(value: str) -> str:
    """Hide PrimeFlow editor markers in Discord without changing stored text."""
    return re.sub(r"\[\[\s*/?\s*(?:added|done)(?::(?:blue|green|grey))?\s*\]\]", "", value, flags=re.I)


def task_label(title: str) -> str:
    plain = display_text(title)
    return (re.sub(r"\s+", " ", plain).strip() or "Detyrë")[:100]


def task_view(task_id: str, fingerprint: str = "") -> discord.ui.View:
    return ui.controls(task_id, fingerprint, ACTION_CHOICES)


def task_pages(task_list: list[dict], title: str):
    if not task_list:
        return [(f"{title}\nNuk ke detyra të hapura për këtë periudhë.", None)]
    pages = []
    for offset in range(0, len(task_list), ui.TASKS_PER_PAGE):
        chunk = task_list[offset:offset + ui.TASKS_PER_PAGE]
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Select(custom_id="pf:task", placeholder="Zgjidh detyrën",
            options=[discord.SelectOption(label=f"{offset + i}. {task_label(ui.heading(task))}"[:100], value=task["id"],
                ) for i, task in enumerate(chunk, 1)]))
        lines = [f"{offset + i}. {discord.utils.escape_markdown(ui.heading(task)[:100])[:120]}" for i, task in enumerate(chunk, 1)]
        content = f"**{title}** · {offset + 1}–{offset + len(chunk)} / {len(task_list)}\n" + "\n".join(lines)
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
        self.task_details = {}
        self.task_cards = {}
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
                for page, (text, view) in enumerate(task_pages(data["tasks"], "Detyrat e tua për sot")):
                    await interaction.followup.send(text, embeds=ui.overview_embeds(data["tasks"], page), view=view or discord.utils.MISSING)
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
        self.agent_results.start()

    async def show_result(self, interaction, result):
        text = result["message"]
        if result.get("applied"):
            text += "\nU zbatuan: " + "; ".join(result["applied"])
        task = result.get("task")
        if task and result.get("fingerprint"):
            await self.show_task(interaction, result, notice=text, update=True)
            return
        if result.get("url"):
            text += f"\n{result['url']}"
        for part in chunks(text):
            await interaction.followup.send(part)

    def remember_task(self, interaction, detail):
        key = (interaction.guild_id, interaction.channel_id, interaction.user.id, detail["task"]["id"])
        self.task_details[key] = detail
        if len(self.task_details) > 512:
            oldest = next(iter(self.task_details))
            del self.task_details[oldest]
            self.task_cards.pop(oldest, None)

    async def show_task(self, interaction, detail, *, notice="Zgjidh veprimin për këtë detyrë.", update=False):
        self.remember_task(interaction, detail)
        task = detail["task"]
        embed = ui.card(task, detail=detail)
        view = task_view(task["id"], detail["fingerprint"])
        source = getattr(interaction, "message", None)
        key = (interaction.guild_id, interaction.channel_id, interaction.user.id, task["id"])
        if not (source and len(source.embeds) == 1 and source.embeds[0].url == ui.task_url(task["id"])):
            source = self.task_cards.get(key)
        if update and source:
            try:
                await source.edit(content=display_text(notice)[:1800], embed=embed, view=view)
            except discord.NotFound:
                self.task_cards.pop(key, None)
                await self.show_task(interaction, detail, notice=notice)
                return
            self.task_cards[key] = source
            await interaction.followup.send("U përditësua në PrimeFlow dhe në kartë.", ephemeral=True)
        else:
            self.task_cards[key] = await interaction.followup.send(display_text(notice)[:1800], embed=embed, view=view, wait=True)

    async def run_direct(self, interaction, task_id, fingerprint, actions, instruction):
        try:
            await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
            result = await self.bridge("/bot/command", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id),
                "request_id": str(interaction.id), "task_id": task_id, "instruction": instruction,
                "expected_fingerprint": fingerprint, "direct_actions": actions})
            if result.get("status") == "DONE" and result.get("task") and (getattr(interaction, "data", None) or {}).get("custom_id", "").startswith("pf:pointset:"):
                picker = ui.points_view(result)
                try:
                    await interaction.message.edit(content="Zgjidh pikat për strike / heqje strike:", view=picker)
                except discord.HTTPException:
                    log.warning("Could not refresh the strike picker after a saved change")
            await self.show_result(interaction, result)
        except Exception as exc:
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    async def current_detail(self, interaction, task_id, fingerprint=None):
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        detail = await self.bridge("/bot/select", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": task_id})
        if fingerprint and detail["fingerprint"] != fingerprint:
            await self.show_task(interaction, detail, notice="Detyra ndryshoi. Zgjidh veprimin mbi këtë kartë të rifreskuar.", update=True)
            return None
        self.remember_task(interaction, detail)
        return detail

    async def show_people(self, interaction, task_id, fingerprint, page=0):
        if not await self.current_detail(interaction, task_id, fingerprint):
            return
        result = await self.bridge("/bot/people", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": task_id})
        await interaction.followup.send("Zgjidh personin e konfirmimit:", view=ui.people_view(result["people"], task_id, fingerprint, page))

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        custom_id = data.get("custom_id", "")
        if not custom_id.startswith("pf:"):
            return
        try:
            if custom_id.startswith("pf:agent:"):
                await agent_client.handle_agent_interaction(self, interaction)
                return
            if custom_id.startswith("pf:quick:"):
                _, _, task_id, fingerprint, action = custom_id.split(":")
                if action == "comment" or action == "done":
                    await interaction.response.send_modal(ui.CommentModal(self, task_id, fingerprint, complete=action == "done"))
                elif action == "edit":
                    key = (interaction.guild_id, interaction.channel_id, interaction.user.id, task_id)
                    detail = self.task_details.get(key)
                    if not detail or detail["fingerprint"] != fingerprint:
                        await interaction.response.send_message("Kliko Rifresko detyrën dhe pastaj Edito.", ephemeral=True)
                    else:
                        await interaction.response.send_modal(ui.EditModal(self, detail))
                else:
                    await interaction.response.defer(thinking=True)
                    if action in {"todo", "progress", "wfe"}:
                        status = {"todo": "TODO", "progress": "IN_PROGRESS", "wfe": "WAITING_CLIENT"}[action]
                        await self.run_direct(interaction, task_id, fingerprint, [ui.action("update_task", {"status": status})], "Ndrysho statusin në " + status)
                    elif action == "confirm":
                        await self.show_people(interaction, task_id, fingerprint)
                    elif action in {"points", "schedule", "refresh"}:
                        detail = await self.current_detail(interaction, task_id, None if action == "refresh" else fingerprint)
                        if detail:
                            if action == "refresh":
                                await self.show_task(interaction, detail, update=True)
                            elif action == "points":
                                view = ui.points_view(detail)
                                await interaction.followup.send("Zgjidh një ose disa pika për strike / heqje strike." if view.children else "Kjo detyrë nuk ka pika për shënim.", view=view if view.children else discord.utils.MISSING)
                            else:
                                await interaction.followup.send("Ndrysho slotin ose AM/PM. Slotet ndjekin datën efektive të PrimeFlow.", view=ui.schedule_view(task_id, fingerprint))
            elif custom_id.startswith("pf:pointset:"):
                _, _, task_id, fingerprint, field, done = custom_id.split(":")
                if field not in {"t", "d"} or done not in {"0", "1"}:
                    raise ValueError("Përzgjedhje e pavlefshme.")
                await interaction.response.defer(thinking=True)
                numbers = [int(number) for number in data["values"]]
                await self.run_direct(interaction, task_id, fingerprint,
                    [ui.action("set_points", {"field": "title" if field == "t" else "description", "numbers": numbers, "done": done == "1"})],
                    ("Bëj strike" if done == "1" else "Hiq strike") + " pikat " + ", ".join(map(str, numbers)))
            elif custom_id.startswith("pf:points:"):
                _, _, task_id, fingerprint, page = custom_id.split(":")
                await interaction.response.defer(thinking=True)
                detail = await self.current_detail(interaction, task_id, fingerprint)
                if detail:
                    await interaction.followup.send("Zgjidh pikat:", view=ui.points_view(detail, max(0, int(page))))
            elif custom_id.startswith("pf:schedule:"):
                _, _, task_id, fingerprint = custom_id.split(":")
                await interaction.response.defer(thinking=True)
                kind, value = data["values"][0].split(":", 1)
                if kind == "period":
                    actions = [ui.action("update_task", {"finish_period": value or None})]
                elif kind == "slot":
                    from zoneinfo import ZoneInfo
                    actions = [ui.action("slot", {"one_h_report_slot": value or None, "report_date": datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date().isoformat()})]
                else:
                    raise ValueError("Planifikim i pavlefshëm.")
                await self.run_direct(interaction, task_id, fingerprint, actions, "Ndrysho planifikimin: " + (value or "hiq periudhën/slotin"))
            elif custom_id.startswith("pf:confirm:"):
                _, _, task_id, fingerprint = custom_id.split(":")
                await interaction.response.defer(thinking=True)
                await self.run_direct(interaction, task_id, fingerprint,
                    [ui.action("update_task", {"confirmation_assignee_id": data["values"][0], "status": "WAITING_CONFIRMATION"})], "Dërgoje për konfirmim te personi i zgjedhur.")
            elif custom_id.startswith("pf:people:"):
                _, _, task_id, fingerprint, page = custom_id.split(":")
                await interaction.response.defer(thinking=True)
                await self.show_people(interaction, task_id, fingerprint, max(0, int(page)))
            elif custom_id.startswith("pf:action:"):
                index = int(data["values"][0])
                if index < 0 or index >= len(ACTION_CHOICES):
                    raise ValueError("Veprim i panjohur.")
                parts = custom_id.split(":")
                await interaction.response.send_modal(InstructionModal(self, parts[2], index, parts[3] if len(parts) > 3 else ""))
            elif custom_id == "pf:task":
                await interaction.response.defer(thinking=True)
                await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
                result = await self.bridge("/bot/select", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": data["values"][0]})
                await self.show_task(interaction, result)
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
    async def agent_results(self):
        try:
            await agent_client.deliver_agent_results(self)
        except Exception as exc:
            log.warning("Agent result polling failed: %s", type(exc).__name__)

    @agent_results.before_loop
    async def before_agent_results(self):
        await self.wait_until_ready()

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
                                json={"content": text, "embeds": [embed.to_dict() for embed in ui.overview_embeds(data["tasks"], page)], "components": view.to_components() if view else [],
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
        self.agent_results.cancel()
        await self.http_bridge.aclose()
        await super().close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not all((settings.DISCORD_ASSISTANT_ENABLED, settings.DISCORD_BOT_TOKEN, settings.DISCORD_BRIDGE_SECRET, settings.DISCORD_GUILD_ID)):
        raise SystemExit("Configure DISCORD_ASSISTANT_ENABLED, DISCORD_BOT_TOKEN, DISCORD_BRIDGE_SECRET and DISCORD_GUILD_ID first.")
    PrimeFlowBot().run(settings.DISCORD_BOT_TOKEN, log_handler=None)
