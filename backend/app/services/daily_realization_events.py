from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.services.audit import add_audit_log


SEMANTIC_FIELDS = {
    "status": "task.status_changed",
    "progress_percentage": "task.progress_changed",
    "due_date": "task.due_date_changed",
    "start_date": "task.start_date_changed",
    "finish_period": "task.finish_period_changed",
    "is_active": "task.reactivated",
}


def semantic_local_day(raw: Any) -> date | None:
    """Normalize an audited date/datetime to the configured operational day."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, date):
        return raw
    else:
        text = str(raw)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()


def task_semantic_state(task) -> dict[str, Any]:
    """Return a stable, JSON-safe view of fields relevant to daily realization."""
    def value(raw):
        if isinstance(raw, datetime):
            return raw.isoformat()
        return getattr(raw, "value", raw)

    return {
        "status": value(task.status),
        "progress_percentage": task.progress_percentage,
        "due_date": value(task.due_date),
        "start_date": value(task.start_date),
        "finish_period": value(task.finish_period),
        "is_active": bool(task.is_active),
        "assigned_to": task.assigned_to,
    }


def postponement_explanation_from_events(events) -> dict:
    """Read the last explained forward date move, leaving legacy daily input intact."""
    explained = [event for event in events if (event.after or {}).get("reason") and (event.after or {}).get("comment")]
    for event in sorted(explained, key=lambda item: (item.created_at, str(item.id)), reverse=True):
        if event.action not in {"task.start_date_changed", "task.due_date_changed"}:
            continue
        before, after = event.before or {}, event.after or {}
        old, new = semantic_local_day(before.get("value")), semantic_local_day(after.get("value"))
        if old and new and new > old and after.get("reason") and after.get("comment"):
            return {"reason": after["reason"], "comment": after["comment"], "postponement_explanation": True}
    return {}


def record_task_semantic_events(
    *, db, task_id: uuid.UUID, actor_user_id: uuid.UUID | None,
    before: dict[str, Any], after: dict[str, Any],
    old_assignee_ids: Iterable[uuid.UUID] = (), new_assignee_ids: Iterable[uuid.UUID] = (),
    reason: str | None = None,
    reason_code: str | None = None, comment: str | None = None,
) -> list:
    """Append one AuditLog row per meaningful change in the caller's transaction."""
    events = []
    local_day = datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()
    metadata = {"day": local_day.isoformat(), "reason": reason}
    if reason_code is not None:
        metadata["reason_code"] = reason_code
    if comment is not None:
        metadata["comment"] = comment
    for field, action in SEMANTIC_FIELDS.items():
        old, new = before.get(field), after.get(field)
        if old == new:
            continue
        actual_action = action
        if field == "status" and str(old).upper() == "DONE" and str(new).upper() != "DONE":
            actual_action = "task.reopened"
        elif field == "is_active":
            actual_action = "task.reactivated" if bool(new) else "task.deactivated"
        event = add_audit_log(
            db=db, actor_user_id=actor_user_id, entity_type="task", entity_id=task_id,
            action=actual_action, before={"field": field, "value": old, **metadata},
            after={"field": field, "value": new, **metadata},
        )
        events.append(event)
        if field == "due_date" and semantic_local_day(new) and semantic_local_day(old) and semantic_local_day(new) > semantic_local_day(old):
            for user_id in set(old_assignee_ids):
                db.add(DailyPlanAdjustment(
                    audit_event_id=event.id, task_id=task_id, user_id=user_id,
                    day_date=local_day, adjustment_type="POSTPONEMENT", reason=reason,
                    created_by=actor_user_id,
                ))

    old_ids, new_ids = set(old_assignee_ids), set(new_assignee_ids)
    if old_ids != new_ids:
        event = add_audit_log(
            db=db, actor_user_id=actor_user_id, entity_type="task", entity_id=task_id,
            action="task.assignee_changed",
            before={"assignee_ids": sorted(map(str, old_ids)), **metadata},
            after={"assignee_ids": sorted(map(str, new_ids)), **metadata},
        )
        events.append(event)
    return events
