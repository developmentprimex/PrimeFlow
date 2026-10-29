"""Household data is deliberately outside public/work task tables."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SCHEMA = "ga_personal"
DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def now():
    return datetime.now(timezone.utc)


class GaPersonalSpace(Base):
    __tablename__ = "spaces"
    __table_args__ = {"schema": SCHEMA}
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(40), unique=True, default="ga_personal")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(DOCUMENT, default=dict)


class GaPersonalMember(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("space_id", "person_key", name="uq_ga_member_person"),
        UniqueConstraint("space_id", "user_id", name="uq_ga_member_user"),
        CheckConstraint("person_key IN ('mrika','lirza','rrita','gane')", name="family_person"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    person_key: Mapped[str] = mapped_column(String(20))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class GaPersonalUnlock(Base):
    __tablename__ = "unlock_sessions"
    __table_args__ = {"schema": SCHEMA}
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    login_session_id: Mapped[str] = mapped_column(String(64))
    password_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class GaPersonalThrottle(Base):
    __tablename__ = "unlock_throttles"
    __table_args__ = {"schema": SCHEMA}
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GaPersonalDevice(Base):
    __tablename__ = "devices"
    __table_args__ = {"schema": SCHEMA}
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    authorized_by: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.memberships.id"))
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GaPersonalDeviceOp(Base):
    __tablename__ = "device_ops"
    __table_args__ = (UniqueConstraint("space_id", "op_id"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.devices.id"))
    op_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payload: Mapped[dict] = mapped_column(DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GaPersonalDeviceRecord(Base):
    __tablename__ = "device_records"
    __table_args__ = (UniqueConstraint("space_id", "kind", "key"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(DOCUMENT)
    client_at: Mapped[int] = mapped_column(BigInteger)
    op_id: Mapped[str] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GaPersonalTemplate(Base):
    __tablename__ = "task_templates"
    __table_args__ = (UniqueConstraint("space_id", "source_id"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    definition: Mapped[dict] = mapped_column(DOCUMENT)
    version: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    import_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class GaPersonalOccurrence(Base):
    __tablename__ = "occurrences"
    __table_args__ = (
        UniqueConstraint("space_id", "template_id", "period_key", "assignment_key"),
        CheckConstraint("status IN ('pending','acknowledged','in_progress','needs_help','rescheduled','done','cancelled')", name="occurrence_status"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.task_templates.id"), index=True)
    period_key: Mapped[str] = mapped_column(String(64))
    assignment_key: Mapped[str] = mapped_column(String(100))
    local_date: Mapped[str] = mapped_column(String(10), index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(DOCUMENT)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GaPersonalEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("space_id", "request_id"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.occurrences.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GaPersonalDelivery(Base):
    __tablename__ = "reminder_deliveries"
    __table_args__ = (UniqueConstraint("occurrence_id", "channel", "sequence"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    occurrence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.occurrences.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="in_app")
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="pending")


class GaPersonalDiscordDelivery(Base):
    __tablename__ = "discord_outbox"
    __table_args__ = (UniqueConstraint("occurrence_id", "schedule_key", "phase", "recipient"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    occurrence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.occurrences.id"), index=True)
    schedule_key: Mapped[str] = mapped_column(String(64))
    phase: Mapped[str] = mapped_column(String(12))
    recipient: Mapped[str] = mapped_column(String(40))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    lease: Mapped[str | None] = mapped_column(String(64))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_id: Mapped[str | None] = mapped_column(String(24))
    message_id: Mapped[str | None] = mapped_column(String(24))
    details: Mapped[dict] = mapped_column(DOCUMENT, default=dict)


class GaPersonalImport(Base):
    __tablename__ = "import_runs"
    __table_args__ = (UniqueConstraint("space_id", "dataset_hash"), {"schema": SCHEMA})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.spaces.id"), index=True)
    dataset_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    summary: Mapped[dict] = mapped_column(DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
