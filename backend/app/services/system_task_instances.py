from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.common_entry import CommonEntry
from app.models.enums import CommonApprovalStatus, CommonCategory, TaskPriority, TaskStatus
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_assignee_slot import SystemTaskTemplateAssigneeSlot
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.system_task_schedule import first_run_at, next_occurrence, template_due_time, template_tz

ALL_USERS_MARKER = "[ALL_USERS]"
GA_EMAIL = "ga@primexeu.com"


def _safe_iso_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _parse_annual_leave_entry(
    entry: CommonEntry | object,
) -> tuple[date, date, bool, str | None, str | None, str | None, bool]:
    note = getattr(entry, "description", None) or ""
    entry_date = getattr(entry, "entry_date", None)
    created_at = getattr(entry, "created_at", None)
    base_date = entry_date or (created_at.date() if isinstance(created_at, datetime) else date.today())
    start_date = base_date
    end_date = base_date
    full_day = True
    start_time: str | None = None
    end_time: str | None = None
    is_all_users = False

    if ALL_USERS_MARKER in note:
        is_all_users = True
        note = note.replace(ALL_USERS_MARKER, "").strip()

    date_range_match = re.search(r"Date range:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", note, re.I)
    if date_range_match:
        start_date = _safe_iso_date(date_range_match.group(1), start_date)
        end_date = _safe_iso_date(date_range_match.group(2), end_date)
        note = re.sub(
            r"Date range:\s*\d{4}-\d{2}-\d{2}\s+to\s+\d{4}-\d{2}-\d{2}",
            "",
            note,
            flags=re.I,
        ).strip()
    else:
        date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", note, re.I)
        if date_match:
            parsed = _safe_iso_date(date_match.group(1), start_date)
            start_date = parsed
            end_date = parsed
            note = re.sub(r"Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I).strip()
        else:
            date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", note)
            if date_matches:
                start_date = _safe_iso_date(date_matches[0], start_date)
                end_date = _safe_iso_date(date_matches[1] if len(date_matches) > 1 else date_matches[0], end_date)

    if re.search(r"\(Full day\)", note, re.I):
        full_day = True
        note = re.sub(r"\(Full day\)", "", note, flags=re.I).strip()
    else:
        time_match = re.search(r"\((\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\)", note)
        if time_match:
            full_day = False
            start_time = time_match.group(1)
            end_time = time_match.group(2)
            note = re.sub(r"\(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\)", "", note).strip()

    cleaned_note = note.strip() if note.strip() else None
    return start_date, end_date, full_day, start_time, end_time, cleaned_note, is_all_users


def _date_in_ranges(day: date, ranges: list[tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in ranges)


def _build_annual_leave_snapshot(
    entries: list[CommonEntry | object],
) -> tuple[dict[uuid.UUID, list[tuple[date, date]]], list[tuple[date, date]]]:
    by_user: dict[uuid.UUID, list[tuple[date, date]]] = {}
    all_users_ranges: list[tuple[date, date]] = []

    for entry in entries:
        start_date, end_date, full_day, _, _, _, is_all_users = _parse_annual_leave_entry(entry)
        if not full_day:
            continue
        if is_all_users:
            all_users_ranges.append((start_date, end_date))
            continue
        user_id = getattr(entry, "assigned_to_user_id", None) or getattr(entry, "created_by_user_id", None)
        if user_id is None:
            continue
        by_user.setdefault(user_id, []).append((start_date, end_date))

    return by_user, all_users_ranges


def _assignee_on_full_day_leave(
    assignee_id: uuid.UUID,
    occurrence_day: date,
    leave_by_user: dict[uuid.UUID, list[tuple[date, date]]],
    all_users_ranges: list[tuple[date, date]],
) -> bool:
    if _date_in_ranges(occurrence_day, all_users_ranges):
        return True
    return _date_in_ranges(occurrence_day, leave_by_user.get(assignee_id, []))


def _adjust_due_datetime_local(
    *,
    tz: ZoneInfo,
    due_time: time,
    start_local_dt: datetime,
    duration_days: int,
) -> datetime:
    due_day = start_local_dt.date() + timedelta(days=max(duration_days, 1) - 1)
    due_dt = datetime.combine(due_day, due_time, tzinfo=tz)
    while due_dt.weekday() > 4:
        due_dt = due_dt - timedelta(days=1)
    return due_dt


async def _system_task_user_maps(
    db: AsyncSession,
    user_ids: set[uuid.UUID],
) -> tuple[dict[uuid.UUID, uuid.UUID | None], dict[uuid.UUID, str]]:
    if not user_ids:
        return {}, {}
    rows = (
        await db.execute(select(User.id, User.department_id, User.email).where(User.work_staff_filter()).where(User.id.in_(user_ids)))
    ).all()
    return (
        {user_id: department_id for user_id, department_id, _ in rows},
        {user_id: (email or "").strip().lower() for user_id, _, email in rows},
    )


def _replacement_user_for_occurrence(
    *,
    template: SystemTaskTemplate | object,
    slots: list[SystemTaskTemplateAssigneeSlot | object],
    occurrence_day: date,
    leave_by_user: dict[uuid.UUID, list[tuple[date, date]]],
    all_users_ranges: list[tuple[date, date]],
    user_email_map: dict[uuid.UUID, str],
) -> tuple[uuid.UUID | None, SystemTaskTemplateAssigneeSlot | object | None]:
    if not slots:
        return None, None

    primary_ids = [slot.primary_user_id for slot in slots]
    absent_ids = {
        user_id
        for user_id in primary_ids
        if _assignee_on_full_day_leave(user_id, occurrence_day, leave_by_user, all_users_ranges)
    }

    if len(primary_ids) == 1:
        fallback_required = primary_ids[0] in absent_ids
        source_slot = slots[0]
    else:
        non_gane_slots = [
            slot for slot in slots if user_email_map.get(slot.primary_user_id, "") != GA_EMAIL
        ]
        relevant_slots = non_gane_slots or slots
        fallback_required = all(slot.primary_user_id in absent_ids for slot in relevant_slots)
        source_slot = next(
            (slot for slot in relevant_slots if slot.primary_user_id in absent_ids),
            relevant_slots[0],
        )

    if not fallback_required:
        return None, None

    for replacement_id in (
        getattr(template, "zv1_user_id", None),
        getattr(template, "zv2_user_id", None),
    ):
        if replacement_id is None:
            continue
        if not _assignee_on_full_day_leave(
            replacement_id,
            occurrence_day,
            leave_by_user,
            all_users_ranges,
        ):
            return replacement_id, source_slot
    return None, None


async def _insert_system_task_instance(
    db: AsyncSession,
    *,
    slot: SystemTaskTemplateAssigneeSlot,
    template: SystemTaskTemplate,
    department_id: uuid.UUID | None,
    origin_run_at: datetime,
    start_at: datetime,
    due_utc: datetime,
    now_utc: datetime,
    assignee_id: uuid.UUID | None = None,
) -> bool:
    assignee_id = assignee_id or slot.primary_user_id
    task_insert = pg_insert(Task).values(
        {
            "id": uuid.uuid4(),
            "title": template.title,
            "description": template.description,
            "internal_notes": template.internal_notes,
            "department_id": department_id,
            "assigned_to": assignee_id,
            "created_by": assignee_id,
            "system_template_origin_id": template.id,
            "system_task_slot_id": slot.id,
            "origin_run_at": origin_run_at,
            "start_date": start_at,
            "due_date": due_utc,
            "status": TaskStatus.TODO,
            "priority": getattr(template, "priority", None) or TaskPriority.NORMAL,
            "finish_period": getattr(template, "finish_period", None),
            "is_active": True,
            "created_at": now_utc,
            "updated_at": now_utc,
        }
    )
    task_insert = task_insert.on_conflict_do_nothing(
        index_elements=["system_template_origin_id", "system_task_slot_id", "origin_run_at"],
        index_where=Task.origin_run_at.is_not(None) & Task.meeting_origin_id.is_(None),
    ).returning(Task.id)

    try:
        async with db.begin_nested():
            inserted_task_id = (await db.execute(task_insert)).scalar_one_or_none()
    except IntegrityError as exc:
        msg = str(exc).lower()
        if "duplicate key value violates unique constraint" in msg and (
            "immutable_date(start_date)" in msg or "uq_tasks_system_template_user_date" in msg
        ):
            inserted_task_id = None
        else:
            raise

    if inserted_task_id is None:
        return False

    await db.execute(
        pg_insert(TaskAssignee)
        .values({"task_id": inserted_task_id, "user_id": assignee_id})
        .on_conflict_do_nothing(index_elements=["task_id", "user_id"])
    )
    return True


async def generate_system_task_instances(
    db: AsyncSession,
    *,
    now_utc: datetime | None = None,
    start: date | None = None,
    end: date | None = None,
    template_ids: list[uuid.UUID] | set[uuid.UUID] | None = None,
) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    if start is not None and end is not None and end < start:
        return 0
    if template_ids is not None and not template_ids:
        return 0

    await ensure_slots_initialized(db)
    slot_stmt = (
        select(SystemTaskTemplateAssigneeSlot, SystemTaskTemplate)
        .join(SystemTaskTemplate, SystemTaskTemplateAssigneeSlot.template_id == SystemTaskTemplate.id)
        .where(SystemTaskTemplateAssigneeSlot.is_active.is_(True))
        .where(SystemTaskTemplate.is_active.is_(True))
        .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
        .where(SystemTaskTemplate.trigger_type.is_(None))
        .order_by(
            SystemTaskTemplateAssigneeSlot.template_id,
            SystemTaskTemplateAssigneeSlot.created_at,
            SystemTaskTemplateAssigneeSlot.id,
        )
    )
    if template_ids is not None:
        slot_stmt = slot_stmt.where(SystemTaskTemplateAssigneeSlot.template_id.in_(template_ids))
    slot_rows = (await db.execute(slot_stmt.with_for_update(skip_locked=True))).all()
    if not slot_rows:
        return 0

    all_user_ids = {slot.primary_user_id for slot, _ in slot_rows}
    department_map, _ = await _system_task_user_maps(db, all_user_ids)

    rows_by_template: dict[
        uuid.UUID,
        tuple[SystemTaskTemplate, list[SystemTaskTemplateAssigneeSlot]],
    ] = {}
    for slot, template in slot_rows:
        if template.id not in rows_by_template:
            rows_by_template[template.id] = (template, [])
        rows_by_template[template.id][1].append(slot)

    created = 0
    for template, template_slots in rows_by_template.values():
        tz = template_tz(template)
        due_time = template_due_time(template)
        range_end = (
            end
            if end is not None
            else now_utc.astimezone(tz).date()
            + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0))
        )
        range_start = start
        slots_by_occurrence: dict[datetime, list[SystemTaskTemplateAssigneeSlot]] = {}
        for slot in template_slots:
            if slot.primary_user_id not in department_map:
                continue
            next_run = slot.next_run_at or first_run_at(template, now_utc)
            while True:
                occurrence_day = next_run.astimezone(tz).date()
                if occurrence_day > range_end:
                    break
                if range_start is None or occurrence_day >= range_start:
                    slots_by_occurrence.setdefault(next_run, []).append(slot)
                next_run = next_occurrence(template, next_run)
            slot.next_run_at = next_run

        for occurrence_run_at in sorted(slots_by_occurrence):
            occurrence_slots = slots_by_occurrence[occurrence_run_at]
            due_local = _adjust_due_datetime_local(
                tz=tz,
                due_time=due_time,
                start_local_dt=occurrence_run_at.astimezone(tz),
                duration_days=int(getattr(template, "duration_days", 1) or 1),
            )
            # Keep the original slot identity while generating. The scheduler
            # immediately follows this with rolling PV/ZV reconciliation, which
            # also corrects already-generated instances when leave data changes.
            for source_slot in occurrence_slots:
                assigned_user_id = source_slot.primary_user_id
                inserted = await _insert_system_task_instance(
                    db,
                    slot=source_slot,
                    template=template,
                    department_id=department_map.get(assigned_user_id) or template.department_id,
                    origin_run_at=occurrence_run_at,
                    start_at=occurrence_run_at,
                    due_utc=due_local.astimezone(timezone.utc),
                    now_utc=now_utc,
                    assignee_id=assigned_user_id,
                )
                if inserted:
                    created += 1

    return created


def _task_can_be_daily_reconciled(
    task: Task | object,
    *,
    template: SystemTaskTemplate | object,
    slot: SystemTaskTemplateAssigneeSlot | object,
) -> bool:
    status_value = getattr(getattr(task, "status", None), "value", getattr(task, "status", None))
    allowed_assignees = {
        slot.primary_user_id,
        getattr(template, "zv1_user_id", None),
        getattr(template, "zv2_user_id", None),
    }
    return (
        status_value == TaskStatus.TODO.value
        and getattr(task, "completed_at", None) is None
        and int(getattr(task, "progress_percentage", 0) or 0) == 0
        and getattr(task, "assigned_to", None) in allowed_assignees
    )


async def _replace_generated_task_assignee(
    db: AsyncSession,
    *,
    task: Task,
    user_id: uuid.UUID,
    department_id: uuid.UUID | None,
) -> None:
    task.assigned_to = user_id
    task.department_id = department_id
    task.is_active = True
    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    await db.execute(
        pg_insert(TaskAssignee)
        .values({"task_id": task.id, "user_id": user_id})
        .on_conflict_do_nothing(index_elements=["task_id", "user_id"])
    )


async def reconcile_system_task_assignments_for_day(
    db: AsyncSession,
    *,
    target_day: date | None = None,
    now_utc: datetime | None = None,
    template_ids: list[uuid.UUID] | set[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Apply the latest full-day PV/ZV state to pre-generated tasks for one day."""
    now_utc = now_utc or datetime.now(timezone.utc)
    app_tz = ZoneInfo(settings.APP_TIMEZONE)
    target_day = target_day or now_utc.astimezone(app_tz).date()

    # Use a wide UTC window, then compare in each template's timezone.
    window_start = datetime.combine(target_day - timedelta(days=1), time.min, tzinfo=timezone.utc)
    window_end = datetime.combine(target_day + timedelta(days=2), time.min, tzinfo=timezone.utc)
    rows_stmt = (
        select(Task, SystemTaskTemplate, SystemTaskTemplateAssigneeSlot)
            .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
            .join(SystemTaskTemplateAssigneeSlot, Task.system_task_slot_id == SystemTaskTemplateAssigneeSlot.id)
            .where(Task.origin_run_at.is_not(None))
            .where(Task.origin_run_at >= window_start, Task.origin_run_at < window_end)
            .where(Task.meeting_origin_id.is_(None))
            .where(SystemTaskTemplate.trigger_type.is_(None))
    )
    if template_ids is not None:
        if not template_ids:
            return {"reassigned": 0, "deactivated": 0, "reactivated": 0, "created": 0, "skipped": 0}
        rows_stmt = rows_stmt.where(SystemTaskTemplate.id.in_(template_ids))
    rows = (await db.execute(rows_stmt)).all()
    rows = [
        (task, template, slot)
        for task, template, slot in rows
        if task.origin_run_at.astimezone(template_tz(template)).date() == target_day
    ]
    if not rows:
        return {"reassigned": 0, "deactivated": 0, "reactivated": 0, "created": 0, "skipped": 0}

    user_ids = {slot.primary_user_id for _, _, slot in rows}
    user_ids.update(
        replacement_id
        for _, template, _ in rows
        for replacement_id in (
            getattr(template, "zv1_user_id", None),
            getattr(template, "zv2_user_id", None),
        )
        if replacement_id is not None
    )
    department_map, user_email_map = await _system_task_user_maps(db, user_ids)
    annual_leave_entries = (
        await db.execute(select(CommonEntry).where(CommonEntry.category == CommonCategory.annual_leave))
    ).scalars().all()
    leave_by_user, all_users_ranges = _build_annual_leave_snapshot(annual_leave_entries)

    grouped: dict[
        tuple[uuid.UUID, datetime],
        tuple[SystemTaskTemplate, list[tuple[Task, SystemTaskTemplateAssigneeSlot]]],
    ] = {}
    for task, template, slot in rows:
        key = (template.id, task.origin_run_at)
        if key not in grouped:
            grouped[key] = (template, [])
        grouped[key][1].append((task, slot))

    counts = {"reassigned": 0, "deactivated": 0, "reactivated": 0, "created": 0, "skipped": 0}
    for (_, origin_run_at), (template, task_slots) in grouped.items():
        task_slots.sort(key=lambda pair: (pair[1].created_at, pair[1].id))
        slots = [slot for _, slot in task_slots if slot.primary_user_id in department_map]
        occurrence_day = origin_run_at.astimezone(template_tz(template)).date()
        expected: dict[uuid.UUID, uuid.UUID] = {
            slot.id: slot.primary_user_id
            for slot in slots
            if slot.primary_user_id in department_map and not _assignee_on_full_day_leave(
                slot.primary_user_id, occurrence_day, leave_by_user, all_users_ranges
            )
        }
        replacement_id, source_slot = _replacement_user_for_occurrence(
            template=template,
            slots=slots,
            occurrence_day=occurrence_day,
            leave_by_user=leave_by_user,
            all_users_ranges=all_users_ranges,
            user_email_map=user_email_map,
        )
        if replacement_id in department_map and source_slot is not None:
            expected[source_slot.id] = replacement_id

        for task, slot in task_slots:
            if not _task_can_be_daily_reconciled(task, template=template, slot=slot):
                counts["skipped"] += 1
                continue
            assigned_user_id = expected.get(slot.id)
            if assigned_user_id is None:
                if task.is_active:
                    task.is_active = False
                    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
                    counts["deactivated"] += 1
                continue

            was_inactive = not task.is_active
            was_reassigned = task.assigned_to != assigned_user_id
            await _replace_generated_task_assignee(
                db,
                task=task,
                user_id=assigned_user_id,
                department_id=department_map.get(assigned_user_id) or template.department_id,
            )
            if was_inactive:
                counts["reactivated"] += 1
            if was_reassigned:
                counts["reassigned"] += 1

    return counts


async def reconcile_system_task_assignments_in_range(
    db: AsyncSession,
    *,
    start: date,
    end: date,
    now_utc: datetime | None = None,
    template_ids: list[uuid.UUID] | set[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Apply PV/ZV assignments to every generated system task in a date range."""
    totals = {"reassigned": 0, "deactivated": 0, "reactivated": 0, "created": 0, "skipped": 0}
    if end < start:
        return totals

    current = start
    while current <= end:
        counts = await reconcile_system_task_assignments_for_day(
            db=db,
            target_day=current,
            now_utc=now_utc,
            template_ids=template_ids,
        )
        for key in totals:
            totals[key] += counts.get(key, 0)
        current += timedelta(days=1)

    return totals


async def ensure_task_instances_in_range(
    db: AsyncSession,
    *,
    start: date,
    end: date,
) -> int:
    return await generate_system_task_instances(
        db,
        now_utc=datetime.now(timezone.utc),
        start=start,
        end=end,
    )


async def ensure_due_today_instances_best_effort(
    db: AsyncSession,
    *,
    now_utc: datetime | None = None,
) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    created = await generate_system_task_instances(db=db, now_utc=now_utc)
    await reconcile_system_task_assignments_for_day(db=db, now_utc=now_utc)
    await db.commit()
    return created


async def ensure_slots_initialized(db: AsyncSession) -> None:
    templates = (
        await db.execute(
            select(SystemTaskTemplate)
            .where(SystemTaskTemplate.is_active.is_(True))
            .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
            .where(SystemTaskTemplate.trigger_type.is_(None))
        )
    ).scalars().all()
    if not templates:
        return

    template_ids = [template.id for template in templates]
    existing_pairs = {
        (template_id, primary_user_id)
        for template_id, primary_user_id in (
            await db.execute(
                select(
                    SystemTaskTemplateAssigneeSlot.template_id,
                    SystemTaskTemplateAssigneeSlot.primary_user_id,
                ).where(SystemTaskTemplateAssigneeSlot.template_id.in_(template_ids))
            )
        ).all()
    }
    now_utc = datetime.now(timezone.utc)
    pending_values: list[dict[str, object]] = []

    for template in templates:
        assignee_ids = list(getattr(template, "assignee_ids", None) or [])
        if not assignee_ids and template.default_assignee_id:
            assignee_ids = [template.default_assignee_id]
        for assignee_id in assignee_ids:
            pair = (template.id, assignee_id)
            if pair in existing_pairs:
                continue
            pending_values.append(
                {
                    "id": uuid.uuid4(),
                    "template_id": template.id,
                    "primary_user_id": assignee_id,
                    "next_run_at": first_run_at(template, now_utc),
                    "is_active": True,
                    "created_at": now_utc,
                    "updated_at": now_utc,
                }
            )
            existing_pairs.add(pair)

    if pending_values:
        await db.execute(insert(SystemTaskTemplateAssigneeSlot), pending_values)


async def reconcile_system_task_slots(
    db: AsyncSession,
    *,
    now_utc: datetime | None = None,
    lookback_days: int = 30,
) -> dict[str, int]:
    del lookback_days
    created_tasks = await generate_system_task_instances(db=db, now_utc=now_utc)
    return {"rewound_slots": 0, "created_tasks": created_tasks}
