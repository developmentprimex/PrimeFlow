"""Run by Windows Task Scheduler at the configured weekday AI Agent times."""
import argparse
import asyncio
from datetime import datetime,timezone
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import httpx
from dotenv import dotenv_values

parser=argparse.ArgumentParser()
parser.add_argument('--config',type=Path,required=True)
parser.add_argument('--slot',required=True)
parser.add_argument('--check',action='store_true')
args=parser.parse_args()
config=json.loads(args.config.read_text(encoding='utf-8'))
backend=Path(config['backend_dir'])
os.chdir(backend);sys.path.insert(0,str(backend))
from app.db import SessionLocal,engine
# Keep the scheduled worker's module beside its config, outside runner cleanups.
module_path=args.config.parent/'service.py'
if module_path.exists():
    spec=importlib.util.spec_from_file_location('ai_agent_invites',module_path)
    service=importlib.util.module_from_spec(spec);spec.loader.exec_module(service)
else:
    from app.services import discord_ai_agent_reminders as service

async def main():
    private=dotenv_values(config['private_env'],interpolate=False)
    primary=dotenv_values(backend/'.env',interpolate=False)
    token=private.get('DISCORD_AI_AGENT_BOT_TOKEN')
    if not token or token in {primary.get('DISCORD_BOT_TOKEN'),primary.get('MIRA_HOST_BOT_TOKEN')}:
        raise ValueError('AI Agent needs its separate bot token')
    failures=[]
    async with httpx.AsyncClient(base_url='https://discord.com/api/v10',timeout=30,
        headers={'Authorization':'Bot '+token}) as client:
        response=await client.get('/users/@me');response.raise_for_status()
        bot=response.json();assert bot['id']==config['bot_id']
        if args.check:
            async with SessionLocal() as db:
                from sqlalchemy import select
                from app.models.discord_assistant import DiscordLink
                from app.models.user import User
                import uuid
                links=(await db.execute(select(DiscordLink,User.full_name).join(User,User.id==DiscordLink.user_id)
                    .where(User.id.in_([uuid.UUID(value) for value in config['user_ids']]),User.is_active.is_(True),
                        DiscordLink.enabled.is_(True),DiscordLink.guild_id==config['guild_id']))).all()
                assert len(links)==4,'All four development users must be linked'
                primary_headers={'Authorization':'Bot '+primary['DISCORD_BOT_TOKEN']}
                basic=(1<<10)|(1<<11)|(1<<14)|(1<<16)
                for link,name in links:
                    r=await client.get('/channels/'+link.channel_id,headers=primary_headers);r.raise_for_status()
                    channel=r.json()
                    assert channel.get('topic')==f'PrimeFlow personal workspace: {link.discord_user_id}'
                    assert channel.get('guild_id')==config['guild_id']
                    overwrite=next((item for item in channel.get('permission_overwrites',[]) if item['id']==config['bot_id'] and item['type']==1),None)
                    # Add only this bot's access; leave every existing overwrite intact.
                    if not overwrite or int(overwrite['allow'])&basic!=basic or int(overwrite['deny'])&basic:
                        repaired=await client.put(f'/channels/{link.channel_id}/permissions/{config["bot_id"]}',
                            headers=primary_headers,json={'type':1,'allow':str(basic),'deny':'0'})
                        repaired.raise_for_status()
                    r=await client.get(f'/channels/{link.channel_id}/messages',params={'limit':1});r.raise_for_status()
                print(json.dumps({'ready':True,'bot_id':bot['id'],'times':config['times'],'timezone':config['timezone'],
                    'recipients':[name for link,name in links],'weekdays_only':True}),flush=True)
        else:
            async with SessionLocal() as db:jobs=await service.claim(db,datetime.now(timezone.utc),args.slot,config)
            for job in jobs:
                try:
                    message_id=await service.deliver(client,job,bot_id=bot['id'])
                    async with SessionLocal() as db:await service.acknowledge(db,job,message_id,datetime.now(timezone.utc))
                    print(json.dumps({'sent':job['id'],'name':job['name'],'slot':job['slot']}),flush=True)
                except Exception as exc:
                    async with SessionLocal() as db:await service.release(db,job,datetime.now(timezone.utc))
                    failures.append(type(exc).__name__)
            print(json.dumps({'claimed':len(jobs),'failed':len(failures),'slot':args.slot}),flush=True)
    await engine.dispose()
    if failures:raise RuntimeError('Invitation delivery failed: '+','.join(failures))

logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
