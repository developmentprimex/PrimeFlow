import asyncio
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select, or_
from app.db import SessionLocal
from app.models.user import User
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.plan_note import PlanNote
from app.models.ga_note import GaNote
from app.models.audit_log import AuditLog
from app.api.routers.common_view import _get_task_dates, _initials


async def main():
    async with SessionLocal() as db:
        users = (await db.execute(select(User))).scalars().all()
        names = {u.id: u.full_name or u.username for u in users}
        for user in users:
            initials = _initials(user.full_name or user.username or '')
            if initials not in {'EP', 'ES', 'DM'}:
                continue
            task_ids = select(TaskAssignee.task_id).where(TaskAssignee.user_id == user.id)
            tasks = (await db.execute(select(Task).where(Task.is_active.is_(True), Task.project_id.is_(None), Task.system_template_origin_id.is_(None), Task.is_1h_report.is_(False), or_(Task.assigned_to == user.id, Task.id.in_(task_ids))))).scalars().all()
            for task in tasks:
                dates = _get_task_dates(task, (task.phase or '').upper() in {'CHECK', 'CONTROL'}, date(2026, 10, 18))
                if date(2026, 10, 15) not in dates:
                    continue
                print('TASK', {'user': initials, 'title': task.title.splitlines()[0], 'created_by': names.get(task.created_by), 'created_at': str(task.created_at), 'plan_note': str(task.plan_note_origin_id) if task.plan_note_origin_id else None, 'ga_note': str(task.ga_note_origin_id) if task.ga_note_origin_id else None, 'phase': task.phase})
                for cls, origin in ((PlanNote, task.plan_note_origin_id), (GaNote, task.ga_note_origin_id)):
                    if not origin:
                        continue
                    note = await db.get(cls, origin)
                    if note:
                        print('ORIGIN', {'type': cls.__name__, 'created_by': names.get(note.created_by), 'created_at': str(note.created_at), 'content': note.content.splitlines()[0][:180], 'project_id': str(note.project_id) if note.project_id else None})
                logs = (await db.execute(select(AuditLog).where(AuditLog.entity_id.in_([task.id] + [value for value in (task.plan_note_origin_id, task.ga_note_origin_id) if value])).order_by(AuditLog.created_at).limit(12))).scalars().all()
                for log in logs:
                    print('LOG', {'entity': log.entity_type, 'action': log.action, 'actor': names.get(log.actor_user_id), 'at': str(log.created_at), 'after_keys': list((log.after or {}).keys()), 'source': {k:v for k,v in (log.after or {}).items() if k in {'source','origin','project_id','plan_note_origin_id','ga_note_origin_id','task_type','is_bllok','is_1h_report'}}})


asyncio.run(main())
