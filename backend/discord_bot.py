"""Run separately: python discord_bot.py (see docs/discord-assistant.md)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
import httpx
from discord import app_commands
from discord.ext import tasks

from app.config import settings
import discord_ui as ui
import discord_agent_client as agent_client
import discord_voice_meetings as voice_meetings

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


def task_view(task_id: str, fingerprint: str = "", status: str | None = None) -> discord.ui.View:
    return ui.controls(task_id, fingerprint, status)


def task_ids_in(message) -> list[str]:
    """Task ids behind a bot message's buttons and menus, in the order shown."""
    ids = []

    def add(value):
        try:
            value = str(uuid.UUID(str(value)))
        except ValueError:
            return
        if value not in ids:
            ids.append(value)
    for row in getattr(message, "components", None) or []:
        for item in getattr(row, "children", None) or []:
            custom_id = getattr(item, "custom_id", None) or ""
            parts = custom_id.split(":")
            if custom_id == "pf:task" or custom_id.startswith("pf:repdone:"):
                for option in item.options:
                    add(option.value)
            elif custom_id.startswith("pf:rep:") and len(parts) > 3:
                add(parts[3])
            elif parts[:2] in (["pf", "open"], ["pf", "quick"], ["pf", "more"], ["pf", "nav"], ["pf", "back"],
                               ["pf", "pointset"], ["pf", "points"], ["pf", "schedule"], ["pf", "confirm"]) and len(parts) > 2:
                add(parts[2])
    return ids


def in_place(interaction) -> bool:
    """True when the click was acknowledged by editing its own message."""
    try:
        return interaction.response.type == discord.InteractionResponseType.deferred_message_update
    except AttributeError:
        return False


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
        await interaction.response.defer()
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
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none(), enable_debug_events=settings.DISCORD_MEETING_NOTES_ENABLED)
        self.meeting_capture = voice_meetings.MeetingCaptureCoordinator(self)
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
        await self.announce_push_done()

    async def announce_push_done(self):
        """After /push the deploy restarts the bot with the new build; tell everyone it is over."""
        try:
            targets = (await self.bridge("/bot/push/complete", {"build": os.getenv("APP_BUILD_SHA", "unknown")}))["targets"]
        except Exception as exc:
            log.warning("Push completion check failed: %s", type(exc).__name__)
            return
        await self.broadcast(targets, ui.push_done)

    async def broadcast(self, targets, render) -> int:
        """Ping each person in their private channel; returns how many were reached."""
        sent = 0
        for target in targets:
            try:
                channel = await self.private_channel(settings.DISCORD_GUILD_ID, target["channel_id"], target["discord_user_id"])
                await channel.send(render(target["discord_user_id"]),
                    allowed_mentions=discord.AllowedMentions(users=[discord.Object(int(target["discord_user_id"]))]))
                sent += 1
            except Exception as exc:
                log.warning("Broadcast to %s failed: %s", target["channel_id"], type(exc).__name__)
        return sent

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

    async def ensure_status_emojis(self):
        """Upload the pink To Do circle once as an application emoji and use it everywhere."""
        try:
            emoji = next((item for item in await self.fetch_application_emojis() if item.name == "pf_todo"), None)
            if emoji is None:
                emoji = await self.create_application_emoji(name="pf_todo", image=ui.pink_circle_png())
            ui.STATUS_ICONS["TODO"] = str(emoji)
        except (discord.HTTPException, discord.DiscordException) as exc:
            # Cosmetic only: the purple fallback keeps everything working.
            log.warning("Pink To Do emoji unavailable, using the fallback: %s", type(exc).__name__)

    async def setup_hook(self):
        await self.ensure_status_emojis()
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
                text, view = ui.list_view(data["tasks"], "📋 Detyrat e tua për sot")
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

        @self.tree.command(name="push", description="Njofto të gjithë që PrimeFlow po përditësohet", guild=guild)
        @app_commands.describe(minuta="Sa minuta zgjat përafërsisht (parazgjedhje 5)", shenim="Shënim opsional për ekipin")
        async def push(interaction: discord.Interaction, minuta: app_commands.Range[int, 1, 60] = 5, shenim: str | None = None):
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                result = await self.bridge("/bot/push", {"discord_user_id": str(interaction.user.id), "guild_id": str(interaction.guild_id),
                    "request_id": str(interaction.id), "build": os.getenv("APP_BUILD_SHA", "unknown")})
                if result["status"] != "SENT":
                    await interaction.followup.send("ℹ " + result["message"], ephemeral=True)
                    return
                sent = await self.broadcast(result["targets"], lambda user_id: ui.push_notice(user_id, result["by"], minuta, shenim))
                await interaction.followup.send(f"📢 Njoftimi u dërgua te {sent} persona. Kur PrimeFlow të rinisë me versionin e ri, "
                    "të gjithë marrin automatikisht njoftimin ✅.", ephemeral=True)
            except Exception as exc:
                await interaction.followup.send(self.error_message(exc), ephemeral=True)

        voice_meetings.register_meeting_commands(self, guild)
        await self.tree.sync(guild=guild)
        if settings.DISCORD_MEETING_NOTES_ENABLED:
            self.voice_meeting_results.start()
        self.reminders.start()
        self.meeting_alerts.start()
        self.agent_results.start()

    async def show_result(self, interaction, result):
        text = result["message"]
        if result.get("applied"):
            text += "\nU zbatuan: " + "; ".join(result["applied"])
        task = result.get("task")
        if task and result.get("fingerprint"):
            await self.show_task(interaction, result, notice="✓ " + text, update=True)
            return
        if result.get("url"):
            text += f"\n{result['url']}"
        for part in chunks(text):
            # A refused click must not leave a new message in the channel.
            await interaction.followup.send(part, ephemeral=in_place(interaction))

    def remember_task(self, interaction, detail):
        key = (interaction.guild_id, interaction.channel_id, interaction.user.id, detail["task"]["id"])
        self.task_details[key] = detail
        if len(self.task_details) > 512:
            oldest = next(iter(self.task_details))
            del self.task_details[oldest]
            self.task_cards.pop(oldest, None)

    async def show_task(self, interaction, detail, *, notice=None, update=False, new=False):
        self.remember_task(interaction, detail)
        task = detail["task"]
        embed = ui.card(task, detail=detail)
        view = task_view(task["id"], detail["fingerprint"], task.get("status"))
        content = display_text(notice)[:1800] if notice else None
        key = (interaction.guild_id, interaction.channel_id, interaction.user.id, task["id"])
        if in_place(interaction) and not new:
            # The clicked message (list, card or picker) becomes the card.
            self.task_cards[key] = await interaction.edit_original_response(content=content, embed=embed, view=view)
            return
        source = getattr(interaction, "message", None)
        if not (source and len(source.embeds) == 1 and source.embeds[0].url == ui.task_url(task["id"])):
            source = self.task_cards.get(key)
        if update and source and not new:
            try:
                await source.edit(content=content, embed=embed, view=view)
            except discord.HTTPException:
                # Deleted, or the interaction token that posted it expired.
                self.task_cards.pop(key, None)
                await self.show_task(interaction, detail, notice=notice)
                return
            self.task_cards[key] = source
            await interaction.followup.send("U përditësua në PrimeFlow dhe në kartë.", ephemeral=True)
        else:
            self.task_cards[key] = await interaction.followup.send(content or discord.utils.MISSING, embed=embed, view=view, wait=True)

    async def show_list(self, interaction, task_list, *, page=0, notice=None, title="📋 Detyrat e tua për sot"):
        content, view = ui.list_view(task_list, title, page)
        if notice:
            content = display_text(notice)[:300] + "\n\n" + content
        await interaction.edit_original_response(content=content[:2000], embed=None, view=view)

    async def today(self, interaction):
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        return (await self.bridge("/bot/tasks", actor(interaction.user.id, interaction.guild_id, interaction.channel_id)))["tasks"]

    async def select(self, interaction, task_id):
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        return await self.bridge("/bot/select", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": task_id})

    async def apply(self, interaction, task_id, fingerprint, actions, instruction, request_id=None):
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        return await self.bridge("/bot/command", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id),
            "request_id": request_id or str(interaction.id), "task_id": task_id, "instruction": instruction,
            "expected_fingerprint": fingerprint, "direct_actions": actions})

    async def run_direct(self, interaction, task_id, fingerprint, actions, instruction):
        try:
            closing = any(item["tool"] == "update_task" and json.loads(item["arguments_json"]).get("status") == "DONE" for item in actions)
            # Remember the order first: a closed task leaves the list.
            order = [task["id"] for task in await self.today(interaction)] if closing and in_place(interaction) else None
            result = await self.apply(interaction, task_id, fingerprint, actions, instruction)
            if order is not None:
                if result.get("status") == "DONE":
                    await self.advance(interaction, task_id, order, "✅ U mbyll: " + ui.label(ui.heading(result.get("task") or {}), 80))
                else:
                    detail = await self.select(interaction, task_id)
                    await self.show_task(interaction, detail, notice="⚠ " + result["message"][:900]
                        + "\nPërdor **Më shumë → 📝 Mbylle me koment** ose **👤 Dërgo për konfirmim**.")
                return
            if result.get("status") == "DONE" and result.get("task") and (getattr(interaction, "data", None) or {}).get("custom_id", "").startswith("pf:pointset:"):
                picker = ui.points_view(result)
                if in_place(interaction):
                    self.remember_task(interaction, result)
                    await interaction.edit_original_response(content="✓ " + result["message"][:300] + "\nZgjidh pika të tjera ose kliko **← Kthehu**.",
                        embed=ui.card(result["task"], detail=result), view=picker)
                    return
                try:
                    await interaction.message.edit(content="Zgjidh pikat për strike / heqje strike:", view=picker)
                except discord.HTTPException:
                    log.warning("Could not refresh the strike picker after a saved change")
            if in_place(interaction) and not result.get("task"):
                # Keep the user on the card: show why nothing changed there.
                detail = await self.select(interaction, task_id)
                await self.show_task(interaction, detail, notice="⚠ " + result["message"][:900])
                return
            await self.show_result(interaction, result)
        except Exception as exc:
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    async def advance(self, interaction, task_id, order, notice):
        """After closing a task, open the next one in the same message."""
        remaining = await self.today(interaction)
        ids = {task["id"] for task in remaining}
        following = order[order.index(task_id) + 1:] if task_id in order else []
        upcoming = next((item for item in following + order if item in ids), None)
        if upcoming is None:
            await self.show_list(interaction, remaining, notice=notice)
            return
        detail = await self.select(interaction, upcoming)
        await self.show_task(interaction, detail, notice=notice + "\nDetyra tjetër:")

    async def current_detail(self, interaction, task_id, fingerprint=None):
        detail = await self.select(interaction, task_id)
        if fingerprint and detail["fingerprint"] != fingerprint:
            await self.show_task(interaction, detail, notice="🔄 Detyra ishte ndryshuar në PrimeFlow. Ky është versioni i fundit; provo përsëri.", update=True)
            return None
        self.remember_task(interaction, detail)
        return detail

    async def show_people(self, interaction, task_id, fingerprint, page=0):
        # The picker carries the fresh version, so an older card never blocks it.
        fingerprint = (await self.current_detail(interaction, task_id))["fingerprint"]
        result = await self.bridge("/bot/people", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": task_id})
        view = ui.people_view(result["people"], task_id, fingerprint, page)
        if in_place(interaction):
            await interaction.edit_original_response(content="Zgjidh personin e konfirmimit:", view=view)
        else:
            await interaction.followup.send("Zgjidh personin e konfirmimit:", view=view)

    async def ack(self, interaction):
        """Clicks edit their own message; slash commands get a reply."""
        if interaction.type in (discord.InteractionType.component, discord.InteractionType.modal_submit) and getattr(interaction, "message", None) is not None:
            await interaction.response.defer()
        else:
            await interaction.response.defer(thinking=True)

    async def open_edit(self, interaction, task_id, fingerprint):
        # A modal must be the first response, so the fresh version is read
        # quickly instead of asking the user to refresh first.
        key = (interaction.guild_id, interaction.channel_id, interaction.user.id, task_id)
        detail = self.task_details.get(key)
        if not detail or detail["fingerprint"] != fingerprint:
            try:
                detail = await asyncio.wait_for(self.bridge("/bot/select", {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "task_id": task_id}), 2.2)
                self.remember_task(interaction, detail)
            except Exception:
                detail = None
        if detail:
            await interaction.response.send_modal(ui.EditModal(self, detail))
        else:
            await interaction.response.send_message("PrimeFlow u vonua. Kliko **Edito** përsëri.", ephemeral=True)

    async def quick(self, interaction, task_id, fingerprint, action):
        if action in {"comment", "done_comment"}:
            await interaction.response.send_modal(ui.CommentModal(self, task_id, fingerprint, complete=action == "done_comment"))
        elif action == "edit":
            await self.open_edit(interaction, task_id, fingerprint)
        elif action == "ai":
            await interaction.response.send_modal(InstructionModal(self, task_id, 0, fingerprint))
        elif action in {"agent", "history"}:
            await agent_client.handle_agent_interaction(self, interaction,
                f"pf:agent:targets:{task_id}:{fingerprint}" if action == "agent" else f"pf:agent:history:{task_id}:0")
        else:
            await self.ack(interaction)
            if action in ui.STATUS_ACTIONS or action == "done":
                # A status change does not depend on the text shown, so a card
                # that is a little out of date must not refuse it.
                fingerprint = (await self.current_detail(interaction, task_id))["fingerprint"]
            if action in ui.STATUS_ACTIONS:
                status = ui.STATUS_ACTIONS[action]
                await self.run_direct(interaction, task_id, fingerprint, [ui.action("update_task", {"status": status})], "Ndrysho statusin në " + status)
            elif action == "done":
                await self.run_direct(interaction, task_id, fingerprint, [ui.action("update_task", {"status": "DONE"})], "Mbylle detyrën.")
            elif action == "confirm":
                await self.show_people(interaction, task_id, fingerprint)
            elif action in {"points", "schedule", "refresh", "full"}:
                detail = await self.current_detail(interaction, task_id)
                if action == "refresh":
                    await self.show_task(interaction, detail, update=True)
                elif action == "full":
                    for part in chunks(ui.full_text(detail["task"], detail)):
                        await interaction.followup.send(part, ephemeral=True)
                elif action == "points":
                    view = ui.points_view(detail)
                    if len(view.children) == 1:
                        await interaction.followup.send("Kjo detyrë nuk ka pika për shënim.", ephemeral=True)
                    elif in_place(interaction):
                        await interaction.edit_original_response(content="Zgjidh një ose disa pika për strike / heqje strike:",
                            embed=ui.card(detail["task"], detail=detail), view=view)
                    else:
                        await interaction.followup.send("Zgjidh një ose disa pika për strike / heqje strike.", view=view)
                else:
                    text = "Ndrysho slotin ose AM/PM. Slotet ndjekin datën efektive të PrimeFlow."
                    if in_place(interaction):
                        await interaction.edit_original_response(content=text, view=ui.schedule_view(task_id, detail["fingerprint"]))
                    else:
                        await interaction.followup.send(text, view=ui.schedule_view(task_id, detail["fingerprint"]))
            else:
                raise ValueError("Veprim i panjohur.")

    async def navigate(self, interaction, task_id, direction):
        task_list = await self.today(interaction)
        ids = [task["id"] for task in task_list]
        if direction == "list" or not ids:
            page = ids.index(task_id) // ui.LIST_PER_PAGE if task_id in ids else 0
            await self.show_list(interaction, task_list, page=page)
            return
        if direction not in {"prev", "next"}:
            raise ValueError("Navigim i pavlefshëm.")
        position = (ids.index(task_id) + (1 if direction == "next" else -1)) % len(ids) if task_id in ids else 0
        await self.show_task(interaction, await self.select(interaction, ids[position]), notice=f"Detyra {position + 1}/{len(ids)}")

    async def report(self, interaction, reminder_hex, task_hex, state, action):
        """One reminder message walks through the slot's tasks, one click each."""
        identity = actor(interaction.user.id, interaction.guild_id, interaction.channel_id)
        reminder_id = str(uuid.UUID(reminder_hex))
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        data = await self.bridge(f"/bot/reminders/{reminder_id}/tasks", identity)
        task_list, bucket = data["tasks"], data["bucket"]
        counts = [int(value) for value in state.split(".")]
        if len(counts) != 4 or action not in {"go", "done", "cont", "wfe", "skip"}:
            raise ValueError("Raportim i pavlefshëm.")
        ids = [task["id"] for task in task_list]
        if action == "go":
            following = 0
        else:
            task_id = str(uuid.UUID(task_hex))
            if task_id not in ids:
                following = 0  # Closed elsewhere meanwhile; continue with what is still open.
            else:
                position = ids.index(task_id)
                status = {"done": "DONE", "cont": "IN_PROGRESS", "wfe": "WAITING_CLIENT"}.get(action)
                if status and task_list[position].get("status") != status:
                    detail = await self.select(interaction, task_id)
                    result = await self.apply(interaction, task_id, detail["fingerprint"], [ui.action("update_task", {"status": status})],
                        f"Raportimi {bucket}: {status}")
                    if result.get("status") != "DONE":
                        await interaction.followup.send(f"⚠ {result['message'][:1500]}\nKliko **📂 Hap detyrën** për koment ose konfirmim.", ephemeral=True)
                        return
                counts[["done", "cont", "wfe", "skip"].index(action)] += 1
                following = position + 1
        if following >= len(task_list):
            await interaction.edit_original_response(content=ui.report_summary(bucket, counts), embed=None,
                view=discord.ui.View(timeout=None).add_item(discord.ui.Button(label="📋 Detyrat e mia", custom_id="pf:list:0")))
            return
        done = sum(counts)
        content, embed, view = ui.report_step(bucket, task_list[following], reminder_id, counts, done + 1, done + len(task_list) - following)
        await interaction.edit_original_response(content=content, embed=embed, view=view)

    async def report_done(self, interaction, reminder_hex, values):
        identity = actor(interaction.user.id, interaction.guild_id, interaction.channel_id)
        reminder_id = str(uuid.UUID(reminder_hex))
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        data = await self.bridge(f"/bot/reminders/{reminder_id}/tasks", identity)
        titles = {task["id"]: ui.label(ui.heading(task), 60) for task in data["tasks"]}
        closed, refused = 0, []
        for index, task_id in enumerate(values):
            if task_id not in titles:
                continue
            detail = await self.select(interaction, task_id)
            result = await self.apply(interaction, task_id, detail["fingerprint"], [ui.action("update_task", {"status": "DONE"})],
                f"Raportimi {data['bucket']}: DONE", request_id=f"{interaction.id}{index:02d}")
            if result.get("status") == "DONE":
                closed += 1
            else:
                refused.append(f"⚠ {titles[task_id]}: {result['message'][:200]}")
        notice = "\n".join([f"✅ U mbyllën {closed}"] + refused)
        remaining = (await self.bridge(f"/bot/reminders/{reminder_id}/tasks", identity))["tasks"]
        if remaining:
            content, view = ui.report_intro(data["bucket"], remaining, reminder_id, notice=notice,
                join_url=self.one_h_url(data["bucket"], interaction.guild_id))
            await interaction.edit_original_response(content=content, embed=None, view=view)
        else:
            await interaction.edit_original_response(content=notice + "\n" + ui.report_summary(data["bucket"], [closed, 0, 0, 0]), embed=None,
                view=discord.ui.View(timeout=None).add_item(discord.ui.Button(label="📋 Detyrat e mia", custom_id="pf:list:0")))

    async def decide_meeting(self, interaction, draft_id, decision):
        """Create or cancel a meeting drafted from chat; the card turns into the outcome."""
        if decision not in {"ok", "force", "no"}:
            raise ValueError("Veprim i panjohur.")
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        identity = actor(interaction.user.id, interaction.guild_id, interaction.channel_id)
        if decision == "no":
            result = await self.bridge(f"/bot/meeting-drafts/{draft_id}/cancel", identity)
        else:
            result = await self.bridge(f"/bot/meeting-drafts/{draft_id}/confirm", {**identity, "force": decision == "force"})
        if result["status"] == "DONE":
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Hap në PrimeFlow", url=result["url"]))
            await interaction.edit_original_response(content="✅ " + result["message"], view=view)
        elif result["status"] == "CANCELLED":
            await interaction.edit_original_response(content="✖ " + result["message"], view=None)
        elif result["status"] == "CONFLICT":
            zone = ZoneInfo(settings.APP_TIMEZONE)
            lines = [f"• {ui.label(item.get('title'), 80)} · "
                     f"{datetime.fromisoformat(item['starts_at']).astimezone(zone).strftime('%H:%M')}–"
                     f"{datetime.fromisoformat(item['ends_at']).astimezone(zone).strftime('%H:%M')}"
                     for item in result.get("conflicts") or [] if item.get("starts_at") and item.get("ends_at")]
            await interaction.edit_original_response(content="⚠ " + result["message"] + "\n" + "\n".join(lines),
                view=ui.meeting_draft_view(draft_id, conflict=True))
        else:
            await interaction.followup.send("⚠ " + result["message"], ephemeral=True)

    async def meeting_held(self, interaction, alert_id, status):
        """Mbajtur / Anuluar: saved once, and every participant's question shows the answer."""
        await self.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        result = await self.bridge(f"/bot/meetings/{alert_id}/status",
                                   {**actor(interaction.user.id, interaction.guild_id, interaction.channel_id), "status": status})
        embeds = interaction.message.embeds if interaction.message else []
        title = embeds[0].title if embeds and embeds[0].title else "Takimi"
        text = ui.meeting_held_text(title, result["status"], result["by"])
        await interaction.edit_original_response(content=text, view=None)
        for other in result.get("others") or []:
            try:
                channel = self.get_channel(int(other["channel_id"])) or await self.fetch_channel(int(other["channel_id"]))
                await channel.get_partial_message(int(other["message_id"])).edit(content=text, view=None)
            except (discord.HTTPException, ValueError):
                log.warning("Could not update meeting question %s", other["message_id"])

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        data = interaction.data or {}
        custom_id = data.get("custom_id", "")
        if not custom_id.startswith("pf:"):
            return
        try:
            if custom_id.startswith("pf:vm:"):
                await voice_meetings.handle_meeting_interaction(self, interaction)
            elif custom_id.startswith("pf:agent:"):
                await agent_client.handle_agent_interaction(self, interaction)
            elif custom_id.startswith("pf:quick:"):
                _, _, task_id, fingerprint, action = custom_id.split(":")
                await self.quick(interaction, task_id, fingerprint, action)
            elif custom_id.startswith("pf:more:"):
                _, _, task_id, fingerprint = custom_id.split(":")
                await self.quick(interaction, task_id, fingerprint, data["values"][0])
            elif custom_id.startswith("pf:open:") or custom_id == "pf:task":
                parts = custom_id.split(":")
                task_id = data["values"][0] if custom_id == "pf:task" else parts[2]
                await self.ack(interaction)
                await self.show_task(interaction, await self.select(interaction, task_id), new=parts[-1] == "new")
            elif custom_id.startswith("pf:back:"):
                await self.ack(interaction)
                await self.show_task(interaction, await self.select(interaction, custom_id.split(":")[2]))
            elif custom_id.startswith("pf:nav:"):
                _, _, task_id, direction = custom_id.split(":")
                await self.ack(interaction)
                await self.navigate(interaction, task_id, direction)
            elif custom_id.startswith("pf:list:"):
                await self.ack(interaction)
                await self.show_list(interaction, await self.today(interaction), page=int(custom_id.split(":")[2]))
            elif custom_id.startswith("pf:rep:"):
                _, _, reminder_hex, task_hex, state, action = custom_id.split(":")
                await self.ack(interaction)
                await self.report(interaction, reminder_hex, task_hex, state, action)
            elif custom_id.startswith("pf:mtg:"):
                _, _, draft_id, decision = custom_id.split(":")
                await self.ack(interaction)
                await self.decide_meeting(interaction, draft_id, decision)
            elif custom_id.startswith("pf:mheld:"):
                _, _, alert_id, status = custom_id.split(":")
                await self.ack(interaction)
                await self.meeting_held(interaction, alert_id, status)
            elif custom_id.startswith("pf:repdone:"):
                await self.ack(interaction)
                await self.report_done(interaction, custom_id.split(":")[2], data["values"])
            elif custom_id.startswith("pf:pointset:"):
                _, _, task_id, fingerprint, field, done = custom_id.split(":")
                if field not in {"t", "d"} or done not in {"0", "1"}:
                    raise ValueError("Përzgjedhje e pavlefshme.")
                await self.ack(interaction)
                numbers = [int(number) for number in data["values"]]
                await self.run_direct(interaction, task_id, fingerprint,
                    [ui.action("set_points", {"field": "title" if field == "t" else "description", "numbers": numbers, "done": done == "1"})],
                    ("Bëj strike" if done == "1" else "Hiq strike") + " pikat " + ", ".join(map(str, numbers)))
            elif custom_id.startswith("pf:points:"):
                _, _, task_id, fingerprint, page = custom_id.split(":")
                await self.ack(interaction)
                detail = await self.current_detail(interaction, task_id)
                view = ui.points_view(detail, max(0, int(page)))
                if in_place(interaction):
                    await interaction.edit_original_response(embed=ui.card(detail["task"], detail=detail), view=view)
                else:
                    await interaction.followup.send("Zgjidh pikat:", view=view)
            elif custom_id.startswith("pf:schedule:"):
                _, _, task_id, fingerprint = custom_id.split(":")
                await self.ack(interaction)
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
                await self.ack(interaction)
                await self.run_direct(interaction, task_id, fingerprint,
                    [ui.action("update_task", {"confirmation_assignee_id": data["values"][0], "status": "WAITING_CONFIRMATION"})], "Dërgoje për konfirmim te personi i zgjedhur.")
            elif custom_id.startswith("pf:people:"):
                _, _, task_id, fingerprint, page = custom_id.split(":")
                await self.ack(interaction)
                await self.show_people(interaction, task_id, fingerprint, max(0, int(page)))
            elif custom_id.startswith("pf:action:"):
                # Cards posted before the simplified layout keep working.
                index = int(data["values"][0])
                if index < 0 or index >= len(ACTION_CHOICES):
                    raise ValueError("Veprim i panjohur.")
                parts = custom_id.split(":")
                await interaction.response.send_modal(InstructionModal(self, parts[2], index, parts[3] if len(parts) > 3 else ""))
        except Exception as exc:
            if interaction.response.is_done():
                await interaction.followup.send(self.error_message(exc), ephemeral=True)
            else:
                await interaction.response.send_message(self.error_message(exc), ephemeral=True)

    async def context_task_ids(self, message) -> list[str]:
        """Tasks the person is looking at: the bot message they replied to,
        otherwise the latest bot list, card or reminder in the channel."""
        try:
            reference = getattr(message, "reference", None)
            if reference and reference.message_id:
                source = reference.resolved if isinstance(reference.resolved, discord.Message) else await message.channel.fetch_message(reference.message_id)
                if source.author.id == self.user.id:
                    return task_ids_in(source)
            async for item in message.channel.history(limit=15, before=message):
                if item.author.id == self.user.id and (ids := task_ids_in(item)):
                    return ids
        except discord.HTTPException:
            log.warning("Could not read recent messages for task context")
        return []

    async def on_message(self, message: discord.Message):
        if not settings.DISCORD_MESSAGE_CONTENT_ENABLED or message.author.bot or not message.guild or not message.content.strip():
            return
        if str(message.guild.id) != settings.DISCORD_GUILD_ID or getattr(message.channel, "topic", None) != f"PrimeFlow personal workspace: {message.author.id}":
            return
        try:
            channel = await self.private_channel(message.guild.id, message.channel.id, message.author.id)
            async with channel.typing():
                result = await self.bridge("/bot/command", {**actor(message.author.id, message.guild.id, channel.id),
                    "request_id": str(message.id), "instruction": message.content[:4000],
                    "context_task_ids": await self.context_task_ids(message)})
            if result.get("status") == "MEETING_DRAFT":
                await channel.send(result["message"], embed=ui.meeting_draft_card(result["meeting"]),
                    view=ui.meeting_draft_view(result["draft_id"]))
                return
            text = result["message"]
            if result.get("applied"):
                text += "\nU zbatuan: " + "; ".join(result["applied"])
            if result.get("task") and result.get("fingerprint"):
                # Show the result as the task card, so strikes and status are visible at once.
                await channel.send((("✓ " if result.get("status") == "DONE" else "⚠ ") + text)[:1800], embed=ui.card(result["task"], detail=result),
                    view=task_view(result["task"]["id"], result["fingerprint"], result["task"].get("status")))
                return
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
                        if job.get("previous"):
                            await self.retire_reminder(channel, job["previous"])
                        if data["tasks"]:
                            text, view = ui.report_intro(job["bucket"], data["tasks"], job["id"], job["discord_user_id"],
                                join_url=self.one_h_url(job["bucket"], job["guild_id"]))
                            # Discord deduplicates the same nonce on a retried
                            # send. The key survives worker/API restarts.
                            nonce = hashlib.sha256(f"{job['id']}:0".encode()).hexdigest()[:24]
                            message = await self.http.request(discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
                                json={"content": text, "components": view.to_components(),
                                    "allowed_mentions": {"parse": [], "users": [job["discord_user_id"]]}, "nonce": nonce, "enforce_nonce": True})
                            message_ids.append(str(message["id"]))
                        await self.bridge(f"/bot/reminders/{job['id']}/ack", {**identity, "message_ids": message_ids})
                    except Exception as exc:
                        log.warning("Reminder %s failed: %s", job["id"], type(exc).__name__)
            await asyncio.gather(*(deliver(job) for job in jobs))
        except Exception as exc:
            log.warning("Reminder polling failed: %s", type(exc).__name__)

    @staticmethod
    def one_h_url(bucket, guild_id) -> str | None:
        """Slot reminders (not AM/PM) call the people with 1H tasks into the 1H meeting."""
        channel_id = settings.DISCORD_1H_VOICE_CHANNEL_ID
        if bucket in {"AM", "PM"} or not channel_id:
            return None
        return f"https://discord.com/channels/{guild_id}/{channel_id}"

    def voice_url(self, guild_id) -> str | None:
        """The configured meeting voice room, otherwise the server's first voice channel."""
        guild = self.get_guild(int(guild_id))
        channel_id = settings.DISCORD_MEETING_VOICE_CHANNEL_ID
        if not channel_id and guild and guild.voice_channels:
            channel_id = guild.voice_channels[0].id
        return f"https://discord.com/channels/{guild_id}/{channel_id}" if channel_id else None

    @tasks.loop(seconds=30)
    async def meeting_alerts(self):
        try:
            jobs = (await self.bridge("/bot/meetings/claim", {}))["jobs"]
            for job in jobs:
                try:
                    channel = await self.private_channel(job["guild_id"], job["channel_id"], job["discord_user_id"])
                    content, embed, view = ui.meeting_alert(job, self.voice_url(job["guild_id"]))
                    nonce = hashlib.sha256(f"meeting:{job['id']}".encode()).hexdigest()[:24]
                    # The mention is what makes Discord ring the phone/desktop.
                    message = await self.http.request(discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
                        json={"content": content, "embeds": [embed.to_dict()], "components": view.to_components(),
                            "allowed_mentions": {"parse": [], "users": [job["discord_user_id"]]}, "nonce": nonce, "enforce_nonce": True})
                    identity = {key: job[key] for key in ("discord_user_id", "guild_id", "channel_id")}
                    await self.bridge(f"/bot/meetings/{job['id']}/ack", {**identity, "message_id": str(message["id"])})
                except Exception as exc:
                    log.warning("Meeting alert %s failed: %s", job["id"], type(exc).__name__)
        except Exception as exc:
            log.warning("Meeting alert polling failed: %s", type(exc).__name__)

    @meeting_alerts.before_loop
    async def before_meeting_alerts(self):
        await self.wait_until_ready()

    async def retire_reminder(self, channel, previous):
        """An unanswered earlier report stops offering buttons once the next one arrives."""
        for message_id in previous.get("message_ids") or []:
            try:
                message = await channel.fetch_message(int(message_id))
                if message.author.id == self.user.id and message.components:
                    await message.edit(content=f"⚠ **{ui.bucket_name(previous['bucket'])}** mbeti pa raportuar. Detyrat i gjen te /detyrat.",
                        embed=None, view=None)
            except (discord.HTTPException, ValueError):
                log.warning("Could not retire reminder message %s", message_id)

    @reminders.before_loop
    async def before_reminders(self):
        await self.wait_until_ready()

    async def on_socket_raw_receive(self, payload):
        # discord.py 2.x emits this hook after decompressing the Gateway JSON.
        # The old socket_response event is not emitted by supported versions.
        if not settings.DISCORD_MEETING_NOTES_ENABLED:
            return
        try:
            event = json.loads(payload)
        except (TypeError, ValueError):
            return
        if (isinstance(event, dict) and event.get("op") == 0
                and event.get("t") in ("VOICE_STATE_UPDATE", "VOICE_SERVER_UPDATE")
                and isinstance(event.get("d"), dict)):
            await self.meeting_capture.gateway(event)

    async def on_disconnect(self):
        if settings.DISCORD_MEETING_NOTES_ENABLED:
            await self.meeting_capture.interrupt("gateway_disconnected")

    @tasks.loop(seconds=15)
    async def voice_meeting_results(self):
        try:
            await voice_meetings.deliver_meeting_results(self)
        except Exception:
            log.warning("Mira meeting result delivery unavailable")

    @voice_meeting_results.before_loop
    async def before_voice_meeting_results(self):
        await self.wait_until_ready()

    async def close(self):
        self.voice_meeting_results.cancel()
        await self.meeting_capture.close()
        self.clear_ready_status()
        self.reminders.cancel()
        self.meeting_alerts.cancel()
        self.agent_results.cancel()
        await self.http_bridge.aclose()
        await super().close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not all((settings.DISCORD_ASSISTANT_ENABLED, settings.DISCORD_BOT_TOKEN, settings.DISCORD_BRIDGE_SECRET, settings.DISCORD_GUILD_ID)):
        raise SystemExit("Configure DISCORD_ASSISTANT_ENABLED, DISCORD_BOT_TOKEN, DISCORD_BRIDGE_SECRET and DISCORD_GUILD_ID first.")
    PrimeFlowBot().run(settings.DISCORD_BOT_TOKEN, log_handler=None)
