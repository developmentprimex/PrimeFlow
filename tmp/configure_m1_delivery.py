"""Configure only M1 delivery; the application scheduler performs sends."""
import argparse, asyncio, json, sys
from datetime import datetime, time
from pathlib import Path
from sqlalchemy import select, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db import SessionLocal, engine
from app.models.reporting_points_settings import ReportingPointsSettings
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.services.reporting_points_settings import settings_lock, settings_payload, manual_recipients, default_settings
from app.services.primeflow_report import report_timezone
from app.services.audit import add_audit_log
from uuid import NAMESPACE_URL, uuid5
async def main(apply):
    async with SessionLocal() as db:
        if not apply:
            await db.execute(text("SET TRANSACTION READ ONLY"))
        else:
            await settings_lock(db, "M1")
        row = (await db.execute(select(ReportingPointsSettings).where(ReportingPointsSettings.report_type == "M1"))).scalar_one_or_none()
        before = settings_payload(row, await manual_recipients(db, "M1", row)) if row else None
        if apply:
            backup = Path(__file__).with_name("m1_delivery_before.json")
            if not backup.exists():
                backup.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
            if row is None:
                row = default_settings("M1")
                db.add(row)
            row.is_active, row.send_time, row.weekdays = True, time(8, 30), [0, 1, 2, 3, 4]
            row.recipients = {"to": ["ga@primexeu.com", "info@primexeu.com"], "cc": [], "bcc": []}
            row.manual_recipients = dict(row.recipients)
            after = settings_payload(row, row.manual_recipients)
            add_audit_log(db=db, actor_user_id=None, entity_type="m1_reporting_points", entity_id=uuid5(NAMESPACE_URL, "primeflow:reporting-points-settings:M1"),
                action="UPDATE_DELIVERY_SETTINGS", before=before, after=after)
            await db.commit()
        day = datetime.now(report_timezone()).date()
        report = (await db.execute(select(M1ReportingPointsReport).where(M1ReportingPointsReport.report_date == day))).scalar_one_or_none()
        print(json.dumps({"applied":apply,"settings":settings_payload(row, await manual_recipients(db,"M1",row)) if row else None,
            "today":str(day),"last_manual_or_auto_sent_at":str(report.sent_at) if report else None,"auto_sent_at":str(report.auto_sent_at) if report else None},ensure_ascii=False))
    await engine.dispose()
parser=argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true")
asyncio.run(main(parser.parse_args().apply))
