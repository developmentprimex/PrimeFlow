from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.department import Department
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.models.enums import (
    RealizationDailyCloseAction,
    RealizationLevel,
    RealizationMarker,
    RealizationObservationCategory,
    RealizationObservationVisibility,
    RealizationPeriodType,
    RealizationPeriodStatus,
    RealizationScopeType,
    RealizationSymbol,
    RealizationOperatingMode,
    RealizationPulse,
    UserRole,
)
from app.models.realization import (
    RealizationDailyApprovalEvent,
    RealizationDailyCloseEvent,
    RealizationDailyPersonComment,
    RealizationDepartmentResult,
    RealizationObservation,
    RealizationPeriod,
    RealizationPersonResult,
    RealizationQuestionAnswer,
)
from app.models.system_task_template import SystemTaskTemplate
from app.models.task import Task
from app.models.task_user_comment import TaskUserComment
from app.services.daily_rlz_compliance import (
    build_daily_rlz_compliance,
    closable_from,
    is_closable_day,
)
from app.models.user import User
from app.models.weekly_planner_snapshot import WeeklyPlannerSnapshot
from app.schemas.realization import (
    RealizationDepartmentResultOut,
    RealizationAIAnalysisOut,
    RealizationDailyOut,
    RealizationDailyPersonCommentOut,
    RealizationDailyPersonCommentUpsert,
    RealizationDailyApprovalOut,
    RealizationDailyApprovalRequest,
    RealizationDailyApprovalRevokeRequest,
    RealizationDailyCloseEventOut,
    RealizationDailyCloseRequest,
    RealizationDailyReopenRequest,
    DailyPlanAdjustmentDecision,
    RealizationObservationCreate,
    RealizationObservationOut,
    RealizationObservationVerify,
    RealizationObservationVoid,
    RealizationManagerReviewOut,
    RealizationManagerReviewUpsert,
    RealizationPeriodOut,
    RealizationPersonResultOut,
    RealizationPersonWorkflowOut,
    RealizationReviewRequest,
    RealizationQuestionAnswerCreate,
    RealizationQuestionAnswerOut,
    RealizationMonthlyOut,
    RealizationMonthlyPersonOut,
    RealizationWeeklyOut,
)
from app.schemas.weekly_planner_snapshot import WeeklySnapshotType
from app.services.audit import add_audit_log
from app.services.daily_realization_approval import (
    approval_state_from_events,
    latest_daily_approval,
    latest_daily_close,
)
from app.services.daily_realization_baseline import ensure_daily_baseline
from app.services.daily_realization_live import build_live_daily_realization, local_day
from app.services.realization_access import (
    can_approve_realization,
    can_lock_realization,
    can_review_realization,
    can_view_observation,
    can_view_person_result,
)
from app.services.realization_calculator import (
    MANDATORY_MANUAL_QUESTION_KEYS,
    MANUAL_BOOLEAN_QUESTION_KEYS,
    MANUAL_TEXT_QUESTION_KEYS,
    build_daily_questions_from_live,
    build_live_questions,
    calculate_weekly_period,
)
from app.services.realization_ai import (
    RealizationAIError,
    analyze_realization,
    mark_analysis_stale,
    record_analysis_state,
)
from app.services.realization_checklist import apply_checklist_answers
from app.services.realization_weekly_summary import suggest_weekly_level
from app.services.realization_daily import (
    _daily_classification,
    _local_date,
    _system_task_operational_day,
    calculate_daily_period,
)
from app.services.realization_evidence import _snapshot_tasks
from app.services.realization_excel import build_realization_workbook
from app.services.realization_weekly_metrics import (
    build_weekly_question_metrics,
    build_weekly_task_metrics,
)
from app.services.realization_periods import (
    RealizationWorkflowError,
    ensure_daily_period,
    ensure_weekly_period,
    ensure_weekly_scope_period,
    find_weekly_scope_period,
    normalize_week_start,
    require_unlocked,
    transition_period,
    weekly_end,
)
from app.services.realization_people import (
    availability_status_from_days,
    full_period_availability_statuses,
    is_realization_excluded_user,
    load_active_users_and_common_leave,
)
from app.services.realization_manager_review import (
    M3_MANAGER_REVIEW_DIMENSIONS,
    M3_MANAGER_REVIEW_SOURCE,
    build_manager_review_response,
    clear_manager_review,
    upsert_manager_review,
)
from app.services.realization_pulse import aggregate_monthly_pulses
from app.services.system_task_schedule import _is_working_day


router = APIRouter()


async def _latest_question_answers(
    db: AsyncSession, result_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, RealizationQuestionAnswer]]:
    if not result_ids:
        return {}
    rows = (
        await db.execute(
            select(RealizationQuestionAnswer)
            .where(RealizationQuestionAnswer.result_id.in_(result_ids))
            .order_by(
                RealizationQuestionAnswer.answered_at.asc(),
                RealizationQuestionAnswer.id.asc(),
            )
        )
    ).scalars().all()
    latest: dict[uuid.UUID, dict[str, RealizationQuestionAnswer]] = {}
    for row in rows:
        result_answers = latest.setdefault(row.result_id, {})
        if (row.value_json or {}).get("cleared") is True:
            result_answers.pop(row.question_key, None)
        else:
            result_answers[row.question_key] = row
    return latest


def _answer_payload(row: RealizationQuestionAnswer, name: str | None = None) -> dict:
    from app.services.realization_proposal_diamonds import proposal_diamond_score
    stored = row.value_json or {}
    return {
        "id": str(row.id),
        "value": stored.get("value"),
        "comment": row.comment,
        "diamond_score": proposal_diamond_score(row),
        "evidence_ids": [str(item) for item in (row.evidence_ids_json or [])],
        "answered_by": str(row.answered_by),
        "answered_by_name": name,
        "answered_at": row.answered_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "supersedes_answer_id": str(row.supersedes_answer_id) if row.supersedes_answer_id else None,
    }


async def _weekly_manual_answers(
    db: AsyncSession, *, period: RealizationPeriod, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, RealizationQuestionAnswer]]:
    """Read the opened period; historical weekly answers remain weekly."""
    if not user_ids:
        return {}
    weekly_period = period if period.period_type == "DAILY" else await find_weekly_scope_period(db, period=period)
    if weekly_period is None:
        return {}
    weekly_results = (await db.execute(
        select(RealizationPersonResult).where(
            RealizationPersonResult.period_id == weekly_period.id,
            RealizationPersonResult.user_id.in_(user_ids),
        )
    )).scalars().all()
    answers = await _latest_question_answers(db, [row.id for row in weekly_results])
    return {row.user_id: answers.get(row.id, {}) for row in weekly_results}


async def _weekly_answer_target(
    db: AsyncSession,
    *,
    period: RealizationPeriod,
    result: RealizationPersonResult,
    actor_id: uuid.UUID,
) -> tuple[RealizationPeriod, RealizationPersonResult]:
    """Keep daily answers dated, while honoring a locked parent week."""
    weekly_period = await ensure_weekly_scope_period(db, period=period, created_by=actor_id)
    require_unlocked(weekly_period)
    if period.period_type == "DAILY":
        return period, result
    if weekly_period.id == period.id and result.period_id == period.id:
        return period, result
    weekly_result = (await db.execute(
        select(RealizationPersonResult).where(
            RealizationPersonResult.period_id == weekly_period.id,
            RealizationPersonResult.user_id == result.user_id,
        )
    )).scalar_one_or_none()
    if weekly_result is None:
        weekly_result = RealizationPersonResult(
            period_id=weekly_period.id,
            user_id=result.user_id,
            department_id=result.department_id or weekly_period.department_id,
        )
        db.add(weekly_result)
        await db.flush()
    return weekly_period, weekly_result


async def _attach_weekly_daily_evidence(db, *, period, daily_by_user, user_ids):
    """Batch-load dated personal comments and latest answers, scoped to this week."""
    if not user_ids:
        return
    scope = (
        RealizationPeriod.period_type == "DAILY",
        RealizationPeriod.slot == "ALL",
        RealizationPeriod.department_id == period.department_id,
        RealizationPeriod.start_date >= period.start_date,
        RealizationPeriod.end_date <= period.end_date,
    )
    results = (await db.execute(
        select(RealizationPersonResult, RealizationPeriod)
        .join(RealizationPeriod, RealizationPersonResult.period_id == RealizationPeriod.id)
        .where(*scope, RealizationPersonResult.user_id.in_(user_ids))
    )).all()
    answers = await _latest_question_answers(db, [row.id for row, _ in results])
    comments = (await db.execute(
        select(RealizationDailyPersonComment, RealizationPeriod)
        .join(RealizationPeriod, RealizationDailyPersonComment.period_id == RealizationPeriod.id)
        .where(*scope, RealizationDailyPersonComment.user_id.in_(user_ids))
    )).all()
    actor_ids = {a.answered_by for items in answers.values() for a in items.values()}
    actor_ids.update(c.updated_by for c, _ in comments if c.updated_by)
    names = {u.id: u.full_name for u in (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()} if actor_ids else {}

    def day_item(user_id, day_period):
        timeline = daily_by_user.setdefault(user_id, [])
        item = next((d for d in timeline if d["date"] == day_period.start_date.isoformat()), None)
        if item is None:
            item = _empty_timeline_day(day_period.start_date.isoformat())
            item["daily_progress_percent"] = None
            timeline.append(item)
        item["period_id"] = str(day_period.id)
        return item

    for row, day_period in results:
        item = day_item(row.user_id, day_period)
        item["manual_answers"] = {key: _answer_payload(answer, names.get(answer.answered_by)) for key, answer in answers.get(row.id, {}).items()}
    for comment, day_period in comments:
        if comment.comment:
            day_item(comment.user_id, day_period)["person_comment"] = {
                "comment": comment.comment, "author": names.get(comment.updated_by),
                "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
            }
    today = datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date().isoformat()
    for timeline in daily_by_user.values():
        for item in timeline:
            item["future"] = item["date"] > today
            if item.get("future") or item.get("on_leave") or not item.get("has_live_metrics"):
                item["daily_progress_percent"] = None
        timeline.sort(key=lambda item: item["date"])


def _can_capture_current_week_final(period: RealizationPeriod, *, today: date | None = None) -> bool:
    local_today = today or datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()
    return (
        period.final_snapshot_id is None
        and normalize_week_start(local_today) == period.start_date
        and local_today >= period.end_date
    )


def _error(exc: ValueError, code: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


def _ensure_department_scope(user: User, department_id: uuid.UUID) -> None:
    if user.role in {UserRole.ADMIN, UserRole.MANAGER}:
        return
    if user.role not in (UserRole.MANAGER, UserRole.STAFF) or user.department_id != department_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def _period(
    db: AsyncSession, period_id: uuid.UUID, *, for_update: bool = False
) -> RealizationPeriod:
    statement = select(RealizationPeriod).where(RealizationPeriod.id == period_id)
    if for_update:
        statement = statement.with_for_update()
    row = (
        await db.execute(statement)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Realization period not found")
    return row


async def _pinned_snapshots(
    db: AsyncSession, period: RealizationPeriod
) -> tuple[WeeklyPlannerSnapshot | None, WeeklyPlannerSnapshot | None]:
    ids = [item for item in (period.planned_snapshot_id, period.final_snapshot_id) if item]
    rows = (
        (
            await db.execute(
                select(WeeklyPlannerSnapshot).where(WeeklyPlannerSnapshot.id.in_(ids))
            )
        ).scalars().all()
        if ids
        else []
    )
    by_id = {row.id: row for row in rows}
    return by_id.get(period.planned_snapshot_id), by_id.get(period.final_snapshot_id)


async def _recalculate_after_evidence(
    db: AsyncSession, *, period: RealizationPeriod, actor_id: uuid.UUID
) -> None:
    """Keep automatic answers and grades synchronized with manager evidence."""
    if period.period_type != "WEEKLY" or period.status not in {
        RealizationPeriodStatus.OPEN.value,
        RealizationPeriodStatus.CALCULATED.value,
    }:
        return
    planned, final = await _pinned_snapshots(db, period)
    if planned is None or final is None:
        return
    # calculate_weekly_period leaves already-reviewed people's results
    # untouched and recalculates everyone else — so this can always run
    # while the period is OPEN/CALCULATED (the outer guard above already
    # stops once every person has been reviewed and the period moves to
    # REVIEWED).
    await calculate_weekly_period(
        db,
        period=period,
        planned_snapshot=planned,
        final_snapshot=final,
        actor_id=actor_id,
    )


async def _mark_ai_stale_for_subject(
    db: AsyncSession, *, period_id: uuid.UUID, user_id: uuid.UUID | None
) -> None:
    if user_id is None:
        return
    result = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.period_id == period_id,
                RealizationPersonResult.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if result is not None and result.ai_generated_at is not None:
        mark_analysis_stale(result)


def _visible_facts(user: User, result: RealizationPersonResult) -> dict:
    facts = dict(result.facts_json or {})
    if user.role != UserRole.STAFF:
        return facts
    facts["observations"] = [
        item
        for item in facts.get("observations") or []
        if item.get("visibility") != RealizationObservationVisibility.PRIVATE_MANAGER.value
    ]
    questions = []
    for question in facts.get("questions") or []:
        item = dict(question)
        if item.get("key") == "comments":
            for value_key in ("auto_value", "final_value"):
                value = item.get(value_key)
                if isinstance(value, dict):
                    value = dict(value)
                    value["manager_comment"] = None
                    value["override_reason"] = None
                    item[value_key] = value
        questions.append(item)
    facts["questions"] = questions
    return facts


def _timeline_task_identity(task: dict) -> str | None:
    task_id = task.get("task_id")
    if task_id:
        return f"id:{task_id}"
    match_key = str(task.get("match_key") or "").strip()
    return match_key or None


def _dedupe_timeline_tasks(tasks: list[dict]) -> list[dict]:
    """Collapse duplicate snapshot occurrences without merging distinct tasks."""
    unique: dict[str, dict] = {}
    anonymous: list[dict] = []
    for task in tasks:
        identity = _timeline_task_identity(task)
        if identity is None:
            anonymous.append(task)
            continue
        previous = unique.get(identity)
        if previous is None:
            unique[identity] = task
            continue
        # Later live/daily facts carry current status, progress and comments.
        # Retain any earlier non-empty metadata that is absent from that fact.
        unique[identity] = {
            **previous,
            **{key: value for key, value in task.items() if value is not None},
        }
    return [*unique.values(), *anonymous]


def _merge_daily_report_task_evidence(
    tasks: list[dict], evidence_tasks: list[dict]
) -> None:
    """Attach the saved Daily Report reason/comment to timeline task cards."""
    evidence_by_task_id = {
        str(item["task_id"]): item
        for item in evidence_tasks
        if item.get("task_id")
    }
    for task in tasks:
        task_id = task.get("task_id")
        evidence = evidence_by_task_id.get(str(task_id)) if task_id else None
        if evidence is None:
            continue
        task["reason_code"] = evidence.get("reason_code")
        task["reason_label"] = evidence.get("reason_label")
        task["daily_report_comment"] = evidence.get("comment")
        if evidence.get("comment") is not None:
            task["user_comment"] = evidence.get("comment")


def _merge_daily_report_timeline_evidence(
    daily_by_user: dict[uuid.UUID, list[dict]],
    evidence_by_user_day: dict[tuple[uuid.UUID, str], list[dict]],
) -> None:
    """Merge evidence after PLANNED/live task lists have been fully assembled."""
    for user_id, timeline in daily_by_user.items():
        for item in timeline:
            _merge_daily_report_task_evidence(
                item.get("tasks") or [],
                evidence_by_user_day.get((user_id, item["date"]), []),
            )


def _append_timeline_attendance(
    item: dict, *, day_key: str, attendance_type: str, source: str
) -> None:
    attendance = [
        entry for entry in (item.get("attendance") or []) if isinstance(entry, dict)
    ]
    if any(
        str(entry.get("type") or "").upper() == attendance_type
        for entry in attendance
    ):
        item["attendance"] = attendance
        return
    attendance.append({
        "date": day_key,
        "type": attendance_type,
        "source": source,
    })
    item["attendance"] = attendance


def _empty_timeline_day(day_key: str) -> dict:
    return {
        "date": day_key,
        "has_snapshot": False,
        "daily_progress_percent": 0,
        "weekly_progress_percent": 0,
        "planned_count": 0,
        "completed_count": 0,
        "weekly_planned_count": 0,
        "weekly_completed_count": 0,
        "additional_count": 0,
        "attendance": [],
        "tasks": [],
    }


def _away_person_result(
    period: RealizationPeriod, *, user_id: uuid.UUID, status: str | None
) -> RealizationPersonResult:
    """A presentation-only row for someone absent the whole period.

    It is never added to the session: there is nothing to calculate for a week
    somebody did not work, only something to state.
    """
    now = datetime.now(timezone.utc)
    row = RealizationPersonResult(
        id=uuid.uuid4(),
        period_id=period.id,
        user_id=user_id,
        department_id=period.department_id,
        facts_json={"availability_status": status},
        created_at=now,
        updated_at=now,
        ai_analysis_stale=True,
    )
    # The counters carry a server default, so an unflushed row leaves them unset
    # and the response schema would reject them.
    for column in RealizationPersonResult.__table__.columns:
        if getattr(row, column.name, None) is not None:
            continue
        try:
            is_count = column.type.python_type is int
        except NotImplementedError:
            is_count = False
        if is_count:
            setattr(row, column.name, 0)
    return row


def _task_uuid(task: dict) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(task.get("task_id")))
    except (TypeError, ValueError):
        return None


async def _task_creation_days(
    db: AsyncSession, tasks: Iterable[dict]
) -> dict[uuid.UUID, date]:
    task_ids = {task_id for task_id in map(_task_uuid, tasks) if task_id is not None}
    if not task_ids:
        return {}
    rows = (
        await db.execute(select(Task.id, Task.created_at).where(Task.id.in_(task_ids)))
    ).all()
    return {
        row.id: created
        for row in rows
        if (created := local_day(row.created_at)) is not None
    }


def _apply_creation_days(tasks: Iterable[dict], created_days: dict[uuid.UUID, date]) -> None:
    for task in tasks:
        task_id = _task_uuid(task)
        created = created_days.get(task_id) if task_id else None
        if created is not None:
            task["created_date"] = created.isoformat()


def _timeline_task_belongs_on_day(
    task: dict, day: date, system_task_days: dict[str, date]
) -> bool:
    if task.get("source_type") != "system" or not task.get("task_id"):
        return True
    operational_day = system_task_days.get(str(task["task_id"]))
    return operational_day is None or operational_day == day


async def _weekly_response(
    db: AsyncSession,
    *,
    period: RealizationPeriod,
    user: User,
    department_name: str | None,
) -> RealizationWeeklyOut:
    from app.api.routers.task_reviews import review_overview
    from app.services.realization_weekly_diamonds import empty_weekly_diamonds, group_weekly_diamonds
    raw_rows = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.period_id == period.id
            )
        )
    ).scalars().all()
    active_users, common_leave = await load_active_users_and_common_leave(
        db,
        department_id=period.department_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    active_user_ids = {active_user.id for active_user in active_users}
    working_days: set[date] = set()
    current_day = period.start_date
    while current_day <= period.end_date:
        if _is_working_day(current_day):
            working_days.add(current_day)
        current_day += timedelta(days=1)
    eligible_user_ids = active_user_ids
    if user.role == UserRole.STAFF:
        eligible_user_ids &= {user.id}
    rows = [row for row in raw_rows if row.user_id in eligible_user_ids]
    visible = [
        row
        for row in rows
        if can_view_person_result(
            user,
            subject_user_id=row.user_id,
            subject_department_id=row.department_id,
        )
    ]
    names = {
        row.id: row.full_name
        for row in (
            await db.execute(
                select(User).where(User.id.in_([item.user_id for item in visible]))
            )
        ).scalars().all()
    } if visible else {}
    active_observations = (
        await db.execute(
            select(RealizationObservation).where(
                RealizationObservation.period_id == period.id,
                RealizationObservation.voided_at.is_(None),
            )
        )
    ).scalars().all()
    verified_ids: set[uuid.UUID] = set()
    for observation in active_observations:
        evidence = observation.evidence_json or {}
        if (
            observation.source_type == "realization_observation_verification"
            and evidence.get("verified") is True
        ):
            try:
                verified_ids.add(
                    uuid.UUID(str(evidence.get("verification_of") or observation.source_id))
                )
            except (TypeError, ValueError):
                pass
    live_by_user: dict[uuid.UUID, list[dict]] = {}
    for observation in active_observations:
        if (
            observation.source_type == "realization_observation_verification"
            or observation.source_type == M3_MANAGER_REVIEW_SOURCE
            or observation.user_id is None
        ):
            continue
        visibility = RealizationObservationVisibility(observation.visibility)
        if not can_view_observation(
            user,
            subject_user_id=observation.user_id,
            department_id=observation.department_id or period.department_id,
            visibility=visibility,
        ):
            continue
        live_by_user.setdefault(observation.user_id, []).append(
            {
                "id": str(observation.id),
                "marker": observation.marker,
                "category": observation.category,
                "comment": observation.comment,
                "task_id": str(observation.task_id) if observation.task_id else None,
                "user_id": str(observation.user_id) if observation.user_id else None,
                "project_id": str(observation.project_id) if observation.project_id else None,
                "impact_minutes": observation.impact_minutes,
                "repeat_count": observation.repeat_count_at_creation,
                "evidence_json": observation.evidence_json or {},
                "source_type": observation.source_type,
                "created_at": observation.created_at.isoformat(),
                "relevant_date": (observation.evidence_json or {}).get("date")
                or (observation.evidence_json or {}).get("occurrence_date"),
                "verified": observation.id in verified_ids
                or (
                    observation.is_system_generated
                    and (observation.evidence_json or {}).get("verified") is True
                ),
                "visibility": observation.visibility,
            }
        )
    daily_rows = (
        await db.execute(
            select(RealizationPersonResult, RealizationPeriod)
            .join(RealizationPeriod, RealizationPeriod.id == RealizationPersonResult.period_id)
            .where(
                RealizationPeriod.period_type == "DAILY",
                RealizationPeriod.department_id == period.department_id,
                RealizationPeriod.start_date >= period.start_date,
                RealizationPeriod.end_date <= period.end_date,
            )
            .order_by(RealizationPeriod.start_date.asc())
        )
    ).all()
    # Weekly rows can be sparse while the week is open: answering one person's
    # weekly question creates only that person's weekly result. Merge the latest
    # calculated daily row for every other eligible person so a partial weekly
    # result set cannot hide the rest of the department.
    latest_by_user: dict[uuid.UUID, tuple[RealizationPersonResult, RealizationPeriod]] = {}
    for daily_result, daily_period in daily_rows:
        latest_by_user[daily_result.user_id] = (daily_result, daily_period)
    visible_user_ids = {row.user_id for row in visible}
    comment_user_ids = (await db.execute(
        select(RealizationDailyPersonComment.user_id).join(
            RealizationPeriod, RealizationPeriod.id == RealizationDailyPersonComment.period_id
        ).where(
            RealizationPeriod.period_type == "DAILY",
            RealizationPeriod.department_id == period.department_id,
            RealizationPeriod.start_date >= period.start_date,
            RealizationPeriod.end_date <= period.end_date,
            RealizationDailyPersonComment.comment.is_not(None),
        ).distinct()
    )).scalars().all()
    for person_id in comment_user_ids:
        if person_id in eligible_user_ids and person_id not in visible_user_ids and person_id not in latest_by_user:
            visible.append(_away_person_result(period, user_id=person_id, status=None))
            visible_user_ids.add(person_id)
    for person_id, (daily_result, _) in latest_by_user.items():
        if person_id in visible_user_ids or person_id not in eligible_user_ids:
            continue
        if not can_view_person_result(
            user,
            subject_user_id=daily_result.user_id,
            subject_department_id=daily_result.department_id,
        ):
            continue
        visible.append(daily_result)
        visible_user_ids.add(person_id)
    # Awards can exist before any weekly/daily task result has been prepared.
    diamond_overview = await review_overview(
        date_from=period.start_date, date_to=period.end_date,
        department_id=period.department_id,
        reviewee_user_id=user.id if user.role == UserRole.STAFF else None,
        review_status="reviewed", db=db, current_user=user,
    )
    diamonds_by_user = group_weekly_diamonds(diamond_overview.rows)
    for person_id in diamonds_by_user:
        if person_id in eligible_user_ids and person_id not in visible_user_ids:
            visible.append(_away_person_result(period, user_id=person_id, status=None))
            visible_user_ids.add(person_id)
    # Somebody on leave for the whole week has neither a weekly nor a daily
    # result, so the week has to say they were away, not that they did nothing.
    away_statuses = full_period_availability_statuses(
        common_leave, working_days=working_days
    )
    for person_id, status in away_statuses.items():
        if person_id in visible_user_ids or person_id not in eligible_user_ids:
            continue
        if not can_view_person_result(
            user,
            subject_user_id=person_id,
            subject_department_id=period.department_id,
        ):
            continue
        visible.append(_away_person_result(period, user_id=person_id, status=status))
        visible_user_ids.add(person_id)
    names = {
        row.id: row.full_name
        for row in (
            await db.execute(
                select(User).where(User.id.in_([item.user_id for item in visible]))
            )
        ).scalars().all()
    } if visible else {}
    daily_by_user: dict[uuid.UUID, list[dict]] = {}
    daily_tasks_by_user: dict[uuid.UUID, dict[str, dict]] = {}
    weekly_completed_tasks_by_user: dict[uuid.UUID, list[dict]] = {}
    for daily_result, daily_period in daily_rows:
        daily_facts = daily_result.facts_json or {}
        daily_counters = daily_facts.get("counters") or {}
        weekly_completed_tasks_by_user[daily_result.user_id] = [
            dict(task) for task in daily_facts.get("weekly_completed_tasks") or []
        ]
        day_tasks = [dict(task) for task in daily_facts.get("tasks") or []]
        daily_by_user.setdefault(daily_result.user_id, []).append(
            {
                "date": daily_period.start_date.isoformat(),
                "period_id": str(daily_period.id),
                "result_id": str(daily_result.id),
                "has_snapshot": True,
                "daily_progress_percent": daily_facts.get("daily_progress_percent", 0),
                "weekly_progress_percent": daily_facts.get("weekly_progress_percent", 0),
                "planned_count": daily_facts.get(
                    "daily_planned_count", daily_result.planned_count
                ),
                "completed_count": daily_facts.get(
                    "daily_completed_count", daily_result.completed_on_time_count
                ),
                "weekly_planned_count": daily_facts.get("weekly_planned_count", 0),
                "weekly_completed_count": daily_facts.get("weekly_completed_count", 0),
                "additional_count": daily_result.additional_count,
                "in_progress_count": daily_facts.get(
                    "in_progress_count", daily_result.in_progress_count
                ),
                "no_progress_count": daily_facts.get(
                    "no_progress_count", daily_result.no_progress_count
                ),
                "pending_count": daily_facts.get(
                    "pending_count", daily_result.pending_count
                ),
                "fast_task_count": daily_counters.get("fast_task_count", 0),
                "attendance": daily_facts.get("attendance") or [],
                "tasks": day_tasks,
                "pulse": daily_facts.get("pulse"),
                "recovery": daily_facts.get("recovery"),
            }
        )
        for task in day_tasks:
            task_key = str(task.get("task_id") or task.get("match_key") or "")
            if task_key:
                daily_tasks_by_user.setdefault(daily_result.user_id, {})[task_key] = task

    # A daily snapshot freezes only what was known the moment the day was
    # calculated, so extras, deadlines and quantities registered afterwards
    # never reach the week. Re-read every working day live so the week
    # classifies exactly the obligations the daily view shows.
    live_user_ids = {row.user_id for row in visible}
    live_availability: dict[uuid.UUID, dict[date, str]] = {}
    if period.department_id is not None:
        for current_day in sorted(working_days):
            day_key = current_day.isoformat()
            live_day = await build_live_daily_realization(
                db, department_id=period.department_id, day=current_day
            )
            for person in live_day.get("people") or []:
                try:
                    person_id = uuid.UUID(str(person.get("user_id")))
                except (TypeError, ValueError):
                    continue
                live_status = person.get("availability_status")
                if live_status:
                    live_availability.setdefault(person_id, {})[current_day] = str(live_status)
                    continue
                live_tasks = [dict(task) for task in person.get("tasks") or []]
                if person_id not in live_user_ids:
                    continue
                timeline = daily_by_user.setdefault(person_id, [])
                item = next(
                    (entry for entry in timeline if entry["date"] == day_key), None
                )
                if item is None:
                    item = {
                        "date": day_key,
                        "has_snapshot": False,
                        "daily_progress_percent": 0,
                        "weekly_progress_percent": 0,
                        "planned_count": 0,
                        "completed_count": 0,
                        "weekly_planned_count": 0,
                        "weekly_completed_count": 0,
                        "additional_count": 0,
                        "attendance": [],
                        "tasks": [],
                    }
                    timeline.append(item)
                metrics = person.get("metrics") or {}
                item["has_live_metrics"] = True
                item["daily_progress_percent"] = metrics.get("raw_plan_realization")
                item["planned_count"] = int(metrics.get("original_planned_count") or 0)
                item["completed_count"] = int(metrics.get("total_completed_today_count") or 0)
                item["additional_count"] = int(metrics.get("additional_count") or 0)
                item["tasks"] = _dedupe_timeline_tasks(
                    [*(item.get("tasks") or []), *live_tasks]
                )
                for task in live_tasks:
                    task_key = str(task.get("task_id") or task.get("match_key") or "")
                    if task_key:
                        daily_tasks_by_user.setdefault(person_id, {})[task_key] = task
    for person_id, by_day in live_availability.items():
        live_status = availability_status_from_days(by_day, working_days=working_days)
        if live_status:
            away_statuses[person_id] = live_status
    for person_id, status in away_statuses.items():
        if person_id in visible_user_ids or person_id not in eligible_user_ids:
            continue
        if not can_view_person_result(
            user,
            subject_user_id=person_id,
            subject_department_id=period.department_id,
        ):
            continue
        visible.append(_away_person_result(period, user_id=person_id, status=status))
        visible_user_ids.add(person_id)
    missing_name_ids = [item.user_id for item in visible if item.user_id not in names]
    if missing_name_ids:
        names.update(
            {
                row.id: row.full_name
                for row in (
                    await db.execute(select(User).where(User.id.in_(missing_name_ids)))
                ).scalars().all()
            }
        )

    close_events = (
        (
            await db.execute(
                select(RealizationDailyCloseEvent, RealizationPeriod)
                .join(RealizationPeriod, RealizationPeriod.id == RealizationDailyCloseEvent.period_id)
                .where(
                    RealizationDailyCloseEvent.user_id.in_([row.user_id for row in visible]),
                    RealizationPeriod.period_type == "DAILY",
                    RealizationPeriod.start_date >= period.start_date,
                    RealizationPeriod.end_date <= period.end_date,
                )
                .order_by(
                    RealizationDailyCloseEvent.created_at.asc(),
                    RealizationDailyCloseEvent.id.asc(),
                )
            )
        ).all()
        if visible
        else []
    )

    approval_events = (
        (
            await db.execute(
                select(RealizationDailyApprovalEvent, RealizationPeriod)
                .join(RealizationPeriod, RealizationPeriod.id == RealizationDailyApprovalEvent.period_id)
                .where(
                    RealizationDailyApprovalEvent.user_id.in_([row.user_id for row in visible]),
                    RealizationPeriod.period_type == "DAILY",
                    RealizationPeriod.start_date >= period.start_date,
                    RealizationPeriod.end_date <= period.end_date,
                )
                .order_by(
                    RealizationDailyApprovalEvent.created_at.asc(),
                    RealizationDailyApprovalEvent.id.asc(),
                )
            )
        ).all()
        if visible
        else []
    )


    close_history: dict[tuple[uuid.UUID, str], list[dict]] = {}
    for close_event, close_period in close_events:
        key = (close_event.user_id, close_period.start_date.isoformat())
        close_history.setdefault(key, []).append(
            RealizationDailyCloseEventOut.model_validate(close_event).model_dump(mode="json")
        )
    approval_history: dict[tuple[uuid.UUID, str], list[dict]] = {}
    for approval_event, approval_period in approval_events:
        key = (approval_event.user_id, approval_period.start_date.isoformat())
        approval_history.setdefault(key, []).append({
            "id": str(approval_event.id),
            "action": approval_event.action,
            "source_close_event_id": str(approval_event.source_close_event_id) if approval_event.source_close_event_id else None,
            "approval_comment": approval_event.approval_comment,
            "reason": approval_event.reason,
            "actor_user_id": str(approval_event.actor_user_id),
            "created_at": approval_event.created_at.isoformat(),
        })
    today_local = datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date().isoformat()
    daily_report_evidence_by_user_day: dict[
        tuple[uuid.UUID, str], list[dict]
    ] = {}
    for user_id, timeline in daily_by_user.items():
        for item in timeline:
            history = close_history.get((user_id, item["date"]), [])
            latest = history[-1] if history else None
            latest_closed = next(
                (
                    event
                    for event in reversed(history)
                    if event.get("action") in {"CLOSE", "CORRECT"}
                ),
                None,
            )
            item["close_history"] = history
            item["close_state"] = (
                "CLOSED"
                if latest and latest["action"] in {"CLOSE", "CORRECT"}
                else "REOPENED"
                if latest and latest["action"] == "REOPEN"
                else "OPEN"
            )
            item["close_event"] = latest
            approvals = approval_history.get((user_id, item["date"]), [])
            latest_approval = approvals[-1] if approvals else None
            approval_status = (
                "PENDING"
                if latest_approval is None
                else "REVOKED"
                if latest_approval["action"] == "REVOKE"
                else "STALE"
                if not latest or latest_approval["source_close_event_id"] != str(latest["id"])
                else "APPROVED"
            )
            item["manager_approval"] = {
                "status": approval_status,
                **(latest_approval or {}),
            }
            current_state = None
            if item["date"] == today_local:
                current_state = await build_daily_rlz_compliance(
                    db, user_id=user_id, day=date.fromisoformat(item["date"])
                )
                item["manager_approval"] = current_state["manager_approval"]
            evidence_tasks = (
                current_state.get("tasks")
                if current_state is not None
                else (
                    ((latest_closed.get("facts_json") or {}).get("daily_report_state") or {}).get("tasks")
                    if latest_closed
                    else []
                )
            ) or []
            daily_report_evidence_by_user_day[(user_id, item["date"])] = evidence_tasks
            if (
                latest
                and item["close_state"] == "CLOSED"
                and latest.get("confirmed_pulse")
            ):
                suggested_pulse = (item.get("pulse") or {}).get("pulse")
                item["pulse"] = {
                    **(item.get("pulse") or {}),
                    "suggested_pulse": suggested_pulse,
                    "pulse": latest["confirmed_pulse"],
                    "confirmed": True,
                }

    planned_tasks_by_user_day: dict[uuid.UUID, dict[str, list[dict]]] = {}
    planned_snapshot: WeeklyPlannerSnapshot | None = None
    if period.planned_snapshot_id is not None:
        planned_snapshot = await db.get(WeeklyPlannerSnapshot, period.planned_snapshot_id)
        if planned_snapshot is not None:
            for task in _snapshot_tasks(planned_snapshot).values():
                occurrences = task.get("occurrences") or []
                if not occurrences and task.get("planned_due_date"):
                    occurrences = [
                        {
                            "day": task["planned_due_date"].date(),
                            "time_slot": task.get("finish_period"),
                            "assignee_id": None,
                        }
                    ]
                for assignee in task.get("assignees") or []:
                    user_id = assignee.get("assignee_id")
                    if user_id is None:
                        continue
                    for occurrence in occurrences:
                        occurrence_day = occurrence.get("day")
                        occurrence_user_id = occurrence.get("assignee_id")
                        if (
                            occurrence_day is None
                            or occurrence_day < period.start_date
                            or occurrence_day > period.end_date
                            or occurrence_user_id not in {None, user_id}
                        ):
                            continue
                        fact = {
                            "match_key": task["match_key"],
                            "task_id": str(task["task_id"]) if task.get("task_id") else None,
                            "title": task["title"],
                            "project_id": str(task["project_id"]) if task.get("project_id") else None,
                            "project_title": task.get("project_title"),
                            "source_type": task.get("source_type") or "project",
                            "classification": "planned",
                            "status": task.get("status") or "TODO",
                            "daily_progress": [],
                            "attribution": "planned_today",
                            "planned_occurrences": [
                                {
                                    "day": occurrence_day.isoformat(),
                                    "time_slot": occurrence.get("time_slot"),
                                    "assignee_id": str(user_id),
                                }
                            ],
                        }
                        day_key = occurrence_day.isoformat()
                        day_tasks = planned_tasks_by_user_day.setdefault(user_id, {}).setdefault(
                            day_key, []
                        )
                        if not any(
                            _timeline_task_identity(existing)
                            == _timeline_task_identity(fact)
                            for existing in day_tasks
                        ):
                            day_tasks.append(fact)

    # Add generated system-task occurrences that are explicitly opted into the
    # Weekly Planner. Realization follows the same visibility contract.
    system_tasks_by_user_day: dict[uuid.UUID, dict[str, list[dict]]] = {}
    system_task_day_by_id: dict[str, date] = {}
    visible_user_ids = [row.user_id for row in visible]
    if visible_user_ids:
        range_start = datetime.combine(
            period.start_date - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
        )
        range_end = datetime.combine(
            period.end_date + timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc
        )
        # Generated occurrences often share a Friday deadline. Their operational
        # day is the actual origin/start run; due_date is only a fallback.
        effective_system_date = func.coalesce(
            Task.origin_run_at, Task.start_date, Task.created_at, Task.due_date
        )
        system_task_rows = (
            await db.execute(
                select(Task)
                .join(
                    SystemTaskTemplate,
                    Task.system_template_origin_id == SystemTaskTemplate.id,
                )
                .where(
                    Task.assigned_to.in_(visible_user_ids),
                    Task.system_template_origin_id.is_not(None),
                    Task.is_active.is_(True),
                    SystemTaskTemplate.show_in_weekly_planner.is_(True),
                    effective_system_date >= range_start,
                    effective_system_date < range_end,
                )
            )
        ).scalars().all()
        for system_task in system_task_rows:
            if system_task.assigned_to is None:
                continue
            task_day = _system_task_operational_day(system_task)
            if (
                task_day is None
                or task_day < period.start_date
                or task_day > period.end_date
                or not _is_working_day(task_day)
            ):
                continue
            system_task_day_by_id[str(system_task.id)] = task_day
            system_fact = {
                "match_key": f"id:{system_task.id}",
                "task_id": str(system_task.id),
                "title": system_task.title,
                "project_id": None,
                "project_title": None,
                "source_type": "system",
                "classification": _daily_classification(system_task, None, task_day),
                "status": system_task.status,
                "daily_progress": [],
                "attribution": "system_schedule",
            }
            system_tasks_by_user_day.setdefault(system_task.assigned_to, {}).setdefault(
                task_day.isoformat(), []
            ).append(system_fact)
            daily_tasks_by_user.setdefault(system_task.assigned_to, {})[
                str(system_task.id)
            ] = system_fact

    for row in visible:
        timeline = daily_by_user.setdefault(row.user_id, [])
        timeline_by_date = {item["date"]: item for item in timeline}
        coverage = common_leave.get(row.user_id)
        pv_days = set(coverage.days) if coverage else set()
        absence_days = set(coverage.absence_days) if coverage else set()
        full_day_absence_days = set(coverage.full_day_absence_days) if coverage else set()
        delay_days = set(coverage.delay_days) if coverage else set()
        for live_day, live_status in live_availability.get(row.user_id, {}).items():
            status = str(live_status).upper()
            if status == "PV":
                pv_days.add(live_day)
            elif status == "MUNGESE":
                absence_days.add(live_day)
                full_day_absence_days.add(live_day)
        current_day = period.start_date
        while current_day <= period.end_date:
            if _is_working_day(current_day):
                day_key = current_day.isoformat()
                planned_tasks = planned_tasks_by_user_day.get(row.user_id, {}).get(day_key, [])
                scheduled_system_tasks = system_tasks_by_user_day.get(row.user_id, {}).get(day_key, [])
                item = timeline_by_date.get(day_key)
                if current_day in pv_days:
                    if item is None:
                        item = _empty_timeline_day(day_key)
                        timeline.append(item)
                        timeline_by_date[day_key] = item
                    item["planned_count"] = 0
                    item["completed_count"] = 0
                    item["daily_progress_percent"] = 0
                    item["tasks"] = []
                    item["on_leave"] = True
                    _append_timeline_attendance(
                        item,
                        day_key=day_key,
                        attendance_type="PUSHIM_VJETOR",
                        source="common_leave",
                    )
                    current_day += timedelta(days=1)
                    continue
                if current_day in full_day_absence_days:
                    if item is None:
                        item = _empty_timeline_day(day_key)
                        timeline.append(item)
                        timeline_by_date[day_key] = item
                    item["planned_count"] = 0
                    item["completed_count"] = 0
                    item["daily_progress_percent"] = 0
                    item["tasks"] = []
                    _append_timeline_attendance(
                        item,
                        day_key=day_key,
                        attendance_type="MUNGESE",
                        source="common_view",
                    )
                    if current_day in delay_days:
                        _append_timeline_attendance(
                            item,
                            day_key=day_key,
                            attendance_type="VONESE",
                            source="common_view",
                        )
                    current_day += timedelta(days=1)
                    continue
                if item is None:
                    tasks_by_key = {
                        str(task.get("task_id") or task.get("match_key") or ""): task
                        for task in [*planned_tasks, *scheduled_system_tasks]
                    }
                    item = {
                        "date": day_key,
                        "has_snapshot": False,
                        "daily_progress_percent": 0,
                        "weekly_progress_percent": 0,
                        "planned_count": len(planned_tasks),
                        "completed_count": 0,
                        "weekly_planned_count": 0,
                        "weekly_completed_count": 0,
                        "additional_count": 0,
                        "attendance": [],
                        "tasks": list(tasks_by_key.values()),
                    }
                    timeline.append(item)
                    timeline_by_date[day_key] = item
                else:
                    actual_tasks = [
                        task
                        for task in (item.get("tasks") or [])
                        if _timeline_task_belongs_on_day(
                            task, current_day, system_task_day_by_id
                        )
                    ]
                    actual_by_key = {
                        str(task.get("task_id") or task.get("match_key") or ""): task
                        for task in actual_tasks
                    }
                    merged_tasks = []
                    planned_keys: set[str] = set()
                    for planned_task in planned_tasks:
                        task_key = str(
                            planned_task.get("task_id") or planned_task.get("match_key") or ""
                        )
                        planned_keys.add(task_key)
                        merged_tasks.append({**planned_task, **actual_by_key.get(task_key, {})})
                    merged_tasks.extend(
                        task
                        for task in actual_tasks
                        if str(task.get("task_id") or task.get("match_key") or "") not in planned_keys
                    )
                    merged_index_by_key = {
                        str(task.get("task_id") or task.get("match_key") or ""): index
                        for index, task in enumerate(merged_tasks)
                    }
                    for system_task in scheduled_system_tasks:
                        task_key = str(
                            system_task.get("task_id") or system_task.get("match_key") or ""
                        )
                        index = merged_index_by_key.get(task_key)
                        if index is None:
                            merged_tasks.append(system_task)
                            continue
                        # Live facts describe the execution, the schedule fact
                        # carries the planner attribution. Keep both.
                        merged_tasks[index] = {**system_task, **merged_tasks[index]}
                    item["tasks"] = _dedupe_timeline_tasks(merged_tasks)
                if current_day in absence_days:
                    _append_timeline_attendance(
                        item,
                        day_key=day_key,
                        attendance_type="MUNGESE",
                        source="common_view",
                    )
                if current_day in delay_days:
                    _append_timeline_attendance(
                        item,
                        day_key=day_key,
                        attendance_type="VONESE",
                        source="common_view",
                    )
            current_day += timedelta(days=1)
        timeline.sort(key=lambda item: item["date"])

        # The latest daily snapshot carries the cumulative list of every task
        # completed during the week. Merge each one into its actual completion
        # day so older tasks outside PLANNED remain visible without being
        # misreported as newly added work.
        timeline_by_date = {item["date"]: item for item in timeline}
        for completed_task in weekly_completed_tasks_by_user.get(row.user_id, []):
            completion_day = str(completed_task.get("completion_day") or "")
            target = timeline_by_date.get(completion_day)
            if target is None:
                continue
            task_key = str(
                completed_task.get("task_id")
                or completed_task.get("match_key")
                or ""
            )
            if not task_key:
                continue
            # A task's scheduled day (from due_date/origin_run_at/start_date)
            # can differ from the day it was actually completed. Without this,
            # the same task shows up twice — once as a "scheduled" ghost entry
            # on its due day and again here on its completion day.
            for other_day in timeline:
                if other_day["date"] == completion_day:
                    continue
                other_tasks = other_day.get("tasks")
                if not other_tasks:
                    continue
                filtered = [
                    task
                    for task in other_tasks
                    if str(task.get("task_id") or task.get("match_key") or "")
                    != task_key
                ]
                if len(filtered) != len(other_tasks):
                    other_day["tasks"] = filtered
            target_tasks = target.setdefault("tasks", [])
            existing_index = next(
                (
                    index
                    for index, task in enumerate(target_tasks)
                    if str(task.get("task_id") or task.get("match_key") or "")
                    == task_key
                ),
                None,
            )
            if existing_index is None:
                target_tasks.append(completed_task)
            else:
                existing_task = target_tasks[existing_index]
                attribution = (
                    "planned_today"
                    if existing_task.get("attribution") == "planned_today"
                    else completed_task.get("attribution")
                )
                target_tasks[existing_index] = {
                    **existing_task,
                    **completed_task,
                    "attribution": attribution,
                }
            daily_tasks_by_user.setdefault(row.user_id, {})[task_key] = completed_task

        for timeline_item in timeline:
            timeline_item["tasks"] = _dedupe_timeline_tasks(
                list(timeline_item.get("tasks") or [])
            )

    # Older daily snapshots may have been calculated before the Weekly Planner
    # opt-in was enforced in Realization. Filter those persisted facts at read
    # time as well, so disabling the option cannot leave stale system cards in
    # the report.
    system_task_ids: set[uuid.UUID] = set()
    system_facts = [
        task
        for timeline in daily_by_user.values()
        for timeline_item in timeline
        for task in timeline_item.get("tasks") or []
    ]
    system_facts.extend(
        task
        for row in visible
        for task in (row.facts_json or {}).get("tasks") or []
    )
    for task in system_facts:
        if task.get("source_type") != "system":
            continue
        try:
            system_task_ids.add(uuid.UUID(str(task.get("task_id"))))
        except (TypeError, ValueError):
            continue
    opted_in_system_task_ids = set(
        (
            await db.execute(
                select(Task.id)
                .join(
                    SystemTaskTemplate,
                    Task.system_template_origin_id == SystemTaskTemplate.id,
                )
                .where(
                    Task.id.in_(system_task_ids),
                    SystemTaskTemplate.show_in_weekly_planner.is_(True),
                )
            )
        ).scalars().all()
    ) if system_task_ids else set()

    def is_realization_visible(task: dict) -> bool:
        if task.get("source_type") != "system":
            return True
        try:
            task_id = uuid.UUID(str(task.get("task_id")))
        except (TypeError, ValueError):
            # Without a live task/template relation the opt-in cannot be
            # verified, therefore a system fact must not affect Realization.
            return False
        return task_id in opted_in_system_task_ids

    for timeline in daily_by_user.values():
        for timeline_item in timeline:
            timeline_item["tasks"] = [
                task
                for task in timeline_item.get("tasks") or []
                if is_realization_visible(task)
            ]
    _merge_daily_report_timeline_evidence(
        daily_by_user, daily_report_evidence_by_user_day
    )
    for user_id, tasks_by_key in daily_tasks_by_user.items():
        daily_tasks_by_user[user_id] = {
            key: task
            for key, task in tasks_by_key.items()
            if is_realization_visible(task)
        }

    visible_task_ids: set[uuid.UUID] = set()
    for row in visible:
        for timeline_item in daily_by_user.get(row.user_id, []):
            for task in timeline_item.get("tasks") or []:
                try:
                    visible_task_ids.add(uuid.UUID(str(task.get("task_id"))))
                except (TypeError, ValueError):
                    continue
    current_task_owners: dict[uuid.UUID, set[uuid.UUID]] = {}
    if visible_task_ids:
        from app.models.task_assignee import TaskAssignee

        for task_id, owner_id in (
            await db.execute(
                select(TaskAssignee.task_id, TaskAssignee.user_id).where(
                    TaskAssignee.task_id.in_(visible_task_ids)
                )
            )
        ).all():
            current_task_owners.setdefault(task_id, set()).add(owner_id)
        for task_id, assigned_to in (
            await db.execute(
                select(Task.id, Task.assigned_to).where(Task.id.in_(visible_task_ids))
            )
        ).all():
            if assigned_to is not None and not current_task_owners.get(task_id):
                current_task_owners.setdefault(task_id, set()).add(assigned_to)

    def belongs_to_person(task: dict, user_id: uuid.UUID) -> bool:
        try:
            task_id = uuid.UUID(str(task.get("task_id")))
        except (TypeError, ValueError):
            return True
        owners = current_task_owners.get(task_id)
        return not owners or user_id in owners

    for row in visible:
        for timeline_item in daily_by_user.get(row.user_id, []):
            timeline_item["tasks"] = [
                task
                for task in timeline_item.get("tasks") or []
                if belongs_to_person(task, row.user_id)
            ]
        if row.user_id in daily_tasks_by_user:
            daily_tasks_by_user[row.user_id] = {
                key: task
                for key, task in daily_tasks_by_user[row.user_id].items()
                if belongs_to_person(task, row.user_id)
            }
    task_comment_map = {
        (comment.task_id, comment.user_id): comment.comment
        for comment in (
            await db.execute(
                select(TaskUserComment).where(
                    TaskUserComment.task_id.in_(visible_task_ids),
                    TaskUserComment.user_id.in_([row.user_id for row in visible]),
                )
            )
        ).scalars().all()
    } if visible_task_ids else {}
    for row in visible:
        for timeline_item in daily_by_user.get(row.user_id, []):
            for task in timeline_item.get("tasks") or []:
                try:
                    task_uuid = uuid.UUID(str(task.get("task_id")))
                except (TypeError, ValueError):
                    task_uuid = None
                daily_comment = task.get("daily_report_comment")
                task["user_comment"] = (
                    daily_comment
                    if daily_comment is not None
                    else task_comment_map.get((task_uuid, row.user_id)) if task_uuid else None
                )
    # The weekly plan snapshot is sometimes captured mid-week and by then it
    # already contains the week's new work, so it cannot tell plan from extra.
    # The task's own creation date can, and it comes from the database rather
    # than from whatever a snapshot happened to freeze.
    weekly_tasks = [
        *(
            task
            for timeline in daily_by_user.values()
            for timeline_item in timeline
            for task in timeline_item.get("tasks") or []
        ),
        *(task for tasks in daily_tasks_by_user.values() for task in tasks.values()),
        *(task for row in visible for task in (row.facts_json or {}).get("tasks") or []),
    ]
    creation_days = await _task_creation_days(db, weekly_tasks)
    _apply_creation_days(weekly_tasks, creation_days)
    await _attach_weekly_daily_evidence(
        db, period=period, daily_by_user=daily_by_user, user_ids=[row.user_id for row in visible]
    )
    answers_by_user = await _weekly_manual_answers(
        db, period=period, user_ids=[row.user_id for row in visible]
    )
    answerer_ids = {
        answer.answered_by
        for user_answers in answers_by_user.values()
        for answer in user_answers.values()
    }
    answerer_names = {
        actor.id: actor.full_name
        for actor in (
            await db.execute(select(User).where(User.id.in_(answerer_ids)))
        ).scalars().all()
    } if answerer_ids else {}
    people: list[RealizationPersonWorkflowOut] = []
    for row in visible:
        payload = RealizationPersonResultOut.model_validate(row).model_dump()
        facts = _visible_facts(user, row)
        facts["tasks"] = [
            task
            for task in facts.get("tasks") or []
            if belongs_to_person(task, row.user_id) and is_realization_visible(task)
        ]
        for task in facts["tasks"]:
            try:
                task_uuid = uuid.UUID(str(task.get("task_id")))
            except (TypeError, ValueError):
                task_uuid = None
            daily_comment = task.get("daily_report_comment")
            task["user_comment"] = (
                daily_comment
                if daily_comment is not None
                else task_comment_map.get((task_uuid, row.user_id)) if task_uuid else None
            )
        _apply_creation_days(facts["tasks"], creation_days)
        facts["daily_timeline"] = daily_by_user.get(row.user_id, [])
        facts.update(
            build_weekly_task_metrics(
                facts["tasks"], facts["daily_timeline"], week_start=period.start_date
            )
        )
        facts.update(build_weekly_question_metrics(facts["daily_timeline"]))
        # The live weekly read never set this, so leave only ever surfaced in a
        # calculated week. Those need a FINAL snapshot, which is why PV never
        # showed up in practice.
        away_status = away_statuses.get(row.user_id)
        if away_status:
            facts["availability_status"] = away_status
        facts["question_scope"] = "WEEKLY"
        facts["observations"] = live_by_user.get(row.user_id, [])
        pulse_history = [
            {
                "date": item["date"],
                "pulse": (item.get("pulse") or {}).get("pulse"),
                "reason": (item.get("pulse") or {}).get("reason"),
                "has_snapshot": item.get("has_snapshot", False),
                "close_state": item.get("close_state", "OPEN"),
                "close_event": item.get("close_event"),
            }
            for item in facts["daily_timeline"]
        ]
        facts["pulse_history"] = pulse_history
        latest_pulse_item = next(
            (item for item in reversed(facts["daily_timeline"]) if item.get("pulse")),
            None,
        )
        if period.final_snapshot_id is None and latest_pulse_item is not None:
            facts["pulse"] = latest_pulse_item.get("pulse")
            facts["projected_weekly_pulse"] = latest_pulse_item.get("pulse")
            facts["recovery"] = latest_pulse_item.get("recovery")
        if period.final_snapshot_id is None:
            facts["tasks"] = list(daily_tasks_by_user.get(row.user_id, {}).values()) or (
                facts.get("tasks") or []
            )
            facts["questions"] = build_live_questions(facts)
        direct_answers = {
            key: _answer_payload(answer, answerer_names.get(answer.answered_by))
            for key, answer in answers_by_user.get(row.user_id, {}).items()
        }
        # Old FINAL snapshots may still classify manager questions as automatic.
        for question in facts.get("questions") or []:
            if question.get("key") in {"respected_meetings", "approved_postponement"}:
                question["source_status"] = "MANUAL_UNANSWERED"
        apply_checklist_answers(facts, direct_answers=direct_answers)
        facts["weekly_evaluation"] = suggest_weekly_level(facts)
        facts.update(diamonds_by_user.get(row.user_id, empty_weekly_diamonds()))
        facts["manager_review_comment"] = row.manager_comment
        payload["facts_json"] = facts
        if user.role == UserRole.STAFF:
            payload["manager_comment"] = None
            payload["override_reason"] = None
        payload["user_name"] = names.get(row.user_id, "Employee")
        people.append(RealizationPersonWorkflowOut.model_validate(payload))
    department_result = (
        await db.execute(
            select(RealizationDepartmentResult).where(
                RealizationDepartmentResult.period_id == period.id
            )
        )
    ).scalar_one_or_none()
    has_planned = period.planned_snapshot_id is not None
    has_final = period.final_snapshot_id is not None
    has_reviewed_result = any(row.reviewed_at is not None for row in rows)
    # A plan photographed on Thursday is not a plan. Saying when it was taken
    # lets the page warn instead of presenting mid-week work as planned.
    planned_captured_day = (
        local_day(planned_snapshot.created_at) if planned_snapshot is not None else None
    )
    message = None
    if not has_planned:
        message = "Nuk ka PLANNED snapshot zyrtar për këtë javë."
    elif not has_final:
        message = (
            "Po shfaqet progresi aktual nga snapshot-et ditore. "
            "FINAL ruhet në mbylljen e javës për vlerësimin përfundimtar."
        )
    return RealizationWeeklyOut(
        period=RealizationPeriodOut.model_validate(period),
        department_name=department_name,
        has_planned_snapshot=has_planned,
        planned_snapshot_captured_day=planned_captured_day,
        has_final_snapshot=has_final,
        can_calculate=(
            has_planned
            and (has_final or _can_capture_current_week_final(period))
            and period.status in {
                RealizationPeriodStatus.OPEN.value,
                RealizationPeriodStatus.CALCULATED.value,
            }
            and not has_reviewed_result
            and user.role in {UserRole.MANAGER, UserRole.ADMIN}
        ),
        message=message,
        people=people,
        department_result=(
            RealizationDepartmentResultOut.model_validate(department_result)
            if department_result and user.role != UserRole.STAFF
            else None
        ),
        unassigned=(department_result.facts_json or {}).get("unassigned", [])
        if department_result and user.role != UserRole.STAFF
        else [],
    )


@router.get("/export.xlsx")
async def export_realization_excel(
    week_start: date,
    department_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Forbidden")

    start = normalize_week_start(week_start)
    end = weekly_end(start)
    period_statement = select(RealizationPeriod).where(
        RealizationPeriod.period_type == "WEEKLY",
        RealizationPeriod.start_date == start,
        RealizationPeriod.end_date == end,
    )
    if department_id is not None:
        period_statement = period_statement.where(
            RealizationPeriod.department_id == department_id
        )
    periods = (await db.execute(period_statement)).scalars().all()
    if not periods:
        raise HTTPException(status_code=409, detail="Nuk ka realizim të gjeneruar për këtë javë")

    department_ids = [period.department_id for period in periods if period.department_id]
    departments_by_id = {
        row.id: row.name
        for row in (
            await db.execute(select(Department).where(Department.id.in_(department_ids)))
        ).scalars().all()
    }
    managers_by_department_id: dict[uuid.UUID, str] = {}
    if department_ids:
        for manager_row in (
            await db.execute(
                select(User).where(
                    User.role == UserRole.MANAGER,
                    User.department_id.in_(department_ids),
                )
            )
        ).scalars().all():
            if manager_row.department_id is not None:
                managers_by_department_id[manager_row.department_id] = manager_row.full_name
    export_departments = []
    for period in periods:
        report = await _weekly_response(
            db, period=period, user=user,
            department_name=departments_by_id.get(period.department_id),
        )
        people = []
        for person in report.people:
            payload = person.model_dump(mode="python")
            review = await build_manager_review_response(
                db, period_id=period.id, user_id=person.user_id, can_edit=False,
            )
            payload["weekly_manager_review"] = review.get("realization")
            facts = payload["facts_json"]
            payload["planned_count"] = facts.get("weekly_planned_count", 0)
            payload["completed_on_time_count"] = facts.get("weekly_all_completed_count", 0)
            payload["completed_late_count"] = 0
            payload["additional_count"] = facts.get("weekly_additional_count", 0)
            facts["report_mode"] = "FINAL_WEEKLY" if period.final_snapshot_id else "LIVE_DAILY"
            people.append(payload)
        export_departments.append({
            "name": departments_by_id.get(period.department_id, "Departamenti"),
            "manager_name": managers_by_department_id.get(period.department_id),
            "status": period.status,
            "report_mode": "FINAL_WEEKLY" if period.final_snapshot_id else "LIVE_DAILY",
            "people": sorted(people, key=lambda item: item["user_name"]),
        })
    content = build_realization_workbook(
        week_start=start.isoformat(),
        week_end=end.isoformat(),
        departments=export_departments,
    )
    filename = f"REALIZIMI_JAVOR_{start.isoformat()}_{end.isoformat()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/weekly", response_model=RealizationWeeklyOut)
async def get_weekly_realization(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationWeeklyOut:
    _ensure_department_scope(user, department_id)
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    try:
        period, _, _ = await ensure_weekly_period(
            db,
            department_id=department_id,
            week_start=week_start,
            created_by=user.id,
        )
        await db.commit()
        await db.refresh(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    return await _weekly_response(
        db, period=period, user=user, department_name=department.name
    )


@router.post("/weekly/prepare", response_model=RealizationWeeklyOut)
async def prepare_weekly_realization(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationWeeklyOut:
    """Recover the active-week baseline and any missing daily calculations."""
    _ensure_department_scope(user, department_id)
    if user.role not in {UserRole.MANAGER, UserRole.ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    requested_week = normalize_week_start(week_start)
    local_today = datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()
    current_week = normalize_week_start(local_today)
    if requested_week != current_week:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PLANNED snapshot mund të rikrijohet vetëm për javën aktuale.",
        )

    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    try:
        planned_recovered = False
        prepared_days: list[str] = []
        period, planned, _ = await ensure_weekly_period(
            db,
            department_id=department_id,
            week_start=requested_week,
            created_by=user.id,
        )
        if planned is None:
            from app.api.routers.planners import _create_and_store_weekly_snapshot

            await _create_and_store_weekly_snapshot(
                db=db,
                user=user,
                department_id=department_id,
                week_start_date=requested_week,
                snapshot_type=WeeklySnapshotType.PLANNED,
                is_this_week=True,
            )
            period, planned, _ = await ensure_weekly_period(
                db,
                department_id=department_id,
                week_start=requested_week,
                created_by=user.id,
            )
            if planned is None:
                raise RealizationWorkflowError("PLANNED snapshot nuk u krijua")
            planned_recovered = True

        current_day = period.start_date
        last_day = min(local_today, period.end_date)
        while current_day <= last_day:
            if _is_working_day(current_day):
                daily_period, daily_planned = await ensure_daily_period(
                    db,
                    department_id=department_id,
                    day=current_day,
                    created_by=user.id,
                )
                if daily_planned is None:
                    raise RealizationWorkflowError(
                        f"PLANNED snapshot mungon për {current_day.isoformat()}"
                    )
                if daily_period.status == RealizationPeriodStatus.OPEN.value:
                    daily_period = await _period(db, daily_period.id, for_update=True)
                    await calculate_daily_period(
                        db,
                        period=daily_period,
                        planned_snapshot=daily_planned,
                        actor_id=user.id,
                    )
                    prepared_days.append(current_day.isoformat())
            current_day += timedelta(days=1)

        if planned_recovered or prepared_days:
            add_audit_log(
                db=db,
                actor_user_id=user.id,
                entity_type="realization_period",
                entity_id=period.id,
                action="weekly_live_data_prepared",
                after={
                    "week_start": requested_week.isoformat(),
                    "planned_snapshot_id": str(planned.id),
                    "planned_snapshot_recovered": planned_recovered,
                    "prepared_days": prepared_days,
                },
            )
        await db.commit()
        await db.refresh(period)
    except (ValueError, RealizationWorkflowError) as exc:
        await db.rollback()
        raise _error(exc)

    return await _weekly_response(
        db, period=period, user=user, department_name=department.name
    )


@router.post("/weekly/calculate", response_model=RealizationWeeklyOut)
async def calculate_realization(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationWeeklyOut:
    _ensure_department_scope(user, department_id)
    if user.role not in {UserRole.MANAGER, UserRole.ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    try:
        period, planned, final = await ensure_weekly_period(
            db,
            department_id=department_id,
            week_start=week_start,
            created_by=user.id,
        )
        if final is None:
            if not _can_capture_current_week_final(period):
                raise RealizationWorkflowError(
                    "FINAL mund të krijohet vetëm në ditën e fundit të javës aktuale."
                )
            from app.api.routers.planners import _create_and_store_weekly_snapshot

            await _create_and_store_weekly_snapshot(
                db=db,
                user=user,
                department_id=department_id,
                week_start_date=period.start_date,
                snapshot_type=WeeklySnapshotType.FINAL,
                is_this_week=True,
            )
            period, planned, final = await ensure_weekly_period(
                db,
                department_id=department_id,
                week_start=week_start,
                created_by=user.id,
            )
        period = await _period(db, period.id, for_update=True)
        if planned is None or final is None:
            raise RealizationWorkflowError("PLANNED dhe FINAL kërkohen për kalkulimin javor")
        before = {"status": period.status}
        await calculate_weekly_period(
            db,
            period=period,
            planned_snapshot=planned,
            final_snapshot=final,
            actor_id=user.id,
        )
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="realization_period",
            entity_id=period.id,
            action="calculated",
            before=before,
            after={
                "status": period.status,
                "planned_snapshot_id": str(period.planned_snapshot_id),
                "final_snapshot_id": str(period.final_snapshot_id),
            },
        )
        await db.commit()
        await db.refresh(period)
    except (ValueError, RealizationWorkflowError) as exc:
        await db.rollback()
        raise _error(exc)
    return await _weekly_response(
        db, period=period, user=user, department_name=department.name
    )


async def _daily_response(
    db: AsyncSession,
    *,
    period: RealizationPeriod,
    department_name: str,
    user: User,
) -> RealizationDailyOut:
    raw_rows = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.period_id == period.id
            )
        )
    ).scalars().all()
    active_users, common_leave = await load_active_users_and_common_leave(
        db,
        department_id=period.department_id,
        start_date=period.start_date,
        end_date=period.end_date,
    )
    eligible_user_ids = {
        active_user.id
        for active_user in active_users
        if active_user.id not in common_leave
        or period.start_date not in common_leave[active_user.id].days
    }
    if user.role == UserRole.STAFF:
        eligible_user_ids &= {user.id}
    rows = [
        row
        for row in raw_rows
        if row.user_id in eligible_user_ids
        and can_view_person_result(
            user,
            subject_user_id=row.user_id,
            subject_department_id=row.department_id,
        )
    ]
    names = {
        row.id: row.full_name
        for row in (
            await db.execute(select(User).where(User.id.in_([item.user_id for item in rows])))
        ).scalars().all()
    } if rows else {}
    answers_by_user = await _weekly_manual_answers(
        db, period=period, user_ids=[row.user_id for row in rows]
    )
    answerer_ids = {
        answer.answered_by
        for user_answers in answers_by_user.values()
        for answer in user_answers.values()
    }
    answerer_names = {
        actor.id: actor.full_name
        for actor in (
            await db.execute(select(User).where(User.id.in_(answerer_ids)))
        ).scalars().all()
    } if answerer_ids else {}
    people = []
    for row in rows:
        payload = RealizationPersonResultOut.model_validate(row).model_dump()
        facts = _visible_facts(user, row)
        # Rebuild from the stored facts so historical daily periods also expose
        # the current 17-question checklist without rewriting their snapshot.
        facts["questions"] = build_live_questions(facts)
        apply_checklist_answers(facts, direct_answers={
            key: _answer_payload(answer, answerer_names.get(answer.answered_by))
            for key, answer in answers_by_user.get(row.user_id, {}).items()
        })
        payload["facts_json"] = facts
        if user.role == UserRole.STAFF:
            payload["manager_comment"] = None
            payload["override_reason"] = None
        payload["user_name"] = names.get(row.user_id, "Employee")
        people.append(RealizationPersonWorkflowOut.model_validate(payload))
    department_result = (
        await db.execute(
            select(RealizationDepartmentResult).where(
                RealizationDepartmentResult.period_id == period.id
            )
        )
    ).scalar_one_or_none()
    has_planned = period.planned_snapshot_id is not None
    return RealizationDailyOut(
        period=RealizationPeriodOut.model_validate(period),
        department_name=department_name,
        has_planned_snapshot=has_planned,
        can_calculate=(
            has_planned
            and period.status in {
                RealizationPeriodStatus.OPEN.value,
                RealizationPeriodStatus.CALCULATED.value,
            }
        ),
        message=None if has_planned else "Nuk ka PLANNED snapshot zyrtar për këtë javë.",
        people=people,
        department_result=(
            RealizationDepartmentResultOut.model_validate(department_result)
            if department_result and user.role != UserRole.STAFF else None
        ),
    )


@router.get("/daily", response_model=RealizationDailyOut)
async def get_daily_realization(
    department_id: uuid.UUID,
    day: date,
    user_id: uuid.UUID | None = None,
    exceptions_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationDailyOut:
    _ensure_department_scope(user, department_id)
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if user.role == UserRole.STAFF:
        user_id = user.id
    elif user_id is not None and not can_view_person_result(
        user, subject_user_id=user_id, subject_department_id=department_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        period, _ = await ensure_daily_period(
            db, department_id=department_id, day=day, created_by=user.id
        )
        local_today = datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()
        if day == local_today:
            await ensure_daily_baseline(
                db, department_id=department_id, day=day, actor=user
            )
        await db.commit()
        await db.refresh(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    response = await _daily_response(
        db, period=period, department_name=department.name, user=user
    )
    response.live = await build_live_daily_realization(
        db, department_id=department_id, day=day,
        user_id=user_id, exceptions_only=exceptions_only,
    )
    live_by_user = {
        str(person.get("user_id")): person
        for person in (response.live or {}).get("people", [])
    }
    for person in response.people:
        live_person = live_by_user.get(str(person.user_id))
        if live_person is None:
            continue
        facts = dict(person.facts_json or {})
        facts["questions"] = build_daily_questions_from_live(facts, live_person)
        facts["daily_planned_count"] = int(
            (live_person.get("metrics") or {}).get("original_planned_count") or 0
        )
        facts["daily_completed_count"] = int(
            (live_person.get("metrics") or {}).get("planned_completed_today_count") or 0
        )
        facts["question_scope"] = "DAILY"
        person.facts_json = facts
    return response


@router.post("/daily/checklist/prepare", response_model=RealizationDailyOut)
async def prepare_daily_checklist(
    department_id: uuid.UUID,
    day: date,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationDailyOut:
    """Create the editable daily checklist without requiring a PLANNED snapshot."""
    _ensure_department_scope(user, department_id)
    if user.role not in {UserRole.MANAGER, UserRole.ADMIN} or not can_review_realization(
        user, department_id=department_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not can_view_person_result(
        user,
        subject_user_id=user_id,
        subject_department_id=department_id,
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")

    try:
        period, _ = await ensure_daily_period(
            db, department_id=department_id, day=day, created_by=user.id
        )
        result = (
            await db.execute(
                select(RealizationPersonResult).where(
                    RealizationPersonResult.period_id == period.id,
                    RealizationPersonResult.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if result is None:
            live = await build_live_daily_realization(
                db,
                department_id=department_id,
                day=day,
                user_id=user_id,
            )
            person = next(
                (
                    item
                    for item in live.get("people") or []
                    if str(item.get("user_id")) == str(user_id)
                ),
                None,
            )
            if person is None:
                raise HTTPException(
                    status_code=404,
                    detail="Personi nuk ka të dhëna ditore për datën e zgjedhur",
                )
            metrics = person.get("metrics") or {}
            planned_count = int(metrics.get("original_planned_count") or 0)
            completed_count = int(metrics.get("total_completed_today_count") or 0)
            completed_late_count = int(metrics.get("completed_late_count") or 0)
            counters = {
                "planned_count": planned_count,
                "completed_count": completed_count,
                "daily_planned_count": planned_count,
                "daily_completed_count": completed_count,
                "in_progress_count": int(metrics.get("in_progress_count") or 0),
                "pending_confirmation_count": int(
                    metrics.get("waiting_confirmation_count") or 0
                ),
                "no_progress_count": int(metrics.get("no_progress_count") or 0),
                "additional_count": int(metrics.get("additional_count") or 0),
                "additional_completed_count": int(
                    metrics.get("additional_completed_count") or 0
                ),
                "additional_in_progress_count": int(
                    metrics.get("additional_in_progress_count") or 0
                ),
                "additional_no_progress_count": int(
                    metrics.get("additional_no_progress_count") or 0
                ),
                "approved_postponement_count": int(
                    metrics.get("approved_postponement_count") or 0
                ),
                "unapproved_postponement_count": int(
                    metrics.get("unapproved_postponement_count") or 0
                ),
            }
            facts = {
                "date": day.isoformat(),
                "user_id": str(user_id),
                "department_id": str(department_id),
                "counters": counters,
                "tasks": person.get("tasks") or [],
                "checklist_without_planned_snapshot": True,
            }
            facts["questions"] = build_live_questions(facts)
            result = RealizationPersonResult(
                period_id=period.id,
                user_id=user_id,
                department_id=department_id,
                facts_json=facts,
                planned_count=planned_count,
                completed_on_time_count=max(0, completed_count - completed_late_count),
                completed_late_count=completed_late_count,
                in_progress_count=counters["in_progress_count"],
                pending_count=counters["pending_confirmation_count"],
                no_progress_count=counters["no_progress_count"],
                additional_count=counters["additional_count"],
                approved_postponement_count=counters["approved_postponement_count"],
                unapproved_postponement_count=counters[
                    "unapproved_postponement_count"
                ],
            )
            db.add(result)
            await db.flush()
            add_audit_log(
                db=db,
                actor_user_id=user.id,
                entity_type="realization_person_result",
                entity_id=result.id,
                action="daily_checklist_prepared",
                after={
                    "day": day.isoformat(),
                    "user_id": str(user_id),
                    "without_planned_snapshot": period.planned_snapshot_id is None,
                },
            )
        await db.commit()
        await db.refresh(period)
    except HTTPException:
        await db.rollback()
        raise
    except RealizationWorkflowError as exc:
        await db.rollback()
        raise _error(exc)

    return await _daily_response(
        db, period=period, department_name=department.name, user=user
    )


@router.get("/daily/tasks/{task_id}/timeline")
async def get_daily_task_timeline(
    task_id: uuid.UUID,
    day: date,
    user_id: uuid.UUID,
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _ensure_department_scope(user, department_id)
    if not can_view_person_result(
        user, subject_user_id=user_id, subject_department_id=department_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    live = await build_live_daily_realization(
        db, department_id=department_id, day=day, user_id=user_id
    )
    for person in live["people"]:
        for task in person["tasks"]:
            if task["task_id"] == str(task_id):
                actor_ids = {
                    uuid.UUID(item["actor_user_id"])
                    for item in task["timeline"] if item.get("actor_user_id")
                }
                names = {
                    row.id: row.full_name
                    for row in (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
                } if actor_ids else {}
                for item in task["timeline"]:
                    actor = item.get("actor_user_id")
                    item["actor_name"] = names.get(uuid.UUID(actor)) if actor else None
                return {"day": day.isoformat(), "user_id": str(user_id), "task": task}
    raise HTTPException(status_code=404, detail="Task is not part of this person's Daily Realization")


@router.post("/daily/tasks/{task_id}/adjustment")
async def decide_daily_plan_adjustment(
    task_id: uuid.UUID,
    payload: DailyPlanAdjustmentDecision,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if user.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Only manager/admin can decide plan adjustments")
    normalized = payload.status.strip().upper()
    if normalized not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="status must be APPROVED or REJECTED")
    adjustment = (await db.execute(select(DailyPlanAdjustment).where(
        DailyPlanAdjustment.task_id == task_id,
        DailyPlanAdjustment.audit_event_id == payload.audit_event_id,
        DailyPlanAdjustment.user_id == payload.user_id,
    ).with_for_update())).scalar_one_or_none()
    if adjustment is None:
        raise HTTPException(status_code=404, detail="Daily plan adjustment not found")
    subject = await db.get(User, payload.user_id)
    if subject is None or (user.role == UserRole.MANAGER and subject.department_id != user.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    before = {"status": adjustment.status}
    adjustment.status = normalized
    adjustment.reason = payload.reason.strip()
    adjustment.decision_comment = (payload.comment or "").strip() or None
    adjustment.decided_by = user.id
    adjustment.decided_at = datetime.now(timezone.utc)
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="daily_plan_adjustment",
        entity_id=adjustment.id, action=normalized.lower(), before=before,
        after={"status": normalized, "reason": adjustment.reason, "comment": adjustment.decision_comment},
    )
    await db.commit()
    return {
        "id": str(adjustment.id),
        "status": adjustment.status,
        "reason": adjustment.reason,
        "comment": adjustment.decision_comment,
        "decided_by_user_id": str(adjustment.decided_by) if adjustment.decided_by else None,
        "decided_by_name": user.full_name,
        "decided_at": adjustment.decided_at.isoformat(),
    }


@router.post("/daily/calculate", response_model=RealizationDailyOut)
async def calculate_daily_realization(
    department_id: uuid.UUID,
    day: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationDailyOut:
    if user.role == UserRole.STAFF:
        raise HTTPException(status_code=403, detail="STAFF cannot recalculate a department snapshot")
    _ensure_department_scope(user, department_id)
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    try:
        period, planned = await ensure_daily_period(
            db, department_id=department_id, day=day, created_by=user.id
        )
        period = await _period(db, period.id, for_update=True)
        await calculate_daily_period(
            db, period=period, planned_snapshot=planned, actor_id=user.id
        )
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="realization_period",
            entity_id=period.id,
            action="daily_snapshot_calculated",
            after={"day": day.isoformat(), "status": period.status},
        )
        await db.commit()
        await db.refresh(period)
    except (ValueError, RealizationWorkflowError) as exc:
        await db.rollback()
        raise _error(exc)
    return await _daily_response(
        db, period=period, department_name=department.name, user=user
    )


@router.post("/daily/prepare", response_model=RealizationDailyOut)
async def prepare_daily_realization(
    department_id: uuid.UUID,
    day: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationDailyOut:
    """Create or refresh the caller's Daily RLZ result after slot rollover."""
    _ensure_department_scope(user, department_id)
    if user.department_id != department_id:
        raise HTTPException(
            status_code=403,
            detail="Daily RLZ can be prepared only for your department",
        )
    if not is_closable_day(day):
        raise HTTPException(status_code=409, detail={
            "code": "DAILY_RLZ_CLOSE_WINDOW_NOT_OPEN",
            "message": "Dita mund të mbyllet nga ora 15:30 e ditës përkatëse.",
            "closable_from": closable_from(day).isoformat(),
        })
    department = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    try:
        period, planned = await ensure_daily_period(
            db, department_id=department_id, day=day, created_by=user.id
        )
        if planned is None:
            raise HTTPException(
                status_code=409,
                detail="PLANNED snapshot is required before closing Daily RLZ",
            )
        period = await _period(db, period.id, for_update=True)
        await calculate_daily_period(
            db,
            period=period,
            planned_snapshot=planned,
            actor_id=user.id,
            only_user_id=user.id,
        )
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="realization_period",
            entity_id=period.id,
            action="daily_result_prepared_for_close",
            after={"day": day.isoformat(), "user_id": str(user.id)},
        )
        await db.commit()
        await db.refresh(period)
    except HTTPException:
        await db.rollback()
        raise
    except (ValueError, RealizationWorkflowError) as exc:
        await db.rollback()
        raise _error(exc)
    return await _daily_response(
        db, period=period, department_name=department.name, user=user
    )


async def _latest_close_event(
    db: AsyncSession, *, period_id: uuid.UUID, user_id: uuid.UUID
) -> RealizationDailyCloseEvent | None:
    return (
        await db.execute(
            select(RealizationDailyCloseEvent)
            .where(
                RealizationDailyCloseEvent.period_id == period_id,
                RealizationDailyCloseEvent.user_id == user_id,
            )
            .order_by(
                RealizationDailyCloseEvent.created_at.desc(),
                RealizationDailyCloseEvent.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


@router.post(
    "/periods/{period_id}/results/{result_id}/close-day",
    response_model=RealizationDailyCloseEventOut,
)
async def close_realization_day(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: RealizationDailyCloseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationDailyCloseEventOut:
    period = await _period(db, period_id, for_update=True)
    if period.period_type != "DAILY" or period.department_id is None:
        raise HTTPException(status_code=409, detail="Only a daily Realization period can be closed")
    result = await db.get(RealizationPersonResult, result_id)
    if result is None or result.period_id != period.id:
        raise HTTPException(status_code=404, detail="Realization result not found")
    if not can_view_person_result(
        user,
        subject_user_id=result.user_id,
        subject_department_id=result.department_id,
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    if user.role == UserRole.STAFF and result.user_id != user.id:
        raise HTTPException(status_code=403, detail="STAFF can close only their own day")
    if result.user_id == user.id and not is_closable_day(period.start_date):
        raise HTTPException(status_code=409, detail={
            "code": "DAILY_RLZ_CLOSE_WINDOW_CLOSED",
            "message": "Dita mund të mbyllet nga ora 15:30 e ditës përkatëse.",
        })
    require_unlocked(period)
    planned, _ = await _pinned_snapshots(db, period)
    if planned is None:
        raise HTTPException(status_code=409, detail="PLANNED snapshot is required")

    # Closing always refreshes the source facts first; it never trusts the 16:20 snapshot blindly.
    await calculate_daily_period(
        db,
        period=period,
        planned_snapshot=planned,
        actor_id=user.id,
        only_user_id=result.user_id if user.role == UserRole.STAFF else None,
    )
    await db.flush()
    await db.refresh(result)
    facts = dict(result.facts_json or {})
    daily_report_state = await build_daily_rlz_compliance(
        db, user_id=result.user_id, day=period.start_date
    )
    if daily_report_state["blockers"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RLZ_DAILY_REPORT_VALIDATION_FAILED",
                "message": "Plotëso detyrat para mbylljes së ditës.",
                "blockers": daily_report_state["blockers"],
            },
        )
    if int(facts.get("missing_pink_explanation_count") or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RLZ_PINK_EXPLANATION_REQUIRED",
                "message": "Para mbylljes, shpjego detyrat Pink pa progres.",
            },
        )
    if not (payload.daily_comment and payload.daily_comment.strip()):
        raise HTTPException(status_code=422, detail="Komenti i mbylljes ditore është i detyrueshëm")
    pulse_raw = (facts.get("pulse") or {}).get("pulse")
    try:
        suggested = RealizationPulse(str(pulse_raw))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Daily Pulse is not available") from exc
    department = await db.get(Department, period.department_id)
    mode = RealizationOperatingMode(
        department.realization_mode if department else RealizationOperatingMode.AUTO.value
    )
    confirmed = payload.confirmed_pulse
    reason = (payload.reason or "").strip() or None
    if mode is RealizationOperatingMode.AUTO:
        if confirmed is None:
            confirmed = suggested
        elif confirmed != suggested:
            if user.role not in {UserRole.MANAGER, UserRole.ADMIN} or not reason:
                raise HTTPException(status_code=409, detail="AUTO override requires manager/admin and a reason")
    elif confirmed is None:
        raise HTTPException(status_code=422, detail="This operating mode requires a confirmed Pulse")
    if mode is RealizationOperatingMode.MANUAL and not reason:
        raise HTTPException(status_code=422, detail="MANUAL Pulse requires a reason")
    if confirmed != suggested and not reason:
        raise HTTPException(status_code=422, detail="Changing the suggested Pulse requires a reason")
    if confirmed is RealizationPulse.DIAMOND and int((facts.get("pulse") or {}).get("verified_diamond_count") or 0) < 1:
        raise HTTPException(status_code=409, detail="DIAMOND requires verified DIAMOND evidence")

    latest = await _latest_close_event(db, period_id=period.id, user_id=result.user_id)
    latest_is_closed = latest is not None and latest.action in {
        RealizationDailyCloseAction.CLOSE.value,
        RealizationDailyCloseAction.CORRECT.value,
    }
    if latest_is_closed and not daily_report_state["rlz_close_state"]["stale"]:
        raise HTTPException(status_code=409, detail="Dita është mbyllur dhe nuk ka ndryshime të reja")
    if latest_is_closed and user.role != UserRole.STAFF:
        raise HTTPException(status_code=409, detail="Manager/admin correction requires the explicit reopen flow")
    action = (
        RealizationDailyCloseAction.CORRECT
        if latest is not None
        else RealizationDailyCloseAction.CLOSE
    )
    if action is RealizationDailyCloseAction.CORRECT and not reason:
        reason = "DAILY_REPORT_STATE_UPDATED"
    event = RealizationDailyCloseEvent(
        period_id=period.id,
        result_id=result.id,
        user_id=result.user_id,
        department_id=period.department_id,
        action=action.value,
        mode=mode.value,
        suggested_pulse=suggested.value,
        confirmed_pulse=confirmed.value if confirmed else None,
        daily_comment=payload.daily_comment.strip(),
        reason=reason,
        facts_json={
            "pulse": facts.get("pulse"),
            "recovery": facts.get("recovery"),
            "counters": facts.get("counters"),
            "task_ids": [item.get("task_id") for item in facts.get("tasks") or [] if item.get("task_id")],
            "daily_report_state": {
                "day": period.start_date.isoformat(),
                "saved_at": datetime.now(ZoneInfo(settings.APP_TIMEZONE)).isoformat(),
                "tasks": daily_report_state["tasks"],
            },
            "daily_realization": (
                (await build_live_daily_realization(
                    db, department_id=period.department_id,
                    day=period.start_date, user_id=result.user_id,
                ))["people"] or [None]
            )[0],
        },
        supersedes_event_id=latest.id if latest else None,
        actor_user_id=user.id,
    )
    db.add(event)
    await db.flush()
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_daily_close",
        entity_id=event.id,
        action=action.value.lower(),
        before={"event_id": str(latest.id)} if latest else None,
        after={
            "suggested_pulse": suggested.value,
            "confirmed_pulse": confirmed.value if confirmed else None,
            "mode": mode.value,
            "reason": reason,
        },
    )
    await db.commit()
    await db.refresh(event)
    return RealizationDailyCloseEventOut.model_validate(event)


def _require_daily_approval_access(user: User, department_id: uuid.UUID) -> None:
    if user.role is UserRole.ADMIN:
        return
    if user.role is UserRole.MANAGER and user.department_id == department_id:
        return
    raise HTTPException(
        status_code=403,
        detail="Vetëm menaxheri i këtij departamenti ose ADMIN mund ta aprovojë ditën.",
    )


def _daily_approval_out(event: RealizationDailyApprovalEvent, status_value: str) -> dict:
    return {
        "id": event.id,
        "period_id": event.period_id,
        "result_id": event.result_id,
        "user_id": event.user_id,
        "department_id": event.department_id,
        "action": event.action,
        "source_close_event_id": event.source_close_event_id,
        "approval_comment": event.approval_comment,
        "reason": event.reason,
        "actor_user_id": event.actor_user_id,
        "created_at": event.created_at,
        "status": status_value,
    }


@router.post(
    "/periods/{period_id}/results/{result_id}/approve-day",
    response_model=RealizationDailyApprovalOut,
)
async def approve_realization_day(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: RealizationDailyApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    period = await _period(db, period_id, for_update=True)
    result = await db.get(RealizationPersonResult, result_id)
    if (
        result is None
        or result.period_id != period.id
        or period.period_type != "DAILY"
        or result.department_id is None
    ):
        raise HTTPException(status_code=404, detail="Daily Realization result not found")
    _require_daily_approval_access(user, result.department_id)
    require_unlocked(period)
    close_event = await latest_daily_close(db, period_id=period.id, user_id=result.user_id)
    if close_event is None or close_event.action not in {"CLOSE", "CORRECT"}:
        raise HTTPException(status_code=409, detail={
            "code": "DAILY_REALIZATION_NOT_CLOSED",
            "message": "Punonjësi duhet ta mbyllë ditën para aprovimit të menaxherit.",
        })
    compliance = await build_daily_rlz_compliance(
        db, user_id=result.user_id, day=period.start_date
    )
    if compliance["blockers"] or compliance["rlz_close_state"]["status"] != "SAVED":
        raise HTTPException(status_code=409, detail={
            "code": "DAILY_REALIZATION_APPROVAL_NOT_READY",
            "message": "Ka ndryshime ose të dhëna të paplotësuara pas mbylljes personale.",
            "blockers": compliance["blockers"],
            "close_state": compliance["rlz_close_state"],
        })
    latest_approval = await latest_daily_approval(
        db, period_id=period.id, user_id=result.user_id
    )
    current_state = approval_state_from_events(
        latest_approval, close_event, personal_close_status="SAVED"
    )
    if current_state["status"] == "APPROVED":
        raise HTTPException(status_code=409, detail="Kjo ditë është aprovuar tashmë.")
    event = RealizationDailyApprovalEvent(
        period_id=period.id,
        result_id=result.id,
        user_id=result.user_id,
        department_id=result.department_id,
        action="APPROVE",
        source_close_event_id=close_event.id,
        approval_comment=(payload.approval_comment or "").strip() or None,
        actor_user_id=user.id,
    )
    db.add(event)
    await db.flush()
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_daily_approval",
        entity_id=event.id,
        action="approve",
        before={"status": current_state["status"]},
        after={"user_id": str(result.user_id), "day": period.start_date.isoformat()},
    )
    await db.commit()
    await db.refresh(event)
    return _daily_approval_out(event, "APPROVED")


@router.post(
    "/periods/{period_id}/results/{result_id}/revoke-day-approval",
    response_model=RealizationDailyApprovalOut,
)
async def revoke_realization_day_approval(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: RealizationDailyApprovalRevokeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    period = await _period(db, period_id, for_update=True)
    result = await db.get(RealizationPersonResult, result_id)
    if result is None or result.period_id != period.id or result.department_id is None:
        raise HTTPException(status_code=404, detail="Daily Realization result not found")
    _require_daily_approval_access(user, result.department_id)
    latest_approval = await latest_daily_approval(
        db, period_id=period.id, user_id=result.user_id
    )
    if latest_approval is None or latest_approval.action != "APPROVE":
        raise HTTPException(status_code=409, detail="Nuk ka aprovim aktiv për t'u hequr.")
    event = RealizationDailyApprovalEvent(
        period_id=period.id,
        result_id=result.id,
        user_id=result.user_id,
        department_id=result.department_id,
        action="REVOKE",
        source_close_event_id=latest_approval.source_close_event_id,
        reason=payload.reason.strip(),
        actor_user_id=user.id,
    )
    db.add(event)
    await db.flush()
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_daily_approval",
        entity_id=event.id,
        action="revoke",
        before={"approval_id": str(latest_approval.id)},
        after={"reason": event.reason},
    )
    await db.commit()
    await db.refresh(event)
    return _daily_approval_out(event, "REVOKED")


@router.post(
    "/periods/{period_id}/results/{result_id}/reopen-day",
    response_model=RealizationDailyCloseEventOut,
)
async def reopen_realization_day(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: RealizationDailyReopenRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationDailyCloseEventOut:
    if user.role not in {UserRole.MANAGER, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Only manager/admin can reopen a closed day")
    period = await _period(db, period_id, for_update=True)
    result = await db.get(RealizationPersonResult, result_id)
    if result is None or result.period_id != period.id or period.period_type != "DAILY":
        raise HTTPException(status_code=404, detail="Daily Realization result not found")
    if not can_review_realization(user, department_id=result.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    require_unlocked(period)
    latest = await _latest_close_event(db, period_id=period.id, user_id=result.user_id)
    if latest is None or latest.action == RealizationDailyCloseAction.REOPEN.value:
        raise HTTPException(status_code=409, detail="The day is not currently closed")
    event = RealizationDailyCloseEvent(
        period_id=period.id,
        result_id=result.id,
        user_id=result.user_id,
        department_id=result.department_id,
        action=RealizationDailyCloseAction.REOPEN.value,
        mode=latest.mode,
        suggested_pulse=latest.suggested_pulse,
        confirmed_pulse=latest.confirmed_pulse,
        daily_comment=latest.daily_comment,
        reason=payload.reason.strip(),
        facts_json=latest.facts_json or {},
        supersedes_event_id=latest.id,
        actor_user_id=user.id,
    )
    db.add(event)
    await db.flush()
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_daily_close",
        entity_id=event.id,
        action="reopen",
        before={"event_id": str(latest.id)},
        after={"reason": event.reason},
    )
    await db.commit()
    await db.refresh(event)
    return RealizationDailyCloseEventOut.model_validate(event)


@router.get("/monthly", response_model=RealizationMonthlyOut)
async def get_monthly_realization(
    department_id: uuid.UUID,
    month_start: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationMonthlyOut:
    _ensure_department_scope(user, department_id)
    start = month_start.replace(day=1)
    next_month = date(start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1, 1)
    end = next_month - timedelta(days=1)
    department = await db.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    # Read-only aggregation: monthly GET never creates a period or rewrites results.
    rows = (
        await db.execute(
            select(RealizationPersonResult, RealizationPeriod)
            .join(RealizationPeriod, RealizationPeriod.id == RealizationPersonResult.period_id)
            .where(
                RealizationPeriod.department_id == department_id,
                RealizationPeriod.period_type == "WEEKLY",
                RealizationPeriod.final_snapshot_id.is_not(None),
                RealizationPeriod.start_date <= end,
                RealizationPeriod.end_date >= start,
                RealizationPeriod.status != RealizationPeriodStatus.OPEN.value,
            )
            .order_by(RealizationPeriod.start_date.asc())
        )
    ).all()
    visible_rows = [
        (result, period)
        for result, period in rows
        if can_view_person_result(
            user,
            subject_user_id=result.user_id,
            subject_department_id=result.department_id,
        )
    ]
    user_ids = {result.user_id for result, _ in visible_rows}
    monthly_users = list((
        await db.execute(select(User).where(User.id.in_(user_ids)))
    ).scalars().all()) if user_ids else []
    monthly_users = [row for row in monthly_users if not is_realization_excluded_user(row)]
    visible_user_ids = {row.id for row in monthly_users}
    visible_rows = [
        (result, period) for result, period in visible_rows
        if result.user_id in visible_user_ids
    ]
    names = {
        row.id: row.full_name
        for row in monthly_users
    }
    weekly_by_user: dict[uuid.UUID, list[dict]] = {}
    departments: dict[uuid.UUID, uuid.UUID | None] = {}
    for result, period in visible_rows:
        facts = result.facts_json or {}
        pulse = (facts.get("pulse") or {}).get("pulse") or RealizationPulse.JUSTIFIED.value
        weekly_by_user.setdefault(result.user_id, []).append(
            {
                "period_id": str(period.id),
                "week_start": period.start_date.isoformat(),
                "week_end": period.end_date.isoformat(),
                "pulse": pulse,
                "unresolved_pink_days": sum(
                    1
                    for item in facts.get("daily_timeline") or []
                    if int(item.get("unresolved_pink_count") or 0) > 0
                ) or (1 if int(facts.get("unresolved_pink_count") or 0) > 0 else 0),
                "verified_positive_extras": int((facts.get("pulse") or {}).get("verified_extra_count") or 0),
                "unresolved_negative_count": int((facts.get("pulse") or {}).get("unresolved_negative_count") or 0),
                "verified_negative_count": int((facts.get("counters") or {}).get("negative_count") or 0),
                "drilldown": {"week_start": period.start_date.isoformat()},
            }
        )
        departments[result.user_id] = result.department_id
    people = [
        RealizationMonthlyPersonOut(
            user_id=user_id,
            user_name=names.get(user_id, "Employee"),
            department_id=departments.get(user_id),
            aggregation=aggregate_monthly_pulses(weekly_rows),
        )
        for user_id, weekly_rows in sorted(weekly_by_user.items(), key=lambda item: names.get(item[0], ""))
    ]
    return RealizationMonthlyOut(
        month_start=start,
        month_end=end,
        department_id=department_id,
        department_name=department.name,
        people=people,
    )


@router.post(
    "/periods/{period_id}/results/{result_id}/questions/{question_key}",
    response_model=RealizationQuestionAnswerOut,
)
async def save_question_answer(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    question_key: str,
    payload: RealizationQuestionAnswerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationQuestionAnswerOut:
    period = await _period(db, period_id, for_update=True)
    try:
        require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    if period.period_type not in {"DAILY", "WEEKLY"} or not can_review_realization(
        user, department_id=period.department_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    if question_key not in MANDATORY_MANUAL_QUESTION_KEYS:
        raise HTTPException(status_code=422, detail="Question is not a manual manager question")
    if payload.clear:
        pass
    elif question_key in MANUAL_BOOLEAN_QUESTION_KEYS:
        if payload.value is not None and not isinstance(payload.value, bool):
            raise HTTPException(status_code=422, detail="Boolean questions accept Po or Jo")
    elif question_key in MANUAL_TEXT_QUESTION_KEYS:
        if not isinstance(payload.value, str) or not payload.value.strip():
            raise HTTPException(status_code=422, detail="This question requires manager text")

    result = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.id == result_id,
                RealizationPersonResult.period_id == period.id,
            )
        )
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="Person result not found")
    if payload.evidence_ids:
        question_support_ids = {
            str(value)
            for question in (result.facts_json or {}).get("questions") or []
            if question.get("key") == question_key
            for value in question.get("evidence_ids") or []
        }
        supplied_ids = {str(value) for value in payload.evidence_ids}
        observation_ids = {
            str(value)
            for value in (
            await db.execute(
                select(RealizationObservation.id).where(
                    RealizationObservation.id.in_(payload.evidence_ids),
                    RealizationObservation.period_id == period.id,
                    RealizationObservation.voided_at.is_(None),
                )
            )
            ).scalars().all()
        }
        if not supplied_ids.issubset(question_support_ids | observation_ids):
            raise HTTPException(status_code=422, detail="Linked evidence must belong to this period")
    try:
        target_period, target_result = await _weekly_answer_target(
            db, period=period, result=result, actor_id=user.id
        )
    except RealizationWorkflowError as exc:
        raise _error(exc)
    previous = (
        await db.execute(
            select(RealizationQuestionAnswer)
            .where(
                RealizationQuestionAnswer.result_id == target_result.id,
                RealizationQuestionAnswer.question_key == question_key,
            )
            .order_by(
                RealizationQuestionAnswer.answered_at.desc(),
                RealizationQuestionAnswer.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    answer = RealizationQuestionAnswer(
        period_id=target_period.id,
        result_id=target_result.id,
        question_key=question_key,
        value_json=(
            {"value": None, "cleared": True}
            if payload.clear
            else {"value": payload.value.strip() if isinstance(payload.value, str) else payload.value}
        ),
        comment=None if payload.clear else payload.comment.strip() if payload.comment and payload.comment.strip() else None,
        evidence_ids_json=[] if payload.clear else [str(item) for item in payload.evidence_ids],
        answered_by=user.id,
        answered_at=now,
        supersedes_answer_id=previous.id if previous else None,
        updated_at=now,
    )
    db.add(answer)
    # Invalidate both the dated report and its parent weekly analysis.
    mark_analysis_stale(result)
    if target_result is not result:
        mark_analysis_stale(target_result)
    if period.period_type == "DAILY":
        parent = await find_weekly_scope_period(db, period=period)
        if parent:
            parent_result = (await db.execute(select(RealizationPersonResult).where(
                RealizationPersonResult.period_id == parent.id,
                RealizationPersonResult.user_id == result.user_id,
            ))).scalar_one_or_none()
            if parent_result:
                mark_analysis_stale(parent_result)
    await db.flush()
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_question_answer",
        entity_id=answer.id,
        action="cleared" if payload.clear else "created" if previous is None else "corrected",
        before=_answer_payload(previous) if previous else None,
        after=_answer_payload(answer),
    )
    await db.commit()
    return RealizationQuestionAnswerOut.model_validate(
        {
            **_answer_payload(answer, user.full_name),
            "period_id": target_period.id,
            "result_id": target_result.id,
            "question_key": question_key,
        }
    )


@router.post(
    "/periods/{period_id}/users/{subject_user_id}/questions/{question_key}",
    response_model=RealizationQuestionAnswerOut,
)
async def save_person_question_answer(
    period_id: uuid.UUID, subject_user_id: uuid.UUID, question_key: str,
    payload: RealizationQuestionAnswerCreate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> RealizationQuestionAnswerOut:
    """Allow a weekly override even before the weekly result is calculated."""
    period = await _period(db, period_id, for_update=True)
    if not can_review_realization(user, department_id=period.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    subject = (await db.execute(select(User).where(User.id == subject_user_id))).scalar_one_or_none()
    if subject is None or period.department_id is None or subject.department_id != period.department_id:
        raise HTTPException(status_code=404, detail="Employee not found in this period")
    result = (await db.execute(select(RealizationPersonResult).where(
        RealizationPersonResult.period_id == period.id,
        RealizationPersonResult.user_id == subject_user_id,
    ))).scalar_one_or_none()
    if result is None:
        result = RealizationPersonResult(period_id=period.id, user_id=subject_user_id, department_id=period.department_id)
        db.add(result)
        await db.flush()
    return await save_question_answer(period_id=period.id, result_id=result.id, question_key=question_key, payload=payload, db=db, user=user)


@router.post(
    "/periods/{period_id}/results/{result_id}/review",
    response_model=RealizationPersonWorkflowOut,
)
async def review_person_result(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: RealizationReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationPersonWorkflowOut:
    period = await _period(db, period_id, for_update=True)
    if not can_review_realization(user, department_id=period.department_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if period.status != RealizationPeriodStatus.CALCULATED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Period is not awaiting review")
    result = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.id == result_id,
                RealizationPersonResult.period_id == period.id,
            )
        )
    ).scalar_one_or_none()
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person result not found")
    latest_answers = (
        await _weekly_manual_answers(db, period=period, user_ids=[result.user_id])
    ).get(result.user_id, {})
    review_facts = dict(result.facts_json or {})
    daily_evidence = {}
    await _attach_weekly_daily_evidence(db, period=period, daily_by_user=daily_evidence, user_ids=[result.user_id])
    # Include all applicable days so missing answers cannot become an implicit No.
    timeline = daily_evidence.setdefault(result.user_id, [])
    current_day = period.start_date
    while current_day <= period.end_date:
        if _is_working_day(current_day) and not any(d["date"] == current_day.isoformat() for d in timeline):
            timeline.append(_empty_timeline_day(current_day.isoformat()))
        current_day += timedelta(days=1)
    review_facts["daily_timeline"] = timeline
    apply_checklist_answers(
        review_facts,
        direct_answers={key: _answer_payload(answer) for key, answer in latest_answers.items()},
    )
    missing_manual = review_facts["manual_question_completeness"]["missing_keys"]
    if missing_manual:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RLZ_MANUAL_QUESTIONS_INCOMPLETE",
                "message": f"{review_facts['manual_question_completeness']['answered']} / {len(MANDATORY_MANUAL_QUESTION_KEYS)} pyetje manuale të plotësuara.",
                "missing_keys": missing_manual,
            },
        )
    final_symbol = payload.final_symbol or RealizationSymbol(result.suggested_symbol)
    final_level = payload.final_level or RealizationLevel(result.suggested_level)
    decision = payload.model_copy(
        update={
            "final_symbol": final_symbol,
            "final_level": final_level,
        }
    )


    try:
        decision.validate_against_suggestion(
            suggested_symbol=RealizationSymbol(result.suggested_symbol),
            suggested_level=RealizationLevel(result.suggested_level),
        )
    except ValueError as exc:
        raise _error(exc, status.HTTP_422_UNPROCESSABLE_ENTITY)
    before = {
        "final_symbol": result.final_symbol,
        "final_level": result.final_level,
    }
    result.final_symbol = final_symbol.value
    result.final_level = final_level.value
    result.final_bonus = None
    result.manager_comment = payload.manager_comment
    result.override_reason = payload.override_reason
    result.reviewed_by = user.id
    result.reviewed_at = datetime.now(timezone.utc)
    facts = review_facts
    known_question_keys = {
        str(question.get("key"))
        for question in facts.get("questions") or []
        if question.get("key")
    }
    unknown_question_keys = set(payload.question_values) - known_question_keys
    if unknown_question_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown question keys: {', '.join(sorted(unknown_question_keys))}",
        )
    questions = []
    for question in facts.get("questions") or []:
        item = dict(question)
        key = item.get("key")
        if key == "suggested_evaluation_level":
            item["final_value"] = final_level.value
            item["source_status"] = "MANAGER_CONFIRMED"
        elif key == "evaluation":
            item["final_value"] = final_symbol.value
            item["source_status"] = "MANAGER_CONFIRMED"
        elif key == "comments":
            item["final_value"] = {
                "automatic_narrative": result.auto_narrative,
                "manager_comment": payload.manager_comment,
                "override_reason": payload.override_reason,
            }
            item["source_status"] = "MANAGER_CONFIRMED"
        elif key in payload.question_values:
            item["final_value"] = payload.question_values[key]
            item["source_status"] = "MANAGER_CONFIRMED"
        questions.append(item)
    facts["questions"] = questions
    result.facts_json = facts
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_person_result",
        entity_id=result.id,
        action="reviewed",
        before=before,
        after={
            "final_symbol": result.final_symbol,
            "final_level": result.final_level,
            "override_reason": result.override_reason,
        },
    )
    await db.flush()
    remaining = (
        await db.execute(
            select(RealizationPersonResult.id).where(
                RealizationPersonResult.period_id == period.id,
                RealizationPersonResult.reviewed_at.is_(None),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if remaining is None:
        transition_period(period, RealizationPeriodStatus.REVIEWED, actor_id=user.id)
    await db.commit()
    await db.refresh(result)
    subject = (
        await db.execute(select(User).where(User.id == result.user_id))
    ).scalar_one()
    out = RealizationPersonResultOut.model_validate(result).model_dump()
    out["user_name"] = subject.full_name
    return RealizationPersonWorkflowOut.model_validate(out)


@router.post(
    "/periods/{period_id}/results/{result_id}/ai-analysis",
    response_model=RealizationAIAnalysisOut,
)
async def analyze_person_result(
    period_id: uuid.UUID,
    result_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationAIAnalysisOut:
    period = await _period(db, period_id, for_update=True)
    if not can_review_realization(user, department_id=period.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    result = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.id == result_id,
            )
        )
    ).scalar_one_or_none()
    if result is None or result.department_id != period.department_id:
        raise HTTPException(status_code=404, detail="Person result not found")
    if result.period_id != period.id:
        source_period = await _period(db, result.period_id)
        if (
            source_period.period_type != "DAILY"
            or source_period.department_id != period.department_id
            or source_period.start_date < period.start_date
            or source_period.end_date > period.end_date
        ):
            raise HTTPException(status_code=404, detail="Person result not found")
    department = await db.get(Department, period.department_id)
    weekly = await _weekly_response(
        db,
        period=period,
        user=user,
        department_name=department.name if department else None,
    )
    enriched_result = next((item for item in weekly.people if item.id == result.id), None)
    analysis_facts = enriched_result.facts_json if enriched_result else (result.facts_json or {})
    try:
        analysis = await analyze_realization(
            str(result.id),
            analysis_facts,
            suggested_level=result.suggested_level,
        )
    except RealizationAIError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    facts = dict(result.facts_json or {})
    new_entry = {
        **analysis,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": str(user.id),
    }
    # Every "Gjenero analizën" click is kept, not overwritten, so a manager
    # can see how the AI's read of a person changed across the week.
    history = list(facts.get("ai_analysis_history") or [])
    history.append(new_entry)
    facts["ai_analysis_history"] = history
    facts["ai_analysis"] = new_entry
    result.facts_json = facts
    record_analysis_state(result, analysis, datetime.now(timezone.utc))
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_person_result",
        entity_id=result.id,
        action="ai_analysis_generated",
        after={
            "model": analysis["model"],
            "suggested_level": analysis["suggested_level"],
            "advisory_only": True,
        },
    )
    await db.commit()
    return RealizationAIAnalysisOut.model_validate(analysis)


@router.post("/periods/{period_id}/approve", response_model=RealizationPeriodOut)
async def approve_period(
    period_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationPeriodOut:
    if not can_approve_realization(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    period = await _period(db, period_id, for_update=True)
    try:
        transition_period(period, RealizationPeriodStatus.APPROVED, actor_id=user.id)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    now = datetime.now(timezone.utc)
    results = (
        await db.execute(
            select(RealizationPersonResult).where(
                RealizationPersonResult.period_id == period.id
            )
        )
    ).scalars().all()
    for result in results:
        result.approved_by = user.id
        result.approved_at = now
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="realization_period",
        entity_id=period.id, action="approved",
        before={"status": "REVIEWED"}, after={"status": "APPROVED"},
    )
    await db.commit()
    await db.refresh(period)
    return RealizationPeriodOut.model_validate(period)


@router.post("/periods/{period_id}/lock", response_model=RealizationPeriodOut)
async def lock_period(
    period_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationPeriodOut:
    if not can_lock_realization(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    period = await _period(db, period_id, for_update=True)
    try:
        transition_period(period, RealizationPeriodStatus.LOCKED, actor_id=user.id)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="realization_period",
        entity_id=period.id, action="locked",
        before={"status": "APPROVED"}, after={"status": "LOCKED"},
    )
    await db.commit()
    await db.refresh(period)
    return RealizationPeriodOut.model_validate(period)


async def _daily_person_comment_context(
    db: AsyncSession, *, period_id: uuid.UUID, subject_user_id: uuid.UUID,
    actor: User, editing: bool,
) -> tuple[RealizationPeriod, bool]:
    period = await _period(db, period_id, for_update=editing)
    if period.period_type != "DAILY" or period.slot != "ALL" or period.department_id is None:
        raise HTTPException(status_code=422, detail="Daily comments require a daily department period")
    subject = (await db.execute(select(User).where(User.id == subject_user_id))).scalar_one_or_none()
    if subject is None or subject.department_id != period.department_id:
        raise HTTPException(status_code=404, detail="Employee not found in this daily period")
    if not can_view_person_result(
        actor, subject_user_id=subject_user_id, subject_department_id=period.department_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
    can_edit = can_review_realization(actor, department_id=period.department_id)
    if editing:
        if not can_edit:
            raise HTTPException(status_code=403, detail="Forbidden")
        try:
            require_unlocked(period)
        except RealizationWorkflowError as exc:
            raise _error(exc)
    return period, can_edit and period.status != RealizationPeriodStatus.LOCKED.value


async def _daily_person_comment(
    db: AsyncSession, *, period_id: uuid.UUID, user_id: uuid.UUID,
) -> RealizationDailyPersonComment | None:
    return (await db.execute(select(RealizationDailyPersonComment).where(
        RealizationDailyPersonComment.period_id == period_id,
        RealizationDailyPersonComment.user_id == user_id,
    ))).scalar_one_or_none()


def _daily_person_comment_out(
    period: RealizationPeriod, user_id: uuid.UUID, can_edit: bool,
    row: RealizationDailyPersonComment | None,
) -> RealizationDailyPersonCommentOut:
    return RealizationDailyPersonCommentOut(
        period_id=period.id, user_id=user_id, day=period.start_date, can_edit=can_edit,
        comment=row.comment if row else None,
        updated_by=row.updated_by if row else None,
        updated_at=row.updated_at if row else None,
    )


@router.get(
    "/periods/{period_id}/users/{subject_user_id}/daily-comment",
    response_model=RealizationDailyPersonCommentOut,
)
async def get_daily_person_comment(
    period_id: uuid.UUID, subject_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> RealizationDailyPersonCommentOut:
    period, can_edit = await _daily_person_comment_context(
        db, period_id=period_id, subject_user_id=subject_user_id, actor=user, editing=False,
    )
    row = await _daily_person_comment(db, period_id=period.id, user_id=subject_user_id)
    return _daily_person_comment_out(period, subject_user_id, can_edit, row)


@router.put(
    "/periods/{period_id}/users/{subject_user_id}/daily-comment",
    response_model=RealizationDailyPersonCommentOut,
)
async def put_daily_person_comment(
    period_id: uuid.UUID, subject_user_id: uuid.UUID, payload: RealizationDailyPersonCommentUpsert,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> RealizationDailyPersonCommentOut:
    period, can_edit = await _daily_person_comment_context(
        db, period_id=period_id, subject_user_id=subject_user_id, actor=user, editing=True,
    )
    row = await _daily_person_comment(db, period_id=period.id, user_id=subject_user_id)
    previous = row.comment if row else None
    if row is None and payload.comment is None:
        return _daily_person_comment_out(period, subject_user_id, can_edit, None)
    if row is None:
        row = RealizationDailyPersonComment(period_id=period.id, user_id=subject_user_id)
        db.add(row)
    row.comment = payload.comment
    row.updated_by = user.id
    await db.flush()
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="realization_daily_person_comment", entity_id=row.id,
        action="daily_comment_saved",
        before={"comment": previous},
        after={"comment": row.comment, "day": period.start_date.isoformat(), "user_id": str(subject_user_id)},
    )
    await db.commit()
    await db.refresh(row)
    return _daily_person_comment_out(period, subject_user_id, can_edit, row)


async def _manager_review_context(
    db: AsyncSession,
    *,
    period_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    actor: User,
    editing: bool,
) -> tuple[RealizationPeriod, User, bool]:
    period = await _period(db, period_id, for_update=editing)
    if period.period_type not in {
        RealizationPeriodType.DAILY.value,
        RealizationPeriodType.WEEKLY.value,
    }:
        raise HTTPException(status_code=422, detail="M3 review supports Daily and Weekly periods only")
    if period.department_id is None:
        raise HTTPException(status_code=422, detail="M3 review requires a department period")
    subject = (
        await db.execute(select(User).where(User.id == subject_user_id))
    ).scalar_one_or_none()
    if subject is None or subject.department_id != period.department_id:
        raise HTTPException(status_code=404, detail="Reviewed employee not found in this period")

    can_edit = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    can_view = can_edit or (
        actor.role == UserRole.STAFF and actor.id == subject_user_id
    )
    if editing and not can_edit:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not editing and not can_view:
        raise HTTPException(status_code=403, detail="Forbidden")
    # The rating and comment are one weekly judgment, recorded or corrected from
    # whichever day the manager happens to have open.
    try:
        if editing:
            period = await ensure_weekly_scope_period(db, period=period, created_by=actor.id)
        else:
            period = await find_weekly_scope_period(db, period=period) or period
        if editing:
            require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    return period, subject, can_edit and period.status != RealizationPeriodStatus.LOCKED.value


@router.get(
    "/periods/{period_id}/users/{subject_user_id}/manager-review",
    response_model=RealizationManagerReviewOut,
)
async def get_manager_review(
    period_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationManagerReviewOut:
    period, _subject, can_edit = await _manager_review_context(
        db,
        period_id=period_id,
        subject_user_id=subject_user_id,
        actor=user,
        editing=False,
    )
    return RealizationManagerReviewOut.model_validate(
        await build_manager_review_response(
            db,
            period_id=period.id,
            user_id=subject_user_id,
            can_edit=can_edit,
        )
    )


@router.put(
    "/periods/{period_id}/users/{subject_user_id}/manager-review/{dimension}",
    response_model=RealizationManagerReviewOut,
)
async def put_manager_review(
    period_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    dimension: str,
    payload: RealizationManagerReviewUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationManagerReviewOut:
    dimension = dimension.upper()
    if dimension not in M3_MANAGER_REVIEW_DIMENSIONS:
        raise HTTPException(status_code=422, detail="Review dimension must be PLANNING or REALIZATION")
    period, _subject, can_edit = await _manager_review_context(
        db,
        period_id=period_id,
        subject_user_id=subject_user_id,
        actor=user,
        editing=True,
    )
    if dimension == "REALIZATION" and payload.level is not None:
        weekly = await _weekly_response(db, period=period, user=user, department_name=None)
        person = next((item for item in weekly.people if item.user_id == subject_user_id), None)
        if person is None or (
            person.facts_json.get("availability_status") != "PV"
            and not (person.facts_json.get("manual_question_completeness") or {}).get("complete")
        ):
            raise HTTPException(status_code=409, detail="Plotëso dhe ruaj 9 përgjigjet para konfirmimit të shkronjës.")
    review = await upsert_manager_review(
        db,
        period_id=period.id,
        user_id=subject_user_id,
        department_id=period.department_id,
        dimension=dimension,
        marker=payload.marker,
        comment=payload.comment,
        actor_id=user.id,
        rating=payload.rating,
        level=payload.level,
        update_level="level" in payload.model_fields_set,
    )
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="realization_observation",
        entity_id=review.id,
        action="m3_manager_review_saved",
        after={
            "period_id": str(period.id),
            "user_id": str(subject_user_id),
            "dimension": dimension,
            "marker": review.marker,
            "rating": payload.rating,
            "level": (review.evidence_json or {}).get("review_level"),
        },
    )
    # A qualitative M3 review is evidence only: it intentionally does not
    # recalculate realization facts or invalidate a Daily Close snapshot.
    await db.commit()
    return RealizationManagerReviewOut.model_validate(
        await build_manager_review_response(
            db, period_id=period.id, user_id=subject_user_id, can_edit=can_edit
        )
    )


@router.delete(
    "/periods/{period_id}/users/{subject_user_id}/manager-review/{dimension}",
    response_model=RealizationManagerReviewOut,
)
async def delete_manager_review(
    period_id: uuid.UUID,
    subject_user_id: uuid.UUID,
    dimension: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationManagerReviewOut:
    dimension = dimension.upper()
    if dimension not in M3_MANAGER_REVIEW_DIMENSIONS:
        raise HTTPException(status_code=422, detail="Review dimension must be PLANNING or REALIZATION")
    period, _subject, can_edit = await _manager_review_context(
        db,
        period_id=period_id,
        subject_user_id=subject_user_id,
        actor=user,
        editing=True,
    )
    cleared = await clear_manager_review(
        db,
        period_id=period.id,
        user_id=subject_user_id,
        dimension=dimension,
        actor_id=user.id,
    )
    if not cleared:
        raise HTTPException(status_code=404, detail="Manager review not found")
    for review in cleared:
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="realization_observation",
            entity_id=review.id,
            action="m3_manager_review_cleared",
            before={"dimension": dimension, "marker": review.marker},
        )
    await db.commit()
    return RealizationManagerReviewOut.model_validate(
        await build_manager_review_response(
            db, period_id=period.id, user_id=subject_user_id, can_edit=can_edit
        )
    )


@router.post("/observations", response_model=RealizationObservationOut)
async def create_observation(
    payload: RealizationObservationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationObservationOut:
    if payload.source_type == M3_MANAGER_REVIEW_SOURCE:
        raise HTTPException(status_code=422, detail="Use the dedicated M3 manager-review endpoint")
    if payload.period_id is None:
        raise HTTPException(status_code=422, detail="period_id is required")
    period = await _period(db, payload.period_id, for_update=True)
    try:
        require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    _ensure_department_scope(user, period.department_id)
    subject_id = payload.user_id
    if not can_review_realization(user, department_id=period.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    if payload.department_id is not None and payload.department_id != period.department_id:
        raise HTTPException(status_code=422, detail="Observation department must match its period")
    if payload.scope_type in {RealizationScopeType.TASK, RealizationScopeType.SYSTEM_TASK}:
        if subject_id is None:
            raise HTTPException(status_code=422, detail="Task observations require user_id attribution")
        task = (
            await db.execute(select(Task).where(Task.id == payload.task_id))
        ).scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
    if subject_id is not None:
        subject = (
            await db.execute(select(User).where(User.id == subject_id))
        ).scalar_one_or_none()
        if subject is None or subject.department_id != period.department_id:
            raise HTTPException(
                status_code=422,
                detail="Observation subject must belong to the period department",
            )
    observation_data = payload.model_dump(mode="python")
    observation_data["department_id"] = period.department_id
    observation = RealizationObservation(
        **observation_data,
        is_system_generated=False,
        created_by=user.id,
    )
    db.add(observation)
    await db.flush()
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="realization_observation",
        entity_id=observation.id, action="created", after={"period_id": str(period.id)},
    )
    await _mark_ai_stale_for_subject(
        db, period_id=period.id, user_id=observation.user_id
    )
    await _recalculate_after_evidence(db, period=period, actor_id=user.id)
    await db.commit()
    await db.refresh(observation)
    return RealizationObservationOut.model_validate(observation)


@router.post("/observations/{observation_id}/verify", response_model=RealizationObservationOut)
async def verify_observation(
    observation_id: uuid.UUID,
    payload: RealizationObservationVerify,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationObservationOut:
    original = (
        await db.execute(
            select(RealizationObservation).where(
                RealizationObservation.id == observation_id,
                RealizationObservation.voided_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if original is None or original.period_id is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    if original.source_type == M3_MANAGER_REVIEW_SOURCE:
        raise HTTPException(status_code=422, detail="M3 manager reviews are not verification evidence")
    if original.source_type == "realization_observation_verification":
        raise HTTPException(status_code=422, detail="Verification events cannot be verified")
    period = await _period(db, original.period_id, for_update=True)
    try:
        require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    if not can_review_realization(user, department_id=period.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    existing = (
        await db.execute(
            select(RealizationObservation).where(
                RealizationObservation.period_id == period.id,
                RealizationObservation.source_type == "realization_observation_verification",
                RealizationObservation.source_id == original.id,
                RealizationObservation.voided_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return RealizationObservationOut.model_validate(existing)
    verification = RealizationObservation(
        period_id=period.id,
        scope_type=original.scope_type,
        task_id=original.task_id,
        user_id=original.user_id,
        project_id=original.project_id,
        department_id=period.department_id,
        marker=RealizationMarker.NEUTRAL.value,
        category=RealizationObservationCategory.OTHER.value,
        comment=payload.comment,
        evidence_json={"verified": True, "verification_of": str(original.id)},
        source_type="realization_observation_verification",
        source_id=original.id,
        is_system_generated=False,
        visibility=original.visibility,
        created_by=user.id,
    )
    db.add(verification)
    await db.flush()
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="realization_observation",
        entity_id=original.id, action="verified", after={"verification_id": str(verification.id)},
    )
    await _mark_ai_stale_for_subject(
        db, period_id=period.id, user_id=original.user_id
    )
    await _recalculate_after_evidence(db, period=period, actor_id=user.id)
    await db.commit()
    await db.refresh(verification)
    return RealizationObservationOut.model_validate(verification)


@router.post("/observations/{observation_id}/void", response_model=RealizationObservationOut)
async def void_observation(
    observation_id: uuid.UUID,
    payload: RealizationObservationVoid,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RealizationObservationOut:
    observation = (
        await db.execute(
            select(RealizationObservation).where(
                RealizationObservation.id == observation_id,
                RealizationObservation.voided_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if observation is None or observation.period_id is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    if observation.source_type == M3_MANAGER_REVIEW_SOURCE:
        raise HTTPException(status_code=422, detail="Use the dedicated M3 manager-review endpoint")
    period = await _period(db, observation.period_id, for_update=True)
    try:
        require_unlocked(period)
    except RealizationWorkflowError as exc:
        raise _error(exc)
    if not can_review_realization(user, department_id=period.department_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    observation.voided_at = datetime.now(timezone.utc)
    observation.voided_by = user.id
    observation.void_reason = payload.reason
    add_audit_log(
        db=db, actor_user_id=user.id, entity_type="realization_observation",
        entity_id=observation.id, action="voided",
        before={"voided_at": None}, after={"reason": payload.reason},
    )
    await _mark_ai_stale_for_subject(
        db, period_id=period.id, user_id=observation.user_id
    )
    await _recalculate_after_evidence(db, period=period, actor_id=user.id)
    await db.commit()
    await db.refresh(observation)
    return RealizationObservationOut.model_validate(observation)
