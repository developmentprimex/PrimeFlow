"""Keep the symbol shared by a note and its linked task representations."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
GA_MARKER_EMAIL = "ga@primexeu.com"
ONE_H_MARKER_SYMBOLS = {
    "EXCLAMATION": "!",
    "CLIENT_URGENT": "!!!",
    "SHARE": "SHARE",
    "QUESTION": "?",
    "KA": "KA",
    "GENT": "GENT",
    "F": "F",
    "BZ1N1": "BZ1N1",
    "M2": "M2",
    "M3": "M3",
    "M2_M3": "M2/3",
    "FLAG": "GA",
    "MONITOR": "👁",
    "CLOSE": "X",
}


def one_h_marker_label(marker: str | None, marker_by_ga: bool = False) -> str:
    symbol = ONE_H_MARKER_SYMBOLS.get((marker or "").strip().upper(), "")
    return f"({symbol})" if symbol and marker_by_ga else symbol


def effective_marker_date(view_date: date, now: datetime | None = None) -> date:
    """Return the requested calendar date; task symbols no longer auto-refresh."""
    return view_date


def current_effective_marker_date(now: datetime | None = None) -> date:
    if now is None:
        from app.config import settings

        now = datetime.now(ZoneInfo(settings.APP_TIMEZONE))
    return now.date()


def marker_is_by_ga(actor_email: str | None) -> bool:
    return (actor_email or "").strip().casefold() == GA_MARKER_EMAIL


def normalize_marker_comment(marker: str | None, comment: str | None) -> str | None:
    normalized = (comment or "").strip()
    return normalized or None


def historical_marker_for_day(rows, target_date: date) -> tuple[str | None, bool, str | None] | None:
    """Resolve the last manual marker change effective on or before a day."""
    applicable = [row for row in rows if row.marker_date <= target_date]
    if not applicable:
        return None
    latest = max(applicable, key=lambda row: row.marker_date)
    marker = latest.one_h_marker
    return (
        marker,
        bool(marker and latest.one_h_marker_by_ga),
        latest.one_h_marker_comment,
    )


def active_one_h_marker(item, report_date=None, now=None) -> str | None:
    """Return the saved symbol until a user manually changes or removes it."""
    return getattr(item, "one_h_marker", None)


def active_one_h_marker_by_ga(item, report_date=None, now=None) -> bool:
    return bool(active_one_h_marker(item, report_date, now) and getattr(item, "one_h_marker_by_ga", False))


async def sync_note_task_marker(
    db: AsyncSession, note: GaNote | PlanNote, marker: str | None, *, actor_email: str | None = None,
    marker_comment: str | None = None,
) -> None:
    marker_date = current_effective_marker_date()
    marker_by_ga = bool(marker and marker_is_by_ga(actor_email))
    marker_comment = normalize_marker_comment(marker, marker_comment)
    previous_comment = note.one_h_marker_comment
    changed = (note.one_h_marker, note.one_h_marker_comment) != (marker, marker_comment)
    note.one_h_marker = marker
    note.one_h_marker_date = marker_date
    note.one_h_marker_by_ga = marker_by_ga
    note.one_h_marker_comment = marker_comment
    origin = Task.plan_note_origin_id if isinstance(note, PlanNote) else Task.ga_note_origin_id
    await db.execute(
        update(Task).where(origin == note.id, Task.is_active.is_(True)).values(
            one_h_marker=marker, one_h_marker_date=marker_date, one_h_marker_by_ga=marker_by_ga,
            one_h_marker_comment=marker_comment,
        )
    )
    if changed:
        from app.services.marker_comments import record_marker_change
        tasks = (await db.execute(select(Task).where(origin == note.id, Task.is_active.is_(True)))).scalars().all()
        from app.services.task_marker_comment_title import sync_comment_title

        await sync_comment_title(db, tasks, previous_comment, marker_comment, source_note=note)
        await record_marker_change(db, list(tasks), marker=marker, comment=marker_comment, actor_email=actor_email)


async def sync_task_marker(
    db: AsyncSession, task: Task, marker: str | None, *, actor_email: str | None = None,
    marker_comment: str | None = None,
) -> None:
    marker_date = current_effective_marker_date()
    marker_by_ga = bool(marker and marker_is_by_ga(actor_email))
    marker_comment = normalize_marker_comment(marker, marker_comment)
    previous_comment = task.one_h_marker_comment
    changed = (task.one_h_marker, task.one_h_marker_comment) != (marker, marker_comment)
    task.one_h_marker = marker
    task.one_h_marker_date = marker_date
    task.one_h_marker_by_ga = marker_by_ga
    task.one_h_marker_comment = marker_comment
    related = []
    if task.fast_task_group_id is not None:
        related.append(Task.fast_task_group_id == task.fast_task_group_id)
    for model, origin in ((GaNote, "ga_note_origin_id"), (PlanNote, "plan_note_origin_id")):
        note_id = getattr(task, origin, None)
        if note_id is not None:
            await db.execute(
                update(model).where(model.id == note_id).values(
                    one_h_marker=marker, one_h_marker_date=marker_date, one_h_marker_by_ga=marker_by_ga,
                    one_h_marker_comment=marker_comment,
                )
            )
            related.append(getattr(Task, origin) == note_id)
    if related:
        await db.execute(
            update(Task).where(or_(*related), Task.is_active.is_(True)).values(
                one_h_marker=marker, one_h_marker_date=marker_date, one_h_marker_by_ga=marker_by_ga,
                one_h_marker_comment=marker_comment,
            )
        )
    if changed:
        from app.services.marker_comments import record_marker_change
        tasks = (await db.execute(select(Task).where(
            or_(Task.id == task.id, *related), Task.is_active.is_(True),
        ))).scalars().all()
        from app.services.task_marker_comment_title import sync_comment_title

        await sync_comment_title(db, tasks, previous_comment, marker_comment)
        await record_marker_change(db, list(tasks), marker=marker, comment=marker_comment, actor_email=actor_email)


def note_bundle_marker_update(note, payload, tasks) -> tuple[bool, str | None]:
    """Ignore unchanged editor fields; accept a symbol edit from either control."""
    if "one_h_marker" in payload.model_fields_set and payload.one_h_marker != active_one_h_marker(note):
        return True, payload.one_h_marker
    if "one_h_marker_comment" in payload.model_fields_set:
        shared_marker = payload.one_h_marker if "one_h_marker" in payload.model_fields_set else active_one_h_marker(note)
        if normalize_marker_comment(shared_marker, payload.one_h_marker_comment) != getattr(note, "one_h_marker_comment", None):
            return True, shared_marker
    by_assignee = {task.assigned_to: active_one_h_marker(task) for task in tasks if task.is_active}
    changed = {
        state.one_h_marker
        for state in payload.assignee_states or []
        if "one_h_marker" in state.model_fields_set
        and state.one_h_marker != by_assignee.get(state.assignee_id, active_one_h_marker(note))
    }
    if len(changed) > 1:
        raise ValueError("Choose one symbol for the linked note and tasks")
    return (True, changed.pop()) if changed else (False, None)
