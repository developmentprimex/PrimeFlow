import asyncio, json, sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db import SessionLocal, engine
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.services.m1_reporting_points import report_payload, report_attachments, render_html, excluded_note_ids
from app.services.primeflow_report import report_timezone
async def main():
    day = datetime.now(report_timezone()).date()
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        row = (await db.execute(select(M1ReportingPointsReport).where(M1ReportingPointsReport.report_date == day))).scalar_one()
        payload = report_payload(row, excluded_note_ids=await excluded_note_ids(db,row))
        output = Path(__file__).with_name("m1-email-preview")
        output.mkdir(exist_ok=True)
        for name, content, mime in report_attachments(payload):
            (output/name).write_bytes(content)
        (output/"email.html").write_text(render_html(payload),encoding="utf-8")
        print(json.dumps({"output":str(output),"notes":len(payload["data"].get("notes", [])),"tasks":len(payload["data"].get("tasks", [])),"auto_sent_at":str(row.auto_sent_at)},ensure_ascii=False))
    await engine.dispose()
asyncio.run(main())
