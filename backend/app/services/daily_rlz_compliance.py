from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date as SQLDate, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.realization import RealizationDailyCloseEvent, RealizationPeriod
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.models.audit_log import AuditLog
from app.models.task import Task
from app.models.system_task_template import SystemTaskTemplate
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_daily_progress import TaskDailyProgress
from app.models.daily_planner_snapshot import DailyPlannerSnapshot
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.user import User
from app.models.department import Department
from app.models.enums import UserRole
from app.services.one_h_slots import effective_slot_date
from app.services.daily_realization_approval import daily_approval_state
from app.services.daily_realization_live import day_bounds, local_day
from app.services.daily_realization_events import semantic_local_day
from app.services.daily_realization_explanation import requires_daily_explanation
from app.services.daily_realization_close_state import resolve_daily_close_state

RLZ_CLOSE_OPEN = time(15, 30)
UNFINISHED = {"TODO", "IN_PROGRESS"}
REASON_DEFINITIONS = (
    ("TOOK_LONGER", "Mori më shumë kohë"),
    ("OTHER_URGENCY", "Urgjencë tjetër"),
    ("WAITING_CLIENT", "Në pritje të klientit"),
    ("PRIORITY_CHANGE", "Ndryshim prioriteti"),
    ("TECHNICAL_PROBLEM", "Problem teknik"),
    ("MISSING_INFORMATION", "Mungesë informacioni"),
    ("REQUEST_CHANGE", "Ndryshim kërkese"),
    ("NEW_REQUESTS", "Kerkesa te reja"),
    ("ABSENCE", "Mungesë"),
    ("OTHER", "Tjetër"),
)
REASON_LABELS = dict(REASON_DEFINITIONS)


def tirana_now() -> datetime:
    return datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE))


def next_working_day(day: date) -> date:
    result = day + timedelta(days=1)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def closable_from(day: date) -> datetime:
    return datetime.combine(day, RLZ_CLOSE_OPEN, tzinfo=ZoneInfo(settings.REALIZATION_TIMEZONE))


def is_editable_day(day: date, now: datetime | None = None) -> bool:
    """A report workday remains open for closing and later corrections."""
    return day.weekday() < 5 and is_explanation_editable_day(day, now)


def is_explanation_editable_day(day: date, now: datetime | None = None) -> bool:
    """Reasons and comments have no cutoff, including for past report days."""
    current = now or tirana_now()
    if current.tzinfo is not None:
        current = current.astimezone(ZoneInfo(settings.REALIZATION_TIMEZONE))
    return day <= current.date()


def is_closable_day(day: date, now: datetime | None = None) -> bool:
    """Daily RLZ can be saved from 15:30 onward, with no expiration."""
    current = now or tirana_now()
    return is_editable_day(day, current) and current >= closable_from(day)


def task_issue_codes(*, status: str, due_date: date | None, requires_one_h_slot: bool,
                     one_h_report_slot: str | None, reason_code: str | None,
                     comment: str | None = None, day: date,
                     is_system_task: bool = False,
                     deadline_was_today: bool = False,
                     postponed_today: bool = False) -> list[str]:
    if status not in UNFINISHED:
        return []
    issues: list[str] = []
    requirement = requires_daily_explanation(
        status=status, selected_day=day, deadline=due_date,
        deadline_was_today=deadline_was_today, postponed_today=postponed_today,
    )
    if requirement.reason_required and not reason_code:
        issues.append("REASON_MISSING")
    if requirement.comment_required and not (comment or "").strip():
        issues.append("COMMENT_MISSING")
    if requirement.comment_required and reason_code == "OTHER" and not (comment or "").strip() and "COMMENT_MISSING" not in issues:
        issues.append("COMMENT_MISSING")
    if not is_system_task and (due_date is None or due_date <= day):
        issues.append("DUE_DATE_NOT_MOVED")
    if not is_system_task and requires_one_h_slot and not one_h_report_slot:
        issues.append("ONE_H_SLOT_MISSING")
    return issues


ISSUE_MESSAGES = {
    "REASON_MISSING": "Mungon arsyeja",
    "COMMENT_MISSING": "Arsyeja Tjetër kërkon koment shpjegues",
    "DUE_DATE_NOT_MOVED": "Deadline-i duhet shtyrë për ditën tjetër të punës ose më vonë",
    "ONE_H_SLOT_MISSING": "Mungon 1H sloti",
}
ISSUE_MESSAGES["COMMENT_MISSING"] = "Mungon komenti"


async def relevant_tasks(db: AsyncSession, *, user_id: uuid.UUID, day: date) -> list[Task]:
    # Mirrors the regular-task membership used by Daily Report: assigned active tasks
    # with a due date that are current/overdue for the selected workday.
    rows = (await db.execute(
        select(Task)
        .outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id)
        .outerjoin(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
        .where(
            Task.is_active.is_(True), Task.due_date.is_not(None),
            Task.question_origin_id.is_(None),
            Task.question_batch_date.is_(None),
            or_(
                Task.system_template_origin_id.is_(None),
                SystemTaskTemplate.show_in_weekly_planner.is_(True),
            ),
            or_(
                Task.system_template_origin_id.is_(None),
                cast(
                    func.timezone(
                    func.coalesce(SystemTaskTemplate.timezone, settings.REALIZATION_TIMEZONE),
                        func.coalesce(Task.origin_run_at, Task.start_date, Task.due_date),
                    ),
                    SQLDate,
                ) == day,
            ),
            or_(Task.assigned_to == user_id, TaskAssignee.user_id == user_id),
            func.date(func.coalesce(Task.start_date, Task.due_date)) <= day,
        ).distinct().order_by(Task.due_date, Task.created_at)
    )).scalars().all()
    result = {task.id: task for task in rows}
    primary_statement = getattr(db, "statement", None)
    # The immutable baseline and same-day semantic events keep a task in Daily
    # RLZ even after a deadline/start-date mutation moves it out of the live
    # membership predicate.
    snapshots = (await db.execute(select(DailyPlannerSnapshot).where(DailyPlannerSnapshot.day_date == day))).scalars().all()
    baseline_ids: set[uuid.UUID] = set()
    for snapshot in snapshots:
        for person in (snapshot.payload or {}).get("people", []):
            if str(person.get("user_id")) != str(user_id):
                continue
            for item in person.get("tasks") or []:
                try:
                    baseline_ids.add(uuid.UUID(str(item.get("task_id"))))
                except (TypeError, ValueError):
                    pass
    event_rows = (await db.execute(select(AuditLog).where(
        AuditLog.entity_type == "task", AuditLog.action.in_(("task.due_date_changed", "task.assignee_changed")),
        AuditLog.created_at >= day_bounds(day)[0], AuditLog.created_at <= day_bounds(day)[1],
    ))).scalars().all()
    event_ids: set[uuid.UUID] = set(baseline_ids)
    assignment_history_ids: set[uuid.UUID] = set()
    for event in event_rows:
        before, after = event.before or {}, event.after or {}
        owners = set(before.get("assignee_ids", [])) | set(after.get("assignee_ids", []))
        old_day = semantic_local_day(before.get("value")); new_day = semantic_local_day(after.get("value"))
        if str(user_id) in owners:
            assignment_history_ids.add(event.entity_id)
        if str(user_id) in owners or old_day == day or new_day == day:
            event_ids.add(event.entity_id)
    missing_ids = event_ids - set(result)
    if missing_ids:
        extra = (await db.execute(select(Task).outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id).where(
            Task.id.in_(missing_ids), or_(
                Task.assigned_to == user_id, TaskAssignee.user_id == user_id,
                Task.id.in_(baseline_ids), Task.id.in_(assignment_history_ids),
            )
        ).distinct())).scalars().all()
        result.update({task.id: task for task in extra})
    if primary_statement is not None and hasattr(db, "statement"):
        db.statement = primary_statement
    def sort_key(task: Task) -> tuple[date, str]:
        raw_due = task.due_date
        due_day = raw_due.date() if isinstance(raw_due, datetime) else raw_due or day
        created_key = task.created_at.isoformat() if task.created_at else ""
        return due_day, created_key

    return sorted(result.values(), key=sort_key)


async def build_daily_rlz_compliance(db: AsyncSession, *, user_id: uuid.UUID, day: date,
                                     now: datetime | None = None) -> dict:
    tasks = await relevant_tasks(db, user_id=user_id, day=day)
    task_ids = [task.id for task in tasks]
    baseline_due: dict[uuid.UUID, date | None] = {}
    for snapshot in (await db.execute(select(DailyPlannerSnapshot).where(DailyPlannerSnapshot.day_date == day))).scalars().all():
        for person in (snapshot.payload or {}).get("people", []):
            if str(person.get("user_id")) != str(user_id):
                continue
            for item in person.get("tasks") or []:
                try:
                    tid = uuid.UUID(str(item.get("task_id")))
                except (TypeError, ValueError):
                    continue
                raw_due = item.get("planned_due_date")
                baseline_due[tid] = date.fromisoformat(str(raw_due)[:10]) if raw_due else None
    states = {}
    slots = {}
    if task_ids:
        states = {row.task_id: row for row in (await db.execute(select(TaskDailyRlzState).where(
            TaskDailyRlzState.user_id == user_id, TaskDailyRlzState.day_date == day,
            TaskDailyRlzState.task_id.in_(task_ids),
        ))).scalars().all()}
        daily_progress = {row.task_id: row for row in (await db.execute(select(TaskDailyProgress).where(
            TaskDailyProgress.task_id.in_(task_ids), TaskDailyProgress.day_date == day,
        ))).scalars().all()}
        slot_rows = (await db.execute(select(
            TaskOneHReportSlot.task_id, TaskOneHReportSlot.one_h_report_slot, TaskOneHReportSlot.updated_at
        ).where(
            TaskOneHReportSlot.task_id.in_(task_ids),
            TaskOneHReportSlot.report_date == effective_slot_date(day, now),
        ))).all()
        slots = {task_id: slot for task_id, slot, _ in slot_rows}
        slot_changed = {task_id: updated_at for task_id, _, updated_at in slot_rows}
    else:
        slot_changed = {}
        daily_progress = {}
    audit_start, audit_end = day_bounds(day)
    semantic_events = (await db.execute(select(AuditLog).where(
        AuditLog.entity_type == "task", AuditLog.entity_id.in_(task_ids or []),
        AuditLog.action.like("task.%"), AuditLog.created_at >= audit_start,
        AuditLog.created_at <= audit_end,
    ))).scalars().all() if task_ids else []
    events_by_task: dict[uuid.UUID, list[AuditLog]] = {}
    for event in semantic_events:
        events_by_task.setdefault(event.entity_id, []).append(event)
    evidence = []
    blockers = []
    latest_change: datetime | None = None
    minimum_due = next_working_day(day)
    for task in tasks:
        state = states.get(task.id)
        status = "DONE" if task.completed_at else str(getattr(task.status, "value", task.status))
        due = local_day(task.due_date)
        slot = slots.get(task.id) or task.one_h_report_slot
        reason = state.reason_code if state else None
        comment = state.comment if state else None
        task_events = events_by_task.get(task.id, [])
        due_events = [event for event in task_events if event.action == "task.due_date_changed"]
        baseline_deadline = baseline_due.get(task.id)
        deadline_was_today = bool(baseline_deadline == day or (task.id not in baseline_due and due == day)) or any(
            semantic_local_day((event.before or {}).get("value")) == day for event in due_events
        )
        had_postponement_event = any(
            semantic_local_day((event.before or {}).get("value")) == day
            and semantic_local_day((event.after or {}).get("value"))
            and semantic_local_day((event.after or {}).get("value")) > day
            for event in due_events
        )
        postponed_today = bool(had_postponement_event and due and due > day)
        issue_codes = task_issue_codes(status=status, due_date=due,
                                       requires_one_h_slot=bool(task.is_1h_report or task.is_r1),
                                       one_h_report_slot=slot, reason_code=reason, comment=comment, day=day,
                                       is_system_task=task.system_template_origin_id is not None,
                                       deadline_was_today=deadline_was_today,
                                       postponed_today=postponed_today)
        requirement = requires_daily_explanation(
            status=status, selected_day=day, deadline=due,
            deadline_was_today=deadline_was_today, postponed_today=postponed_today,
        )
        item = {
            "task_id": str(task.id), "title": task.title, "status": status,
            "due_date": due.isoformat() if due else None, "one_h_report_slot": slot,
            "reason_code": reason, "reason_label": REASON_LABELS.get(reason),
            "comment": comment,
            "source_type": "system" if task.system_template_origin_id else "project" if task.project_id else "fast",
            "planned_due_date": baseline_deadline.isoformat() if baseline_deadline else None,
            "requires_explanation": requirement.requires_explanation,
            "reason_required": requirement.reason_required,
            "comment_required": requirement.comment_required,
            "reason_missing": requirement.reason_required and not reason,
            "comment_missing": requirement.comment_required and not (comment or "").strip(),
            "deadline_was_today": deadline_was_today,
            "deadline_is_overdue": bool(due and due < day and status != "DONE"),
            "postponed_today": postponed_today,
        }
        evidence.append(item)
        if issue_codes:
            blockers.append({
                "task_id": str(task.id), "title": task.title, "status": status,
                "due_date": item["due_date"], "minimum_due_date": minimum_due.isoformat(),
                "one_h_report_slot": slot, "reason_code": reason,
                "reason_label": REASON_LABELS.get(reason), "comment": item["comment"],
                "issues": [{"code": code, "message": ISSUE_MESSAGES[code]} for code in issue_codes],
            })
        for changed in (task.updated_at, state.updated_at if state else None,
                        daily_progress.get(task.id).updated_at if daily_progress.get(task.id) else None,
                        slot_changed.get(task.id)):
            if changed and (latest_change is None or changed > latest_change):
                latest_change = changed
    latest_close = (await db.execute(
        select(RealizationDailyCloseEvent).join(RealizationPeriod, RealizationPeriod.id == RealizationDailyCloseEvent.period_id).where(
            RealizationDailyCloseEvent.user_id == user_id, RealizationPeriod.period_type == "DAILY",
            RealizationPeriod.start_date == day,
        ).order_by(RealizationDailyCloseEvent.created_at.desc(), RealizationDailyCloseEvent.id.desc()).limit(1)
    )).scalar_one_or_none()
    user_key = str(user_id)
    for event in semantic_events:
        before_ids = (event.before or {}).get("assignee_ids", [])
        after_ids = (event.after or {}).get("assignee_ids", [])
        if event.entity_id in task_ids or user_key in before_ids or user_key in after_ids:
            if latest_change is None or event.created_at > latest_change:
                latest_change = event.created_at
    adjustments = (await db.execute(select(DailyPlanAdjustment).where(
        DailyPlanAdjustment.user_id == user_id,
        DailyPlanAdjustment.day_date == day,
    ))).scalars().all()
    for adjustment in adjustments:
        changed = adjustment.decided_at or adjustment.created_at
        if changed and (latest_change is None or changed > latest_change):
            latest_change = changed
    close_status, saved, stale = resolve_daily_close_state(
        latest_action=latest_close.action if latest_close else None,
        close_created_at=latest_close.created_at if latest_close else None,
        latest_relevant_change=latest_change,
        editable=is_editable_day(day, now),
    )
    manager_approval = await daily_approval_state(
        db, user_id=user_id, day=day, personal_close_status=close_status
    )
    return {
        "day": day.isoformat(), "user_id": str(user_id), "tasks": evidence, "blockers": blockers,
        "manager_approval": manager_approval,
        "compliant": not blockers, "rlz_close_state": {
            "status": close_status, "saved": saved, "stale": stale,
            "saved_at": latest_close.created_at.isoformat() if saved and latest_close else None,
            "closed_by_user_id": str(latest_close.actor_user_id) if saved and latest_close and latest_close.actor_user_id else None,
            "is_editable": is_closable_day(day, now),
            "closable_from": closable_from(day).isoformat(),
            "editable_until": None,
        },
    }


async def build_daily_rlz_control(db: AsyncSession, *, day: date, department_id: uuid.UUID | None = None,
                                  user_id: uuid.UUID | None = None) -> dict:
    stmt = select(User).where(User.is_active.is_(True), User.department_id.is_not(None), User.role == UserRole.STAFF)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if user_id:
        stmt = stmt.where(User.id == user_id)
    users = (await db.execute(stmt.order_by(User.department_id, User.full_name, User.email))).scalars().all()
    department_ids = {subject.department_id for subject in users if subject.department_id}
    departments = {row.id: row.name for row in (await db.execute(
        select(Department).where(Department.id.in_(department_ids))
    )).scalars().all()} if department_ids else {}
    people, totals = [], {"employees_checked": 0, "employees_not_saved": 0, "employees_stale": 0,
                         "employees_approval_pending": 0, "employees_approval_stale": 0,
                         "tasks_missing_reason": 0, "tasks_missing_comment": 0,
                         "tasks_deadline_not_moved": 0, "tasks_missing_slot": 0}
    for subject in users:
        report = await build_daily_rlz_compliance(db, user_id=subject.id, day=day)
        totals["employees_checked"] += 1
        state = report["rlz_close_state"]["status"]
        if state in {"NOT_SAVED", "CLOSED_EDIT_WINDOW"}: totals["employees_not_saved"] += 1
        if state == "STALE": totals["employees_stale"] += 1
        approval_status = report["manager_approval"]["status"]
        if approval_status in {"PENDING", "REVOKED"}: totals["employees_approval_pending"] += 1
        if approval_status == "STALE": totals["employees_approval_stale"] += 1
        for blocker in report["blockers"]:
            codes = {issue["code"] for issue in blocker["issues"]}
            totals["tasks_missing_reason"] += int("REASON_MISSING" in codes)
            totals["tasks_missing_comment"] += int("COMMENT_MISSING" in codes)
            totals["tasks_deadline_not_moved"] += int("DUE_DATE_NOT_MOVED" in codes)
            totals["tasks_missing_slot"] += int("ONE_H_SLOT_MISSING" in codes)
        if report["blockers"] or state != "SAVED" or approval_status != "APPROVED":
            people.append({"user_id": str(subject.id), "employee": subject.full_name or subject.username or subject.email,
                           "department_id": str(subject.department_id), "department": departments.get(subject.department_id, "—"), **report})
    totals["departments_checked"] = len({person.department_id for person in users})
    return {"day": day.isoformat(), "summary": totals, "people": people, "all_good": not people}
