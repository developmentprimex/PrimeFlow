from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import ProjectPhaseStatus, TaskFinishPeriod, TaskPriority, TaskSkillCategory, TaskStatus
from app.schemas.plan_note import PxJavPlanningBrief


class TaskAssigneeOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    username: str | None = None
    full_name: str | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    internal_notes: str | None = None
    skill_category: TaskSkillCategory | None = None
    project_id: uuid.UUID | None = None
    dependency_task_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None
    confirmation_assignee_id: uuid.UUID | None = None
    assignees: list[TaskAssigneeOut] = Field(default_factory=list)
    created_by: uuid.UUID | None = None
    ga_note_origin_id: uuid.UUID | None = None
    plan_note_origin_id: uuid.UUID | None = None
    planning_brief: PxJavPlanningBrief | None = None
    question_origin_id: uuid.UUID | None = None
    system_template_origin_id: uuid.UUID | None = None
    origin_run_at: datetime | None = None
    system_task_slot_id: uuid.UUID | None = None
    meeting_origin_id: uuid.UUID | None = None
    meeting_occurrence_date: date | None = None
    meeting_system_task_kind: str | None = None
    status: TaskStatus
    priority: TaskPriority
    finish_period: TaskFinishPeriod | None = None
    phase: ProjectPhaseStatus
    progress_percentage: int
    daily_products: int | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    original_due_date: datetime | None = None
    planned_date: datetime | None = None
    late_days: int | None = None
    moved_days: int | None = None
    completed_at: datetime | None = None
    is_deadline_important: bool
    is_bllok: bool
    is_1h_report: bool
    one_h_report_slot: str | None = None
    one_h_marker: str | None = None
    one_h_marker_by_ga: bool = False
    one_h_marker_comment: str | None = None
    is_r1: bool
    is_personal: bool
    fast_task_order: int | None = None
    is_active: bool
    user_comment: str | None = None
    alignment_user_ids: list[uuid.UUID] | None = None
    created_at: datetime
    updated_at: datetime


class GaNoteTaskSummaryOut(BaseModel):
    """Lean task shape used by the GA/KA notes dashboard."""

    id: uuid.UUID
    description: str | None = None
    skill_category: TaskSkillCategory | None = None
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None
    confirmation_assignee_id: uuid.UUID | None = None
    assignees: list[TaskAssigneeOut] = Field(default_factory=list)
    ga_note_origin_id: uuid.UUID | None = None
    plan_note_origin_id: uuid.UUID | None = None
    status: TaskStatus
    priority: TaskPriority
    finish_period: TaskFinishPeriod | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    is_deadline_important: bool
    is_bllok: bool
    is_1h_report: bool
    one_h_report_slot: str | None = None
    one_h_marker: str | None = None
    one_h_marker_comment: str | None = None
    is_r1: bool
    is_personal: bool
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=2)
    description: str | None = Field(default=None)
    internal_notes: str | None = None
    skill_category: TaskSkillCategory | None = None
    project_id: uuid.UUID | None = None
    dependency_task_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = Field(default=None)
    assigned_to: uuid.UUID | None = None
    confirmation_assignee_id: uuid.UUID | None = None
    assignees: list[uuid.UUID] | None = None
    ga_note_origin_id: uuid.UUID | None = None
    plan_note_origin_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    finish_period: TaskFinishPeriod | None = None
    phase: ProjectPhaseStatus | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    daily_products: int | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    is_deadline_important: bool | None = None
    is_bllok: bool | None = None
    is_1h_report: bool | None = None
    one_h_report_slot: str | None = Field(default=None, pattern=r"^(10:00|11:00|11:50|14:20|16:00)$")
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    is_r1: bool | None = None
    is_personal: bool | None = None
    fast_task_order: int | None = Field(default=None, ge=1)
    alignment_user_ids: list[uuid.UUID] | None = None
    completion_override_reason: str | None = Field(default=None, max_length=2000, exclude=True)


class TaskRemoveFromDayRequest(BaseModel):
    day_date: date
    user_id: uuid.UUID
    time_slot: str | None = None


class TaskUpdate(BaseModel):
    postponement_reason_code: str | None = Field(default=None, max_length=40, exclude=True)
    postponement_comment: str | None = Field(default=None, max_length=10000, exclude=True)
    title: str | None = Field(default=None, min_length=2)
    description: str | None = Field(default=None)
    internal_notes: str | None = None
    skill_category: TaskSkillCategory | None = None
    project_id: uuid.UUID | None = None
    dependency_task_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None
    confirmation_assignee_id: uuid.UUID | None = None
    assignees: list[uuid.UUID] | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    finish_period: TaskFinishPeriod | None = None
    phase: ProjectPhaseStatus | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    daily_products: int | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    is_deadline_important: bool | None = None
    is_bllok: bool | None = None
    is_1h_report: bool | None = None
    one_h_report_slot: str | None = Field(default=None, pattern=r"^(10:00|11:00|11:50|14:20|16:00)$")
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    is_r1: bool | None = None
    is_personal: bool | None = None
    fast_task_order: int | None = Field(default=None, ge=1)
    alignment_user_ids: list[uuid.UUID] | None = None
    completion_override_reason: str | None = Field(default=None, max_length=2000, exclude=True)
