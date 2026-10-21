"""Require and preserve an explanation in the date update's transaction."""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.user import User
from app.services.daily_realization_events import semantic_local_day
from app.services.daily_rlz_compliance import REASON_LABELS


def require_postponement_explanation(*, task, updates: dict, reason_code: str | None, comment: str | None) -> dict:
    changes = []
    for field in ("start_date", "due_date"):
        old, new = semantic_local_day(getattr(task, field, None)), semantic_local_day(updates.get(field))
        if field in updates and old and new and new > old:
            changes.append({"field": field, "from": old.isoformat(), "to": new.isoformat()})
    if not changes:
        return {}
    reason_code, comment = (reason_code or "").strip(), (comment or "").strip()
    if reason_code not in REASON_LABELS or not comment:
        raise HTTPException(status_code=409, detail={
            "code": "TASK_POSTPONEMENT_EXPLANATION_REQUIRED",
            "message": "Për ta shtyrë detyrën, zgjidh arsyen dhe plotëso komentin.",
            "task_id": str(task.id), "task_title": task.title, "changes": changes,
        })
    return {"reason_code": reason_code, "reason": REASON_LABELS[reason_code], "comment": comment}


def require_note_postponement_explanations(*, tasks, updates_by_assignee: dict, explanations: dict) -> dict:
    """Validate the entire bundle before applying any note or execution-state edits."""
    saved, missing = {}, []
    for task in tasks:
        if not task.is_active or task.assigned_to not in updates_by_assignee:
            continue
        explanation = explanations.get(task.id)
        try:
            saved[task.id] = require_postponement_explanation(
                task=task, updates=updates_by_assignee[task.assigned_to],
                reason_code=explanation.postponement_reason_code if explanation else None,
                comment=explanation.postponement_comment if explanation else None,
            )
        except HTTPException as error:
            missing.append({**error.detail, "assignee_id": str(task.assigned_to)})
    if missing:
        raise HTTPException(status_code=409, detail={
            "code": "TASK_POSTPONEMENT_EXPLANATION_REQUIRED",
            "message": "Për çdo detyrë të shtyrë, plotëso arsyen dhe komentin.",
            "postponements": missing,
        })
    return saved


async def check_note_postponement_explanations(db, **kwargs) -> dict:
    try:
        return require_note_postponement_explanations(**kwargs)
    except HTTPException as error:
        rows = error.detail["postponements"]
        owner_ids = {uuid.UUID(row["assignee_id"]) for row in rows if row.get("assignee_id") not in (None, "None")}
        owners = (await db.execute(select(User).where(User.id.in_(owner_ids)))).scalars().all() if owner_ids else []
        names = {str(owner.id): owner.full_name or owner.username or owner.email for owner in owners}
        for row in rows:
            row["assignee_name"] = names.get(row.get("assignee_id"))
        raise


async def save_postponement_daily_explanation(db, *, task_id, user_ids, explanation: dict) -> None:
    if not explanation or not user_ids:
        return
    day = datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()
    statement = insert(TaskDailyRlzState).values([
        {"task_id": task_id, "user_id": user_id, "day_date": day,
         "reason_code": explanation["reason_code"], "comment": explanation["comment"]}
        for user_id in sorted(set(user_ids), key=str)
    ])
    await db.execute(statement.on_conflict_do_update(
        constraint="uq_task_daily_rlz_state_task_user_day",
        set_={"reason_code": statement.excluded.reason_code, "comment": statement.excluded.comment,
              "updated_at": func.now()},
    ))
