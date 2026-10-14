from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.primeflow_1h_reports import require_report_manager
from app.db import get_db
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import report_timezone
from app.services.reporting_points_settings import DeliverySettingsPayload, read_settings, save_settings
from app.services.m1_reporting_points import (
    MANUAL_POINTS, backfill_saved_note_authors, excluded_note_ids, get_settings, locked_report, refresh_report,
    reorder_saved_report_tasks, render_html,
    render_plain_text, report_payload, send_report, report_attachments,
)

router = APIRouter()


@router.get("/settings")
async def delivery_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)) -> dict:
    return await read_settings(db, "M1")


@router.put("/settings")
async def update_delivery_settings(payload: DeliverySettingsPayload, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(require_report_manager)) -> dict:
    try:
        return await save_settings(db, "M1", payload, user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class ManualAnswersPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_answers: dict[str, str] = Field(default_factory=dict)

    @field_validator("manual_answers")
    @classmethod
    def validate_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) - set(MANUAL_POINTS):
            raise ValueError("Pike manuale e panjohur.")
        if any(len(answer) > 10000 for answer in value.values()):
            raise ValueError("Pergjigjja nuk mund te kete mbi 10000 karaktere.")
        return value


async def _by_id(db: AsyncSession, report_id: uuid.UUID) -> M1ReportingPointsReport:
    row = await db.get(M1ReportingPointsReport, report_id)
    if row is None:
        raise HTTPException(404, "Raporti nuk u gjet.")
    return await _refresh_saved_metadata(db, row)


async def _refresh_saved_metadata(db: AsyncSession, row: M1ReportingPointsReport) -> M1ReportingPointsReport:
    data = row.data or {}
    if data.get("note_author_version") == 1 and (row.sent_at or data.get("task_order_version") == 1):
        return row
    row = await locked_report(db, row.report_date)
    await db.refresh(row)
    notes_changed = await backfill_saved_note_authors(db, row)
    tasks_changed = await reorder_saved_report_tasks(db, row)
    if notes_changed or tasks_changed:
        await db.commit()
    return row


async def _current_payload(db: AsyncSession, row: M1ReportingPointsReport) -> dict:
    return report_payload(row, excluded_note_ids=await excluded_note_ids(db, row))


@router.get("/recipients")
async def recipients(db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)) -> dict:
    settings = await get_settings(db)
    return {"recipients": normalize_recipients(settings.recipients), "delivery": "MANUAL_AVAILABLE"}


@router.get("/history")
async def history(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db),
                  _: User = Depends(get_current_user)) -> list[dict]:
    rows = (await db.execute(select(M1ReportingPointsReport)
                            .order_by(M1ReportingPointsReport.report_date.desc()).limit(limit))).scalars().all()
    return [{key: report_payload(row)[key] for key in ("id", "report_date", "status", "generated_at", "sent_at")}
            for row in rows]


@router.get("")
async def get_report(report_date: date, db: AsyncSession = Depends(get_db),
                     _: User = Depends(get_current_user)) -> dict:
    row = (await db.execute(select(M1ReportingPointsReport).where(
        M1ReportingPointsReport.report_date == report_date))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Raporti nuk eshte gjeneruar per kete date.")
    row = await _refresh_saved_metadata(db, row)
    return await _current_payload(db, row)


@router.post("/generate")
async def generate(report_date: date, db: AsyncSession = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    if report_date != datetime.now(report_timezone()).date():
        return await get_report(report_date, db, user)
    row = await locked_report(db, report_date)
    await refresh_report(db, row)
    row.status, row.last_error, row.updated_by = "DRAFT", None, user.id
    add_audit_log(db=db, actor_user_id=user.id, entity_type="m1_reporting_points", entity_id=row.id,
                  action="GENERATE", after={"report_date": report_date.isoformat()})
    await db.commit()
    return await _current_payload(db, row)


@router.put("/{report_id}/answers")
async def save_answers(report_id: uuid.UUID, payload: ManualAnswersPayload,
                       db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    existing = await _by_id(db, report_id)
    row = await locked_report(db, existing.report_date)
    await db.refresh(row)
    before = dict(row.manual_answers or {})
    row.manual_answers = {**before, **payload.manual_answers}
    row.status, row.last_error, row.updated_by = "DRAFT", None, user.id
    add_audit_log(db=db, actor_user_id=user.id, entity_type="m1_reporting_points", entity_id=row.id,
                  action="SAVE_ANSWERS", before=before, after=row.manual_answers)
    await db.commit()
    return await _current_payload(db, row)


@router.get("/{report_id}/preview")
async def preview(report_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                  _: User = Depends(get_current_user)) -> dict:
    report = await _current_payload(db, await _by_id(db, report_id))
    return {"html": render_html(report), "plain_text": render_plain_text(report)}


@router.post("/{report_id}/send")
async def send(report_id: uuid.UUID, db: AsyncSession = Depends(get_db),
               user: User = Depends(require_report_manager)) -> dict:
    existing = await _by_id(db, report_id)
    row = await locked_report(db, existing.report_date)
    await db.refresh(row)
    if not row.generated_at:
        raise HTTPException(409, "Gjenero raportin perpara dergimit.")
    try:
        settings = await get_settings(db)
        recipients = normalize_recipients(settings.recipients)
        if row.report_date == datetime.now(report_timezone()).date():
            await refresh_report(db, row)
        add_audit_log(db=db, actor_user_id=user.id, entity_type="m1_reporting_points", entity_id=row.id,
                      action="MANUAL_SEND", after={"report_date": row.report_date.isoformat(), "recipients": recipients})
        await send_report(db, row, recipients)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Dergimi deshtoi. Kontrollo konfigurimin e email-it ose provo perseri.") from exc
    return await _current_payload(db, row)


@router.get("/{report_id}/download/{format}")
async def download(report_id: uuid.UUID, format: Literal["docx", "png", "xlsx", "txt", "html"],
                   db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    report = await _current_payload(db, await _by_id(db, report_id))
    filename = f"pikat_m1_{report['report_date']}.{format}"
    if format in {"docx", "png", "xlsx"}:
        attachments = await asyncio.to_thread(report_attachments, report)
        _, content, mime = next(item for item in attachments if item[0].endswith(f".{format}"))
    else:
        content = (render_html(report) if format == "html" else render_plain_text(report)).encode("utf-8")
        mime = "text/html" if format == "html" else "text/plain"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
