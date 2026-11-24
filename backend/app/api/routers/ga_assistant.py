"""GA assistant API used by the MCP assistant profile (``PRIMEFLOW_MCP_PROFILE=assistant``).

Reads build one agenda from PrimeFlow tasks, meetings, Outlook and Microsoft To Do
(see app.services.ga_assistant). Writes reuse the existing PrimeFlow operations
(task update, task comment, meeting occurrence status) so permissions, audit and
side effects stay identical to the web app, and each write adds its own
``ga_assistant`` audit entry. Only the GA account or an admin may call these.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import TaskStatus, UserRole
from app.models.oauth import GaAssistantItemTime
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.task import Task
from app.models.task_alignment_user import TaskAlignmentUser
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.schemas.ga_discord_mentions import (
    DISCORD_FEED_DEFAULT_LIMIT,
    DISCORD_FEED_MAX_LIMIT,
    DISCORD_MESSAGE_ID_PATTERN,
    DiscordMentionAttachments,
    DiscordMentionsFeed,
)
from app.services import ga_assistant as svc
from app.services.audit import add_audit_log
from app.services.ga_identity import is_ga_user

router = APIRouter()


# ---------------------------------------------------------------- helpers


def ensure_assistant_user(user: User) -> None:
    if is_ga_user(user) or user.role == UserRole.ADMIN:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the GA account or an admin can use the GA assistant")


def _parse_moment(value: str | None, *, default: datetime) -> datetime:
    tz = svc.ga_tz()
    if not value:
        return default
    raw = value.strip()
    try:
        if "T" not in raw and len(raw) == 10:
            return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=tz)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid ISO 8601 date/time: {value}")
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed.astimezone(tz)


def _now() -> datetime:
    return datetime.now(svc.ga_tz())


def _audit_id(item_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"primeflow-ga-assistant:{item_id}")


def _audit(db: AsyncSession, user: User, entity_id: uuid.UUID, action: str, after: dict) -> None:
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="ga_assistant", entity_id=entity_id,
        action=action, after={**after, "via": "mcp_assistant"},
    )


ITEM_PREFIXES = (svc.PREFIX_TASK, svc.PREFIX_MEETING, svc.PREFIX_EVENT, svc.PREFIX_TODO, svc.PREFIX_TIME_TABLE, svc.PREFIX_DISCORD)
IPHONE_READ_ONLY = (
    "iPhone reminders (tt:) come from the one-way iPhone Sync (iPhone -> PrimeFlow); PrimeFlow cannot change them "
    "on the phone. Complete, move or edit the reminder in Reminders on the iPhone; the next sync updates PrimeFlow. "
    "remove_from_day can still hide it from GA's assistant day."
)


def _parse_item(item_id: str) -> tuple[str, str]:
    for prefix in ITEM_PREFIXES:
        if item_id.startswith(prefix) and len(item_id) > len(prefix):
            return prefix, item_id[len(prefix):]
    raise HTTPException(status_code=422, detail="item_id must start with pf_task:, pf_meeting:, ms_event:, todo:, tt: or dc:")


async def _set_discord_status(db: AsyncSession, user: User, raw: str, new_status: str):
    from app.models.ga_discord_mention import GaDiscordMention

    if not is_ga_user(user) and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only the GA account or an admin can mark GA's Discord mentions")
    row = await db.get(GaDiscordMention, raw)
    if row is None:
        raise HTTPException(status_code=404, detail="Discord mention not found")
    previous = row.status
    row.status, row.status_changed_at, row.status_changed_by = new_status, datetime.now(timezone.utc), user.id
    _audit(db, user, _audit_id(f"{svc.PREFIX_DISCORD}{raw}"), "GA_ASSISTANT_DISCORD_MARK",
           {"item_id": f"{svc.PREFIX_DISCORD}{raw}", "from": previous, "to": new_status})
    await db.commit()
    return row


def _task_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid PrimeFlow task id")


def _meeting_ref(raw: str) -> tuple[uuid.UUID, date]:
    meeting_raw, _, day_raw = raw.partition("@")
    try:
        return uuid.UUID(meeting_raw), date.fromisoformat(day_raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Meeting ids look like pf_meeting:<uuid>@YYYY-MM-DD")


def _todo_ref(raw: str) -> tuple[str, str]:
    list_id, sep, task_id = raw.partition(svc.TODO_ID_SEPARATOR)
    if not sep or not list_id or not task_id:
        raise HTTPException(status_code=422, detail="To Do ids look like todo:<list_id>::<task_id>")
    return list_id, task_id


async def _load_task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None or not task.is_active:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def _relation(db: AsyncSession, task: Task, user: User) -> str:
    """'owner' (assignee or confirmer), 'bz' (alignment only) or 'other'."""
    is_assignee = task.assigned_to == user.id or (
        await db.execute(select(TaskAssignee).where(TaskAssignee.task_id == task.id, TaskAssignee.user_id == user.id))
    ).first() is not None
    status_value = svc.task_status(task)
    if is_assignee or (status_value == "WAITING_CONFIRMATION" and task.confirmation_assignee_id == user.id):
        return "owner"
    aligned = (
        await db.execute(select(TaskAlignmentUser).where(TaskAlignmentUser.task_id == task.id, TaskAlignmentUser.user_id == user.id))
    ).first() is not None
    if not aligned and task.system_template_origin_id is not None:
        aligned = (
            await db.execute(
                select(SystemTaskTemplateAlignmentUser).where(
                    SystemTaskTemplateAlignmentUser.template_id == task.system_template_origin_id,
                    SystemTaskTemplateAlignmentUser.user_id == user.id,
                )
            )
        ).first() is not None
    return "bz" if aligned else "other"


async def _upsert_day_state(db: AsyncSession, user: User, item_key: str, day: date, **values) -> None:
    row = (
        await db.execute(
            select(GaAssistantItemTime).where(
                GaAssistantItemTime.user_id == user.id,
                GaAssistantItemTime.item_key == item_key,
                GaAssistantItemTime.day_date == day,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = GaAssistantItemTime(user_id=user.id, item_key=item_key, day_date=day)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by = user.id


async def _todo_client(db: AsyncSession):
    from app.integrations.microsoft_todo import TodoClient, TodoScopeMissing, ensure_todo_scope
    from app.services.microsoft_calendar_sync import get_shared_calendar_token

    if not settings.MS_TODO_ENABLED:
        raise HTTPException(status_code=503, detail="Microsoft To Do is not enabled (MS_TODO_ENABLED=false)")
    if not settings.MS_REDIRECT_URI:
        raise HTTPException(status_code=503, detail="Microsoft integration is not configured")
    token = await get_shared_calendar_token(db, redirect_uri=settings.MS_REDIRECT_URI)
    if token is None:
        raise HTTPException(status_code=503, detail=f"No Microsoft connection for {settings.MS_ORGANIZER_EMAIL}")
    try:
        ensure_todo_scope(token.scope)
    except TodoScopeMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return TodoClient(token.access_token)


def _ensure_todo_allowed(user: User) -> None:
    if not is_ga_user(user):
        raise HTTPException(status_code=403, detail="Microsoft To Do of the organizer mailbox is available to the GA account only")


async def _graph_call(coro):
    import httpx

    try:
        return await coro
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        raise HTTPException(status_code=404 if code == 404 else 502, detail=f"Microsoft Graph request failed ({code})")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Microsoft Graph is unreachable")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------- reads


@router.get("/agenda")
async def agenda(
    start: str = Query(..., description="ISO 8601 start (inclusive)"),
    end: str = Query(..., description="ISO 8601 end (exclusive)"),
    include_untimed: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ensure_assistant_user(user)
    now = _now()
    window_start = _parse_moment(start, default=now)
    window_end = _parse_moment(end, default=now + timedelta(hours=1))
    if window_end <= window_start or window_end - window_start > timedelta(days=31):
        raise HTTPException(status_code=422, detail="end must be after start and the window at most 31 days")
    last_day = (window_end - timedelta(microseconds=1)).date()
    items, warnings = await svc.collect_items(
        db, user, window_start.date(), last_day, include_microsoft=is_ga_user(user), now=now
    )
    selected = svc.select_agenda(items, window_start, window_end, include_untimed=include_untimed)
    return {
        "timezone": settings.GA_TIMEZONE,
        "start": window_start.isoformat(),
        "end": window_end.isoformat(),
        "count": len(selected),
        "items": [item.to_dict() for item in selected],
        "warnings": warnings,
    }


@router.get("/leftovers")
async def leftovers(
    as_of: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ensure_assistant_user(user)
    moment = _parse_moment(as_of, default=_now())
    day_from = moment.date() - timedelta(days=svc.LEFTOVER_LOOKBACK_DAYS)
    items, warnings = await svc.collect_items(db, user, day_from, moment.date(), include_microsoft=is_ga_user(user), now=moment)
    selected = svc.select_leftovers(items, moment)
    return {
        "timezone": settings.GA_TIMEZONE,
        "as_of": moment.isoformat(),
        "count": len(selected),
        "items": [item.to_dict() for item in selected],
        "warnings": warnings,
    }


@router.get("/untimed")
async def untimed(
    day: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ensure_assistant_user(user)
    target = _parse_moment(day, default=_now()).date()
    items, warnings = await svc.collect_items(db, user, target, target, include_microsoft=is_ga_user(user))
    selected = svc.select_untimed(items, target)
    return {
        "timezone": settings.GA_TIMEZONE,
        "date": target.isoformat(),
        "count": len(selected),
        "items": [item.to_dict() for item in selected],
        "warnings": warnings,
    }


# ---------------------------------------------------------------- writes


class ItemDoneIn(BaseModel):
    item_id: str = Field(min_length=5, max_length=600)
    # PrimeFlow closes a task only with the closer's personal result comment (RLZ rule),
    # or - for managers/admins - an audited override reason. Both are optional here and
    # the backend explains with a 409 when one is needed.
    comment: str | None = Field(default=None, max_length=4000)
    override_reason: str | None = Field(default=None, max_length=2000)


class ItemPostponeIn(BaseModel):
    item_id: str = Field(min_length=5, max_length=600)
    new_date: date
    new_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    reason_code: str | None = Field(default=None, max_length=40)
    reason_comment: str | None = Field(default=None, max_length=2000)


class ItemSetTimeIn(BaseModel):
    item_id: str = Field(min_length=5, max_length=600)
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    day: date | None = None


class ItemRemoveIn(BaseModel):
    item_id: str = Field(min_length=5, max_length=600)
    reason: str = Field(min_length=2, max_length=1000)
    day: date | None = None


class ItemCommentIn(BaseModel):
    item_id: str = Field(min_length=5, max_length=600)
    text: str = Field(min_length=1, max_length=4000)


@router.post("/items/done")
async def item_done(payload: ItemDoneIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_assistant_user(user)
    prefix, raw = _parse_item(payload.item_id)
    if prefix == svc.PREFIX_TASK:
        from app.api.routers.tasks import TaskCommentUpdate, update_task_in_session, update_task_user_comment_in_session
        from app.schemas.task import TaskUpdate

        task = await _load_task(db, _task_uuid(raw))
        if not svc.task_is_open(task):
            return {"item_id": payload.item_id, "result": "already_done", "status": "DONE"}
        relation = await _relation(db, task, user)
        if relation == "owner":
            if payload.comment and payload.comment.strip():
                # Same transaction as the status change: the comment is committed only if closing succeeds.
                await update_task_user_comment_in_session(
                    task.id, TaskCommentUpdate(comment=payload.comment.strip()), db, user, append=True
                )
            update = TaskUpdate(status=TaskStatus.DONE)
            update.completion_override_reason = payload.override_reason
            await update_task_in_session(
                task.id, update, db, user,
                before_commit=lambda t: _audit(db, user, t.id, "GA_ASSISTANT_DONE", {"item_id": payload.item_id}),
            )
            return {"item_id": payload.item_id, "result": "done", "status": "DONE"}
        if relation == "bz":
            stamp = _now().strftime("%d.%m.%Y %H:%M")
            await update_task_user_comment_in_session(task.id, TaskCommentUpdate(comment=f"BZ u mbajt ({stamp})"), db, user, append=True)
            _audit(db, user, task.id, "GA_ASSISTANT_BZ_HELD", {"item_id": payload.item_id, "at": stamp})
            await db.commit()
            return {"item_id": payload.item_id, "result": "bz_held", "status": svc.task_status(task)}
        raise HTTPException(status_code=409, detail="GA is neither assignee, confirmer nor BZ person of this task, so it is not closed from here")
    if prefix == svc.PREFIX_MEETING:
        from app.api.routers.meetings import update_meeting_occurrence_status_in_session
        from app.schemas.meeting import MeetingOccurrenceStatusUpdate

        meeting_id, day = _meeting_ref(raw)

        async def audit_meeting(meeting) -> None:  # meetings awaits its before_commit hook
            _audit(db, user, meeting.id, "GA_ASSISTANT_MEETING_HELD", {"item_id": payload.item_id})

        await update_meeting_occurrence_status_in_session(
            meeting_id, MeetingOccurrenceStatusUpdate(occurrence_date=day, status="held"), db, user,
            before_commit=audit_meeting,
        )
        return {"item_id": payload.item_id, "result": "held", "status": "Mbajtur"}
    if prefix == svc.PREFIX_TODO:
        _ensure_todo_allowed(user)
        list_id, task_id = _todo_ref(raw)
        client = await _todo_client(db)
        await _graph_call(client.update(list_id, task_id, {"status": "completed"}))
        _audit(db, user, _audit_id(payload.item_id), "GA_ASSISTANT_TODO_DONE", {"item_id": payload.item_id})
        await db.commit()
        return {"item_id": payload.item_id, "result": "done", "status": "completed"}
    if prefix == svc.PREFIX_DISCORD:
        await _set_discord_status(db, user, raw, "done")
        return {"item_id": payload.item_id, "result": "done", "status": "done"}
    if prefix == svc.PREFIX_TIME_TABLE:
        raise HTTPException(status_code=409, detail=IPHONE_READ_ONLY)
    raise HTTPException(status_code=409, detail="Outlook events are read-only here")


@router.post("/items/postpone")
async def item_postpone(payload: ItemPostponeIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_assistant_user(user)
    prefix, raw = _parse_item(payload.item_id)
    tz = svc.ga_tz()
    if prefix == svc.PREFIX_TASK:
        from app.api.routers.tasks import update_task_in_session
        from app.schemas.task import TaskUpdate

        task = await _load_task(db, _task_uuid(raw))
        if await _relation(db, task, user) == "bz":
            raise HTTPException(status_code=409, detail="A BZ follows the assignee's task; use set_time or remove_from_day for GA's day instead")
        reference = task.due_date or task.start_date
        tod = reference.astimezone(tz).timetz().replace(tzinfo=None) if reference is not None else time(0, 0)
        new_due = datetime.combine(payload.new_date, tod, tzinfo=tz)
        fields: dict = {"due_date": new_due}
        if task.start_date is not None and svc.local_date(task.start_date, tz) > payload.new_date:
            fields["start_date"] = new_due
        update = TaskUpdate(**fields)
        update.postponement_reason_code = payload.reason_code
        update.postponement_comment = payload.reason_comment
        before = {"due_date": task.due_date.isoformat() if task.due_date else None}
        await update_task_in_session(
            task.id, update, db, user,
            before_commit=lambda t: _audit(
                db, user, t.id, "GA_ASSISTANT_POSTPONE",
                {"item_id": payload.item_id, **before, "new_date": payload.new_date.isoformat(), "new_time": payload.new_time},
            ),
        )
        if payload.new_time is not None:
            await _upsert_day_state(
                db, user, payload.item_id, payload.new_date, has_time_override=True, time_value=payload.new_time, removed=False
            )
            await db.commit()
        return {"item_id": payload.item_id, "result": "postponed", "new_date": payload.new_date.isoformat(), "new_time": payload.new_time}
    if prefix == svc.PREFIX_TODO:
        from app.integrations.microsoft_todo import due_payload, graph_datetime, parse_graph_dt

        _ensure_todo_allowed(user)
        list_id, task_id = _todo_ref(raw)
        client = await _todo_client(db)
        current = await _graph_call(client.get(list_id, task_id))
        body: dict = {"dueDateTime": due_payload(payload.new_date)}
        reminder = parse_graph_dt(current.get("reminderDateTime"), tz) if current.get("isReminderOn") else None
        new_time = svc.parse_hhmm(payload.new_time) if payload.new_time else (reminder.timetz().replace(tzinfo=None) if reminder else None)
        if new_time is not None:
            body.update(reminderDateTime=graph_datetime(payload.new_date, new_time, tz), isReminderOn=True)
        await _graph_call(client.update(list_id, task_id, body))
        _audit(db, user, _audit_id(payload.item_id), "GA_ASSISTANT_TODO_POSTPONE",
               {"item_id": payload.item_id, "new_date": payload.new_date.isoformat(), "new_time": payload.new_time})
        await db.commit()
        return {"item_id": payload.item_id, "result": "postponed", "new_date": payload.new_date.isoformat(),
                "new_time": new_time.strftime("%H:%M") if new_time else None}
    if prefix == svc.PREFIX_TIME_TABLE:
        raise HTTPException(status_code=409, detail=IPHONE_READ_ONLY)
    if prefix == svc.PREFIX_DISCORD:
        raise HTTPException(status_code=409, detail="Discord mentions are marked seen/done, not postponed")
    raise HTTPException(status_code=409, detail="Meetings and Outlook events are moved in the calendar, not from the assistant")


@router.post("/items/set-time")
async def item_set_time(payload: ItemSetTimeIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_assistant_user(user)
    prefix, raw = _parse_item(payload.item_id)
    tz = svc.ga_tz()
    today = _now().date()
    if payload.time is not None:
        svc.parse_hhmm(payload.time)
    if prefix == svc.PREFIX_TASK:
        task = await _load_task(db, _task_uuid(raw))
        plan_day = svc.task_plan_day(task, tz)
        day = payload.day or (plan_day if plan_day and plan_day >= today else today)
        await _upsert_day_state(db, user, payload.item_id, day, has_time_override=True, time_value=payload.time)
        _audit(db, user, task.id, "GA_ASSISTANT_SET_TIME", {"item_id": payload.item_id, "day": day.isoformat(), "time": payload.time})
        await db.commit()
        return {"item_id": payload.item_id, "result": "time_set", "day": day.isoformat(), "time": payload.time}
    if prefix == svc.PREFIX_TODO:
        from app.integrations.microsoft_todo import due_payload, graph_datetime, parse_due_date

        _ensure_todo_allowed(user)
        list_id, task_id = _todo_ref(raw)
        client = await _todo_client(db)
        current = await _graph_call(client.get(list_id, task_id))
        day = payload.day or parse_due_date(current.get("dueDateTime"), tz) or today
        if payload.time is None:
            body: dict = {"isReminderOn": False, "reminderDateTime": None}
        else:
            body = {
                "dueDateTime": due_payload(day),
                "reminderDateTime": graph_datetime(day, svc.parse_hhmm(payload.time), tz),
                "isReminderOn": True,
            }
        await _graph_call(client.update(list_id, task_id, body))
        _audit(db, user, _audit_id(payload.item_id), "GA_ASSISTANT_TODO_SET_TIME",
               {"item_id": payload.item_id, "day": day.isoformat(), "time": payload.time})
        await db.commit()
        return {"item_id": payload.item_id, "result": "time_set", "day": day.isoformat(), "time": payload.time}
    if prefix == svc.PREFIX_TIME_TABLE:
        raise HTTPException(status_code=409, detail=IPHONE_READ_ONLY)
    raise HTTPException(status_code=409, detail="Meetings, Outlook events and Discord mentions keep their own time")


@router.post("/items/remove-from-day")
async def item_remove_from_day(payload: ItemRemoveIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Soft removal: hides the item from GA's assistant agenda for one day; nothing is deleted."""
    ensure_assistant_user(user)
    prefix, raw = _parse_item(payload.item_id)
    day = payload.day or (_meeting_ref(raw)[1] if prefix == svc.PREFIX_MEETING else _now().date())
    if prefix == svc.PREFIX_TASK:
        await _load_task(db, _task_uuid(raw))
    await _upsert_day_state(db, user, payload.item_id, day, removed=True, removed_reason=payload.reason)
    entity_id = _task_uuid(raw) if prefix == svc.PREFIX_TASK else _audit_id(payload.item_id)
    _audit(db, user, entity_id, "GA_ASSISTANT_REMOVE_FROM_DAY", {"item_id": payload.item_id, "day": day.isoformat(), "reason": payload.reason})
    await db.commit()
    return {"item_id": payload.item_id, "result": "removed_from_day", "day": day.isoformat()}


@router.post("/items/comment")
async def item_comment(payload: ItemCommentIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    ensure_assistant_user(user)
    prefix, raw = _parse_item(payload.item_id)
    if prefix == svc.PREFIX_TASK:
        from app.api.routers.tasks import TaskCommentUpdate, update_task_user_comment_in_session

        task = await _load_task(db, _task_uuid(raw))
        await update_task_user_comment_in_session(task.id, TaskCommentUpdate(comment=payload.text.strip()), db, user, append=True)
        _audit(db, user, task.id, "GA_ASSISTANT_COMMENT", {"item_id": payload.item_id})
        await db.commit()
        return {"item_id": payload.item_id, "result": "commented"}
    if prefix == svc.PREFIX_TODO:
        from app.integrations.microsoft_todo import join_body, split_body

        _ensure_todo_allowed(user)
        list_id, task_id = _todo_ref(raw)
        client = await _todo_client(db)
        current = await _graph_call(client.get(list_id, task_id))
        notes, steps = split_body((current.get("body") or {}).get("content"))
        notes = f"{notes}\n{payload.text.strip()}".strip()
        await _graph_call(client.update(list_id, task_id, {"body": {"contentType": "text", "content": join_body(notes, steps)}}))
        _audit(db, user, _audit_id(payload.item_id), "GA_ASSISTANT_TODO_COMMENT", {"item_id": payload.item_id})
        await db.commit()
        return {"item_id": payload.item_id, "result": "commented"}
    if prefix == svc.PREFIX_TIME_TABLE:
        raise HTTPException(status_code=409, detail=IPHONE_READ_ONLY)
    raise HTTPException(status_code=409, detail="Comments are supported on PrimeFlow tasks and To Do items")


# ---------------------------------------------------------------- Microsoft To Do


class TodoCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_date: date | None = None
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    notes: str | None = Field(default=None, max_length=4000)
    list_name: str | None = Field(default=None, max_length=255)


class TodoUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    due_date: date | None = None
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    clear_time: bool = False
    notes: str | None = Field(default=None, max_length=4000)


class TodoStepIn(BaseModel):
    text: str = Field(min_length=1, max_length=255)
    done: bool = False


class TodoStepsIn(BaseModel):
    steps: list[TodoStepIn] = Field(max_length=50)


def _todo_out(todo: dict, todo_list: dict) -> dict:
    from app.integrations.microsoft_todo import parse_due_date, parse_graph_dt, split_body

    item = svc.todo_to_item(todo, todo_list, tz=svc.ga_tz(), parse_due_date=parse_due_date, parse_graph_dt=parse_graph_dt, split_body=split_body)
    notes, steps = split_body((todo.get("body") or {}).get("content"))
    return {
        "id": item.id,
        "list": todo_list.get("displayName"),
        "title": item.title,
        "due_date": item.due_date,
        "time": item.start.strftime("%H:%M") if item.start else None,
        "status": item.status,
        "notes": notes or None,
        "steps": [{"text": step.text, "done": step.done} for step in steps],
    }


@router.get("/todo")
async def todo_list(
    list_name: str | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_completed: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ensure_assistant_user(user)
    _ensure_todo_allowed(user)
    client = await _todo_client(db)
    lists = await _graph_call(client.lists())
    if list_name:
        lists = [await _graph_call(client.resolve_list(list_name))]
    out = []
    for todo_list in lists:
        for todo in await _graph_call(client.tasks(todo_list["id"], include_completed=include_completed)):
            row = _todo_out(todo, todo_list)
            due = date.fromisoformat(row["due_date"]) if row["due_date"] else None
            if date_from and (due is None or due < date_from):
                continue
            if date_to and (due is None or due > date_to):
                continue
            out.append(row)
    return {"count": len(out), "items": out}


@router.post("/todo")
async def todo_create(payload: TodoCreateIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from app.integrations.microsoft_todo import due_payload, graph_datetime

    ensure_assistant_user(user)
    _ensure_todo_allowed(user)
    if payload.time and payload.due_date is None:
        raise HTTPException(status_code=422, detail="A time needs a due_date")
    client = await _todo_client(db)
    # Without an explicit list, create where iPhone Reminders sync (see TodoClient.create_list).
    todo_list = await _graph_call(
        client.resolve_list(payload.list_name) if payload.list_name else client.create_list(settings.MS_TODO_CREATE_LIST)
    )
    body: dict = {"title": payload.title.strip()}
    if payload.notes:
        body["body"] = {"contentType": "text", "content": payload.notes.strip()}
    if payload.due_date:
        body["dueDateTime"] = due_payload(payload.due_date)
    if payload.time and payload.due_date:
        body["reminderDateTime"] = graph_datetime(payload.due_date, svc.parse_hhmm(payload.time), svc.ga_tz())
        body["isReminderOn"] = True
    created = await _graph_call(client.create(todo_list["id"], body))
    out = _todo_out(created, todo_list)
    _audit(db, user, _audit_id(out["id"]), "GA_ASSISTANT_TODO_CREATE", {"item_id": out["id"], "title": out["title"]})
    await db.commit()
    return out


@router.patch("/todo/{item_id:path}")
async def todo_update(item_id: str, payload: TodoUpdateIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from app.integrations.microsoft_todo import due_payload, graph_datetime, join_body, parse_due_date, split_body

    ensure_assistant_user(user)
    _ensure_todo_allowed(user)
    prefix, raw = _parse_item(item_id)
    if prefix != svc.PREFIX_TODO:
        raise HTTPException(status_code=422, detail="Not a To Do id")
    list_id, task_id = _todo_ref(raw)
    client = await _todo_client(db)
    current = await _graph_call(client.get(list_id, task_id))
    body: dict = {}
    if payload.title is not None:
        body["title"] = payload.title.strip()
    day = payload.due_date or parse_due_date(current.get("dueDateTime"), svc.ga_tz())
    if payload.due_date is not None:
        body["dueDateTime"] = due_payload(payload.due_date)
    if payload.clear_time:
        body.update(isReminderOn=False, reminderDateTime=None)
    elif payload.time is not None:
        day = day or _now().date()
        body.update(
            dueDateTime=due_payload(day),
            reminderDateTime=graph_datetime(day, svc.parse_hhmm(payload.time), svc.ga_tz()),
            isReminderOn=True,
        )
    if payload.notes is not None:
        _, steps = split_body((current.get("body") or {}).get("content"))
        body["body"] = {"contentType": "text", "content": join_body(payload.notes, steps)}
    if not body:
        raise HTTPException(status_code=422, detail="Nothing to update")
    updated = await _graph_call(client.update(list_id, task_id, body))
    _audit(db, user, _audit_id(item_id), "GA_ASSISTANT_TODO_UPDATE", {"item_id": item_id, "fields": sorted(body)})
    await db.commit()
    return _todo_out(updated, {"id": list_id, "displayName": None})


@router.post("/todo/{item_id:path}/complete")
async def todo_complete(item_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return await item_done(ItemDoneIn(item_id=item_id), db, user)


@router.put("/todo/{item_id:path}/steps")
async def todo_set_steps(item_id: str, payload: TodoStepsIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from app.integrations.microsoft_todo import Step, join_body, split_body

    ensure_assistant_user(user)
    _ensure_todo_allowed(user)
    prefix, raw = _parse_item(item_id)
    if prefix != svc.PREFIX_TODO:
        raise HTTPException(status_code=422, detail="Not a To Do id")
    list_id, task_id = _todo_ref(raw)
    client = await _todo_client(db)
    current = await _graph_call(client.get(list_id, task_id))
    notes, _ = split_body((current.get("body") or {}).get("content"))
    content = join_body(notes, [Step(step.text, step.done) for step in payload.steps])
    updated = await _graph_call(client.update(list_id, task_id, {"body": {"contentType": "text", "content": content}}))
    _audit(db, user, _audit_id(item_id), "GA_ASSISTANT_TODO_STEPS", {"item_id": item_id, "steps": len(payload.steps)})
    await db.commit()
    return _todo_out(updated, {"id": list_id, "displayName": None})


# ---------------------------------------------------------------- Discord mentions of the GA


class DiscordMarkIn(BaseModel):
    status: str = Field(pattern=r"^(new|seen|done)$")


@router.get("/discord/mentions")
async def discord_mentions(
    since: str | None = None,
    until: str | None = None,
    only_open: bool = True,
    only_ready: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Server-channel messages that mention GA (or a role of hers) or reply to her. Default: today.

    only_ready=true keeps only messages a colleague already approved with a reaction (ready_for_ga).
    """
    from app.services import ga_discord_mentions as mentions

    ensure_assistant_user(user)
    now = _now()
    start = _parse_moment(since, default=datetime.combine(now.date(), time.min, tzinfo=svc.ga_tz()))
    end = _parse_moment(until, default=now + timedelta(minutes=1))
    if end <= start:
        raise HTTPException(status_code=422, detail="until must be after since")
    rows = await mentions.list_mentions(db, since=start, until=end, statuses=mentions.OPEN_STATUSES if only_open else None)
    items = await mentions.render_with_context(db, rows, svc.ga_tz())
    if only_ready:
        items = [item for item in items if item["ready_for_ga"]]
    last = await mentions.last_message_at(db)
    return {
        "timezone": settings.GA_TIMEZONE,
        "since": start.isoformat(),
        "until": end.isoformat(),
        "only_open": only_open,
        "only_ready": only_ready,
        "approval_emojis": [item.strip() for item in settings.GA_DISCORD_APPROVAL_EMOJIS.split(",") if item.strip()],
        "count": len(items),
        "items": items,
        "bot_configured": bool(settings.GA_DISCORD_MENTIONS_BOT_TOKEN),
        "last_stored_message_at": last.astimezone(svc.ga_tz()).isoformat() if last else None,
    }


@router.post("/discord/mentions/{item_id}/status")
async def discord_mark(item_id: str, payload: DiscordMarkIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from app.services import ga_discord_mentions as mentions

    ensure_assistant_user(user)
    raw = item_id[len(svc.PREFIX_DISCORD):] if item_id.startswith(svc.PREFIX_DISCORD) else item_id
    if not raw.isdigit():
        raise HTTPException(status_code=422, detail="Discord mention ids look like dc:<message id>")
    row = await _set_discord_status(db, user, raw, payload.status)
    return (await mentions.render(db, [row], svc.ga_tz()))[0]


@router.get("/discord/mentions/feed", response_model=DiscordMentionsFeed)
async def discord_mentions_feed(
    before: str | None = Query(default=None, pattern=DISCORD_MESSAGE_ID_PATTERN),
    limit: int = Query(default=DISCORD_FEED_DEFAULT_LIMIT, ge=1, le=DISCORD_FEED_MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Direct GA mentions in the configured staff channel with their current reactions."""
    from app.services import ga_discord_mentions as mentions

    ensure_assistant_user(user)
    try:
        rows = await mentions.list_staff_channel_mentions(db, before=before, limit=limit + 1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    page = rows[:limit]
    tz = svc.ga_tz()
    items = await mentions.render_with_context(db, page, tz)
    return {
        "channel_id": settings.DISCORD_GA_REPLIES_CHANNEL_ID,
        "timezone": settings.GA_TIMEZONE,
        "bot_configured": bool(settings.DISCORD_GUILD_ID and settings.DISCORD_GA_REPLIES_CHANNEL_ID
                               and settings.GA_DISCORD_MENTIONS_BOT_TOKEN),
        "items": items,
        "next_before": page[-1].id if len(rows) > limit else None,
    }


@router.get("/discord/mentions/feed/{message_id}/attachments")
async def discord_mention_attachments(
    message_id: str = Path(pattern=DISCORD_MESSAGE_ID_PATTERN),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DiscordMentionAttachments:
    from app.services import ga_discord_mentions as mentions

    ensure_assistant_user(user)
    links = await mentions.staff_mention_attachment_links(db, message_id)
    return DiscordMentionAttachments(id=f"dc:{message_id}", attachments=links)
