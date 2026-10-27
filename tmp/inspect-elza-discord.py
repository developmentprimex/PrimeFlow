"""Read-only investigation of Elza's Discord account collision; no codes or secrets."""
import asyncio
import json
import sys
import httpx
from dotenv import dotenv_values
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select, or_
from app.db import SessionLocal, engine
from app.models.user import User
from app.models.discord_assistant import DiscordLink, DiscordLinkCode

async def main():
    async with SessionLocal() as db:
        users = (await db.execute(select(User).where(or_(User.full_name.ilike('%elza%'), User.username.ilike('%elza%'), User.full_name.ilike('%preniq%'))))).scalars().all()
        for user in users:
            link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == user.id))).scalar_one_or_none()
            codes = (await db.execute(select(DiscordLinkCode.expires_at).where(DiscordLinkCode.user_id == user.id))).scalars().all()
            print(json.dumps({'id': str(user.id), 'username': user.username, 'name': user.full_name, 'active': user.is_active,
                'link': {key: str(getattr(link, key)) for key in ('id','discord_user_id','guild_id','channel_id','enabled','created_at')} if link else None,
                'code_expirations': list(map(str, codes))}))
        rows = (await db.execute(select(User.full_name, User.username, DiscordLink.discord_user_id, DiscordLink.enabled).join(DiscordLink, DiscordLink.user_id == User.id))).all()
        print(json.dumps({'links': [dict(row._mapping) for row in rows]}))
    config = dotenv_values(Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend\.env'))
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"https://discord.com/api/v10/guilds/{config['DISCORD_GUILD_ID']}/members/1493249068556750968",
            headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
        response.raise_for_status()
        for member in [response.json()]:
            user = member['user']
            names = ' '.join(str(value or '') for value in (member.get('nick'), user.get('username'), user.get('global_name')))
            if 'elza' in names.lower() or user['id'] == '1493249068556750968':
                print(json.dumps({'discord_member': {'id': user['id'], 'names': names}}))
    await engine.dispose()

asyncio.run(main())
