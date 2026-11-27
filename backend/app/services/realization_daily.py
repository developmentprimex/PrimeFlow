from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attendance_log import AttendanceLog
from app.models.enums import AttendanceType, RealizationPeriodStatus
from app.models.project import Project
from app.models.realization import (
    RealizationDepartmentResult,
    RealizationObservation,
    RealizationPeriod,
    RealizationPersonResult,
)
from app.models.system_task_template import SystemTaskTemplate
from app.services.realization_manager_review import M3_MANAGER_REVIEW_SOURCE
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_user_comment import TaskUserComment
from app.models.weekly_planner_snapshot import WeeklyPlannerSnapshot
from app.services.daily_realization_explanation import reason_requires_comment
from app.services.realization_calculator import build_live_questions, build_project_progress
from app.services.realization_evidence import _snapshot_tasks
from app.services.realization_people import load_active_users_and_common_leave
from app.services.realization_periods import require_recalculable, transition_period
from app.services.realization_pulse import build_recovery, calculate_pulse


def _local_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    zone = ZoneInfo(settings.REALIZATION_TIMEZONE)
    localized = value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)
    return localized.date()


def _effective_task_comment_map(
    general_rows: list[TaskUserComment],
    daily_rows: list[TaskDailyRlzState],
) -> dict[tuple[uuid.UUID, uuid.UUID], str]:
    """Prefer the day-scoped RLZ comment over the task's general comment."""
    comments = {
        (row.task_id, row.user_id): (row.comment or "").strip()
        for row in general_rows
    }
    for row in daily_rows:
        if row.comment is not None:
            comments[(row.task_id, row.user_id)] = row.comment.strip()
    return comments


def _system_task_operational_day(task: Task) -> date | None:
    """Place generated work on its occurrence/run day, not its final deadline."""
    meeting_day = getattr(task, "meeting_occurrence_date", None)
    if meeting_day is not None:
        return meeting_day
    return _local_date(
        task.origin_run_at
        or task.start_date
        or getattr(task, "created_at", None)
        or task.due_date
    )


def _include_nonplanned_weekly_task(
    *,
    created_at: datetime,
    planned_snapshot_at: datetime,
    completed_day: date | None,
    week_start: date,
    as_of_day: date,
) -> bool:
    """Keep new work and every task actually completed inside the report week."""
    return created_at >= planned_snapshot_at or bool(
        completed_day is not None and week_start <= completed_day <= as_of_day
    )


def _include_task_in_daily_facts(
    *,
    task: Task | None,
    classification: str,
    day: date,
) -> bool:
    """Keep future, untouched work out of today's Realization facts.

    A pinned weekly snapshot can still contain an occurrence for today after the
    live task has been moved to a later start date.  That historical occurrence
    remains useful for weekly-plan accounting, but it must not become a Pink
    no-progress blocker for a day on which the task has not started yet.

    Actual progress or completion is still reported even when the live dates are
    inconsistent, so this guard only excludes ``no_progress`` facts.
    """
    if task is None or classification != "no_progress":
        return True
    start_day = _local_date(task.start_date)
    return start_day is None or start_day <= day


def _daily_classification(
    task: Task | None,
    progress: TaskDailyProgress | None,
    day: date,
) -> str:
    if task is not None and _local_date(task.completed_at) is not None:
        if _local_date(task.completed_at) <= day:  # type: ignore[operator]
            return "completed"
    status = str(progress.daily_status if progress else (task.status if task else "TODO")).upper()
    if status == "DONE":
        return "completed"
    if status == "WAITING_CONFIRMATION":
        return "pending_confirmation"
    if status == "IN_PROGRESS" or (progress and progress.completed_delta > 0):
        return "in_progress"
    return "no_progress"


def _task_fact(
    *,
    key: str,
    title: str,
    task: Task | None,
    raw: dict[str, Any] | None,
    progress: TaskDailyProgress | None,
    day: date,
    attribution: str,
) -> dict[str, Any]:
    project_id = task.project_id if task else (raw or {}).get("project_id")
    daily_progress = []
    if progress is not None:
        daily_progress.append(
            {
                "id": str(progress.id),
                "day": progress.day_date.isoformat(),
                "completed_value": progress.completed_value,
                "total_value": progress.total_value,
                "completed_delta": progress.completed_delta,
                "daily_status": progress.daily_status,
                "finish_period": progress.finish_period,
            }
        )
    source_type = (raw or {}).get("source_type")
    if not source_type and task is not None:
        source_type = "system" if task.system_template_origin_id else (
            "project" if task.project_id else "fast"
        )
    return {
        "match_key": key,
        "task_id": str(task.id) if task else (
            str((raw or {}).get("task_id")) if (raw or {}).get("task_id") else None
        ),
        "title": title,
        "project_id": str(project_id) if project_id else None,
        "project_title": (raw or {}).get("project_title"),
        "source_type": source_type or "project",
        "classification": _daily_classification(task, progress, day),
        "status": task.status if task else (raw or {}).get("status"),
        "daily_progress": daily_progress,
        "attribution": attribution,
        "evidence_ids": [str(progress.id)] if progress else [],
    }


async def calculate_daily_period(
    db: AsyncSession,
    *,
    period: RealizationPeriod,
    planned_snapshot: WeeklyPlannerSnapshot,
    actor_id: uuid.UUID,
    only_user_id: uuid.UUID | None = None,
) -> tuple[list[RealizationPersonResult], RealizationDepartmentResult | None]:
    """Persist an immutable-by-day operational snapshot for one department."""
    require_recalculable(period)
    if planned_snapshot is None:
        raise ValueError("PLANNED snapshot is required for daily realization")

    day = period.start_date
    planned = _snapshot_tasks(planned_snapshot)
    planned_ids = {row["task_id"] for row in planned.values() if row.get("task_id")}
    question_task_ids = set(
        (
            await db.execute(
                select(Task.id).where(
                    Task.id.in_(planned_ids),
                    or_(
                        Task.question_origin_id.is_not(None),
                        Task.question_batch_date.is_not(None),
                    ),
                )
            )
        ).scalars().all()
    ) if planned_ids else set()
    if question_task_ids:
        planned = {
            key: row
            for key, row in planned.items()
            if row.get("task_id") not in question_task_ids
        }
        planned_ids -= question_task_ids

    # A weekly snapshot may predate a template visibility change. System tasks
    # are eligible for Realization only while their template is explicitly
    # opted into the Weekly Planner, so remove opted-out snapshot rows before
    # any daily or cumulative weekly counters are built.
    excluded_system_task_ids = set(
        (
            await db.execute(
                select(Task.id)
                .join(
                    SystemTaskTemplate,
                    Task.system_template_origin_id == SystemTaskTemplate.id,
                )
                .where(
                    Task.id.in_(planned_ids),
                    Task.system_template_origin_id.is_not(None),
                    SystemTaskTemplate.show_in_weekly_planner.is_not(True),
                )
            )
        ).scalars().all()
    ) if planned_ids else set()
    if excluded_system_task_ids:
        planned = {
            key: row
            for key, row in planned.items()
            if row.get("task_id") not in excluded_system_task_ids
        }
        planned_ids -= excluded_system_task_ids

    department_users, common_leave = await load_active_users_and_common_leave(
        db,
        department_id=period.department_id,
        start_date=day,
        end_date=day,
    )
    department_user_ids = {user.id for user in department_users}

    zone = ZoneInfo(settings.REALIZATION_TIMEZONE)
    day_end_local = datetime.combine(day, time.max, tzinfo=zone)
    day_end_utc = day_end_local.astimezone(timezone.utc)
    task_query = select(Task).outerjoin(
        SystemTaskTemplate,
        Task.system_template_origin_id == SystemTaskTemplate.id,
    ).where(
        or_(
            Task.department_id == period.department_id,
            Task.id.in_(planned_ids),
            and_(
                Task.system_template_origin_id.is_not(None),
                Task.assigned_to.in_(department_user_ids),
            ),
        ),
        Task.created_at <= day_end_utc,
        Task.question_origin_id.is_(None),
        Task.question_batch_date.is_(None),
        # System work belongs in Realization only when its template was
        # explicitly opted into the Weekly Planner.
        or_(
            Task.system_template_origin_id.is_(None),
            SystemTaskTemplate.show_in_weekly_planner.is_(True),
        ),
    )
    tasks = (await db.execute(task_query)).scalars().all()
    task_by_id = {task.id: task for task in tasks}
    planned = {
        key: row
        for key, row in planned.items()
        if row.get("source_type") != "system" or row.get("task_id") in task_by_id
    }
    planned_ids = {row["task_id"] for row in planned.values() if row.get("task_id")}
    project_ids = {task.project_id for task in tasks if task.project_id}
    project_titles = {
        project.id: project.title
        for project in (
            await db.execute(select(Project).where(Project.id.in_(project_ids)))
        ).scalars().all()
    } if project_ids else {}
    relevant_ids = set(task_by_id) | planned_ids
    progress_rows = (
        (
            await db.execute(
                select(TaskDailyProgress)
                .where(
                    TaskDailyProgress.task_id.in_(relevant_ids),
                    TaskDailyProgress.day_date <= day,
                )
                .order_by(
                    TaskDailyProgress.task_id.asc(),
                    TaskDailyProgress.day_date.asc(),
                    TaskDailyProgress.id.asc(),
                )
            )
        ).scalars().all()
        if relevant_ids
        else []
    )
    latest_progress: dict[uuid.UUID, TaskDailyProgress] = {}
    daily_progress: dict[uuid.UUID, TaskDailyProgress] = {}
    for row in progress_rows:
        latest_progress[row.task_id] = row
        if row.day_date == day:
            daily_progress[row.task_id] = row

    assignee_rows = (
        (
            await db.execute(select(TaskAssignee).where(TaskAssignee.task_id.in_(relevant_ids)))
        ).scalars().all()
        if relevant_ids
        else []
    )
    assignees: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for row in assignee_rows:
        assignees[row.task_id].add(row.user_id)
    for task in tasks:
        if task.assigned_to and not assignees.get(task.id):
            assignees[task.id].add(task.assigned_to)

    excluded_on_leave = {
        user_id for user_id, leave in common_leave.items() if day in leave.days
    }
    eligible_users = [
        user
        for user in department_users
        if user.id not in excluded_on_leave
        and (only_user_id is None or user.id == only_user_id)
    ]
    user_names = {user.id: user.full_name for user in eligible_users}
    people: dict[uuid.UUID, dict[str, Any]] = {
        user_id: {
            "user_id": str(user_id),
            "user_name": name,
            "date": day.isoformat(),
            "tasks": [],
            "attendance": [],
            "counters": defaultdict(int),
            "questions": [],
        }
        for user_id, name in user_names.items()
    }

    weekly_task_keys_by_user: dict[uuid.UUID, set[str]] = defaultdict(set)
    weekly_expected_keys_by_user: dict[uuid.UUID, set[str]] = defaultdict(set)
    weekly_completed_by_user: dict[uuid.UUID, set[str]] = defaultdict(set)
    weekly_all_completed_by_user: dict[uuid.UUID, dict[str, dict[str, Any]]] = defaultdict(dict)
    weekly_additional_keys_by_user: dict[uuid.UUID, set[str]] = defaultdict(set)
    weekly_fast_task_keys_by_user: dict[uuid.UUID, set[str]] = defaultdict(set)
    week_start = planned_snapshot.week_start_date

    progress_completion_day: dict[uuid.UUID, date] = {}
    for row in progress_rows:
        if str(row.daily_status or "").upper() != "DONE":
            continue
        previous = progress_completion_day.get(row.task_id)
        if previous is None or row.day_date < previous:
            progress_completion_day[row.task_id] = row.day_date

    def completion_day(task: Task | None, raw: dict[str, Any] | None = None) -> date | None:
        task_day = _local_date(task.completed_at) if task is not None else None
        if task_day is not None:
            return task_day
        if task is not None and task.id in progress_completion_day:
            return progress_completion_day[task.id]
        return _local_date((raw or {}).get("completed_at"))

    def remember_weekly_completion(
        *,
        user_id: uuid.UUID,
        key: str,
        fact: dict[str, Any],
        completed_day: date | None,
    ) -> None:
        if completed_day is None or completed_day < week_start or completed_day > day:
            return
        fact["completion_day"] = completed_day.isoformat()
        weekly_all_completed_by_user[user_id][key] = fact

    for key, raw in planned.items():
        task = task_by_id.get(raw.get("task_id"))
        progress = daily_progress.get(raw.get("task_id"))
        occurrence_users: dict[uuid.UUID, bool] = {}
        task_id = raw.get("task_id")
        current_owner_ids = assignees.get(task_id, set()) if task_id else set()
        snapshot_owner_ids = {
            assignment.get("assignee_id")
            for assignment in raw.get("assignees") or []
            if assignment.get("assignee_id")
        }
        owner_ids = current_owner_ids or snapshot_owner_ids
        occurrences = raw.get("occurrences") or []
        for user_id in owner_ids:
            # Ownership comes from the live assignment table. Snapshot occurrence
            # assignees are historical and must not leak another person's task.
            occurrence_users[user_id] = any(
                occurrence.get("day") == day for occurrence in occurrences
            ) or (
                not occurrences and _local_date(raw.get("planned_due_date")) == day
            )
            expected_by_today = any(
                occurrence.get("day") is not None and occurrence.get("day") <= day
                for occurrence in occurrences
            ) or (
                not occurrences
                and _local_date(raw.get("planned_due_date")) is not None
                and _local_date(raw.get("planned_due_date")) <= day  # type: ignore[operator]
            )
            if expected_by_today:
                weekly_expected_keys_by_user[user_id].add(key)
        for user_id, due_today in occurrence_users.items():
            if user_id not in people:
                continue
            weekly_task_keys_by_user[user_id].add(key)
            latest = latest_progress.get(raw.get("task_id"))
            completed_as_of_day = (
                task is not None
                and _local_date(task.completed_at) is not None
                and _local_date(task.completed_at) <= day  # type: ignore[operator]
            ) or (latest is not None and latest.daily_status == "DONE")
            if completed_as_of_day:
                weekly_completed_by_user[user_id].add(key)
                completed_day = completion_day(task, raw)
                completion_fact = _task_fact(
                    key=key,
                    title=raw["title"],
                    task=task,
                    raw=raw,
                    progress=latest,
                    day=day,
                    attribution="completed_from_weekly_plan",
                )
                remember_weekly_completion(
                    user_id=user_id,
                    key=key,
                    fact=completion_fact,
                    completed_day=completed_day,
                )
            if not due_today:
                continue
            fact = _task_fact(
                key=key,
                title=raw["title"],
                task=task,
                raw=raw,
                progress=progress,
                day=day,
                attribution="planned_today",
            )
            if not _include_task_in_daily_facts(
                task=task,
                classification=fact["classification"],
                day=day,
            ):
                continue
            people[user_id]["tasks"].append(fact)
            people[user_id]["counters"]["planned_count"] += 1
            people[user_id]["counters"][f"{fact['classification']}_count"] += 1
            if fact["source_type"] == "system":
                people[user_id]["counters"]["system_task_count"] += 1
                if fact["classification"] == "completed":
                    people[user_id]["counters"]["system_task_completed_count"] += 1

    for task in tasks:
        is_system_task = task.system_template_origin_id is not None
        if task.id in planned_ids:
            continue
        if _local_date(task.created_at) > day:  # type: ignore[operator]
            continue

        created_after_plan = task.created_at >= planned_snapshot.created_at
        completed_day = completion_day(task)
        scheduled_system_day = _system_task_operational_day(task)
        completed_this_week = bool(
            completed_day is not None and week_start <= completed_day <= day
        )
        if not is_system_task and not _include_nonplanned_weekly_task(
            created_at=task.created_at,
            planned_snapshot_at=planned_snapshot.created_at,
            completed_day=completed_day,
            week_start=week_start,
            as_of_day=day,
        ):
            continue

        source_type = "system" if is_system_task else (
            "project" if task.project_id else "fast"
        )
        for user_id in assignees.get(task.id, set()):
            if user_id not in people:
                continue
            if (
                is_system_task
                and scheduled_system_day is not None
                and week_start <= scheduled_system_day <= day
            ):
                system_key = f"id:{task.id}"
                weekly_task_keys_by_user[user_id].add(system_key)
                weekly_expected_keys_by_user[user_id].add(system_key)
                if completed_this_week:
                    weekly_completed_by_user[user_id].add(system_key)
            if not is_system_task and created_after_plan:
                weekly_additional_keys_by_user[user_id].add(str(task.id))
                if source_type == "fast":
                    weekly_fast_task_keys_by_user[user_id].add(str(task.id))
            if completed_this_week:
                completion_fact = _task_fact(
                    key=f"id:{task.id}",
                    title=task.title,
                    task=task,
                    raw={
                        "project_title": project_titles.get(task.project_id),
                        "source_type": source_type,
                    },
                    progress=latest_progress.get(task.id),
                    day=day,
                    attribution=(
                        "system_schedule"
                        if is_system_task
                        else (
                            "added_after_weekly_plan"
                            if created_after_plan
                            else "completed_outside_weekly_plan"
                        )
                    ),
                )
                remember_weekly_completion(
                    user_id=user_id,
                    key=f"id:{task.id}",
                    fact=completion_fact,
                    completed_day=completed_day,
                )

        has_activity_today = (
            _local_date(task.created_at) == day
            or _local_date(task.completed_at) == day
            or task.id in daily_progress
        )
        if is_system_task:
            if scheduled_system_day != day and not has_activity_today:
                continue
        elif not has_activity_today:
            continue

        for user_id in assignees.get(task.id, set()):
            if user_id not in people:
                continue
            fact = _task_fact(
                key=f"id:{task.id}",
                title=task.title,
                task=task,
                raw={
                    "project_title": project_titles.get(task.project_id),
                    "source_type": source_type,
                },
                progress=daily_progress.get(task.id),
                day=day,
                attribution=(
                    "system_schedule" if is_system_task else "added_after_weekly_plan"
                ),
            )
            if not _include_task_in_daily_facts(
                task=task,
                classification=fact["classification"],
                day=day,
            ):
                continue
            people[user_id]["tasks"].append(fact)
            if is_system_task:
                people[user_id]["counters"]["system_task_count"] += 1
                if fact["classification"] == "completed":
                    people[user_id]["counters"]["system_task_completed_count"] += 1
                else:
                    people[user_id]["counters"][f"{fact['classification']}_count"] += 1
            else:
                people[user_id]["counters"]["additional_count"] += 1
            if fact["source_type"] == "fast":
                people[user_id]["counters"]["fast_task_count"] += 1

    attendance = (
        await db.execute(
            select(AttendanceLog).where(
                AttendanceLog.user_id.in_(list(people)), AttendanceLog.date == day
            )
        )
    ).scalars().all() if people else []
    for row in attendance:
        person = people.get(row.user_id)
        if person is None:
            continue
        person["attendance"].append(
            {"id": str(row.id), "type": row.type.value, "details": row.details}
        )
        if row.type == AttendanceType.VONESE:
            person["counters"]["tardiness_count"] += 1
        elif row.type == AttendanceType.PUSHIM_VJETOR:
            person["counters"]["annual_leave_days"] += 1
            person["counters"]["approved_absence_days"] += 1
        elif row.type == AttendanceType.MUNGESE:
            person["counters"]["unexcused_absence_days"] += 1

    for user_id, person in people.items():
        coverage = common_leave.get(user_id)
        if coverage is None:
            continue
        types = {
            str(item.get("type") or "").upper()
            for item in person["attendance"]
            if isinstance(item, dict)
        }
        if day in coverage.delay_days and "VONESE" not in types:
            person["attendance"].append({
                "date": day.isoformat(),
                "type": AttendanceType.VONESE.value,
                "details": "Common View Vonesë",
                "source": "common_view",
            })
            person["counters"]["tardiness_count"] += 1
        if day in coverage.absence_days and "MUNGESE" not in types:
            person["attendance"].append({
                "date": day.isoformat(),
                "type": AttendanceType.MUNGESE.value,
                "details": "Common View Mungesë",
                "source": "common_view",
            })
            person["counters"]["unexcused_absence_days"] += 1

    # M3 and RLZ share these normalized source records. We never parse report text.
    relevant_task_ids = {
        uuid.UUID(str(task_fact["task_id"]))
        for person in people.values()
        for task_fact in person["tasks"]
        if task_fact.get("task_id")
    }
    comment_rows = (
        (
            await db.execute(
                select(TaskUserComment).where(
                    TaskUserComment.task_id.in_(relevant_task_ids),
                    TaskUserComment.user_id.in_(list(people)),
                )
            )
        ).scalars().all()
        if relevant_task_ids and people
        else []
    )
    daily_comment_rows = (
        (
            await db.execute(
                select(TaskDailyRlzState).where(
                    TaskDailyRlzState.task_id.in_(relevant_task_ids),
                    TaskDailyRlzState.user_id.in_(list(people)),
                    TaskDailyRlzState.day_date == period.start_date,
                )
            )
        ).scalars().all()
        if relevant_task_ids and people
        else []
    )
    comments = _effective_task_comment_map(comment_rows, daily_comment_rows)
    comment_exempt_tasks = {
        (row.task_id, row.user_id) for row in daily_comment_rows if not reason_requires_comment(row.reason_code)
    }

    observation_rows = (
        await db.execute(
            select(RealizationObservation).where(
                RealizationObservation.department_id == period.department_id,
                RealizationObservation.voided_at.is_(None),
                RealizationObservation.created_at <= day_end_utc,
            )
        )
    ).scalars().all()
    verified_ids: set[uuid.UUID] = set()
    for observation in observation_rows:
        if observation.source_type != "realization_observation_verification":
            continue
        raw_id = (observation.evidence_json or {}).get("verification_of") or observation.source_id
        try:
            verified_ids.add(uuid.UUID(str(raw_id)))
        except (TypeError, ValueError):
            continue
    for observation in observation_rows:
        if observation.source_type in {
            "realization_observation_verification",
            M3_MANAGER_REVIEW_SOURCE,
        } or observation.user_id not in people:
            continue
        verified = observation.id in verified_ids or (
            observation.is_system_generated and (observation.evidence_json or {}).get("verified") is True
        )
        person = people[observation.user_id]
        person.setdefault("observations", []).append(
            {
                "id": str(observation.id),
                "marker": observation.marker,
                "category": observation.category,
                "comment": observation.comment,
                "task_id": str(observation.task_id) if observation.task_id else None,
                "evidence_json": observation.evidence_json or {},
                "verified": verified,
                "visibility": observation.visibility,
            }
        )
        if not verified:
            if observation.marker in {"POSITIVE", "DIAMOND"}:
                person["counters"]["unverified_extra_count"] += 1
            continue
        if observation.marker == "DIAMOND":
            person["counters"]["verified_diamond_count"] += 1
        elif observation.marker == "POSITIVE":
            person["counters"]["verified_extra_count"] += 1
        elif observation.marker == "NEGATIVE":
            evidence = observation.evidence_json or {}
            if observation.category == "BLOCKER" and evidence.get("outside_person_control") is True:
                person["counters"]["verified_external_blocker_count"] += 1
            else:
                person["counters"]["unresolved_negative_count"] += 1
        if observation.category == "PRIORITY_CHANGE":
            person["counters"]["approved_priority_change_count"] += 1

    existing = {
        row.user_id: row
        for row in (
            await db.execute(
                select(RealizationPersonResult).where(
                    RealizationPersonResult.period_id == period.id
                )
            )
        ).scalars().all()
    }
    for user_id, stale_result in existing.items():
        if only_user_id is None and user_id not in people:
            await db.delete(stale_result)
    results: list[RealizationPersonResult] = []
    for user_id, person in people.items():
        counters = dict(person["counters"])
        planned_today = int(counters.get("planned_count", 0))
        completed_today = int(counters.get("completed_count", 0))
        weekly_total = len(weekly_task_keys_by_user[user_id])
        weekly_expected = len(weekly_expected_keys_by_user[user_id])
        weekly_completed = len(weekly_completed_by_user[user_id])
        weekly_all_completed = len(weekly_all_completed_by_user[user_id])
        counters["daily_planned_count"] = planned_today
        counters["daily_completed_count"] = completed_today
        counters["weekly_planned_count"] = weekly_total
        counters["weekly_expected_count"] = weekly_expected
        counters["weekly_completed_count"] = weekly_completed
        counters["weekly_all_completed_count"] = weekly_all_completed
        counters["weekly_completed_outside_plan_count"] = max(
            0, weekly_all_completed - weekly_completed
        )
        counters["weekly_additional_count"] = len(weekly_additional_keys_by_user[user_id])
        counters["weekly_fast_task_count"] = len(weekly_fast_task_keys_by_user[user_id])
        person["counters"] = counters
        person["daily_planned_count"] = planned_today
        person["daily_completed_count"] = completed_today
        person["weekly_planned_count"] = weekly_total
        person["expected_cumulative_count"] = weekly_expected
        person["actual_cumulative_count"] = weekly_completed
        person["weekly_completed_count"] = weekly_completed
        person["weekly_all_completed_count"] = weekly_all_completed
        person["weekly_completed_outside_plan_count"] = max(
            0, weekly_all_completed - weekly_completed
        )
        person["weekly_completed_tasks"] = list(
            weekly_all_completed_by_user[user_id].values()
        )
        person["weekly_additional_count"] = len(weekly_additional_keys_by_user[user_id])
        person["weekly_fast_task_count"] = len(weekly_fast_task_keys_by_user[user_id])
        person["daily_progress_percent"] = (
            round(completed_today * 100.0 / planned_today, 1) if planned_today else 0.0
        )
        person["weekly_progress_percent"] = (
            round(weekly_completed * 100.0 / weekly_total, 1) if weekly_total else 0.0
        )
        missing_comments = 0
        missing_pink_explanations = 0
        for task_fact in person["tasks"]:
            task_id_raw = task_fact.get("task_id")
            task_uuid = uuid.UUID(str(task_id_raw)) if task_id_raw else None
            comment = comments.get((task_uuid, user_id), "") if task_uuid else ""
            comment_exempt = (task_uuid, user_id) in comment_exempt_tasks
            task_fact["user_comment"] = comment or None
            task_fact["comment_required_before_close"] = task_fact.get("source_type") != "system" and (
                not comment_exempt or task_fact.get("classification") == "completed"
            )
            task_fact["rlz_impact"] = (
                "PINK_ACTION_REQUIRED"
                if task_fact.get("attribution") in {"planned_today", "system_schedule"}
                and task_fact.get("classification") == "no_progress"
                else "EXPECTED_PLAN"
                if task_fact.get("attribution") == "planned_today"
                else "ADDITIONAL_EVIDENCE"
            )
            task_fact["explanation_missing"] = bool(
                task_fact["rlz_impact"] == "PINK_ACTION_REQUIRED" and not comment and not comment_exempt
            )
            if task_fact["explanation_missing"]:
                missing_pink_explanations += 1
            if (
                task_fact.get("classification") == "completed"
                and task_fact.get("source_type") != "system"
                and not comment
            ):
                missing_comments += 1
        counters["missing_comment_count"] = missing_comments
        counters["missing_pink_explanation_count"] = missing_pink_explanations
        person["missing_comment_count"] = missing_comments
        person["missing_pink_explanation_count"] = missing_pink_explanations
        person["unresolved_pink_count"] = int(counters.get("no_progress_count", 0))
        pulse = calculate_pulse(person)
        person["pulse"] = pulse.to_dict()
        person["recovery"] = build_recovery(
            decision=pulse,
            weekly_planned_count=weekly_total,
            as_of_day=day,
            week_end=period.start_date + timedelta(days=4),
        )
        person["project_progress"] = build_project_progress(person["tasks"])
        person["questions"] = build_live_questions(person)
        result = existing.get(user_id)
        if result is None:
            result = RealizationPersonResult(
                period_id=period.id,
                user_id=user_id,
                department_id=period.department_id,
            )
            db.add(result)
        previous_facts = result.facts_json or {}
        previous_ai_analysis = previous_facts.get("ai_analysis")
        if previous_ai_analysis:
            person["ai_analysis"] = previous_ai_analysis
        previous_ai_history = previous_facts.get("ai_analysis_history")
        if previous_ai_history:
            person["ai_analysis_history"] = previous_ai_history
        result.facts_json = person
        result.planned_count = planned_today
        result.completed_on_time_count = completed_today
        result.in_progress_count = int(counters.get("in_progress_count", 0))
        result.pending_count = int(counters.get("pending_confirmation_count", 0))
        result.no_progress_count = int(counters.get("no_progress_count", 0))
        result.additional_count = int(counters.get("additional_count", 0))
        result.system_task_count = int(counters.get("system_task_count", 0))
        result.system_task_completed_count = int(
            counters.get("system_task_completed_count", 0)
        )
        result.tardiness_count = int(counters.get("tardiness_count", 0))
        result.approved_absence_days = int(counters.get("approved_absence_days", 0))
        result.suggested_symbol = None
        result.suggested_level = None
        result.suggested_bonus = None
        results.append(result)

    department_result = (
        await db.execute(
            select(RealizationDepartmentResult).where(
                RealizationDepartmentResult.period_id == period.id,
                RealizationDepartmentResult.department_id == period.department_id,
            )
        )
    ).scalar_one_or_none()
    if department_result is None and only_user_id is None:
        department_result = RealizationDepartmentResult(
            period_id=period.id, department_id=period.department_id
        )
        db.add(department_result)
    if department_result is not None and only_user_id is None:
        department_result.facts_json = {
            "date": day.isoformat(),
            "people_count": len(results),
            "planned_count": sum(row.planned_count for row in results),
            "completed_count": sum(row.completed_on_time_count for row in results),
            "additional_count": sum(row.additional_count for row in results),
            "source_planned_snapshot_id": str(planned_snapshot.id),
            "excluded_people": [
                {
                    "user_id": str(user.id),
                    "user_name": user.full_name,
                    "reason": "ANNUAL_LEAVE_COMMON_VIEW",
                    "common_entry_ids": [
                        str(entry_id) for entry_id in common_leave[user.id].entry_ids
                    ],
                }
                for user in department_users
                if user.id in excluded_on_leave
            ],
        }
        department_result.total_bonus = None
        department_result.average_bonus = None
    if period.status == RealizationPeriodStatus.OPEN.value:
        transition_period(period, RealizationPeriodStatus.CALCULATED, actor_id=actor_id)
    else:
        period.calculated_at = datetime.now(timezone.utc)
    await db.flush()
    return results, department_result
