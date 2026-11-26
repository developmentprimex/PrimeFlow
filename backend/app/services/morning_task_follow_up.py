"""Shared task selection and Discord comments for the morning follow-ups."""

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select

from app.config import settings
from app.models.discord_assistant import DiscordLink, DiscordReminder
from app.models.task import Task
from app.models.user import User
from app.services.task_title_rules import title_has_eight_am_indicator

FOLLOW_UP_BY_SLOT = {"11:00": "08:00", "11:50": "DL AM"}
CARRIED_FOLLOW_UPS = {
    "11:50": ("08:00",),
    "14:10": ("08:00", "DL AM"),
    "14:20": ("08:00", "DL AM"),
    "16:00": ("08:00", "DL AM"),
}


def report_follow_up_groups(slot):
    primary = FOLLOW_UP_BY_SLOT.get(slot)
    return ((primary,) if primary else ()) + CARRIED_FOLLOW_UPS.get(slot, ())


def is_open_follow_up(row):
    status = str(row.get("status") or "").strip().upper()
    return not row.get("completed_at") and status not in {"DONE", "COMPLETED", "COMPLETED_LATE"}


def discord_follow_up_groups(row, day, slot):
    primary = FOLLOW_UP_BY_SLOT.get(slot)
    groups = []
    if is_open_follow_up(row):
        due_groups = task_row_groups(row, day)
        groups.extend(group for group in CARRIED_FOLLOW_UPS.get(slot, ()) if group in due_groups)
    if primary and primary in task_row_groups(row, day, include_planned_days=True):
        groups.append(primary)
    return groups


def local_task_day(value):
    try:
        if isinstance(value, str):
            value = (date.fromisoformat(value) if len(value) == 10
                     else datetime.fromisoformat(value.replace("Z", "+00:00")))
        if isinstance(value, datetime):
            zone = ZoneInfo(settings.APP_TIMEZONE)
            return (value if value.tzinfo else value.replace(tzinfo=zone)).astimezone(zone).date()
    except ValueError:
        return None
    return value if isinstance(value, date) else None


def morning_task_groups(day, *, due_date, title, is_system_task, deadline_important, finish_period, start_date=None):
    due_day = local_task_day(due_date)
    start_day = local_task_day(start_date) or due_day
    if day is None or due_day is None or not min(start_day, due_day) <= day <= due_day:
        return set()
    groups = set()
    if title_has_eight_am_indicator(title, is_system_task=is_system_task):
        groups.add("08:00")
    if deadline_important and finish_period == "AM":
        groups.add("DL AM")
    return groups


def task_row_groups(row, day, *, include_planned_days=False):
    return morning_task_groups(
        day, due_date=row.get("due_date"), title=row.get("task_title") or row.get("title"),
        is_system_task=bool(row.get("is_system_task") or row.get("system_template_origin_id") or row.get("system_task_slot_id")),
        deadline_important=row.get("is_deadline_important"), finish_period=row.get("finish_period"),
        start_date=row.get("start_date") if include_planned_days else None,
    )


def task_model_groups(task, day, *, include_planned_days=False):
    return morning_task_groups(
        day, due_date=task.due_date, title=task.title,
        is_system_task=bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None)),
        deadline_important=getattr(task, "is_deadline_important", False), finish_period=task.finish_period,
        start_date=getattr(task, "start_date", None) if include_planned_days else None,
    )


async def load_morning_task_rows(db, day, *, frozen_task_ids=()):
    """Load morning tasks in their planned date range, including tasks without a slot."""
    from app.services.meetings_report import (
        _assignee_names, _effective_task_assignee_ids, _normalize_report_status, apply_weekly_planner_task_order,
    )
    from app.services.task_marker import active_one_h_marker
    from app.services.task_pause import pause_until_on_day

    start = datetime.combine(day, time.min, ZoneInfo(settings.APP_TIMEZONE))
    end = start + timedelta(days=1)
    frozen = {UUID(task_id) for task_id in frozen_task_ids}
    tasks = (await db.execute(select(Task).where(
        Task.work_staff_filter(), Task.is_active.is_(True),
        or_(
            and_(Task.due_date >= start, or_(Task.due_date < end, Task.start_date < end)),
            Task.id.in_(frozen),
        ),
    ))).scalars().all()
    tasks = [task for task in tasks if task.id in frozen or task_model_groups(task, day, include_planned_days=True)]
    if not tasks:
        return []
    owners = await _effective_task_assignee_ids(db, tasks)
    names = await _assignee_names(db, tasks)
    await apply_weekly_planner_task_order(db, tasks, owners)
    rows = []
    for task in tasks:
        assignees = sorted(names[user_id] for user_id in owners[task.id] if user_id in names)
        rows.append({
            "id": f"task:{task.id}:{day}", "task_id": str(task.id), "date": day.isoformat(),
            "title": task.title, "description": task.description, "status": _normalize_report_status(task.status),
            "person": ", ".join(assignees) or "Unknown", "assignees": assignees,
            "user_id": str(task.assigned_to) if task.assigned_to else None,
            "department_id": str(task.department_id) if task.department_id else None,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "start_date": task.start_date.isoformat() if task.start_date else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "finish_period": task.finish_period, "is_deadline_important": task.is_deadline_important,
            "is_system_task": bool(task.system_template_origin_id or task.system_task_slot_id),
            "is_paused": bool(pause_until_on_day(task.pause_periods, day)),
            "one_h_marker": active_one_h_marker(task, day),
            "weekly_planner_sort": getattr(task, "_weekly_planner_report_sort", None),
        })
    return rows


async def load_follow_up_comments(db, day, slots, *, group=None, include_regular_answers=False):
    """Return saved follow-up answers and, when requested, ordinary 1H answers."""
    rows = (await db.execute(
        select(DiscordReminder.bucket, DiscordReminder.one_h_report, User.full_name, User.username)
        .join(DiscordLink, DiscordLink.id == DiscordReminder.link_id)
        .join(User, User.id == DiscordLink.user_id)
        .where(DiscordReminder.day == day, DiscordReminder.bucket.in_(slots),
               DiscordReminder.one_h_report.is_not(None))
        .order_by(User.full_name, User.username, DiscordReminder.id)
    )).all()
    comments = {}
    for slot, report, name, username in rows:
        for item in (report or {}).get("tasks", []):
            groups = (item.get("follow_up") or "").split(" / ")
            eligible = {*CARRIED_FOLLOW_UPS.get(slot, ()), FOLLOW_UP_BY_SLOT.get(slot)}
            tracked = bool(eligible.intersection(groups))
            if group is not None and group not in groups:
                continue
            if not tracked and not (include_regular_answers and item.get("answer")):
                continue
            answers = comments.setdefault(slot, {}).setdefault(item["id"], [])
            if item.get("answer"):
                answers.append(f"{name or username}: {item['answer']}")
    return {slot: {task_id: "\n".join(answers) for task_id, answers in entries.items()}
            for slot, entries in comments.items()}
