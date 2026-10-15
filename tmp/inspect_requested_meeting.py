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
    print(json.dumps({'host': url.host, 'database': url.database, 'timezone': settings.APP_TIMEZONE}))
    async with SessionLocal() as db:
        queries = {
            'users': "SELECT id, full_name, department_id, role FROM users WHERE is_active AND (full_name ILIKE '%rines%' OR full_name ILIKE '%laurent%' OR full_name ILIKE '%elsa%' OR full_name ILIKE '%hyseni%')",
            'departments': 'SELECT id, name, code FROM departments',
            'similar_meetings': "SELECT id, title, department_id, starts_at, recurrence_type, recurrence_days_of_week FROM meetings WHERE title ILIKE '%TESTING%' OR (meeting_type = 'internal' AND title ILIKE '%ZHV%')",
        }
        for label, query in queries.items():
            rows = (await db.execute(text(query))).mappings().all()
            print(label, json.dumps([dict(row) for row in rows], default=str, ensure_ascii=False))
    await engine.dispose()

asyncio.run(main())
