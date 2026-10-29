from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import AwareDatetime

from app.api.deps import http_bearer
from app.api.routers.ga_personal import PrivateRoute, admin
from app.db import get_db
from app.schemas.ga_personal_devices import DeviceCreate, DeviceOpsRequest
from app.services import ga_personal_devices as service
from app.services import ga_personal_device_sync as sync

router = APIRouter(route_class=PrivateRoute)


async def device_access(credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
                        x_device_id: str | None = Header(default=None), db=Depends(get_db)):
    return await service.authenticate_device(db, credentials.credentials if credentials else None, x_device_id)


@router.get("/devices")
async def devices(member=Depends(admin), db=Depends(get_db)):
    return await service.list_devices(db, member)


@router.post("/devices", status_code=201)
async def create_device(payload: DeviceCreate, member=Depends(admin), db=Depends(get_db)):
    return await service.create_device(db, member, payload)


@router.post("/devices/{device_id}/revoke")
async def revoke_device(device_id: uuid.UUID, member=Depends(admin), db=Depends(get_db)):
    return await service.revoke_device(db, member, device_id)


@router.get("/device/state")
async def state(since: AwareDatetime | None = None, device=Depends(device_access), db=Depends(get_db)):
    return await sync.read_state(db, device, since)


@router.post("/device/ops")
async def operations(payload: DeviceOpsRequest, device=Depends(device_access), db=Depends(get_db)):
    return await sync.apply_ops(db, device, payload)
