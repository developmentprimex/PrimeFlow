from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_task_occurrence import SystemTaskOccurrence
from app.models.system_task_template import SystemTaskTemplate
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.models.enums import CommonApprovalStatus
from app.services.system_task_schedule import matches_template_date
from app.services.system_task_instances import ensure_task_instances_in_range


OPEN = "OPEN"
DONE = "DONE"
NOT_DONE = "NOT_DONE"
SKIPPED = "SKIPPED"


async def _assignee_ids_for_template(db: AsyncSession, template_id: uuid.UUID) -> list[uuid.UUID]:
    """Get assignees from assignee_ids array in template."""
    tmpl = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == template_id))
    ).scalar_one_or_none()
    
    if not tmpl:
        return []
    
    # Get assignees from the array (safely handle NULL or missing field)
    assignee_ids = getattr(tmpl, 'assignee_ids', None) or []
    
    # Fallback to default_assignee_id if array is empty
    if not assignee_ids and tmpl.default_assignee_id:
        assignee_ids = [tmpl.default_assignee_id]
    
    if not assignee_ids:
        return []
    active_ids = set((await db.execute(
        select(User.id).where(User.work_staff_filter()).where(
            User.id.in_(assignee_ids), User.is_active.is_(True)
        )
    )).scalars().all())
    return [user_id for user_id in assignee_ids if user_id in active_ids]


def _template_start_date(template: SystemTaskTemplate) -> date | None:
    """First eligible schedule date for a template (creation boundary)."""
    created_at = getattr(template, "created_at", None)
    if created_at is None:
        return None
    if isinstance(created_at, datetime):
        if created_at.tzinfo is not None:
            try:
                local_tz = ZoneInfo(settings.APP_TIMEZONE)
            except Exception:
                local_tz = timezone.utc
            return created_at.astimezone(local_tz).date()
        return created_at.date()
    if isinstance(created_at, date):
        return created_at
    return None


def _is_occurrence_eligible_for_template(template: SystemTaskTemplate, occurrence_day: date) -> bool:
    template_start = _template_start_date(template)
    if template_start is not None and occurrence_day < template_start:
        return False
    return matches_template_date(template, occurrence_day)


async def ensure_occurrences_in_range(
    *,
    db: AsyncSession,
    start: date,
    end: date,
    template_ids: list[uuid.UUID] | None = None,
) -> None:
    """
    Back-compat wrapper.
    Also ensures task-backed system instances exist for the same range.
    """
    await ensure_task_instances_in_range(db=db, start=start, end=end)
    if end < start:
        return

    tmpl_stmt = (
        select(SystemTaskTemplate)
        .where(SystemTaskTemplate.is_active.is_(True))
        .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
    )
    if template_ids:
        tmpl_stmt = tmpl_stmt.where(SystemTaskTemplate.id.in_(template_ids))
    templates = (await db.execute(tmpl_stmt)).scalars().all()
    if not templates:
        return

    now = datetime.now(timezone.utc)
    current = start
    while current <= end:
        for tmpl in templates:
            if not _is_occurrence_eligible_for_template(tmpl, current):
                continue
            assignee_ids = await _assignee_ids_for_template(db, tmpl.id)
            if not assignee_ids:
                continue
            rows = [
                {
                    "id": uuid.uuid4(),
                    "template_id": tmpl.id,
                    "user_id": uid,
                    "occurrence_date": current,
                    "status": OPEN,
                    "created_at": now,
                    "updated_at": now,
                }
                for uid in assignee_ids
            ]
            stmt = pg_insert(SystemTaskOccurrence).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["template_id", "user_id", "occurrence_date"]
            )
            await db.execute(stmt)
        current += timedelta(days=1)


"""
NOTE:
Daily recurring tasks are configured to remain OPEN if missed, and show as overdue in Daily Report
until the user explicitly marks them DONE / NOT_DONE / SKIPPED.
"""

