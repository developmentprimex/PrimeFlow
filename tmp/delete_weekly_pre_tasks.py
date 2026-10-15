import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import delete, select, text
from app.db import SessionLocal, engine
from app.models.task import Task
from app.models.meeting import Meeting
from app.services.meeting_system_tasks import TAK_INT_PRE_ONE_H_TASK_KIND


def is_weekly(meeting):
    return (meeting.recurrence_type or "").strip().casefold() == "weekly" or any(
        "weekly" in str(category).casefold() for category in (meeting.calendar_categories or [])
    )


async def main():
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Task, Meeting).join(Meeting, Meeting.id == Task.meeting_origin_id)
            .where(Task.meeting_system_task_kind == TAK_INT_PRE_ONE_H_TASK_KIND)
        )).all()
        matches = [(task, meeting) for task, meeting in rows if is_weekly(meeting)]
        print(json.dumps({"matching_tasks": len(matches), "tasks": [
            {"id": str(task.id), "title": task.title, "status": task.status, "active": task.is_active,
             "date": str(task.start_date), "meeting": meeting.title}
            for task, meeting in matches
        ]}, ensure_ascii=True))
        refs = (await db.execute(text("""
            SELECT conrelid::regclass::text AS table_name, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint WHERE contype = 'f' AND confrelid = 'tasks'::regclass
        """))).all()
        print(json.dumps({"references": [dict(row._mapping) for row in refs]}))
        if "--apply" in sys.argv and matches:
            task_ids = [task.id for task, _ in matches]
            post_query = select(Task.id).where(Task.meeting_system_task_kind == "tak_int_post_one_h")
            post_before = set((await db.execute(post_query)).scalars().all())
            backup = {}
            task_rows = (await db.execute(select(Task.__table__).where(Task.id.in_(task_ids)))).mappings().all()
            backup["tasks"] = [dict(row) for row in task_rows]
            for table_name, definition in refs:
                if "ON DELETE CASCADE" not in definition:
                    continue
                if not table_name.replace("_", "").isalnum():
                    raise ValueError("Unexpected table name")
                related = (await db.execute(
                    text(f'SELECT * FROM "{table_name}" WHERE task_id = ANY(:task_ids)'),
                    {"task_ids": task_ids},
                )).mappings().all()
                backup[table_name] = [dict(row) for row in related]
            backup_path = Path(__file__).parent / ("weekly_pre_tasks_backup_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
            backup_path.write_text(json.dumps(backup, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
            deleted_ids = set((await db.execute(
                delete(Task).where(Task.id.in_(task_ids), Task.meeting_system_task_kind == TAK_INT_PRE_ONE_H_TASK_KIND).returning(Task.id)
            )).scalars().all())
            assert deleted_ids == set(task_ids), "Unexpected deleted tasks"
            post_after = set((await db.execute(post_query)).scalars().all())
            assert post_after == post_before, "Post tasks changed"
            await db.commit()
            remaining = (await db.execute(select(Task.id).where(Task.id.in_(task_ids)))).scalars().all()
            assert not remaining, "Tasks remain after commit"
            print(json.dumps({"deleted": len(deleted_ids), "remaining": len(remaining), "post_tasks_unchanged": True, "backup": str(backup_path)}))
    await engine.dispose()


asyncio.run(main())
