import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, text
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.db import SessionLocal, engine
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.services.m3_unheld_meetings import build_unheld_meetings
from app.services.m3_reporting_points import current_report_payload
from app.services.primeflow_report import report_timezone

async def main():
    day = datetime.now(report_timezone()).date()
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        row = (await db.execute(select(M3ReportingPointsReport).where(M3ReportingPointsReport.report_date == day))).scalar_one_or_none()
        saved = (row.data or {}).get("unheld_meetings", []) if row else []
        live = await build_unheld_meetings(db, day)
        restored = (await current_report_payload(db, row))["data"]["unheld_meetings"] if row else []
        expected = {item["meeting_id"]: item for item in live}
        assert all(item.get("fill") == expected[item["meeting_id"]]["fill"] and item.get("origin") == expected[item["meeting_id"]]["origin"] for item in restored if item["meeting_id"] in expected)
        assert all(item.get("meeting_relation") == expected[item["meeting_id"]].get("meeting_relation") for item in restored if item["meeting_id"] in expected)
        fields = ("meeting_id", "title", "meeting_type", "time", "status", "origin", "fill", "highlighted", "meeting_relation")
        print(json.dumps({"day": day.isoformat(), "generated_at": row.generated_at.isoformat() if row and row.generated_at else None,
                          "saved": [{key: item.get(key) for key in fields} for item in saved],
                          "restored": [{key: item.get(key) for key in fields} for item in restored if item["meeting_id"] in expected],
                          "colours_verified": True, "live": [{key: item.get(key) for key in fields} for item in live]}, ensure_ascii=False))
    await engine.dispose()

asyncio.run(main())
