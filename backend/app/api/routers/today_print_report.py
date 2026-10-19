from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_manager_or_admin
from app.models.today_print_report_delivery import TodayPrintReportDelivery
from app.models.today_print_report_settings import TodayPrintReportSettings
from app.models.one_h_print_report_snapshot import OneHPrintReportSnapshot
from app.models.user import User
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import report_timezone
from app.services.today_print_report_freeze import (
    FROZEN_KIND, TodayPrintFreezeMissing, frozen_history, frozen_report, is_closed, local_now,
    today_report, view_metadata,
)
from app.services.one_h_print_report_snapshot import (
    get_one_h_print_snapshot,
    save_one_h_print_snapshot,
    serialize_one_h_print_snapshot,
)
from app.services.today_print_strikes import with_report_strikes
from app.services.tomorrow_print_report import (
    REQUIRED_SHTYPI_RECIPIENTS,
    ensure_required_shtypi_recipient,
    send_tomorrow_print_report,
)

router = APIRouter()
DEFAULT_RECIPIENTS = {
    "to": ["ga@primexeu.com", *REQUIRED_SHTYPI_RECIPIENTS], "cc": [], "bcc": []
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


def _settings(row: TodayPrintReportSettings) -> dict:
    return {
        "is_active": row.is_active,
        "send_time": row.send_time.strftime("%H:%M"),
        "timezone": row.timezone,
        "weekdays": row.weekdays or [],
        "recipients": ensure_required_shtypi_recipient(normalize_recipients(row.recipients)),
        "last_run_date": row.last_run_date.isoformat() if row.last_run_date else None,
    }


def _history(row: TodayPrintReportDelivery) -> dict:
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


async def _settings_row(db: AsyncSession) -> TodayPrintReportSettings:
    row = (
        await db.execute(select(TodayPrintReportSettings).order_by(TodayPrintReportSettings.created_at.asc()))
    ).scalars().first()
    if row is None:
        row = TodayPrintReportSettings(
            send_time=time(8, 50), weekdays=[0, 1, 2, 3, 4], recipients=DEFAULT_RECIPIENTS
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)) -> dict:
    return _settings(await _settings_row(db))


@router.put("/settings")
async def update_settings(
    payload: SettingsPayload, db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)
) -> dict:
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
async def preview(report_date: date | None = None, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    target_date = report_date or datetime.now(report_timezone()).date()
    return await _report(db, target_date)


async def _report(db: AsyncSession, day: date, *, include_attachment: bool = False) -> dict:
    try:
        return await today_report(db, day, include_attachment=include_attachment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _frozen(db: AsyncSession, day: date) -> dict:
    try:
        return await frozen_report(db, day)
    except TodayPrintFreezeMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/frozen-history")
async def get_frozen_history(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    return await frozen_history(db)


@router.get("/freeze-status")
async def freeze_status(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    day = local_now().date()
    ready = (await db.execute(select(exists().where(
        OneHPrintReportSnapshot.report_kind == FROZEN_KIND,
        OneHPrintReportSnapshot.report_date == day,
    )))).scalar() if is_closed(day) else False
    return {"report_date": day.isoformat(), "freeze_ready": bool(ready), **view_metadata(day)}


@router.get("/snapshot")
async def get_snapshot(
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    snapshot_date = report_date or datetime.now(report_timezone()).date()
    if is_closed(snapshot_date):
        return await _frozen(db, snapshot_date)
    row = await get_one_h_print_snapshot(db, "TODAY", snapshot_date)
    if row is None:
        raise HTTPException(status_code=404, detail="Generated report not found")
    result = await serialize_one_h_print_snapshot(db, row)
    result = await with_report_strikes(db, result, snapshot_date)
    if is_closed(snapshot_date):
        return await _frozen(db, snapshot_date)
    return {**result, **view_metadata(snapshot_date)}


@router.post("/generate")
async def generate_snapshot(
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    snapshot_date = report_date or datetime.now(report_timezone()).date()
    if is_closed(snapshot_date):
        return await _frozen(db, snapshot_date)
    if snapshot_date != local_now().date():
        raise HTTPException(status_code=400, detail="Generate Today only for today's date")
    # Serialize manual generations for this date; a delayed request cannot
    # replace a snapshot or return live data across the freeze boundary.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                     {"key": f"today_print_generate|{snapshot_date.isoformat()}"})
    report = await _report(db, snapshot_date)
    if report.get("is_frozen"):
        return report
    row = await save_one_h_print_snapshot(
        db,
        report_kind="TODAY",
        report_date=snapshot_date,
        report=report,
        user=user,
    )
    result = await serialize_one_h_print_snapshot(db, row)
    result = await with_report_strikes(db, result, snapshot_date)
    if is_closed(snapshot_date):
        return await _frozen(db, snapshot_date)
    return {**result, **view_metadata(snapshot_date)}


@router.get("/print-preview")
async def print_preview(
    report_date: date | None = None, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """Return the canonical Today report for printing from Common View."""
    target_date = report_date or datetime.now(report_timezone()).date()
    return await _report(db, target_date)


@router.post("/send")
async def send(
    report_date: date | None = None, db: AsyncSession = Depends(get_db), _: User = Depends(require_manager_or_admin)
) -> dict:
    delivery_date = report_date or datetime.now(report_timezone()).date()
    settings = await _settings_row(db)
    recipients = ensure_required_shtypi_recipient(normalize_recipients(settings.recipients))
    if not recipients["to"]:
        raise HTTPException(status_code=400, detail="Add at least one To recipient before sending")
    existing = (
        await db.execute(
            select(TodayPrintReportDelivery).where(TodayPrintReportDelivery.delivery_date == delivery_date)
        )
    ).scalar_one_or_none()
    report = await _report(db, delivery_date, include_attachment=True)
    if existing is None:
        existing = TodayPrintReportDelivery(
            delivery_date=delivery_date,
            target_date=delivery_date,
            subject=report["subject"],
            recipients=recipients,
        )
        db.add(existing)
    else:
        # "Send now" is an explicit resend. Automatic delivery remains
        # idempotent in the scheduler, but the manual action must not silently
        # return an older SENT history row without sending a new message.
        existing.status = "PENDING"
        existing.last_error = None
    try:
        message = await send_tomorrow_print_report(report, recipients)
    except Exception as exc:
        existing.status = "FAILED"
        existing.last_error = str(exc)[:2000]
        await db.commit()
        raise HTTPException(status_code=502, detail="Email delivery failed") from exc
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
        await db.execute(
            select(TodayPrintReportDelivery).order_by(TodayPrintReportDelivery.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return [_history(row) for row in rows]
