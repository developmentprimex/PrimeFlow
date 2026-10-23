from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attendance_log import AttendanceLog
from app.models.audit_log import AuditLog
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.models.daily_planner_snapshot import DailyPlannerSnapshot
from app.models.project import Project
from app.models.realization import RealizationDailyCloseEvent, RealizationPeriod
from app.models.system_task_template import SystemTaskTemplate
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.task_strike_event import TaskStrikeEvent
from app.models.user import User
from app.models.enums import AttendanceType
from app.services.daily_realization_classifier import (
    DailyClassificationInput, EXCEPTION_CLASSIFICATIONS, classify_daily_task,
)
from app.services.daily_realization_metrics import calculate_daily_metrics, multi_day_share
from app.services.daily_realization_quantities import daily_task_quantity
from app.services.daily_realization_events import semantic_local_day
from app.services.daily_realization_explanation import requires_daily_explanation
from app.services.daily_realization_close_state import resolve_daily_close_state
from app.services.one_h_slots import effective_slot_date
from app.services.realization_people import (
    availability_status_on_day,
    is_realization_excluded_user,
    load_active_users_and_common_leave,
)


def local_day(value: datetime | None) -> date | None:
    if value is None:
        return None
    zone = ZoneInfo(settings.REALIZATION_TIMEZONE)
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(zone).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings.REALIZATION_TIMEZONE)
    start = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=zone).astimezone(timezone.utc)
    return start, end


def candidate_task_ids_for_person(
    person_id: uuid.UUID,
    *,
    baseline_by_user: dict[uuid.UUID, dict[uuid.UUID, dict]],
    current_assignees: dict[uuid.UUID, set[uuid.UUID]],
    tasks: dict[uuid.UUID, Any],
    events_by_task: dict[uuid.UUID, list[AuditLog]],
    day: date,
    daily_evidence_task_ids: set[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """Keep baseline tasks and tasks with evidence tied to the selected day."""
    daily_evidence_task_ids = daily_evidence_task_ids or set()
    candidate_ids = set(baseline_by_user.get(person_id, {}))
    candidate_ids.update(
        task_id for task_id, owners in current_assignees.items()
        if person_id in owners and (
            task_id in baseline_by_user.get(person_id, {})
            or local_day(getattr(tasks.get(task_id), "created_at", None)) == day
            or local_day(getattr(tasks.get(task_id), "completed_at", None)) == day
            or bool(events_by_task.get(task_id))
            or task_id in daily_evidence_task_ids
        )
    )
    candidate_ids.update(
        task_id for task_id, task_events in events_by_task.items()
        if any(
            event.action == "task.assignee_changed"
            and str(person_id) in set((event.before or {}).get("assignee_ids", [])) | set((event.after or {}).get("assignee_ids", []))
            for event in task_events
        )
    )
    return candidate_ids


def additional_task_has_day_evidence(
    *,
    task: Any | None,
    day: date,
    completion_credited: bool,
    progress: TaskDailyProgress | None,
    state: TaskDailyRlzState | None,
    events: list[AuditLog],
) -> bool:
    """Exclude backlog and future planning from a day's Extra counters."""
    if completion_credited or progress is not None or state is not None:
        return True
    if task is None:
        return bool(events)

    start_day = local_day(task.start_date)
    due_day = local_day(task.due_date)
    created_day = local_day(task.created_at)
    operational_by_day = (
        start_day <= day
        if start_day is not None
        else due_day <= day
        if due_day is not None
        else created_day == day
    )
    if created_day == day and operational_by_day:
        return True

    for event in events:
        action = str(event.action or "").lower()
        before = event.before or {}
        after = event.after or {}
        if action == "task.status_changed" and str(after.get("value") or "").upper() in {
            "IN_PROGRESS", "DONE",
        }:
            return True
        if action == "task.progress_changed":
            try:
                if float(after.get("value") or 0) > float(before.get("value") or 0):
                    return True
            except (TypeError, ValueError):
                pass
        if action in {"task.due_date_changed", "task.start_date_changed"}:
            if day in {
                semantic_local_day(before.get("value")),
                semantic_local_day(after.get("value")),
            }:
                return True
        if action in {"task.assignee_changed", "task.reopened"} and operational_by_day:
            return True
    return False


def assignees_at_timestamp(
    *,
    current_assignees: set[uuid.UUID],
    assignee_events: list[AuditLog],
    timestamp: datetime | None,
) -> set[uuid.UUID]:
    """Reconstruct ownership at a fact timestamp by reversing later changes."""
    owners = set(current_assignees)
    if timestamp is None:
        return owners
    for event in sorted(assignee_events, key=lambda row: (row.created_at, str(row.id)), reverse=True):
        if event.created_at <= timestamp:
            continue
        owners = {
            uuid.UUID(str(value))
            for value in (event.before or {}).get("assignee_ids", [])
        }
    return owners


def credited_completion_day(
    *,
    person_id: uuid.UUID,
    day: date,
    completion_at: datetime | None,
    current_assignees: set[uuid.UUID],
    assignee_events: list[AuditLog],
    baseline_owner: bool = False,
) -> date | None:
    """Credit a completion only to an owner at the completion timestamp."""
    completed_day = local_day(completion_at)
    if completed_day != day:
        return None
    owners = assignees_at_timestamp(
        current_assignees=current_assignees,
        assignee_events=assignee_events,
        timestamp=completion_at,
    )
    if person_id in owners or (not owners and baseline_owner):
        return completed_day
    return None


def timeline_from_events(*, day: date, baseline_task: dict | None, events: list[AuditLog]) -> list[dict]:
    rows: list[dict[str, Any]] = []
    if baseline_task:
        rows.append({
            "id": f"plan:{baseline_task.get('match_key')}", "type": "PLANNED_FOR_DAY",
            "timestamp": None, "actor_user_id": None,
            "old_value": None, "new_value": baseline_task.get("original_daily_plan"),
            "metadata": {"time_slot": baseline_task.get("time_slot")},
        })
    postponements = 0
    for event in sorted(events, key=lambda row: (row.created_at, str(row.id))):
        old = event.before or {}
        new = event.after or {}
        event_type = event.action.removeprefix("task.").upper()
        if event.action == "task.due_date_changed":
            old_value, new_value = old.get("value"), new.get("value")
            old_day, new_day = semantic_local_day(old_value), semantic_local_day(new_value)
            if old_day and new_day:
                if new_day > old_day:
                    postponements += 1
                    event_type = "POSTPONED_AGAIN" if postponements > 1 else "POSTPONED"
                elif new_day == day:
                    event_type = "MOVED_BACK_TO_TODAY"
                else:
                    event_type = "MOVED_EARLIER"
        elif event.action == "task.status_changed":
            if str(new.get("value")).upper() == "DONE": event_type = "COMPLETED"
            elif str(new.get("value")).upper() == "IN_PROGRESS": event_type = "STARTED"
        rows.append({
            "id": str(event.id), "type": event_type,
            "timestamp": event.created_at.isoformat(),
            "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
            "old_value": old.get("value", old.get("assignee_ids")),
            "new_value": new.get("value", new.get("assignee_ids")),
            "metadata": {"reason": new.get("reason_code") or new.get("reason") or old.get("reason"),
                         **({"comment": new["comment"]} if new.get("comment") else {})},
        })
    return rows


def manager_decision_timeline_item(adjustment: DailyPlanAdjustment, *, decided_by_name: str | None) -> dict | None:
    if not adjustment.decided_at or adjustment.status not in {"APPROVED", "REJECTED"}:
        return None
    return {
        "id": f"adjustment:{adjustment.id}",
        "type": f"POSTPONEMENT_{adjustment.status}",
        "timestamp": adjustment.decided_at.isoformat(),
        "actor_user_id": str(adjustment.decided_by) if adjustment.decided_by else None,
        "actor_name": decided_by_name,
        "old_value": None,
        "new_value": adjustment.status,
        "metadata": {"reason": adjustment.reason, "comment": adjustment.decision_comment},
    }


async def build_live_daily_realization(
    db: AsyncSession, *, department_id: uuid.UUID, day: date,
    user_id: uuid.UUID | None = None, exceptions_only: bool = False,
) -> dict[str, Any]:
    baseline = (await db.execute(select(DailyPlannerSnapshot).where(
        DailyPlannerSnapshot.department_id == department_id,
        DailyPlannerSnapshot.day_date == day,
    ))).scalar_one_or_none()
    baseline_people = (baseline.payload or {}).get("people", []) if baseline else []
    baseline_by_user: dict[uuid.UUID, dict[uuid.UUID, dict]] = defaultdict(dict)
    task_ids: set[uuid.UUID] = set()
    for person in baseline_people:
        try: owner = uuid.UUID(str(person["user_id"]))
        except (KeyError, ValueError): continue
        for item in person.get("tasks") or []:
            try: task_id = uuid.UUID(str(item.get("task_id")))
            except (TypeError, ValueError): continue
            baseline_by_user[owner][task_id] = item
            task_ids.add(task_id)

    department_users, common_leave = await load_active_users_and_common_leave(
        db, department_id=department_id, start_date=day, end_date=day,
    )
    department_user_ids = {row.id for row in department_users}
    availability_by_user = {
        person_id: status
        for person_id, coverage in common_leave.items()
        if (status := availability_status_on_day(coverage, day)) is not None
    }
    attendance_rows = list((await db.execute(select(AttendanceLog).where(
        AttendanceLog.user_id.in_(department_user_ids),
        AttendanceLog.date == day,
        AttendanceLog.type.in_({AttendanceType.PUSHIM_VJETOR, AttendanceType.MUNGESE}),
    ))).scalars().all()) if department_user_ids else []
    for attendance in attendance_rows:
        if attendance.user_id is None:
            continue
        if attendance.type == AttendanceType.PUSHIM_VJETOR:
            availability_by_user[attendance.user_id] = "PV"
        elif attendance.user_id not in availability_by_user:
            availability_by_user[attendance.user_id] = "MUNGESE"

    def common_view_attendance_for(person_id: uuid.UUID) -> list[dict]:
        coverage = common_leave.get(person_id)
        if coverage is None:
            return []
        rows: list[dict] = []
        if day in coverage.delay_days:
            rows.append({
                "date": day.isoformat(),
                "type": "VONESE",
                "source": "common_view",
            })
        if day in coverage.absence_days:
            rows.append({
                "date": day.isoformat(),
                "type": "MUNGESE",
                "source": "common_view",
            })
        return rows

    scoped_task_ids = set(task_ids)
    if department_user_ids:
        scoped_task_ids.update((await db.execute(
            select(Task.id).outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id).where(or_(
                Task.assigned_to.in_(department_user_ids),
                TaskAssignee.user_id.in_(department_user_ids),
            )).distinct()
        )).scalars().all())

    start_utc, end_utc = day_bounds(day)
    events = list((await db.execute(select(AuditLog).where(
        AuditLog.entity_type == "task",
        AuditLog.entity_id.in_(scoped_task_ids) if scoped_task_ids else False,
        AuditLog.created_at >= start_utc,
        AuditLog.created_at <= end_utc,
    ).order_by(AuditLog.created_at, AuditLog.id))).scalars().all())
    # A person can be an intermediate owner (A -> B -> C) and therefore be in
    # neither the baseline nor current assignment. Preserve that day history.
    if department_user_ids:
        department_user_keys = {str(value) for value in department_user_ids}
        assignee_history = (await db.execute(select(AuditLog).where(
            AuditLog.entity_type == "task",
            AuditLog.action == "task.assignee_changed",
            AuditLog.created_at >= start_utc,
            AuditLog.created_at <= end_utc,
        ).order_by(AuditLog.created_at, AuditLog.id))).scalars().all()
        known_event_ids = {event.id for event in events}
        for event in assignee_history:
            event_users = set((event.before or {}).get("assignee_ids", [])) | set((event.after or {}).get("assignee_ids", []))
            if event.id not in known_event_ids and event_users.intersection(department_user_keys):
                events.append(event)
        events.sort(key=lambda row: (row.created_at, str(row.id)))
    events_by_task: dict[uuid.UUID, list[AuditLog]] = defaultdict(list)
    for event in events:
        events_by_task[event.entity_id].append(event)
        task_ids.add(event.entity_id)

    # Match candidate_task_ids_for_person before loading large titles/descriptions.
    # Baseline and audit tasks are always retained, including former assignees.
    # Current ownership alone does not make the entire backlog a daily obligation.
    current_rows = (await db.execute(
        select(Task).where(or_(
            Task.id.in_(task_ids) if task_ids else False,
            and_(
                Task.id.in_(scoped_task_ids) if scoped_task_ids else False,
                or_(
                    Task.created_at.between(start_utc, end_utc),
                    Task.completed_at.between(start_utc, end_utc),
                    Task.id.in_(select(TaskDailyProgress.task_id).where(
                        TaskDailyProgress.day_date == day,
                    )),
                    Task.id.in_(select(TaskDailyRlzState.task_id).where(
                        TaskDailyRlzState.day_date == day,
                    )),
                ),
            ),
        ))
    )).scalars().all()
    tasks = {row.id: row for row in current_rows}
    task_ids.update(tasks)
    # System tasks hidden from the Weekly Planner are routine, not extra work.
    system_template_ids = {row.system_template_origin_id for row in current_rows if row.system_template_origin_id}
    hidden_system_template_ids = set((await db.execute(select(SystemTaskTemplate.id).where(
        SystemTaskTemplate.id.in_(system_template_ids),
        SystemTaskTemplate.show_in_weekly_planner.is_not(True),
    ))).scalars().all()) if system_template_ids else set()
    assignee_rows = (await db.execute(select(TaskAssignee).where(
        TaskAssignee.task_id.in_(task_ids)
    ))).scalars().all() if task_ids else []
    current_assignees: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for row in assignee_rows: current_assignees[row.task_id].add(row.user_id)
    for task in tasks.values():
        if task.assigned_to: current_assignees[task.id].add(task.assigned_to)

    progress_rows = (await db.execute(select(TaskDailyProgress).where(
        TaskDailyProgress.task_id.in_(task_ids), TaskDailyProgress.day_date == day,
    ))).scalars().all() if task_ids else []
    progress = {row.task_id: row for row in progress_rows}
    # Latest snapshot before the day, so cumulative product counts become the day's own work.
    previous_progress: dict[uuid.UUID, TaskDailyProgress] = {}
    if task_ids:
        for row in (await db.execute(select(TaskDailyProgress).where(
            TaskDailyProgress.task_id.in_(task_ids), TaskDailyProgress.day_date < day,
        ).order_by(TaskDailyProgress.task_id, TaskDailyProgress.day_date.desc()).distinct(
            TaskDailyProgress.task_id,
        ))).scalars().all():
            previous_progress[row.task_id] = row
    # The first later transition records the status at the selected day's end.
    # Use it for all daily outcomes, so later work cannot rewrite earlier progress.
    status_after_day: dict[uuid.UUID, str] = {}
    if task_ids:
        for event in (await db.execute(select(AuditLog).where(
            AuditLog.entity_type == "task",
            AuditLog.entity_id.in_(task_ids),
            AuditLog.action.in_(("task.status_changed", "task.reopened")),
            AuditLog.created_at > end_utc,
        ).order_by(AuditLog.entity_id, AuditLog.created_at.asc()).distinct(AuditLog.entity_id))).scalars().all():
            status_after_day[event.entity_id] = str((event.before or {}).get("value") or "").upper()
    strike_rows = (await db.execute(select(TaskStrikeEvent).where(
        TaskStrikeEvent.task_id.in_(task_ids),
    ))).scalars().all() if task_ids else []
    strikes_by_task = defaultdict(list)
    for strike in strike_rows:
        strikes_by_task[strike.task_id].append(strike)

    person_ids = set(baseline_by_user) | department_user_ids
    for task_id, owners in current_assignees.items():
        if task_id in tasks and local_day(tasks[task_id].created_at) == day:
            person_ids.update(owners)
        for event in events_by_task.get(task_id, []):
            if event.action == "task.assignee_changed":
                person_ids.update(uuid.UUID(value) for value in (event.after or {}).get("assignee_ids", []))
                person_ids.update(uuid.UUID(value) for value in (event.before or {}).get("assignee_ids", []))
    if user_id: person_ids &= {user_id}

    actor_ids = {event.actor_user_id for event in events if event.actor_user_id}
    all_visible_user_ids = person_ids | actor_ids
    users = {row.id: row for row in (await db.execute(select(User).where(User.id.in_(all_visible_user_ids)))).scalars().all()} if all_visible_user_ids else {}
    person_ids = {
        person_id for person_id in person_ids
        if person_id not in users or not is_realization_excluded_user(users[person_id])
    }
    project_ids = {task.project_id for task in tasks.values() if task.project_id}
    projects = {row.id: row for row in (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()} if project_ids else {}
    states = {(row.user_id, row.task_id): row for row in (await db.execute(select(TaskDailyRlzState).where(
        TaskDailyRlzState.user_id.in_(person_ids), TaskDailyRlzState.day_date == day,
    ))).scalars().all()} if person_ids else {}
    adjustments = {(row.user_id, row.audit_event_id): row for row in (await db.execute(select(DailyPlanAdjustment).where(
        DailyPlanAdjustment.user_id.in_(person_ids), DailyPlanAdjustment.day_date == day,
    ))).scalars().all()} if person_ids else {}
    decision_user_ids = {row.decided_by for row in adjustments.values() if row.decided_by}
    if decision_user_ids:
        users.update({
            row.id: row
            for row in (await db.execute(select(User).where(User.id.in_(decision_user_ids)))).scalars().all()
        })
    slot_updates = {row.task_id: row.updated_at for row in (await db.execute(select(TaskOneHReportSlot).where(
        TaskOneHReportSlot.task_id.in_(task_ids),
        TaskOneHReportSlot.report_date == effective_slot_date(day),
    ))).scalars().all()} if task_ids else {}

    people = []
    department_metric_rows: list[dict] = []
    for person_id in sorted(person_ids, key=lambda value: ((users.get(value).full_name if users.get(value) else ""), str(value))):
        availability_status = availability_by_user.get(person_id)
        if availability_status:
            user = users.get(person_id)
            people.append({
                "user_id": str(person_id),
                "user_name": user.full_name if user else next((p.get("user_name") for p in baseline_people if p.get("user_id") == str(person_id)), str(person_id)),
                "department_id": str(department_id),
                "tasks": [],
                "metrics": calculate_daily_metrics([]),
                "availability_status": availability_status,
                "attendance": common_view_attendance_for(person_id),
            })
            continue
        candidate_ids = candidate_task_ids_for_person(
            person_id, baseline_by_user=baseline_by_user,
            current_assignees=current_assignees, tasks=tasks,
            events_by_task=events_by_task, day=day,
            daily_evidence_task_ids=(
                set(progress)
                | {task_id for owner_id, task_id in states if owner_id == person_id}
            ),
        )
        rows = []
        metric_rows = []
        for task_id in sorted(candidate_ids, key=str):
            task = tasks.get(task_id)
            status_on_day = status_after_day.get(task_id) or (
                str(getattr(task.status, "value", task.status)).upper() if task else "TODO"
            )
            original = baseline_by_user.get(person_id, {}).get(task_id)
            task_events = events_by_task.get(task_id, [])
            assignee_events = [event for event in task_events if event.action == "task.assignee_changed"]
            was_assigned_in = any(str(person_id) not in (event.before or {}).get("assignee_ids", []) and str(person_id) in (event.after or {}).get("assignee_ids", []) for event in assignee_events)
            was_assigned_out = bool(original) and person_id not in current_assignees.get(task_id, set())
            due_events = [event for event in task_events if event.action == "task.due_date_changed"]
            latest_due_adjustment = next(
                (adjustments[(person_id, event.id)] for event in reversed(due_events) if (person_id, event.id) in adjustments),
                None,
            )
            adjustment_status = latest_due_adjustment.status if latest_due_adjustment else None
            decision_user = users.get(latest_due_adjustment.decided_by) if latest_due_adjustment and latest_due_adjustment.decided_by else None
            manager_decision = ({
                "status": latest_due_adjustment.status,
                "reason": latest_due_adjustment.reason,
                "comment": latest_due_adjustment.decision_comment,
                "decided_by_user_id": str(latest_due_adjustment.decided_by) if latest_due_adjustment.decided_by else None,
                "decided_by_name": decision_user.full_name if decision_user else None,
                "decided_at": latest_due_adjustment.decided_at.isoformat() if latest_due_adjustment.decided_at else None,
            } if latest_due_adjustment else None)
            approved = adjustment_status == "APPROVED"
            reopened = any(event.action == "task.reopened" for event in task_events)
            progress_delta = float(progress.get(task_id).completed_delta if progress.get(task_id) else 0)
            percentage_delta = sum(max(0, float((event.after or {}).get("value") or 0) - float((event.before or {}).get("value") or 0)) for event in task_events if event.action == "task.progress_changed")
            original_due = None
            if original and original.get("planned_due_date"):
                try: original_due = date.fromisoformat(str(original["planned_due_date"])[:10])
                except ValueError: pass
            completion_at = task.completed_at if task else None
            completed_day = local_day(completion_at)
            if progress.get(task_id) and str(progress[task_id].daily_status or "").upper() == "DONE":
                completed_day = day
                completion_at = progress[task_id].updated_at or completion_at
            for event in task_events:
                if event.action == "task.status_changed" and str((event.after or {}).get("value")).upper() == "DONE":
                    completed_day = local_day(event.created_at)
                    completion_at = event.created_at
                elif event.action == "task.reopened":
                    # An earlier completion stops counting while the task is
                    # open. A later DONE event restores its completion credit.
                    completed_day = None
                    completion_at = None
            credited_completed_day = credited_completion_day(
                person_id=person_id,
                day=day,
                completion_at=completion_at,
                current_assignees=current_assignees.get(task_id, set()),
                assignee_events=assignee_events,
                baseline_owner=bool(original),
            )
            completion_credited = credited_completed_day == day
            quantity = daily_task_quantity(
                task, day=day, baseline=original, progress=progress.get(task_id),
                strike_events=strikes_by_task.get(task_id, []),
                done_for_day=completion_credited,
                previous_progress=previous_progress.get(task_id),
            )
            current_due = local_day(task.due_date) if task else None
            created_day = local_day(task.created_at) if task else None
            had_postponement_event = any(
                event.action == "task.due_date_changed"
                and semantic_local_day((event.before or {}).get("value")) == day
                and semantic_local_day((event.after or {}).get("value"))
                and semantic_local_day((event.after or {}).get("value")) > day
                for event in due_events
            )
            postponed_today = bool(had_postponement_event and current_due and current_due > day)
            # A deadline pushed back before its own day still is a postponement
            # on the day it was decided, so the plan column has to record it.
            # The deadline column keeps the stricter rule above: an obligation
            # only counts as missed once its day actually arrives.
            forward_due_events = [
                event for event in due_events
                if semantic_local_day((event.before or {}).get("value"))
                and semantic_local_day((event.after or {}).get("value"))
                and semantic_local_day((event.after or {}).get("value"))
                > semantic_local_day((event.before or {}).get("value"))
            ]
            postponed_on_day = bool(forward_due_events and current_due and current_due > day)
            deadline_was_today = bool(original_due == day or (original is None and current_due == day)) or any(
                semantic_local_day((event.before or {}).get("value")) == day for event in due_events
            )
            deadline_is_overdue = bool(current_due and current_due < day)
            completed_today = completion_credited
            daily_share, multi_day_before_deadline = multi_day_share(
                local_day(task.start_date) if task else None, original_due or current_due, day,
            )
            requirement = requires_daily_explanation(
                status=status_on_day, selected_day=day,
                deadline=current_due, deadline_was_today=deadline_was_today,
                postponed_today=postponed_today,
            )
            classification = classify_daily_task(DailyClassificationInput(
                day=day, in_baseline=bool(original), original_due_date=original_due or current_due,
                current_due_date=current_due, created_date=created_day,
                completed_date=credited_completed_day, status=status_on_day,
                progress_delta=max(progress_delta, percentage_delta, quantity["completed"] if quantity and quantity["source"] == "title" else 0),
                postponed=postponed_on_day,
                postponement_approved=approved, reopened=reopened,
                reassigned_out=was_assigned_out, reassigned_in=was_assigned_in,
            ))
            state = states.get((person_id, task_id))
            if not original and task and task.system_template_origin_id in hidden_system_template_ids:
                continue
            if not original and not additional_task_has_day_evidence(
                task=task,
                day=day,
                completion_credited=completion_credited,
                progress=progress.get(task_id),
                state=state,
                events=task_events,
            ):
                continue
            issues = []
            if classification in {"NO_PROGRESS", "POSTPONED_UNAPPROVED"} and not (state and state.reason_code): issues.append("MISSING_REASON")
            reason_missing = requirement.reason_required and not (state and state.reason_code)
            comment_missing = requirement.comment_required and not (state and (state.comment or "").strip())
            if reason_missing and "MISSING_REASON" not in issues: issues.append("MISSING_REASON")
            if comment_missing and "MISSING_REQUIRED_COMMENT" not in issues: issues.append("MISSING_REQUIRED_COMMENT")
            action_required = bool(issues) or (
                classification == "POSTPONED_UNAPPROVED"
            ) or (
                deadline_is_overdue and not completed_today
            ) or (
                deadline_was_today and not completed_today and not postponed_today
            )
            row = {
                "task_id": str(task_id), "match_key": (original or {}).get("match_key") or f"id:{task_id}",
                "title": task.title if task else (original or {}).get("title", "Deleted task"),
                "project_id": str(task.project_id) if task and task.project_id else (original or {}).get("project_id"),
                "project_title": projects.get(task.project_id).title if task and task.project_id in projects else (original or {}).get("project_title"),
                "source_type": (original or {}).get("source_type") or ("system" if task and task.system_template_origin_id else "project" if task and task.project_id else "fast"),
                "original_daily_plan": (original or {}).get("original_daily_plan"),
                "baseline_due_date": original_due.isoformat() if original_due else None,
                "current_due_date": current_due.isoformat() if current_due else None,
                "current_status": status_on_day if task else "DELETED",
                "wfe": bool(task) and not completion_credited and status_on_day == "WAITING_CLIENT",
                "classification": classification, "in_original_plan": bool(original),
                "created_date": created_day.isoformat() if created_day else None,
                "completion_credited": completion_credited,
                "progress_today": percentage_delta, "completed_delta": progress_delta,
                "quantity": quantity,
                "reason_code": state.reason_code if state else None, "comment": state.comment if state else None,
                "is_bllok": bool(task and task.is_bllok),
                "one_h_report_slot": task.one_h_report_slot if task else None,
                "last_change": max(
                    [event.created_at for event in task_events]
                    + [strike.occurred_at for strike in strikes_by_task.get(task_id, []) if strike.occurred_at <= end_utc]
                    + ([task.updated_at] if task and task.updated_at else [])
                    + ([progress.get(task_id).updated_at] if progress.get(task_id) and progress.get(task_id).updated_at else [])
                    + ([state.updated_at] if state and state.updated_at else [])
                    + ([latest_due_adjustment.decided_at or latest_due_adjustment.created_at] if latest_due_adjustment else [])
                    + ([slot_updates.get(task_id)] if slot_updates.get(task_id) else []),
                    default=None,
                ).isoformat() if (task or task_events or progress.get(task_id) or state or latest_due_adjustment or slot_updates.get(task_id)) else None,
                "postponement_count": len(forward_due_events),
                "adjustment_status": adjustment_status,
                "manager_decision": manager_decision,
                "requires_explanation": requirement.requires_explanation,
                "reason_required": requirement.reason_required,
                "comment_required": requirement.comment_required,
                "reason_missing": reason_missing,
                "comment_missing": comment_missing,
                "deadline_was_today": deadline_was_today,
                "deadline_is_overdue": deadline_is_overdue,
                "daily_share": daily_share,
                "multi_day_before_deadline": multi_day_before_deadline,
                "postponed_today": postponed_today,
                "had_postponement_event": had_postponement_event,
                "deadline_completed": bool(deadline_was_today and completed_today),
                "deadline_critical": bool((original or {}).get("is_deadline_important") or (task and task.is_deadline_important)),
                "action_required": action_required,
                "issues": issues,
                "timeline": timeline_from_events(day=day, baseline_task=original, events=task_events),
            }
            for timeline_item in row["timeline"]:
                actor_raw = timeline_item.get("actor_user_id")
                if actor_raw:
                    actor = users.get(uuid.UUID(actor_raw))
                    timeline_item["actor_name"] = actor.full_name if actor else None
            for due_event in due_events:
                adjustment = adjustments.get((person_id, due_event.id))
                if not adjustment:
                    continue
                adjustment_user = users.get(adjustment.decided_by) if adjustment.decided_by else None
                decision_item = manager_decision_timeline_item(
                    adjustment, decided_by_name=adjustment_user.full_name if adjustment_user else None
                )
                if decision_item:
                    row["timeline"].append(decision_item)
            row["timeline"].sort(key=lambda item: (item.get("timestamp") is not None, item.get("timestamp") or "", item["id"]))
            metric_rows.append(row)
            if not exceptions_only or classification in EXCEPTION_CLASSIFICATIONS or issues:
                rows.append(row)
        if not metric_rows:
            continue
        metrics = calculate_daily_metrics(metric_rows)
        department_metric_rows.extend(metric_rows)
        user = users.get(person_id)
        people.append({
            "user_id": str(person_id), "user_name": user.full_name if user else next((p.get("user_name") for p in baseline_people if p.get("user_id") == str(person_id)), str(person_id)),
            "department_id": str(department_id), "tasks": rows, "metrics": metrics,
            "attendance": common_view_attendance_for(person_id),
        })

    department_metrics = calculate_daily_metrics(department_metric_rows)
    latest_close = (await db.execute(select(RealizationDailyCloseEvent, RealizationPeriod).join(
        RealizationPeriod, RealizationPeriod.id == RealizationDailyCloseEvent.period_id
    ).where(RealizationPeriod.department_id == department_id, RealizationPeriod.start_date == day)
      .order_by(RealizationDailyCloseEvent.created_at.desc(), RealizationDailyCloseEvent.id.desc()))).all()
    close_by_user = {}
    for close, _ in latest_close:
        close_by_user.setdefault(str(close.user_id), close)
    close_actor_ids = {close.actor_user_id for close in close_by_user.values() if close.actor_user_id}
    close_actor_names = {
        row.id: row.full_name
        for row in (await db.execute(select(User).where(User.id.in_(close_actor_ids)))).scalars().all()
    } if close_actor_ids else {}
    from app.services.daily_rlz_compliance import is_editable_day
    for person in people:
        if person.get("availability_status"):
            person["close_state"] = "NOT_SAVED"
            person["close_state_details"] = {"status": "NOT_SAVED"}
            continue
        close = close_by_user.get(person["user_id"])
        latest_change = max((datetime.fromisoformat(row["last_change"]) for row in person["tasks"] if row.get("last_change")), default=None)
        person["close_state"], _, _ = resolve_daily_close_state(
            latest_action=close.action if close else None,
            close_created_at=close.created_at if close else None,
            latest_relevant_change=latest_change,
            editable=is_editable_day(day),
        )
        stale_adjustment = next((
            row for row in person["tasks"]
            if close and (row.get("manager_decision") or {}).get("decided_at")
            and datetime.fromisoformat(row["manager_decision"]["decided_at"]) > close.created_at
        ), None)
        person["close_state_details"] = {
            "status": person["close_state"],
            "closed_at": close.created_at.isoformat() if close and close.action in {"CLOSE", "CORRECT"} else None,
            "closed_by_user_id": str(close.actor_user_id) if close and close.actor_user_id else None,
            "closed_by_name": close_actor_names.get(close.actor_user_id) if close else None,
            "action": close.action if close else None,
            "stale_cause": "MANAGER_POSTPONEMENT_DECISION" if person["close_state"] == "STALE" and stale_adjustment else None,
        }
        if person["close_state"] != "SAVED":
            person["metrics"]["daily_control_state"] = "ACTION_REQUIRED"
    if any(person["metrics"].get("daily_control_state") == "ACTION_REQUIRED" for person in people):
        department_metrics["daily_control_state"] = "ACTION_REQUIRED"
    return {
        "day": day.isoformat(), "department_id": str(department_id),
        "timezone": settings.REALIZATION_TIMEZONE,
        "baseline_id": str(baseline.id) if baseline else None,
        "baseline_captured_at": baseline.captured_at.isoformat() if baseline else None,
        "baseline_available": baseline is not None, "historical_estimate": False,
        "live": day == datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "metrics": department_metrics, "people": people,
    }
