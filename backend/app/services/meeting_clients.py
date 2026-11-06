from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting_client import MeetingClient


async def resolve_meeting_client(
    db: AsyncSession, *, client_id: uuid.UUID | None = None,
    client_name: str | None = None, actor_id: uuid.UUID | None = None,
) -> MeetingClient | None:
    """Reuse one identity across meetings, including concurrent submissions."""
    if client_id is not None:
        client = await db.get(MeetingClient, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Klienti nuk u gjet.")
        return client
    name = " ".join((client_name or "").split())
    if not name:
        return None
    key = name.casefold()
    stmt = insert(MeetingClient).values(id=uuid.uuid4(), name=name, name_key=key, created_by=actor_id)
    # Preserve the existing display name when another user uses different casing.
    stmt = stmt.on_conflict_do_update(index_elements=["name_key"], set_={"name_key": key}).returning(MeetingClient)
    return (await db.execute(stmt)).scalar_one()
