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
from app.models.project import Project
from app.models.department import Department
from app.api.routers.common_view import _get_task_dates, _initials, get_common_view
from app.services.tomorrow_print_report import _project_covered_initials, _missing_one_h_initials, _missing_blocked_initials
from starlette.requests import Request
from starlette.responses import Response


async def main():
    day = date(2026, 10, 15)
    async with SessionLocal() as db:
        users = (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
        for user in users:
            initials = _initials(user.full_name or user.username or '')
            if initials not in {'EP', 'ES', 'DM'}:
                continue
            department = await db.get(Department, user.department_id) if user.department_id else None
            print('USER', initials, user.full_name, department.name if department else '-')
            task_ids = select(TaskAssignee.task_id).where(TaskAssignee.user_id == user.id)
            rows = (await db.execute(select(Task, Project, Department).outerjoin(Project, Task.project_id == Project.id).outerjoin(Department, Project.department_id == Department.id).where(Task.is_active.is_(True), or_(Task.assigned_to == user.id, Task.id.in_(task_ids))))).all()
            found = 0
            for task, project, project_department in rows:
                dates = _get_task_dates(task, (task.phase or '').upper() in {'CHECK', 'CONTROL'}, date(2026, 10, 18))
                if day not in dates:
                    continue
                found += 1
                print({'title': task.title[:180], 'period': task.finish_period or 'AM/PM', 'status': task.status, '1H': task.is_1h_report, 'slot': task.one_h_report_slot, 'BLL': task.is_bllok, 'R1': task.is_r1, 'system': bool(task.system_template_origin_id or task.system_task_slot_id), 'project': project.title[:100] if project else None, 'project_department': project_department.name if project_department else None})
            print('TASK_COUNT', found)
        payload = await get_common_view(Request({'type': 'http', 'headers': []}), Response(), week_start=date(2026, 10, 12), include='entries,tasks', include_all_departments=True, db=db, user=users[0])
        data = payload.model_dump(mode='json')
        covered = _project_covered_initials(data, day)
        missing = _missing_one_h_initials(data, day)
        missing_bll = _missing_blocked_initials(data, day)
        for initials in ('EP', 'ES', 'DM'):
            print('RESULT', initials, {'missing_slots': [slot for slot, names in missing.items() if initials in names], 'project_covers': [slot for slot, names in covered.items() if initials in names], 'missing_BLL': initials in missing_bll})


asyncio.run(main())
