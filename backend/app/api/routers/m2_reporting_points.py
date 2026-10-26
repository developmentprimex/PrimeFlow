from __future__ import annotations

import uuid
import asyncio
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.primeflow_1h_reports import require_report_manager
from app.db import get_db
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import report_timezone
from app.services.reporting_points_settings import DeliverySettingsPayload, read_settings, save_settings
from app.services.m2_reporting_points import (
    MANUAL_POINTS, get_settings, locked_report, refresh_report, render_html,
    render_plain_text, report_payload, current_report_payload, send_report, report_attachments,
)

router = APIRouter()

@router.get("/settings")
async def delivery_settings(db: AsyncSession = Depends(get_db), _: User = Depends(require_report_manager)) -> dict:
    return await read_settings(db, "M2")


@router.put("/settings")
async def update_delivery_settings(payload: DeliverySettingsPayload, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(require_report_manager)) -> dict:
    try:
        return await save_settings(db, "M2", payload, user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class ManualAnswersPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_answers: dict[str, str] = Field(default_factory=dict)

    @field_validator("manual_answers")
    @classmethod
    def validate_answers(cls, value: dict[str, str]) -> dict[str, str]:
        # Ignore the removed point from tabs or drafts loaded before the update.
        value = {key: answer for key, answer in value.items() if key != "ga_reply"}
        for key in value:
            if key in MANUAL_POINTS:
                continue
            prefix, _, task_id = key.partition(":")
            if prefix not in {"delivery", "delivery_choice", "postponed_comment", "unfinished_comment", "progress_reason", "progress_comment", "postponed_reason", "unfinished_reason"}:
                raise ValueError("Pike manuale e panjohur.")
            try:
                if str(uuid.UUID(task_id)) != task_id:
                    raise ValueError()
            except ValueError as exc:
                raise ValueError("Detyre e pavlefshme per pergjigjen manuale.") from exc
            if prefix == "delivery_choice" and value[key] not in {"", "PO", "JO"}:
                raise ValueError("Zgjedhja duhet te jete PO ose JO.")
            if prefix.endswith("_reason") and value[key] and value[key] not in REASON_LABELS:
                raise ValueError("Arsye e panjohur.")
        if any(len(answer) > 10000 for answer in value.values()):
            raise ValueError("Pergjigjja nuk mund te kete mbi 10000 karaktere.")
        return value


async def _by_id(db: AsyncSession, report_id: uuid.UUID) -> M2ReportingPointsReport:
    row = await db.get(M2ReportingPointsReport, report_id)
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
    rows = (await db.execute(select(M2ReportingPointsReport)
                            .order_by(M2ReportingPointsReport.report_date.desc()).limit(limit))).scalars().all()
    return [{key: report_payload(row)[key] for key in (
        "id", "report_date", "status", "generated_at", "sent_at",
    )} for row in rows]


@router.get("")
async def get_report(report_date: date, db: AsyncSession = Depends(get_db),
                     _: User = Depends(get_current_user)) -> dict:
    row = (await db.execute(select(M2ReportingPointsReport).where(
        M2ReportingPointsReport.report_date == report_date,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Raporti nuk eshte gjeneruar per kete date.")
    if (report_date == datetime.now(report_timezone()).date()
            and any(not item.get("task_id") for item in (row.data or {}).get("unfinished_priority", []))):
        # Older snapshots omitted task IDs, which are needed to edit comments.
        await refresh_report(db, row)
        await db.commit()
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
    add_audit_log(db=db, actor_user_id=user.id, entity_type="m2_reporting_points", entity_id=row.id,
                  action="GENERATE", after={"report_date": report_date.isoformat()})
    await db.commit()
    return await current_report_payload(db, row)


@router.put("/{report_id}/answers")
async def save_answers(report_id: uuid.UUID, payload: ManualAnswersPayload,
                       db: AsyncSession = Depends(get_db), user: User = Depends(require_report_manager)) -> dict:
    existing = await _by_id(db, report_id)
    row = await locked_report(db, existing.report_date)
    await db.refresh(row)
    before = dict(row.manual_answers or {})
    valid_keys = {f"{prefix}:{item['task_id']}" for item in (row.data or {}).get("delivery", [])
                  for prefix in ("delivery", "delivery_choice")}
    valid_keys.update(f"postponed_comment:{item['task_id']}" for section in ("postponed", "postponed_am")
                      for item in (row.data or {}).get(section, []))
    valid_keys.update(f"unfinished_comment:{item['task_id']}"
                      for item in (row.data or {}).get("unfinished_priority", []) if item.get("task_id"))
    valid_keys.update(f"{prefix}:{item['task_id']}" for item in (row.data or {}).get("ga_progress", [])
                      for prefix in ("progress_reason", "progress_comment"))
    if any(key not in MANUAL_POINTS and key not in valid_keys and key not in before for key in payload.manual_answers):
        raise HTTPException(422, "Detyra nuk gjendet ne kete raport.")
    row.manual_answers = {**before, **payload.manual_answers}
    row.status, row.last_error = "DRAFT", None
    row.updated_by = user.id
    add_audit_log(db=db, actor_user_id=user.id, entity_type="m2_reporting_points", entity_id=row.id,
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
    try:
        settings = await get_settings(db)
        recipients = normalize_recipients(settings.recipients)
        if not recipients["to"]:
            raise ValueError("Shto marresit To ne konfigurimin e raportit M2.")
        if row.report_date == datetime.now(report_timezone()).date():
            await refresh_report(db, row)
        add_audit_log(db=db, actor_user_id=user.id, entity_type="m2_reporting_points", entity_id=row.id,
                      action="MANUAL_SEND", after={"report_date": row.report_date.isoformat(), "recipients": recipients})
        await send_report(db, row, recipients)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "Dergimi deshtoi. Kontrollo konfigurimin e email-it ose provo perseri.") from exc
    return await current_report_payload(db, row)


@router.get("/{report_id}/download/{format}")
async def download(report_id: uuid.UUID, format: Literal["docx", "png", "txt", "html"],
                   db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    report = await current_report_payload(db, await _by_id(db, report_id))
    filename = f"pikat_m2_{report['report_date']}.{format}"
    if format in {"docx", "png"}:
        attachments = await asyncio.to_thread(report_attachments, report)
        _, content, mime = next(item for item in attachments if item[0].endswith(f".{format}"))
    else:
        content = (render_html(report) if format == "html" else render_plain_text(report)).encode("utf-8")
        mime = "text/html" if format == "html" else "text/plain"
    return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
