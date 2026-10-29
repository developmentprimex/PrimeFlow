from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Body
from sqlalchemy import select

from app.api.routers.ga_personal import PrivateRoute, admin
from app.config import settings
from app.db import get_db
from app.models.ga_personal import GaPersonalSpace
from app.schemas.ga_personal_discord import DiscordSettings, LeaseRequest, DeliveryResult, DiscordAction, PollRequest, SyncResult
from app.services import ga_personal as tasks
from app.services import ga_personal_discord as service

router = APIRouter(route_class=PrivateRoute)


async def bridge(x_ga_bridge_key: str | None = Header(default=None), db=Depends(get_db)):
    expected = settings.GA_PERSONAL_DISCORD_BRIDGE_SECRET or ""
    if (not settings.GA_PERSONAL_ENABLED or len(expected) < 32 or not x_ga_bridge_key
        or not secrets.compare_digest(expected, x_ga_bridge_key)):
        raise HTTPException(401, "Lidhje e paautorizuar.")
    candidate = (await db.execute(select(GaPersonalSpace).where(GaPersonalSpace.key == "ga_personal"))).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(403, "Hapësira private nuk është konfiguruar.")
    return await tasks.lock_space(db, candidate.id)


@router.get("/discord/settings")
async def read_settings(member=Depends(admin), db=Depends(get_db)):
    return await service.get_settings(db, member)


@router.put("/discord/settings")
async def update_settings(payload: DiscordSettings, member=Depends(admin), db=Depends(get_db)):
    return await service.save_settings(db, member, payload)


@router.post("/bridge/poll")
async def poll(payload: PollRequest = Body(default=PollRequest()), space=Depends(bridge), db=Depends(get_db)):
    return await service.poll(db, space, delivery_enabled=payload.delivery_enabled, health_only=payload.health_only)


@router.post("/bridge/deliveries/{delivery_id}/prepare")
async def prepare(delivery_id: uuid.UUID, payload: LeaseRequest, space=Depends(bridge), db=Depends(get_db)):
    return await service.prepare(db, space, delivery_id, payload)


@router.post("/bridge/deliveries/{delivery_id}/result")
async def result(delivery_id: uuid.UUID, payload: DeliveryResult, space=Depends(bridge), db=Depends(get_db)):
    return await service.report(db, space, delivery_id, payload)


@router.post("/bridge/deliveries/{delivery_id}/action")
async def action(delivery_id: uuid.UUID, payload: DiscordAction, space=Depends(bridge), db=Depends(get_db)):
    return await service.action(db, space, delivery_id, payload)


@router.post("/bridge/deliveries/{delivery_id}/sync")
async def synced(delivery_id: uuid.UUID, payload: SyncResult, space=Depends(bridge), db=Depends(get_db)):
    return await service.synced(db, space, delivery_id, payload)
