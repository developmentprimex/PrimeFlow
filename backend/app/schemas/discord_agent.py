from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, model_validator

from app.api.routers.discord_assistant import Actor


class AgentActor(Actor):
    pass


class AgentCreate(Actor):
    request_id: str = Field(pattern=r"^\d{1,32}$")
    task_id: uuid.UUID
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{16}$")
    mode: Literal["RESEARCH", "DRAFT"]
    instruction: str = Field(min_length=1, max_length=4000)
    field: Literal["title", "description"] | None = None
    number: int | None = Field(default=None, ge=1, strict=True)
    parent_run_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def valid_target(self):
        if (self.field is None) != (self.number is None):
            raise ValueError("Zgjidh fushën dhe numrin e pikës bashkë.")
        if not self.instruction.strip():
            raise ValueError("Shkruaj udhëzimin për agjentin.")
        return self


class AgentAccept(AgentActor):
    request_id: str = Field(pattern=r"^\d{1,32}$")
    mark_point_done: bool = False


class AgentDelivery(AgentActor):
    lease_token: uuid.UUID


class AgentReceipt(AgentDelivery):
    message_ids: list[str] = Field(min_length=1)

