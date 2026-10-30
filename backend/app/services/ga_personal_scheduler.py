"""Generate only configured household occurrences; this worker sends no alerts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models.ga_personal import GaPersonalSpace, GaPersonalMember
from app.models.user import User
from app.schemas.ga_personal import GenerateRequest
from app.services import ga_personal as service

logger = logging.getLogger(__name__)


async def generation_tick(db, *, day=None):
    explicit_day = day is not None
    day = day or datetime.now(service.TZ).date()
    spaces = (await db.execute(select(GaPersonalSpace).where(GaPersonalSpace.key == "ga_personal"))).scalars().all()
    created = 0
    for candidate in spaces:
        space = await service.lock_space(db, candidate.id)
        config = space.config.get("automatic_generation", {})
        if not config.get("enabled") or not space.password_hash:
            continue
        if not config.get("starts_on") or day.isoformat() < config["starts_on"]:
            continue
        member = (await db.execute(select(GaPersonalMember).join(User, User.id == GaPersonalMember.user_id).where(
            GaPersonalMember.space_id == space.id, GaPersonalMember.active.is_(True),
            GaPersonalMember.is_admin.is_(True), User.is_active.is_(True),
        ).order_by(GaPersonalMember.id).limit(1))).scalar_one_or_none()
        if member is None:
            continue
        # Keep today's list current, then maintain a rolling 14-day window so
        # the week view has actual occurrences before those dates arrive.
        # School days, presence, first-home and conditions are not inferred.
        days = {day}
        if not explicit_day:
            horizon = day + timedelta(days=13)
            through = config.get("future_generated_through")
            try:
                first_future = max(day, datetime.fromisoformat(through).date() + timedelta(days=1)) if through else day
            except (TypeError, ValueError):
                first_future = day
            if first_future <= horizon:
                days.update(first_future + timedelta(days=offset) for offset in range((horizon - first_future).days + 1))
            config = {**config, "future_generated_through": horizon.isoformat()}
        for scheduled_day in sorted(days):
            result = await service.generate(db, member, GenerateRequest(day=scheduled_day), automatic=True, commit=False)
            created += result["created"]
        space.config = {**space.config, "automatic_generation": {
            **config, "last_checked_at": service.utcnow().isoformat(),
        }}
    await db.commit()
    return created


async def run_ga_personal_generation_forever():
    while True:
        try:
            async with SessionLocal() as db:
                created = await generation_tick(db)
                if created:
                    logger.info("GA PERSONAL generated %d configured occurrences", created)
        except Exception as exc:
            # Keep family content, SQL parameters and credentials out of logs.
            logger.warning("GA PERSONAL generation needs a retry (%s)", type(exc).__name__)
        await asyncio.sleep(60)
