"""Check task delivery against messages from the assigned person's Discord account."""

import asyncio
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import case, delete, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.discord_assistant import DiscordLink
from app.models.discord_task_delivery_comment import DiscordTaskDeliveryComment
from app.models.enums import UserRole
from app.models.ga_discord_channel_message import GaDiscordChannelMessage
from app.models.project import Project
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_marker_history import TaskOneHMarkerHistory
from app.models.user import User
from app.services.m3_reporting_points import task_row_appearance
from app.services.task_pause import pause_until_on_day
from app.services.meetings_report import (
    WEEKLY_PLANNER_DEPARTMENT_ORDER,
    _clean_task_title,
    _initials,
    _local_time,
    _m3_am_pm_label,
    _m3_department_code_label,
    _m3_task_type_label,
    common_view_task_sort_key,
    weekly_planner_user_sort_keys,
)
from app.services.primeflow_report import report_timezone
from app.services.one_h_slots import effective_slot_date
from app.services.note_markup import parse_marked_note_content
from app.services.personal_task_owner import PERSONAL_OWNER_PREFIX
from app.services.report_attendance import load_report_attendance
from app.services.task_date_window import common_view_task_date_window_filter
from app.services.task_marker import current_effective_marker_date, one_h_marker_label
from app.services.task_reporting_choices import ENTITY, choice_members, group_key, personal_choices, reporting_differences, slot_values

log = logging.getLogger(__name__)
DEADLINES = {"M2": "12:15", "M3": "16:30"}
DELIVERY_MARKERS = {"M2", "M3", "M2_M3"}
DISCORD_EPOCH_MS = 1420070400000
UNASSIGNED_ORDER = (len(WEEKLY_PLANNER_DEPARTMENT_ORDER), "~", 1, 0, "~")
LINE_PREFIX = re.compile(r"^(?:\s|<@!?\d+>|<@&\d+>|[-•]\s+|\d+[.)]\s+|#{1,3}\s+)+")
DELIVERY_PREFIX = re.compile(r"^(?:(?:m[23]|dor[eë]zim)\s*:\s*)+")


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _message_titles(content: str) -> set[str]:
    titles = set()
    for line in content.splitlines():
        if line.lstrip().startswith(">"):
            continue
        line = LINE_PREFIX.sub("", line).strip()
        line = re.sub(r"\s+(?:<?https?://\S+>?)\s*$", "", line).strip(" *`")
        title = _normalize(line)
        titles.update((title, DELIVERY_PREFIX.sub("", title).strip(" *`")))
    return titles - {""}


async def _task_rows(db: AsyncSession, day: date, today: date, guild_id: str | None = None) -> list[dict]:
    zone = ZoneInfo(settings.REALIZATION_TIMEZONE)
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    query = select(Task, Project.title).outerjoin(Project, Task.project_id == Project.id)
    marker = Task.one_h_marker
    marker_by_ga = Task.one_h_marker_by_ga
    if day < today:
        history = (select(TaskOneHMarkerHistory.marker_date, TaskOneHMarkerHistory.one_h_marker,
                          TaskOneHMarkerHistory.one_h_marker_by_ga)
                   .where(TaskOneHMarkerHistory.task_id == Task.id, TaskOneHMarkerHistory.marker_date <= day)
                   .order_by(TaskOneHMarkerHistory.marker_date.desc()).limit(1).correlate(Task).lateral())
        query = query.outerjoin(history, true())
        marker = case(
            (history.c.marker_date.is_not(None), history.c.one_h_marker),
            (Task.one_h_marker_date <= day, Task.one_h_marker),
            (Task.one_h_marker_date.is_(None), Task.one_h_marker),
        )
        marker_by_ga = case(
            (history.c.marker_date.is_not(None), history.c.one_h_marker_by_ga),
            else_=Task.one_h_marker_by_ga,
        )
    delivery_markers = sorted(DELIVERY_MARKERS)
    personal_candidates = select(AuditLog.entity_id).where(
        AuditLog.entity_type == ENTITY, AuditLog.action == "marker",
        AuditLog.after["personal"].as_boolean().is_(True),
        AuditLog.after["date"].as_string() <= day.isoformat(),
        func.string_to_array(AuditLog.after["value"].as_string(), ",").op("&&")(delivery_markers),
    )
    tasks = (await db.execute(query.add_columns(marker, marker_by_ga).where(
        Task.is_active.is_(True), Task.work_staff_filter(),
        Task.created_at < end, Task.start_date < end, Task.due_date >= start,
        or_(func.string_to_array(marker, ",").op("&&")(delivery_markers), Task.id.in_(personal_candidates)),
    ))).all()
    if not tasks:
        return []

    owners = defaultdict(set)
    for task, *_ in tasks:
        if task.assigned_to:
            owners[task.id].add(task.assigned_to)
    for task_id, user_id in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id)
                              .where(TaskAssignee.task_id.in_([task.id for task, *_ in tasks])))).all():
        owners[task_id].add(user_id)

    people = (await db.execute(select(User, DiscordLink.discord_user_id).outerjoin(
        DiscordLink, (DiscordLink.user_id == User.id) & DiscordLink.enabled.is_(True)
        & (DiscordLink.guild_id == guild_id),
    ).where(User.id.in_({user_id for ids in owners.values() for user_id in ids}), User.work_staff_filter()))).all()
    identities = {user.id: (user, discord_id) for user, discord_id in people}
    choices = await personal_choices(db, [task_id for task_id, members in owners.items() if len(members) > 1], day)
    names = {user.id: user.full_name or user.username or user.email for user, _ in people}
    department_codes = dict((await db.execute(select(Department.id, Department.code))).tuples().all())
    person_order = await weekly_planner_user_sort_keys(db, set(identities), department_codes)
    rows = []
    for task, project, marker, marker_by_ga in tasks:
        system = bool(task.system_template_origin_id or task.system_task_slot_id)
        title = _clean_task_title(task.title, is_system_task=system)
        status = str(getattr(task.status, "value", task.status)).upper()
        is_paused = pause_until_on_day(task.pause_periods, day) is not None
        fill, foreground, eight_am = task_row_appearance({
            "title": title,
            "status": status,
            "deadline_important": task.is_deadline_important,
            "is_system_task": system,
            "is_paused": is_paused,
            "eight_am": task.due_date is not None and _local_time(task.due_date) == "08:00",
        })
        assignees = [identities[user_id] for user_id in owners[task.id] if user_id in identities]
        for user, discord_id in assignees or [(None, None)]:
            user_id = user.id if user else None
            choice = choices.get((task.id, str(user_id), "marker"))
            owner_marker = choice["value"] if choice is not None else marker
            owner_marker_by_ga = choice.get("marker_by_ga", False) if choice is not None else marker_by_ga
            markers = set((owner_marker or "").split(","))
            slots = [slot for slot in DEADLINES if slot in markers or "M2_M3" in markers]
            if not slots:
                continue
            person = names.get(user_id)
            department = _m3_department_code_label(user.department_id or task.department_id, department_codes) if user else "-"
            row = {
                "id": f"{task.id}:{user_id}", "task_id": str(task.id),
                "user_id": str(user_id) if user_id else None,
                "status": status, "deadline_important": bool(task.is_deadline_important),
                "is_paused": is_paused,
                "person": person or "Pa përgjegjës", "initials": _initials(person),
                "department": department, "project": project or "—",
                "am_pm": _m3_am_pm_label(task), "task_type": _m3_task_type_label(task),
                "title": title, "symbol": one_h_marker_label(owner_marker, bool(owner_marker_by_ga)), "slots": slots,
                "fill": fill, "foreground": foreground, "eight_am": eight_am,
                "discord_id": discord_id,
            }
            sort_key = (
                *person_order.get(user_id, UNASSIGNED_ORDER),
                *common_view_task_sort_key(task, names, {task.id: {user_id}} if user else None),
                row["id"],
            )
            rows.append((sort_key, row))
    return [row for _, row in sorted(rows, key=lambda item: item[0])]


async def _staff_guild(db: AsyncSession) -> str | None:
    if settings.DISCORD_GUILD_ID:
        return settings.DISCORD_GUILD_ID
    # Channel snowflakes are globally unique. Only trust the existing, scoped archive.
    return await db.scalar(select(GaDiscordChannelMessage.guild_id).where(
        GaDiscordChannelMessage.channel_id == settings.DISCORD_GA_REPLIES_CHANNEL_ID,
    ).limit(1))


async def _archived_messages(db: AsyncSession, guild_id: str, authors: set[str], day: date, now: datetime) -> list[dict]:
    channel = GaDiscordChannelMessage
    start = datetime.combine(day, time.min, now.tzinfo)
    end = datetime.combine(day + timedelta(days=1), time.min, now.tzinfo)
    rows = (await db.execute(select(channel.id, channel.author_discord_id, channel.content,
                                   channel.created_at, channel.edited_at, channel.attachments)
                             .where(channel.guild_id == guild_id,
                                    channel.channel_id == settings.DISCORD_GA_REPLIES_CHANNEL_ID,
                                    channel.author_discord_id.in_(authors),
                                    channel.created_at >= start, channel.created_at < end))).all()
    return [{"id": message_id, "author": {"id": author}, "content": content, "timestamp": created.isoformat(),
             "edited_timestamp": edited.isoformat() if edited else None, "attachments": attachments}
            for message_id, author, content, created, edited, attachments in rows]


async def _channel_messages(day: date, now: datetime) -> list[dict]:
    token = settings.GA_DISCORD_MENTIONS_BOT_TOKEN or settings.DISCORD_BOT_TOKEN
    if not (token and settings.DISCORD_GA_REPLIES_CHANNEL_ID):
        raise ValueError("Discord staff channel is not configured")
    channel = settings.DISCORD_GA_REPLIES_CHANNEL_ID
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    start = datetime.combine(day, time.min, now.tzinfo)
    end = min(start + timedelta(days=1), now)
    before = (int(end.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22
    messages = []
    has_readable_content = False
    async with httpx.AsyncClient(timeout=8, headers={"Authorization": f"Bot {token}"}) as client:
        while True:
            response = await client.get(url, params={"before": str(before), "limit": 100})
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):
                raise ValueError("Invalid Discord history response")
            has_readable_content |= any(
                (item.get("content") or item.get("attachments")) and not item["author"].get("bot")
                for item in page
            )
            for message in page:
                sent_at = datetime.fromisoformat(message["timestamp"])
                if start <= sent_at < end:
                    messages.append(message)
            if len(page) < 100 or datetime.fromisoformat(page[-1]["timestamp"]) < start:
                break
            cursor = int(page[-1]["id"])
            if cursor >= before:
                raise ValueError("Discord history did not advance")
            before = cursor
        # Discord also returns an empty array when Read Message History is absent.
        if not has_readable_content:
            response = await client.get(url, params={"limit": 20})
            response.raise_for_status()
            if not any(item.get("content") and not item["author"].get("bot") for item in response.json()):
                raise ValueError("Discord message content could not be verified")
    return messages


def _delivery_details(message: dict, *, live: bool) -> dict:
    attachments = []
    channel_path = f"/attachments/{settings.DISCORD_GA_REPLIES_CHANNEL_ID}/"
    for attachment in message.get("attachments") or []:
        name = attachment.get("filename") or attachment.get("name")
        if not name:
            continue
        file = {"name": name}
        url = attachment.get("url")
        if live and isinstance(url, str):
            try:
                asset = urlsplit(url)
            except ValueError:
                pass
            else:
                if (asset.scheme == "https" and asset.netloc in {"cdn.discordapp.com", "media.discordapp.net"}
                        and asset.path.startswith(channel_path)):
                    file["url"] = url
        attachments.append(file)
    return {"content": message.get("content", ""), "attachments": attachments}


def _delivery_results(
    rows: list[dict], messages: list[dict] | None, day: date, now: datetime, *,
    guild_id: str | None = None, complete: bool = True, include_details: bool = False,
) -> list[dict]:
    titles = Counter((row["discord_id"], _normalize(row["title"])) for row in rows)
    matches = defaultdict(dict)
    for message in messages or []:
        author = message["author"]
        if author.get("bot") or message.get("webhook_id") or message.get("type", 0) not in {0, 19}:
            continue
        sent_at = datetime.fromisoformat(message["timestamp"])
        edited = message.get("edited_timestamp")
        # The first verifiable version of the current title is the edited version.
        verified_at = (datetime.fromisoformat(edited) if edited else sent_at).astimezone(now.tzinfo)
        if sent_at.astimezone(now.tzinfo).date() != day or verified_at.date() != day:
            continue
        for title in _message_titles(message.get("content", "")):
            matches[(author["id"], title)][message["id"]] = (verified_at, message)

    deadlines = {slot: datetime.combine(day, time.fromisoformat(value), now.tzinfo) for slot, value in DEADLINES.items()}
    result = []
    for row in rows:
        key = (row["discord_id"], _normalize(row["title"]))
        evidence = sorted(matches[key].values(), key=lambda item: item[0])
        deliveries = {}
        for slot in row["slots"]:
            applicable = evidence
            if len(row["slots"]) == 2:
                applicable = [(at, message) for at, message in evidence
                              if (at <= deadlines["M2"]) == (slot == "M2")]
            status = "pending" if now <= deadlines[slot] else "missing"
            record = {"status": status}
            if not row["discord_id"]:
                record["status"] = "unlinked"
            elif key[1] == "-" or titles[key] > 1:
                record["status"] = "ambiguous"
            elif applicable:
                at, message = applicable[0]
                message_id = message["id"]
                record = {
                    "status": "on_time" if at <= deadlines[slot] else "late",
                    "verified_at": at.isoformat(),
                    "url": f"https://discord.com/channels/{guild_id or settings.DISCORD_GUILD_ID}/{settings.DISCORD_GA_REPLIES_CHANNEL_ID}/{message_id}",
                }
                if include_details:
                    record["details"] = _delivery_details(message, live=complete)
            elif messages is None or not complete:
                record["status"] = "unavailable"
            deliveries[slot] = record
        result.append({**{key: value for key, value in row.items() if key not in {"discord_id", "slots"}},
                       "deliveries": deliveries})
    return result


async def checked_deliveries(
    db: AsyncSession, day: date, *, include_details: bool = False,
) -> tuple[datetime, str, bool, list[dict]]:
    now = datetime.now(report_timezone())
    guild_id = await _staff_guild(db)
    rows = await _task_rows(db, day, now.date(), guild_id)
    messages: list[dict] | None = None
    source = "unavailable" if rows and not guild_id else "not_needed"
    authors = {row["discord_id"] for row in rows if row["discord_id"]}
    if authors and guild_id:
        try:
            async with asyncio.timeout(15):
                messages = await _channel_messages(day, now)
            source = "live"
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            if settings.GA_DISCORD_MENTIONS_BOT_TOKEN or settings.DISCORD_BOT_TOKEN:
                log.warning("Discord task delivery history unavailable (%s)", type(exc).__name__)
            messages = await _archived_messages(db, guild_id, authors, day, now)
            source = "archive" if messages else "unavailable"
    comment_model = DiscordTaskDeliveryComment
    comments_available = await _comments_available(db)
    comments = dict((await db.execute(select(comment_model.row_id, comment_model.comment).where(
        comment_model.report_date == day,
    ))).tuples().all()) if rows and comments_available else {}
    checked = _delivery_results(rows, messages, day, now, guild_id=guild_id, complete=source == "live",
                                include_details=include_details)
    return now, source, comments_available, [{**row, "comment": comments.get(row["id"], "")} for row in checked]


async def with_discord_delivery(db: AsyncSession, report: dict, slot: str) -> dict:
    if "delivery" not in report["data"]:
        return report
    day = date.fromisoformat(report["report_date"])
    _, _, _, rows = await checked_deliveries(db, day, include_details=True)
    attendance = await load_report_attendance(db, day)
    report_task_ids = {row["task_id"] for row in report["data"]["delivery"]}
    deliveries = [
        {**row, "assignees": row["initials"] or "—", "marker": row["symbol"], "discord_delivery": row["deliveries"][slot],
         "delivery_note_editable": row["task_id"] in report_task_ids}
        for row in rows if slot in row["deliveries"] and not attendance.excludes(row["user_id"], row["person"])
    ]
    return {**report, "discord_delivery_slot": slot, "data": {**report["data"], "delivery": deliveries}}


def delivery_text(row: dict) -> str:
    delivery = row["discord_delivery"]
    label = {"on_time": "PO", "late": "PO (me vonesë)", "missing": "JO", "pending": "Në pritje",
             "unlinked": "Pa lidhje Discord", "ambiguous": "Titull i paqartë", "unavailable": "I paverifikuar"}[delivery["status"]]
    if delivery.get("verified_at"):
        return f"{label} · {_local_time(datetime.fromisoformat(delivery['verified_at']))}"
    return label


async def build_report(db: AsyncSession, day: date) -> dict:
    now, source, comments_available, checked = await checked_deliveries(db, day, include_details=True)
    slot_day = effective_slot_date(day)
    differences = await reporting_differences(db, day, now, marker_day=current_effective_marker_date(),
                                              slot_day=slot_day)
    return {
        "report_date": day.isoformat(), "today": now.date().isoformat(),
        "checked_at": now.isoformat(), "timezone": str(now.tzinfo), "discord_source": source,
        "comments_available": comments_available, "deadlines": DEADLINES,
        "rows": checked,
        "reporting_differences": await _format_reporting_differences(db, differences),
        "missing_slot_date": slot_day.isoformat(),
        "missing_slots": await _missing_slot_tasks(db, day, slot_day),
        "missing_morning_coverage": await _missing_morning_coverage(db, day, now.date()),
    }


def _covers_morning(*, is_one_h, slot, personal_with_someone, period, marker):
    if is_one_h and slot == "10:00":
        return True
    return (period or "").strip().upper() in {"", "AM", "AM/PM"} and (
        personal_with_someone or "F" in (marker or "").split(",")
    )


def _person_initials(user) -> set[str]:
    return {_initials(value) for value in (user.full_name, user.username, user.email.split("@")[0]) if value}


async def _missing_morning_coverage(db: AsyncSession, day: date, today: date) -> list[dict]:
    users = (await db.scalars(select(User).where(User.is_active.is_(True), User.work_staff_filter()))).all()
    attendance = await load_report_attendance(db, day)
    initials_by_id = {user.id: _person_initials(user) for user in users}
    eligible = {user.id: user for user in users if user.role != UserRole.ADMIN
                and not initials_by_id[user.id].intersection({"GA", "KA", "HV", "HS", "HSH"})
                and not attendance.excludes(user.id, user.full_name)}
    if not eligible:
        return []
    counterpart_codes = set().union(*initials_by_id.values(), {"GA", "KA", "HV", "GENT", "GENTI", "GT"})
    tasks = (await db.scalars(select(Task).where(Task.is_active.is_(True), Task.work_staff_filter(),
        common_view_task_date_window_filter(day, day)))).all()
    owners, _ = await choice_members(db, tasks)
    slots = await slot_values(db, tasks, day) if tasks else {}
    personal = await personal_choices(db, [task.id for task in tasks if len(owners[task.id]) > 1], day)
    historical_markers = {}
    if day < today and tasks:
        history = (await db.execute(select(TaskOneHMarkerHistory.task_id, TaskOneHMarkerHistory.one_h_marker).where(
            TaskOneHMarkerHistory.task_id.in_([task.id for task in tasks]), TaskOneHMarkerHistory.marker_date <= day,
        ).distinct(TaskOneHMarkerHistory.task_id).order_by(
            TaskOneHMarkerHistory.task_id, TaskOneHMarkerHistory.marker_date.desc(),
        ))).all()
        historical_markers = dict(history)
    personal_group_members = defaultdict(set)
    for task in tasks:
        if task.is_personal:
            personal_group_members[group_key(task)].update(owners[task.id])
    covered = set()
    for task in tasks:
        assigned = owners[task.id]
        candidates = assigned.intersection(eligible).difference(covered)
        if not candidates:
            continue
        marker = historical_markers.get(task.id, task.one_h_marker
                                        if day == today or not task.one_h_marker_date or task.one_h_marker_date <= day else None)
        participants = set()
        has_coassignee = False
        if task.is_personal:
            has_coassignee = len(personal_group_members[group_key(task)]) > 1
            title = parse_marked_note_content(task.title).text.strip()
            prefix = PERSONAL_OWNER_PREFIX.match(title)
            if prefix:
                participants = {value.strip().upper() for value in re.split(r"[:/]", prefix.group())} & counterpart_codes
        for owner in candidates:
            own_slot = personal.get((task.id, str(owner), "slot"))
            own_marker = personal.get((task.id, str(owner), "marker"))
            if _covers_morning(
                is_one_h=task.is_1h_report,
                slot=own_slot["value"] if own_slot is not None else slots.get(task.id, task.one_h_report_slot),
                personal_with_someone=has_coassignee or bool(participants - initials_by_id[owner]),
                period=task.finish_period,
                marker=own_marker["value"] if own_marker is not None else marker,
            ):
                covered.add(owner)
    missing = set(eligible) - covered
    if not missing:
        return []
    departments = dict((await db.execute(select(Department.id, Department.code))).tuples().all())
    order = await weekly_planner_user_sort_keys(db, missing, departments)
    return [{
        "id": str(owner), "initials": _initials(eligible[owner].full_name), "person": eligible[owner].full_name,
        "department": _m3_department_code_label(eligible[owner].department_id, departments),
    } for owner in sorted(missing, key=lambda owner: (*order.get(owner, UNASSIGNED_ORDER), str(owner)))]


async def _missing_slot_tasks(db: AsyncSession, day: date, slot_day: date) -> list[dict]:
    tasks = (await db.scalars(select(Task).where(
        Task.is_1h_report.is_(True), Task.is_active.is_(True), Task.work_staff_filter(),
        common_view_task_date_window_filter(day, day),
    ).order_by(Task.id))).all()
    if not tasks:
        return []
    owners, names = await choice_members(db, tasks)
    slots = await slot_values(db, tasks, slot_day)
    personal = await personal_choices(db, [task.id for task in tasks if len(owners[task.id]) > 1],
                                      slot_day, marker_day=day)
    rows = []
    for task in tasks:
        assignees = owners[task.id].intersection(names)
        if not assignees and owners[task.id]:
            continue
        for owner in assignees or {None}:
            slot = personal.get((task.id, str(owner), "slot"))
            effective = slot["value"] if slot is not None else slots.get(task.id, task.one_h_report_slot)
            if not (effective or "").strip():
                rows.append((task, names.get(owner), owner, personal.get((task.id, str(owner), "marker"))))
    return await _format_missing_slots(db, rows)


async def _format_missing_slots(db: AsyncSession, rows) -> list[dict]:
    if not rows:
        return []
    owners = {owner for _, _, owner, _ in rows if owner}
    departments = dict((await db.execute(select(Department.id, Department.code))).tuples().all())
    owner_departments = dict((await db.execute(select(User.id, User.department_id).where(User.id.in_(owners)))).tuples().all())
    person_order = await weekly_planner_user_sort_keys(db, owners, departments)
    project_ids = {task.project_id for task, *_ in rows if task.project_id}
    projects = dict((await db.execute(select(Project.id, Project.title).where(Project.id.in_(project_ids)))).tuples().all())
    formatted = []
    for task, name, owner, marker in rows:
        fill, foreground, eight_am = _task_appearance(task, task.title)
        sort_key = (
            *person_order.get(owner, UNASSIGNED_ORDER),
            *common_view_task_sort_key(task, {owner: name} if owner else {}, {task.id: {owner}} if owner else None),
            str(task.id),
        )
        formatted.append((sort_key, {
            "id": f"{task.id}:{owner}", "task_title": task.title, "person": name or "Pa përgjegjës",
            "initials": _initials(name), "department": _m3_department_code_label(
                owner_departments.get(owner) or task.department_id, departments,
            ),
            "am_pm": _m3_am_pm_label(task), "project": projects.get(task.project_id, "—"),
            "symbol": one_h_marker_label(marker["value"], marker.get("marker_by_ga", False))
            if marker is not None else one_h_marker_label(task.one_h_marker, task.one_h_marker_by_ga),
            "fill": fill, "foreground": foreground, "eight_am": eight_am,
        }))
    return [row for _, row in sorted(formatted, key=lambda item: item[0])]


def _task_appearance(task: Task | None, title: str) -> tuple[str, str, bool]:
    return task_row_appearance({
        "title": title,
        "status": task.status if task else None,
        "deadline_important": task.is_deadline_important if task else False,
        "is_system_task": bool(task and (task.system_template_origin_id or task.system_task_slot_id)),
        "eight_am": bool(task and task.due_date and _local_time(task.due_date) == "08:00"),
    })


async def _format_reporting_differences(db: AsyncSession, differences: list[dict]) -> list[dict]:
    if not differences:
        return []
    task_ids = {UUID(row["task_id"]) for row in differences}
    tasks = {str(task.id): task for task in await db.scalars(select(Task).where(Task.id.in_(task_ids)))}
    person_order = await weekly_planner_user_sort_keys(db, {UUID(row["owner_id"]) for row in differences})
    group_ids = {}
    formatted = []
    for row in differences:
        task_id = row["task_id"]
        task = tasks.get(task_id)
        task_group_id = group_ids.setdefault(group_key(task), task_id) if task is not None else task_id
        owner_id = UUID(row["owner_id"])
        fill, foreground, eight_am = _task_appearance(task, row["task_title"])
        sort_key = (
            *person_order.get(owner_id, UNASSIGNED_ORDER),
            0 if task and task.is_deadline_important else 1,
            0 if eight_am else 1,
            task.fast_task_order if task and task.fast_task_order is not None else 10**9,
            _clean_task_title(row["task_title"], is_system_task=True).casefold(),
        )
        formatted.append((sort_key, {
            **row, "task_group_id": task_group_id, "initials": _initials(row["person"]), "fill": fill,
            "foreground": foreground, "eight_am": eight_am,
            "peers": [{**peer, "initials": _initials(peer["person"])} for peer in row["peers"]],
        }))
    return [row for _, row in sorted(formatted, key=lambda item: item[0])]


async def _comments_available(db: AsyncSession) -> bool:
    return bool(await db.scalar(select(func.to_regclass(DiscordTaskDeliveryComment.__tablename__))))


async def save_comment(db: AsyncSession, day: date, row_id: str, comment: str) -> str:
    if not await _comments_available(db):
        raise HTTPException(503, "Ruajtja e komenteve nuk është aktive në këtë server.")
    today = datetime.now(report_timezone()).date()
    row = next((row for row in await _task_rows(db, day, today) if row["id"] == row_id), None)
    if row is None:
        raise HTTPException(404, "Rreshti nuk gjendet në raportin e kësaj date.")
    model = DiscordTaskDeliveryComment
    if comment:
        statement = insert(model).values(report_date=day, row_id=row_id, task_id=UUID(row["task_id"]), comment=comment)
        await db.execute(statement.on_conflict_do_update(
            index_elements=[model.report_date, model.row_id], set_={"comment": statement.excluded.comment},
        ))
    else:
        await db.execute(delete(model).where(model.report_date == day, model.row_id == row_id))
    await db.commit()
    return comment
