"""GA assistant agenda: one list of everything on the GA's day, from every source.

Sources and the rules they mirror:

* PrimeFlow tasks, classified like the first table of ``/admin-tasks``
  (``frontend/src/app/(app)/admin-tasks/page.tsx`` allTasksTableRows):
  ``GA_TASK``  = GA is a real assignee or the WAITING_CONFIRMATION confirmer ("GA Tasks").
  ``BZ``       = GA is only an alignment (BZ) person, by task or system template ("BZ ME GA Tasks").
  ``F_TASK``   = any other active task carrying the task symbol ``F`` = "DET FIZIKISHT (ME GA)"
                 (``tasks.one_h_marker``), selected like M1 "FIZIKISHT ME GA?".
  ``GA_MARKED_TASK`` = any other active task carrying the GA symbol (stored as ``FLAG``),
                       selected on the same days as an F task.
* Meetings, like the GA Time Table: every visible external meeting plus manual
  internal meetings, expanded per day with their held/canceled status.
* Outlook events and Microsoft To Do tasks of the organizer mailbox (GA only).
  To Do tasks without a date show as untimed on every day until done; the
  "Flagged Emails" list is not a reminder list and is skipped.
* iPhone reminders imported by "iPhone Sync" into the GA Time Table (shown there as
  "R: HH:MM: ..."), source ``iphone_sync`` (GA only). Completion is queued for
  the paired Shortcut. A reminder that is also in To Do appears once.
* Discord messages that mention the GA (``ga_discord_mentions``, GA only): untimed
  on the day they were written until marked seen/done.

Times: a per-day assistant override (``ga_assistant_item_times``) wins, then the
BZ time of the system template, then the 1H slot, then a due time on the task.
An explicit AM/PM supplies a fallback time. Items without a time or period are untimed.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import and_, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.ga_discord_mention import GaDiscordMention  # noqa: F401 - mapper registration
from app.models.ga_icloud_sync_connection import GaIcloudSyncConnection
from app.models.ga_time_slot_entry import GaTimeSlotEntry
from app.models.meeting import Meeting
from app.models.meeting_note import MeetingNote
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.oauth import GaAssistantItemTime
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.task import Task
from app.models.task_alignment_user import TaskAlignmentUser
from app.models.task_assignee import TaskAssignee
from app.models.task_user_comment import TaskUserComment
from app.models.user import User
from app.services.meeting_scheduler import meeting_occurrence_window
from app.services.after_break_report import _task_covers_day  # Common View day rule (M1/End Week BZ)
from app.services.ga_icloud_sync import PENDING_COMPLETE
from app.services.morning_report import _marked_task_identity  # M1 grouping of linked marked copies
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting
from app.services.task_marker import ONE_H_MARKER_SYMBOLS

logger = logging.getLogger(__name__)

KIND_GA_TASK = "GA_TASK"
KIND_BZ = "BZ"
KIND_F_TASK = "F_TASK"
KIND_GA_MARKED_TASK = "GA_MARKED_TASK"
KIND_MEETING = "MEETING"
KIND_EVENT = "EVENT"
KIND_REMINDER = "REMINDER"
KIND_DISCORD = "DISCORD"
TASK_KINDS = {KIND_GA_TASK, KIND_BZ, KIND_F_TASK, KIND_GA_MARKED_TASK}
GA_MARKERS = {"F", "FLAG"}
DAYPART_STARTS = {"AM": time(9), "PM": time(13, 30)}

PREFIX_TASK = "pf_task:"
PREFIX_MEETING = "pf_meeting:"
PREFIX_EVENT = "ms_event:"
PREFIX_TODO = "todo:"
PREFIX_TIME_TABLE = "tt:"
PREFIX_DISCORD = "dc:"
SOURCE_IPHONE_SYNC = "iphone_sync"
# The iPhone Shortcut re-sends [today - 7 days, today + 60 days] on every run
# (docs/GA_ICLOUD_SHORTCUT_SYNC.md); older rows are no longer refreshed.
IPHONE_SYNC_LOOKBACK_DAYS = 7
IPHONE_SYNC_STALE_HOURS = 24
TODO_ID_SEPARATOR = "::"

# How far back unfinished work is collected for leftovers and the "today" view.
LEFTOVER_LOOKBACK_DAYS = 120


def ga_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.GA_TIMEZONE)
    except Exception:
        return ZoneInfo("Europe/Belgrade")


def local_date(value: datetime | None, tz: ZoneInfo) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz).date()


def parse_hhmm(value: str | None) -> time | None:
    if value is None or value == "":
        return None
    try:
        hours, minutes = str(value).strip()[:5].split(":")
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        raise ValueError("time must be HH:MM (24h)")


def markers_of(task: Task) -> list[str]:
    return [part.strip().upper() for part in (task.one_h_marker or "").split(",") if part.strip()]


def task_is_open(task: Task) -> bool:
    status = (task.status.value if hasattr(task.status, "value") else str(task.status or "")).upper()
    return status != "DONE" and task.completed_at is None


def task_status(task: Task) -> str:
    value = task.status.value if hasattr(task.status, "value") else str(task.status or "")
    return value.upper() or ("DONE" if task.completed_at else "TODO")


def task_plan_day(task: Task, tz: ZoneInfo) -> date | None:
    """Mirror getTaskDateIso: a done system task keeps its original planned day."""
    if task.system_template_origin_id is not None and not task_is_open(task):
        return local_date(task.original_due_date or task.origin_run_at or task.start_date or task.due_date, tz)
    return local_date(task.due_date or task.start_date, tz)


def due_time_of(task: Task, tz: ZoneInfo) -> time | None:
    """A meaningful due time: not the date-only midnight / end-of-day placeholders."""
    if task.due_date is None:
        return None
    value = task.due_date if task.due_date.tzinfo else task.due_date.replace(tzinfo=timezone.utc)
    local = value.astimezone(tz).time().replace(second=0, microsecond=0)
    if local in (time(0, 0), time(23, 59)):
        return None
    return local


def business_days_late(due: date | None, today: date) -> int | None:
    if due is None or due >= today:
        return None
    days, cursor = 0, due
    while cursor < today:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days or None


@dataclass
class AgendaItem:
    id: str
    source: str
    kind: str
    title: str
    day: date | None
    start: datetime | None = None
    end: datetime | None = None
    time_basis: str | None = None
    am_pm: str | None = None
    due_date: str | None = None
    original_due_date: str | None = None
    days_late: int | None = None
    status: str | None = None
    priority: str | None = None
    bz_with: list[str] = field(default_factory=list)
    frequency: str | None = None
    comment: str | None = None
    can_complete: bool = False
    url: str | None = None
    is_open: bool = True
    markers: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    item_key: str = ""
    linked_ids: list[str] = field(default_factory=list)
    meeting_type: str | None = None
    held: bool | None = None
    join_url: str | None = None
    notes_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        daypart = None
        symbols = []
        if self.kind in TASK_KINDS:
            daypart = self.am_pm if self.am_pm in DAYPART_STARTS else None
            if daypart is None and self.start is not None:
                clock = self.start.time()
                if clock >= DAYPART_STARTS["PM"]:
                    daypart = "PM"
                elif clock >= DAYPART_STARTS["AM"]:
                    daypart = "AM"
            symbols = [ONE_H_MARKER_SYMBOLS.get(marker, marker) for marker in self.markers]
        return {
            "id": self.id,
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "day": self.day.isoformat() if self.day else None,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "time_basis": self.time_basis,
            "am_pm": self.am_pm,
            "daypart": daypart,
            "due_date": self.due_date,
            "original_due_date": self.original_due_date,
            "days_late": self.days_late,
            "status": self.status,
            "status_label": "✓ në pritje për iPhone" if self.status == PENDING_COMPLETE else None,
            "is_open": self.is_open,
            "type": self.meeting_type,
            "held": self.held,
            "join_url": self.join_url,
            "notes_url": self.notes_url,
            "priority": self.priority,
            "bz_with": self.bz_with,
            "frequency": self.frequency,
            "comment": self.comment,
            "can_complete": self.can_complete,
            "url": self.url,
            "markers": self.markers,
            "symbols": symbols,
            "assignees": self.assignees,
            "linked_ids": self.linked_ids,
        }


@dataclass
class DayState:
    time_override: bool = False
    time_value: time | None = None
    removed: bool = False


def frontend_url(path: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/{path.lstrip('/')}"


async def load_day_states(db: AsyncSession, user_id: uuid.UUID, day_from: date, day_to: date) -> dict[tuple[str, date], DayState]:
    rows = (
        await db.execute(
            select(GaAssistantItemTime).where(
                GaAssistantItemTime.user_id == user_id,
                GaAssistantItemTime.day_date >= day_from,
                GaAssistantItemTime.day_date <= day_to,
            )
        )
    ).scalars().all()
    return {
        (row.item_key, row.day_date): DayState(
            time_override=bool(row.has_time_override),
            time_value=parse_hhmm(row.time_value) if row.time_value else None,
            removed=bool(row.removed),
        )
        for row in rows
    }


def _user_label(user: User | None) -> str:
    if user is None:
        return "?"
    return user.full_name or user.username or user.email


async def collect_task_items(
    db: AsyncSession, owner: User, day_from: date, day_to: date, *, today: date, tz: ZoneInfo
) -> list[AgendaItem]:
    owner_id = owner.id
    aligned_template_ids = set(
        (
            await db.execute(
                select(SystemTaskTemplateAlignmentUser.template_id).where(SystemTaskTemplateAlignmentUser.user_id == owner_id)
            )
        ).scalars().all()
    )
    assigned_ids = select(TaskAssignee.task_id).where(TaskAssignee.user_id == owner_id)
    aligned_ids = select(TaskAlignmentUser.task_id).where(TaskAlignmentUser.user_id == owner_id)
    delimited_markers = literal(",") + Task.one_h_marker + ","
    has_ga_marker = or_(delimited_markers.like("%,F,%"), delimited_markers.like("%,FLAG,%"))
    relevance = [
        Task.assigned_to == owner_id,
        Task.id.in_(assigned_ids),
        Task.id.in_(aligned_ids),
        and_(Task.status == "WAITING_CONFIRMATION", Task.confirmation_assignee_id == owner_id),
        and_(has_ga_marker, Task.work_staff_filter()),
    ]
    if aligned_template_ids:
        relevance.append(Task.system_template_origin_id.in_(aligned_template_ids))
    window_start = datetime.combine(min(day_from, today) - timedelta(days=LEFTOVER_LOOKBACK_DAYS), time.min, tzinfo=tz)
    window_end = datetime.combine(day_to + timedelta(days=1), time.min, tzinfo=tz)
    # Overlap with the window: also catches long tasks that start before and end after it.
    in_window = or_(
        and_(Task.due_date >= window_start, or_(Task.start_date.is_(None), Task.start_date < window_end)),
        and_(Task.due_date.is_(None), Task.start_date >= window_start, Task.start_date < window_end),
    )
    tasks = (
        await db.execute(
            select(Task).where(Task.is_active.is_(True), or_(*relevance), in_window).order_by(Task.due_date, Task.created_at)
        )
    ).scalars().all()
    if not tasks:
        return []
    task_ids = [task.id for task in tasks]

    assignee_rows = (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(task_ids)))).all()
    alignment_rows = (
        await db.execute(select(TaskAlignmentUser.task_id, TaskAlignmentUser.user_id).where(TaskAlignmentUser.task_id.in_(task_ids)))
    ).all()
    assignees: dict[uuid.UUID, set[uuid.UUID]] = {}
    for task_id, user_id in assignee_rows:
        assignees.setdefault(task_id, set()).add(user_id)
    for task in tasks:
        if task.assigned_to:
            assignees.setdefault(task.id, set()).add(task.assigned_to)
    task_alignment: dict[uuid.UUID, set[uuid.UUID]] = {}
    for task_id, user_id in alignment_rows:
        task_alignment.setdefault(task_id, set()).add(user_id)

    template_ids = {task.system_template_origin_id for task in tasks if task.system_template_origin_id}
    templates = {
        tpl.id: tpl
        for tpl in (
            await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id.in_(template_ids)))
        ).scalars().all()
    } if template_ids else {}

    comment_rows = (
        await db.execute(
            select(TaskUserComment.task_id, TaskUserComment.comment)
            .where(TaskUserComment.task_id.in_(task_ids))
            .order_by(TaskUserComment.task_id, TaskUserComment.updated_at.desc().nulls_last())
            .distinct(TaskUserComment.task_id)
        )
    ).all()
    comments = {task_id: comment for task_id, comment in comment_rows}

    user_ids = set().union(*assignees.values()) if assignees else set()
    users = {
        user.id: user for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    } if user_ids else {}

    items: dict[str, AgendaItem] = {}
    for task in tasks:
        plan_day = task_plan_day(task, tz)
        if plan_day is None:
            continue
        is_open = task_is_open(task)
        is_system = task.system_template_origin_id is not None
        template = templates.get(task.system_template_origin_id) if is_system else None
        real_assignee = owner_id in assignees.get(task.id, set())
        has_task_alignment = owner_id in task_alignment.get(task.id, set())
        has_template_alignment = bool(is_system and task.system_template_origin_id in aligned_template_ids)
        needs_confirmation = task_status(task) == "WAITING_CONFIRMATION" and task.confirmation_assignee_id == owner_id
        markers = markers_of(task)
        if real_assignee or needs_confirmation:
            kind = KIND_GA_TASK
        elif has_task_alignment or has_template_alignment:
            kind = KIND_BZ
        elif GA_MARKERS.intersection(markers):
            kind = KIND_F_TASK if "F" in markers else KIND_GA_MARKED_TASK
        else:
            continue

        if kind in {KIND_F_TASK, KIND_GA_MARKED_TASK}:
            # "F" = DET FIZIKISHT ME GA: the M1 rule (morning report "FIZIKISHT ME GA?") lists a
            # marked task on every day its Start-Due interval covers (Common View planning rule),
            # one row per group of linked copies. Unfinished marked work from before today is reported
            # once, on its due day, as a leftover.
            days = [
                day for day in _days(day_from, day_to)
                if _task_covers_day(task, day) and (not is_open or day >= today)
            ]
            if is_open and day_from <= plan_day < today:
                days.append(plan_day)
            identity = f"marked:{_marked_task_identity(task)}:{','.join(sorted(markers))}"
        else:
            # GA TASKS / BZ ME GA TASKS: one row on the task's planned day (admin-tasks getTaskDateIso).
            if (plan_day < day_from and not is_open) or plan_day > day_to:
                continue
            days = [plan_day]
            # One logical task per system template and day, and per fast-task group
            # (Common View merges assignees of every copy the same way).
            if is_system:
                identity = f"tpl:{task.system_template_origin_id}"
            elif task.fast_task_group_id:
                identity = f"grp:{task.fast_task_group_id}"
            else:
                identity = f"task:{task.id}"

        people = sorted(_user_label(users.get(uid)) for uid in assignees.get(task.id, set()))
        bz_time = template.alignment_time if (has_template_alignment and template is not None) else None
        for day in days:
            dedupe = f"{identity}:{day.isoformat()}"
            existing = items.get(dedupe)
            if existing is not None:
                existing.assignees = sorted(set(existing.assignees) | set(people))
                if existing.kind == KIND_BZ:
                    existing.bz_with = existing.assignees
                # Prefer the owner's own copy so done/postpone act on it.
                if kind == KIND_GA_TASK and existing.kind != KIND_GA_TASK:
                    existing.kind, existing.id, existing.item_key = kind, f"{PREFIX_TASK}{task.id}", f"{PREFIX_TASK}{task.id}"
                    existing.can_complete = is_open
                continue
            item = AgendaItem(
                id=f"{PREFIX_TASK}{task.id}",
                item_key=f"{PREFIX_TASK}{task.id}",
                source="primeflow",
                kind=kind,
                title=task.title or "-",
                day=day,
                am_pm=(task.finish_period.value if hasattr(task.finish_period, "value") else task.finish_period) or None,
                due_date=local_date(task.due_date, tz).isoformat() if task.due_date else None,
                original_due_date=local_date(task.original_due_date, tz).isoformat() if task.original_due_date else None,
                days_late=business_days_late(plan_day, today) if is_open else None,
                status=task_status(task),
                priority="BLLOK" if task.is_bllok else (task.priority.value if hasattr(task.priority, "value") else task.priority),
                bz_with=people if kind == KIND_BZ else [],
                frequency=(template.frequency if template is not None else None),
                comment=comments.get(task.id),
                can_complete=bool(is_open and kind == KIND_GA_TASK),
                url=frontend_url(f"/tasks/{task.id}"),
                is_open=is_open,
                markers=markers,
                assignees=people,
            )
            if bz_time is not None:
                item.start, item.time_basis = datetime.combine(day, bz_time, tzinfo=tz), "koha_bz"
            elif task.is_1h_report and task.one_h_report_slot:
                item.start, item.time_basis = datetime.combine(day, parse_hhmm(task.one_h_report_slot), tzinfo=tz), "one_h_slot"
            elif (due_time := due_time_of(task, tz)) is not None and day == plan_day:
                item.start, item.time_basis = datetime.combine(day, due_time, tzinfo=tz), "due"
            elif (part_start := DAYPART_STARTS.get(item.am_pm)) is not None:
                item.start, item.time_basis = datetime.combine(day, part_start, tzinfo=tz), "ampm"
            items[dedupe] = item
    result = list(items.values())
    await _set_bz_held(db, owner, result)
    return result


async def _set_bz_held(db: AsyncSession, owner: User, items: list[AgendaItem]) -> None:
    # A BZ occurrence has its own concrete task ID, including system task instances.
    bz_items = {uuid.UUID(item.id.removeprefix(PREFIX_TASK)): item for item in items if item.kind == KIND_BZ}
    if not bz_items:
        return
    held = set((await db.execute(
        select(AuditLog.entity_id).where(
            AuditLog.entity_type == "ga_assistant",
            AuditLog.action == "GA_ASSISTANT_BZ_HELD",
            AuditLog.actor_user_id == owner.id,
            AuditLog.entity_id.in_(bz_items),
        ).distinct()
    )).scalars().all())
    for task_id, item in bz_items.items():
        item.meeting_type = "BZ"
        item.held = task_id in held


def _days(day_from: date, day_to: date):
    day = day_from
    while day <= day_to:
        yield day
        day += timedelta(days=1)


def _teams_join_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname in {"teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"}:
            return url
    except ValueError:
        pass
    return None


async def collect_meeting_items(db: AsyncSession, owner: User, day_from: date, day_to: date, *, tz: ZoneInfo) -> list[AgendaItem]:
    """GA Time Table meetings: visible external meetings and manual internal meetings."""
    meetings = (
        await db.execute(
            select(Meeting).where(
                Meeting.starts_at.is_not(None),
                or_(
                    Meeting.meeting_type == "external",
                    and_(
                        Meeting.meeting_type == "internal",
                        Meeting.paired_external_meeting_id.is_(None),
                        Meeting.pre_external_meeting_id.is_(None),
                    ),
                ),
                or_(
                    Meeting.recurrence_type.in_(["weekly", "monthly", "yearly"]),
                    and_(
                        Meeting.starts_at >= datetime.combine(day_from, time.min, tzinfo=tz),
                        Meeting.starts_at < datetime.combine(day_to + timedelta(days=1), time.min, tzinfo=tz),
                    ),
                ),
            )
        )
    ).scalars().all()
    meetings = [meeting for meeting in meetings if is_common_view_visible_meeting(meeting)]
    if not meetings:
        return []
    meeting_ids = [meeting.id for meeting in meetings]
    statuses = {
        (row.meeting_id, row.occurrence_date): row.status
        for row in (
            await db.execute(
                select(MeetingOccurrenceStatus).where(
                    MeetingOccurrenceStatus.meeting_id.in_(meeting_ids),
                    MeetingOccurrenceStatus.occurrence_date >= day_from,
                    MeetingOccurrenceStatus.occurrence_date <= day_to,
                )
            )
        ).scalars().all()
    }
    noted_occurrences = set((await db.execute(
        select(MeetingNote.meeting_id, MeetingNote.occurrence_date).where(
            MeetingNote.meeting_id.in_(meeting_ids),
            MeetingNote.occurrence_date >= day_from,
            MeetingNote.occurrence_date <= day_to,
        ).distinct()
    )).all())
    items: list[AgendaItem] = []
    day = day_from
    while day <= day_to:
        probe = datetime.combine(day, time(12, 0), tzinfo=tz)
        for meeting in meetings:
            window = meeting_occurrence_window(meeting, probe)
            if window is None:
                continue
            start, end = (value.astimezone(tz) for value in window)
            if start.date() != day:
                continue
            status = statuses.get((meeting.id, day)) or ""
            key = f"{PREFIX_MEETING}{meeting.id}@{day.isoformat()}"
            meeting_type = "INT" if meeting.meeting_type == "internal" else "EXT"
            items.append(
                AgendaItem(
                    id=key,
                    item_key=key,
                    source="primeflow",
                    kind=KIND_MEETING,
                    title=f"TAK {meeting_type}: {meeting.title}",
                    day=day,
                    start=start,
                    end=end,
                    time_basis="event",
                    status={"held": "Mbajtur", "canceled": "Anuluar"}.get(status, "PLANNED"),
                    can_complete=status == "",
                    is_open=status == "",
                    url=frontend_url("/admin-tasks#ga-time-table"),
                    meeting_type=meeting_type,
                    held=status == "held",
                    join_url=_teams_join_url(meeting.meeting_url),
                    notes_url=(
                        frontend_url(f"/meetings/{meeting.id}?date={day.isoformat()}")
                        if (meeting.id, day) in noted_occurrences else None
                    ),
                )
            )
        day += timedelta(days=1)
    return items


async def collect_microsoft_items(
    db: AsyncSession, owner: User, day_from: date, day_to: date, *, tz: ZoneInfo, include_completed: bool = False,
    today: date | None = None,
) -> tuple[list[AgendaItem], list[str]]:
    """Outlook events and To Do tasks of the organizer mailbox. Failures are reported, not raised."""
    from app.integrations.microsoft import fetch_calendar_events
    from app.integrations.microsoft_todo import TodoClient, TodoScopeMissing, ensure_todo_scope, parse_due_date, parse_graph_dt, split_body
    from app.services.microsoft_calendar_sync import get_shared_calendar_token

    warnings: list[str] = []
    items: list[AgendaItem] = []
    if not settings.MS_REDIRECT_URI:
        return items, ["Microsoft integration is not configured (MS_REDIRECT_URI)."]
    try:
        token = await get_shared_calendar_token(db, redirect_uri=settings.MS_REDIRECT_URI)
    except Exception as exc:  # network/Graph failures must not break the PrimeFlow agenda
        logger.warning("GA assistant: Microsoft token unavailable: %s", type(exc).__name__)
        return items, ["Microsoft connection is unavailable."]
    if token is None:
        return items, [f"No Microsoft connection for {settings.MS_ORGANIZER_EMAIL}."]

    start = datetime.combine(day_from, time.min, tzinfo=tz)
    end = datetime.combine(day_to + timedelta(days=1), time.min, tzinfo=tz)
    try:
        imported = set(
            (await db.execute(select(Meeting.microsoft_event_id).where(Meeting.microsoft_event_id.is_not(None)))).scalars().all()
        )
        for event in await fetch_calendar_events(token.access_token, start, end):
            if event.get("isCancelled") or event.get("id") in imported:
                continue
            ev_start = parse_graph_dt(event.get("start"), tz)
            ev_end = parse_graph_dt(event.get("end"), tz)
            if ev_start is None:
                continue
            all_day = bool(event.get("isAllDay"))
            key = f"{PREFIX_EVENT}{event.get('id')}"
            items.append(
                AgendaItem(
                    id=key, item_key=key, source="outlook", kind=KIND_EVENT, title=event.get("subject") or "(pa titull)",
                    day=ev_start.date(), start=None if all_day else ev_start, end=None if all_day else ev_end,
                    time_basis=None if all_day else "event", status="PLANNED", url=event.get("webLink"),
                    join_url=_teams_join_url((event.get("onlineMeeting") or {}).get("joinUrl") or event.get("onlineMeetingUrl")),
                )
            )
    except Exception as exc:
        logger.warning("GA assistant: Outlook events failed: %s", type(exc).__name__)
        warnings.append("Outlook events could not be read.")

    if not settings.MS_TODO_ENABLED:
        return items, warnings
    try:
        ensure_todo_scope(token.scope)
        client = TodoClient(token.access_token)
        current_day = today or datetime.now(tz).date()
        # An undated open To Do belongs to "today" (and later days asked for) until it is done.
        undated_day = max(day_from, current_day)
        for todo_list in await client.lists():
            if is_flagged_email_list(todo_list):
                continue
            for todo in await client.tasks(todo_list["id"], include_completed=include_completed):
                item = todo_to_item(todo, todo_list, tz=tz, parse_due_date=parse_due_date, parse_graph_dt=parse_graph_dt, split_body=split_body)
                if item.day is None:
                    if not item.is_open or undated_day > day_to:
                        continue
                    item.day = undated_day
                elif not (item.day <= day_to and (item.day >= day_from or item.is_open)):
                    continue
                items.append(item)
    except TodoScopeMissing as exc:
        warnings.append(str(exc))
    except Exception as exc:
        logger.warning("GA assistant: To Do failed: %s", type(exc).__name__)
        warnings.append("Microsoft To Do could not be read.")
    return items, warnings


def is_flagged_email_list(todo_list: dict) -> bool:
    """Outlook's "Flagged Emails" list mirrors flagged mail; it is not a reminder list."""
    wellknown = str(todo_list.get("wellknownListName") or "").casefold()
    name = str(todo_list.get("displayName") or "").strip().casefold()
    return wellknown == "flaggedemails" or name == "flagged emails"


def todo_to_item(todo: dict, todo_list: dict, *, tz: ZoneInfo, parse_due_date, parse_graph_dt, split_body) -> AgendaItem:
    due = parse_due_date(todo.get("dueDateTime"), tz)
    reminder = parse_graph_dt(todo.get("reminderDateTime"), tz) if todo.get("isReminderOn") else None
    day = due or (reminder.date() if reminder else None)
    notes, steps = split_body((todo.get("body") or {}).get("content"))
    status = str(todo.get("status") or "notStarted")
    is_open = status != "completed"
    key = f"{PREFIX_TODO}{todo_list['id']}{TODO_ID_SEPARATOR}{todo['id']}"
    return AgendaItem(
        id=key,
        item_key=key,
        source="microsoft_todo",
        kind=KIND_REMINDER,
        title=todo.get("title") or "(pa titull)",
        day=day,
        start=reminder if (reminder and day and reminder.date() == day) else None,
        time_basis="reminder" if reminder else None,
        due_date=due.isoformat() if due else None,
        status=status,
        priority="HIGH" if todo.get("importance") == "high" else None,
        comment=notes or None,
        can_complete=is_open,
        is_open=is_open,
        frequency=todo_list.get("displayName"),
        markers=[f"{'☑' if step.done else '☐'} {step.text}" for step in steps],
    )


_REMINDER_CONTENT = re.compile(r"^\s*REMINDER\s*(?:(\d{1,2}):(\d{2}))?\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)


def is_iphone_completion_key(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


def parse_reminder_content(content: str | None) -> tuple[time | None, bool, str, str | None]:
    """Split an iPhone Sync row ("REMINDER 09:30: title · notes").

    Returns (time, has_clock, title, notes). "REMINDER 00:00: ..." is a date-only
    reminder (no time); "REMINDER: ..." has no clock at all.
    """
    match = _REMINDER_CONTENT.match(content or "")
    if not match:
        return None, False, (content or "").strip() or "(pa titull)", None
    hours, minutes, rest = match.groups()
    at: time | None = None
    has_clock = hours is not None
    if has_clock:
        try:
            at = time(int(hours), int(minutes))
        except ValueError:
            at = None
        if at == time(0, 0):
            at = None
    title, sep, notes = rest.partition(" · ")
    return at, has_clock, title.strip() or "(pa titull)", (notes.strip() or None) if sep else None


async def collect_time_table_reminders(
    db: AsyncSession, owner: User, day_from: date, day_to: date, *, tz: ZoneInfo, today: date, now: datetime | None = None,
) -> tuple[list[AgendaItem], list[str]]:
    """GA Time Table "R:" rows imported from GA's paired iPhone.

    Unconfirmed completion requests remain visible until the Shortcut acknowledges them.
    """
    rows = (
        await db.execute(
            select(GaTimeSlotEntry, GaIcloudSyncConnection.last_synced_at)
            .join(GaIcloudSyncConnection, GaIcloudSyncConnection.id == GaTimeSlotEntry.sync_connection_id)
            .where(
                GaTimeSlotEntry.user_id == owner.id,
                GaTimeSlotEntry.source_type == "reminder",
                GaTimeSlotEntry.is_completed.is_(False),
                GaIcloudSyncConnection.revoked_at.is_(None),
                GaTimeSlotEntry.day_date <= day_to,
                GaTimeSlotEntry.falls_on_weekday(),
            )
            .order_by(GaTimeSlotEntry.day_date, GaTimeSlotEntry.start_time)
        )
    ).all()
    items: list[AgendaItem] = []
    warnings: list[str] = []
    last_sync: datetime | None = None
    seen: set[str] = set()
    for entry, synced_at in rows:
        if synced_at is None:
            continue
        last_sync = synced_at if last_sync is None else max(last_sync, synced_at)
        window_start = synced_at.astimezone(tz).date() - timedelta(days=IPHONE_SYNC_LOOKBACK_DAYS)
        pending = getattr(entry, "completion_requested_at", None) is not None
        if entry.day_date < window_start and not pending:
            continue
        at, has_clock, title, notes = parse_reminder_content(entry.content)
        day = entry.day_date
        source = getattr(entry, "reminder_source", None)
        undated = source["due_at"] is None if source else not has_clock and day == window_start
        if undated:
            # The import files a reminder without a date on the window's first day; like an
            # undated To Do it belongs to today until it is completed on the iPhone.
            day = max(day_from, today)
            if day > day_to:
                continue
        elif day < day_from and day >= today:
            continue
        key = f"{PREFIX_TIME_TABLE}{entry.source_external_id or entry.id}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            AgendaItem(
                id=key, item_key=key, source=SOURCE_IPHONE_SYNC, kind=KIND_REMINDER, title=title, day=day,
                start=datetime.combine(day, at, tzinfo=tz) if at else None,
                time_basis="reminder" if at else None,
                due_date=None if undated else entry.day_date.isoformat(),
                status=PENDING_COMPLETE if pending else "open", comment=notes,
                can_complete=not pending and bool(source) and is_iphone_completion_key(entry.source_external_id or ""),
                is_open=not pending,
                frequency=entry.source_name, url=frontend_url("/admin-tasks"),
            )
        )
    if last_sync is not None:
        age = (now or datetime.now(timezone.utc)) - last_sync
        if age > timedelta(hours=IPHONE_SYNC_STALE_HOURS):
            warnings.append(
                f"iPhone Sync last ran {last_sync.astimezone(tz):%d.%m.%Y %H:%M}; iPhone reminders may be out of date."
            )
    return items, warnings


def _norm_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def dedupe_reminders(items: list[AgendaItem]) -> list[AgendaItem]:
    """Prefer To Do for duplicates unless the iPhone completion is pending."""
    todo_by_key = {
        (_norm_title(item.title), item.day): item
        for item in items if item.source == "microsoft_todo" and item.day is not None
    }
    kept: list[AgendaItem] = []
    replaced_todos: set[str] = set()
    for item in items:
        if item.source == SOURCE_IPHONE_SYNC:
            twin = todo_by_key.get((_norm_title(item.title), item.day))
            if twin is not None:
                if item.status == PENDING_COMPLETE:
                    item.linked_ids.append(twin.id)
                    replaced_todos.add(twin.id)
                    kept.append(item)
                    continue
                twin.linked_ids.append(item.id)
                if twin.start is None and item.start is not None:
                    twin.start, twin.time_basis = item.start, "reminder"
                continue
        kept.append(item)
    return [item for item in kept if item.id not in replaced_todos]


async def collect_discord_items(db: AsyncSession, day_from: date, day_to: date, *, tz: ZoneInfo) -> list[AgendaItem]:
    """Open (new/seen) Discord mentions of the GA, untimed on the day they were written."""
    from app.services import ga_discord_mentions as mentions

    start = datetime.combine(day_from, time.min, tzinfo=tz)
    end = datetime.combine(day_to + timedelta(days=1), time.min, tzinfo=tz)
    rows = await mentions.list_mentions(db, since=start, until=end, statuses=mentions.OPEN_STATUSES)
    items: list[AgendaItem] = []
    for row, out in zip(rows, await mentions.render(db, rows, tz)):
        local = row.created_at.astimezone(tz)
        text = " ".join(row.content.split())
        items.append(
            AgendaItem(
                id=out["id"], item_key=out["id"], source="discord", kind=KIND_DISCORD,
                title=f"{out['author_initials']} në {out['channel']} ({local:%H:%M}): {text[:200] or '(bashkëngjitje)'}",
                day=local.date(), status=row.status, comment=row.content or None,
                can_complete=True, is_open=True, url=row.jump_url, assignees=[out["author"]],
                markers=[f"📎 {attachment.get('name')}" for attachment in (row.attachments or [])]
                + ([f"✅ {', '.join(out['reviewed_by'])}"] if out["ready_for_ga"] else []),
            )
        )
    return items


def apply_day_states(items: list[AgendaItem], states: dict[tuple[str, date], DayState], tz: ZoneInfo) -> list[AgendaItem]:
    kept: list[AgendaItem] = []
    for item in items:
        state = states.get((item.item_key, item.day)) if item.day else None
        if state and state.removed:
            continue
        if state and state.time_override and item.kind in TASK_KINDS:
            if state.time_value is None:
                item.start, item.time_basis = None, ("ampm" if item.am_pm else None)
            else:
                item.start, item.time_basis = datetime.combine(item.day, state.time_value, tzinfo=tz), "assistant"
        kept.append(item)
    return kept


async def collect_items(
    db: AsyncSession, owner: User, day_from: date, day_to: date, *, include_microsoft: bool,
    include_live_microsoft: bool = True, now: datetime | None = None,
) -> tuple[list[AgendaItem], list[str]]:
    tz = ga_tz()
    today = (now or datetime.now(tz)).astimezone(tz).date()
    items = await collect_task_items(db, owner, day_from, day_to, today=today, tz=tz)
    items += await collect_meeting_items(db, owner, day_from, day_to, tz=tz)
    warnings: list[str] = []
    if include_microsoft:  # GA's private sources include both live Graph and local records.
        if include_live_microsoft:
            ms_items, warnings = await collect_microsoft_items(db, owner, day_from, day_to, tz=tz, today=today)
            items += ms_items
        tt_items, tt_warnings = await collect_time_table_reminders(db, owner, day_from, day_to, tz=tz, today=today, now=now)
        items = dedupe_reminders(items + tt_items)
        warnings += tt_warnings
        items += await collect_discord_items(db, day_from, day_to, tz=tz)
    states = await load_day_states(db, owner.id, min(day_from, today) - timedelta(days=LEFTOVER_LOOKBACK_DAYS), day_to)
    return apply_day_states(items, states, tz), warnings


def sort_key(item: AgendaItem):
    return (
        item.start or datetime.max.replace(tzinfo=timezone.utc),
        {KIND_GA_TASK: 0, KIND_BZ: 1, KIND_F_TASK: 2, KIND_GA_MARKED_TASK: 2, KIND_MEETING: 3,
         KIND_EVENT: 4, KIND_REMINDER: 5, KIND_DISCORD: 6}.get(item.kind, 9),
        item.title.casefold(),
    )


def select_agenda(items: list[AgendaItem], start: datetime, end: datetime, *, include_untimed: bool) -> list[AgendaItem]:
    """Timed items whose start is in [start, end); untimed items of the covered days on request."""
    last_day = (end - timedelta(microseconds=1)).date()
    days = {start.date() + timedelta(days=offset) for offset in range((last_day - start.date()).days + 1)}
    selected = []
    for item in items:
        if item.start is not None:
            if start <= item.start < end:
                selected.append(item)
        elif include_untimed and item.day in days and (item.is_open or item.status == PENDING_COMPLETE):
            selected.append(item)
    return sorted(selected, key=sort_key)


def select_leftovers(items: list[AgendaItem], as_of: datetime) -> list[AgendaItem]:
    """Unfinished items due before ``as_of``: earlier days, or earlier today when timed."""
    today = as_of.date()
    selected = []
    for item in items:
        if not item.is_open or item.day is None or item.kind == KIND_EVENT:
            continue
        if item.kind == KIND_MEETING and item.day != today:
            continue  # unmarked meetings only matter on the day itself
        if item.kind == KIND_DISCORD and item.status != "new":
            continue  # a mention GA has already seen is not a leftover
        if item.day < today or (item.day == today and item.start is not None and item.start < as_of):
            selected.append(item)
    for item in selected:
        if item.days_late is None and item.day and item.day < today:
            item.days_late = (today - item.day).days
    return sorted(selected, key=lambda item: (item.day, item.start or datetime.max.replace(tzinfo=timezone.utc), item.title.casefold()))


def select_untimed(items: list[AgendaItem], day: date) -> list[AgendaItem]:
    return sorted(
        (
            item for item in items
            if item.is_open and item.start is None and item.day == day
            and item.kind in TASK_KINDS | {KIND_REMINDER, KIND_DISCORD}
        ),
        key=sort_key,
    )
