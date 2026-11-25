from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DiscordTaskDeliveryComment(Base):
    __tablename__ = "discord_task_delivery_comments"

    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    row_id: Mapped[str] = mapped_column(String(73), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    comment: Mapped[str] = mapped_column(Text)
