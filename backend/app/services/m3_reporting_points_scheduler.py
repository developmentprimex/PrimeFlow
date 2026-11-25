"""Capture staff Realization at 16:15. This loop never sends email.

Generating or sending the report after 16:15 captures it again, so the
report always carries the latest realization of the day.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.db import SessionLocal
from app.services.m3_reporting_points import (
    REALIZATION_CAPTURE_TIME,
    build_realization_capture,
    locked_report,
    record_realization_capture,
    refresh_report,
)
from app.services.primeflow_report import report_timezone

logger = logging.getLogger(__name__)
CAPTURE_TIME = REALIZATION_CAPTURE_TIME


def is_capture_minute(now: datetime) -> bool:
    local = now.astimezone(report_timezone())
    return local.weekday() < 5 and local.time().replace(second=0, microsecond=0, tzinfo=None) == CAPTURE_TIME


async def run_m3_reporting_points_scheduler_once(now: datetime | None = None) -> bool:
    now = now or datetime.now(report_timezone())
    if not is_capture_minute(now):
        return False
    day = now.astimezone(report_timezone()).date()
    async with SessionLocal() as db:
        row = await locked_report(db, day, wait=False)
        if row is None or row.realization_captured_at is not None or row.status == "SENT":
            return False
        # Manual answers survive capture.
        if row.generated_at:
            record_realization_capture(row, await build_realization_capture(db, day), now)
        else:
            await refresh_report(db, row, now)
        await db.commit()
        logger.info("m3_reporting_points_realization_captured day=%s at=%s", day, now.isoformat())
        return True


async def run_m3_reporting_points_scheduler_forever() -> None:
    while True:
        try:
            await run_m3_reporting_points_scheduler_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("m3_reporting_points_capture_failed")
        await asyncio.sleep(15)
