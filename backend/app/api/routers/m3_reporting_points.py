from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.primeflow_1h_reports import require_report_manager
from app.db import get_db
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import report_timezone
from app.services.reporting_points_settings import DeliverySettingsPayload, read_settings, save_settings
from app.services.m3_unheld_meetings import is_meeting_comment_key
from app.services.m3_reporting_points import (
    MANUAL_POINTS, current_report_payload, get_settings, locked_report, refresh_report, render_html,
    render_plain_text, report_payload, send_report,
)

router = APIRouter()

@router.get("/settings")
async def delivery_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)) -> dict:
    return await read_settings(db, "M3")


@router.put("/settings")
async def update_delivery_settings(payload: DeliverySettingsPayload, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(require_report_manager)) -> dict:
    try:
        return await save_settings(db, "M3", payload, user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class ManualAnswersPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_answers: dict[str, str] = Field(default_factory=dict)

    @field_validator("manual_answers")
    @classmethod
    def validate_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if any(key not in MANUAL_POINTS and not is_meeting_comment_key(key)
               and not is_task_comment_key(key) for key in value):
            raise ValueError("Pike manuale e panjohur.")
        if any(len(answer) > 10000 for answer in value.values()):
            raise ValueError("Pergjigjja nuk mund te kete mbi 10000 karaktere.")
        if any(key.startswith("delivery_choice:") and answer not in {"", "PO", "JO"}
               for key, answer in value.items()):
            raise ValueError("Zgjedhja duhet te jete PO ose JO.")
        return value


def is_task_comment_key(key: str) -> bool:
    prefix, _, task_id = key.partition(":")
    if prefix not in {"untouched_comment", "delivery", "delivery_choice"}:
        return False
    try:
        return str(uuid.UUID(task_id)) == task_id
    except ValueError:
        return False


async def _by_id(db: AsyncSession, report_id: uuid.UUID) -> M3ReportingPointsReport:
    row = await db.get(M3ReportingPointsReport, report_id)
    if row is None:
        raise HTTPException(404, "Raporti nuk u gjet.")
    return row


@router.get("/recipients")
async def recipients(db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)) -> dict:
    try:
        settings = await get_settings(db)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"recipients": normalize_recipients(settings.recipients), "delivery": "MANUAL_AVAILABLE"}


@router.get("/history")
async def history(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db),
                  _: User = Depends(get_current_user)) -> list[dict]:
    rows = (await db.execute(select(M3ReportingPointsReport)
                            .order_by(M3ReportingPointsReport.report_date.desc()).limit(limit))).scalars().all()
    return [{key: report_payload(row)[key] for key in (
        "id", "report_date", "status", "generated_at", "realization_captured_at", "sent_at",
    )} for row in rows]


@router.get("")
async def get_report(report_date: date, db: AsyncSession = Depends(get_db),
                     _: User = Depends(get_current_user)) -> dict:
    row = (await db.execute(select(M3ReportingPointsReport).where(
        M3ReportingPointsReport.report_date == report_date,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Raporti nuk eshte gjeneruar per kete date.")
    return await current_report_payload(db, row)


@router.post("/generate")
async def generate(report_date: date, db: AsyncSession = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    today = datetime.now(report_timezone()).date()
    if report_date != today:
        return await get_report(report_date, db, user)
    row = await locked_report(db, report_date)
    await refresh_report(db, row)
    row.status, row.last_error = "DRAFT", None
    row.updated_by = user.id
    add_audit_log(db=db, actor_user_id=user.id, entity_type="m3_reporting_points", entity_id=row.id,
                  action="GENERATE", after={"report_date": report_date.isoformat()})
    await db.commit()
    return await current_report_payload(db, row)


@router.put("/{report_id}/answers")
async def save_answers(report_id: uuid.UUID, payload: ManualAnswersPayload,
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    if any(not is_meeting_comment_key(key) for key in payload.manual_answers):
        await require_report_manager(user)
    existing = await _by_id(db, report_id)
    row = await locked_report(db, existing.report_date)
    await db.refresh(row)
    before = dict(row.manual_answers or {})
    valid_comments = {f"untouched_comment:{item['task_id']}"
                      for item in (row.data or {}).get("untouched", []) if item.get("task_id")}
    valid_comments.update(f"{prefix}:{item['task_id']}"
                          for item in (row.data or {}).get("delivery", []) if item.get("task_id")
                          for prefix in ("delivery", "delivery_choice"))
    if any(is_task_comment_key(key) and key not in valid_comments and key not in before
           for key in payload.manual_answers):
        raise HTTPException(422, "Detyra nuk gjendet ne kete raport.")
    row.manual_answers = {**before, **payload.manual_answers}
    row.status, row.last_error = "DRAFT", None
    row.updated_by = user.id
    add_audit_log(db=db, actor_user_id=user.id, entity_type="m3_reporting_points", entity_id=row.id,
                  action="SAVE_ANSWERS", before=before, after=row.manual_answers)
    await db.commit()
    return await current_report_payload(db, row)


@router.get("/{report_id}/preview")
async def preview(report_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                  _: User = Depends(get_current_user)) -> dict:
    report = await current_report_payload(db, await _by_id(db, report_id))
    return {"html": render_html(report), "plain_text": render_plain_text(report)}


@router.post("/{report_id}/send")
async def send(report_id: uuid.UUID, db: AsyncSession = Depends(get_db),
               user: User = Depends(require_report_manager)) -> dict:
    existing = await _by_id(db, report_id)
    row = await locked_report(db, existing.report_date)
    await db.refresh(row)
    if not row.generated_at:
        raise HTTPException(409, "Gjenero raportin perpara dergimit.")
    if not row.realization_captured_at:
        raise HTTPException(409, "Raporti dergohet pasi te jete ruajtur realizimi i ores 16:15.")
    try:
        settings = await get_settings(db)
        recipients = normalize_recipients(settings.recipients)
        if not recipients["to"]:
            raise ValueError("Shto marresit To ne konfigurimin e raportit M3.")
        if row.report_date == datetime.now(report_timezone()).date():
            await refresh_report(db, row)
        add_audit_log(db=db, actor_user_id=user.id, entity_type="m3_reporting_points", entity_id=row.id,
                      action="MANUAL_SEND", after={"report_date": row.report_date.isoformat(), "recipients": recipients})
        await send_report(db, row, recipients)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Dergimi deshtoi. Kontrollo konfigurimin e email-it ose provo perseri.") from exc
    return await current_report_payload(db, row)
