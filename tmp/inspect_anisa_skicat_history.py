import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import text
from app.db import SessionLocal, engine

async def main():
    try:
        async with SessionLocal() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            rows = (await db.execute(text('''
                SELECT t.id, t.title, t.status, t.is_active, t.phase, t.created_at,
                       t.start_date, t.due_date, t.completed_at, t.updated_at,
                       t.daily_products, t.internal_notes, u.full_name AS assignee,
                       p.title AS project, u.department_id, t.assigned_to
                FROM tasks t LEFT JOIN users u ON u.id=t.assigned_to
                LEFT JOIN projects p ON p.id=t.project_id
                WHERE t.title = 'TT-PIM SKICAT' AND u.full_name = 'Anisa Ternava'
                  AND t.start_date::date = '2026-10-19'
                ORDER BY t.start_date DESC NULLS LAST, t.created_at
            '''))).mappings().all()
            print('TASKS', json.dumps([dict(r) for r in rows], default=str))
            for row in rows:
                if not str(row['start_date']).startswith('2026-10-19'):
                    continue
                logs = (await db.execute(text('''
                    SELECT a.action, a.before, a.after, a.created_at, u.full_name AS actor
                    FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_user_id
                    WHERE a.entity_id=:id ORDER BY a.created_at
                '''), {'id': row['id']})).mappings().all()
                print('AUDIT_COUNT', row['id'], len(logs))
                for log in logs:
                    before, after = log['before'] or {}, log['after'] or {}
                    if log['action'].startswith('task.') or log['action'] == 'created' or any(before.get(k) != after.get(k) for k in ('due_date', 'start_date', 'status', 'completed_at')):
                        print('EVENT', json.dumps({'id': row['id'], 'action': log['action'], 'at': log['created_at'], 'actor': log['actor'], 'before': {k:v for k,v in before.items() if k in ('value','due_date','start_date','status','completed_at')}, 'after': {k:v for k,v in after.items() if k in ('value','due_date','start_date','status','completed_at')}}, default=str))
            if rows:
                from datetime import date
                from app.services.daily_realization_live import build_live_daily_realization
                report = await build_live_daily_realization(db, department_id=rows[0]['department_id'], day=date(2026,10,19), user_id=rows[0]['assigned_to'])
                print('LIVE_META', json.dumps({k:v for k,v in report.items() if k != 'people'}, default=str))
                info = (await db.execute(text('SELECT id, full_name, is_active, department_id FROM users WHERE id=:id'), {'id': rows[0]['assigned_to']})).mappings().all()
                print('USER', json.dumps([dict(r) for r in info], default=str))
                for person in report['people']:
                    print('LIVE_PERSON', json.dumps({'user_id': person['user_id'], 'metrics':person['metrics'], 'tasks':[{k:v for k,v in t.items() if k in ('task_id','classification','current_status','completion_credited','in_original_plan')} for t in person['tasks']]}, default=str))
            await db.rollback()
    finally:
        await engine.dispose()

asyncio.run(main())
