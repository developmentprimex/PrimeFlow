"""Install beside Kujtesa's existing script. PrimeFlow is the only task store.

No Discord requests occur on import or --check. The Discord token is read only
by main() and remains in this bot's .env, never sent to PrimeFlow.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import tasks

LOG = logging.getLogger("kujtesa.primeflow")
ZONE = ZoneInfo("Europe/Belgrade")
STATE = Path(__file__).resolve().with_name(".primeflow-receipts.json")
LABELS = {"pending": "Për t’u bërë", "acknowledged": "E pashë", "in_progress": "Po ia nisi",
          "done": "U kry", "needs_help": "Më duhet ndihmë", "rescheduled": "E shtyrë", "cancelled": "E anuluar"}


class BridgeError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class DeliveryFailure(Exception):
    pass


class ReceiptStore:
    """Only delivery receipts, never a second task database. Atomic local writes."""
    def __init__(self, path=STATE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def pending(self):
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, value):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(self.path)

    def put(self, key, value):
        data = self.pending(); data[key] = value; self.write(data)

    def remove(self, key):
        data = self.pending(); data.pop(key, None); self.write(data)


def card_text(card):
    if card.get("removed"):
        return "Kjo kujtesë ka ndryshuar. Shiko detyrën e përditësuar në PrimeFlow."
    when = datetime.fromisoformat(card["due_at"]).astimezone(ZONE).strftime("%d/%m · %H:%M") if card.get("due_at") else "Pa orar"
    who = ", ".join(card.get("names", []))
    hint = {"before": "Edhe 5 minuta deri te detyra.", "due": "Është koha për këtë detyrë.",
            "after": "A u kry? Konfirmo kur ta kesh përfunduar."}.get(card.get("phase"), "")
    title = discord.utils.escape_markdown(card.get("title", "Detyra"))
    return f"{who}\n**{title}**\n{when}\n{LABELS.get(card.get('status'), '')}\n{hint}"[:2000]


def card_view(card):
    view = discord.ui.View(timeout=None)
    disabled = card.get("removed") or card.get("status") in {"done", "cancelled"}
    buttons = [("acknowledged", "E pashë", discord.ButtonStyle.secondary),
               ("in_progress", "Po ia nisi", discord.ButtonStyle.primary),
               ("done", "U kry", discord.ButtonStyle.success),
               ("needs_help", "Më duhet ndihmë", discord.ButtonStyle.secondary)]
    for action, label, style in buttons:
        view.add_item(discord.ui.Button(label=label, style=style, custom_id=f"gap:{card['id']}:{action}", disabled=bool(disabled)))
    menu = discord.ui.Select(custom_id=f"gap:{card['id']}:menu", placeholder="Hapat ose më duhet kohë", disabled=bool(disabled), options=[
        discord.SelectOption(label="Hapat / Si bëhet?", value="steps"),
        discord.SelectOption(label="Më duhet kohë · 15 minuta", value="later15"),
        discord.SelectOption(label="Më duhet kohë · 30 minuta", value="later30"),
        discord.SelectOption(label="Më duhet kohë · 1 orë", value="later60"),
    ])
    view.add_item(menu)
    return view


class KujtesaBridge(discord.Client):
    def __init__(self, base_url, bridge_key, *, reminders_enabled=False, receipt_path=STATE, status_path=None):
        super().__init__(intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.none())
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Use HTTPS for remote PrimeFlow, or HTTP only on localhost.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("PrimeFlow URL must not contain credentials, query or fragment.")
        self.base_url = base_url.rstrip("/") + "/ga-personal/bridge"
        self.bridge_key = bridge_key
        self.reminders_enabled = reminders_enabled
        self.receipts = ReceiptStore(receipt_path)
        self.http_session = None
        self.allowed_user_ids = set()
        self.status_path = Path(status_path) if status_path else None
        self.expected_guild_id = None

    async def api(self, path, body):
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        async with self.http_session.post(self.base_url + path, json=body,
            headers={"X-GA-Bridge-Key": self.bridge_key}, allow_redirects=False) as response:
            data = await response.json()
            if response.status >= 300:
                raise BridgeError(response.status, data.get("detail", "Lidhja me PrimeFlow dështoi."))
            return data

    async def setup_hook(self):
        health = await self.api("/poll", {"delivery_enabled": False, "health_only": True})
        self.expected_guild_id = health.get("guild_id")
        if not self.expected_guild_id:
            raise BridgeError(409, "Configure the Kujtesa Discord server in GA PERSONAL settings first.")
        self.worker.start()

    def clear_ready_status(self):
        if not self.status_path:
            return
        try:
            if json.loads(self.status_path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                self.status_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def publish_ready_status(self):
        if not self.status_path or not self.expected_guild_id or not self.is_ready() or not self.get_guild(int(self.expected_guild_id)):
            self.clear_ready_status()
            return
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        status = {"pid": os.getpid(), "build": os.environ.get("APP_BUILD_SHA", "unknown"),
                  "guild_id": self.expected_guild_id, "last_seen_at": datetime.now(timezone.utc).isoformat(),
                  "reminders_enabled": self.reminders_enabled}
        temporary = self.status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(status), encoding="utf-8")
        temporary.replace(self.status_path)

    async def on_ready(self):
        if not self.get_guild(int(self.expected_guild_id)):
            LOG.error("Kujtesa is not installed in the configured Discord server")
            await self.close()

    async def on_disconnect(self):
        self.clear_ready_status()

    async def close(self):
        self.clear_ready_status()
        self.worker.cancel()
        if self.http_session:
            await self.http_session.close()
        await super().close()

    @tasks.loop(seconds=15)
    async def worker(self):
        try:
            await self.tick()
        except Exception as error:
            # Do not print tokens, request payloads or family task content.
            LOG.warning("PrimeFlow needs a retry (%s)", type(error).__name__)
            self.clear_ready_status()

    @worker.before_loop
    async def before_worker(self):
        await self.wait_until_ready()

    async def record(self, delivery_id, body):
        self.receipts.put(delivery_id, body)
        await self.flush_receipts()

    async def flush_receipts(self):
        for delivery_id, body in self.receipts.pending().items():
            try:
                await self.api(f"/deliveries/{delivery_id}/result", body)
                self.receipts.remove(delivery_id)
            except BridgeError as error:
                if error.status not in {404, 409}:
                    raise
                # Keep a visible failed receipt for operator inspection.
                LOG.warning("Delivery receipt needs review (%s)", error.status)

    async def tick(self):
        if self.reminders_enabled:
            await self.flush_receipts()
        batch = await self.api("/poll", {"delivery_enabled": self.reminders_enabled})
        self.publish_ready_status()
        if not self.reminders_enabled or not batch.get("enabled"):
            return
        self.allowed_user_ids = set(batch.get("allowed_user_ids", []))
        for card in batch.get("deliveries", []):
            await self.deliver(card)
        for card in batch.get("updates", []):
            try:
                channel = await self.destination(card, editing=True)
                message = channel.get_partial_message(int(card["message_id"]))
                await message.edit(content=card_text(card), view=card_view(card), allowed_mentions=discord.AllowedMentions.none())
                await self.api(f"/deliveries/{card['id']}/sync", {"channel_id": card["channel_id"],
                    "message_id": card["message_id"], "sync_key": card["sync_key"]})
            except (discord.HTTPException, DeliveryFailure) as error:
                LOG.warning("A reminder card could not be refreshed")
                failure = "not_found" if isinstance(error, discord.NotFound) else "permissions" if isinstance(error, (discord.Forbidden, DeliveryFailure)) else "network"
                await self.api(f"/deliveries/{card['id']}/sync", {"channel_id": card["channel_id"],
                    "message_id": card["message_id"], "sync_key": card["sync_key"], "error": failure})

    async def destination(self, card, *, editing=False):
        guild = self.get_guild(int(card["guild_id"]))
        if guild is None:
            raise DeliveryFailure("permissions")
        target = card["target"]
        if target["kind"] == "dm":
            uid = int(target["user_id"])
            if str(uid) not in self.allowed_user_ids and not (editing and card.get("removed")):
                raise DeliveryFailure("permissions")
            try:
                member = await guild.fetch_member(uid)
                channel = await member.create_dm()
            except discord.Forbidden:
                raise DeliveryFailure("blocked_dm")
            if editing and str(channel.id) != card["channel_id"]:
                raise DeliveryFailure("permissions")
            return channel
        channel = self.get_channel(int(target["channel_id"])) or await self.fetch_channel(int(target["channel_id"]))
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
            raise DeliveryFailure("permissions")
        if channel.permissions_for(guild.default_role).view_channel:
            raise DeliveryFailure("permissions")
        for principal, overwrite in channel.overwrites.items():
            if overwrite.view_channel is not True:
                continue
            if isinstance(principal, discord.Role):
                if not principal.managed or not principal.tags or principal.tags.bot_id != self.user.id:
                    raise DeliveryFailure("permissions")
            elif principal.id != self.user.id and str(principal.id) not in self.allowed_user_ids:
                raise DeliveryFailure("permissions")
        return channel

    async def deliver(self, original):
        delivery_id, lease = original["id"], original["lease"]
        try:
            card = await self.api(f"/deliveries/{delivery_id}/prepare", {"lease": lease})
        except BridgeError as error:
            if error.status in {403, 404, 409}:
                return
            raise
        report = {"lease": lease}
        if "allowed_user_ids" in card:
            self.allowed_user_ids = set(card["allowed_user_ids"])
        try:
            channel = await self.destination(card)
            # Persist uncertainty before the network send. A crash never causes
            # an automatic replay of a potentially delivered private message.
            self.receipts.put(delivery_id, {**report, "outcome": "uncertain", "error": "network"})
            message = await channel.send(content=card_text(card), view=card_view(card),
                allowed_mentions=discord.AllowedMentions.none(), nonce=int(delivery_id.replace("-", "")[:15], 16))
            report.update(outcome="sent", channel_id=str(channel.id), message_id=str(message.id), sync_key=card["sync_key"])
        except DeliveryFailure as error:
            report.update(outcome="failed", error=str(error))
        except discord.Forbidden:
            report.update(outcome="failed", error="blocked_dm" if card["target"]["kind"] == "dm" else "permissions")
        except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
            report.update(outcome="uncertain", error="network")
        await self.record(delivery_id, report)

    async def on_interaction(self, interaction):
        if interaction.type is not discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith("gap:"):
            return
        pieces = custom_id.split(":")
        if len(pieces) != 3 or not interaction.message:
            return
        _, delivery_id, action = pieces
        if action == "menu":
            action = (interaction.data.get("values") or [""])[0]
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.flush_receipts()
            result = await self.api(f"/deliveries/{delivery_id}/action", {
                "actor_id": str(interaction.user.id), "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "channel_id": str(interaction.channel_id), "message_id": str(interaction.message.id),
                "interaction_id": str(interaction.id), "action": action,
            })
            if action == "steps":
                body = result.get("description", "") + "\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(result.get("steps", []), 1))
                await interaction.followup.send(body.strip()[:1900] or "Ende pa hapa të shkruar.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            else:
                card = result["card"]
                await interaction.message.edit(content=card_text(card), view=card_view(card), allowed_mentions=discord.AllowedMentions.none())
                await interaction.followup.send("U ruajt në PrimeFlow.", ephemeral=True)
        except BridgeError as error:
            await interaction.followup.send(str(error), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            LOG.warning("Interaction needs a retry (%s)", type(error).__name__)
            await interaction.followup.send("Lidhja u ndërpre. Kontrollo detyrën në PrimeFlow para se ta provosh përsëri.", ephemeral=True)


def runtime_paths():
    base = Path(__file__).resolve().parent
    state = Path(os.environ.get("KUJTESA_STATE_DIR", str(base)))
    return {"env": Path(os.environ.get("KUJTESA_ENV_FILE", str(base / ".env"))),
            "receipts": state / ".primeflow-receipts.json", "status": state / ".kujtesa-worker-status.json"}


def load_env():
    path = runtime_paths()["env"]
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = json.loads(value)
                else:
                    value = value.strip("'")
                # The dedicated server file takes precedence over a stale PM2
                # inherited environment; standalone mode preserves env overrides.
                if os.environ.get("KUJTESA_ENV_FILE"):
                    os.environ[key.strip()] = value
                else:
                    os.environ.setdefault(key.strip(), value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check only PrimeFlow authentication; never connect to Discord or claim reminders")
    args = parser.parse_args()
    load_env()
    if os.environ.get("KUJTESA_ENABLED", "true").lower() == "false":
        print("Kujtesa server worker is disabled.")
        return 0
    base = os.environ.get("PRIMEFLOW_API_URL", "").strip()
    key = os.environ.get("PRIMEFLOW_GA_BRIDGE_KEY", "").strip()
    if not base or len(key) < 32:
        raise SystemExit("Configure PRIMEFLOW_API_URL and PRIMEFLOW_GA_BRIDGE_KEY in bot/.env.")
    paths = runtime_paths()
    bot = KujtesaBridge(base, key, reminders_enabled=os.environ.get("REMINDERS_ENABLED") == "1",
                        receipt_path=paths["receipts"], status_path=None if args.check else paths["status"])
    if args.check:
        async def check():
            try:
                result = await bot.api("/poll", {"delivery_enabled": False, "health_only": True})
                print("PrimeFlow bridge: OK. Reminder grant:", "enabled" if result.get("enabled") else "disabled")
            finally:
                await bot.close()
        asyncio.run(check())
        return 0
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("Configure DISCORD_TOKEN locally; never put it in a chat or repository.")
    bot.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
