from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.ga_note import GaNote
from app.models.enums import GaNoteStatus
from app.schemas.ga_note import GaNotePublicOut
from app.services.gmail_px_notes import GMAIL_NOTE_ORIGIN
from app.integrations.gmail_mail import PX_EU_NOTE_ORIGIN
from app.integrations.homeface_mail import NOTE_ORIGIN as HF_NOTE_ORIGIN
from app.integrations.microsoft_mail import INFO_PX_NOTE_ORIGIN, IT_NOTE_ORIGIN


router = APIRouter()

PUBLIC_NOTES_LIMIT = 20


def _public_note_out(note: GaNote) -> GaNotePublicOut:
    return GaNotePublicOut(
        id=note.id,
        content=note.content,
        note_type=note.note_type,
        status=note.status,
        created_at=note.created_at,
    )


@router.get("/ga-notes", response_model=list[GaNotePublicOut])
async def list_public_ga_notes(
    db: AsyncSession = Depends(get_db),
) -> list[GaNotePublicOut]:
    stmt = (
        select(GaNote)
        .where(GaNote.status != GaNoteStatus.CLOSED)
        .where(GaNote.knowledge_type.is_distinct_from(GMAIL_NOTE_ORIGIN))
        .where(GaNote.knowledge_type.is_distinct_from(INFO_PX_NOTE_ORIGIN))
        .where(GaNote.knowledge_type.is_distinct_from(IT_NOTE_ORIGIN))
        .where(GaNote.knowledge_type.is_distinct_from(PX_EU_NOTE_ORIGIN))
        .where(GaNote.knowledge_type.is_distinct_from(HF_NOTE_ORIGIN))
        .order_by(GaNote.created_at.desc())
        .limit(PUBLIC_NOTES_LIMIT)
    )
    notes = (await db.execute(stmt)).scalars().all()
    return [_public_note_out(note) for note in notes]
