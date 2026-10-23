import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import text
from sqlalchemy.engine import make_url
from app.config import settings
from app.db import SessionLocal, engine

async def main():
    url = make_url(settings.DATABASE_URL)
    print(json.dumps({'host': url.host, 'database': url.database}))
    async with SessionLocal() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        rows = (await db.execute(text("""
            SELECT t.id, t.title, t.assigned_to, u.full_name, t.status,
                   t.start_date, t.due_date, t.original_due_date,
                   t.ga_note_origin_id, t.plan_note_origin_id, t.is_active,
                   t.created_at, t.updated_at
            FROM tasks t LEFT JOIN users u ON u.id=t.assigned_to
            WHERE t.title ILIKE '%ACC QE I KEMI PER PX%'
            ORDER BY t.created_at, u.full_name
        """))).mappings().all()
        print('TASKS', json.dumps([{k: v for k, v in dict(r).items() if k != 'title'} for r in rows], default=str, ensure_ascii=False))
        ids = {r['id'] for r in rows}
        ids.update(r[k] for r in rows for k in ('ga_note_origin_id', 'plan_note_origin_id') if r[k])
        if ids:
            logs = (await db.execute(text("""
                SELECT entity_id, entity_type, action, created_at, before, after
                FROM audit_logs WHERE entity_id = ANY(:ids)
                ORDER BY created_at DESC LIMIT 60
            """), {'ids': list(ids)})).mappings().all()
            fields = ('start_date', 'due_date', 'status')
            for r in logs:
                before, after = r['before'] or {}, r['after'] or {}
                if r['action'] == 'updated':
                    before = {k: before.get(k) for k in fields}
                    after = {k: after.get(k) for k in fields}
                elif r['action'] not in ('task.start_date_changed', 'task.due_date_changed'):
                    continue
                print('AUDIT', json.dumps({'id': r['entity_id'], 'at': r['created_at'], 'action': r['action'], 'before': before, 'after': after}, default=str))
    await engine.dispose()

asyncio.run(main())
