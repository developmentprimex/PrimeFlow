import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import text
from app.db import SessionLocal, engine

async def main():
    async with SessionLocal() as db:
        rows = (await db.execute(text('SELECT u.full_name, u.username, u.weekly_planner_sort_order, d.code FROM users u LEFT JOIN departments d ON d.id = u.department_id WHERE u.is_active = true'))).all()
        ranks = {'DEV': 0, 'GD': 1, 'GDS': 1, 'PCM': 2}
        for name, username, order, department in sorted(rows, key=lambda row: (ranks.get(row[3], 99), row[2] is None, row[2] or 0, (row[0] or row[1] or '').casefold())):
            label = name or username or ''
            initials = ''.join(part[0] for part in label.split()).upper()
            print(department, order, initials, label)
    await engine.dispose()

asyncio.run(main())
