"""Bot-side delegation interactions and restart-safe result delivery."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

import discord
from discord.http import handle_message_parameters

import discord_agent_ui as ui

log = logging.getLogger(__name__)


async def handle_agent_interaction(bot, interaction):
    data = interaction.data or {}
    custom_id = data.get("custom_id", "")
    if not custom_id.startswith("pf:agent:"):
        return False
    parts = custom_id.split(":")
    action = parts[2]
    if action == "mode":
        task_id, version, target = parts[3:6]
        mode = data["values"][0]
        if mode not in {"RESEARCH", "DRAFT"}:
            raise ValueError("Mënyrë e pavlefshme.")
        field, number = (None, None) if target == "all" else ("title" if target[0] == "t" else "description", int(target[1:]))
        await interaction.response.send_modal(ui.AgentInstructionModal(bot, task_id, version, mode, field, number))
        return True
    if action == "revise":
        await interaction.response.send_modal(ui.AgentRevisionModal(bot, parts[3]))
        return True
    await interaction.response.defer(thinking=True)
    await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
    identity = ui.actor(interaction)
    if action in {"targets", "target", "whole"}:
        task_id, version = parts[3:5]
        detail = await bot.current_detail(interaction, task_id, version)
        if detail:
            if action == "targets":
                await interaction.followup.send("Delego detyrën e plotë ose zgjidh një pikë:", view=ui.target_view(detail, int(parts[5]) if len(parts)>5 else 0))
            else:
                field, number = (None, None) if action == "whole" else ("title" if parts[5] == "t" else "description", int(data["values"][0]))
                target = {"field": field, "number": number}
                text = ui.target_name(target)
                if field:
                    point = next((p for p in detail[field+"_points"] if p["number"] == number), None)
                    if not point: raise ValueError("Pika nuk ekziston më.")
                    text += "\n" + ui.tasks_ui.plain(point["text"])[:1200]
                await interaction.followup.send(text, view=ui.mode_view(task_id, version, field, number))
    elif action == "history":
        task_id, offset = parts[3], int(parts[4]) if len(parts)>4 else 0
        result = await bot.bridge(f"/bot/agents/tasks/{task_id}/runs?offset={offset}", identity)
        view = discord.ui.View(timeout=None)
        if result["runs"]:
            view.add_item(discord.ui.Select(custom_id="pf:agent:pick", options=[discord.SelectOption(value=run["id"],
                label=f"{ui.STATUS.get(run['status'], run['status'])} · {ui.tasks_ui.label(run['instruction'],65)}"[:100],
                description=ui.target_name(run["target"])[:100]) for run in result["runs"]]))
        if offset:
            view.add_item(discord.ui.Button(label="←", row=1, custom_id=f"pf:agent:history:{task_id}:{max(0,offset-25)}"))
        if result.get("next_offset") is not None:
            view.add_item(discord.ui.Button(label="→", row=1, custom_id=f"pf:agent:history:{task_id}:{result['next_offset']}"))
        await interaction.followup.send("Zgjidh punën e agjentit:" if result["runs"] else "Ende nuk ka punë të deleguara për këtë detyrë.", view=view)
    elif action in {"run", "pick", "cancel", "accept", "strike"}:
        run_id = data["values"][0] if action == "pick" else parts[3]
        path = f"/bot/agents/runs/{run_id}"
        if action in {"accept", "strike"}:
            result = await bot.bridge(path+"/accept", {**identity, "request_id": str(interaction.id), "mark_point_done": action == "strike"})
            if result.get("task_detail"):
                await bot.show_task(interaction, result["task_detail"], notice="Rezultati u pranua dhe pika u shënua e kryer.", update=True)
            await ui.show_run(interaction, result["run"])
        else:
            run = await bot.bridge(path+("/cancel" if action == "cancel" else ""), identity)
            await ui.show_run(interaction, run)
    else:
        raise ValueError("Veprim i panjohur i agjentit.")
    return True


def delivery_nonce(run_id, part):
    return hashlib.sha256(f"agent:{run_id}:{part}".encode()).hexdigest()[:24]


def delivery_marker(run_id, part):
    return f"PrimeFlow AI · {run_id} · {part}"


async def send_durable_result(bot, channel, run):
    message = ui.result_message(run)
    sources = message.pop("source_embeds")
    parts = [message] + [{"embed": embed} for embed in sources]
    expected = {delivery_marker(run["id"], i): i for i in range(len(parts))}
    found = {}
    created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")) if run.get("created_at") else None
    # Stable visible footer markers recover delivery even after Discord's
    # short nonce-deduplication window. Only trust messages from this bot.
    async for previous in channel.history(limit=None, after=created_at-timedelta(seconds=5) if created_at else None):
        if previous.author.id != bot.user.id:
            continue
        for embed in previous.embeds:
            marker = embed.footer.text
            if marker in expected:
                found[expected[marker]] = str(previous.id)
        if len(found) == len(parts): break
    try:
        for index, part in enumerate(parts):
            if index in found:
                continue
            part["embed"].set_footer(text=delivery_marker(run["id"], index))
            with handle_message_parameters(**part, nonce=delivery_nonce(run["id"], index), allowed_mentions=discord.AllowedMentions.none()) as params:
                # discord.py's public send currently omits enforce_nonce.
                if params.payload is not None:
                    params.payload["enforce_nonce"] = True
                else:
                    for field in params.multipart:
                        if field.get("name") == "payload_json":
                            payload = json.loads(field["value"])
                            payload["enforce_nonce"] = True
                            field["value"] = json.dumps(payload)
                sent = await bot.http.send_message(channel.id, params=params)
                found[index] = str(sent["id"])
        return [found[i] for i in range(len(parts))]
    finally:
        if "file" in message: message["file"].close()


async def deliver_agent_results(bot):
    jobs = (await bot.bridge("/bot/agents/deliveries/claim", {}))["jobs"]
    for job in jobs:
        try:
            channel = await bot.private_channel(job["guild_id"], job["channel_id"], job["discord_user_id"])
            identity = {key: job[key] for key in ("discord_user_id", "guild_id", "channel_id")}
            delivery = {**identity, "lease_token": job["lease_token"]}
            run = await bot.bridge(f"/bot/agents/runs/{job['run_id']}/delivery", delivery)
            ids = await send_durable_result(bot, channel, run)
            await bot.bridge(f"/bot/agents/runs/{job['run_id']}/ack", {**delivery, "message_ids": ids})
        except Exception as exc:
            log.warning("Agent delivery %s failed: %s", job["run_id"], type(exc).__name__)
