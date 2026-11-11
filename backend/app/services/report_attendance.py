"""Report-only attendance policy. Never changes assignments in the database."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.models.common_entry import CommonEntry
from app.models.enums import CommonCategory
from app.models.user import User
from app.services.common_leave import (
    is_common_view_full_day_absence, parse_common_view_annual_leave,
    parse_common_view_entry_day,
)


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _initials(value: Any) -> str:
    if _key(value) == "haris shaqiri":
        return "HSH"
    if re.fullmatch(r"[A-Za-z]{1,5}", str(value or "").strip()):
        return str(value).strip().upper()
    words = str(value or "").strip().split()
    return "".join(word[0] for word in words).upper()


class ReportNames(dict):
    """Keep large shared assignments explicit after removing unavailable people."""
    attendance_filtered = True


def _minutes(value: Any) -> int | None:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or "").strip())
    if not match:
        return None
    hour, minute = map(int, match.groups())
    return hour * 60 + minute if hour < 24 and minute < 60 else None


@dataclass
class ReportAttendance:
    user_ids: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    labels: set[str] = field(default_factory=set)
    all_users: bool = False

    def excludes(self, user_id: Any = None, name: Any = None) -> bool:
        return self.all_users or str(user_id) in self.user_ids or _key(name) in self.names

    def with_users(self, users) -> "ReportAttendance":
        for user in users:
            row = user if isinstance(user, dict) else {
                key: getattr(user, key, None) for key in ("id", "full_name", "username", "email")
            }
            aliases = {_key(row.get(key)) for key in ("full_name", "username", "email") if row.get(key)}
            if str(row.get("id")) in self.user_ids or aliases & self.names:
                self.user_ids.add(str(row.get("id")))
                self.names.update(aliases)
                label = _initials(row.get("full_name") or row.get("username") or row.get("email"))
                if label:
                    self.labels.add(label)
                standard = "".join(part[0] for part in str(row.get("full_name") or "").split()).upper()
                if standard:
                    self.labels.add(standard)
        return self

    def owner_text(self, value: str) -> str:
        """Filter report owner cells, whose values are full names or initials."""
        if self.all_users:
            return ""
        if self.excludes(name=value) or str(value).strip().upper() in self.labels:
            return ""
        if str(value).strip().upper() == "ALL" and self.user_ids:
            return "Të pranishmit"
        parts = re.split(r"\s*[,/|]\s*", str(value or ""))
        if len(parts) == 1 and re.fullmatch(r"[A-Z]{1,5}(?:\s+[A-Z]{1,5})+", parts[0]):
            parts = parts[0].split()
        present = [part for part in parts if part and not self.excludes(name=part)
                   and part.upper() not in self.labels]
        return str(value or "") if len(present) == len(parts) else " ".join(present)

    def item(self, row: dict) -> dict | None:
        """Copy a display row and retain only its present owners."""
        if self.all_users:
            return None
        owners = row.get("assignees")
        if isinstance(owners, str):
            present = self.owner_text(owners)
            if owners not in {"", "-", "—"} and not present:
                return None
            return {**row, "assignees": present} if present != owners else row
        person_key = next((key for key in ("person", "owner", "employee", "user_name", "assignee_name", "user", "author")
                           if row.get(key)), None)
        person = str(row.get(person_key) or "") if person_key else ""
        owners = owners or [part.strip() for part in person.split(",") if part.strip()]
        uid = row.get("userId") or row.get("user_id")
        if len(owners) <= 1 and self.excludes(uid):
            return None
        present = [name for name in owners if not self.excludes(name=name)
                   and str(name).strip().upper() not in self.labels]
        if owners and not present:
            return None
        if present == owners:
            return row
        result = {**row, "assignees": present}
        for key in ("employee", "person", "owner", "user_name", "assignee_name", "user"):
            if key in result:
                result[key] = ", ".join(present)
        if self.excludes(uid):
            result.pop("userId", None)
            result.pop("user_id", None)
        return result

    def task_context(self, tasks, names, owners):
        filtered, present_owners = [], {}
        for task in tasks:
            assigned = set(owners.get(task.id, set()))
            if getattr(task, "assigned_to", None):
                assigned.add(task.assigned_to)
            present = {uid for uid in assigned if not self.excludes(uid, names.get(uid))}
            if self.all_users or (assigned and not present):
                continue
            filtered.append(task)
            present_owners[task.id] = present
        visible_names = {uid: name for uid, name in names.items() if not self.excludes(uid, name)}
        return filtered, ReportNames(visible_names) if self.user_ids or self.all_users else visible_names, present_owners


def attendance_from_items(items: dict, day: date, users=()) -> ReportAttendance:
    policy = ReportAttendance()
    for bucket in ("absent", "leave"):
        for row in items.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if bucket == "leave":
                start = str(row.get("startDate") or row.get("start_date") or "")[:10]
                end = str(row.get("endDate") or row.get("end_date") or start)[:10]
                if not start or not start <= day.isoformat() <= end:
                    continue
            elif str(row.get("date") or "")[:10] != day.isoformat():
                continue
            full_day = row.get("fullDay", row.get("full_day"))
            start, end = _minutes(row.get("from")), _minutes(row.get("to"))
            if full_day is not True and not (
                (start is None and end is None and full_day is not False)
                or (start is not None and end is not None and start <= 480 and end >= 960)
            ):
                continue
            policy.all_users |= bool(row.get("isAllUsers") or row.get("is_all_users"))
            uid = row.get("userId") or row.get("user_id")
            if uid:
                policy.user_ids.add(str(uid))
            name = next((row.get(key) for key in ("employee", "person", "owner", "user_name", "assignee_name", "user") if row.get(key)), None)
            if name:
                policy.names.add(_key(name))
                policy.labels.add(_initials(name))
    return policy.with_users(users)


def attendance_from_entries(entries, day: date) -> ReportAttendance:
    policy = ReportAttendance()
    for entry in entries:
        if entry.category == CommonCategory.absences:
            if parse_common_view_entry_day(entry) != day or not is_common_view_full_day_absence(entry):
                continue
        else:
            start, end, full_day, start_time, end_time, _, all_users = parse_common_view_annual_leave(entry)
            if not start <= day <= end:
                continue
            first, last = _minutes(start_time), _minutes(end_time)
            if not full_day and not (first is not None and last is not None and first <= 480 and last >= 960):
                continue
            policy.all_users |= all_users
        uid = entry.assigned_to_user_id or entry.created_by_user_id
        if uid:
            policy.user_ids.add(str(uid))
    return policy


async def _with_report_users(db, policy: ReportAttendance) -> ReportAttendance:
    if policy.user_ids:
        users = (await db.execute(select(User).where(User.id.in_([uuid.UUID(uid) for uid in policy.user_ids])))).scalars().all()
        policy.with_users(users)
    return policy


async def load_report_attendance(db, day: date) -> ReportAttendance:
    entries = (await db.execute(select(CommonEntry).where(CommonEntry.category.in_(
        [CommonCategory.absences, CommonCategory.annual_leave]
    )))).scalars().all()
    return await _with_report_users(db, attendance_from_entries(entries, day))


async def load_period_attendance(db, start: date, end: date) -> ReportAttendance:
    """A multi-day summary excludes people only when away throughout its workdays."""
    if start >= end:
        return await load_report_attendance(db, start)
    entries = (await db.execute(select(CommonEntry).where(CommonEntry.category.in_(
        [CommonCategory.absences, CommonCategory.annual_leave]
    )))).scalars().all()
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    working_days = [day for day in days if day.weekday() < 5] or days
    policies = [attendance_from_entries(entries, day) for day in working_days]
    candidates = set().union(*(policy.user_ids for policy in policies))
    policy = ReportAttendance(
        user_ids={uid for uid in candidates if all(item.excludes(uid) for item in policies)},
        all_users=all(item.all_users for item in policies),
    )
    return await _with_report_users(db, policy)


async def filter_task_context(db, day, tasks, names, owners):
    return (await load_report_attendance(db, day)).task_context(tasks, names, owners)


class ReportTask:
    """A display proxy; assigning a present primary owner must not update an ORM row."""
    def __init__(self, task, owner_ids, owner_names):
        self._source = task
        self.assigned_to = task.assigned_to if task.assigned_to in owner_ids else next(iter(sorted(owner_ids, key=str)), None)
        self.report_owner_names = owner_names
        self.report_owner_ids = owner_ids

    def __getattr__(self, name):
        return getattr(self._source, name)


async def filter_export_tasks(db, tasks, day: date | tuple[date | None, date | None] | None = None):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.config import settings
    from app.models.task_assignee import TaskAssignee
    if isinstance(day, tuple) and any(day):
        start, end = day
        policy = await load_period_attendance(db, start or end, end or start)
    else:
        day = day if isinstance(day, date) else datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
        policy = await load_report_attendance(db, day)
    # The same export's assignee and fallback-name queries use this date as well.
    if isinstance(getattr(db, "info", None), dict):
        db.info["report_attendance"] = policy
    if not policy.user_ids and not policy.all_users:
        return tasks
    ids = {task.id for task in tasks}
    owners = {}
    if ids:
        for tid, uid in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(ids)))).all():
            owners.setdefault(tid, set()).add(uid)
    all_ids = {uid for values in owners.values() for uid in values}
    all_ids.update(task.assigned_to for task in tasks if task.assigned_to)
    users = {user.id: user for user in (await db.execute(select(User).where(User.id.in_(all_ids)))).scalars().all()} if all_ids else {}
    names = {uid: user.full_name or user.username or user.email for uid, user in users.items()}
    visible, names, owners = policy.task_context(tasks, names, owners)
    return [ReportTask(task, owners[task.id], [names[uid] for uid in sorted(owners[task.id], key=str) if uid in names]) for task in visible]


async def filter_export_rows(db, rows, day: date | None = None):
    tasks = await filter_export_tasks(db, [row[0] for row in rows], day)
    by_id = {task.id: task for task in tasks}
    result = []
    for row in rows:
        if row[0].id not in by_id:
            continue
        task = by_id[row[0].id]
        values = [task, *row[1:]]
        # Fast-task exports join the primary User in column 3.
        if len(values) > 2 and isinstance(values[2], User) and values[2].id != task.assigned_to:
            values[2] = await db.get(User, task.assigned_to) if task.assigned_to else None
        result.append(tuple(values))
    return result


async def filter_points_payload(db, payload: dict) -> dict:
    policy = await load_report_attendance(db, date.fromisoformat(payload["report_date"]))
    if not policy.user_ids and not policy.all_users:
        return payload
    data = {}
    for key, rows in payload.get("data", {}).items():
        data[key] = [filtered for row in rows if (filtered := policy.item(row)) is not None] if (
            isinstance(rows, list) and any(isinstance(row, dict) and (row.get("task_id") or row.get("assignees")
                or row.get("person") or row.get("author")) for row in rows)
        ) else rows
    realization = payload.get("realization")
    if realization and "people" in realization:
        original_count = len(realization["people"])
        realization = {**realization, "people": [row for row in realization.get("people", [])
                                                if not policy.excludes(row.get("user_id"), row.get("name"))]}
        realization["employees"] = max(0, realization.get("employees", original_count) - original_count + len(realization["people"]))
    return {**payload, "data": data, **({"realization": realization} if "realization" in payload else {})}


async def filter_report_sections(db, sections: list[dict], day: date, *, tomorrow: date | None = None) -> list[dict]:
    """Filter saved ASCII report tables too, without rewriting archived documents."""
    from app.services.meetings_report import _ascii_table_block, _merge_ascii_continuation_rows
    policy = await load_report_attendance(db, day)
    next_policy = await load_report_attendance(db, tomorrow) if tomorrow else policy
    if not (policy.user_ids or policy.all_users or next_policy.user_ids or next_policy.all_users):
        return sections
    result = []
    for section in sections:
        title = str(section.get("section_key") or section.get("title") or "").upper()
        current = next_policy if tomorrow and (title.startswith("N-") or "NESER" in title or "NESËR" in title) else policy
        lines = (section.get("body") or "").splitlines()
        output, index = [], 0
        while index < len(lines):
            block = _ascii_table_block(lines, index)
            if block is None:
                output.append(lines[index])
                index += 1
                continue
            table_lines, following = block
            cells = [line.strip().strip("|").split("|") for line in table_lines if line.lstrip().startswith("|")]
            header = [cell.strip() for cell in cells[0]] if cells else []
            owner_column = next((i for i, label in enumerate(header) if label.upper() in {"KUSH", "WHO", "USER", "PER", "PERSONI", "PERSONAT", "ASSIGNEES", "FROM"}), None)
            if owner_column is None:
                output.extend(table_lines)
            else:
                rows = _merge_ascii_continuation_rows(header, [[cell.strip() for cell in row] for row in cells[1:]])
                kept = []
                for row in rows:
                    owner = current.owner_text(row[owner_column])
                    if not owner and row[owner_column] not in {"", "-", "—"}:
                        continue
                    row[owner_column] = owner or row[owner_column]
                    if header[0].upper() == "NR":
                        row[0] = str(len(kept) + 1)
                    kept.append(row)
                widths = [max([len(label), 1] + [len(part) for row in kept for part in str(row[i]).splitlines()]) for i, label in enumerate(header)]
                border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
                def line(row):
                    return "| " + " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)) + " |"
                output.extend([border, line(header), border])
                for row in kept:
                    values = [str(value).splitlines() or [""] for value in row]
                    for position in range(max(map(len, values))):
                        output.append(line([value[position] if position < len(value) else "" for value in values]))
                    output.append(border)
                if not kept:
                    output.append(border)
            index = following
        result.append({**section, "body": "\n".join(output)})
    return result
