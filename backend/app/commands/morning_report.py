from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models.morning_report_draft import MorningReportDraft
from app.services.discord_ga_replies import refresh_m1_section
from app.services.morning_report import (
    TASK_FEEDBACK_OVERRIDES,
    build_morning_report_sections,
    normalize_morning_report_sections,
    refresh_morning_task_tables,
    render_html,
    render_plain_text,
    send_morning_report,
    subject_for,
)
from app.services.primeflow_report import report_timezone
from app.services.primeflow_report_delivery import configured_recipients, validate_report_config


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or send a PrimeFlow Hapja e dites M1 report")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--send", action="store_true", help="Send the saved/generated draft; default is dry-run")
    args = parser.parse_args()
    validate_report_config(require_gmail=args.send)

    async with SessionLocal() as db:
        row = (
            await db.execute(select(MorningReportDraft).where(MorningReportDraft.report_date == args.date))
        ).scalar_one_or_none()
        if row is None:
            sections, snapshot = await build_morning_report_sections(db, args.date)
            row = MorningReportDraft(
                report_date=args.date,
                subject=subject_for(args.date),
                sections=sections,
                generated_snapshot=snapshot,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
        else:
            sections = await refresh_morning_task_tables(
                db, normalize_morning_report_sections(row.sections), row.report_date,
                task_feedback_overrides=(row.generated_snapshot or {}).get(TASK_FEEDBACK_OVERRIDES),
            )
            sections = await refresh_m1_section(db, sections, row.report_date, refresh_current=row.status != "SENT",
                                                sent_at=row.sent_at, generated_snapshot=row.generated_snapshot)

        plain_text = render_plain_text(row.subject, row.report_date, sections)
        if args.send:
            message = await send_morning_report(
                row.subject,
                await configured_recipients(),
                plain_text,
                render_html(row.subject, row.report_date, sections),
                report_day=row.report_date,
                sections=sections,
            )
            row.sections = sections
            row.status = "SENT"
            row.sent_at = datetime.now(report_timezone())
            row.gmail_message_id = message.get("id")
            row.gmail_thread_id = message.get("threadId")
            await db.commit()
            print(json.dumps({"id": str(row.id), "status": row.status, "subject": row.subject, "gmail_message_id": row.gmail_message_id}))
        else:
            print(json.dumps({"id": str(row.id), "status": row.status, "subject": row.subject}))
            print(plain_text)


if __name__ == "__main__":
    asyncio.run(main())

