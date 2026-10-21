"""Preview, or remove with --apply, generated work for canceled external meetings."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.task import Task
from app.services.meeting_cancellation import delete_external_meeting_dependents, external_meeting_is_canceled


async def main(apply: bool) -> None:
    try:
        async with SessionLocal() as db:
            candidates = (await db.execute(select(Meeting).where(
                Meeting.meeting_type == "external",
                Meeting.id.in_(select(MeetingOccurrenceStatus.meeting_id).where(
                    MeetingOccurrenceStatus.status == "canceled")),
            ).with_for_update())).scalars().all()
            meetings = [meeting for meeting in candidates if await external_meeting_is_canceled(db, meeting)]
            external_ids = [meeting.id for meeting in meetings]
            internal_ids = list((await db.execute(select(Meeting.id).where(
                Meeting.meeting_type == "internal",
                or_(Meeting.pre_external_meeting_id.in_(external_ids),
                    Meeting.paired_external_meeting_id.in_(external_ids)),
            ))).scalars().all())
            task_ids = list((await db.execute(select(Task.id).where(
                Task.meeting_origin_id.in_([*external_ids, *internal_ids]),
                Task.meeting_system_task_kind.is_not(None),
            ))).scalars().all())
            url = make_url(settings.DATABASE_URL)
            print(json.dumps({"host": url.host, "database": url.database, "apply": apply,
                "external_meetings_preserved": [{"id": str(m.id), "title": m.title} for m in meetings],
                "internal_meetings_to_delete": len(internal_ids), "generated_tasks_to_delete": len(task_ids)}, ensure_ascii=True))
            if not apply or not (internal_ids or task_ids):
                return

            # Keep complete rows for the removed roots and every directly affected
            # referencing row before the database applies CASCADE / SET NULL.
            roots = {"meetings": internal_ids, "tasks": task_ids}
            backup = {}
            for table in Base.metadata.sorted_tables:
                conditions = []
                if table.name in roots:
                    conditions.append(table.c.id.in_(roots[table.name]))
                for fk in table.foreign_keys:
                    if fk.column.table.name in roots and fk.column.name == "id":
                        conditions.append(fk.parent.in_(roots[fk.column.table.name]))
                if conditions:
                    rows = (await db.execute(select(table).where(or_(*conditions)))).mappings().all()
                    if rows:
                        backup[table.name] = [dict(row) for row in rows]
            backup_dir = Path("private-data/maintenance-backups")
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / ("canceled-meetings-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
            backup_path.write_text(json.dumps(backup, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
            for meeting in meetings:
                await delete_external_meeting_dependents(db, meeting)
            remaining_external_ids = set((await db.execute(select(Meeting.id).where(Meeting.id.in_(external_ids)))).scalars().all())
            assert remaining_external_ids == set(external_ids), "External meetings must be preserved"
            assert not (await db.execute(select(Meeting.id).where(Meeting.id.in_(internal_ids)))).scalars().all()
            assert not (await db.execute(select(Task.id).where(Task.id.in_(task_ids)))).scalars().all()
            await db.commit()
            print(json.dumps({"deleted_internal_meetings": len(internal_ids), "deleted_generated_tasks": len(task_ids),
                "preserved_external_meetings": len(external_ids), "backup": str(backup_path)}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
