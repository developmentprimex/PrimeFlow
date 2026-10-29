from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Snowflake = str


class PollRequest(BaseModel):
    delivery_enabled: bool = True
    health_only: bool = False


class DiscordSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    guild_id: str = Field(default="", pattern=r"^(\d{17,20})?$")
    channel_id: str = Field(default="", pattern=r"^(\d{17,20})?$")
    user_ids: dict[Literal["rrita", "mrika", "gane"], str] = Field(default_factory=dict)
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def valid(self):
        ids = [v for v in self.user_ids.values() if v]
        if any(not v.isascii() or not v.isdigit() or not 17 <= len(v) <= 20 for v in ids):
            raise ValueError("Discord User ID duhet te jete 17-20 shifra.")
        if len(ids) != len(set(ids)):
            raise ValueError("Nje llogari Discord nuk lidhet me dy persona.")
        if self.enabled and (not self.guild_id or not self.channel_id):
            raise ValueError("Cakto serverin dhe kanalin privat.")
        return self


class LeaseRequest(BaseModel):
    lease: str = Field(min_length=32, max_length=64)


class DeliveryResult(LeaseRequest):
    outcome: Literal["sent", "failed", "uncertain"]
    channel_id: str | None = Field(default=None, pattern=r"^\d{17,20}$")
    message_id: str | None = Field(default=None, pattern=r"^\d{17,20}$")
    error: Literal["blocked_dm", "permissions", "network", "unknown"] | None = None
    sync_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SyncResult(BaseModel):
    channel_id: str = Field(pattern=r"^\d{17,20}$")
    message_id: str = Field(pattern=r"^\d{17,20}$")
    sync_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    error: Literal["not_found", "permissions", "network"] | None = None


class DiscordAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(pattern=r"^\d{17,20}$")
    guild_id: str | None = Field(default=None, pattern=r"^\d{17,20}$")
    channel_id: str = Field(pattern=r"^\d{17,20}$")
    message_id: str = Field(pattern=r"^\d{17,20}$")
    interaction_id: str = Field(pattern=r"^\d{17,20}$")
    action: Literal["acknowledged", "in_progress", "done", "needs_help", "steps", "later15", "later30", "later60"]
