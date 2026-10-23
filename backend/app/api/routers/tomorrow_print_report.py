from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_manager_or_admin
from app.models.tomorrow_print_report_delivery import TomorrowPrintReportDelivery
from app.models.tomorrow_print_report_settings import TomorrowPrintReportSettings
from app.models.user import User
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import report_timezone
from app.services.one_h_print_report_snapshot import (
    get_one_h_print_snapshot,
    save_one_h_print_snapshot,
    serialize_one_h_print_snapshot,
)
from app.services.tomorrow_print_report import (
    REQUIRED_SHTYPI_RECIPIENTS,
    build_tomorrow_print_report,
    ensure_required_shtypi_recipient,
    send_tomorrow_print_report,
)

router = APIRouter()

DEFAULT_RECIPIENTS = {
    "to": ["ga@primexeu.com", *REQUIRED_SHTYPI_RECIPIENTS],
    "cc": [],
    "bcc": [],
}


class RecipientsPayload(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    is_active: bool
    send_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: str = Field(default="Europe/Tirane", min_length=1, max_length=80)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    recipients: RecipientsPayload


def _settings(row: TomorrowPrintReportSettings) -> dict:
    return {
        "is_active": row.is_active,
        "send_time": row.send_time.strftime("%H:%M"),
        "timezone": row.timezone,
        "weekdays": row.weekdays or [],
        "recipients": ensure_required_shtypi_recipient(normalize_recipients(row.recipients)),
        "last_run_date": row.last_run_date.isoformat() if row.last_run_date else None,
    }


def _history(row: TomorrowPrintReportDelivery) -> dict:
    return {
        "id": str(row.id),
        "delivery_date": row.delivery_date.isoformat(),
        "target_date": row.target_date.isoformat(),
        "subject": row.subject,
        "recipients": normalize_recipients(row.recipients),
        "status": row.status,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "last_error": row.last_error,
    }


def _parse_time(value: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Send time must be a valid HH:MM value") from exc


async def _settings_row(db: AsyncSession) -> TomorrowPrintReportSettings:
    row = (
        await db.execute(select(TomorrowPrintReportSettings).order_by(TomorrowPrintReportSettings.created_at.asc()))
    ).scalars().first()
    if row is None:
        row = TomorrowPrintReportSettings(recipients=DEFAULT_RECIPIENTS)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> dict:
    return _settings(await _settings_row(db))


@router.put("/settings")
async def update_settings(payload: SettingsPayload, db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> dict:
    if any(day < 0 or day > 6 for day in payload.weekdays):
        raise HTTPException(status_code=400, detail="Weekdays must be numbers from 0 to 6")
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Timezone is not valid") from exc
    row = await _settings_row(db)
    row.is_active = payload.is_active
    row.send_time = _parse_time(payload.send_time)
    row.timezone = payload.timezone
    row.weekdays = sorted(set(payload.weekdays))
    row.recipients = ensure_required_shtypi_recipient(
        normalize_recipients(payload.recipients.model_dump())
    )
    await db.commit()
    await db.refresh(row)
    return _settings(row)


@router.get("/preview")
async def preview(
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    delivery_date = report_date or datetime.now(report_timezone()).date()
    return await build_tomorrow_print_report(delivery_date, db=db)


@router.get("/snapshot")
async def get_snapshot(
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    delivery_date = report_date or datetime.now(report_timezone()).date()
    row = await get_one_h_print_snapshot(db, "TOMORROW", delivery_date)
    if row is None:
        raise HTTPException(status_code=404, detail="Generated report not found")
    return await serialize_one_h_print_snapshot(db, row)


@router.post("/generate")
async def generate_snapshot(
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    delivery_date = report_date or datetime.now(report_timezone()).date()
    # Opening the view can generate concurrently for several users. Serialize
    # the build and save so the first snapshot is only inserted once.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                     {"key": f"tomorrow_print_generate|{delivery_date.isoformat()}"})
    report = await build_tomorrow_print_report(delivery_date, db=db)
    row = await save_one_h_print_snapshot(
        db,
        report_kind="TOMORROW",
        report_date=delivery_date,
        report=report,
        user=user,
    )
    return await serialize_one_h_print_snapshot(db, row)


@router.post("/send")
async def send(report_date: date | None = None, db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> dict:
    delivery_date = report_date or datetime.now(report_timezone()).date()
    settings = await _settings_row(db)
    recipients = ensure_required_shtypi_recipient(normalize_recipients(settings.recipients))
    if not recipients["to"]:
        raise HTTPException(status_code=400, detail="Add at least one To recipient before sending")
    existing = (
        await db.execute(select(TomorrowPrintReportDelivery).where(TomorrowPrintReportDelivery.delivery_date == delivery_date))
    ).scalar_one_or_none()
    report = await build_tomorrow_print_report(delivery_date, include_attachment=True, db=db)
    if existing is None:
        existing = TomorrowPrintReportDelivery(
            delivery_date=delivery_date,
            target_date=date.fromisoformat(report["target_date"]),
            subject=report["subject"],
            recipients=recipients,
        )
        db.add(existing)
    else:
        # Manual "Send now" deliberately resends even if today's scheduled
        # delivery already succeeded. Scheduler duplicate protection is kept.
        existing.status = "PENDING"
        existing.last_error = None
    try:
        message = await send_tomorrow_print_report(report, recipients)
    except Exception as exc:
        existing.status = "FAILED"
        existing.last_error = str(exc)[:2000]
        await db.commit()
        raise HTTPException(status_code=502, detail="Email delivery failed") from exc
    existing.target_date = date.fromisoformat(report["target_date"])
    existing.subject = report["subject"]
    existing.recipients = recipients
    existing.status = "SENT"
    existing.sent_at = datetime.now(report_timezone())
    existing.gmail_message_id = message.get("id")
    existing.gmail_thread_id = message.get("threadId")
    existing.last_error = None
    settings.last_run_date = existing.sent_at
    await db.commit()
    await db.refresh(existing)
    return _history(existing)


@router.get("/history")
async def history(db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> list[dict]:
    rows = (
        await db.execute(select(TomorrowPrintReportDelivery).order_by(TomorrowPrintReportDelivery.created_at.desc()).limit(50))
    ).scalars().all()
    return [_history(row) for row in rows]
