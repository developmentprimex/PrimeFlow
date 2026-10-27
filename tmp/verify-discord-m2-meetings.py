"""Read-only M2 AM meeting readiness: forecast collection without sending it."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, time
from pathlib import Path
import httpx
from dotenv import dotenv_values
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(remote / '.env')
sys.path.insert(0, str(root / 'backend'))
from sqlalchemy import select
from app.db import SessionLocal, engine
from app.models.discord_assistant import DiscordLink
from app.models.user import User
from app.services import discord_meetings
from app.services.primeflow_report import report_timezone

async def main():
    for file in ('app/services/discord_meetings.py', 'app/api/routers/discord_assistant.py', 'discord_ui.py'):
        assert hashlib.sha256((remote / file).read_bytes()).digest() == hashlib.sha256((root / 'backend' / file).read_bytes()).digest()
    async with SessionLocal() as db:
        ids = (await db.execute(select(DiscordLink.user_id).join(User, User.id == DiscordLink.user_id).where(
            DiscordLink.enabled.is_(True), DiscordLink.channel_id.is_not(None), DiscordLink.guild_id == config['DISCORD_GUILD_ID'], User.is_active.is_(True)))).scalars().all()
        now = datetime.combine(datetime.now(report_timezone()).date(), time(11, 45), report_timezone())
        due = await discord_meetings.m2_due_alerts(db, now, ids)
        print(json.dumps({'source_verified': True, 'forecast_at': now.isoformat(),
            'unfilled_am_meetings': len({meeting.id for meeting, *_ in due}),
            'question_recipients': len(due), 'messages_sent_by_verification': 0}))
    async with httpx.AsyncClient(timeout=15) as client:
        for base in ('http://192.168.10.8:8000', 'http://192.168.10.8:8080', 'https://api-flow.primexeu.com'):
            response = await client.get(base + '/openapi.json')
            response.raise_for_status()
            assert '/api/discord/bot/meetings/{alert_id}/status' in response.json()['paths']
            print(json.dumps({'api': base, 'ready': True}))
    await engine.dispose()

asyncio.run(main())
