"""Discord task cards and deterministic task-edit forms."""
from __future__ import annotations

import json
import math
import re
import uuid
from html import unescape
from difflib import SequenceMatcher
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from app.config import settings

LIST_PER_PAGE = 20
POINTS_SHOWN = 25
# PrimeFlow appends the strike time as `HH:MM DD.MM` to a completed point.
STRIKE_TIME = re.compile(r"\s+(\d{2}:\d{2}\s+\d{2}\.\d{2})\s*$")
STATUS_LABELS = {"TODO": "To Do", "IN_PROGRESS": "Në progres", "WAITING_CLIENT": "WFE",
                 "WAITING_CONFIRMATION": "Në konfirmim", "DONE": "E kryer"}
# PrimeFlow's status colours: To Do pink, In progress yellow, Done green, WFE gold,
# confirmation peach. Discord has no pink circle emoji: the bot uploads its own
# (see pink_circle_png) and replaces the To Do placeholder once it is ready.
TODO_PINK = 0xFFC4ED
STATUS_ICONS = {"TODO": "🟣", "IN_PROGRESS": "🟡", "WAITING_CLIENT": "🟠", "WAITING_CONFIRMATION": "⚪", "DONE": "🟢"}
STATUS_COLORS = {"TODO": TODO_PINK, "IN_PROGRESS": 0xFFFF00, "WAITING_CLIENT": 0xE2C15B,
                 "WAITING_CONFIRMATION": 0xFFEDD5, "DONE": 0xC4FDC4}
MARKER = re.compile(r"\[\[\s*/?\s*(?:added|done)(?::(?:blue|green|grey))?\s*\]\]", re.I)
# The few buttons that fit the task's current status; everything else lives in "Më shumë".
PRIMARY = {"TODO": [("▶ Fillo", "progress", discord.ButtonStyle.primary), ("✅ Mbylle", "done", discord.ButtonStyle.success)],
           "IN_PROGRESS": [("✅ Mbylle", "done", discord.ButtonStyle.success), ("⏸ WFE", "wfe", discord.ButtonStyle.secondary)],
           "WAITING_CLIENT": [("▶ Vazhdo", "progress", discord.ButtonStyle.primary), ("✅ Mbylle", "done", discord.ButtonStyle.success)],
           "WAITING_CONFIRMATION": [("▶ Në progres", "progress", discord.ButtonStyle.secondary)],
           "DONE": [("↺ Rihap", "todo", discord.ButtonStyle.secondary)]}
MORE = [("📄 Teksti i plotë", "full"), ("✏️ Edito", "edit"), ("💬 Koment", "comment"), ("📝 Mbylle me koment", "done_comment"),
        ("🕐 Slot / AM–PM", "schedule"), ("👤 Dërgo për konfirmim", "confirm"), ("To Do", "todo"),
        ("Në progres", "progress"), ("WFE", "wfe"), ("🤖 Udhëzim për AI", "ai"), ("🧠 Delegoja agjentit", "agent"),
        ("📚 Rezultatet AI", "history"), ("🔄 Rifresko", "refresh")]
STATUS_ACTIONS = {"todo": "TODO", "progress": "IN_PROGRESS", "wfe": "WAITING_CLIENT"}


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


def icon(status: str | None) -> str:
    return STATUS_ICONS.get(status) or STATUS_ICONS["TODO"]


def pink_circle_png(size: int = 64) -> bytes:
    """A smooth To Do pink circle as PNG, built without image libraries."""
    import struct
    import zlib
    red, green, blue = TODO_PINK >> 16 & 255, TODO_PINK >> 8 & 255, TODO_PINK & 255
    centre, radius = (size - 1) / 2, size / 2 - 1
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            alpha = max(0.0, min(1.0, radius - ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5 + 0.5))
            raw += bytes((red, green, blue, round(alpha * 255)))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def status_text(status: str | None) -> str:
    return f"{icon(status)} {STATUS_LABELS.get(status, status or '—')}"


def summary(task: dict) -> str:
    """One line instead of separate Status / Planning / Due fields."""
    parts = [status_text(task.get("status"))]
    if task.get("one_h_report_slot"):
        parts.append("Sloti " + task["one_h_report_slot"])
    if task.get("finish_period"):
        parts.append(task["finish_period"])
    if task.get("due_date"):
        try:
            due = datetime.fromisoformat(task["due_date"].replace("Z", "+00:00")).astimezone(ZoneInfo(settings.APP_TIMEZONE))
            parts.append("Afati " + due.strftime("%d.%m %H:%M"))
        except ValueError:
            pass
    return " · ".join(parts)


def point_sections(task: dict, detail: dict) -> list[tuple[str, list[dict]]]:
    sections = []
    for name, key in (("Pikat e titullit", "title_points"), ("Pikat e përshkrimit", "description_points")):
        if key == "title_points" and task.get("_px_note"):
            name = "Pikat (PX Notes)"
        points = detail.get(key, [])
        if key == "description_points" and readable(task.get("description")) == readable(task.get("title")):
            continue
        if key == "title_points" and len(points) == 1 and label(strip_number(points[0]["text"]), 230) == heading(task):
            continue  # The only "point" is the title itself.
        if points:
            sections.append((name, points))
    return sections


def strip_number(text: str) -> str:
    return re.sub(r"^\s*(?:\d+\.\s+|[•*-]\s+)", "", readable(text))


def point_line(point: dict, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", strip_number(point["text"])) if limit else strip_number(point["text"])
    match = STRIKE_TIME.search(text)
    stamp = match.group(1) if match and point["done"] else ""
    if stamp:
        text = text[:match.start()]
    if limit and len(text) > limit:
        text = text[:limit - 1] + "…"
    text = discord.utils.escape_markdown(text)
    # Non-breaking spaces keep the strike time on one line.
    stamp = " · 🕘 " + stamp.replace(" ", " ") if stamp else ""
    return f"{point['number']}. " + (f"✅ ~~{text}~~{stamp}" if point["done"] else f"⬜ {text}")


def points_count(task: dict, detail: dict) -> str:
    points = [point for _, items in point_sections(task, detail) for point in items]
    return f"☑ {sum(point['done'] for point in points)}/{len(points)} pika" if points else ""


def full_text(task: dict, detail: dict) -> str:
    """Complete task text, shown privately on request instead of in every card."""
    sections = []
    for name, points in point_sections(task, detail):
        lines = [point_line(point) for point in points]
        sections.append("**" + name + "**\n" + "\n".join(lines))
    if not sections and task.get("description"):
        sections.append(formatted(task["description"]))
    if task.get("user_comment"):
        sections.append("**Komenti yt**\n" + formatted(task["user_comment"]))
    return "**" + heading(task) + "**\n\n" + ("\n\n".join(sections) or "Kjo detyrë nuk ka përshkrim.")


def badges(task: dict) -> str:
    names = [name for key, name in (("is_bllok", "BLL"), ("is_r1", "R1"), ("is_personal", "Personal"), ("is_1h_report", "1H")) if task.get(key)]
    if task.get("priority") == "HIGH":
        names.append("Prioritet i lartë")
    return " · ".join(names)


def card(task: dict, *, number: int | None = None, detail: dict | None = None) -> discord.Embed:
    embed = discord.Embed(title=((f"{number}. " if number is not None else "") + heading(task))[:256],
        url=task_url(task["id"]), color=STATUS_COLORS.get(task.get("status"), 0x64748B))
    lines = [summary(task)]
    shortened = False
    if detail is not None and points_count(task, detail):
        lines[0] += " · " + points_count(task, detail)
    if detail is not None:
        sections = point_sections(task, detail)
        shown = 0
        for name, points in sections:
            if len(sections) > 1:
                lines.append(f"\n**{name}**")
            elif not shown:
                lines.append("")
            for point in points:
                if shown >= POINTS_SHOWN:
                    shortened = True
                    break
                shortened = shortened or len(strip_number(point["text"])) > 160
                lines.append(point_line(point, 160))
                shown += 1
        remaining = sum(len(points) for _, points in sections) - shown
        if remaining > 0:
            lines.append(f"… +{remaining} pika të tjera te **☑ Pikat**")
        if not sections and task.get("description"):
            text = formatted(task["description"])
            short = "\n".join(text.splitlines()[:6])[:600]
            shortened = shortened or short != text
            lines += ["", short + ("…" if short != text else "")]
        if task.get("user_comment"):
            comment = formatted(task["user_comment"])
            lines += ["", "💬 " + comment[:200] + ("…" if len(comment) > 200 else "")]
        if shortened:
            lines.append("\n_Teksti i plotë: **Më shumë → 📄 Teksti i plotë**_")
    else:
        preview = formatted(task.get("title"))
        if "\n" not in preview and task.get("description"):
            preview = formatted(task["description"])
        elif "\n" in preview:
            preview = preview.split("\n", 1)[1]
        elif plain(preview).strip() == heading(task):
            preview = ""
        if preview:
            lines += ["", preview[:400] + ("…" if len(preview) > 400 else "")]
    embed.description = "\n".join(lines)[:4000]
    if badges(task):
        embed.set_footer(text=badges(task))
    return embed


def controls(task_id: str, fingerprint: str, status: str | None = None) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    primary = PRIMARY.get(status, PRIMARY["IN_PROGRESS"])
    for text, action, style in primary:
        view.add_item(discord.ui.Button(label=text, custom_id=f"pf:quick:{task_id}:{fingerprint}:{action}", style=style, row=0))
    view.add_item(discord.ui.Button(label="☑ Pikat", custom_id=f"pf:quick:{task_id}:{fingerprint}:points", row=0))
    view.add_item(discord.ui.Button(label="Hap PrimeFlow", url=task_url(task_id), row=0))
    hidden = {action for _, action, _ in primary} | {action for action, value in STATUS_ACTIONS.items() if value == status}
    view.add_item(discord.ui.Select(custom_id=f"pf:more:{task_id}:{fingerprint}", row=1, placeholder="Më shumë…",
        options=[discord.SelectOption(label=text, value=value, emoji=icon(STATUS_ACTIONS[value]) if value in STATUS_ACTIONS else None)
                 for text, value in MORE if value not in hidden]))
    for text, direction in (("◀", "prev"), ("↩ Lista", "list"), ("▶", "next")):
        view.add_item(discord.ui.Button(label=text, custom_id=f"pf:nav:{task_id}:{direction}", row=2))
    return view


def back_button(task_id: str, row: int) -> discord.ui.Button:
    return discord.ui.Button(label="← Kthehu", custom_id=f"pf:back:{task_id}", row=row)


def list_view(task_list: list[dict], title: str, page: int = 0):
    """Numbered titles with one button per task: one click opens the card."""
    if not task_list:
        return f"**{title}**\nNuk ke detyra të hapura. 🎉", None
    pages = math.ceil(len(task_list) / LIST_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    offset = page * LIST_PER_PAGE
    chunk = task_list[offset:offset + LIST_PER_PAGE]
    lines = [f"`{offset + i}.` {icon(task.get('status'))} {discord.utils.escape_markdown(label(heading(task), 70))}"
             for i, task in enumerate(chunk, 1)]
    content = f"**{title}** · {len(task_list)}" + (f" · faqja {page + 1}/{pages}" if pages > 1 else "") + "\n" + "\n".join(lines)
    view = discord.ui.View(timeout=None)
    for i, task in enumerate(chunk):
        view.add_item(discord.ui.Button(label=str(offset + i + 1), custom_id=f"pf:open:{task['id']}", row=i // 5))
    if pages > 1:
        view.add_item(discord.ui.Button(label="◀", row=4, disabled=page == 0, custom_id=f"pf:list:{max(0, page - 1)}"))
        view.add_item(discord.ui.Button(label="▶", row=4, disabled=page + 1 >= pages, custom_id=f"pf:list:{page + 1}"))
    return content + "\nKliko numrin për ta hapur.", view


def bucket_name(bucket: str) -> str:
    return f"Raportimi {bucket}" if bucket in {"AM", "PM"} else f"Sloti {bucket}"


def report_intro(bucket: str, task_list: list[dict], reminder_id: str, user_id: str | None = None, notice: str | None = None,
                 join_url: str | None = None):
    lines = [f"`{i}.` {icon(task.get('status'))} {discord.utils.escape_markdown(label(heading(task), 70))}"
             for i, task in enumerate(task_list[:25], 1)]
    content = ((f"<@{user_id}> " if user_id else "") + f"⏰ **{bucket_name(bucket)}** · {len(task_list)} detyra\n"
               + (f"🎧 **Takimi 1H fillon në {bucket}.** Kyçu në kanalin 1H.\n" if join_url else "")
               + (notice + "\n" if notice else "") + "\n".join(lines))
    view = discord.ui.View(timeout=None)
    rid = uuid.UUID(str(reminder_id)).hex
    view.add_item(discord.ui.Button(label="📝 Fillo raportimin", style=discord.ButtonStyle.primary, row=0,
        custom_id=f"pf:rep:{rid}:-:0.0.0.0:go"))
    if join_url:
        view.add_item(discord.ui.Button(label="🎧 Kyçu në takimin 1H", url=join_url, row=0))
    view.add_item(discord.ui.Select(custom_id=f"pf:repdone:{rid}", row=1, placeholder="✅ Shëno të kryerat (një ose disa)…",
        min_values=1, max_values=min(len(task_list), 25), options=[discord.SelectOption(
            label=f"{i}. {label(heading(task), 90)}"[:100], value=task["id"]) for i, task in enumerate(task_list[:25], 1)]))
    return content[:2000], view


def report_step(bucket: str, task: dict, reminder_id: str, counts: list[int], position: int, total: int):
    rid, tid = uuid.UUID(str(reminder_id)).hex, uuid.UUID(str(task["id"])).hex
    state = ".".join(map(str, counts))
    view = discord.ui.View(timeout=None)
    for text, action, style in (("✅ U krye", "done", discord.ButtonStyle.success), ("🟡 Vazhdon", "cont", discord.ButtonStyle.primary),
                                ("⏸ WFE", "wfe", discord.ButtonStyle.secondary), ("⏭ Kalo", "skip", discord.ButtonStyle.secondary)):
        view.add_item(discord.ui.Button(label=text, style=style, row=0, custom_id=f"pf:rep:{rid}:{tid}:{state}:{action}"))
    view.add_item(discord.ui.Button(label="📂 Hap detyrën", row=1, custom_id=f"pf:open:{task['id']}:new"))
    return f"⏰ **{bucket_name(bucket)}** · {position}/{total}", card(task), view


def report_summary(bucket: str, counts: list[int]) -> str:
    done, cont, wfe, skipped = counts
    parts = [(f"{done} e kryer" if done == 1 else f"{done} të kryera") if done else None,
             (f"{cont} vazhdon" if cont == 1 else f"{cont} vazhdojnë") if cont else None,
             f"{wfe} WFE" if wfe else None, (f"{skipped} e kaluar" if skipped == 1 else f"{skipped} të kaluara") if skipped else None]
    return f"✓ **{bucket_name(bucket)} u raportua**" + (" · " + " · ".join(filter(None, parts)) if any(counts) else "")


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
    view.add_item(back_button(task_id, 4))
    return view


def schedule_view(task_id: str, fingerprint: str):
    options = [discord.SelectOption(label="Periudha " + value, value="period:" + value) for value in ("AM", "PM")]
    options += [discord.SelectOption(label="Sloti " + value, value="slot:" + value) for value in ("10:00", "11:00", "11:50", "14:20", "16:00")]
    options += [discord.SelectOption(label="Hiq AM/PM", value="period:"), discord.SelectOption(label="Hiq slotin", value="slot:")]
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(custom_id=f"pf:schedule:{task_id}:{fingerprint}", placeholder="Zgjidh slotin ose periudhën", options=options))
    view.add_item(back_button(task_id, 1))
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
    view.add_item(back_button(task_id, 1))
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
        await interaction.response.defer()
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
        await interaction.response.defer()
        try:
            changes = {}
            for key, field in self.inputs.items():
                value = str(field).strip()
                original = self.original[key].strip()
                if value == original or (len(original) > field.max_length and not value):
                    continue
                if key == "finish_period":
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
            await interaction.followup.send("Kontrollo fushat: periudha AM/PM dhe afati YYYY-MM-DD HH:MM.", ephemeral=True)


def meeting_alert(job: dict, voice_url: str | None = None):
    """Meeting reminder that pings the person; internal meetings link the voice room."""
    meeting = job["meeting"]
    starts = datetime.fromisoformat(meeting["starts_at"]).astimezone(ZoneInfo(settings.APP_TIMEZONE))
    internal = meeting.get("type") == "internal"
    if job["kind"] == "start":
        headline = "🔴 **Takimi po fillon tani**"
    else:
        headline = f"🔔 **Takim pas {meeting.get('minutes_before') or 0} min**"
    content = f"<@{job['discord_user_id']}> {headline} · {discord.utils.escape_markdown(label(meeting['title'], 150))}"
    embed = discord.Embed(title=label(meeting["title"], 250), color=0xEF4444 if job["kind"] == "start" else 0xF59E0B)
    details = [f"🕘 {starts.strftime('%H:%M')} · " + ("Takim i brendshëm" if internal else "Takim i jashtëm")]
    if meeting.get("platform"):
        details.append("📍 " + label(meeting["platform"], 100))
    others = meeting.get("others") or []
    if others:
        details.append("👥 Me: " + ", ".join(label(person["name"], 40) for person in others[:15]) + (" …" if len(others) > 15 else ""))
    embed.description = "\n".join(details)
    view = discord.ui.View(timeout=None)
    url = (meeting.get("url") or "").strip()
    if url.startswith(("https://", "http://")):
        view.add_item(discord.ui.Button(label="🔗 Hap takimin", url=url[:512]))
    if internal and voice_url:
        view.add_item(discord.ui.Button(label="🎧 Hyr në kanalin zanor", url=voice_url))
    return content[:2000], embed, view
