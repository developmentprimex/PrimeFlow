import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskSymbolCommentEvent(Base):
    __tablename__ = "task_symbol_comment_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), index=True,
    )
    marker: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
