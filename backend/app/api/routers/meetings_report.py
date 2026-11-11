from __future__ import annotations

from app.services.report_attendance import filter_report_sections

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_manager_or_admin
from app.db import get_db
from app.models.meetings_report_draft import MeetingsReportDraft
from app.models.meetings_report_settings import MeetingsReportSettings
from app.models.enums import UserRole
from app.models.user import User
from app.services.meetings_report import (
    MANUAL_SECTION_TITLES,
    build_meetings_report_sections,
    normalize_meetings_report_sections,
    render_html,
    render_plain_text,
    send_meetings_report,
    subject_for,
)
from app.services.meeting_point_manual_sync import (
    custom_manual_questions,
    merge_common_view_manual_sections,
    reconcile_custom_manual_questions,
    removes_custom_manual_section,
    with_section_keys,
)
from app.services.report_section_merge import preserve_manual_sections
from app.services.primeflow_report import report_timezone
from app.services.primeflow_report_access import can_manage_reports
from app.services.primeflow_report_delivery import configured_recipients
from app.services.meetings_report_scheduler import DEFAULT_RECIPIENTS, normalize_recipients

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
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    recipients: RecipientsPayload


def _recipients_from_payload(value: dict | RecipientsPayload | None) -> dict[str, list[str]]:
    return normalize_recipients(value.model_dump() if isinstance(value, RecipientsPayload) else value)


def _time_from_hhmm(value: str):
    from datetime import time

    hour, minute = value.split(":", 1)
    try:
        return time(hour=int(hour), minute=int(minute))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Send time must be a valid HH:MM value") from exc


def _validate_gmail_config() -> None:
    import os

    missing = [name for name in ("EMAIL_USER", "EMAIL_PASSWORD") if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing required Gmail configuration: " + ", ".join(missing))


def _can_use_meetings_report(user: User) -> bool:
    return True


def _can_edit_meetings_report(user: User) -> bool:
    return can_manage_reports(user) or user.role == "MANAGER"


async def require_meetings_report_user(user: User = Depends(get_current_user)) -> User:
    if not _can_use_meetings_report(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


async def require_meetings_report_editor(user: User = Depends(get_current_user)) -> User:
    if not _can_edit_meetings_report(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or manager access required")
    return user


async def _get_or_create_settings(db: AsyncSession) -> MeetingsReportSettings:
    row = (
        await db.execute(select(MeetingsReportSettings).order_by(MeetingsReportSettings.created_at.asc()))
    ).scalars().first()
    if row is None:
        row = MeetingsReportSettings(recipients=DEFAULT_RECIPIENTS)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _default_draft_recipients(db: AsyncSession) -> dict[str, list[str]]:
    settings = await _get_or_create_settings(db)
    recipients = normalize_recipients(settings.recipients)
    if recipients["to"]:
        return recipients
    configured = normalize_recipients(await configured_recipients())
    return configured if configured["to"] else DEFAULT_RECIPIENTS


def _settings(row: MeetingsReportSettings) -> dict:
    return {
        "id": str(row.id),
        "is_active": row.is_active,
        "send_time": row.send_time.strftime("%H:%M"),
        "timezone": row.timezone,
        "weekdays": row.weekdays or [],
        "recipients": normalize_recipients(row.recipients),
        "last_run_date": row.last_run_date.isoformat() if row.last_run_date else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _draft(db: AsyncSession, row: MeetingsReportDraft) -> dict:
    return {
        "id": str(row.id),
        "report_date": row.report_date.isoformat(),
        "tomorrow_date": row.tomorrow_date.isoformat(),
        "subject": row.subject,
        "recipients": normalize_recipients(row.recipients),
        "sections": with_section_keys("meetings", await filter_report_sections(db, row.sections, row.report_date, tomorrow=row.tomorrow_date)),
        "generated_snapshot": row.generated_snapshot,
        "status": row.status,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "gmail_message_id": row.gmail_message_id,
        "gmail_thread_id": row.gmail_thread_id,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _normalize_saved_draft_sections(db: AsyncSession, row: MeetingsReportDraft) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    sections = with_section_keys("meetings", row.sections)
    settings = await _get_or_create_settings(db)
    sections = await merge_common_view_manual_sections(
        db, sections, "meetings", row.sections, settings.manual_questions
    )
    sections = normalize_meetings_report_sections(sections)
    if sections != (row.sections or []):
        row.sections = sections
        flag_modified(row, "sections")
        await db.commit()
        await db.refresh(row)
    else:
        row.sections = sections


@router.get("/settings")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_manager_or_admin),
) -> dict:
    return _settings(await _get_or_create_settings(db))


@router.put("/settings")
async def update_settings(
    payload: SettingsPayload,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_manager_or_admin),
) -> dict:
    if any(day < 0 or day > 6 for day in payload.weekdays):
        raise HTTPException(status_code=400, detail="Weekdays must be numbers from 0 to 6")
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Timezone is not valid") from exc
    row = await _get_or_create_settings(db)
    row.is_active = payload.is_active
    row.send_time = _time_from_hhmm(payload.send_time)
    row.timezone = payload.timezone
    row.weekdays = sorted(set(payload.weekdays))
    row.recipients = _recipients_from_payload(payload.recipients)
    await db.commit()
    await db.refresh(row)
    return _settings(row)


@router.get("/history")
async def get_delivery_history(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_meetings_report_user),
) -> list[dict]:
    rows = (
        await db.execute(
            select(MeetingsReportDraft)
            .where(MeetingsReportDraft.sent_at.is_not(None))
            .order_by(MeetingsReportDraft.sent_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(row.id),
            "report_date": row.report_date.isoformat(),
            "subject": row.subject,
            "recipients": normalize_recipients(row.recipients),
            "status": row.status,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "gmail_message_id": row.gmail_message_id,
            "last_error": row.last_error,
        }
        for row in rows
    ]


@router.get("")
async def get_draft(
    report_date: date,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_meetings_report_user),
) -> dict:
    row = (
        await db.execute(select(MeetingsReportDraft).where(MeetingsReportDraft.report_date == report_date))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    await _normalize_saved_draft_sections(db, row)
    return await _draft(db, row)


@router.post("/generate")
async def generate_draft(
    report_date: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_meetings_report_user),
) -> dict:
    try:
        tomorrow, sections, snapshot = await build_meetings_report_sections(db, report_date)
        recipients = await _default_draft_recipients(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Generate failed: {exc}") from exc
    row = (
        await db.execute(select(MeetingsReportDraft).where(MeetingsReportDraft.report_date == report_date))
    ).scalar_one_or_none()
    if row is not None:
        sections = preserve_manual_sections(sections, row.sections, MANUAL_SECTION_TITLES)
    settings = await _get_or_create_settings(db)
    sections = await merge_common_view_manual_sections(
        db, sections, "meetings", row.sections if row is not None else None,
        settings.manual_questions,
    )
    if row is None:
        row = MeetingsReportDraft(
            report_date=report_date,
            tomorrow_date=tomorrow,
            subject=subject_for(report_date),
            recipients=normalize_recipients(recipients),
            sections=normalize_meetings_report_sections(sections),
            generated_snapshot=snapshot,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        db.add(row)
    else:
        row.tomorrow_date = tomorrow
        row.subject = subject_for(report_date)
        if not normalize_recipients(row.recipients)["to"]:
            row.recipients = normalize_recipients(recipients)
        row.sections = normalize_meetings_report_sections(sections)
        row.generated_snapshot = snapshot
        row.status = "DRAFT"
        row.last_error = None
        row.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(row)
    return await _draft(db, row)


@router.patch("/{draft_id}")
async def update_draft(
    draft_id: uuid.UUID,
    payload: DraftUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_meetings_report_user),
) -> dict:
    row = await db.get(MeetingsReportDraft, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    can_manage_delivery = _can_edit_meetings_report(user)
    if payload.recipients is not None and not can_manage_delivery:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or manager can change delivery details",
        )
    if payload.subject is not None:
        row.subject = payload.subject
    if payload.recipients is not None:
        row.recipients = _recipients_from_payload(payload.recipients)
    if payload.sections is not None:
        if user.role != UserRole.ADMIN and removes_custom_manual_section(
            row.sections, [{"section_key": section.section_key} for section in payload.sections]
        ):
            raise HTTPException(status_code=403, detail="Only admin can delete manually added report points")
        # Keep user-edited question titles as saved (do not remap via normalize).
        saved = with_section_keys("meetings", [
            {
                "section_key": section.section_key,
                "title": (section.title or "").strip() or "Untitled",
                "body": section.body or "",
            }
            for section in payload.sections
        ])
        previous_questions = custom_manual_questions(row.sections)
        current_questions = custom_manual_questions(saved)
        if current_questions != previous_questions:
            settings = await _get_or_create_settings(db)
            settings.manual_questions = reconcile_custom_manual_questions(
                settings.manual_questions, previous_questions, current_questions
            )
        row.sections = saved
    row.status = "DRAFT" if row.status != "SENT" else row.status
    row.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(row)
    return await _draft(db, row)


@router.get("/{draft_id}/preview")
async def preview_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_meetings_report_user),
) -> dict:
    row = await db.get(MeetingsReportDraft, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    sections = await filter_report_sections(db, row.sections, row.report_date, tomorrow=row.tomorrow_date)
    return {
        "plain_text": render_plain_text(row.subject, row.report_date, row.tomorrow_date, sections),
        "html": render_html(row.subject, row.report_date, row.tomorrow_date, sections),
    }


@router.post("/{draft_id}/send")
async def send_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_meetings_report_editor),
) -> dict:
    row = await db.get(MeetingsReportDraft, draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    recipients = normalize_recipients(row.recipients)
    if not recipients["to"]:
        raise HTTPException(status_code=400, detail="Add at least one To recipient before sending")
    sections = await filter_report_sections(db, row.sections, row.report_date, tomorrow=row.tomorrow_date)
    plain_text = render_plain_text(row.subject, row.report_date, row.tomorrow_date, sections)
    html_body = render_html(row.subject, row.report_date, row.tomorrow_date, sections)
    try:
        _validate_gmail_config()
        message = await send_meetings_report(
            row.subject, recipients, plain_text, html_body,
            db=db, report_day=row.report_date, tomorrow=row.tomorrow_date, sections=sections,
        )
    except Exception as exc:
        row.last_error = str(exc)[:2000]
        await db.commit()
        raise HTTPException(status_code=502, detail=row.last_error)
    row.status = "SENT"
    row.sent_at = datetime.now(report_timezone())
    row.gmail_message_id = message.get("id")
    row.gmail_thread_id = message.get("threadId")
    row.last_error = None
    row.updated_by_user_id = user.id
    await db.commit()
    await db.refresh(row)
    return await _draft(db, row)
