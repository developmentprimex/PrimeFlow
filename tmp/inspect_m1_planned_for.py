import asyncio
from datetime import date
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.m1_reporting_points import M1ReportingPointsReport


async def main():
    async with SessionLocal() as db:
        report = (await db.execute(select(M1ReportingPointsReport).where(
            M1ReportingPointsReport.report_date == date(2026, 10, 15)))).scalar_one_or_none()
        if report:
            rows = (report.data or {}).get("tasks") or []
            print({"sent": bool(report.sent_at), "tasks": len(rows),
                   "missing_planned_for": sum(not row.get("planned_for") for row in rows),
                   "missing_marker": sum("marker" not in row for row in rows)})
        else:
            print("No report for today")
    await engine.dispose()


asyncio.run(main())
