"""PrimeFlow data used by the ASIST GA – DET GA reports."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.ga_assistant import (
    ItemDoneIn,
    _relation,
    _task_uuid,
    ensure_assistant_user,
    item_done,
)
from app.api.routers.m1_reporting_points import save_locked_manual_answers
from app.db import get_db
from app.models.ga_device_reaction import GaDeviceReaction
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services import ga_assistant as svc
from app.services.after_break_report import _task_covers_day
from app.services.ga_identity import is_ga_user, resolve_ga_user
from app.services.m1_reporting_points import locked_report
from app.services.primeflow_report import report_timezone

router = APIRouter()
ReportDB = Annotated[AsyncSession, Depends(get_db)]
ReportUser = Annotated[User, Depends(get_current_user)]

REPORT_LINKS = (
    ("m1_start_of_day", "M1 Start of day", "/morning-report"),
    ("pas_pz", "M2 Pas pauzës", "/after-break-report"),
    ("m3", "M3 End of Day", "/meetings-report"),
    ("m1_pikat", "M1 Pikat", "/m1-reporting-points"),
    ("m2_pikat", "M2 Pikat", "/m2-reporting-points"),
    ("m3_pikat", "M3 Pikat", "/m3-reporting-points"),
    ("1h_s", "1H SHTYPI Sot", "/today-print-report"),
    ("1h_sh_n", "1H SHTYPI Nesër", "/tomorrow-print-report"),
)


@router.get("/report-links")
async def report_links(date: date, user: ReportUser) -> dict:
    ensure_assistant_user(user)
    return {"date": date, "links": [
        {"key": key, "title": title, "url": svc.frontend_url(f"{path}?date={date}"), "available": True}
        for key, title, path in REPORT_LINKS
    ]}


def reorg_data(day: date, value: str | None) -> dict:
    raw = (value or "").strip()
    first_line, _, rest = raw.partition("\n")
    if first_line == "Pa përgjigje":
        return {"date": day, "answer": None, "comment": rest}
    if first_line.casefold() in {"po", "jo"}:
        return {"date": day, "answer": first_line.casefold(), "comment": rest.strip()}
    match = re.fullmatch(r"(po|jo)\s*[:;,–—-]\s*(.*)", raw, re.IGNORECASE | re.DOTALL)
    return {
        "date": day,
        "answer": match.group(1).lower() if match else None,
        "comment": (match.group(2) or "").strip() if match else raw,
    }


@router.get("/m1/reorg")
async def m1_reorg_read(date: date, db: ReportDB, user: ReportUser) -> dict:
    ensure_assistant_user(user)
    answers = (await db.execute(
        select(M1ReportingPointsReport.manual_answers).where(M1ReportingPointsReport.report_date == date)
    )).scalar_one_or_none()
    return reorg_data(date, (answers or {}).get("reorganization"))


class ReorgInput(BaseModel):
    date: date
    answer: Literal["po", "jo"] | None
    comment: str = Field(default="", max_length=9987)


@router.post("/m1/reorg")
async def m1_reorg_write(payload: ReorgInput, db: ReportDB, user: ReportUser) -> dict:
    ensure_assistant_user(user)
    day = payload.date
    today = datetime.now(report_timezone()).date()
    if day > today:
        raise HTTPException(422, "M1 Pikat mund të plotësohet deri në datën e sotme.")
    row = await locked_report(db, day)
    if row.generated_at is None and day < today:
        raise HTTPException(404, "M1 Pikat nuk është gjeneruar për këtë datë.")
    comment = payload.comment.strip()
    answer_text = payload.answer.capitalize() if payload.answer else ("Pa përgjigje" if comment else "")
    value = "\n".join(part for part in (answer_text, comment) if part)
    await save_locked_manual_answers(db, row, {"reorganization": value}, user)
    return {"date": day, "answer": payload.answer, "comment": comment}


def devices_filter():
    return and_(
        Task.is_active.is_(True),
        Task.work_staff_filter(),
        Task.title.op("~*")(r"\mGA([[:space:]]*:[[:space:]]*|[[:space:]]+)DEVICES\M"),
    )


@router.get("/devices")
async def devices(date: date, db: ReportDB, user: ReportUser) -> dict:
    ensure_assistant_user(user)
    tz = svc.ga_tz()
    start = datetime.combine(date, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    rows = (await db.execute(
        select(Task, GaDeviceReaction.reacted_at)
        .outerjoin(GaDeviceReaction, GaDeviceReaction.task_id == Task.id)
        .where(devices_filter(), or_(Task.start_date.is_(None), Task.start_date < end),
               or_(Task.due_date.is_(None), Task.due_date >= start))
        .order_by(Task.due_date, Task.title, Task.id)
    )).all()
    rows = [(task, reacted_at) for task, reacted_at in rows if _task_covers_day(task, date)]
    people: dict = {}
    if rows:
        assignments = (await db.execute(
            select(Task.id, User.full_name).select_from(Task)
            .outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id)
            .join(User, or_(User.id == Task.assigned_to, User.id == TaskAssignee.user_id))
            .where(Task.id.in_([task.id for task, _ in rows]), User.work_staff_filter())
            .order_by(User.full_name)
        )).all()
        for task_id, name in assignments:
            people.setdefault(task_id, set()).add(name)

    items = []
    for task, reacted_at in rows:
        marks = svc.markers_of(task)
        slot = svc.parse_hhmm(task.one_h_report_slot) or svc.due_time_of(task, tz)
        moment = datetime.combine(date, slot, tzinfo=tz) if slot else None
        names = sorted(people.get(task.id, ()))
        items.append({
            "id": f"{svc.PREFIX_TASK}{task.id}",
            "title": task.title,
            "category": "fizikisht" if "F" in marks else ("personalisht" if task.is_personal else "pa reagim GA"),
            "person": " / ".join(names) or None,
            "time": moment,
            "link": svc.frontend_url(f"/tasks/{task.id}"),
            "status": ("reacted" if reacted_at else "pending") if svc.task_is_open(task) else "done",
            "task_status": svc.task_status(task),
            "reacted_at": reacted_at,
        })
    return {"date": date, "items": items}


class DeviceMark(BaseModel):
    id: str = Field(pattern=r"^pf_task:[0-9a-fA-F-]{36}$")
    status: Literal["reacted", "done"]
    comment: str | None = Field(default=None, max_length=4000)


@router.post("/devices/mark")
async def device_mark(payload: DeviceMark, db: ReportDB, user: ReportUser) -> dict:
    ensure_assistant_user(user)
    if not is_ga_user(user):
        raise HTTPException(403, "Vetëm GA mund t'i shënojë detyrat GA Devices.")
    task_id = _task_uuid(payload.id.removeprefix(svc.PREFIX_TASK))
    task = (await db.execute(select(Task).where(Task.id == task_id, devices_filter()))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "Detyra GA Devices nuk u gjet.")
    if not svc.task_is_open(task):
        return {"id": payload.id, "status": "done"}
    if payload.status == "done":
        if await _relation(db, task, user) != "owner":
            raise HTTPException(409, "GA duhet të jetë përgjegjës ose konfirmues për ta mbyllur detyrën.")
        result = await item_done(ItemDoneIn(item_id=payload.id, comment=payload.comment), db, user)
        return {"id": payload.id, "status": "done", "task_result": result}
    await db.execute(insert(GaDeviceReaction).values(task_id=task_id, reacted_by=user.id).on_conflict_do_nothing())
    await db.commit()
    return {"id": payload.id, "status": "reacted"}


@router.get("/px-tasks")
async def px_tasks(date: date, until: time, db: ReportDB, user: ReportUser) -> dict:
    ensure_assistant_user(user)
    if until.tzinfo is not None:
        raise HTTPException(422, "Përdor orën lokale të raportit, p.sh. 11:00.")
    tz = svc.ga_tz()
    cutoff = datetime.combine(date, until, tzinfo=tz)
    start = datetime.combine(date, time.min, tzinfo=tz)
    owner = user if is_ga_user(user) else await resolve_ga_user(db, work_staff_only=True)
    if owner is None:
        raise HTTPException(404, "Llogaria e GA-së nuk u gjet.")
    assigned_ids = select(TaskAssignee.task_id).where(TaskAssignee.user_id == owner.id)
    rows = (await db.execute(
        select(Task).where(
            Task.is_active.is_(True), Task.work_staff_filter(), Task.due_date >= start, Task.due_date <= cutoff,
            or_(Task.assigned_to == owner.id, Task.id.in_(assigned_ids),
                and_(Task.status == "WAITING_CONFIRMATION", Task.confirmation_assignee_id == owner.id)),
        )
        .order_by(Task.due_date, Task.id)
    )).scalars().all()
    return {
        "date": date, "until": cutoff,
        "items": [{
            "id": f"{svc.PREFIX_TASK}{task.id}", "title": task.title, "scope": "PX",
            "due_at": task.due_date.astimezone(tz), "status": svc.task_status(task),
            "link": svc.frontend_url(f"/tasks/{task.id}"),
        } for task in rows if svc.due_time_of(task, tz) is not None or cutoff.time() >= time(23, 59)],
    }
