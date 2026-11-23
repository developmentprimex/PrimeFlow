from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MicrosoftMailToken(Base):
    __tablename__ = "microsoft_mail_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
