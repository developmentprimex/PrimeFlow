from __future__ import annotations

import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.triggers.cron import CronTrigger

from app.api.deps import get_current_user
from app.db import get_db
from app.models.audit_log import AuditLog
from app.models.primeflow_report_delivery_run import PrimeFlowReportDeliveryRun
from app.models.primeflow_report_recipient import PrimeFlowReportRecipient
from app.models.primeflow_report_schedule import PrimeFlowReportSchedule
from app.models.primeflow_report_snapshot import PrimeFlowReportSnapshot
from app.models.user import User
from app.models.enums import UserRole
from app.services.audit import add_audit_log
from app.services.primeflow_report_access import can_manage_reports
from app.services.primeflow_report import ReportDocument, SLOTS, add_preview_strike_filter, render_docx, render_plain_text, render_png
from app.services.primeflow_report_delivery import (
    configured_recipients,
    deliver_report,
    generate_fresh,
    load_common_view,
    render_ga_recipient_email_html,
)
from app.services.daily_rlz_control_delivery import (
    SCHEDULE_TYPE as RLZ_SCHEDULE_TYPE, REPORT_TYPE as RLZ_REPORT_TYPE,
    DEFAULT_VARIANT_TIMES,
    deliver_daily_rlz_control, generate_fresh as generate_rlz_fresh,
    render_html as render_rlz_html, render_plain as render_rlz_plain,
)
from app.services.primeflow_report_schedule_config import (
    DEFAULT_1H_SCHEDULES,
    DEFAULT_TIMEZONE,
    DEFAULT_WEEKDAYS,
)

router = APIRouter()


async def require_report_manager(user: User = Depends(get_current_user)) -> User:
    if not can_manage_reports(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


async def require_rlz_report_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


def require_report_type_access(user: User, report_type: str) -> None:
    allowed = (
        user.role in {UserRole.ADMIN, UserRole.MANAGER}
        if report_type == RLZ_SCHEDULE_TYPE
        else can_manage_reports(user)
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _recipient(row: PrimeFlowReportRecipient) -> dict:
    data = {key: getattr(row, key) for key in (
        "id", "email", "report_type", "recipient_type", "is_active", "sort_order", "is_default",
        "created_at", "updated_at", "created_by", "updated_by",
    )}
    return {key: value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, uuid.UUID) else value for key, value in data.items()}


def _schedule(row: PrimeFlowReportSchedule) -> dict:
    trigger = CronTrigger(
        day_of_week=",".join(str(day) for day in row.weekdays),
        hour=row.execution_time.hour, minute=row.execution_time.minute, timezone=row.timezone,
    )
    next_runs = []
    previous = None
    now = datetime.now(ZoneInfo(row.timezone))
    for _ in range(3):
        following = trigger.get_next_fire_time(previous, now if previous is None else previous)
        if not following:
            break
        next_runs.append(following.isoformat())
        previous = following
    return {
        "id": str(row.id), "name": row.name, "report_type": row.report_type,
        "report_variant": row.report_variant, "report_slot": row.report_slot,
        "execution_time": row.execution_time.strftime("%H:%M"), "timezone": row.timezone,
        "weekdays": row.weekdays, "is_active": row.is_active, "is_default": row.is_default,
        "backfill_enabled": row.backfill_enabled, "predecessor_schedule_id": str(row.predecessor_schedule_id) if row.predecessor_schedule_id else None,
        "grace_period_minutes": row.grace_period_minutes, "retry_count": row.retry_count,
        "retry_delays_seconds": row.retry_delays_seconds, "sort_order": row.sort_order,
        "version": row.version, "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": str(row.updated_by) if row.updated_by else None,
        "next_runs": next_runs,
    }


class PreviewRequest(BaseModel):
    report_date: date
    report_slot: str
    format: str = "json"
    to: list[EmailStr] = Field(default_factory=list)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    use_default_recipients: bool = True
    show_full_mira_notes: bool = False

    @field_validator("report_slot")
    @classmethod
    def validate_slot(cls, value: str) -> str:
        if value not in SLOTS:
            raise ValueError("Unsupported report slot")
        return value


class SendRequest(PreviewRequest):
    reason: str = Field(min_length=3, max_length=2000)
    force: bool = False
    confirmation_phrase: str | None = None
    source_run_id: uuid.UUID | None = None


class RlzPreviewRequest(BaseModel):
    report_date: date
    report_variant: str = "FINAL"
    to: list[EmailStr] = Field(default_factory=list)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    use_default_recipients: bool = True

    @field_validator("report_variant")
    @classmethod
    def valid_variant(cls, value: str) -> str:
        value = value.upper()
        if value not in DEFAULT_VARIANT_TIMES:
            raise ValueError("Unsupported RLZ report variant")
        return value


class RlzSendRequest(RlzPreviewRequest):
    reason: str = Field(min_length=3, max_length=2000)


class RecipientCreate(BaseModel):
    email: EmailStr
    report_type: str = "ONE_H"
    recipient_type: str = "TO"
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)

    @field_validator("report_type")
    @classmethod
    def report_type_valid(cls, value: str) -> str:
        value = value.upper()
        if value not in {"ONE_H", "RLZ_DAILY_CONTROL"}:
            raise ValueError("Unsupported report type")
        return value

    @field_validator("recipient_type")
    @classmethod
    def type_valid(cls, value: str) -> str:
        value = value.upper()
        if value not in {"TO", "CC", "BCC"}:
            raise ValueError("recipient_type must be TO, CC, or BCC")
        return value


class RecipientUpdate(BaseModel):
    email: EmailStr | None = None
    recipient_type: str | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class SchedulePayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    report_type: str = "ONE_H"
    report_variant: str | None = None
    report_slot: str | None = None
    execution_time: str
    timezone: str = "Europe/Tirane"
    weekdays: list[int]
    is_active: bool = True
    backfill_enabled: bool = True
    predecessor_schedule_id: uuid.UUID | None = None
    grace_period_minutes: int = Field(default=30, ge=1, le=1440)
    retry_count: int = Field(default=3, ge=1, le=10)
    retry_delays_seconds: list[int] = Field(default_factory=lambda: [0, 2, 5])
    sort_order: int = Field(default=0, ge=0, le=10000)

    @field_validator("report_type")
    @classmethod
    def schedule_report_type_valid(cls, value: str) -> str:
        value = value.upper()
        if value not in {"ONE_H", "RLZ_DAILY_CONTROL"}:
            raise ValueError("Unsupported report type")
        return value

    @field_validator("report_variant")
    @classmethod
    def schedule_variant_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.upper()
        if value not in DEFAULT_VARIANT_TIMES:
            raise ValueError("Unsupported RLZ report variant")
        return value

    @field_validator("execution_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        time.fromisoformat(value)
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int]) -> list[int]:
        if not value or any(day not in range(7) for day in value):
            raise ValueError("Select at least one valid weekday")
        return sorted(set(value))

    @field_validator("retry_delays_seconds")
    @classmethod
    def valid_delays(cls, value: list[int]) -> list[int]:
        if not value or len(value) > 10 or any(delay < 0 or delay > 3600 for delay in value):
            raise ValueError("Invalid retry delays")
        return value


async def _recipient_map(request: PreviewRequest) -> dict[str, list[str]]:
    result = await configured_recipients() if request.use_default_recipients else {"to": [], "cc": [], "bcc": []}
    result = {key: list(value) for key, value in result.items()}
    for key in ("to", "cc", "bcc"):
        result[key].extend(str(value) for value in getattr(request, key))
        result[key] = list(dict.fromkeys(result[key]))
    if not any(result.values()):
        raise HTTPException(status_code=422, detail="At least one recipient is required")
    return result


async def _rlz_recipient_map(request: RlzPreviewRequest, *, require_any: bool) -> dict[str, list[str]]:
    result = await configured_recipients(RLZ_SCHEDULE_TYPE) if request.use_default_recipients else {"to": [], "cc": [], "bcc": []}
    result = {key: list(value) for key, value in result.items()}
    for key in ("to", "cc", "bcc"):
        result[key].extend(str(value) for value in getattr(request, key))
        result[key] = list(dict.fromkeys(result[key]))
    if require_any and not any(result.values()):
        raise HTTPException(422, "Configure at least one valid RLZ Daily Control recipient")
    return result


def _file_response(content: bytes, media_type: str, filename: str) -> Response:
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)) -> dict:
    recipients = (await db.execute(select(PrimeFlowReportRecipient).where(PrimeFlowReportRecipient.report_type == "ONE_H").order_by(PrimeFlowReportRecipient.sort_order))).scalars().all()
    schedules = (await db.execute(select(PrimeFlowReportSchedule).where(PrimeFlowReportSchedule.report_type == "ONE_H").order_by(PrimeFlowReportSchedule.sort_order))).scalars().all()
    recent = (await db.execute(select(PrimeFlowReportDeliveryRun).where(PrimeFlowReportDeliveryRun.report_type == "primeflow_1h").order_by(PrimeFlowReportDeliveryRun.created_at.desc()).limit(10))).scalars().all()
    return {"recipients": [_recipient(row) for row in recipients], "schedules": [_schedule(row) for row in schedules], "recent_runs": [_run(row) for row in recent]}


@router.post("/preview")
async def preview(
    payload: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    recipients = await _recipient_map(payload)
    # Load Common View once; the GA email body below reuses it instead of
    # fetching the same data a second time.
    source_data = await load_common_view(payload.report_date)
    document = await generate_fresh(payload.report_date, payload.report_slot, recipients, data=source_data,
        show_full_mira_notes=payload.show_full_mira_notes)
    filename = f"PrimeFlow_1H_{payload.report_date:%d.%m.%Y}_{payload.report_slot.replace(':', '-')}"
    if payload.format == "docx":
        return _file_response(render_docx(document), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename + ".docx")
    if payload.format == "png":
        return _file_response(render_png(document), "image/png", filename + ".png")
    if payload.format == "txt":
        return _file_response(render_plain_text(document).encode(), "text/plain; charset=utf-8", filename + ".txt")
    email_html = await render_ga_recipient_email_html(db, document, payload.report_date, source_data=source_data)
    if payload.format == "html":
        return HTMLResponse(email_html)
    return {
        "document": document.model_dump(mode="json"), "html": add_preview_strike_filter(email_html),
        "plain_text": render_plain_text(document), "task_count": document.task_count,
        "warning": "No tasks found" if document.task_count == 0 else None,
    }


@router.post("/send")
async def manual_send(payload: SendRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_report_manager)):
    recipients = await _recipient_map(payload)
    run = await deliver_report(
        payload.report_date, payload.report_slot, recipient_map=recipients, trigger_type="MANUAL",
        triggered_by_user_id=user.id, manual_reason=payload.reason,
        show_full_mira_notes=payload.show_full_mira_notes,
    )
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_run", entity_id=run.id, action="MANUAL_SEND", after={"status": run.status, "reason": payload.reason})
    await db.commit()
    if run.status not in {"SENT", "ALREADY_SENT"}:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Gmail delivery was not completed",
                "run_id": str(run.id),
                "status": run.status,
                "error_code": run.error_code,
                "error_message": run.error_message,
            },
        )
    return _run(run)


@router.get("/rlz/overview")
async def rlz_overview(db: AsyncSession = Depends(get_db), _: User = Depends(require_rlz_report_manager)) -> dict:
    recipients = (await db.execute(select(PrimeFlowReportRecipient).where(
        PrimeFlowReportRecipient.report_type == RLZ_SCHEDULE_TYPE
    ).order_by(PrimeFlowReportRecipient.sort_order))).scalars().all()
    schedules = (await db.execute(select(PrimeFlowReportSchedule).where(
        PrimeFlowReportSchedule.report_type == RLZ_SCHEDULE_TYPE
    ).order_by(PrimeFlowReportSchedule.sort_order))).scalars().all()
    recent = (await db.execute(select(PrimeFlowReportDeliveryRun).where(
        PrimeFlowReportDeliveryRun.report_type == RLZ_REPORT_TYPE
    ).order_by(PrimeFlowReportDeliveryRun.created_at.desc()).limit(50))).scalars().all()
    return {"recipients": [_recipient(row) for row in recipients], "schedules": [_schedule(row) for row in schedules],
            "recent_runs": [_run(row) for row in recent]}


async def _rlz_configured_time(db: AsyncSession) -> str:
    value = await db.scalar(select(PrimeFlowReportSchedule.execution_time).where(
        PrimeFlowReportSchedule.report_type == RLZ_SCHEDULE_TYPE,
        PrimeFlowReportSchedule.is_active.is_(True),
    ).order_by(PrimeFlowReportSchedule.sort_order).limit(1))
    return value.strftime("%H:%M") if value else "15:50"


async def _rlz_variant_time(db: AsyncSession, variant: str) -> str:
    value = await db.scalar(select(PrimeFlowReportSchedule.execution_time).where(
        PrimeFlowReportSchedule.report_type == RLZ_SCHEDULE_TYPE,
        PrimeFlowReportSchedule.report_variant == variant,
        PrimeFlowReportSchedule.is_active.is_(True),
    ).order_by(PrimeFlowReportSchedule.sort_order).limit(1))
    return value.strftime("%H:%M") if value else DEFAULT_VARIANT_TIMES[variant]


@router.post("/rlz/preview")
async def rlz_preview(payload: RlzPreviewRequest, db: AsyncSession = Depends(get_db),
                      _: User = Depends(require_rlz_report_manager)) -> dict:
    recipients = await _rlz_recipient_map(payload, require_any=False)
    try:
        report = await generate_rlz_fresh(payload.report_date, payload.report_variant)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    report_time = await _rlz_variant_time(db, payload.report_variant)
    return {"report": report, "recipients": recipients, "plain_text": render_rlz_plain(report, report_time),
            "html": render_rlz_html(report, report_time)}


@router.post("/rlz/send")
async def rlz_send(payload: RlzSendRequest, db: AsyncSession = Depends(get_db),
                   user: User = Depends(require_rlz_report_manager)) -> dict:
    recipients = await _rlz_recipient_map(payload, require_any=True)
    report_time = await _rlz_variant_time(db, payload.report_variant)
    run = await deliver_daily_rlz_control(
        payload.report_date, recipient_map=recipients, trigger_type="MANUAL",
        triggered_by_user_id=user.id, manual_reason=payload.reason, report_time=report_time,
        variant=payload.report_variant,
    )
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_run", entity_id=run.id,
                  action="MANUAL_SEND", after={"report_type": RLZ_REPORT_TYPE, "status": run.status, "reason": payload.reason})
    await db.commit()
    if run.status not in {"SENT", "ALREADY_SENT", "SKIPPED_NO_CHANGES"}:
        raise HTTPException(502, detail={"message": "RLZ Daily Control delivery failed", "run_id": str(run.id),
                                         "status": run.status, "error_message": run.error_message})
    return _run(run)


def _run(row: PrimeFlowReportDeliveryRun) -> dict:
    return {key: getattr(row, key) for key in (
        "id", "report_type", "report_date", "report_slot", "trigger_type", "schedule_id", "schedule_version",
        "status", "attempt_count", "data_generated_at", "subject", "recipients", "gmail_message_id",
        "gmail_thread_id", "error_code", "error_message", "triggered_by_user_id", "manual_reason",
        "created_at", "started_at", "finished_at",
    )}


@router.get("/runs")
async def runs(limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)):
    rows = (await db.execute(select(PrimeFlowReportDeliveryRun).where(PrimeFlowReportDeliveryRun.report_type == "primeflow_1h").order_by(PrimeFlowReportDeliveryRun.created_at.desc()).limit(limit))).scalars().all()
    return [_run(row) for row in rows]


@router.get("/runs/{run_id}")
async def run_detail(run_id: uuid.UUID, db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)):
    row = await db.get(PrimeFlowReportDeliveryRun, run_id)
    if not row:
        raise HTTPException(404, "Report run not found")
    snapshot = (await db.execute(select(PrimeFlowReportSnapshot).where(PrimeFlowReportSnapshot.delivery_run_id == run_id))).scalar_one_or_none()
    return {"run": _run(row), "snapshot": snapshot.normalized_report_json if snapshot else None, "html": snapshot.html_body if snapshot else None, "plain_text": snapshot.plain_text_body if snapshot else None}


async def _snapshot(db: AsyncSession, run_id: uuid.UUID) -> tuple[PrimeFlowReportDeliveryRun, PrimeFlowReportSnapshot]:
    run = await db.get(PrimeFlowReportDeliveryRun, run_id)
    snapshot = (await db.execute(select(PrimeFlowReportSnapshot).where(PrimeFlowReportSnapshot.delivery_run_id == run_id))).scalar_one_or_none()
    if not run or not snapshot:
        raise HTTPException(404, "Stored report snapshot not found; historical data will not be regenerated")
    return run, snapshot


@router.get("/runs/{run_id}/download.{format}")
async def download(run_id: uuid.UUID, format: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)):
    run, snapshot = await _snapshot(db, run_id)
    document = ReportDocument.model_validate(snapshot.normalized_report_json)
    base = f"PrimeFlow_1H_{run.report_date:%d.%m.%Y}_{run.report_slot.replace(':', '-')}"
    if format == "docx":
        return _file_response(render_docx(document), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", base + ".docx")
    if format == "png":
        return _file_response(render_png(document), "image/png", base + ".png")
    if format == "txt":
        return _file_response(snapshot.plain_text_body.encode(), "text/plain; charset=utf-8", base + ".txt")
    raise HTTPException(404, "Unsupported format")


@router.get("/recipients")
async def recipients(report_type: str = "ONE_H", db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)):
    rows = (await db.execute(select(PrimeFlowReportRecipient).where(PrimeFlowReportRecipient.report_type == report_type).order_by(PrimeFlowReportRecipient.sort_order, PrimeFlowReportRecipient.email))).scalars().all()
    return [_recipient(row) for row in rows]


@router.post("/recipients", status_code=201)
async def create_recipient(payload: RecipientCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    require_report_type_access(user, payload.report_type)
    row = PrimeFlowReportRecipient(**payload.model_dump(mode="json"), created_by=user.id, updated_by=user.id)
    db.add(row)
    await db.flush()
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_recipient", entity_id=row.id, action="CREATE", after=_recipient(row))
    await db.commit()
    await db.refresh(row)
    return _recipient(row)


@router.post("/recipients/restore-defaults")
async def restore_default_recipients(db: AsyncSession = Depends(get_db), user: User = Depends(require_report_manager)):
    restored = []
    for order, email in enumerate(("130primex.eu@gmail.com", "ga@primexeu.com"), 1):
        row = (await db.execute(select(PrimeFlowReportRecipient).where(
            PrimeFlowReportRecipient.email == email,
            PrimeFlowReportRecipient.recipient_type == "TO",
            PrimeFlowReportRecipient.report_type == "ONE_H",
        ))).scalar_one_or_none()
        if row is None:
            row = PrimeFlowReportRecipient(email=email, report_type="ONE_H", recipient_type="TO", created_by=user.id)
            db.add(row)
            await db.flush()
        row.is_active, row.is_default, row.sort_order, row.updated_by = True, True, order * 10, user.id
        add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_recipient", entity_id=row.id, action="RESTORE_DEFAULTS", after=_recipient(row))
        restored.append(row)
    await db.commit()
    return [_recipient(row) for row in restored]


async def _ensure_active_recipient(db: AsyncSession, excluding: uuid.UUID) -> None:
    target = await db.get(PrimeFlowReportRecipient, excluding)
    count = (await db.execute(select(func.count()).select_from(PrimeFlowReportRecipient).where(
        PrimeFlowReportRecipient.is_active.is_(True), PrimeFlowReportRecipient.id != excluding,
        PrimeFlowReportRecipient.report_type == (target.report_type if target else "ONE_H"),
    ))).scalar_one()
    if count == 0:
        raise HTTPException(422, "Automatic reports require at least one active recipient")


@router.patch("/recipients/{recipient_id}")
async def update_recipient(recipient_id: uuid.UUID, payload: RecipientUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = await db.get(PrimeFlowReportRecipient, recipient_id)
    if not row:
        raise HTTPException(404, "Recipient not found")
    require_report_type_access(user, row.report_type)
    before = _recipient(row)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("recipient_type"):
        changes["recipient_type"] = changes["recipient_type"].upper()
        if changes["recipient_type"] not in {"TO", "CC", "BCC"}:
            raise HTTPException(422, "Invalid recipient type")
    if row.is_active and changes.get("is_active") is False:
        await _ensure_active_recipient(db, row.id)
    for key, value in changes.items():
        setattr(row, key, str(value) if key == "email" else value)
    row.updated_by = user.id
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_recipient", entity_id=row.id, action="UPDATE", before=before, after=_recipient(row))
    await db.commit()
    await db.refresh(row)
    return _recipient(row)


@router.delete("/recipients/{recipient_id}", status_code=204)
async def delete_recipient(recipient_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = await db.get(PrimeFlowReportRecipient, recipient_id)
    if not row:
        raise HTTPException(404, "Recipient not found")
    require_report_type_access(user, row.report_type)
    if row.is_active:
        await _ensure_active_recipient(db, row.id)
    before = _recipient(row)
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_recipient", entity_id=row.id, action="DELETE", before=before)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.get("/schedules")
async def schedules(report_type: str = "ONE_H", db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)):
    rows = (await db.execute(select(PrimeFlowReportSchedule).where(PrimeFlowReportSchedule.report_type == report_type).order_by(PrimeFlowReportSchedule.sort_order))).scalars().all()
    return [_schedule(row) for row in rows]


async def _validate_schedule(db: AsyncSession, payload: SchedulePayload, row_id: uuid.UUID | None = None) -> None:
    if payload.report_type not in {"ONE_H", "RLZ_DAILY_CONTROL"}:
        raise HTTPException(422, "Unsupported report type")
    if payload.report_type == "ONE_H" and payload.report_slot not in SLOTS:
        raise HTTPException(422, "ONE_H schedules require a supported report slot")
    if payload.report_type == "ONE_H" and payload.report_variant is not None:
        raise HTTPException(422, "ONE_H schedules do not use report_variant")
    if payload.report_type == "RLZ_DAILY_CONTROL" and (
        payload.report_slot is not None or payload.backfill_enabled or payload.predecessor_schedule_id is not None
    ):
        raise HTTPException(422, "RLZ Daily Control has no 1H slot, predecessor, or backfill chain")
    if payload.report_type == "RLZ_DAILY_CONTROL" and payload.report_variant not in DEFAULT_VARIANT_TIMES:
        raise HTTPException(422, "RLZ Daily Control requires PRECHECK, FINAL, or CORRECTION")
    duplicate = (await db.execute(select(PrimeFlowReportSchedule).where(
        PrimeFlowReportSchedule.id != row_id if row_id else PrimeFlowReportSchedule.id.isnot(None),
        PrimeFlowReportSchedule.report_type == payload.report_type,
        (
            PrimeFlowReportSchedule.report_variant == payload.report_variant
            if payload.report_type == "RLZ_DAILY_CONTROL"
            else PrimeFlowReportSchedule.report_slot == payload.report_slot
        ),
        PrimeFlowReportSchedule.is_active.is_(True),
    ))).scalars().first()
    if payload.is_active and duplicate:
        raise HTTPException(409, "An active schedule already delivers this report slot")
    if payload.predecessor_schedule_id == row_id:
        raise HTTPException(422, "A schedule cannot reference itself")
    seen = {row_id} if row_id else set()
    current = payload.predecessor_schedule_id
    while current:
        if current in seen:
            raise HTTPException(422, "Circular predecessor dependency")
        seen.add(current)
        predecessor = await db.get(PrimeFlowReportSchedule, current)
        if not predecessor:
            raise HTTPException(422, "Predecessor schedule not found")
        current = predecessor.predecessor_schedule_id


@router.post("/schedules", status_code=201)
async def create_schedule(payload: SchedulePayload, db: AsyncSession = Depends(get_db), user: User = Depends(require_report_manager)):
    await _validate_schedule(db, payload)
    values = payload.model_dump(exclude={"execution_time"})
    row = PrimeFlowReportSchedule(**values, execution_time=time.fromisoformat(payload.execution_time), created_by=user.id, updated_by=user.id)
    db.add(row)
    await db.flush()
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_schedule", entity_id=row.id, action="CREATE", after=_schedule(row))
    await db.commit()
    await db.refresh(row)
    return _schedule(row)


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: uuid.UUID, payload: SchedulePayload, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = await db.get(PrimeFlowReportSchedule, schedule_id)
    if not row:
        raise HTTPException(404, "Schedule not found")
    require_report_type_access(user, row.report_type)
    if payload.report_type != row.report_type:
        raise HTTPException(422, "Report type cannot be changed")
    await _validate_schedule(db, payload, row.id)
    before = _schedule(row)
    for key, value in payload.model_dump(exclude={"execution_time"}).items():
        setattr(row, key, value)
    row.execution_time, row.updated_by, row.version = time.fromisoformat(payload.execution_time), user.id, row.version + 1
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_schedule", entity_id=row.id, action="UPDATE", before=before, after=_schedule(row))
    await db.commit()
    await db.refresh(row)
    return _schedule(row)


@router.post("/schedules/restore-defaults")
async def restore_default_schedules(db: AsyncSession = Depends(get_db), user: User = Depends(require_report_manager)):
    rows = (await db.execute(select(PrimeFlowReportSchedule).where(PrimeFlowReportSchedule.report_type == "ONE_H"))).scalars().all()
    rows_by_name = {row.name: row for row in rows}
    restored: list[PrimeFlowReportSchedule] = []
    predecessor_id: uuid.UUID | None = None

    for default in DEFAULT_1H_SCHEDULES:
        row = rows_by_name.get(default.name)
        before = _schedule(row) if row is not None else None
        if row is None:
            row = PrimeFlowReportSchedule(
                name=default.name,
                report_type="ONE_H",
                report_slot=default.report_slot,
                execution_time=default.execution_time,
                created_by=user.id,
            )
            db.add(row)
            await db.flush()
            rows_by_name[row.name] = row

        row.report_slot = default.report_slot
        row.execution_time = default.execution_time
        row.timezone = DEFAULT_TIMEZONE
        row.weekdays = list(DEFAULT_WEEKDAYS)
        row.is_active = True
        row.is_default = True
        row.backfill_enabled = True
        row.predecessor_schedule_id = predecessor_id
        row.grace_period_minutes = 30
        row.retry_count = 3
        row.retry_delays_seconds = [0, 2, 5]
        row.sort_order = default.sort_order
        row.updated_by = user.id
        row.version += 1
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="primeflow_report_schedule",
            entity_id=row.id,
            action="RESTORE_DEFAULTS",
            before=before,
            after=_schedule(row),
        )
        restored.append(row)
        predecessor_id = row.id

    await db.commit()
    return [_schedule(row) for row in restored]


@router.post("/schedules/{schedule_id}/{action}")
async def schedule_action(schedule_id: uuid.UUID, action: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_report_manager)):
    if action not in {"enable", "disable", "duplicate"}:
        raise HTTPException(404, "Unknown schedule action")
    row = await db.get(PrimeFlowReportSchedule, schedule_id)
    if not row:
        raise HTTPException(404, "Schedule not found")
    if action == "duplicate":
        copy = PrimeFlowReportSchedule(
            name=f"{row.name} copy {datetime.now():%H%M%S}", report_type=row.report_type, report_slot=row.report_slot,
            execution_time=row.execution_time, timezone=row.timezone, weekdays=row.weekdays,
            is_active=False, backfill_enabled=row.backfill_enabled,
            predecessor_schedule_id=row.predecessor_schedule_id, grace_period_minutes=row.grace_period_minutes,
            retry_count=row.retry_count, retry_delays_seconds=row.retry_delays_seconds,
            sort_order=row.sort_order + 1, created_by=user.id, updated_by=user.id,
        )
        db.add(copy)
        await db.flush()
        add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_schedule", entity_id=copy.id, action="DUPLICATE", after=_schedule(copy))
        await db.commit()
        return _schedule(copy)
    if action == "enable":
        candidate = SchedulePayload(
            name=row.name, report_type=row.report_type, report_slot=row.report_slot, execution_time=row.execution_time.strftime("%H:%M"),
            timezone=row.timezone, weekdays=row.weekdays, is_active=True,
            backfill_enabled=row.backfill_enabled, predecessor_schedule_id=row.predecessor_schedule_id,
            grace_period_minutes=row.grace_period_minutes, retry_count=row.retry_count,
            retry_delays_seconds=row.retry_delays_seconds, sort_order=row.sort_order,
        )
        await _validate_schedule(db, candidate, row.id)
    before = _schedule(row)
    row.is_active, row.updated_by, row.version = action == "enable", user.id, row.version + 1
    add_audit_log(db=db, actor_user_id=user.id, entity_type="primeflow_report_schedule", entity_id=row.id, action=action.upper(), before=before, after=_schedule(row))
    await db.commit()
    return _schedule(row)


@router.get("/audit")
async def audit(limit: int = Query(200, ge=1, le=500), db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)):
    rows = (await db.execute(select(AuditLog).where(AuditLog.entity_type.in_([
        "primeflow_report_recipient", "primeflow_report_schedule", "primeflow_report_run",
    ])).order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": row.id, "actor_user_id": row.actor_user_id, "entity_type": row.entity_type, "entity_id": row.entity_id, "action": row.action, "before": row.before, "after": row.after, "created_at": row.created_at} for row in rows]
