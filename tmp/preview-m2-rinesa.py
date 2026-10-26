import asyncio
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.api.routers.discord_m2 import data_with_moves
from app.services.discord_m2 import question_rows
from app.services.primeflow_report import report_timezone
from datetime import datetime


async def main():
    user_id = uuid.UUID('e2e3568f-0e54-4067-be33-013c6177d47b')
    async with SessionLocal() as db:
        day = datetime.now(report_timezone()).date()
        owned = set((await db.execute(select(Task.id).where(Task.assigned_to == user_id, Task.is_active.is_(True)))).scalars())
        owned.update((await db.execute(select(TaskAssignee.task_id).where(TaskAssignee.user_id == user_id))).scalars())
        data = await data_with_moves(db, day)
        for kind, row in question_rows(data):
            if uuid.UUID(row['task_id']) in owned:
                print(json.dumps({'kind': kind, 'task_id': row['task_id'], 'title': row['title'], 'status': row['status'],
                                  'movement': row.get('postponement_kind')}, ensure_ascii=True))
        print(json.dumps({'date': str(day), 'section_counts': {key: len(rows) for key, rows in data.items()}}))
    await engine.dispose()

asyncio.run(main())
