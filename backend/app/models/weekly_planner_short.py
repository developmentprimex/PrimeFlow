from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class WeeklyPlannerShortPoint(Base):
    __tablename__ = "weekly_planner_short_points"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    point: Mapped[int] = mapped_column(primary_key=True)
    decision: Mapped[str | None] = mapped_column(String(5))
    owner: Mapped[str | None] = mapped_column(String(120))
    due_date: Mapped[date | None] = mapped_column(Date)


class WeeklyPlannerShortComment(Base):
    __tablename__ = "weekly_planner_short_comments"
    __table_args__ = (Index("ix_weekly_planner_short_comments_week", "week_start"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    point: Mapped[int]
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
