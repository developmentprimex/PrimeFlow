"""Deliver M1, M2 and M3 reporting points using their saved email settings."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.db import SessionLocal
from app.services import m1_reporting_points as m1, m2_reporting_points as m2, m3_reporting_points as m3
from app.services.primeflow_report import report_timezone
from app.services.reporting_points_settings import get_delivery_settings

logger = logging.getLogger(__name__)
REPORT_SERVICES = (("M1", m1), ("M2", m2), ("M3", m3))


async def run_reporting_points_auto_scheduler_once(now: datetime | None = None) -> bool:
    local = (now or datetime.now(report_timezone())).astimezone(report_timezone())
    sent = False
    for name, service in REPORT_SERVICES:
        try:
            async with SessionLocal() as db:
                settings = await get_delivery_settings(db, name, lock=True, wait=False)
                if (settings is None or not settings.is_active or local.weekday() not in settings.weekdays
                        or local.time().replace(tzinfo=None) < settings.send_time):
                    continue
                # Use the same daily lock as manual saves, capture and sends.
                # Keep it through refresh, SMTP delivery and the marker commit.
                row = await service.locked_report(db, local.date(), wait=False)
                if row is None or row.auto_sent_at is not None:
                    continue
                try:
                    # Generate even if nobody opened the page; retain answers.
                    # M3 also takes the latest post-16:15 realization capture.
                    await service.refresh_report(db, row, local)
                except Exception as exc:
                    row.status, row.last_error = "FAILED", str(exc)[:2000]
                    await db.commit()
                    raise
                await service.send_report(db, row, settings.recipients, automatic=True)
                sent = True
                logger.info("reporting_points_auto_sent report=%s day=%s slot=%s", name, local.date(), settings.send_time)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed send stays due, and one report cannot block the other.
            logger.exception("reporting_points_auto_send_failed report=%s day=%s", name, local.date())
    return sent


async def run_reporting_points_auto_scheduler_forever() -> None:
    while True:
        try:
            await run_reporting_points_auto_scheduler_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reporting_points_auto_scheduler_failed")
        # Includes same-day catch-up after downtime, never historical backfill.
        await asyncio.sleep(30)
