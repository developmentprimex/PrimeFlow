"""Persistent task-agent controls and forms. No model interpretation of clicks."""
from __future__ import annotations

import io
import math
from urllib.parse import quote

import discord

import discord_ui as tasks_ui

STATUS = {"QUEUED": "Në radhë", "SUBMITTING": "Duke nisur", "RUNNING": "Duke punuar",
    "CANCEL_REQUESTED": "Anulimi u kërkua", "READY": "Gati për kontroll", "FAILED": "Dështoi", "CANCELLED": "Anuluar"}


def actor(interaction):
    return {"discord_user_id": str(interaction.user.id), "guild_id": str(interaction.guild_id), "channel_id": str(interaction.channel_id)}


def target_name(target):
    return (f"Pika {target['number']} · {'titulli' if target['field'] == 'title' else 'përshkrimi'}"
        if target.get("field") else "Detyra e plotë")


def target_view(detail: dict, page=0):
    task_id, version = detail["task"]["id"], detail["fingerprint"]
    maximum = max(1, math.ceil(max(len(detail.get("title_points", [])), len(detail.get("description_points", []))) / 25))
    page = min(max(0, page), maximum - 1)
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Detyra e plotë", row=0, style=discord.ButtonStyle.primary,
        custom_id=f"pf:agent:whole:{task_id}:{version}"))
    for row, (code, key, name) in enumerate((("t", "title_points", "titulli"), ("d", "description_points", "përshkrimi")), 1):
        points = detail.get(key, [])[page*25:(page+1)*25]
        if points:
            view.add_item(discord.ui.Select(row=row, custom_id=f"pf:agent:target:{task_id}:{version}:{code}",
                placeholder=f"Zgjidh pikën · {name}", options=[discord.SelectOption(
                    label=f"{p['number']}. {tasks_ui.label(p['text'], 86)}"[:100], value=str(p["number"])) for p in points]))
    if maximum > 1:
        for tag, text, target, disabled in (("prev", "←", page-1, page==0), ("current", f"{page+1}/{maximum}", page, True), ("next", "→", page+1, page+1>=maximum)):
            view.add_item(discord.ui.Button(row=3, label=text, disabled=disabled,
                custom_id=f"pf:agent:targets:{task_id}:{version}:{max(0,target)}:{tag}"))
    return view


def mode_view(task_id, fingerprint, field=None, number=None):
    target = ("t" if field == "title" else "d") + str(number) if field else "all"
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(custom_id=f"pf:agent:mode:{task_id}:{fingerprint}:{target}",
        placeholder="Çfarë pune t'i delegosh?", options=[
            discord.SelectOption(label="Hulumtim në internet", value="RESEARCH", description="Kërkim, krahasim dhe raport me burime"),
            discord.SelectOption(label="Përgatit tekst / analizë", value="DRAFT", description="Draft nga detyra dhe udhëzimet e tua")]))
    return view


def run_view(run):
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Rifresko rezultatin", custom_id=f"pf:agent:run:{run['id']}"))
    if run["status"] not in {"READY", "FAILED", "CANCELLED"}:
        view.add_item(discord.ui.Button(label="Anulo", custom_id=f"pf:agent:cancel:{run['id']}", style=discord.ButtonStyle.danger))
    if run["status"] == "READY":
        view.add_item(discord.ui.Button(label="Prano rezultatin", custom_id=f"pf:agent:accept:{run['id']}", style=discord.ButtonStyle.success, disabled=bool(run.get("accepted_at"))))
        if run["target"].get("field"):
            view.add_item(discord.ui.Button(label="Prano dhe shëno pikën të kryer", row=1,
                custom_id=f"pf:agent:strike:{run['id']}", style=discord.ButtonStyle.success))
        view.add_item(discord.ui.Button(label="Kërko ndryshime", row=1, custom_id=f"pf:agent:revise:{run['id']}"))
    elif run["status"] in {"FAILED", "CANCELLED"}:
        view.add_item(discord.ui.Button(label="Nis punë të re", custom_id=f"pf:agent:revise:{run['id']}"))
    return view


def result_message(run):
    target = run["target"]
    text = run.get("result_text") or run.get("error") or "Puna po përgatitet. Rifresko për të parë gjendjen."
    embed = discord.Embed(title=STATUS.get(run["status"], run["status"]), description=text[:3000] + ("\n… Rezultati i plotë është në skedarin e bashkëngjitur." if len(text)>3000 else ""),
        color=0x22C55E if run["status"] == "READY" else 0x64748B)
    embed.add_field(name="Objektivi", value=target_name(target), inline=False)
    embed.add_field(name="Modeli", value=run["model"], inline=True)
    embed.add_field(name="Krijuar", value=(run.get("created_at") or "—")[:32], inline=True)
    if run.get("finished_at"):
        embed.add_field(name="Përfunduar", value=run["finished_at"][:32], inline=True)
    if run.get("accepted_at"):
        embed.add_field(name="Pranimi", value="Rezultati u pranua", inline=True)
    source_lines = []
    for index, source in enumerate(run.get("sources", []), 1):
        url = quote(source["url"], safe=":/?=&%#@+~!;$,*-._")
        name = discord.utils.escape_markdown(source.get("title") or "Burimi")[:180]
        source_lines.append(f"{index}. [{name}](<{url}>)")
    chunks, current = [], ""
    for line in source_lines:
        # Very long URL lines still remain intact in the result attachment.
        if len(line) > 3500:
            line = line[:160].split("](", 1)[0] + " — URL e plotë në skedar."
        if len(current) + len(line) + 1 > 3500:
            chunks.append(current)
            current = ""
        current += ("\n" if current else "") + line
    if current: chunks.append(current)
    sources = [discord.Embed(title="Burimet e hulumtimit", description=chunk, color=0x3B82F6) for chunk in chunks]
    message = {"embed": embed, "view": run_view(run), "source_embeds": sources}
    if len(text) > 3000 or run.get("sources"):
        full = text + "\n\nBurimet:\n" + "\n".join(f"{s.get('title') or 'Burimi'}: {s['url']}" for s in run.get("sources", []))
        message["file"] = discord.File(io.BytesIO(full.encode("utf-8")), filename=f"primeflow-ai-{run['id']}.txt")
    return message


async def show_run(interaction, run):
    message = result_message(run)
    sources = message.pop("source_embeds")
    await interaction.followup.send(**message)
    for embed in sources:
        await interaction.followup.send(embed=embed)


class AgentInstructionModal(discord.ui.Modal):
    def __init__(self, bot, task_id, fingerprint, mode, field=None, number=None):
        super().__init__(title=("Hulumtim" if mode == "RESEARCH" else "Draft / analizë") + (f" · pika {number}" if field else " · detyra"), timeout=600)
        self.bot, self.task_id, self.fingerprint, self.mode = bot, task_id, fingerprint, mode
        self.field, self.number = field, number
        self.instruction = discord.ui.TextInput(label="Udhëzimi dhe rezultati që pret", style=discord.TextStyle.paragraph, max_length=4000)
        self.add_item(self.instruction)

    async def on_submit(self, interaction):
        await interaction.response.defer(thinking=True)
        try:
            await self.bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
            run = await self.bot.bridge("/bot/agents/runs", {**actor(interaction), "request_id": str(interaction.id),
                "task_id": self.task_id, "expected_fingerprint": self.fingerprint, "mode": self.mode,
                "field": self.field, "number": self.number, "instruction": str(self.instruction)})
            await show_run(interaction, run)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)


class AgentRevisionModal(discord.ui.Modal):
    def __init__(self, bot, run_id):
        super().__init__(title="Udhëzimi për punën e re", timeout=600)
        self.bot, self.run_id = bot, run_id
        self.instruction = discord.ui.TextInput(label="Çfarë të ndryshojë ose të plotësojë?", style=discord.TextStyle.paragraph, max_length=4000)
        self.add_item(self.instruction)

    async def on_submit(self, interaction):
        await interaction.response.defer(thinking=True)
        try:
            await self.bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
            identity = actor(interaction)
            parent = await self.bot.bridge(f"/bot/agents/runs/{self.run_id}", identity)
            detail = await self.bot.bridge("/bot/select", {**identity, "task_id": parent["task_id"]})
            target = parent["target"]
            if target.get("field"):
                points = detail["title_points" if target["field"] == "title" else "description_points"]
                if not any(p["number"] == target["number"] and p["text"] == target["text"] for p in points):
                    raise ValueError("Pika ndryshoi. Zgjidh objektivin përsëri nga karta e detyrës.")
            run = await self.bot.bridge("/bot/agents/runs", {**identity, "request_id": str(interaction.id),
                "task_id": parent["task_id"], "expected_fingerprint": detail["fingerprint"], "mode": parent["mode"],
                "field": target.get("field"), "number": target.get("number"), "instruction": str(self.instruction),
                "parent_run_id": parent["id"] if parent["status"] == "READY" else None})
            await show_run(interaction, run)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)
