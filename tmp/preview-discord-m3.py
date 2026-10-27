"""Read-only production-data preview; never creates or sends a question."""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.discord_assistant import DiscordLink
from app.models.user import User
from app.config import settings
from app.api.routers import discord_m3 as api
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
if not settings.DISCORD_GUILD_ID:
    settings.DISCORD_GUILD_ID = json.loads((remote / '.discord-worker-status.json').read_text(encoding='utf-8'))['guild_id']


async def main():
    now = datetime.now(api.report_timezone())
    day, target = now.date(), api.rules.target_day(now.date())
    async with SessionLocal() as db:
        data = await api.reports.build_task_data(db, day)
        rows, owners, names = await api.tomorrow_data(db, target)
        links = (await db.execute(select(DiscordLink).join(User, User.id == DiscordLink.user_id).where(
            DiscordLink.enabled.is_(True), User.is_active.is_(True), DiscordLink.channel_id.is_not(None),
            DiscordLink.guild_id == settings.DISCORD_GUILD_ID))).scalars().all()
        slots = api.rules.slot_questions(rows, owners, names)
        print(json.dumps({'day': day.isoformat(), 'next_workday': target.isoformat(),
            'linked_people': len(links), 'm3_todo': len(data.get('untouched', [])),
            'm3_delivery': len(data.get('delivery', [])), 'tomorrow_tasks': len(rows),
            'tomorrow_1h_tasks': sum(row['is_1h'] for row in rows),
            'missing_1h_slots': sum(row['missing_slot'] for row in slots),
            'other_slot_checks': sum(not row['missing_slot'] for row in slots)}))
    await engine.dispose()

asyncio.run(main())
