from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attendance_log import AttendanceLog
from app.models.audit_log import AuditLog
from app.models.enums import AttendanceType
from app.models.realization import RealizationObservation, RealizationPeriod
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.weekly_planner_snapshot import WeeklyPlannerSnapshot
from app.services.realization_manager_review import M3_MANAGER_REVIEW_SOURCE
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.realization_people import (
    CommonLeaveCoverage,
    full_period_availability_statuses,
    load_active_users_and_common_leave,
)
from app.services.system_task_schedule import _is_working_day


def qualifies_as_verified_extra(
    *, marker: str, category: str, evidence_json: dict, related_task: dict | None = None
) -> bool:
    """Pure deterministic rule for evidence that increments verified extras."""
    if marker not in {"POSITIVE", "DIAMOND"}:
        return False
    if category in {"QUALITY", "TIME_SAVED", "HELPED_COLLEAGUE", "PROPOSAL"}:
        return True
    if category != "EXTRA_TASK":
        return False
    kind = str(evidence_json.get("kind") or "").upper()
    if kind == "REQUESTED_EXTRA_TASK":
        return True
    return bool(
        kind == "COMPLETED_EXTRA_TASK"
        and related_task is not None
        and (
            related_task.get("classification") == "additional_completed"
            or (
                evidence_json.get("high_impact") is True
                and related_task.get("positive_progress_delta", 0) > 0
            )
        )
        and evidence_json.get("replaces_unfinished_planned_task") is False
        and evidence_json.get("duplicate") is False
    )


def verified_positive_counter_updates(
    *,
    marker: str,
    category: str,
    impact_minutes: int | None,
    evidence_json: dict,
    related_task: dict | None = None,
) -> dict[str, int]:
    updates: dict[str, int] = {}
    if category == "PROPOSAL":
        updates["proposal_count"] = 1
    if category == "HELPED_COLLEAGUE":
        updates["helped_colleague_count"] = 1
    if category == "TIME_SAVED":
        updates["time_saved_minutes"] = max(0, int(impact_minutes or 0))
    if qualifies_as_verified_extra(
        marker=marker,
        category=category,
        evidence_json=evidence_json,
        related_task=related_task,
    ):
        updates["verified_extra_count"] = 1
    return updates


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _status(value: Any) -> str:
    normalized = str(value or "TODO").upper().replace(" ", "_")
    return {"TO_DO": "TODO", "INPROGRESS": "IN_PROGRESS"}.get(normalized, normalized)


def _snapshot_tasks(snapshot: WeeklyPlannerSnapshot) -> dict[str, dict[str, Any]]:
    """Read the canonical match keys persisted by the existing planner."""
    rows = (snapshot.payload or {}).get("task_items") or []
    tasks: dict[str, dict[str, Any]] = {}
    for raw in rows:
        task_id = _uuid(raw.get("task_id"))
        fallback = raw.get("fallback_key") or ""
        match_key = raw.get("match_key") or (
            f"id:{task_id}" if task_id else f"fallback:{fallback}"
        )
        assignees = []
        for assignee in raw.get("assignees") or []:
            assignees.append(
                {
                    "assignee_id": _uuid(assignee.get("assignee_id")),
                    "assignee_name": assignee.get("assignee_name") or "Unassigned",
                }
            )
        occurrences = []
        for occurrence in raw.get("occurrences") or []:
            occurrences.append(
                {
                    "day": _date(occurrence.get("day")),
                    "time_slot": occurrence.get("time_slot"),
                    "assignee_id": _uuid(occurrence.get("assignee_id")),
                }
            )
        current_status = _status(raw.get("daily_status") or raw.get("status"))
        tasks[match_key] = {
            "match_key": match_key,
            "task_id": task_id,
            "title": raw.get("title") or "(Untitled task)",
            "project_id": _uuid(raw.get("project_id")),
            "project_title": raw.get("project_title"),
            "source_type": raw.get("source_type") or "project",
            "status": current_status,
            "completed_at": _datetime(raw.get("completed_at")),
            "is_completed": bool(raw.get("is_completed")) or current_status == "DONE",
            "finish_period": raw.get("finish_period"),
            "planned_due_date": _datetime(raw.get("due_date")),
            "assignees": assignees or [{"assignee_id": None, "assignee_name": "Unassigned"}],
            "occurrences": occurrences,
        }
    return tasks


def _snapshot_users(snapshot: WeeklyPlannerSnapshot) -> dict[uuid.UUID, str]:
    """Return the historical employee set captured inside a planner snapshot."""
    users: dict[uuid.UUID, str] = {}
    department = (snapshot.payload or {}).get("department") or {}
    for day in department.get("days") or []:
        for raw in day.get("users") or []:
            user_id = _uuid(raw.get("user_id"))
            if user_id is not None:
                users[user_id] = raw.get("user_name") or "Employee"
    for task in _snapshot_tasks(snapshot).values():
        for assignee in task["assignees"]:
            user_id = assignee.get("assignee_id")
            if user_id is not None:
                users[user_id] = assignee.get("assignee_name") or users.get(user_id, "Employee")
    return users


def _local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    zone = ZoneInfo(settings.APP_TIMEZONE)
    return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)


def _iso(value: Any) -> Any:
    if isinstance(value, (date, datetime, uuid.UUID)):
        return value.isoformat() if not isinstance(value, uuid.UUID) else str(value)
    if isinstance(value, dict):
        return {key: _iso(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_iso(item) for item in value]
    return value


def _planned_deadline(
    task: dict[str, Any],
    source: Task | None,
    period: RealizationPeriod,
    *,
    am_cutoff: time,
    pm_cutoff: time,
) -> datetime:
    zone = ZoneInfo(settings.APP_TIMEZONE)
    if task.get("planned_due_date"):
        return _local(task["planned_due_date"])  # type: ignore[return-value]
    if source and source.original_due_date:
        return _local(source.original_due_date)  # type: ignore[return-value]
    days = [item["day"] for item in task["occurrences"] if item.get("day")]
    if not days:
        return datetime.combine(period.end_date, pm_cutoff, tzinfo=zone)
    planned_day = max(days)
    last_day_slots = {
        str(item.get("time_slot") or "").upper()
        for item in task["occurrences"]
        if item.get("day") == planned_day
    }
    finish = str(task.get("finish_period") or "").upper()
    if finish not in {"AM", "PM"}:
        finish = "AM" if last_day_slots == {"AM"} else "PM"
    cutoff = am_cutoff if finish == "AM" else pm_cutoff
    return datetime.combine(planned_day, cutoff, tzinfo=zone)


def _postponement(
    source: Task | None,
    logs: list[AuditLog],
) -> tuple[str | None, list[str]]:
    if source is None or source.original_due_date is None or source.due_date is None:
        return None, []
    if source.due_date <= source.original_due_date:
        return None, []
    evidence_ids: list[str] = []
    for log in logs:
        after = log.after or {}
        action = (log.action or "").lower()
        if after.get("postponement_approved") is True or action in {
            "postponement_approved",
            "due_date_change_approved",
        }:
            evidence_ids.append(str(log.id))
            return "approved_postponement", evidence_ids
        if after.get("postponement_rejected") is True or action == "postponement_rejected":
            evidence_ids.append(str(log.id))
            return "rejected_postponement", evidence_ids
    if source.confirmation_assignee_id or source.status == "WAITING_CONFIRMATION":
        return "postponement_needs_review", evidence_ids
    return "unapproved_postponement", evidence_ids


def _approved_postponement_deadline(
    source: Task | None,
    logs: list[AuditLog],
    baseline: datetime,
) -> datetime:
    for log in reversed(logs):
        after = log.after or {}
        action = (log.action or "").lower()
        if after.get("postponement_approved") is True or action in {
            "postponement_approved",
            "due_date_change_approved",
        }:
            approved_due = _datetime(after.get("effective_due_date") or after.get("due_date"))
            if approved_due is not None:
                return _local(approved_due)  # type: ignore[return-value]
    if source is not None and source.due_date is not None:
        return _local(source.due_date)  # type: ignore[return-value]
    return baseline


def _verification_map(observations: list[RealizationObservation]) -> set[uuid.UUID]:
    verified: set[uuid.UUID] = set()
    for observation in observations:
        evidence = observation.evidence_json or {}
        if (
            observation.voided_at is None
            and observation.source_type == "realization_observation_verification"
            and evidence.get("verified") is True
        ):
            original_id = _uuid(evidence.get("verification_of") or observation.source_id)
            if original_id:
                verified.add(original_id)
    return verified


def _classify_planned_task(
    *,
    current: dict[str, Any] | None,
    positive_delta: int,
    postponement: str | None,
    effective_deadline: datetime,
    period_end: date,
    cancellation: str | None = None,
) -> str:
    if current is None:
        return cancellation or "needs_review"
    if current["is_completed"]:
        completed_at = _local(current.get("completed_at"))
        if completed_at is None:
            return "needs_review"
        return (
            "completed_on_time"
            if completed_at <= effective_deadline
            else "completed_late"
        )
    if postponement == "approved_postponement":
        return "in_progress" if current["status"] == "IN_PROGRESS" else "pending_confirmation"
    if current["status"] == "IN_PROGRESS":
        return "in_progress"
    if current["status"] == "WAITING_CONFIRMATION":
        return "pending_confirmation"
    if positive_delta <= 0:
        return "no_progress"
    return "late_open" if effective_deadline.date() <= period_end else "in_progress"


async def collect_weekly_evidence(
    db: AsyncSession,
    *,
    period: RealizationPeriod,
    planned_snapshot: WeeklyPlannerSnapshot,
    final_snapshot: WeeklyPlannerSnapshot,
    am_cutoff: time,
    pm_cutoff: time,
) -> dict[str, Any]:
    planned = _snapshot_tasks(planned_snapshot)
    final = _snapshot_tasks(final_snapshot)
    task_ids = {
        task["task_id"] for task in [*planned.values(), *final.values()] if task["task_id"]
    }
    completed_department_tasks = (
        await db.execute(
            select(Task).where(
                Task.department_id == period.department_id,
                Task.completed_at.is_not(None),
                Task.completed_at <= final_snapshot.created_at,
            )
        )
    ).scalars().all()
    completed_department_tasks = [
        task
        for task in completed_department_tasks
        if period.start_date
        <= (_local(task.completed_at) or task.completed_at).date()
        <= period.end_date
    ]
    completed_outside_snapshot_ids = {
        task.id for task in completed_department_tasks if task.id not in task_ids
    }
    task_ids.update(completed_outside_snapshot_ids)
    tasks = (
        (await db.execute(select(Task).where(Task.id.in_(task_ids)))).scalars().all()
        if task_ids
        else []
    )
    task_map = {task.id: task for task in tasks}
    current_owner_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    if task_ids:
        for assignment in (
            await db.execute(
                select(TaskAssignee).where(
                    TaskAssignee.task_id.in_(task_ids)
                )
            )
        ).scalars().all():
            current_owner_ids[assignment.task_id].add(assignment.user_id)
    for task in tasks:
        if task.assigned_to is not None and not current_owner_ids.get(task.id):
            current_owner_ids[task.id].add(task.assigned_to)
    progress_rows = (
        (
            await db.execute(
                select(TaskDailyProgress).where(
                    TaskDailyProgress.task_id.in_(task_ids),
                    TaskDailyProgress.day_date >= period.start_date,
                    TaskDailyProgress.day_date <= period.end_date,
                    (
                        TaskDailyProgress.created_at <= final_snapshot.created_at
                    )
                    | TaskDailyProgress.created_at.is_(None),
                )
                .order_by(
                    TaskDailyProgress.task_id.asc(),
                    TaskDailyProgress.day_date.asc(),
                    TaskDailyProgress.id.asc(),
                )
            )
        ).scalars().all()
        if task_ids
        else []
    )
    progress_by_task: dict[uuid.UUID, list[TaskDailyProgress]] = defaultdict(list)
    for row in progress_rows:
        progress_by_task[row.task_id].append(row)
    audit_rows = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.entity_type == "task",
                    AuditLog.entity_id.in_(task_ids),
                    (AuditLog.created_at <= final_snapshot.created_at)
                    | AuditLog.created_at.is_(None),
                )
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            )
        ).scalars().all()
        if task_ids
        else []
    )
    audit_by_task: dict[uuid.UUID, list[AuditLog]] = defaultdict(list)
    for row in audit_rows:
        audit_by_task[row.entity_id].append(row)

    observations = (
        await db.execute(
            select(RealizationObservation).where(
                RealizationObservation.period_id == period.id,
                RealizationObservation.voided_at.is_(None),
            )
            .order_by(RealizationObservation.created_at.asc(), RealizationObservation.id.asc())
        )
    ).scalars().all()
    verified_ids = _verification_map(observations)
    evidence_observations = [
        row
        for row in observations
        if row.source_type not in {
            "realization_observation_verification",
            M3_MANAGER_REVIEW_SOURCE,
        }
    ]
    cancellation_by_task: dict[uuid.UUID, tuple[str, str]] = {}
    verified_absence_by_user_date: dict[tuple[uuid.UUID, date], str] = {}
    for observation in evidence_observations:
        if (
            observation.id in verified_ids
            and observation.user_id is not None
            and observation.category == "ABSENCE"
        ):
            absence_date = _date((observation.evidence_json or {}).get("date"))
            classification = str(
                (observation.evidence_json or {}).get("classification") or ""
            ).upper()
            if absence_date and classification:
                verified_absence_by_user_date[(observation.user_id, absence_date)] = classification
        if observation.id not in verified_ids or observation.task_id is None:
            continue
        kind = str((observation.evidence_json or {}).get("kind") or "").upper()
        if kind in {"CANCELLATION_APPROVED", "REMOVAL_APPROVED"}:
            cancellation_by_task[observation.task_id] = (
                "removed_or_canceled_approved",
                str(observation.id),
            )
        elif kind in {"CANCELLATION_REJECTED", "REMOVAL_UNAPPROVED"}:
            cancellation_by_task[observation.task_id] = (
                "removed_or_canceled_unapproved",
                str(observation.id),
            )

    active_users, common_leave = await load_active_users_and_common_leave(
        db,
        department_id=period.department_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    active_by_id = {user.id: user for user in active_users}
    working_days: set[date] = set()
    current_day = period.start_date
    while current_day <= period.end_date:
        if _is_working_day(current_day):
            working_days.add(current_day)
        current_day += timedelta(days=1)
    attendance = list((await db.execute(
        select(AttendanceLog)
        .where(
            AttendanceLog.user_id.in_(active_by_id),
            AttendanceLog.date >= period.start_date,
            AttendanceLog.date <= period.end_date,
        )
        .order_by(AttendanceLog.date.asc(), AttendanceLog.id.asc())
    )).scalars().all()) if active_by_id else []
    leave_days_by_user = {
        user_id: set(coverage.days) for user_id, coverage in common_leave.items()
    }
    absence_days_by_user = {
        user_id: set(coverage.absence_days) for user_id, coverage in common_leave.items()
    }
    full_day_absence_days_by_user = {
        user_id: set(coverage.full_day_absence_days)
        for user_id, coverage in common_leave.items()
    }
    delay_days_by_user = {
        user_id: set(coverage.delay_days) for user_id, coverage in common_leave.items()
    }
    for row in attendance:
        if row.user_id is None:
            continue
        if row.type == AttendanceType.PUSHIM_VJETOR:
            leave_days_by_user.setdefault(row.user_id, set()).add(row.date)
        elif row.type == AttendanceType.MUNGESE:
            absence_days_by_user.setdefault(row.user_id, set()).add(row.date)
            full_day_absence_days_by_user.setdefault(row.user_id, set()).add(row.date)
        elif row.type == AttendanceType.VONESE:
            delay_days_by_user.setdefault(row.user_id, set()).add(row.date)
    availability_statuses = full_period_availability_statuses(
        {
            user_id: CommonLeaveCoverage(
                days=frozenset(leave_days_by_user.get(user_id, set())),
                entry_ids=common_leave.get(user_id, CommonLeaveCoverage(frozenset(), ())).entry_ids,
                absence_days=frozenset(absence_days_by_user.get(user_id, set())),
                absence_entry_ids=common_leave.get(user_id, CommonLeaveCoverage(frozenset(), ())).absence_entry_ids,
                full_day_absence_days=frozenset(
                    full_day_absence_days_by_user.get(user_id, set())
                ),
                delay_days=frozenset(delay_days_by_user.get(user_id, set())),
                delay_entry_ids=common_leave.get(
                    user_id, CommonLeaveCoverage(frozenset(), ())
                ).delay_entry_ids,
            )
            for user_id in (
                set(leave_days_by_user)
                | set(absence_days_by_user)
                | set(full_day_absence_days_by_user)
                | set(delay_days_by_user)
            )
        },
        working_days=working_days,
    )
    eligible_user_ids = set(active_by_id)

    people: dict[uuid.UUID, dict[str, Any]] = {}
    unassigned: list[dict[str, Any]] = []

    def ensure_person(user_id: uuid.UUID, name: str) -> dict[str, Any] | None:
        if user_id not in eligible_user_ids:
            return None
        canonical_name = active_by_id[user_id].full_name or name
        availability_status = availability_statuses.get(user_id)
        if availability_status:
            return None
        if user_id not in people:
            people[user_id] = {
                "user_id": user_id,
                "user_name": canonical_name,
                "tasks": [],
                "observations": [],
                "attendance": {},
                "counters": defaultdict(int),
                "needs_review": [],
                # Daily RLZ reason + comment saved by the person themselves each working
                # day (see build_daily_rlz_compliance / TaskDailyRlzState). This is the
                # evidence the person entered while closing their own Daily Report — the
                # weekly Realization export surfaces it so managers don't re-collect it.
                "daily_rlz": [],
            }
        elif people[user_id]["user_name"] == "Employee" and canonical_name != "Employee":
            people[user_id]["user_name"] = canonical_name
        return people[user_id]

    for active_user in active_users:
        ensure_person(active_user.id, active_user.full_name)
    for snapshot in (planned_snapshot, final_snapshot):
        for user_id, name in _snapshot_users(snapshot).items():
            ensure_person(user_id, name)
    for observation in evidence_observations:
        if observation.user_id is not None:
            ensure_person(observation.user_id, "Employee")

    def assigned_people(task_id: uuid.UUID | None, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
        owners = current_owner_ids.get(task_id, set()) if task_id else set()
        if not owners:
            return fallback
        return [
            {
                "assignee_id": owner_id,
                "assignee_name": active_by_id[owner_id].full_name
                if owner_id in active_by_id
                else "Employee",
            }
            for owner_id in sorted(owners, key=str)
        ]

    user_ids = list(people)
    approved_absence_dates: dict[uuid.UUID, set[date]] = defaultdict(set)
    for user_id, leave in common_leave.items():
        if user_id in eligible_user_ids:
            approved_absence_dates[user_id].update(leave.days & working_days)
    for row in attendance:
        if row.user_id is not None and row.type == AttendanceType.PUSHIM_VJETOR:
            approved_absence_dates[row.user_id].add(row.date)

    for match_key, planned_task in planned.items():
        current = final.get(match_key)
        source = task_map.get(planned_task["task_id"])
        progress = progress_by_task.get(planned_task["task_id"], []) if planned_task["task_id"] else []
        positive_delta = sum(max(0, row.completed_delta) for row in progress)
        progress_evidence = [
            {
                "id": row.id,
                "day": row.day_date,
                "completed_value": row.completed_value,
                "total_value": row.total_value,
                "completed_delta": row.completed_delta,
                "daily_status": row.daily_status,
                "finish_period": row.finish_period,
            }
            for row in progress
        ]
        postpone, postponement_evidence = _postponement(
            source,
            audit_by_task.get(planned_task["task_id"], []) if planned_task["task_id"] else [],
        )
        deadline = _planned_deadline(
            planned_task,
            source,
            period,
            am_cutoff=am_cutoff,
            pm_cutoff=pm_cutoff,
        )
        effective_deadline = (
            _approved_postponement_deadline(
                source,
                audit_by_task.get(planned_task["task_id"], [])
                if planned_task["task_id"]
                else [],
                deadline,
            )
            if postpone == "approved_postponement"
            else deadline
        )
        classification = _classify_planned_task(
            current=current,
            positive_delta=positive_delta,
            postponement=postpone,
            effective_deadline=effective_deadline,
            period_end=period.end_date,
            cancellation=cancellation_by_task.get(
                planned_task["task_id"], ("needs_review", "")
            )[0]
            if current is None
            else None,
        )

        fact = {
            "match_key": match_key,
            "task_id": planned_task["task_id"],
            "title": planned_task["title"],
            "project_title": planned_task["project_title"],
            "project_id": planned_task["project_id"],
            "source_type": planned_task["source_type"],
            "classification": classification,
            "status": current["status"] if current else None,
            "completed_at": current.get("completed_at") if current else None,
            "planned_deadline": deadline,
            "effective_deadline": effective_deadline,
            "positive_progress_delta": positive_delta,
            "planned_occurrences": planned_task["occurrences"],
            "daily_progress": progress_evidence,
            "postponement": postpone,
            "postponement_evidence_ids": postponement_evidence,
            "meeting_origin_id": source.meeting_origin_id if source else None,
            "attribution": "planned_owner",
            "reassignment": (
                current is not None
                and {
                    item.get("assignee_id") for item in current["assignees"]
                }
                != {item.get("assignee_id") for item in planned_task["assignees"]}
            ),
            "status_progress_inconsistent": (
                current is not None
                and current["status"] == "IN_PROGRESS"
                and positive_delta <= 0
            ),
        }
        assignees = assigned_people(planned_task["task_id"], planned_task["assignees"])
        for assignee in assignees:
            user_id = assignee["assignee_id"]
            if user_id is None:
                unassigned.append(_iso(fact))
                continue
            person = ensure_person(user_id, assignee["assignee_name"])
            if person is None:
                continue
            planned_days = {
                item["day"]
                for item in planned_task["occurrences"]
                if item.get("day")
                and item.get("assignee_id") in {None, user_id}
            }
            absence_explains_no_progress = bool(
                classification == "no_progress"
                and planned_days
                and planned_days & approved_absence_dates.get(user_id, set())
            )
            person_classification = (
                "needs_review" if absence_explains_no_progress else classification
            )
            person_fact = {
                **fact,
                "classification": person_classification,
                "approved_absence_explanation": absence_explains_no_progress,
            }
            person["tasks"].append(person_fact)
            person["counters"]["planned_count"] += 1
            person["counters"][f"{person_classification}_count"] += 1
            if (
                person_classification
                in {
                    "completed_on_time",
                    "completed_late",
                    "removed_or_canceled_approved",
                }
                or postpone == "approved_postponement"
                or absence_explains_no_progress
            ):
                person["counters"]["accounted_planned_count"] += 1
            if postpone:
                person["counters"][f"{postpone}_count"] += 1
                if postpone == "rejected_postponement":
                    person["counters"]["unapproved_postponement_count"] += 1
            if fact["reassignment"]:
                person["needs_review"].append(
                    {"kind": "REASSIGNMENT", "match_key": match_key}
                )
            if person_classification == "needs_review":
                person["needs_review"].append(
                    {
                        "kind": (
                            "APPROVED_ABSENCE_EXPLANATION"
                            if absence_explains_no_progress
                            else (
                                "MISSING_COMPLETION_TIMESTAMP"
                                if current is not None and current["is_completed"]
                                else "MISSING_FROM_FINAL"
                            )
                        ),
                        "match_key": match_key,
                    }
                )
            if fact["status_progress_inconsistent"]:
                person["needs_review"].append(
                    {"kind": "STATUS_WITHOUT_PROGRESS", "match_key": match_key}
                )

        if current is not None:
            planned_owner_ids = {
                item.get("assignee_id")
                for item in assignees
                if item.get("assignee_id") is not None
            }
            actual_credit_supported = bool(
                current.get("is_completed")
                and current.get("completed_at")
                or positive_delta > 0
            )
            for assignee in assigned_people(current["task_id"], current["assignees"]):
                user_id = assignee.get("assignee_id")
                if user_id is None or user_id in planned_owner_ids:
                    continue
                actual_person = ensure_person(user_id, assignee["assignee_name"])
                if actual_person is None:
                    continue
                if actual_credit_supported:
                    credit_fact = {
                        **fact,
                        "attribution": "actual_worker",
                        "planned_owner": False,
                    }
                    actual_person["tasks"].append(credit_fact)
                    actual_person["counters"]["actual_work_credit_count"] += 1
                    if current.get("is_completed"):
                        actual_person["counters"]["actual_completed_credit_count"] += 1
                else:
                    actual_person["needs_review"].append(
                        {"kind": "UNCLEAR_REASSIGNMENT_CREDIT", "match_key": match_key}
                    )

    for match_key, task in final.items():
        if match_key in planned:
            continue
        source = task_map.get(task["task_id"])
        status = task["status"]
        progress = progress_by_task.get(task["task_id"], []) if task["task_id"] else []
        positive_delta = sum(max(0, row.completed_delta) for row in progress)
        progress_evidence = [
            {
                "id": row.id,
                "day": row.day_date,
                "completed_value": row.completed_value,
                "total_value": row.total_value,
                "completed_delta": row.completed_delta,
                "daily_status": row.daily_status,
                "finish_period": row.finish_period,
            }
            for row in progress
        ]
        if task["is_completed"]:
            classification = "additional_completed"
        elif status == "IN_PROGRESS" and positive_delta:
            classification = "additional_in_progress"
        elif status == "WAITING_CONFIRMATION":
            classification = "additional_pending"
        else:
            classification = "additional_no_progress"
        fact = {
            "match_key": match_key,
            "task_id": task["task_id"],
            "title": task["title"],
            "project_title": task["project_title"],
            "project_id": task["project_id"],
            "source_type": task["source_type"],
            "classification": classification,
            "status": status,
            "completed_at": task["completed_at"],
            "positive_progress_delta": positive_delta,
            "planned_occurrences": task["occurrences"],
            "daily_progress": progress_evidence,
            "introduced_after_baseline": True,
            "created_after_baseline": bool(
                source is not None
                and source.created_at is not None
                and source.created_at >= planned_snapshot.created_at
            ),
            "meeting_origin_id": source.meeting_origin_id if source else None,
            "attribution": "additional_owner",
        }
        for assignee in assigned_people(task["task_id"], task["assignees"]):
            user_id = assignee["assignee_id"]
            if user_id is None:
                unassigned.append(_iso(fact))
                continue
            person = ensure_person(user_id, assignee["assignee_name"])
            if person is None:
                continue
            person["tasks"].append(fact)
            person["counters"]["additional_count"] += 1
            person["counters"][f"{classification}_count"] += 1

    for task_id in completed_outside_snapshot_ids:
        source = task_map.get(task_id)
        if source is None:
            continue
        completed_day = (_local(source.completed_at) or source.completed_at).date()
        fact = {
            "match_key": f"id:{source.id}",
            "task_id": source.id,
            "title": source.title,
            "project_title": None,
            "project_id": source.project_id,
            "source_type": (
                "system" if source.system_template_origin_id else (
                    "project" if source.project_id else "fast"
                )
            ),
            "classification": "completed_outside_plan",
            "status": source.status,
            "completed_at": source.completed_at,
            "completion_day": completed_day,
            "daily_progress": [
                {
                    "id": row.id,
                    "day": row.day_date,
                    "completed_value": row.completed_value,
                    "total_value": row.total_value,
                    "completed_delta": row.completed_delta,
                    "daily_status": row.daily_status,
                    "finish_period": row.finish_period,
                }
                for row in progress_by_task.get(source.id, [])
            ],
            "introduced_after_baseline": False,
            "created_after_baseline": False,
            "meeting_origin_id": source.meeting_origin_id,
            "attribution": "completed_outside_weekly_plan",
        }
        for user_id in current_owner_ids.get(source.id, set()):
            person = ensure_person(user_id, "Employee")
            if person is None:
                continue
            person["tasks"].append(fact)
            person["counters"]["completed_outside_plan_count"] += 1

    completed_classes = {
        "completed_on_time",
        "completed_late",
        "additional_completed",
        "completed_outside_plan",
    }
    for person in people.values():
        completed_keys = {
            str(task.get("task_id") or task.get("match_key"))
            for task in person["tasks"]
            if task.get("classification") in completed_classes
        }
        person["counters"]["weekly_all_completed_count"] = len(completed_keys)
        person["weekly_all_completed_count"] = len(completed_keys)

    observation_by_user: dict[uuid.UUID, list[RealizationObservation]] = defaultdict(list)
    for observation in evidence_observations:
        if observation.user_id:
            observation_by_user[observation.user_id].append(observation)
    for user_id, person_observations in observation_by_user.items():
        if user_id not in people:
            continue
        person = people[user_id]
        for observation in person_observations:
            verified = observation.id in verified_ids or (
                observation.is_system_generated
                and (observation.evidence_json or {}).get("verified") is True
            )
            item = {
                "id": observation.id,
                "marker": observation.marker,
                "category": observation.category,
                "comment": observation.comment,
                "task_id": observation.task_id,
                "user_id": observation.user_id,
                "project_id": observation.project_id,
                "impact_minutes": observation.impact_minutes,
                "repeat_count": observation.repeat_count_at_creation,
                "evidence_json": observation.evidence_json or {},
                "source_type": observation.source_type,
                "created_at": observation.created_at,
                "relevant_date": (observation.evidence_json or {}).get("date")
                or (observation.evidence_json or {}).get("occurrence_date"),
                "verified": verified,
                "visibility": observation.visibility,
            }
            person["observations"].append(item)
            if verified:
                person["counters"][f"{observation.marker.lower()}_count"] += 1
                if observation.category == "REPEATED_PROBLEM":
                    person["counters"]["repeated_problem_count"] += 1
                if observation.category == "MISSED_MEETING":
                    person["counters"]["meeting_missed_count"] += 1
                if observation.category == "ABSENCE":
                    absence_kind = str(
                        (observation.evidence_json or {}).get("classification") or ""
                    ).upper()
                    if absence_kind == "UNEXCUSED":
                        person["counters"]["unexcused_absence_days"] += 1
                    elif absence_kind == "APPROVED_PERSONAL":
                        person["counters"]["approved_personal_absence_days"] += 1
                        person["counters"]["approved_absence_days"] += 1
                    elif absence_kind == "ANNUAL_LEAVE":
                        person["counters"]["annual_leave_days"] += 1
                        person["counters"]["approved_absence_days"] += 1
                related_task = next(
                    (
                        task
                        for task in person["tasks"]
                        if task.get("task_id") == observation.task_id
                    ),
                    None,
                )
                for counter_key, increment in verified_positive_counter_updates(
                    marker=observation.marker,
                    category=observation.category,
                    impact_minutes=observation.impact_minutes,
                    evidence_json=observation.evidence_json or {},
                    related_task=related_task,
                ).items():
                    person["counters"][counter_key] += increment
                impact = (observation.evidence_json or {}).get("impact_level")
                if observation.marker == "NEGATIVE" and impact in {"MAJOR", "MULTIPLE_PEOPLE"}:
                    person["counters"]["major_negative_impact"] = 1
                elif observation.marker == "NEGATIVE" and impact == "MINOR":
                    person["counters"]["minor_negative_impact_count"] += 1

    for row in attendance:
        if row.user_id not in people:
            continue
        person = people[row.user_id]
        if row.type == AttendanceType.VONESE:
            person["counters"]["tardiness_count"] += 1
        elif row.type == AttendanceType.PUSHIM_VJETOR:
            if (row.user_id, row.date) not in verified_absence_by_user_date:
                person["counters"]["annual_leave_days"] += 1
                person["counters"]["approved_absence_days"] += 1
        elif row.type == AttendanceType.MUNGESE:
            classification = verified_absence_by_user_date.get((row.user_id, row.date))
            if classification in {"APPROVED_PERSONAL", "ANNUAL_LEAVE", "UNEXCUSED"}:
                pass
            else:
                person["counters"]["unexcused_absence_days"] += 1
        person["attendance"][str(row.id)] = {
            "date": row.date,
            "type": row.type.value,
            "details": row.details,
        }

    attendance_leave_pairs = {
        (row.user_id, row.date)
        for row in attendance
        if row.user_id is not None and row.type == AttendanceType.PUSHIM_VJETOR
    }
    attendance_absence_pairs = {
        (row.user_id, row.date)
        for row in attendance
        if row.user_id is not None and row.type == AttendanceType.MUNGESE
    }
    attendance_delay_pairs = {
        (row.user_id, row.date)
        for row in attendance
        if row.user_id is not None and row.type == AttendanceType.VONESE
    }
    for user_id, leave in common_leave.items():
        if user_id not in people:
            continue
        person = people[user_id]
        for leave_day in sorted(leave.days & working_days):
            if (user_id, leave_day) in attendance_leave_pairs:
                continue
            person["counters"]["annual_leave_days"] += 1
            person["counters"]["approved_absence_days"] += 1
            evidence_key = f"common-leave:{user_id}:{leave_day.isoformat()}"
            person["attendance"][evidence_key] = {
                "date": leave_day,
                "type": AttendanceType.PUSHIM_VJETOR.value,
                "details": "Common View PV/FEST",
                "common_entry_ids": [str(entry_id) for entry_id in leave.entry_ids],
            }
        for delay_day in sorted(leave.delay_days & working_days):
            if (user_id, delay_day) in attendance_delay_pairs:
                continue
            person["counters"]["tardiness_count"] += 1
            evidence_key = f"common-delay:{user_id}:{delay_day.isoformat()}"
            person["attendance"][evidence_key] = {
                "date": delay_day,
                "type": AttendanceType.VONESE.value,
                "details": "Common View Vonesë",
                "common_entry_ids": [str(entry_id) for entry_id in leave.delay_entry_ids],
            }
        for absence_day in sorted(leave.absence_days & working_days):
            if (user_id, absence_day) in attendance_absence_pairs:
                continue
            classification = verified_absence_by_user_date.get((user_id, absence_day))
            if classification in {"APPROVED_PERSONAL", "ANNUAL_LEAVE"}:
                continue
            if classification != "UNEXCUSED":
                person["counters"]["unexcused_absence_days"] += 1
            evidence_key = f"common-absence:{user_id}:{absence_day.isoformat()}"
            person["attendance"][evidence_key] = {
                "date": absence_day,
                "type": AttendanceType.MUNGESE.value,
                "details": "Common View Mungesë",
                "common_entry_ids": [str(entry_id) for entry_id in leave.absence_entry_ids],
            }

    daily_rlz_rows = (
        (
            await db.execute(
                select(TaskDailyRlzState, Task.title)
                .join(Task, Task.id == TaskDailyRlzState.task_id)
                .where(
                    TaskDailyRlzState.user_id.in_(people.keys()),
                    TaskDailyRlzState.day_date >= period.start_date,
                    TaskDailyRlzState.day_date <= period.end_date,
                )
                .order_by(TaskDailyRlzState.day_date.asc(), TaskDailyRlzState.updated_at.asc())
            )
        ).all()
        if people
        else []
    )
    for state, task_title in daily_rlz_rows:
        person = people.get(state.user_id)
        if person is None or (not state.reason_code and not state.comment):
            continue
        person["daily_rlz"].append(
            {
                "date": state.day_date,
                "task_title": task_title,
                "reason_code": state.reason_code,
                "reason_label": REASON_LABELS.get(state.reason_code) if state.reason_code else None,
                "comment": state.comment,
            }
        )

    for person in people.values():
        person["tasks"].sort(
            key=lambda item: (
                item.get("match_key") or "",
                item.get("attribution") or "",
            )
        )
        person["observations"].sort(key=lambda item: str(item["id"]))
        person["needs_review"].sort(
            key=lambda item: (str(item.get("kind") or ""), str(item.get("match_key") or ""))
        )
        person["attendance"] = dict(sorted(person["attendance"].items()))
        person["daily_rlz"].sort(key=lambda item: (item.get("date") or date.min, item.get("task_title") or ""))

    return {
        "people": {
            str(user_id): _iso(people[user_id])
            for user_id in sorted(people, key=str)
        },
        "unassigned": sorted(
            unassigned,
            key=lambda item: (item.get("match_key") or "", item.get("classification") or ""),
        ),
        "department_unique_task_keys": sorted(set(planned) | set(final)),
        "department_planned_task_keys": sorted(planned),
        "department_final_task_keys": sorted(final),
        "department_additional_task_keys": sorted(set(final) - set(planned)),
        "excluded_people": [
            {
                "user_id": str(user.id),
                "user_name": user.full_name,
                "reason": availability_statuses[user.id],
                "common_entry_ids": [
                    str(entry_id) for entry_id in common_leave[user.id].entry_ids
                ] if user.id in common_leave else [],
            }
            for user in active_users
            if user.id in availability_statuses
        ],
        "planned_snapshot_id": str(planned_snapshot.id),
        "final_snapshot_id": str(final_snapshot.id),
    }
