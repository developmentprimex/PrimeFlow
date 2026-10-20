"""Require and preserve an explanation in the date update's transaction."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models.task_daily_rlz_state import TaskDailyRlzState
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
