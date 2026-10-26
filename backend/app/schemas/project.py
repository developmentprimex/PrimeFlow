from __future__ import annotations

import uuid

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ProjectPhaseStatus, ProjectType, TaskStatus


class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    display_title: str | None = None
    description: str | None = None
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    project_type: ProjectType | None = None
    current_phase: ProjectPhaseStatus
    status: TaskStatus
    progress_percentage: int
    total_products: int | None = None
    is_template: bool = False
    is_active: bool = True
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None)
    department_id: uuid.UUID
    manager_id: uuid.UUID | None = None
    project_type: ProjectType | None = None
    template_project_id: uuid.UUID | None = None
    current_phase: ProjectPhaseStatus | None = None
    status: TaskStatus | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    total_products: int | None = Field(default=None, ge=0)
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None)
    manager_id: uuid.UUID | None = None
    project_type: ProjectType | None = None
    current_phase: ProjectPhaseStatus | None = None
    status: TaskStatus | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    total_products: int | None = Field(default=None, ge=0)
    is_template: bool | None = None
    is_active: bool | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None


class ProjectRemoveFromDayRequest(BaseModel):
    day_date: date
    user_id: uuid.UUID
    time_slot: str | None = None

