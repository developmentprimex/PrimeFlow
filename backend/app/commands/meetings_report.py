from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models.meetings_report_draft import MeetingsReportDraft
from app.services.meetings_report import (
    SECTION_TITLES,
    build_meetings_report_sections,
    meetings_sections_for_snapshot,
    refresh_saved_leave_table,
    render_html,
    render_plain_text,
    send_meetings_report,
    subject_for,
)
from app.services.primeflow_report import report_timezone
from app.services.primeflow_report_delivery import configured_recipients, validate_report_config


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or send a PrimeFlow Meetings Report")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--send", action="store_true", help="Send the saved/generated draft; default is dry-run")
    args = parser.parse_args()
    validate_report_config(require_gmail=args.send)

    async with SessionLocal() as db:
        row = (
            await db.execute(select(MeetingsReportDraft).where(MeetingsReportDraft.report_date == args.date))
        ).scalar_one_or_none()
        if row is None:
            tomorrow, sections, snapshot = await build_meetings_report_sections(db, args.date)
            row = MeetingsReportDraft(
                report_date=args.date,
                tomorrow_date=tomorrow,
                subject=subject_for(args.date),
                sections=sections,
                generated_snapshot=snapshot,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)

        sections = meetings_sections_for_snapshot(row.sections, row.generated_snapshot)
        sections = await refresh_saved_leave_table(
            db, sections, section_title=SECTION_TITLES[4], report_day=row.report_date,
            leave_day=row.tomorrow_date, snapshot=row.generated_snapshot,
        )
        plain_text = render_plain_text(row.subject, row.report_date, row.tomorrow_date, sections)
        if args.send:
            message = await send_meetings_report(
                row.subject,
                await configured_recipients(),
                plain_text,
                render_html(row.subject, row.report_date, row.tomorrow_date, sections,
                            tomorrow_symbols_html=(row.generated_snapshot or {}).get("tomorrow_symbols_html")),
                db=db,
                report_day=row.report_date,
                tomorrow=row.tomorrow_date,
                sections=sections,
            )
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
