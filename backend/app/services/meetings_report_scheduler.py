from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.models.meetings_report_draft import MeetingsReportDraft
from app.models.meetings_report_settings import MeetingsReportSettings
from app.services.meetings_report import (
    MANUAL_SECTION_TITLES,
    build_meetings_report_sections,
    is_generated_subject,
    render_html,
    render_plain_text,
    send_meetings_report,
    subject_for,
)
from app.services.report_section_merge import preserve_manual_sections

logger = logging.getLogger(__name__)


DEFAULT_RECIPIENTS = {"to": ["130primex.eu@gmail.com"], "cc": [], "bcc": []}
M3_AUTO_SEND_TIMES = (time(16, 30),)


def _due_m3_send_slot(now: datetime, sent_slots: set[str]) -> str | None:
    """Return the next due M3 delivery slot that has not already been sent."""
    current_time = now.time().replace(second=0, microsecond=0)
    for send_time in M3_AUTO_SEND_TIMES:
        slot = send_time.strftime("%H:%M")
        if current_time >= send_time and slot not in sent_slots:
            return slot
    return None


def normalize_recipients(value: dict | None) -> dict[str, list[str]]:
    raw = value or {}
    result = {"to": [], "cc": [], "bcc": []}
    for kind in result:
        rows = raw.get(kind) if isinstance(raw, dict) else []
        if not isinstance(rows, list):
            continue
        seen: set[str] = set()
        for email in rows:
            cleaned = str(email).strip()
            normalized = cleaned.lower()
            if not cleaned or normalized in seen:
                continue
            seen.add(normalized)
            result[kind].append(cleaned)
    return result


async def get_or_create_meetings_report_settings() -> MeetingsReportSettings:
    async with SessionLocal() as db:
        row = (
            await db.execute(select(MeetingsReportSettings).order_by(MeetingsReportSettings.created_at.asc()))
        ).scalars().first()
        if row is None:
            row = MeetingsReportSettings(recipients=DEFAULT_RECIPIENTS)
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return row


async def run_meetings_report_scheduler_once(now: datetime | None = None) -> bool:
    async with SessionLocal() as db:
        settings = (
            await db.execute(select(MeetingsReportSettings).order_by(MeetingsReportSettings.created_at.asc()))
        ).scalars().first()
        if settings is None or not settings.is_active:
            return False

        timezone = ZoneInfo(settings.timezone or "Europe/Tirane")
        local_now = (now or datetime.now(timezone)).astimezone(timezone) if (now and now.tzinfo) else (now or datetime.now(timezone))
        report_day = local_now.date()
        if local_now.weekday() not in (settings.weekdays or []):
            return False
        row = (
            await db.execute(select(MeetingsReportDraft).where(MeetingsReportDraft.report_date == report_day))
        ).scalar_one_or_none()
        sent_slots = {str(slot) for slot in (getattr(row, "auto_sent_slots", None) or [])}
        delivery_slot = _due_m3_send_slot(local_now, sent_slots)
        if delivery_slot is None:
            return False

        recipients = normalize_recipients(settings.recipients)
        if not recipients["to"]:
            logger.warning("meetings_report_scheduler_skipped reason=no_to_recipients")
            return False

        # Always rebuild from live data at send time so auto-filled sections stay current.
        # Keep any manual answers already saved on today's draft.
        tomorrow, sections, snapshot = await build_meetings_report_sections(db, report_day)
        existing_sections = row.sections if row is not None else None
        if row is not None:
            sections = preserve_manual_sections(sections, row.sections, MANUAL_SECTION_TITLES)
        from app.services.meeting_point_manual_sync import merge_common_view_manual_sections

        sections = await merge_common_view_manual_sections(
            db, sections, "meetings", existing_sections, getattr(settings, "manual_questions", [])
        )
        if row is None:
            row = MeetingsReportDraft(
                report_date=report_day,
                tomorrow_date=tomorrow,
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
            row.tomorrow_date = tomorrow
            row.sections = sections
            row.generated_snapshot = snapshot

        plain_text = render_plain_text(row.subject, row.report_date, row.tomorrow_date, row.sections)
        html_body = render_html(row.subject, row.report_date, row.tomorrow_date, row.sections,
                                tomorrow_symbols_html=snapshot.get("tomorrow_symbols_html"))
        try:
            message = await send_meetings_report(
                row.subject, recipients, plain_text, html_body,
                db=db, report_day=row.report_date, tomorrow=row.tomorrow_date, sections=row.sections,
            )
        except Exception as exc:
            row.status = "DRAFT"
            row.last_error = str(exc)[:2000]
            await db.commit()
            logger.exception("meetings_report_scheduler_send_failed")
            return False

        row.status = "SENT"
        row.sent_at = datetime.now(timezone)
        row.gmail_message_id = message.get("id")
        row.gmail_thread_id = message.get("threadId")
        row.auto_sent_slots = [*sorted(sent_slots), delivery_slot]
        row.last_error = None
        settings.last_run_date = datetime.now(timezone)
        await db.commit()
        logger.info("meetings_report_scheduler_sent report_date=%s slot=%s", report_day, delivery_slot)
        return True


async def run_meetings_report_scheduler_forever() -> None:
    while True:
        try:
            await run_meetings_report_scheduler_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("meetings_report_scheduler_failed")
        await asyncio.sleep(30)
