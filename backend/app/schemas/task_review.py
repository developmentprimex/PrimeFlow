from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaskReviewCreate(BaseModel):
    task_id: uuid.UUID
    reviewee_user_id: uuid.UUID
    diamond_score: Literal[1] = 1
    comment: str | None = Field(default=None, max_length=4000)


class TaskReviewUpdate(BaseModel):
    diamond_score: Literal[1] | None = None
    comment: str | None = Field(default=None, max_length=4000)


class TaskReviewOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    source: Literal["TASK", "REALIZATION_PROPOSAL"] = "TASK"
    realization_period_id: uuid.UUID | None = None
    reviewee_user_id: uuid.UUID
    reviewee_name: str
    reviewer_user_id: uuid.UUID | None
    reviewer_name: str
    diamond_score: int
    comment: str | None
    is_sample: bool = False
    task_title: str
    project_title: str | None
    created_at: datetime
    updated_at: datetime


class TaskReviewOverviewRow(BaseModel):
    task_id: uuid.UUID | None
    source: Literal["TASK", "REALIZATION_PROPOSAL"] = "TASK"
    realization_period_id: uuid.UUID | None = None
    task_title: str
    project_id: uuid.UUID | None = None
    project_title: str | None = None
    department_id: uuid.UUID | None = None
    reviewee_user_id: uuid.UUID
    reviewee_name: str
    completed_at: datetime
    due_date: datetime | None = None
    is_late: bool = False
    review: TaskReviewOut | None = None


class TaskReviewUserSummary(BaseModel):
    user_id: uuid.UUID
    user_name: str
    completed_count: int = 0
    reviewed_count: int = 0
    unreviewed_count: int = 0
    late_count: int = 0
    diamonds_total: int = 0
    proposal_count: int = 0


class TaskReviewOverviewOut(BaseModel):
    completed_count: int = 0
    reviewed_count: int = 0
    unreviewed_count: int = 0
    diamonds_total: int = 0
    proposal_count: int = 0
    users: list[TaskReviewUserSummary] = Field(default_factory=list)
    rows: list[TaskReviewOverviewRow] = Field(default_factory=list)


class TaskReviewDeleteSamplesOut(BaseModel):
    deleted_count: int = 0


TaskReviewStatusFilter = Literal["all", "reviewed", "unreviewed"]
