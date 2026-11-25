from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.schemas.internal_meeting_session import (
    InternalMeetingSessionEnsure,
    InternalMeetingSessionOut,
)
from app.services.development_m1 import ensure_development_m1_internal_item
from app.services.internal_meeting_sessions import ensure_internal_meeting_session


router = APIRouter()


@router.post("/ensure", response_model=InternalMeetingSessionOut)
async def ensure_session(
    payload: InternalMeetingSessionEnsure,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
) -> InternalMeetingSessionOut:
    try:
        session = await ensure_internal_meeting_session(db, checklist_id=payload.checklist_id)
    except ValueError as exc:
        detail = str(exc) or "Invalid checklist"
        status_code = status.HTTP_400_BAD_REQUEST
        if "not found" in detail.lower():
            status_code = status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=status_code, detail=detail) from exc

    result = InternalMeetingSessionOut(
        session_id=session.id,
        checklist_id=session.checklist_id,
        session_date=session.session_date,
        starts_at=session.starts_at,
        ends_at=session.ends_at,
        reset_at=session.reset_at,
    )
    if await ensure_development_m1_internal_item(db, payload.checklist_id):
        await db.commit()
    return result
