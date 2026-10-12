from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KnowledgePrompt(Base):
    """A reusable prompt, definition or regulation in Knowledge PX.

    Lifecycle (``status``):
      PENDING_TEST      -> waiting for another person to test a prompt or check other material
      PENDING_APPROVAL  -> tested and confirmed, waiting for a manager/admin
      APPROVED          -> visible in the Prompt Library
      REJECTED          -> sent back by the tester or manager (author edits -> PENDING_TEST)
    """

    __tablename__ = "knowledge_prompts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PROMPT", index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False, server_default="{}")
    files_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    source_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ga_notes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING_TEST", index=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    # Person chosen by the author to test the prompt, and the "PROMPT: TESTO: ..." task created for them.
    tester_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    test_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    tested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_comment: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    file_original_name: Mapped[str | None] = mapped_column(String(255))
    file_stored_name: Mapped[str | None] = mapped_column(String(255))
    file_content_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
