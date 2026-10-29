"""Device secrets never authenticate users or authorize the work/Discord APIs."""
from __future__ import annotations

import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models.ga_personal import GaPersonalDevice as Device, GaPersonalMember as Member, GaPersonalSpace as Space
from app.models.user import User
from app.services import ga_personal as tasks

TOKEN_PREFIX = "pfgap_device_"


def device_out(row):
    return {"id": str(row.id), "name": row.name, "device_id": row.device_id,
            "created_at": tasks.aware(row.created_at).isoformat(),
            "last_seen_at": tasks.aware(row.last_seen_at).isoformat() if row.last_seen_at else None,
            "revoked_at": tasks.aware(row.revoked_at).isoformat() if row.revoked_at else None}


async def list_devices(db, member):
    rows = (await db.execute(select(Device).where(Device.space_id == member.space_id)
                            .order_by(Device.created_at.desc()))).scalars().all()
    return [device_out(row) for row in rows]


async def create_device(db, member, payload):
    await tasks.lock_member_space(db, member, need_admin=True)
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = Device(space_id=member.space_id, authorized_by=member.id, name=payload.name,
                 token_hash=tasks.digest(raw))
    db.add(row)
    await db.commit()
    return {**device_out(row), "code": raw}


async def revoke_device(db, member, device_id):
    await tasks.lock_member_space(db, member, need_admin=True)
    row = (await db.execute(select(Device).where(Device.id == device_id, Device.space_id == member.space_id)
                            .with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Pajisja nuk u gjet.")
    if row.revoked_at is None:
        row.revoked_at = tasks.utcnow()
        await db.commit()
    return device_out(row)


async def authenticate_device(db, token, device_id):
    if not settings.GA_PERSONAL_ENABLED:
        raise HTTPException(404, "Moduli nuk është aktivizuar.")
    denied = HTTPException(401, "Kodi ose pajisja nuk është e autorizuar.",
                           headers={"WWW-Authenticate": "Bearer"})
    try:
        device_id = str(uuid.UUID(device_id))
    except (ValueError, TypeError, AttributeError):
        raise denied
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 100:
        raise denied
    row = (await db.execute(select(Device).where(Device.token_hash == tasks.digest(token))
                            .with_for_update())).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise denied
    authorizer = await authorized_member(db, row)
    if authorizer is None or (row.device_id is not None and row.device_id != device_id):
        raise denied
    # A row lock makes simultaneous first requests from different devices atomic.
    row.device_id = device_id
    row.last_seen_at = tasks.utcnow()
    await db.commit()
    return row


async def authorized_member(db, row):
    return (await db.execute(select(Member).join(User, User.id == Member.user_id)
        .join(Space, Space.id == Member.space_id).where(
            Member.id == row.authorized_by, Member.space_id == row.space_id,
            Member.active.is_(True), Member.is_admin.is_(True), User.is_active.is_(True),
            Space.key == "ga_personal",
        ).execution_options(populate_existing=True))).scalar_one_or_none()
