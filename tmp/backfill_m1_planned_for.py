import asyncio
from datetime import datetime
from app.db import SessionLocal, engine
from app.services.m1_reporting_points import locked_report, backfill_saved_task_planning, report_timezone


async def main():
    async with SessionLocal() as db:
        row = await locked_report(db, datetime.now(report_timezone()).date())
        changed = await backfill_saved_task_planning(db, row)
        if changed:
            await db.commit()
        rows = (row.data or {}).get("tasks") or []
        print({"updated": changed, "tasks": len(rows),
               "missing_planned_for": sum(not task.get("planned_for") for task in rows)})
    await engine.dispose()


asyncio.run(main())
