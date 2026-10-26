"""Proposed date changes: tasks are untouched until the designated reviewer approves."""
from __future__ import annotations
import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class DiscordM2Postponement(Base):
    __tablename__ = 'discord_m2_postponements'
    __table_args__ = (Index('uq_discord_m2_pending_task', 'task_id', unique=True, postgresql_where=text("status = 'PENDING'")),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('discord_m2_questions.id', ondelete='CASCADE'))
    requester_link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('discord_links.id', ondelete='CASCADE'))
    approver_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    day: Mapped[date] = mapped_column(Date)
    request_id: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(16), default='PENDING', index=True)
    change_kind: Mapped[str] = mapped_column(String(16))
    proposed_dates: Mapped[dict] = mapped_column(JSONB)
    original_tasks: Mapped[list] = mapped_column(JSONB)
    reason_code: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    decision_detail: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_message_id: Mapped[str | None] = mapped_column(String(32))
    review_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requester_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
