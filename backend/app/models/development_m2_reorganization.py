from datetime import date

from sqlalchemy import Date, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DevelopmentM2Reorganization(Base):
    __tablename__ = "development_m2_reorganization"

    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
