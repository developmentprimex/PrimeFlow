"""Initialize sync metadata from genuine manual report-save audit events only."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select, func
from app.db import SessionLocal, engine
from app.models.audit_log import AuditLog
from app.models.m2_reporting_points import M2ReportingPointsReport as Report
from app.models.discord_m2_question import DiscordM2Question as Question
from app.services.discord_answer_sync import capture_report_changes

async def main():
    async with SessionLocal() as db:
        earliest = (await db.execute(select(func.min(Question.day)))).scalar_one()
        count = 0
        if earliest:
            events = (await db.execute(select(AuditLog, Report.report_date).join(Report, Report.id == AuditLog.entity_id).where(
                AuditLog.entity_type == 'm2_reporting_points', AuditLog.action == 'SAVE_ANSWERS', Report.report_date >= earliest)
                .order_by(AuditLog.created_at))).all()
            for event, day in events:
                if not isinstance(event.after, dict):
                    continue
                report = SimpleNamespace(report_date=day, manual_answers=event.after)
                await capture_report_changes(db, report, event.before or {}, event.after, changed_at=event.created_at)
                count += 1
            await db.commit()
        print(json.dumps({'manual_save_events_checked': count, 'task_or_report_answers_changed': False}))
    await engine.dispose()
asyncio.run(main())
