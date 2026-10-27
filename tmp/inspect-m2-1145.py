"""Read-only diagnostics for the live M2 collection window."""
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import select, text, or_

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(remote / '.env')
for key in ('DISCORD_GUILD_ID', 'DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'FRONTEND_URL'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(root / 'backend'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
from app.db import SessionLocal, engine
from app.models.user import User
from app.models.discord_assistant import DiscordLink
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.task import Task
from app.api.routers import discord_m2 as api


async def main():
    now = datetime.now(api.report_timezone())
    print(json.dumps({'local_now': now.isoformat(), 'collection_open': api.service.collection_open(now),
        'worker': json.loads((remote / '.discord-worker-status.json').read_text(encoding='utf-8'))}))
    async with SessionLocal() as db:
        users = (await db.execute(select(User).where(or_(User.full_name.ilike('%diellza%'), User.full_name.ilike('%muj%'),
            User.username.ilike('%muj%'))))).scalars().all()
        for user in users:
            links = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == user.id))).scalars().all()
            print(json.dumps({'user': user.full_name, 'username': user.username, 'active': user.is_active,
                'links': [{'id': str(link.id), 'enabled': link.enabled, 'guild_matches': link.guild_id == config['DISCORD_GUILD_ID'],
                    'channel': link.channel_id} for link in links]}))
            for link in links:
                qs = (await db.execute(select(Question).where(Question.link_id == link.id, Question.day == now.date()))).scalars().all()
                print(json.dumps({'user': user.username, 'questions': [{'id': str(q.id), 'kind': q.kind,
                    'sent': str(q.sent_at), 'message': q.message_id, 'answered': str(q.answered_at),
                    'lease_until': str(q.lease_until), 'title': q.snapshot.get('title', '')[:100]} for q in qs]}))
        qs = (await db.execute(select(Question).where(Question.day == now.date()))).scalars().all()
        print(json.dumps({'total_today': len(qs), 'sent': sum(bool(q.sent_at) for q in qs),
            'unsent_kinds': dict(Counter(q.kind for q in qs if not q.sent_at))}))
        data = await api.data_with_moves(db, now.date())
        candidates = api.service.question_rows(data)
        from app.api.routers.discord_m3 import task_owners
        import uuid
        ids = [uuid.UUID(row['task_id']) for _, row in candidates]
        tasks = (await db.execute(select(Task).where(Task.id.in_(ids)))).scalars().all()
        owners = await task_owners(db, tasks)
        for user in users:
            print(json.dumps({'user': user.username, 'eligible': [{'kind': kind, 'title': row['title'][:100]}
                for kind, row in candidates if user.id in owners.get(row['task_id'], set())]}))
    await engine.dispose()

asyncio.run(main())
logs = Path(r'\\192.168.10.8\C$\pm2-system\logs')
for path in sorted(logs.glob('primeflow-discord*error*.log'), key=lambda p: p.stat().st_mtime, reverse=True)[:2]:
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 18000))
        lines = stream.read().decode('utf-8', errors='replace').splitlines()
    print(json.dumps({'log': path.name, 'tail': lines[-45:]}))
