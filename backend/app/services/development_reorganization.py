from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.development_m1_reorganization import DevelopmentM1Reorganization
from app.models.development_m2_reorganization import DevelopmentM2Reorganization


DevelopmentSlot = Literal["m1", "m2"]
REORGANIZATION_MODELS = {"m1": DevelopmentM1Reorganization, "m2": DevelopmentM2Reorganization}


async def read_development_reorganization(db: AsyncSession, slot: DevelopmentSlot, day: date) -> str:
    model = REORGANIZATION_MODELS[slot]
    return await db.scalar(select(model.body).where(model.report_date == day)) or ""
