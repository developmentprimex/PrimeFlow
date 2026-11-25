from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.after_break_report_draft import AfterBreakReportDraft
from app.models.after_break_report_settings import AfterBreakReportSettings
from app.services.after_break_report import (
    UNFINISHED_EXPLANATION_OVERRIDES,
    apply_unfinished_priority_task_table,
    build_after_break_report_sections,
    is_generated_subject,
    render_html,
    render_plain_text,
    send_after_break_report,
    subject_for,
)
from app.services.meetings_report_scheduler import DEFAULT_RECIPIENTS, normalize_recipients

logger = logging.getLogger(__name__)


async def get_or_create_after_break_report_settings() -> AfterBreakReportSettings:
    async with SessionLocal() as db:
        row = (
            await db.execute(select(AfterBreakReportSettings).order_by(AfterBreakReportSettings.created_at.asc()))
        ).scalars().first()
        if row is None:
            row = AfterBreakReportSettings(recipients=DEFAULT_RECIPIENTS)
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return row


async def run_after_break_report_scheduler_once(now: datetime | None = None) -> bool:
    async with SessionLocal() as db:
        settings = (
            await db.execute(select(AfterBreakReportSettings).order_by(AfterBreakReportSettings.created_at.asc()))
        ).scalars().first()
        if settings is None or not settings.is_active:
            return False

        timezone = ZoneInfo(settings.timezone or "Europe/Tirane")
        local_now = (now or datetime.now(timezone)).astimezone(timezone) if (now and now.tzinfo) else (now or datetime.now(timezone))
        report_day = local_now.date()
        if local_now.weekday() not in (settings.weekdays or []):
            return False
        current_minute = local_now.time().replace(second=0, microsecond=0)
        configured_send_minute = settings.send_time.replace(second=0, microsecond=0)
        if current_minute != configured_send_minute:
            return False

        lock_key = f"after_break_report_auto|{report_day.isoformat()}"
        lock_acquired = (
            await db.execute(select(func.pg_try_advisory_xact_lock(func.hashtext(lock_key))))
        ).scalar_one()
        if not lock_acquired:
            logger.info("after_break_report_scheduler_skipped reason=send_locked report_date=%s", report_day)
            return False

        row = (
            await db.execute(select(AfterBreakReportDraft).where(AfterBreakReportDraft.report_date == report_day).with_for_update())
        ).scalar_one_or_none()
        if row and row.status == "SENT":
            return False

        recipients = normalize_recipients(settings.recipients)
        if not recipients["to"]:
            logger.warning("after_break_report_scheduler_skipped reason=no_to_recipients")
            return False

        # Always rebuild from live data at send time so auto-filled sections stay current.
        # Keep any manual answers already saved on today's draft.
        sections, snapshot = await build_after_break_report_sections(db, report_day)
        if row and (overrides := (row.generated_snapshot or {}).get(UNFINISHED_EXPLANATION_OVERRIDES)):
            snapshot[UNFINISHED_EXPLANATION_OVERRIDES] = overrides
            sections = await apply_unfinished_priority_task_table(db, sections, report_day, explanation_overrides=overrides)
        existing_sections = row.sections if row is not None else None
        from app.services.meeting_point_manual_sync import merge_common_view_manual_sections

        sections = await merge_common_view_manual_sections(
            db, sections, "after_break", existing_sections, settings.manual_questions
        )
        if row is None:
            row = AfterBreakReportDraft(
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
            message = await send_after_break_report(
                row.subject, recipients, plain_text, html_body,
                report_day=row.report_date, sections=row.sections,
            )
        except Exception as exc:
            row.status = "DRAFT"
            row.last_error = str(exc)[:2000]
            await db.commit()
            logger.exception("after_break_report_scheduler_send_failed")
            return False

        row.status = "SENT"
        row.sent_at = datetime.now(timezone)
        row.gmail_message_id = message.get("id")
        row.gmail_thread_id = message.get("threadId")
        row.last_error = None
        settings.last_run_date = datetime.now(timezone)
        await db.commit()
        logger.info("after_break_report_scheduler_sent report_date=%s", report_day)
        return True


async def run_after_break_report_scheduler_forever() -> None:
    while True:
        try:
            await run_after_break_report_scheduler_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("after_break_report_scheduler_failed")
        await asyncio.sleep(30)
