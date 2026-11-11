from __future__ import annotations

from app.services.report_attendance import filter_report_sections

import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_manager_or_admin
from app.db import get_db
from app.models.end_week_bz_report_draft import EndWeekBzReportDraft
from app.models.end_week_bz_report_settings import EndWeekBzReportSettings
from app.models.user import User
from app.services.end_week_bz_report import (
    build_end_week_bz_report_sections, normalize_sections, render_html, render_plain_text,
    send_end_week_bz_report, subject_for,
)
from app.services.meetings_report_scheduler import DEFAULT_RECIPIENTS, normalize_recipients
from app.services.primeflow_report import report_timezone
from app.services.primeflow_report_delivery import configured_recipients

router = APIRouter()


class SectionPayload(BaseModel):
    section_key: str | None = None
    title: str
    body: str = ""


class RecipientsPayload(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class DraftUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    recipients: RecipientsPayload | None = None
    sections: list[SectionPayload] | None = None


class SettingsPayload(BaseModel):
    is_active: bool
    send_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: str = Field(default="Europe/Tirane", min_length=1, max_length=80)
    weekdays: list[int] = Field(default_factory=lambda: [4])
    recipients: RecipientsPayload


async def _settings_row(db: AsyncSession) -> EndWeekBzReportSettings:
    row = (await db.execute(select(EndWeekBzReportSettings).order_by(EndWeekBzReportSettings.created_at))).scalars().first()
    if row is None:
        configured = normalize_recipients(await configured_recipients())
        row = EndWeekBzReportSettings(recipients=configured if configured["to"] else DEFAULT_RECIPIENTS)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _settings(row: EndWeekBzReportSettings) -> dict:
    return {"id": str(row.id), "is_active": row.is_active, "send_time": row.send_time.strftime("%H:%M"), "timezone": row.timezone, "weekdays": row.weekdays or [], "recipients": normalize_recipients(row.recipients), "last_run_date": row.last_run_date}


async def _draft(db: AsyncSession, row: EndWeekBzReportDraft) -> dict:
    return {"id": str(row.id), "report_date": row.report_date, "subject": row.subject, "recipients": normalize_recipients(row.recipients), "sections": await filter_report_sections(db, normalize_sections(row.sections), row.report_date), "generated_snapshot": row.generated_snapshot, "status": row.status, "sent_at": row.sent_at, "gmail_message_id": row.gmail_message_id, "gmail_thread_id": row.gmail_thread_id, "last_error": row.last_error, "updated_at": row.updated_at}


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> dict:
    return _settings(await _settings_row(db))


@router.put("/settings")
async def update_settings(payload: SettingsPayload, db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> dict:
    if any(day < 0 or day > 6 for day in payload.weekdays):
        raise HTTPException(status_code=400, detail="Weekdays must be numbers from 0 to 6")
    try:
        ZoneInfo(payload.timezone)
        hour, minute = payload.send_time.split(":")
        send_time = time(int(hour), int(minute))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid timezone or send time") from exc
    row = await _settings_row(db)
    row.is_active, row.send_time, row.timezone = payload.is_active, send_time, payload.timezone
    row.weekdays = sorted(set(payload.weekdays))
    row.recipients = normalize_recipients(payload.recipients.model_dump())
    await db.commit(); await db.refresh(row)
    return _settings(row)


@router.get("/history")
async def history(limit: int = 50, db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> list[dict]:
    rows = (await db.execute(select(EndWeekBzReportDraft).where(EndWeekBzReportDraft.sent_at.is_not(None)).order_by(EndWeekBzReportDraft.sent_at.desc()).limit(min(max(limit, 1), 100)))).scalars().all()
    return [await _draft(db, row) for row in rows]


@router.get("")
async def get_draft(report_date: date, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    row = (await db.execute(select(EndWeekBzReportDraft).where(EndWeekBzReportDraft.report_date == report_date))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return await _draft(db, row)


@router.post("/generate")
async def generate(report_date: date, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    sections, snapshot = await build_end_week_bz_report_sections(db, report_date)
    settings = await _settings_row(db)
    row = (await db.execute(select(EndWeekBzReportDraft).where(EndWeekBzReportDraft.report_date == report_date))).scalar_one_or_none()
    if row is None:
        row = EndWeekBzReportDraft(report_date=report_date, subject=subject_for(report_date), recipients=normalize_recipients(settings.recipients), sections=sections, generated_snapshot=snapshot, created_by_user_id=user.id, updated_by_user_id=user.id)
        db.add(row)
    else:
        # All sections are generated tables. Regeneration intentionally refreshes live data.
        row.subject, row.sections, row.generated_snapshot = subject_for(report_date), sections, snapshot
        row.status, row.last_error, row.updated_by_user_id = "DRAFT", None, user.id
    await db.commit(); await db.refresh(row)
    return await _draft(db, row)


@router.patch("/{draft_id}")
async def update_draft(draft_id: uuid.UUID, payload: DraftUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = await db.get(EndWeekBzReportDraft, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if payload.subject is not None: row.subject = payload.subject
    if payload.recipients is not None: row.recipients = normalize_recipients(payload.recipients.model_dump())
    if payload.sections is not None:
        row.sections = normalize_sections([item.model_dump() for item in payload.sections])
    if row.status != "SENT": row.status = "DRAFT"
    row.updated_by_user_id = user.id
    await db.commit(); await db.refresh(row)
    return await _draft(db, row)


@router.get("/{draft_id}/preview")
async def preview(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    row = await db.get(EndWeekBzReportDraft, draft_id)
    if row is None: raise HTTPException(status_code=404, detail="Draft not found")
    sections = await filter_report_sections(db, normalize_sections(row.sections), row.report_date)
    return {"plain_text": render_plain_text(row.subject, row.report_date, sections), "html": render_html(row.subject, row.report_date, sections)}


@router.post("/{draft_id}/send")
async def send(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_manager_or_admin)) -> dict:
    row = await db.get(EndWeekBzReportDraft, draft_id)
    if row is None: raise HTTPException(status_code=404, detail="Draft not found")
    recipients = normalize_recipients(row.recipients)
    if not recipients["to"]: raise HTTPException(status_code=400, detail="Add at least one To recipient before sending")
    sections = await filter_report_sections(db, normalize_sections(row.sections), row.report_date)
    try:
        message = await send_end_week_bz_report(row.subject, recipients, render_plain_text(row.subject, row.report_date, sections), render_html(row.subject, row.report_date, sections), report_day=row.report_date, sections=sections)
    except Exception as exc:
        row.last_error = str(exc)[:2000]; await db.commit()
        raise HTTPException(status_code=502, detail=row.last_error) from exc
    row.status, row.sent_at = "SENT", datetime.now(report_timezone())
    row.gmail_message_id, row.gmail_thread_id, row.last_error, row.updated_by_user_id = message.get("id"), message.get("threadId"), None, user.id
    await db.commit(); await db.refresh(row)
    return await _draft(db, row)
