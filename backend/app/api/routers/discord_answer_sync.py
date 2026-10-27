from datetime import datetime, timedelta, timezone
from typing import Literal
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.config import settings
from app.api.routers.discord_assistant import Actor, identity, require_bot
from app.models.discord_assistant import DiscordLink
from app.models.user import User
from app.services import discord_answer_sync as service

router = APIRouter(dependencies=[Depends(require_bot)])


@router.post('/claim')
async def claim(db: AsyncSession = Depends(get_db)):
    acquired = (await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('discord-answer-sync'))"))).scalar()
    if not acquired:
        return {'jobs': []}
    now = datetime.now(timezone.utc)
    jobs = []
    for kind, model in service.MODELS.items():
        query = select(model, DiscordLink).join(DiscordLink, DiscordLink.id == model.link_id).join(User, User.id == DiscordLink.user_id).where(
            model.message_id.is_not(None), model.sent_at.is_not(None), DiscordLink.enabled.is_(True),
            DiscordLink.channel_id.is_not(None), DiscordLink.guild_id == settings.DISCORD_GUILD_ID, User.is_active.is_(True))
        if kind == 'meeting':
            query = query.where(model.kind.in_(('after', 'm2_after')))
        for source, link in (await db.execute(query.order_by(model.sent_at.desc()))).all():
            if source.sync_lease_until and source.sync_lease_until > now:
                continue
            job = await service.make_job(db, kind, source, link)
            if not job or job['fingerprint'] == source.sync_hash:
                continue
            source.sync_pending_hash = job['fingerprint']
            source.sync_lease_until = now + timedelta(minutes=2)
            jobs.append(job)
            if len(jobs) >= 50:
                break
        if len(jobs) >= 50:
            break
    await db.commit()
    return {'jobs': jobs}


async def owned_source(db, kind, object_id, actor):
    link, _ = await identity(db, actor)
    source = await db.get(service.MODELS[kind], object_id, with_for_update=True)
    if not source or source.link_id != link.id or not source.message_id:
        raise HTTPException(403, 'Ky mesazh nuk i përket llogarisë tënde.')
    if kind == 'meeting' and source.kind not in ('after', 'm2_after'):
        raise HTTPException(422, 'Nuk është pyetje për statusin e takimit.')
    return source, link


@router.post('/{kind}/{object_id}/open')
async def open_sync(kind: Literal['m2', 'meeting'], object_id: uuid.UUID, actor: Actor, db: AsyncSession = Depends(get_db)):
    source, link = await owned_source(db, kind, object_id, actor)
    job = await service.make_job(db, kind, source, link)
    if job:
        source.sync_pending_hash = job['fingerprint']
        source.sync_lease_until = datetime.now(timezone.utc) + timedelta(minutes=2)
        await db.commit()
    return {'job': job}


class Receipt(Actor):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')


@router.post('/{kind}/{object_id}/ack')
async def ack(kind: Literal['m2', 'meeting'], object_id: uuid.UUID, value: Receipt, db: AsyncSession = Depends(get_db)):
    source, _ = await owned_source(db, kind, object_id, value)
    if value.fingerprint == source.sync_pending_hash:
        source.sync_hash = value.fingerprint
        source.sync_pending_hash = None
        source.sync_lease_until = None
        await db.commit()
    return {'ok': True}
