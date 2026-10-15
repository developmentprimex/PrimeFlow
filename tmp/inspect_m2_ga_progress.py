import asyncio, json, sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db import SessionLocal, engine
from app.models.task import Task
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.services.personal_task_owner import personal_task_owner
from app.services.daily_realization_events import semantic_local_day
from app.services.primeflow_report import report_timezone
from app.services.m2_reporting_points import select_task_sections, build_task_data
from app.services.note_markup import parse_marked_note_content
from app.api.routers.common_view import _get_task_dates, _normalize_multiline_title
async def main():
    day = datetime.now(report_timezone()).date()
    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        tasks = list((await db.execute(select(Task).where(Task.is_active.is_(True), Task.is_personal.is_(True)))).scalars())
        ga = dict((await db.execute(select(GaNote.id, GaNote.content).where(GaNote.id.in_({t.ga_note_origin_id for t in tasks if t.ga_note_origin_id})))).all())
        plan = dict((await db.execute(select(PlanNote.id, PlanNote.content).where(PlanNote.id.in_({t.plan_note_origin_id for t in tasks if t.plan_note_origin_id})))).all())
        live = (await build_task_data(db, day))["ga_progress"]
        selected = {r["task_id"] for r in live}
        saved = (await db.execute(select(M2ReportingPointsReport).where(M2ReportingPointsReport.report_date == day))).scalar_one_or_none()
        result = []
        for t in tasks:
            title = parse_marked_note_content(_normalize_multiline_title(ga.get(t.ga_note_origin_id) or plan.get(t.plan_note_origin_id) or t.title)).text
            if personal_task_owner(title) != "GA" or day not in _get_task_dates(t, False, day):
                continue
            result.append({"id":str(t.id), "title":title.splitlines()[0][:150], "task_title":t.title.splitlines()[0][:150],
                "owner":personal_task_owner(title), "period":t.finish_period,"marker":t.one_h_marker,"start":str(t.start_date),"due":str(t.due_date),
                "ga_origin":bool(t.ga_note_origin_id),"plan_origin":bool(t.plan_note_origin_id),
                "current_selected":str(t.id) in selected,
                "saved_selected":any(r["task_id"]==str(t.id) for r in (saved.data or {}).get("ga_progress", [])) if saved else False})
        assert all(item["current_selected"] for item in result if item["period"] in {"AM", "AM/PM"})
        print(json.dumps({"verified":True,"live_ga_count":len(live),"day":str(day),"generated_at":str(saved.generated_at) if saved else None,"personal_ga":result},ensure_ascii=False))
    await engine.dispose()
asyncio.run(main())
