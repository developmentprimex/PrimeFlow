from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models.after_break_report_draft import AfterBreakReportDraft
from app.services.after_break_report import (
    UNFINISHED_EXPLANATION_OVERRIDES,
    apply_unfinished_priority_task_table,
    build_after_break_report_sections,
    normalize_after_break_report_sections,
    populate_pcm_projects_section,
    refresh_after_break_discord_sections,
    render_html,
    render_plain_text,
    send_after_break_report,
    subject_for,
)
from app.services.primeflow_report import report_timezone
from app.services.primeflow_report_delivery import configured_recipients, validate_report_config


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or send a PrimeFlow Permbledhja pas pauzes report")
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--send", action="store_true", help="Send the saved/generated draft; default is dry-run")
    args = parser.parse_args()
    validate_report_config(require_gmail=args.send)

    async with SessionLocal() as db:
        row = (
            await db.execute(select(AfterBreakReportDraft).where(AfterBreakReportDraft.report_date == args.date))
        ).scalar_one_or_none()
        if row is None:
            sections, snapshot = await build_after_break_report_sections(db, args.date)
            row = AfterBreakReportDraft(
                report_date=args.date,
                subject=subject_for(args.date),
                sections=sections,
                generated_snapshot=snapshot,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)

        sections = await refresh_after_break_discord_sections(
            db, normalize_after_break_report_sections(row.sections), row.report_date,
            generated_snapshot=row.generated_snapshot, sent=row.status == "SENT", sent_at=row.sent_at,
        )
        sections = await populate_pcm_projects_section(db, sections, row.report_date)
        sections = await apply_unfinished_priority_task_table(
            db, sections, row.report_date, explanation_overrides=(row.generated_snapshot or {}).get(UNFINISHED_EXPLANATION_OVERRIDES),
        )
        plain_text = render_plain_text(row.subject, row.report_date, sections)
        if args.send:
            message = await send_after_break_report(
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
