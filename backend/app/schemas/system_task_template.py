from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, Field

from app.models.enums import CommonApprovalStatus, FrequencyType, SystemTaskScope, TaskFinishPeriod, TaskPriority
from app.schemas.task import TaskAssigneeOut


class SystemTaskTemplateOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    internal_notes: str | None = None
    department_id: uuid.UUID | None = None
    department_ids: list[uuid.UUID] | None = None
    default_assignee_id: uuid.UUID | None = None
    assignee_ids: list[uuid.UUID] | None = None
    zv1_user_id: uuid.UUID | None = None
    zv2_user_id: uuid.UUID | None = None
    assignees: list[TaskAssigneeOut] = Field(default_factory=list)
    assignee_slots: list["SystemTaskTemplateAssigneeSlotOut"] = Field(default_factory=list)
    scope: SystemTaskScope
    frequency: FrequencyType
    day_of_week: int | None = None
    days_of_week: list[int] | None = None
    day_of_month: int | None = None
    month_of_year: int | None = None
    timezone: str = "Europe/Budapest"
    due_time: time = time(9, 0)
    lookahead: int = 14
    interval: int = 1
    apply_from: datetime | None = None
    duration_days: int = 1
    priority: TaskPriority | None = None
    finish_period: TaskFinishPeriod | None = None
    requires_alignment: bool = False
    alignment_time: time | None = None
    show_in_weekly_planner: bool = False
    is_repetitive: bool = False
    alignment_roles: list[str] | None = None
    alignment_user_ids: list[uuid.UUID] | None = None
    is_active: bool
    created_by_user_id: uuid.UUID | None = None
    approval_status: CommonApprovalStatus = CommonApprovalStatus.approved
    approved_by_user_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejected_by_user_id: uuid.UUID | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime


class SystemTaskTemplateCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    internal_notes: str | None = None
    department_id: uuid.UUID | None = None
    default_assignee_id: uuid.UUID | None = None
    assignee_ids: list[uuid.UUID] | None = None
    zv1_user_id: uuid.UUID | None = None
    zv2_user_id: uuid.UUID | None = None
    assignee_slots: list["SystemTaskTemplateAssigneeSlotIn"] | None = None
    scope: SystemTaskScope | None = None
    frequency: FrequencyType
    day_of_week: int | None = None
    days_of_week: list[int] | None = None
    day_of_month: int | None = None
    month_of_year: int | None = None
    timezone: str | None = None
    due_time: time | None = None
    lookahead: int | None = Field(default=None, ge=1)
    interval: int | None = Field(default=None, ge=1)
    apply_from: datetime | None = None
    duration_days: int | None = Field(default=None, ge=1)
    priority: TaskPriority | None = None
    finish_period: TaskFinishPeriod | None = None
    requires_alignment: bool | None = None
    alignment_time: time | None = None
    show_in_weekly_planner: bool | None = None
    is_repetitive: bool | None = None
    alignment_roles: list[str] | None = None
    alignment_user_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class SystemTaskTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = None
    internal_notes: str | None = None
    department_id: uuid.UUID | None = None
    default_assignee_id: uuid.UUID | None = None
    assignee_ids: list[uuid.UUID] | None = None
    zv1_user_id: uuid.UUID | None = None
    zv2_user_id: uuid.UUID | None = None
    assignee_slots: list["SystemTaskTemplateAssigneeSlotIn"] | None = None
    scope: SystemTaskScope | None = None
    frequency: FrequencyType | None = None
    day_of_week: int | None = None
    days_of_week: list[int] | None = None
    day_of_month: int | None = None
    month_of_year: int | None = None
    timezone: str | None = None
    due_time: time | None = None
    lookahead: int | None = Field(default=None, ge=1)
    interval: int | None = Field(default=None, ge=1)
    apply_from: datetime | None = None
    duration_days: int | None = Field(default=None, ge=1)
    priority: TaskPriority | None = None
    finish_period: TaskFinishPeriod | None = None
    requires_alignment: bool | None = None
    alignment_time: time | None = None
    show_in_weekly_planner: bool | None = None
    is_repetitive: bool | None = None
    alignment_roles: list[str] | None = None
    alignment_user_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class SystemTaskTemplateReject(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class SystemTaskTemplateAssigneeSlotIn(BaseModel):
    id: uuid.UUID | None = None
    primary_user_id: uuid.UUID
    is_active: bool | None = None


class SystemTaskTemplateAssigneeSlotOut(BaseModel):
    id: uuid.UUID
    primary_user_id: uuid.UUID
    is_active: bool

