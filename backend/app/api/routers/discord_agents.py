from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers import discord_assistant as bridge
from app.db import get_db
from app.models.discord_agent_run import DiscordAgentRun
from app.schemas.discord_agent import AgentActor, AgentCreate, AgentAccept
from app.services import discord_agents as service

router = APIRouter(dependencies=[Depends(bridge.require_bot)])


@router.post("/runs")
async def create(payload: AgentCreate, db: AsyncSession = Depends(get_db)):
    return await service.create_run(db, payload)


@router.post("/tasks/{task_id}/runs")
async def history(task_id: uuid.UUID, payload: AgentActor, offset: int = Query(default=0, ge=0), db: AsyncSession = Depends(get_db)):
    link, user = await bridge.identity(db, payload)
    await bridge.owned_task(db, user, task_id)
    rows = (await db.execute(select(DiscordAgentRun).where(DiscordAgentRun.link_id == link.id,
        DiscordAgentRun.user_id == user.id, DiscordAgentRun.task_id == task_id)
        .order_by(DiscordAgentRun.created_at.desc(), DiscordAgentRun.id.desc()).offset(offset).limit(26))).scalars().all()
    return {"runs": [service.serialize_run(row) for row in rows[:25]], "next_offset": offset + 25 if len(rows) > 25 else None}


@router.post("/runs/{run_id}")
async def detail(run_id: uuid.UUID, payload: AgentActor, db: AsyncSession = Depends(get_db)):
    run, _, _, _ = await service.authorized_run(db, payload, run_id)
    return service.serialize_run(run)


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: uuid.UUID, payload: AgentActor, db: AsyncSession = Depends(get_db)):
    return await service.cancel_run(db, run_id, payload)


@router.post("/runs/{run_id}/accept")
async def accept(run_id: uuid.UUID, payload: AgentAccept, db: AsyncSession = Depends(get_db)):
    return await service.accept_run(db, run_id, payload)
