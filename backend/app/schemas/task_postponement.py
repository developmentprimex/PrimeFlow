from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class PostponementExplanationIn(BaseModel):
    postponement_reason_code: str | None = Field(default=None, max_length=40)
    postponement_comment: str | None = Field(default=None, max_length=10000)


class TaskPostponementExplanations(BaseModel):
    postponement_explanations: dict[uuid.UUID, PostponementExplanationIn] = Field(default_factory=dict)
