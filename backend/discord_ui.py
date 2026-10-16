"""Discord task cards and deterministic task-edit forms."""
from __future__ import annotations

import json
import math
import re
from html import unescape
from difflib import SequenceMatcher
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from app.config import settings

TASKS_PER_PAGE = 10
STATUS_LABELS = {"TODO": "To Do", "IN_PROGRESS": "Në progres", "WAITING_CLIENT": "WFE",
                 "WAITING_CONFIRMATION": "Në konfirmim", "DONE": "E kryer"}
STATUS_COLORS = {"TODO": 0x64748B, "IN_PROGRESS": 0x3B82F6, "WAITING_CLIENT": 0xD4A017,
                 "WAITING_CONFIRMATION": 0xA855F7, "DONE": 0x22C55E}
MARKER = re.compile(r"\[\[\s*/?\s*(?:added|done)(?::(?:blue|green|grey))?\s*\]\]", re.I)


def plain(value: str | None) -> str:
    return MARKER.sub("", value or "")


def label(value: str | None, limit=100) -> str:
    return (re.sub(r"\s+", " ", readable(value)).strip() or "Detyrë")[:limit]


def readable(value: str | None) -> str:
    """Render legacy rich text for Discord without modifying stored markup."""
    value = re.sub(r"<\s*(?:br\s*/?|/p|/div|/li|/h[1-6])\s*>", "\n", value or "", flags=re.I)
    value = re.sub(r"<[^>]*>", "", value)
    return unescape(plain(value)).strip()


def heading(task: dict) -> str:
    return next((line.strip() for line in readable(task.get("title")).splitlines() if line.strip()), "Detyrë")[:230]


def task_url(task_id: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/tasks/{task_id}"


def formatted(value: str | None) -> str:
    value = re.sub(r"\[\[\s*done(?::(?:blue|green|grey))?\s*\]\](.*?)\[\[\s*/\s*done\s*\]\]",
                   lambda match: "~~" + discord.utils.escape_markdown(plain(match.group(1))) + "~~", value or "", flags=re.I | re.S)
    return readable(value)


def card(task: dict, *, number: int | None = None, detail: dict | None = None) -> discord.Embed:
    title = heading(task)
    embed = discord.Embed(title=(f"{number}. " if number is not None else "") + title,
        url=task_url(task["id"]), color=STATUS_COLORS.get(task.get("status"), 0x64748B))
    embed.add_field(name="Statusi", value=STATUS_LABELS.get(task.get("status"), task.get("status") or "—"), inline=True)
    plan = " · ".join(filter(None, ["1H " + task["one_h_report_slot"] if task.get("one_h_report_slot") else None, task.get("finish_period")])) or "Pa slot / AM–PM"
    embed.add_field(name="Planifikimi", value=plan, inline=True)
    embed.add_field(name="Progresi", value=f"{task.get('progress_percentage') or 0}%", inline=True)
    badges = [name for key, name in (("is_bllok", "BLL"), ("is_r1", "R1"), ("is_personal", "Personal"), ("is_1h_report", "1H")) if task.get(key)]
    badges.append("Prioritet i lartë" if task.get("priority") == "HIGH" else "Prioritet normal")
    embed.set_footer(text=" · ".join(badges))
    if detail is not None:
        sections = []
        for name, key in (("Pikat e titullit", "title_points"), ("Pikat e përshkrimit", "description_points")):
            if key == "title_points" and task.get("_px_note"):
                name = "Pikat (PX Notes)"
            points = detail.get(key, [])
            if key == "description_points" and readable(task.get("description")) == readable(task.get("title")):
                continue
            if points:
                lines = []
                for point in points:
                    text = re.sub(r"^\s*(?:\d+\.\s+|[•*-]\s+)", "", readable(point["text"]))
                    text = discord.utils.escape_markdown(text)
                    lines.append(f"{point['number']}. " + (f"✓ ~~{text}~~" if point["done"] else f"○ {text}"))
                sections.append("**" + name + "**\n" + "\n".join(lines))
        if not sections and task.get("description"):
            sections.append(formatted(task["description"]))
        if task.get("user_comment"):
            sections.append("**Komenti yt**\n" + formatted(task["user_comment"]))
        body = "\n\n".join(sections)
        embed.description = body[:3700] + ("\n… Teksti i plotë: hap PrimeFlow. Pikat mund të zgjidhen te **Pikat**." if len(body) > 3700 else "")
        if task.get("due_date"):
            try:
                due = datetime.fromisoformat(task["due_date"].replace("Z", "+00:00")).astimezone(ZoneInfo(settings.APP_TIMEZONE))
                embed.add_field(name="Afati", value=due.strftime("%d.%m.%Y · %H:%M"), inline=True)
            except ValueError:
                pass
    else:
        preview = formatted(task.get("title"))
        if "\n" not in preview and task.get("description"):
            preview = formatted(task["description"])
        elif "\n" in preview:
            preview = preview.split("\n", 1)[1]
        elif plain(preview).strip() == heading(task):
            preview = ""
        embed.description = preview[:520] + ("\n… Zgjidhe për detajet dhe editimin." if len(preview) > 520 else "")
    return embed


def overview_embeds(task_list: list[dict], page: int) -> list[discord.Embed]:
    # Initial messages contain titles only; details open after selection.
    return []


def controls(task_id: str, fingerprint: str, action_choices) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    first = [("To Do", "todo", discord.ButtonStyle.secondary), ("Në progres", "progress", discord.ButtonStyle.primary),
             ("WFE", "wfe", discord.ButtonStyle.secondary), ("Mbylle", "done", discord.ButtonStyle.success),
             ("Konfirmim", "confirm", discord.ButtonStyle.secondary)]
    second = [("Pikat / Strike", "points"), ("Edito", "edit"), ("Koment", "comment"), ("Slot / AM–PM", "schedule")]
    for text, action, style in first:
        view.add_item(discord.ui.Button(label=text, custom_id=f"pf:quick:{task_id}:{fingerprint}:{action}", style=style, row=0))
    for text, action in second:
        view.add_item(discord.ui.Button(label=text, custom_id=f"pf:quick:{task_id}:{fingerprint}:{action}", row=1))
    view.add_item(discord.ui.Button(label="Hap PrimeFlow", url=task_url(task_id), row=1))
    view.add_item(discord.ui.Select(custom_id=f"pf:action:{task_id}:{fingerprint}", row=2,
        placeholder="AI dhe ndryshime të tjera…", options=[discord.SelectOption(label=text, value=str(i)) for i, (text, _) in enumerate(action_choices)]))
    view.add_item(discord.ui.Button(label="Rifresko detyrën", custom_id=f"pf:quick:{task_id}:{fingerprint}:refresh", row=3))
    return view


def points_view(detail: dict, page=0):
    task_id, fingerprint = detail["task"]["id"], detail["fingerprint"]
    view = discord.ui.View(timeout=None)
    maximum = 1
    row = 0
    for field, key, name in (("t", "title_points", "titulli"), ("d", "description_points", "përshkrimi")):
        if field == "t" and detail["task"].get("_px_note"):
            name = "PX Notes"
        if field == "d" and readable(detail["task"].get("description")) == readable(detail["task"].get("title")):
            continue
        for done in (True, False):
            points = [point for point in detail.get(key, []) if point["done"] != done]
            maximum = max(maximum, math.ceil(len(points) / 25))
            portion = points[page * 25:(page + 1) * 25]
            if not portion:
                continue
            names = [label(re.sub(r"^\s*(?:\d+\.\s+|[•*-]\s+)", "", plain(point["text"])), 88) for point in portion]
            options = [discord.SelectOption(label=f"{point['number']}. {name}"[:100], value=str(point["number"])) for point, name in zip(portion, names)]
            view.add_item(discord.ui.Select(custom_id=f"pf:pointset:{task_id}:{fingerprint}:{field}:{int(done)}", row=row,
                placeholder=f"{'Strike' if done else 'Hiq strike'} · {name} · zgjidh një ose disa pika", min_values=1, max_values=len(options), options=options))
            row += 1
    if maximum > 1:
        for text, target, disabled in (("←", page - 1, page <= 0), (f"{page + 1}/{maximum}", page, True), ("→", page + 1, page + 1 >= maximum)):
            view.add_item(discord.ui.Button(label=text, row=4, disabled=disabled, custom_id=f"pf:points:{task_id}:{fingerprint}:{max(0, target)}"))
    return view


def schedule_view(task_id: str, fingerprint: str):
    options = [discord.SelectOption(label="Periudha " + value, value="period:" + value) for value in ("AM", "PM")]
    options += [discord.SelectOption(label="Sloti " + value, value="slot:" + value) for value in ("10:00", "11:00", "11:50", "14:20", "16:00")]
    options += [discord.SelectOption(label="Hiq AM/PM", value="period:"), discord.SelectOption(label="Hiq slotin", value="slot:")]
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(custom_id=f"pf:schedule:{task_id}:{fingerprint}", placeholder="Zgjidh slotin ose periudhën", options=options))
    return view


def people_view(people: list[dict], task_id: str, fingerprint: str, page=0):
    view = discord.ui.View(timeout=None)
    portion = people[page * 25:(page + 1) * 25]
    if portion:
        view.add_item(discord.ui.Select(custom_id=f"pf:confirm:{task_id}:{fingerprint}", row=0,
            placeholder="Kush duhet ta konfirmojë?", options=[discord.SelectOption(label=label(person["full_name"]), value=person["id"]) for person in portion]))
    if len(people) > 25:
        for text, target, disabled in (("←", page - 1, page == 0), ("→", page + 1, (page + 1) * 25 >= len(people))):
            view.add_item(discord.ui.Button(label=text, row=1, disabled=disabled, custom_id=f"pf:people:{task_id}:{fingerprint}:{max(0, target)}"))
    return view


def action(tool: str, arguments: dict) -> dict:
    return {"tool": tool, "arguments_json": json.dumps(arguments, ensure_ascii=False)}


def preserve_markers(original: str | None, edited: str) -> str:
    """Keep editor annotations around text that the user did not change."""
    original = original or ""
    clean = plain(original)
    blocks = SequenceMatcher(None, clean, edited, autojunk=False).get_matching_blocks()
    stack = []
    spans = []
    cursor = 0
    previous = 0
    for marker in MARKER.finditer(original):
        cursor += marker.start() - previous
        name = "done" if "done" in marker.group().lower() else "added"
        closing = bool(re.match(r"\[\[\s*/", marker.group()))
        if not closing:
            stack.append((name, cursor, marker.group(), marker.start()))
        elif stack and stack[-1][0] == name:
            _, start, opening, order = stack.pop()
            spans.append((start, cursor, opening, marker.group(), order, marker.start()))
        previous = marker.end()
    insertions = []
    for start, end, opening, closing, open_order, close_order in spans:
        for block in blocks:
            if block.a <= start and end <= block.a + block.size and start < end:
                insertions.extend([(block.b + start - block.a, open_order, opening), (block.b + end - block.a, close_order, closing)])
                break
    for position, order, marker in sorted(insertions, reverse=True):
        edited = edited[:position] + marker + edited[position:]
    return edited


class CommentModal(discord.ui.Modal):
    def __init__(self, bot, task_id, fingerprint, *, complete=False):
        super().__init__(title="Mbylle detyrën" if complete else "Shto koment", timeout=600)
        self.bot, self.task_id, self.fingerprint, self.complete = bot, task_id, fingerprint, complete
        self.comment = discord.ui.TextInput(label="Komenti i rezultatit" if complete else "Komenti yt", style=discord.TextStyle.paragraph,
            required=not complete, max_length=2000)
        self.add_item(self.comment)

    async def on_submit(self, interaction):
        await interaction.response.defer(thinking=True)
        actions = []
        if str(self.comment).strip():
            actions.append(action("comment", {"comment": str(self.comment).strip()}))
        if self.complete:
            actions.append(action("update_task", {"status": "DONE"}))
        await self.bot.run_direct(interaction, self.task_id, self.fingerprint, actions,
            "Mbylle detyrën dhe shto komentin e rezultatit." if self.complete else "Shto komentin personal.")


class EditModal(discord.ui.Modal):
    def __init__(self, bot, detail):
        super().__init__(title="Edito detyrën", timeout=600)
        self.bot, self.detail = bot, detail
        task = detail["task"]
        self.original = {}
        self.inputs = {}
        due = task.get("due_date")
        if due:
            due = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(ZoneInfo(settings.APP_TIMEZONE)).strftime("%Y-%m-%d %H:%M")
        values = [("title", "Titulli", task.get("title"), 4000), ("description", "Përshkrimi", task.get("description"), 4000),
                  ("progress_percentage", "Progresi 0–100", str(task.get("progress_percentage") or 0), 3),
                  ("due_date", "Afati: YYYY-MM-DD HH:MM", due, 32), ("finish_period", "Periudha: AM ose PM", task.get("finish_period"), 2)]
        for key, name, value, limit in values:
            # Editor markup stays in the payload unless the user explicitly
            # edits this text. A metadata-only edit never erases existing strikes.
            value = value or ""
            self.original[key] = plain(value) if key in {"title", "description"} else value
            shown = self.original[key] if len(self.original[key]) <= limit else ""
            if not shown and self.original[key]:
                name = name + " i ri (opsional)"
            self.inputs[key] = discord.ui.TextInput(label=name, default=shown or None, required=False, max_length=limit,
                style=discord.TextStyle.paragraph if key in {"title", "description"} else discord.TextStyle.short)
            self.add_item(self.inputs[key])

    async def on_submit(self, interaction):
        await interaction.response.defer(thinking=True)
        try:
            changes = {}
            for key, field in self.inputs.items():
                value = str(field).strip()
                original = self.original[key].strip()
                if value == original or (len(original) > field.max_length and not value):
                    continue
                if key == "progress_percentage":
                    value = int(value)
                    if not 0 <= value <= 100:
                        raise ValueError("Progresi duhet të jetë nga 0 deri në 100.")
                elif key == "finish_period":
                    value = value.upper() or None
                    if value not in {None, "AM", "PM"}:
                        raise ValueError("Periudha duhet të jetë AM ose PM.")
                elif key == "due_date":
                    if value:
                        if len(value) < 16:
                            raise ValueError("Shkruaj afatin si YYYY-MM-DD HH:MM.")
                        date = datetime.fromisoformat(value)
                        value = (date.replace(tzinfo=ZoneInfo(settings.APP_TIMEZONE)) if date.tzinfo is None else date).isoformat()
                    else:
                        value = None
                elif key == "title" and len(value) < 2:
                    raise ValueError("Titulli duhet të ketë të paktën 2 karaktere.")
                if key in {"title", "description"}:
                    value = preserve_markers(self.detail["task"].get(key), value)
                changes[key] = value
            if not changes:
                await interaction.followup.send("Nuk ke ndryshuar asnjë fushë.", ephemeral=True)
                return
            await self.bot.run_direct(interaction, self.detail["task"]["id"], self.detail["fingerprint"],
                [action("update_task", changes)], "Edito fushat e plotësuara në formular.")
        except (ValueError, TypeError):
            await interaction.followup.send("Kontrollo fushat: progresi 0–100, periudha AM/PM dhe afati YYYY-MM-DD HH:MM.", ephemeral=True)
