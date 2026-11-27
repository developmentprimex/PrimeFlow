"""Per-assignee reporting choices and their explanations."""

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from app.models.audit_log import AuditLog
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.meetings_report import _m3_task_type_label
from app.services.task_date_window import common_view_task_date_window_filter
from app.services.task_marker import one_h_marker_label

ENTITY = "task_reporting_choice"
TASK_TYPE_FIELDS = ("is_bllok", "is_r1", "is_1h_report", "is_personal")


def proposed_task_type(task, edits):
    values = {field: getattr(task, field, False) for field in TASK_TYPE_FIELDS}
    values.update({field: edits[field] for field in TASK_TYPE_FIELDS if edits.get(field) is not None})
    if edits.get("one_h_report_slot") and not getattr(task, "is_r1", False) and edits.get("is_r1") is not True:
        values["is_1h_report"] = True
    return _m3_task_type_label(SimpleNamespace(
        **values, project_id=getattr(task, "project_id", None),
        system_template_origin_id=getattr(task, "system_template_origin_id", None),
        system_task_slot_id=getattr(task, "system_task_slot_id", None),
    ), prefer_reporting_type=True)


def group_key(task):
    for field in ("ga_note_origin_id", "plan_note_origin_id", "fast_task_group_id"):
        if value := getattr(task, field, None):
            return (field, value, task.project_id) if field != "fast_task_group_id" else (field, value)
    if task.system_template_origin_id and task.origin_run_at:
        return ("system", task.system_template_origin_id, task.origin_run_at)
    if task.meeting_origin_id and task.meeting_occurrence_date:
        return ("meeting", task.meeting_origin_id, task.meeting_occurrence_date, task.meeting_system_task_kind)
    if task.project_id and task.created_at:
        # Legacy project copies are inserted in the same transaction. Do not
        # associate separate tasks just because they happen to have the same title.
        return ("project", task.project_id, task.created_at, task.created_by, task.title)
    return ("task", task.id)


def group_filter(key):
    kind, *values = key
    columns = {
        "system": (Task.system_template_origin_id, Task.origin_run_at),
        "meeting": (Task.meeting_origin_id, Task.meeting_occurrence_date, Task.meeting_system_task_kind),
        "project": (Task.project_id, Task.created_at, Task.created_by, Task.title),
        "task": (Task.id,),
        "ga_note_origin_id": (Task.ga_note_origin_id, Task.project_id),
        "plan_note_origin_id": (Task.plan_note_origin_id, Task.project_id),
        "fast_task_group_id": (Task.fast_task_group_id,),
    }[kind]
    return and_(*(column == value for column, value in zip(columns, values)))


async def lock_task_group(db, task_id):
    task = await db.scalar(select(Task).where(Task.id == task_id))
    if task is None:
        raise HTTPException(404, "Task not found")
    # The same row lock order serializes concurrent edits on different copies.
    group = (await db.scalars(select(Task).where(or_(Task.id == task_id, and_(
        Task.is_active.is_(True), group_filter(group_key(task)),
    ))).order_by(Task.id).with_for_update().execution_options(populate_existing=True))).all()
    return next(item for item in group if item.id == task_id), group


async def choice_members(db, tasks):
    owners = defaultdict(set)
    ids = [task.id for task in tasks]
    if not ids:
        return owners, {}
    for task in tasks:
        if task.assigned_to:
            owners[task.id].add(task.assigned_to)
    for task_id, user_id in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id)
                                              .where(TaskAssignee.task_id.in_(ids)))).all():
        owners[task_id].add(user_id)
    user_ids = {user_id for members in owners.values() for user_id in members}
    people = (await db.execute(select(User.id, User.full_name, User.username).where(
        User.id.in_(user_ids), User.work_staff_filter(), User.is_active.is_(True),
    ))).all()
    return owners, {user_id: name or username or "—" for user_id, name, username in people}


async def shared_task_assignee_ids(db, tasks):
    task_groups = {task.id: group_key(task) for task in tasks}
    groups = list(dict.fromkeys(key for key in task_groups.values() if key[0] != "task"))
    if not groups:
        return {}

    siblings = []
    for offset in range(0, len(groups), 100):
        batch = groups[offset:offset + 100]
        siblings.extend((await db.scalars(select(Task).where(
            Task.is_active.is_(True), Task.work_staff_filter(),
            or_(*(group_filter(key) for key in batch)),
        ))).all())

    owners, people = await choice_members(db, siblings)
    grouped_owners = defaultdict(set)
    for sibling in siblings:
        grouped_owners[group_key(sibling)].update(user_id for user_id in owners.get(sibling.id, ()) if user_id in people)
    return {task_id: sorted(grouped_owners[key]) for task_id, key in task_groups.items()
            if len(grouped_owners[key]) > 1}


async def personal_choices(db, task_ids, day: date, *, user_id=None, marker_day: date | None = None, slot_days=()):
    if not task_ids:
        return {}
    query = select(AuditLog).where(
        AuditLog.entity_type == ENTITY, AuditLog.entity_id.in_(task_ids),
        AuditLog.after["personal"].as_boolean().is_(True),
        or_(
            and_(AuditLog.action == "slot", AuditLog.after["date"].as_string().in_(
                [item.isoformat() for item in slot_days] if slot_days else [day.isoformat()],
            )),
            and_(AuditLog.action == "marker", AuditLog.after["date"].as_string() <= (marker_day or day).isoformat()),
        ),
    )
    if user_id is not None:
        query = query.where(AuditLog.after["owner_id"].as_string() == str(user_id))
    rows = (await db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()))).all()
    result = {}
    for row in rows:
        key = (row.entity_id, row.after["owner_id"], row.action)
        if slot_days and row.action == "slot":
            key += (row.after["date"],)
        result.setdefault(key, row.after)
    return result


def shared_assignees(task, assignees):
    return len({person.id for person in assignees} | ({task.assigned_to} if task.assigned_to else set())) > 1


def apply_personal_choices(dto, values, user_id):
    if (slot := values.get((dto.id, str(user_id), "slot"))) is not None:
        dto.one_h_report_slot = slot["value"]
    if (marker := values.get((dto.id, str(user_id), "marker"))) is not None:
        dto.one_h_marker = marker["value"]
        dto.one_h_marker_by_ga = marker.get("marker_by_ga", False)
        dto.one_h_marker_comment = marker.get("marker_comment")
    return dto


def same_choice(field, first, second):
    if field == "marker":
        return set((first or "").split(",")) == set((second or "").split(","))
    return first == second


def choice_label(field, value):
    if field == "marker":
        return one_h_marker_label(value) or "Pa simbol"
    if field == "task_type":
        return value
    return value or "Pa slot"


def _owner_values(tasks, owners, names, field, slots, personal, target=None):
    values = {}
    for task in tasks:
        if not task.is_active and task is not target:
            continue
        for user_id in owners.get(task.id, set()):
            # If redundant records exist, prefer the person's primary copy.
            if user_id not in names or (user_id in values and task.assigned_to != user_id):
                continue
            if field == "task_type":
                values[user_id] = _m3_task_type_label(task, prefer_reporting_type=True)
                continue
            base = slots.get(task.id, task.one_h_report_slot) if field == "slot" else task.one_h_marker
            state = personal.get((task.id, str(user_id), field))
            values[user_id] = state["value"] if state is not None else base
    return values


async def slot_values(db, tasks, day):
    return dict((await db.execute(select(TaskOneHReportSlot.task_id, TaskOneHReportSlot.one_h_report_slot)
                                  .where(TaskOneHReportSlot.report_date == day,
                                         TaskOneHReportSlot.task_id.in_([task.id for task in tasks])))).all())


async def record_choice(
    db, task, group, user, *, field, value, day, confirmation=None, marker_comment=None, marker_by_ga=False,
):
    owners, names = await choice_members(db, group)
    members = owners[task.id]
    active_members = members.intersection(names)
    personal = len(members) > 1 and user.id in active_members
    owner = user.id if personal else next(iter(active_members)) if len(active_members) == 1 else None
    if owner not in names or len(names) < 2 or not task.is_active:
        return False
    slots = await slot_values(db, group, day) if field == "slot" else {}
    overrides = await personal_choices(db, [item.id for item in group if len(owners[item.id]) > 1], day)
    values = _owner_values(group, owners, names, field, slots, overrides, task)
    previous = values.get(owner)
    unchanged = same_choice(field, previous, value)
    if unchanged:
        if not personal or field == "slot":
            return personal
        current = overrides.get((task.id, str(owner), field), {"marker_comment": task.one_h_marker_comment})
        if current.get("marker_comment") == marker_comment:
            return personal
    _save_choice(db, task, user, field, day, owner, value, previous, values, names, confirmation,
                 personal=personal, marker_comment=marker_comment, marker_by_ga=marker_by_ga)
    if personal:
        task.updated_at = datetime.now(timezone.utc)
    return personal


def _save_choice(db, task, user, field, day, owner, value, previous, values, names, confirmation,
                 *, personal=False, marker_comment=None, marker_by_ga=False, confirmation_field=None):
    peers = [
        {"owner_id": str(peer), "person": names[peer], "value": other, "label": choice_label(field, other)}
        for peer, other in sorted(values.items(), key=lambda item: str(item[0]))
        if not same_choice(field, previous, value) and peer != owner
        and not same_choice(field, other, value) and (field != "slot" or other is not None)
    ]
    details = {
        "field": field, "date": day.isoformat(), "task_title": task.title, "owner_id": str(owner),
        "person": names[owner], "value": value, "label": choice_label(field, value), "peers": peers,
    }
    key = sha256(json.dumps([str(task.id), str(user.id), details], sort_keys=True).encode()).hexdigest()
    reason = str((confirmation or {}).get("reason") or "").strip()
    if peers and ((confirmation or {}).get("key") != key or not reason or len(reason) > 2000):
        raise HTTPException(409, {"code": "TASK_REPORTING_CHOICE_REASON_REQUIRED", "key": key,
                                  "confirmation_field": confirmation_field or field, **details})
    if personal or peers or field == "task_type":
        add_audit_log(db=db, actor_user_id=user.id, entity_type=ENTITY, entity_id=task.id, action=field,
                      before={"value": previous}, after={
                          **details, "reason": reason if peers else "", "personal": personal, "task_id": str(task.id),
                          "marker_comment": marker_comment, "marker_by_ga": marker_by_ga,
                          "actor": getattr(user, "full_name", None) or getattr(user, "username", None) or names[owner],
                      })


async def check_task_type_change(db, task, group, user, edits, day, confirmation):
    previous = proposed_task_type(task, {})
    value = proposed_task_type(task, edits)
    if previous == value or not task.is_active or len(group) < 2:
        return
    owners, names = await choice_members(db, group)
    members = owners[task.id].intersection(names)
    if len(members) != 1:
        return
    owner = next(iter(members))
    values = _owner_values(group, owners, names, "task_type", {}, {})
    _save_choice(db, task, user, "task_type", day, owner, value, previous, values, names, confirmation)


async def check_note_reporting_choices(db, tasks, payload, user):
    from zoneinfo import ZoneInfo

    from app.config import settings
    from app.services.one_h_slots import current_effective_slot_date
    from app.services.task_marker import current_effective_marker_date

    states = {state.assignee_id: state for state in payload.assignee_states or []}
    active = [task for task in tasks if task.is_active and task.assigned_to is not None
              and (payload.assignee_ids is None or task.assigned_to in payload.assignee_ids)]
    if not states or len(active) < 2:
        return
    _, names = await choice_members(db, active)
    days = {"slot": current_effective_slot_date(), "marker": current_effective_marker_date(),
            "task_type": datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()}
    slots = await slot_values(db, active, days["slot"]) if any(
        "one_h_report_slot" in state.model_fields_set for state in states.values()
    ) else {}
    groups = defaultdict(list)
    for task in active:
        if task.assigned_to in names:
            groups[group_key(task)].append(task)
    for group in groups.values():
        if len(group) < 2:
            continue
        for field in ("slot", "marker", "task_type"):
            previous = {}
            proposed = {}
            for task in group:
                owner = task.assigned_to
                state = states.get(owner)
                edits = state.model_dump(exclude_unset=True) if state else {}
                if field == "task_type":
                    previous[owner] = proposed_task_type(task, {})
                    proposed[owner] = proposed_task_type(task, {
                        key: getattr(state, key) for key in TASK_TYPE_FIELDS
                    } if state is not None else {})
                elif field == "slot":
                    previous[owner] = slots.get(task.id, task.one_h_report_slot)
                    proposed[owner] = edits.get("one_h_report_slot", previous[owner])
                else:
                    previous[owner] = task.one_h_marker
                    proposed[owner] = edits.get("one_h_marker", previous[owner])
            for task in group:
                owner = task.assigned_to
                if same_choice(field, previous[owner], proposed[owner]):
                    continue
                key = f"{field}:{owner}"
                _save_choice(db, task, user, field, days[field], owner, proposed[owner], previous[owner],
                             proposed, names, payload.reporting_choice_confirmations.get(key),
                             confirmation_field=key)


async def replace_group_marker_overrides(db, tasks, user, value, day, *, marker_by_ga):
    owners, _ = await choice_members(db, tasks)
    personal = await personal_choices(db, [task.id for task in tasks if len(owners[task.id]) > 1], day)
    for task in tasks:
        for owner in owners[task.id]:
            state = personal.get((task.id, str(owner), "marker"))
            if state is None:
                continue
            add_audit_log(db=db, actor_user_id=user.id, entity_type=ENTITY, entity_id=task.id, action="marker",
                          before={"value": state["value"]}, after={
                              **state, "value": value, "date": day.isoformat(), "marker_by_ga": marker_by_ga,
                              "label": choice_label("marker", value), "peers": [], "reason": "",
                          })


async def reporting_differences(db, day: date, now: datetime, *, marker_day: date, slot_day: date):
    is_today = day == now.date()
    start = datetime.combine(day, time.min, now.tzinfo)
    stop = datetime.combine(day + timedelta(days=1), time.min, now.tzinfo)
    entries = (await db.scalars(select(AuditLog).where(
        AuditLog.entity_type == ENTITY,
        or_(AuditLog.after["date"].as_string() == day.isoformat(),
            and_(AuditLog.created_at >= start, AuditLog.created_at < stop),
            and_(AuditLog.action == "task_type", AuditLog.after["date"].as_string() <= day.isoformat())),
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()))).all()
    rows = [
        {**entry.after, "id": str(entry.id), "task_id": str(entry.entity_id), "changed_at": entry.created_at.isoformat(),
         "previous": choice_label(entry.action, (entry.before or {}).get("value"))}
        for entry in entries if entry.after.get("peers") and entry.action != "task_type"
        and (not is_today or entry.action != "slot")
    ]
    # Compare current task types for the tasks scheduled on the selected day.
    # Task types do not have the per-day history available for slots and symbols.
    tasks = (await db.scalars(select(Task).where(Task.is_active.is_(True), Task.work_staff_filter(),
        common_view_task_date_window_filter(day, day)).order_by(Task.id))).all()
    groups = defaultdict(list)
    for task in tasks:
        groups[group_key(task)].append(task)
    owners, names = await choice_members(db, tasks)
    groups = [items for items in groups.values()
              if len({owner for task in items for owner in owners[task.id] if owner in names}) > 1]
    candidates = [task for items in groups for task in items]
    if not candidates:
        return rows
    slots = {}
    personal = {}
    fields = ("task_type",)
    if is_today:
        fields = ("slot", "marker", "task_type")
        slots = await slot_values(db, candidates, slot_day)
        personal = await personal_choices(db, [task.id for task in candidates if len(owners[task.id]) > 1],
                                          slot_day, marker_day=marker_day)
    dates = {"slot": slot_day, "marker": marker_day, "task_type": day}
    latest_slots = {}
    latest_types = {}
    for entry in entries:
        if entry.action == "slot" and entry.after["date"] == slot_day.isoformat():
            latest_slots.setdefault((entry.entity_id, entry.after["owner_id"]), entry)
        elif entry.action == "task_type" and entry.after["date"] <= day.isoformat():
            latest_types.setdefault((entry.entity_id, entry.after["owner_id"]), entry)
    seen = {(row.get("task_id"), row["owner_id"], row["field"], row["value"]) for row in rows}
    for group in groups:
        for field in fields:
            values = _owner_values(group, owners, names, field, slots, personal)
            for owner, value in values.items():
                if any((str(task.id), str(owner), field, value) in seen for task in group):
                    continue
                peers = [{"person": names[peer], "label": choice_label(field, other)}
                         for peer, other in values.items() if peer != owner and not same_choice(field, value, other)]
                if peers:
                    task = min((item for item in group if owner in owners[item.id]),
                               key=lambda item: (item.assigned_to != owner, item.id))
                    reason = ""
                    if field in {"slot", "task_type"}:
                        latest_by_owner = latest_slots if field == "slot" else latest_types
                        changes = (latest_by_owner.get((item.id, str(owner))) for item in group)
                        latest = max((change for change in changes if change is not None),
                                     key=lambda change: (change.created_at, change.id), default=None)
                        if latest is not None and same_choice(field, latest.after["value"], value):
                            reason = latest.after.get("reason", "")
                    rows.append({"id": f"{task.id}:{owner}:{field}", "field": field, "task_title": task.title,
                                 "task_id": str(task.id), "owner_id": str(owner),
                                 "person": names[owner], "label": choice_label(field, value), "peers": peers,
                                 "reason": reason, "date": dates[field].isoformat(),
                                 "previous": None, "changed_at": None})
    return rows
