from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.models.morning_report_draft import MorningReportDraft
from app.models.morning_report_settings import MorningReportSettings
from app.services.morning_report import (
    MANUAL_SECTION_TITLES,
    TASK_FEEDBACK_OVERRIDES,
    build_morning_report_sections,
    is_generated_subject,
    preserve_morning_plan_note,
    render_html,
    render_plain_text,
    send_morning_report,
    subject_for,
)
from app.services.report_section_merge import preserve_manual_sections
from app.services.meetings_report_scheduler import DEFAULT_RECIPIENTS, normalize_recipients

logger = logging.getLogger(__name__)
M1_AUTO_SEND_TIMES = (time(7, 0), time(9, 0))


def _due_m1_send_slot(now: datetime, sent_slots: set[str]) -> str | None:
    """Return the latest due M1 slot that has not already been delivered."""
    current_time = now.time().replace(second=0, microsecond=0)
    due_slots = [
        send_time.strftime("%H:%M")
        for send_time in M1_AUTO_SEND_TIMES
        if current_time >= send_time and send_time.strftime("%H:%M") not in sent_slots
    ]
    return due_slots[-1] if due_slots else None


async def get_or_create_morning_report_settings() -> MorningReportSettings:
    async with SessionLocal() as db:
        row = (
            await db.execute(select(MorningReportSettings).order_by(MorningReportSettings.created_at.asc()))
        ).scalars().first()
        if row is None:
            row = MorningReportSettings(recipients=DEFAULT_RECIPIENTS)
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return row


async def run_morning_report_scheduler_once(now: datetime | None = None) -> bool:
    async with SessionLocal() as db:
        settings = (
            await db.execute(select(MorningReportSettings).order_by(MorningReportSettings.created_at.asc()))
        ).scalars().first()
        if settings is None or not settings.is_active:
            return False

        timezone = ZoneInfo(settings.timezone or "Europe/Tirane")
        local_now = (now or datetime.now(timezone)).astimezone(timezone) if (now and now.tzinfo) else (now or datetime.now(timezone))
        report_day = local_now.date()
        if local_now.weekday() not in (settings.weekdays or []):
            return False
        row = (
            await db.execute(select(MorningReportDraft).where(MorningReportDraft.report_date == report_day).with_for_update())
        ).scalar_one_or_none()
        sent_slots = {str(slot) for slot in (getattr(row, "auto_sent_slots", None) or [])}
        delivery_slot = _due_m1_send_slot(local_now, sent_slots)
        if delivery_slot is None:
            return False

        recipients = normalize_recipients(settings.recipients)
        if not recipients["to"]:
            logger.warning("morning_report_scheduler_skipped reason=no_to_recipients")
            return False

        # Always rebuild from live data at send time so auto-filled sections stay current.
        # Keep any manual answers already saved on today's draft.
        overrides = (getattr(row, "generated_snapshot", None) or {}).get(TASK_FEEDBACK_OVERRIDES)
        sections, snapshot = await build_morning_report_sections(
            db, report_day, task_feedback_overrides=overrides,
        )
        existing_sections = row.sections if row is not None else None
        if row is not None:
            sections = preserve_manual_sections(sections, row.sections, MANUAL_SECTION_TITLES)
            sections = preserve_morning_plan_note(sections, row.sections)
        from app.services.meeting_point_manual_sync import merge_common_view_manual_sections

        sections = await merge_common_view_manual_sections(
            db, sections, "morning", existing_sections, getattr(settings, "manual_questions", [])
        )
        if row is None:
            row = MorningReportDraft(
                report_date=report_day,
                subject=subject_for(report_day),
                recipients=recipients,
                sections=sections,
                generated_snapshot=snapshot,
            )
            db.add(row)
            await db.flush()
        else:
            if not row.subject or is_generated_subject(row.subject, report_day):
                row.subject = subject_for(report_day)
            row.recipients = recipients
            row.sections = sections
            row.generated_snapshot = snapshot

        plain_text = render_plain_text(row.subject, row.report_date, row.sections)
        html_body = render_html(row.subject, row.report_date, row.sections)
        try:
            message = await send_morning_report(
                row.subject, recipients, plain_text, html_body,
                report_day=row.report_date, sections=row.sections,
            )
        except Exception as exc:
            row.status = "DRAFT"
            row.last_error = str(exc)[:2000]
            await db.commit()
            logger.exception("morning_report_scheduler_send_failed")
            return False

        row.status = "SENT"
        row.sent_at = datetime.now(timezone)
        row.gmail_message_id = message.get("id")
        row.gmail_thread_id = message.get("threadId")
        row.auto_sent_slots = [*sorted(sent_slots), delivery_slot]
        row.last_error = None
        settings.last_run_date = datetime.now(timezone)
        await db.commit()
        logger.info("morning_report_scheduler_sent report_date=%s slot=%s", report_day, delivery_slot)
        return True


async def run_morning_report_scheduler_forever() -> None:
    while True:
        try:
            await run_morning_report_scheduler_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("morning_report_scheduler_failed")
        await asyncio.sleep(30)
