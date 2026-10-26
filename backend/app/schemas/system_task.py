from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field

from app.models.enums import CommonApprovalStatus, FrequencyType, SystemTaskScope, TaskFinishPeriod, TaskPriority, TaskStatus
from app.schemas.task import TaskAssigneeOut


class SystemTaskOut(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    title: str
    description: str | None = None
    internal_notes: str | None = None
    department_id: uuid.UUID | None = None
    department_ids: list[uuid.UUID] | None = None  # All departments from assignees
    default_assignee_id: uuid.UUID | None = None
    assignees: list[TaskAssigneeOut] = Field(default_factory=list)
    scope: SystemTaskScope
    frequency: FrequencyType
    day_of_week: int | None = None
    days_of_week: list[int] | None = None
    day_of_month: int | None = None
    month_of_year: int | None = None
    occurrence_date: date | None = None
    next_occurrence_date: date | None = None
    effective_occurrence_date: date | None = None
    priority: TaskPriority
    finish_period: TaskFinishPeriod | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    status: TaskStatus
    is_active: bool
    user_comment: str | None = None
    requires_alignment: bool | None = None
    alignment_time: time | None = None
    show_in_weekly_planner: bool = False
    is_repetitive: bool = False
    alignment_roles: list[str] | None = None
    alignment_user_ids: list[uuid.UUID] | None = None
    created_by: uuid.UUID | None = None
    approval_status: CommonApprovalStatus | None = None
    created_at: datetime
