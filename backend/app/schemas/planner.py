from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.project import ProjectOut
from app.schemas.task import TaskOut
from app.models.enums import TaskStatus


class WeeklyPlannerDay(BaseModel):
    date: date
    tasks: list[TaskOut]


class WeeklyPlannerProject(BaseModel):
    project: ProjectOut
    tasks: list[TaskOut]


class WeeklyPlannerResponse(BaseModel):
    week_start: date
    week_end: date
    overdue: list[TaskOut]
    projects: list[WeeklyPlannerProject]
    fast_tasks: list[TaskOut]
    days: list[WeeklyPlannerDay]


class WeeklyTableProjectTaskEntry(BaseModel):
    """A task within a project entry in the weekly table"""
    task_id: uuid.UUID
    task_title: str
    phase: str | None = None
    status: TaskStatus = TaskStatus.TODO
    # Optional per-day status override (driven by task_daily_progress).
    daily_status: TaskStatus | None = None
    is_paused: bool = False
    created_at: datetime | None = None
    completed_at: datetime | None = None
    daily_products: int | None = None
    total_products: int | None = None
    completed_products: int | None = None
    weekly_planned_products: int | None = None
    day_total_products: int | None = None
    day_done_products: int | None = None
    finish_period: str | None = None
    is_bllok: bool = False
    is_1h_report: bool = False
    is_r1: bool = False
    is_personal: bool = False
    is_deadline_important: bool = False
    one_h_marker: str | None = None
    one_h_marker_by_ga: bool = False
    one_h_marker_comment: str | None = None
    ga_note_origin_id: uuid.UUID | None = None
    plan_note_origin_id: uuid.UUID | None = None


class WeeklyTableProjectEntry(BaseModel):
    """A project entry in the weekly table"""
    project_id: uuid.UUID
    project_title: str
    project_total_products: int | None = None
    project_current_phase: str | None = None
    project_type: str | None = None
    task_count: int = 0
    tasks: list[WeeklyTableProjectTaskEntry] = []
    is_late: bool = False


class WeeklyTableTaskEntry(BaseModel):
    """A task entry (for system/fast tasks) in the weekly table"""
    task_id: uuid.UUID | None = None
    title: str
    status: TaskStatus = TaskStatus.TODO
    # Optional per-day status override (driven by task_daily_progress).
    daily_status: TaskStatus | None = None
    is_paused: bool = False
    created_at: datetime | None = None
    completed_at: datetime | None = None
    daily_products: int | None = None
    finish_period: str | None = None
    fast_task_type: str | None = None
    is_bllok: bool = False
    is_1h_report: bool = False
    is_r1: bool = False
    is_personal: bool = False
    is_deadline_important: bool = False
    one_h_marker: str | None = None
    one_h_marker_by_ga: bool = False
    one_h_marker_comment: str | None = None
    ga_note_origin_id: uuid.UUID | None = None
    plan_note_origin_id: uuid.UUID | None = None


class WeeklyTableUserDay(BaseModel):
    """Items for a user on a specific day and time slot"""
    user_id: uuid.UUID
    user_name: str
    am_projects: list[WeeklyTableProjectEntry] = []
    pm_projects: list[WeeklyTableProjectEntry] = []
    am_system_tasks: list[WeeklyTableTaskEntry] = []
    pm_system_tasks: list[WeeklyTableTaskEntry] = []
    am_fast_tasks: list[WeeklyTableTaskEntry] = []
    pm_fast_tasks: list[WeeklyTableTaskEntry] = []


class WeeklyTableDay(BaseModel):
    """Plan for a specific day"""
    date: date
    users: list[WeeklyTableUserDay] = []


class WeeklyTableDepartment(BaseModel):
    """Weekly plan for a department"""
    department_id: uuid.UUID
    department_name: str
    days: list[WeeklyTableDay] = []


class WeeklyTableResponse(BaseModel):
    """Table-structured weekly planner response"""
    week_start: date
    week_end: date
    departments: list[WeeklyTableDepartment]
    saved_plan_id: uuid.UUID | None = None


class WeeklyPlannerSaveDayRequest(BaseModel):
    department_id: uuid.UUID
    week_start: date | None = None
    day_date: date | None = None


class WeeklyPlannerSaveDayResponse(BaseModel):
    department_id: uuid.UUID
    day_date: date
    saved_count: int


class MonthlyPlannerSummary(BaseModel):
    month_completed: int
    previous_month_completed: int


class MonthlyPlannerResponse(BaseModel):
    month_start: date
    month_end: date
    tasks: list[TaskOut]
    recurring: list[TaskOut]
    summary: MonthlyPlannerSummary


class WeeklyPlannerLegendEntryOut(BaseModel):
    """Legend entry for weekly planner questions"""
    id: uuid.UUID
    department_id: uuid.UUID
    week_start_date: date
    key: str
    label: str
    question_text: str
    answer_text: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WeeklyPlannerLegendEntryUpdate(BaseModel):
    """Update payload for legend entry answer"""
    answer_text: str | None = None


class WeeklyPlannerUserOrderUpdate(BaseModel):
    """Update weekly planner user ordering for a department."""
    department_id: uuid.UUID
    ordered_user_ids: list[uuid.UUID]


class WeeklyPlannerUserVisibilityUpdate(BaseModel):
    """Hide/unhide one user from weekly planner tables."""
    department_id: uuid.UUID
    user_id: uuid.UUID
    hidden: bool
