from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import FrequencyType, SystemTaskScope, TaskFinishPeriod, TaskPriority, TaskStatus
from app.models.meeting import Meeting
from app.models.department import Department
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_assignee_slot import SystemTaskTemplateAssigneeSlot
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.user import User
from app.services.meeting_participants import manual_participant_ids
from app.services.microsoft_calendar_sync import is_routine_external_meeting

EXTERNAL_MEETING_TASK_KIND = "external_meeting_prepare"
EXTERNAL_MEETING_TRIGGER_TYPE = "EXTERNAL_MEETING_ONCE"
EXTERNAL_MEETING_TASK_TITLE = "TESTIMI I AGENTAVE PARA TAK"
EXTERNAL_MEETING_TASK_DESCRIPTION = (
    "1. Para çdo takimi extern duhet të testohen agjentat përkatës që do të prezantohen ose "
    "diskutohen në takim.\n"
    "2. Testimi bëhet para fillimit të takimit dhe duhet të konfirmojë që agjenti funksionon "
    "saktë, përgjigjet siç duhet dhe nuk ka probleme teknike ose logjike.\n"
    "3. Gjatë testimit plotësohet checklista me emrin \"Testimi i Agent\" te Meetings në "
    "Development Department.\n"
    "4. Pas përfundimit të testimit, checklista e testuar dërgohet në grup dhe njoftohen GA "
    "dhe KA për agjentat e testuar dhe rezultatin e testimit."
)
EXTERNAL_MEETING_TASK_TIME = time(8, 0)
EXTERNAL_MEETING_ASSIGNEE_NAMES = (
    "Laurent Hoxha",
    "Endi Hyseni",
    "Elsa Ferati",
    "Rinesa Ahmedi",
)

PIM_IMAGE_MEETING_TASK_KIND = "external_meeting_pim_image_test"
PIM_IMAGE_MEETING_TRIGGER_TYPE = "EXTERNAL_MEETING_PIM_IMAGE_ONCE"
PIM_IMAGE_MEETING_TASK_TITLE = "TESTIMI I PIM IMAGE PARA TAK"
PIM_IMAGE_MEETING_TASK_DESCRIPTION = (
    "Para takimit ekstern, kontrollohen PIM images që do të prezantohen.\n"
    "Verifikohet përmbajtja, cilësia, dimensionet, emërtimi dhe përputhja me produktin.\n"
    "Rezultati i testimit dokumentohet dhe çdo problem i raportohet ekipit para fillimit të takimit."
)

# 1H tasks for every person assigned on a one-time TAK EXT: one in the 1H slot
# before the meeting (TAK INT para) and one in the slot right after it
# (TAK INT pas). Both are completed manually, independently of meeting status.
# These are plain 1H tasks, not system tasks: no template or system slot.
TAK_INT_PRE_ONE_H_TASK_KIND = "tak_int_pre_one_h"
TAK_INT_POST_ONE_H_TASK_KIND = "tak_int_post_one_h"
TAK_INT_ONE_H_TASK_KINDS = (TAK_INT_PRE_ONE_H_TASK_KIND, TAK_INT_POST_ONE_H_TASK_KIND)
TAK_INT_PRE_ONE_H_TASK_TITLE = "TAK INT PARA TAK EXT"
TAK_INT_POST_ONE_H_TASK_TITLE = "TAK INT PAS TAK EXT"
TAK_INT_PRE_ONE_H_TASK_DESCRIPTION = (
    "TAK INT para takimit ekstern. Përgatitet takimi dhe diskutohen pikat që do të "
    "prezantohen. Detyra mbyllet manualisht, pavarësisht statusit të takimit."
)
TAK_INT_POST_ONE_H_TASK_DESCRIPTION = (
    "TAK INT pas takimit ekstern. Diskutohen rezultatet dhe hapat e ardhshëm të takimit. "
    "Detyra mbyllet manualisht, pavarësisht statusit të takimit."
)
TAK_INT_ONE_H_SLOTS: tuple[tuple[time, str], ...] = (
    (time(10, 0), "10:00"),
    (time(11, 0), "11:00"),
    (time(11, 50), "11:50"),
    (time(14, 20), "14:20"),
    # The "1H 16:00" row is held at 15:50 (see ONE_H_SLOT_TIMES in calendar sync).
    (time(15, 50), "16:00"),
)
INACTIVE_CALENDAR_SYNC_STATUSES = {"cancelled", "excluded"}


def _app_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def is_one_time_external_meeting(meeting: Meeting | object) -> bool:
    recurrence_type = (getattr(meeting, "recurrence_type", None) or "").strip().lower()
    return (
        (getattr(meeting, "meeting_type", None) or "external") == "external"
        and bool(getattr(meeting, "external_agent_test_task_requested", False))
        and recurrence_type in ("", "none")
        and getattr(meeting, "starts_at", None) is not None
    )


def is_one_time_external_pim_image_meeting(meeting: Meeting | object) -> bool:
    recurrence_type = (getattr(meeting, "recurrence_type", None) or "").strip().lower()
    return (
        (getattr(meeting, "meeting_type", None) or "external") == "external"
        and bool(getattr(meeting, "external_pim_image_test_task_requested", False))
        and recurrence_type in ("", "none")
        and getattr(meeting, "starts_at", None) is not None
    )


def meeting_occurrence_date(meeting: Meeting | object) -> date | None:
    starts_at = getattr(meeting, "starts_at", None)
    if starts_at is None:
        return None
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    return starts_at.astimezone(_app_tz()).date()


def meeting_task_start_at(occurrence_date: date) -> datetime:
    local_dt = datetime.combine(occurrence_date, EXTERNAL_MEETING_TASK_TIME, tzinfo=_app_tz())
    return local_dt.astimezone(timezone.utc)


def external_meeting_task_title(meeting: Meeting | object) -> str:
    return _meeting_task_title(meeting, EXTERNAL_MEETING_TASK_TITLE)


def pim_image_meeting_task_title(meeting: Meeting | object) -> str:
    return _meeting_task_title(meeting, PIM_IMAGE_MEETING_TASK_TITLE)


def _meeting_task_title(meeting: Meeting | object, base_title: str) -> str:
    meeting_title = (getattr(meeting, "title", None) or "").strip()
    starts_at = getattr(meeting, "starts_at", None)
    time_label = ""
    if starts_at is not None:
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=timezone.utc)
        time_label = starts_at.astimezone(_app_tz()).strftime("%H:%M")

    details = " ".join(part for part in (meeting_title, time_label) if part)
    return f"{base_title} - {details}" if details else base_title


def _local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(day, time.min, tzinfo=_app_tz())
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


async def ensure_external_meeting_trigger_template(db: AsyncSession) -> SystemTaskTemplate:
    return await _ensure_external_meeting_trigger_template(
        db,
        trigger_type=EXTERNAL_MEETING_TRIGGER_TYPE,
        title=EXTERNAL_MEETING_TASK_TITLE,
        description=EXTERNAL_MEETING_TASK_DESCRIPTION,
    )


async def ensure_pim_image_meeting_trigger_template(db: AsyncSession) -> SystemTaskTemplate:
    return await _ensure_external_meeting_trigger_template(
        db,
        trigger_type=PIM_IMAGE_MEETING_TRIGGER_TYPE,
        title=PIM_IMAGE_MEETING_TASK_TITLE,
        description=PIM_IMAGE_MEETING_TASK_DESCRIPTION,
    )


async def _ensure_external_meeting_trigger_template(
    db: AsyncSession,
    *,
    trigger_type: str,
    title: str,
    description: str,
) -> SystemTaskTemplate:
    template = (
        await db.execute(
            select(SystemTaskTemplate).where(SystemTaskTemplate.trigger_type == trigger_type)
        )
    ).scalar_one_or_none()
    if template is not None:
        return template

    template = SystemTaskTemplate(
        title=title,
        description=description,
        internal_notes=None,
        department_id=None,
        default_assignee_id=None,
        assignee_ids=[],
        scope=SystemTaskScope.ALL.value,
        frequency=FrequencyType.DAILY.value,
        day_of_week=None,
        days_of_week=None,
        day_of_month=None,
        month_of_year=None,
        timezone=settings.APP_TIMEZONE,
        due_time=EXTERNAL_MEETING_TASK_TIME,
        lookahead=1,
        interval=1,
        apply_from=None,
        duration_days=1,
        trigger_type=trigger_type,
        priority=TaskPriority.NORMAL.value,
        finish_period=TaskFinishPeriod.AM.value,
        requires_alignment=False,
        alignment_time=None,
        is_active=False,
    )
    db.add(template)
    await db.flush()
    return template


async def _ensure_slot(
    db: AsyncSession,
    *,
    template_id: uuid.UUID,
    user_id: uuid.UUID,
    next_run_at: datetime,
) -> SystemTaskTemplateAssigneeSlot:
    slot = (
        await db.execute(
            select(SystemTaskTemplateAssigneeSlot)
            .where(SystemTaskTemplateAssigneeSlot.template_id == template_id)
            .where(SystemTaskTemplateAssigneeSlot.primary_user_id == user_id)
        )
    ).scalar_one_or_none()
    if slot is not None:
        return slot

    slot = SystemTaskTemplateAssigneeSlot(
        id=uuid.uuid4(),
        template_id=template_id,
        primary_user_id=user_id,
        next_run_at=next_run_at,
        is_active=False,
    )
    db.add(slot)
    await db.flush()
    return slot


async def _fixed_assignee_ids(db: AsyncSession) -> list[uuid.UUID]:
    rows = (
        await db.execute(
            select(User.id, User.full_name)
            .where(User.full_name.in_(EXTERNAL_MEETING_ASSIGNEE_NAMES))
            .order_by(User.full_name.asc())
        )
    ).all()
    by_name = {str(full_name).strip().lower(): user_id for user_id, full_name in rows if full_name}
    return [
        by_name[name.lower()]
        for name in EXTERNAL_MEETING_ASSIGNEE_NAMES
        if name.lower() in by_name
    ]


async def _graphic_design_assignee_ids(db: AsyncSession) -> list[uuid.UUID]:
    rows = (
        await db.execute(
            select(User.id)
            .join(Department, Department.id == User.department_id)
            .where(User.is_active.is_(True))
            .where(
                or_(
                    func.upper(func.trim(Department.name)) == "GRAPHIC DESIGN",
                    func.upper(func.trim(Department.code)).in_(("GD", "GDS")),
                )
            )
            .order_by(User.full_name.asc())
        )
    ).scalars().all()
    return list(rows)


async def _user_department_map(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID | None]:
    if not user_ids:
        return {}
    rows = (await db.execute(select(User.id, User.department_id).where(User.id.in_(user_ids)))).all()
    return {user_id: department_id for user_id, department_id in rows}


def _can_repurpose_existing_task(task: Task, occurrence_date: date, participant_ids: set[uuid.UUID]) -> bool:
    if task.status == TaskStatus.DONE:
        return False
    if task.assigned_to not in participant_ids:
        return False
    return task.meeting_occurrence_date != occurrence_date


async def _reconcile_external_meeting_task_kind(
    db: AsyncSession,
    meeting: Meeting,
    *,
    task_kind: str,
    description: str,
    qualifies: bool,
    participant_ids: list[uuid.UUID],
    task_title: str,
    template: SystemTaskTemplate | None,
    now_utc: datetime | None = None,
) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    existing_tasks = (
        await db.execute(
            select(Task)
            .where(Task.meeting_origin_id == meeting.id)
            .where(Task.meeting_system_task_kind == task_kind)
            .order_by(Task.created_at.asc())
        )
    ).scalars().all()

    occurrence_date = meeting_occurrence_date(meeting) if qualifies else None
    participant_id_set = set(participant_ids)

    if not qualifies or occurrence_date is None or not participant_ids:
        for task in existing_tasks:
            if task.status != TaskStatus.DONE:
                task.is_active = False
        return 0

    task_start_at = meeting_task_start_at(occurrence_date)
    if template is None:
        return 0
    department_map = await _user_department_map(db, participant_ids)
    created_or_reactivated = 0

    current_tasks: dict[uuid.UUID, Task] = {}
    stale_reusable: dict[uuid.UUID, Task] = {}
    for task in existing_tasks:
        if task.assigned_to is None:
            if task.status != TaskStatus.DONE:
                task.is_active = False
            continue
        if (
            task.assigned_to in participant_id_set
            and task.meeting_occurrence_date == occurrence_date
        ):
            current_tasks[task.assigned_to] = task
            continue
        if _can_repurpose_existing_task(task, occurrence_date, participant_id_set):
            stale_reusable.setdefault(task.assigned_to, task)
            continue
        if task.status != TaskStatus.DONE:
            task.is_active = False

    for user_id in participant_ids:
        slot = await _ensure_slot(db, template_id=template.id, user_id=user_id, next_run_at=task_start_at)
        existing = current_tasks.get(user_id)
        if existing is None:
            existing = stale_reusable.get(user_id)
        if existing is not None and existing.status != TaskStatus.DONE:
            should_count = (
                not existing.is_active
                or existing.meeting_occurrence_date != occurrence_date
                or existing.origin_run_at != task_start_at
            )
            existing.title = task_title
            existing.description = description
            existing.department_id = department_map.get(user_id) or meeting.department_id
            existing.assigned_to = user_id
            existing.created_by = meeting.created_by or user_id
            existing.system_template_origin_id = template.id
            existing.system_task_slot_id = slot.id
            existing.origin_run_at = task_start_at
            existing.start_date = task_start_at
            existing.due_date = task_start_at
            existing.meeting_occurrence_date = occurrence_date
            existing.priority = TaskPriority.NORMAL.value
            existing.finish_period = TaskFinishPeriod.AM.value
            existing.is_active = True
            existing.completed_at = None
            if should_count:
                created_or_reactivated += 1
            await db.execute(
                pg_insert(TaskAssignee)
                .values({"task_id": existing.id, "user_id": user_id})
                .on_conflict_do_nothing(index_elements=["task_id", "user_id"])
            )
            continue

        task_id = uuid.uuid4()
        task_insert = pg_insert(Task).values(
            {
                "id": task_id,
                "title": task_title,
                "description": description,
                "internal_notes": None,
                "department_id": department_map.get(user_id) or meeting.department_id,
                "assigned_to": user_id,
                "created_by": meeting.created_by or user_id,
                "system_template_origin_id": template.id,
                "system_task_slot_id": slot.id,
                "origin_run_at": task_start_at,
                "start_date": task_start_at,
                "due_date": task_start_at,
                "meeting_origin_id": meeting.id,
                "meeting_occurrence_date": occurrence_date,
                "meeting_system_task_kind": task_kind,
                "status": TaskStatus.TODO.value,
                "priority": TaskPriority.NORMAL.value,
                "finish_period": TaskFinishPeriod.AM.value,
                "is_active": True,
                "created_at": now_utc,
                "updated_at": now_utc,
            }
        )
        task_insert = task_insert.on_conflict_do_nothing(
            index_elements=[
                "meeting_origin_id",
                "meeting_occurrence_date",
                "assigned_to",
                "meeting_system_task_kind",
            ],
            index_where=and_(
                Task.meeting_origin_id.is_not(None),
                Task.meeting_system_task_kind.is_not(None),
            ),
        ).returning(Task.id)
        inserted_task_id = (await db.execute(task_insert)).scalar_one_or_none()
        if inserted_task_id is None:
            continue
        await db.execute(
            pg_insert(TaskAssignee)
            .values({"task_id": inserted_task_id, "user_id": user_id})
            .on_conflict_do_nothing(index_elements=["task_id", "user_id"])
        )
        created_or_reactivated += 1

    return created_or_reactivated


async def reconcile_external_meeting_system_tasks_for_meeting(
    db: AsyncSession,
    meeting: Meeting,
    *,
    now_utc: datetime | None = None,
) -> int:
    changed = await reconcile_agent_test_task_for_meeting(db, meeting, now_utc=now_utc)
    changed += await reconcile_pim_image_test_task_for_meeting(db, meeting, now_utc=now_utc)
    return changed


async def reconcile_agent_test_task_for_meeting(
    db: AsyncSession,
    meeting: Meeting,
    *,
    now_utc: datetime | None = None,
) -> int:
    agent_qualifies = is_one_time_external_meeting(meeting)
    agent_ids = await _fixed_assignee_ids(db) if agent_qualifies else []
    agent_template = await ensure_external_meeting_trigger_template(db) if agent_qualifies and agent_ids else None
    return await _reconcile_external_meeting_task_kind(
        db,
        meeting,
        task_kind=EXTERNAL_MEETING_TASK_KIND,
        description=EXTERNAL_MEETING_TASK_DESCRIPTION,
        qualifies=agent_qualifies,
        participant_ids=agent_ids,
        task_title=external_meeting_task_title(meeting),
        template=agent_template,
        now_utc=now_utc,
    )


async def reconcile_pim_image_test_task_for_meeting(
    db: AsyncSession,
    meeting: Meeting,
    *,
    now_utc: datetime | None = None,
) -> int:
    pim_qualifies = is_one_time_external_pim_image_meeting(meeting)
    pim_ids = await _graphic_design_assignee_ids(db) if pim_qualifies else []
    pim_template = await ensure_pim_image_meeting_trigger_template(db) if pim_qualifies and pim_ids else None
    return await _reconcile_external_meeting_task_kind(
        db,
        meeting,
        task_kind=PIM_IMAGE_MEETING_TASK_KIND,
        description=PIM_IMAGE_MEETING_TASK_DESCRIPTION,
        qualifies=pim_qualifies,
        participant_ids=pim_ids,
        task_title=pim_image_meeting_task_title(meeting),
        template=pim_template,
        now_utc=now_utc,
    )


async def deactivate_external_meeting_system_tasks(
    db: AsyncSession,
    meeting_id: uuid.UUID,
) -> int:
    tasks = (
        await db.execute(
            select(Task)
            .where(Task.meeting_origin_id == meeting_id)
            .where(
                Task.meeting_system_task_kind.in_(
                    (EXTERNAL_MEETING_TASK_KIND, PIM_IMAGE_MEETING_TASK_KIND, *TAK_INT_ONE_H_TASK_KINDS)
                )
            )
        )
    ).scalars().all()
    changed = 0
    for task in tasks:
        if task.status == TaskStatus.DONE or not task.is_active:
            continue
        task.is_active = False
        changed += 1
    return changed


async def reconcile_external_meeting_system_tasks(
    db: AsyncSession,
    *,
    start: date | None = None,
    end: date | None = None,
    now_utc: datetime | None = None,
) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    local_today = now_utc.astimezone(_app_tz()).date()
    start = start or local_today
    end = end or (local_today + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0)))
    if end < start:
        return 0

    start_utc, _ = _local_day_bounds_utc(start)
    _, end_utc = _local_day_bounds_utc(end)
    meetings = (
        await db.execute(
            select(Meeting)
            .where(Meeting.starts_at.is_not(None))
            .where(Meeting.starts_at >= start_utc)
            .where(Meeting.starts_at < end_utc)
            .where(Meeting.meeting_type == "external")
            .where(
                or_(
                    Meeting.external_agent_test_task_requested.is_(True),
                    Meeting.external_pim_image_test_task_requested.is_(True),
                )
            )
            .where(or_(Meeting.recurrence_type.is_(None), Meeting.recurrence_type == "", Meeting.recurrence_type == "none"))
        )
    ).scalars().all()

    changed = 0
    for meeting in meetings:
        changed += await reconcile_external_meeting_system_tasks_for_meeting(
            db,
            meeting,
            now_utc=now_utc,
        )
    return changed


def _shift_working_day(day: date, step: int) -> date:
    day += timedelta(days=step)
    while day.weekday() >= 5:
        day += timedelta(days=step)
    return day


def _as_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_app_tz())


def tak_int_pre_one_h_slot(meeting: Meeting | object) -> tuple[date, str] | None:
    """Return the last 1H slot strictly before the TAK EXT starts (13:00 -> 11:50)."""
    starts_at = getattr(meeting, "starts_at", None)
    if starts_at is None:
        return None
    local_start = _as_local(starts_at)
    start_time = local_start.time().replace(tzinfo=None)
    earlier = [label for slot_time, label in TAK_INT_ONE_H_SLOTS if slot_time < start_time]
    if earlier:
        return local_start.date(), earlier[-1]
    return _shift_working_day(local_start.date(), -1), TAK_INT_ONE_H_SLOTS[-1][1]


def tak_int_post_one_h_slot(
    meeting: Meeting | object,
    internal_meeting: Meeting | object | None = None,
) -> tuple[date, str] | None:
    """Return the 1H slot for the TAK INT held after a TAK EXT.

    With a scheduled TAK INT it is the slot it falls in (TAK INT 14:30 -> 14:20);
    otherwise the first slot once the TAK EXT has finished (ends 13:30 -> 14:20).
    """
    starts_at = getattr(meeting, "starts_at", None)
    if starts_at is None:
        return None
    internal_starts_at = getattr(internal_meeting, "starts_at", None)
    if internal_starts_at is not None:
        local_internal = _as_local(internal_starts_at)
        internal_time = local_internal.time().replace(tzinfo=None)
        current = [label for slot_time, label in TAK_INT_ONE_H_SLOTS if slot_time <= internal_time]
        return local_internal.date(), current[-1] if current else TAK_INT_ONE_H_SLOTS[0][1]
    ends_at = getattr(meeting, "ends_at", None) or starts_at + timedelta(hours=1)
    local_end = _as_local(ends_at)
    end_time = local_end.time().replace(tzinfo=None)
    for slot_time, label in TAK_INT_ONE_H_SLOTS:
        if slot_time >= end_time:
            return local_end.date(), label
    return _shift_working_day(local_end.date(), 1), TAK_INT_ONE_H_SLOTS[0][1]


def _one_h_slot_start_at(day: date, label: str) -> datetime:
    slot_time = next(slot_time for slot_time, slot_label in TAK_INT_ONE_H_SLOTS if slot_label == label)
    return datetime.combine(day, slot_time, tzinfo=_app_tz()).astimezone(timezone.utc)


def _one_h_slot_finish_period(label: str) -> str:
    return TaskFinishPeriod.AM.value if label < "12:00" else TaskFinishPeriod.PM.value


def qualifies_for_tak_int_one_h_tasks(meeting: Meeting | object) -> bool:
    recurrence_type = (getattr(meeting, "recurrence_type", None) or "").strip().lower()
    sync_status = (getattr(meeting, "calendar_sync_status", None) or "").strip().lower()
    return (
        (getattr(meeting, "meeting_type", None) or "external") == "external"
        and recurrence_type in ("", "none")
        and getattr(meeting, "starts_at", None) is not None
        and sync_status not in INACTIVE_CALENDAR_SYNC_STATUSES
    )


async def _post_internal_meeting(db: AsyncSession, external_meeting_id: uuid.UUID) -> Meeting | None:
    return (
        await db.execute(
            select(Meeting).where(
                Meeting.meeting_type == "internal",
                Meeting.paired_external_meeting_id == external_meeting_id,
            )
        )
    ).scalars().first()


async def _resolve_external_meeting(db: AsyncSession, meeting: Meeting) -> Meeting | None:
    if meeting.meeting_type == "external":
        return meeting
    external_id = meeting.pre_external_meeting_id or meeting.paired_external_meeting_id
    if external_id is None:
        return None
    return (await db.execute(select(Meeting).where(Meeting.id == external_id))).scalar_one_or_none()


async def reconcile_tak_int_one_h_tasks_for_meeting(
    db: AsyncSession,
    meeting: Meeting,
    *,
    now_utc: datetime | None = None,
) -> int:
    """Create/update the TAK INT 1H tasks for the people assigned on a TAK EXT.

    Accepts the TAK EXT itself or one of its linked TAK INT meetings.
    """
    external = await _resolve_external_meeting(db, meeting)
    if external is None:
        return 0

    qualifies = qualifies_for_tak_int_one_h_tasks(external)
    # Weekly/routine calendar meetings have only a follow-up TAK INT. Keep
    # their tasks consistent, including deactivating old open preparation tasks.
    needs_preparation = qualifies and not is_routine_external_meeting(
        getattr(external, "calendar_categories", None), external.recurrence_type
    )
    participant_ids: list[uuid.UUID] = []
    post_internal: Meeting | None = None
    if qualifies:
        participant_ids = (await manual_participant_ids(db, [external.id])).get(external.id, [])
        post_internal = await _post_internal_meeting(db, external.id)

    changed = 0
    for task_kind, base_title, description, slot in (
        (
            TAK_INT_PRE_ONE_H_TASK_KIND,
            TAK_INT_PRE_ONE_H_TASK_TITLE,
            TAK_INT_PRE_ONE_H_TASK_DESCRIPTION,
            tak_int_pre_one_h_slot(external) if needs_preparation else None,
        ),
        (
            TAK_INT_POST_ONE_H_TASK_KIND,
            TAK_INT_POST_ONE_H_TASK_TITLE,
            TAK_INT_POST_ONE_H_TASK_DESCRIPTION,
            tak_int_post_one_h_slot(external, post_internal) if post_internal is not None else None,
        ),
    ):
        changed += await _reconcile_tak_int_one_h_task_kind(
            db,
            external,
            task_kind=task_kind,
            task_title=_meeting_task_title(external, base_title),
            description=description,
            slot=slot,
            participant_ids=participant_ids,
            now_utc=now_utc or datetime.now(timezone.utc),
        )
    return changed


async def _reconcile_tak_int_one_h_task_kind(
    db: AsyncSession,
    external: Meeting,
    *,
    task_kind: str,
    task_title: str,
    description: str,
    slot: tuple[date, str] | None,
    participant_ids: list[uuid.UUID],
    now_utc: datetime,
) -> int:
    existing_tasks = (
        await db.execute(
            select(Task)
            .where(Task.meeting_origin_id == external.id)
            .where(Task.meeting_system_task_kind == task_kind)
            .order_by(Task.created_at.asc())
        )
    ).scalars().all()
    participant_id_set = set(participant_ids) if slot is not None else set()

    current_by_user: dict[uuid.UUID, Task] = {}
    for task in existing_tasks:
        # Plain 1H tasks: detach anything left over from the system-task version.
        task.system_template_origin_id = None
        task.system_task_slot_id = None
        task.origin_run_at = None
        if task.assigned_to in participant_id_set and task.assigned_to not in current_by_user:
            current_by_user[task.assigned_to] = task
        elif task.status != TaskStatus.DONE:
            task.is_active = False

    if slot is None or not participant_ids:
        return 0

    slot_date, slot_label = slot
    if slot_date < now_utc.astimezone(_app_tz()).date():
        # The slot day is already over: never create (or move) a task into the past,
        # and drop open tasks that were created only after their day had passed.
        for task in current_by_user.values():
            if task.status == TaskStatus.DONE or task.start_date is None or task.created_at is None:
                continue
            if _as_local(task.created_at).date() > _as_local(task.start_date).date():
                task.is_active = False
        return 0

    task_start_at = _one_h_slot_start_at(slot_date, slot_label)
    finish_period = _one_h_slot_finish_period(slot_label)
    department_map = await _user_department_map(db, participant_ids)
    changed = 0
    for user_id in participant_ids:
        existing = current_by_user.get(user_id)
        if existing is not None:
            if existing.status == TaskStatus.DONE:
                continue
            if not existing.is_active:
                changed += 1
            existing.title = task_title
            existing.description = description
            existing.is_1h_report = True
            existing.is_active = True
            # Only move the slot when the meeting time moved, so manual slot edits stick.
            if existing.start_date != task_start_at:
                existing.start_date = task_start_at
                existing.due_date = task_start_at
                existing.meeting_occurrence_date = slot_date
                existing.one_h_report_slot = slot_label
                existing.finish_period = finish_period
                await _set_one_h_report_slot_row(db, existing.id, slot_date, slot_label, overwrite=True)
                changed += 1
            else:
                await _set_one_h_report_slot_row(
                    db, existing.id, slot_date, existing.one_h_report_slot or slot_label, overwrite=False
                )
            continue

        task_insert = pg_insert(Task).values(
            {
                "id": uuid.uuid4(),
                "title": task_title,
                "description": description,
                "department_id": department_map.get(user_id) or external.department_id,
                "assigned_to": user_id,
                "created_by": external.created_by or user_id,
                "start_date": task_start_at,
                "due_date": task_start_at,
                "meeting_origin_id": external.id,
                "meeting_occurrence_date": slot_date,
                "meeting_system_task_kind": task_kind,
                "status": TaskStatus.TODO.value,
                "priority": TaskPriority.NORMAL.value,
                "finish_period": finish_period,
                "is_1h_report": True,
                "one_h_report_slot": slot_label,
                "is_active": True,
                "created_at": now_utc,
                "updated_at": now_utc,
            }
        ).on_conflict_do_nothing(
            index_elements=[
                "meeting_origin_id",
                "meeting_occurrence_date",
                "assigned_to",
                "meeting_system_task_kind",
            ],
            index_where=and_(
                Task.meeting_origin_id.is_not(None),
                Task.meeting_system_task_kind.is_not(None),
            ),
        ).returning(Task.id)
        inserted_task_id = (await db.execute(task_insert)).scalar_one_or_none()
        if inserted_task_id is None:
            continue
        await db.execute(
            pg_insert(TaskAssignee)
            .values({"task_id": inserted_task_id, "user_id": user_id})
            .on_conflict_do_nothing(index_elements=["task_id", "user_id"])
        )
        await _set_one_h_report_slot_row(db, inserted_task_id, slot_date, slot_label, overwrite=True)
        changed += 1
    return changed


async def _set_one_h_report_slot_row(
    db: AsyncSession,
    task_id: uuid.UUID,
    report_date: date,
    slot_label: str,
    *,
    overwrite: bool,
) -> None:
    """Daily views (My View, reports) read the 1H slot only from the per-day slot rows."""
    statement = pg_insert(TaskOneHReportSlot).values(
        {
            "id": uuid.uuid4(),
            "task_id": task_id,
            "report_date": report_date,
            "one_h_report_slot": slot_label,
        }
    )
    if overwrite:
        statement = statement.on_conflict_do_update(
            index_elements=["task_id", "report_date"],
            set_={"one_h_report_slot": slot_label, "updated_at": func.now()},
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=["task_id", "report_date"])
    await db.execute(statement)


async def reconcile_tak_int_one_h_tasks(
    db: AsyncSession,
    *,
    start: date | None = None,
    end: date | None = None,
    now_utc: datetime | None = None,
) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    local_today = now_utc.astimezone(_app_tz()).date()
    start = start or local_today
    end = end or (local_today + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0)))
    if end < start:
        return 0
    # Look a week back too, so open tasks wrongly dated in the past get cleaned up.
    start_utc, _ = _local_day_bounds_utc(start - timedelta(days=7))
    _, end_utc = _local_day_bounds_utc(end)
    meetings = (
        await db.execute(
            select(Meeting)
            .where(Meeting.starts_at.is_not(None))
            .where(Meeting.starts_at >= start_utc)
            .where(Meeting.starts_at < end_utc)
            .where(Meeting.meeting_type == "external")
        )
    ).scalars().all()
    changed = 0
    for meeting in meetings:
        changed += await reconcile_tak_int_one_h_tasks_for_meeting(db, meeting, now_utc=now_utc)
    return changed
