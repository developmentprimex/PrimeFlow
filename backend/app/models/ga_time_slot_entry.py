import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Time, false, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GaTimeSlotEntry(Base):
    __tablename__ = "ga_time_slot_entries"
    __table_args__ = (
        Index(
            "ix_ga_time_slot_entries_user_day_time",
            "user_id",
            "day_date",
            "start_time",
            "end_time",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    day_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    content: Mapped[str] = mapped_column(String(8000), nullable=False, server_default="")
    sync_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ga_icloud_sync_connections.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(700), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
