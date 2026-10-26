"""Read-only production M2 approval readiness and collection evidence."""
import asyncio
import json
import sys
from pathlib import Path
import httpx
from sqlalchemy import text
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.db import SessionLocal, engine

async def main():
    async with SessionLocal() as db:
        rows = (await db.execute(text("SELECT kind, count(*) AS total, count(message_id) AS sent FROM discord_m2_questions WHERE day=CURRENT_DATE GROUP BY kind ORDER BY kind"))).mappings().all()
        print(json.dumps({'today_questions': [dict(row) for row in rows]}))
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get('https://api-flow.primexeu.com/openapi.json')
        response.raise_for_status()
        paths = response.json()['paths']
        found = sorted(path for path in paths if 'm2/postponements' in path)
        print(json.dumps({'approval_routes': found}))
        assert len(found) == 4
        response = await client.get('https://primeflow.primexeu.com/m2-reporting-points', follow_redirects=True)
        print(json.dumps({'frontend_status': response.status_code, 'new_deployment': 'm2-approvals-20261026' in response.text}))
        assert response.status_code == 200 and 'm2-approvals-20261026' in response.text
    await engine.dispose()

asyncio.run(main())
