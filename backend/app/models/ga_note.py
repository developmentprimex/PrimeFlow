from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import GaNotePriority, GaNoteStatus, GaNoteType


class GaNote(Base):
    __tablename__ = "ga_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    note_type: Mapped[GaNoteType] = mapped_column(
        Enum(GaNoteType, name="ga_note_type"), nullable=False, server_default="GA"
    )
    status: Mapped[GaNoteStatus] = mapped_column(
        Enum(GaNoteStatus, name="ga_note_status"), nullable=False, server_default="OPEN"
    )
    priority: Mapped[GaNotePriority | None] = mapped_column(Enum(GaNotePriority, name="ga_note_priority"))

    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_converted_to_task: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_discussed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mira_shared_to_px: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    one_h_marker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    one_h_marker_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    one_h_marker_by_ga: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    one_h_marker_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"))
    # Knowledge PX origin, e.g. "PROMPT" for a Prompt Note. NULL for regular PX Notes.
    knowledge_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # Prompt notes: person who will test the prompt (chosen when the task is created).
    knowledge_tester_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    attachments = relationship(
        "GaNoteAttachment",
        backref="note",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

