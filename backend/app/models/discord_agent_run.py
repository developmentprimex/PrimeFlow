"""Durable Discord research/drafting work, independent of interaction lifetimes."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DiscordAgentRun(Base):
    __tablename__ = "discord_agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("discord_links.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("discord_agent_runs.id", ondelete="SET NULL"))
    request_id: Mapped[str] = mapped_column(String(32), unique=True)
    mode: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    instruction: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    target: Mapped[dict] = mapped_column(JSONB)
    context: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", index=True)
    response_id: Mapped[str | None] = mapped_column(String(128))
    result_text: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list | None] = mapped_column(JSONB)
    usage: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    delivery_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_ids: Mapped[list | None] = mapped_column(JSONB)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_request_id: Mapped[str | None] = mapped_column(String(32))
    acceptance_status: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

