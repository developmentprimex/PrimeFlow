"""Mira view in PrimeFlow: 1H meeting history, Mira's notes, knowledge and host settings."""
import uuid
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, require_manager_or_admin
from app.db import get_db
from app.models.mira_host import MiraKnowledgeItem
from app.services import mira_host as host

router = APIRouter()
Category = Literal["STRUKTURA", "RREGULLORE", "DEFINIME", "PROCESE", "TJETER"]


class KnowledgeIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Category = "TJETER"
    content_text: str = Field(min_length=1, max_length=200000)
    is_active: bool = True
    sort_order: int = 0


class KnowledgePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: Category | None = None
    content_text: str | None = Field(default=None, min_length=1, max_length=200000)
    is_active: bool | None = None
    sort_order: int | None = None


class GaParticipant(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    fallback: str | None = Field(default=None, max_length=200)


class SettingsIn(BaseModel):
    ga_participants: list[GaParticipant] = Field(max_length=10)
    protocol_text: str = Field(min_length=1, max_length=4000)
    target_minutes_per_person: int = Field(ge=1, le=30)
    knowledge_char_budget: int = Field(ge=2000, le=120000)


class HostSwitch(BaseModel):
    enabled: bool
    until: str | None = Field(default=None, max_length=5)


def knowledge_row(row: MiraKnowledgeItem) -> dict:
    return {"id": str(row.id), "title": row.title, "category": row.category, "content_text": row.content_text,
            "source": row.source, "file_name": row.file_name, "is_active": row.is_active, "sort_order": row.sort_order,
            "chars": len(row.content_text or ""),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get('/meetings')
async def meetings(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await host.list_meetings(db, min(max(limit, 1), 200), max(offset, 0))


@router.get('/meetings/{meeting_id}')
async def meeting(meeting_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await host.meeting_detail(db, meeting_id)


@router.post('/meetings/{meeting_id}/summarize')
async def resummarize(meeting_id: uuid.UUID, background: BackgroundTasks, db: AsyncSession = Depends(get_db),
                      user=Depends(require_manager_or_admin)):
    row = await host.meeting_for(db, meeting_id, lock=True)
    if row.status not in ("DONE", "ABORTED") or not row.host_transcript:
        raise HTTPException(409, "Takimi nuk ka përfunduar ose nuk ka transkript.")
    row.summary_status = "PENDING"
    await db.commit()
    background.add_task(host.summarize, row.id)
    return {"ok": True}


@router.get('/notes')
async def notes(limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0),
                db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await host.mira_notes(db, limit, offset)


@router.post('/notes/{kind}/{note_id}/show-in-px-notes')
async def show_note_in_px_notes(kind: Literal["1H", "PX_NOTE"], note_id: uuid.UUID,
                               db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await host.show_mira_note_in_px(db, kind, note_id, user)


@router.get('/notes/{note_id}/transcript')
async def note_transcript(note_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    from app.services import mira_desktop
    desktop=await mira_desktop.note_transcript_for_note(db,user,note_id)
    if desktop is not None:return desktop
    # Existing Discord transcript visibility stays unchanged.
    return await host.note_transcript(db, note_id)


@router.get('/status')
async def status(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await host.live_status(db)
    await db.commit()
    return result


@router.put('/settings')
async def save_settings(payload: SettingsIn, db: AsyncSession = Depends(get_db), user=Depends(require_manager_or_admin)):
    row = await host.get_settings(db, lock=True)
    row.ga_participants = [p.model_dump(exclude_none=True) for p in payload.ga_participants]
    row.protocol_text = payload.protocol_text.strip()
    row.target_minutes_per_person = payload.target_minutes_per_person
    row.knowledge_char_budget = payload.knowledge_char_budget
    await db.commit()
    return host.settings_view(row)


@router.post('/host')
async def switch_host(payload: HostSwitch, db: AsyncSession = Depends(get_db), user=Depends(require_manager_or_admin)):
    row = await host.get_settings(db, lock=True)
    row.enabled_until = host.enable_until(host.now(), payload.until) if payload.enabled else None
    row.enabled_by_user_id = user.id if payload.enabled else row.enabled_by_user_id
    await db.commit()
    return host.settings_view(row)


@router.get('/knowledge')
async def knowledge(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(select(MiraKnowledgeItem).order_by(MiraKnowledgeItem.sort_order,
        MiraKnowledgeItem.category, MiraKnowledgeItem.title))).scalars().all()
    budget = (await host.get_settings(db)).knowledge_char_budget
    await db.commit()
    return {"items": [knowledge_row(r) for r in rows], "budget": budget,
            "active_chars": sum(len(r.content_text or "") for r in rows if r.is_active)}


@router.post('/knowledge')
async def add_knowledge(payload: KnowledgeIn, db: AsyncSession = Depends(get_db), user=Depends(require_manager_or_admin)):
    row = MiraKnowledgeItem(**payload.model_dump(), source="MANUAL", updated_by_user_id=user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return knowledge_row(row)


@router.post('/knowledge/upload')
async def upload_knowledge(file: UploadFile = File(...), title: str | None = Form(default=None),
                           category: Category = Form(default="TJETER"), db: AsyncSession = Depends(get_db),
                           user=Depends(require_manager_or_admin)):
    content = await file.read(5_000_001)
    await file.close()
    if len(content) > 5_000_000:
        raise HTTPException(413, "Skedari është më i madh se 5 MB.")
    text = host.extract_text(file.filename or "", content).strip()
    if not text:
        raise HTTPException(422, "Skedari nuk ka tekst.")
    row = MiraKnowledgeItem(title=(title or (file.filename or "Dokument")).strip()[:200], category=category,
                            content_text=text[:200000], source="FILE", file_name=(file.filename or "")[:255],
                            is_active=True, sort_order=0, updated_by_user_id=user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return knowledge_row(row)


@router.patch('/knowledge/{item_id}')
async def edit_knowledge(item_id: uuid.UUID, payload: KnowledgePatch, db: AsyncSession = Depends(get_db),
                         user=Depends(require_manager_or_admin)):
    row = await db.get(MiraKnowledgeItem, item_id, with_for_update=True)
    if not row:
        raise HTTPException(404, "Nuk u gjet.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, key, value)
    row.updated_by_user_id, row.updated_at = user.id, datetime.now(host.now().tzinfo)
    await db.commit()
    await db.refresh(row)
    return knowledge_row(row)


@router.delete('/knowledge/{item_id}')
async def delete_knowledge(item_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_manager_or_admin)):
    row = await db.get(MiraKnowledgeItem, item_id)
    if row:
        await db.delete(row)
        await db.commit()
    return {"ok": True}
