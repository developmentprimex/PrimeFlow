"""Read-only M1 integration check; no reports saved or emails sent."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from sqlalchemy import select, text
from app.db import SessionLocal, engine
from app.models.ga_note import GaNote
from app.models.enums import GaNoteStatus
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.services.m1_reporting_points import build_data, excluded_note_ids, report_payload, render_html, render_plain_text
from app.services.primeflow_report import report_timezone

async def main():
    now = datetime.now(report_timezone())
    day = now.date()
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        row = (await db.execute(select(M1ReportingPointsReport).where(M1ReportingPointsReport.report_date == day))).scalar_one_or_none()
        data = await build_data(db, day, now)
        morning = await build_data(db, day, now.replace(hour=8, minute=30, second=0, microsecond=0))
        assert data["captured_until"] == now.isoformat()
        assert all(datetime.fromisoformat(item["created_at"]) <= now for key in ("notes", "tasks") for item in data[key])
        details = {"day": day.isoformat(), "new_report_notes": len(data["notes"]), "saved_report_exists": row is not None, "capture_time": now.isoformat(), "live_counts": {key: len(data[key]) for key in ("absences", "delays", "notes", "tasks")}, "morning_counts": {key: len(morning[key]) for key in ("absences", "delays", "notes", "tasks")}}
        if row:
            excluded = await excluded_note_ids(db, row)
            payload = report_payload(row, excluded_note_ids=excluded)
            html_body, plain_text = render_html(payload), render_plain_text(payload)
            ids = {note["id"] for note in payload["data"]["notes"]}
            assert not ids.intersection(excluded)
            live = (await db.execute(select(GaNote).where(GaNote.id.in_(ids)))).scalars().all() if ids else []
            assert all(note.status != GaNoteStatus.CLOSED and not note.is_converted_to_task for note in live)
            highlighted = (await db.execute(select(GaNote).where(GaNote.content.ilike("%RAP PER CDO SHITJE/CLAIM%")))).scalars().all()
            details.update({"stored_notes": len((row.data or {}).get("notes", [])), "visible_notes": len(ids), "excluded_notes": len(excluded), "highlighted_note_statuses": [note.status.value for note in highlighted], "highlighted_note_visible": any(str(note.id) in ids for note in highlighted), "export_verified": bool(html_body and plain_text)})
        print(json.dumps(details))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
