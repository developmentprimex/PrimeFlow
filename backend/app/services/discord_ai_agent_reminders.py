"""Durable, recipient-scoped AI Agent invitations, independent of audio capture."""
from datetime import datetime, timedelta
import hashlib
import uuid
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from app.models.discord_assistant import DiscordLink, DiscordReminder
from app.models.user import User


def due(at, slot, config):
    if not config.get('enabled') or slot not in config['times']:
        return False
    local=at.astimezone(ZoneInfo(config['timezone']))
    hour,minute=map(int,slot.split(':'))
    scheduled=local.replace(hour=hour,minute=minute,second=0,microsecond=0)
    return local.weekday()<5 and timedelta(0)<=local-scheduled<timedelta(minutes=5)


async def claim(db, at, slot, config):
    if not due(at,slot,config):return []
    local=at.astimezone(ZoneInfo(config['timezone']))
    targets=[uuid.UUID(value) for value in config['user_ids']]
    links=(await db.execute(select(DiscordLink,User.full_name).join(User,User.id==DiscordLink.user_id).where(
        User.id.in_(targets),User.is_active.is_(True),DiscordLink.enabled.is_(True),
        DiscordLink.guild_id==config['guild_id'],DiscordLink.channel_id.is_not(None)).order_by(DiscordLink.id))).all()
    jobs=[]
    for link,name in links:
        lease=at+timedelta(seconds=50)
        stmt=insert(DiscordReminder).values(id=uuid.uuid4(),link_id=link.id,day=local.date(),
            bucket='AI_AGENT_'+slot,lease_until=lease)
        stmt=stmt.on_conflict_do_update(constraint='uq_discord_reminder_bucket',
            set_={'lease_until':lease},where=DiscordReminder.sent_at.is_(None)&(DiscordReminder.lease_until<at))
        reminder_id=(await db.execute(stmt.returning(DiscordReminder.id))).scalar_one_or_none()
        if reminder_id:
            jobs.append({'id':str(reminder_id),'lease_until':lease.isoformat(),'day':local.date().isoformat(),
                'slot':slot,'guild_id':link.guild_id,'channel_id':link.channel_id,
                'discord_user_id':link.discord_user_id,'name':name,'voice_channel_id':config['voice_channel_id']})
    await db.commit()
    return jobs


def invitation(job):
    marker=f'AI Agent invitation · {job["day"]} · {job["slot"]}'
    return {'content':f'<@{job["discord_user_id"]}> 🔔 **Takimi AI Agent · {job["slot"]}**\nKyçu në kanalin zanor AI Agent.',
        'allowed_mentions':{'parse':[],'users':[job['discord_user_id']],'replied_user':False},
        'embeds':[{'description':f'🎧 <#{job["voice_channel_id"]}>','color':0x00A88F,'footer':{'text':marker}}],
        'components':[{'type':1,'components':[{'type':2,'style':5,'label':'Kyçu në AI Agent',
            'url':f'https://discord.com/channels/{job["guild_id"]}/{job["voice_channel_id"]}'}]}],
        'nonce':hashlib.sha256(('ai-agent-invite:'+job['id']).encode()).hexdigest()[:24],'enforce_nonce':True}


async def deliver(client, job, *, bot_id):
    payload=invitation(job)
    # If a send succeeded but the receipt failed, a retry reuses the existing message.
    response=await client.get(f'/channels/{job["channel_id"]}/messages',params={'limit':100})
    response.raise_for_status()
    marker=payload['embeds'][0]['footer']['text']
    for message in response.json():
        if message.get('author',{}).get('id')==bot_id and any(embed.get('footer',{}).get('text')==marker for embed in message.get('embeds',[])):
            return message['id']
    response=await client.post(f'/channels/{job["channel_id"]}/messages',json=payload)
    response.raise_for_status()
    return response.json()['id']


async def acknowledge(db, job, message_id, at):
    result=await db.execute(update(DiscordReminder).where(DiscordReminder.id==uuid.UUID(job['id']),
        DiscordReminder.lease_until==datetime.fromisoformat(job['lease_until']),DiscordReminder.sent_at.is_(None))
        .values(sent_at=at,message_ids=[str(message_id)]))
    await db.commit()
    return bool(result.rowcount)


async def release(db, job, at):
    await db.execute(update(DiscordReminder).where(DiscordReminder.id==uuid.UUID(job['id']),
        DiscordReminder.lease_until==datetime.fromisoformat(job['lease_until']),DiscordReminder.sent_at.is_(None))
        .values(lease_until=at-timedelta(seconds=1)))
    await db.commit()
