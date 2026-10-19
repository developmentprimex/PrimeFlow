from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.discord_assistant import DiscordAction, DiscordLink, DiscordLinkCode, DiscordReminder
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.task_user_comment import TaskUserComment
from app.models.user import User
from app.services import discord_task_tools as tools

router = APIRouter()


def configured() -> bool:
    return bool(settings.DISCORD_ASSISTANT_ENABLED and settings.DISCORD_BRIDGE_SECRET
                and len(settings.DISCORD_BRIDGE_SECRET) >= 32 and settings.DISCORD_GUILD_ID)


def require_bot(x_primeflow_discord_secret: Annotated[str | None, Header()] = None):
    if not configured():
        raise HTTPException(503, "Asistenti Discord nuk është aktivizuar.")
    if not x_primeflow_discord_secret or not secrets.compare_digest(x_primeflow_discord_secret, settings.DISCORD_BRIDGE_SECRET):
        raise HTTPException(401, "Invalid bot credentials")


class Actor(BaseModel):
    discord_user_id: str = Field(pattern=r"^\d{1,32}$")
    guild_id: str = Field(pattern=r"^\d{1,32}$")
    channel_id: str = Field(pattern=r"^\d{1,32}$")


class LinkRequest(BaseModel):
    code: str = Field(min_length=16, max_length=100)
    discord_user_id: str = Field(pattern=r"^\d{1,32}$")
    guild_id: str = Field(pattern=r"^\d{1,32}$")


class Selection(Actor):
    task_id: uuid.UUID


class Command(Actor):
    request_id: str = Field(pattern=r"^\d{1,32}$")
    task_id: uuid.UUID | None = None
    instruction: str = Field(min_length=1, max_length=4000)
    expected_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    direct_actions: list[tools.ToolAction] | None = Field(default=None, min_length=1, max_length=20)


async def identity(db: AsyncSession, actor: Actor, *, lock: bool = False):
    if actor.guild_id != settings.DISCORD_GUILD_ID:
        raise HTTPException(403, "Serveri Discord nuk përputhet.")
    stmt = select(DiscordLink).where(DiscordLink.discord_user_id == actor.discord_user_id,
        DiscordLink.guild_id == actor.guild_id, DiscordLink.channel_id == actor.channel_id, DiscordLink.enabled.is_(True))
    link = (await db.execute(stmt)).scalar_one_or_none()
    if link and lock:
        # Serialize commands without locking the FK row that task deletion
        # may SET NULL through a separate normal-API transaction.
        key = int.from_bytes(hashlib.sha256(link.id.bytes).digest()[:8], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        link = (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "Përdor /lidh në kanalin tënd privat.")
    user = await db.get(User, link.user_id, populate_existing=True)
    if not user or not user.is_active:
        raise HTTPException(403, "Llogaria PrimeFlow nuk është aktive.")
    return link, user


async def owned_task(db: AsyncSession, user: User, task_id: uuid.UUID):
    task = await db.get(Task, task_id, populate_existing=True)
    assigned = task and (task.assigned_to == user.id or (await db.execute(select(TaskAssignee.task_id).where(
        TaskAssignee.task_id == task_id, TaskAssignee.user_id == user.id))).scalar_one_or_none())
    if not assigned or not task.is_active:
        raise HTTPException(403, "Mund të veprosh vetëm mbi detyrat e tua aktive.")
    result = await tools.user_api(user, "GET", f"/api/tasks/{task_id}")
    result["user_comment"] = (await db.execute(select(TaskUserComment.comment).where(
        TaskUserComment.task_id == task_id, TaskUserComment.user_id == user.id))).scalar_one_or_none()
    return await tools.with_source_note(user, result)


async def daily_tasks(db: AsyncSession, user: User, bucket: str | None = None):
    now = datetime.now(ZoneInfo(settings.APP_TIMEZONE))
    start = datetime.combine(now.date(), time.min, now.tzinfo)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    tasks = await tools.user_api(user, "GET", "/api/tasks", params={"assigned_to": str(user.id),
        "window_from": start.isoformat(), "window_to": end.isoformat(), "include_done": "false", "include_inactive": "false"})
    # Always read today's explicit overrides. At 16:05 the slot editing endpoint
    # targets tomorrow, but the PM reminder still reports today's work.
    overrides = dict((await db.execute(select(TaskOneHReportSlot.task_id, TaskOneHReportSlot.one_h_report_slot)
        .where(TaskOneHReportSlot.report_date == now.date()))).all())
    overrides = {str(key): value for key, value in overrides.items()}
    if bucket:
        tasks = [task for task in tasks if tools.in_bucket(task, bucket, overrides)]
    for task in tasks:
        task["one_h_report_slot"] = overrides.get(str(task["id"]), task.get("one_h_report_slot"))
    return tasks


@router.get("/me")
async def me(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == user.id))).scalar_one_or_none()
    return {"configured": configured(), "timezone": settings.APP_TIMEZONE,
        "schedule": [{"bucket": b, "at": at.isoformat(timespec="minutes")} for b, at in tools.REMINDERS],
        "linked": bool(link and link.enabled), "channel_id": link.channel_id if link and link.enabled else None,
        "guild_id": link.guild_id if link and link.enabled else None}


@router.post("/link-code")
async def create_link_code(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not configured():
        raise HTTPException(503, "Administratori duhet të konfigurojë botin Discord fillimisht.")
    # Serialize code issuance against unlink/relink for the same account.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    await db.execute(delete(DiscordLinkCode).where(DiscordLinkCode.user_id == user.id))
    code = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.add(DiscordLinkCode(code_hash=hashlib.sha256(code.encode()).hexdigest(), user_id=user.id, expires_at=expires))
    await db.commit()
    return {"code": code, "expires_at": expires, "command": f"/lidh kodi:{code}"}


@router.delete("/link")
async def unlink(user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == user.id).with_for_update())).scalar_one_or_none()
    if link:
        link.enabled = False
        link.selected_task_id = None
        link.pending_instruction = None
        link.selected_fingerprint = None
    await db.execute(delete(DiscordLinkCode).where(DiscordLinkCode.user_id == user.id))
    await db.commit()
    return {"ok": True}


@router.post("/bot/link", dependencies=[Depends(require_bot)])
async def redeem_code(payload: LinkRequest, db: AsyncSession = Depends(get_db)):
    if payload.guild_id != settings.DISCORD_GUILD_ID:
        raise HTTPException(403, "Server i palejuar.")
    code = await db.get(DiscordLinkCode, hashlib.sha256(payload.code.encode()).hexdigest(), with_for_update=True)
    if not code or code.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(400, "Kodi ka skaduar ose është përdorur. Gjenero një kod të ri në PrimeFlow.")
    user = await db.get(User, code.user_id)
    if not user or not user.is_active:
        raise HTTPException(403, "Llogaria nuk është aktive.")
    existing = (await db.execute(select(DiscordLink).where(DiscordLink.guild_id == payload.guild_id,
        DiscordLink.discord_user_id == payload.discord_user_id).with_for_update())).scalar_one_or_none()
    if existing and existing.user_id != user.id:
        raise HTTPException(409, "Kjo llogari Discord është lidhur me një përdorues tjetër.")
    link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == user.id).with_for_update())).scalar_one_or_none()
    if not link:
        link = DiscordLink(user_id=user.id, discord_user_id=payload.discord_user_id, guild_id=payload.guild_id)
        db.add(link)
    if link.discord_user_id != payload.discord_user_id or link.guild_id != payload.guild_id:
        link.channel_id = None
    link.discord_user_id, link.guild_id, link.enabled = payload.discord_user_id, payload.guild_id, True
    link.selected_task_id, link.pending_instruction = None, None
    link.selected_fingerprint = None
    await db.delete(code)
    await db.commit()
    return {"link_id": str(link.id), "channel_id": link.channel_id, "full_name": user.full_name}


@router.post("/bot/bind-channel", dependencies=[Depends(require_bot)])
async def bind_channel(payload: Actor, db: AsyncSession = Depends(get_db)):
    if payload.guild_id != settings.DISCORD_GUILD_ID:
        raise HTTPException(403, "Server i palejuar.")
    link = (await db.execute(select(DiscordLink).where(DiscordLink.discord_user_id == payload.discord_user_id,
        DiscordLink.guild_id == payload.guild_id, DiscordLink.enabled.is_(True)).with_for_update())).scalar_one_or_none()
    if not link:
        raise HTTPException(404, "Lidhja nuk u gjet.")
    if link.channel_id and link.channel_id != payload.channel_id:
        raise HTTPException(409, "Llogaria ka tashmë një kanal privat.")
    link.channel_id = payload.channel_id
    await db.commit()
    return {"ok": True}


@router.post("/bot/tasks", dependencies=[Depends(require_bot)])
async def tasks_for_actor(payload: Actor, db: AsyncSession = Depends(get_db)):
    _, user = await identity(db, payload)
    return {"tasks": await daily_tasks(db, user), "full_name": user.full_name}


@router.post("/bot/select", dependencies=[Depends(require_bot)])
async def select_task(payload: Selection, db: AsyncSession = Depends(get_db)):
    link, user = await identity(db, payload, lock=True)
    task = await owned_task(db, user, payload.task_id)
    link.selected_task_id, link.selected_at, link.pending_instruction = payload.task_id, datetime.now(timezone.utc), None
    link.selected_fingerprint = tools.fingerprint(task)
    await db.commit()
    return {"task": task, "fingerprint": tools.fingerprint(task)[:16], "title_points": tools.text_points(tools.point_text(task, "title"), "title"),
        "description_points": tools.text_points(tools.point_text(task, "description"), "description"),
        "url": f"{settings.FRONTEND_URL.rstrip('/')}/tasks/{payload.task_id}"}


@router.post("/bot/people", dependencies=[Depends(require_bot)])
async def people_for_actor(payload: Selection, db: AsyncSession = Depends(get_db)):
    _, user = await identity(db, payload)
    await owned_task(db, user, payload.task_id)
    people = await tools.user_api(user, "GET", "/api/users")
    return {"people": [{"id": person["id"], "full_name": person["full_name"]}
                       for person in people if person.get("is_active", True)]}


@router.post("/bot/command", dependencies=[Depends(require_bot)])
async def command(payload: Command, db: AsyncSession = Depends(get_db)):
    if payload.direct_actions is not None and (not payload.task_id or not payload.expected_fingerprint):
        raise HTTPException(422, "Veprimi direkt kërkon detyrën dhe versionin e shfaqur.")
    link, user = await identity(db, payload, lock=True)
    old = await db.get(DiscordAction, payload.request_id)
    if old:
        if old.link_id != link.id:
            raise HTTPException(409, "Komandë e përsëritur me identitet tjetër.")
        return (old.result.get("reply", old.result) if old.result else
            {"message": "Kjo komandë është në përpunim ose kërkon kontroll në PrimeFlow; nuk do të përsëritet.", "status": old.status})
    task_id = payload.task_id or link.selected_task_id
    if not task_id:
        return {"message": "Zgjidh detyrën nga dropdown fillimisht.", "status": "QUESTION"}
    action = DiscordAction(id=payload.request_id, link_id=link.id, task_id=task_id, instruction=payload.instruction)
    db.add(action)
    # Durable reservation BEFORE calling an API that may commit. An interrupted
    # command is never replayed blindly, even after a worker restart.
    await db.commit()
    link, user = await identity(db, payload, lock=True)
    applied = []
    before = None
    try:
        before = await owned_task(db, user, task_id)
        expected = payload.expected_fingerprint
        if not expected and link.selected_task_id == task_id:
            expected = (link.selected_fingerprint or "")[:16]
        if expected and tools.fingerprint(before)[:16] != expected:
            raise ValueError("Detyra ndryshoi pasi u shfaq në Discord. Zgjidhe përsëri nga dropdown për të parë pikat aktuale.")
        history = link.pending_instruction if link.selected_task_id == task_id else None
        try:
            checklists = await tools.user_api(user, "GET", "/api/checklists", params={"task_id": str(task_id)})
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            checklists = []  # Task text points remain editable for staff.
        users = await tools.user_api(user, "GET", "/api/users")
        users = [{k: u.get(k) for k in ("id", "full_name", "username", "email")} for u in users if u.get("is_active", True)]
        # Buttons and forms already specify the exact change. They use the same
        # validation/audit/idempotency path, without asking AI to reinterpret it.
        plan = (tools.TaskPlan(question=None, actions=payload.direct_actions) if payload.direct_actions is not None
                else await tools.interpret(payload.instruction, before, checklists, users, history))
        if plan.question:
            link.selected_task_id, link.selected_at = task_id, datetime.now(timezone.utc)
            link.pending_instruction = ((history + "\n") if history else "") + payload.instruction + "\nPyetja: " + plan.question
            link.pending_instruction = link.pending_instruction[-8000:]
            result = {"message": plan.question, "status": "QUESTION"}
        else:
            operations = tools.compile_actions(plan, before, checklists, users, ((history + "\n") if history else "") + payload.instruction, datetime.now(ZoneInfo(settings.APP_TIMEZONE)), user_id=str(user.id))
            current = await owned_task(db, user, task_id)
            if tools.fingerprint(current) != tools.fingerprint(before):
                raise ValueError("Detyra ndryshoi gjatë bisedës. Zgjidhe përsëri dhe ridërgo udhëzimin.")
            for operation in operations:
                await identity(db, payload)
                await owned_task(db, user, task_id)
                await tools.user_api(user, operation["method"], operation["path"], body=operation.get("body"), params=operation.get("params"))
                applied.append(operation)
            link.pending_instruction = None
            after = None if any(op["method"] == "DELETE" for op in operations) else await tools.user_api(user, "GET", f"/api/tasks/{task_id}")
            if after:
                after = await tools.with_source_note(user, after)
                after["user_comment"] = (await db.execute(select(TaskUserComment.comment).where(
                    TaskUserComment.task_id == task_id, TaskUserComment.user_id == user.id))).scalar_one_or_none()
                link.selected_task_id = task_id
                link.selected_fingerprint = tools.fingerprint(after)
            else:
                link.selected_task_id, link.selected_fingerprint = None, None
            result = {"status": "DONE", "message": "; ".join(op["label"] for op in applied) or "Nuk u kërkua ndryshim.",
                "task": after, "fingerprint": tools.fingerprint(after)[:16] if after else None,
                "title_points": tools.text_points(tools.point_text(after, "title"), "title") if after else [],
                "description_points": tools.text_points(tools.point_text(after, "description"), "description") if after else [],
                "url": f"{settings.FRONTEND_URL.rstrip('/')}/tasks/{task_id}"}
        action.result, action.status = {"reply": result, "before": before, "operations": applied}, result["status"]
        await db.commit()
        return result
    except Exception as exc:
        # API writes can have succeeded before a later operation was refused.
        # Preserve and report each applied operation instead of claiming rollback.
        import logging
        if isinstance(exc, HTTPException):
            message = str(exc.detail.get("message", exc.detail)) if isinstance(exc.detail, dict) else str(exc.detail)
        elif isinstance(exc, ValueError):
            message = str(exc)[:1000]
        else:
            logging.getLogger(__name__).exception("Discord action %s failed", payload.request_id)
            message = "Shërbimi nuk e përfundoi komandën. Kontrollo rezultatin në PrimeFlow para se ta ridërgosh."
        recoverable = isinstance(exc, HTTPException) and exc.status_code in {400, 409, 422} and not applied
        if recoverable:
            link.selected_task_id = task_id
            link.pending_instruction = (payload.instruction + "\nSqarimi i kërkuar nga PrimeFlow: " + message)[-8000:]
        result = {"status": "PARTIAL" if applied else "QUESTION" if recoverable else "ERROR", "message": message, "applied": [op["label"] for op in applied]}
        action.result, action.status = {"reply": result, "before": before, "operations": applied}, result["status"]
        await db.commit()
        return result


@router.post("/bot/reminders/claim", dependencies=[Depends(require_bot)])
async def claim_reminders(db: AsyncSession = Depends(get_db)):
    now = datetime.now(ZoneInfo(settings.APP_TIMEZONE))
    jobs = []
    for bucket in tools.due_buckets(now):
        links = (await db.execute(select(DiscordLink).join(User, User.id == DiscordLink.user_id).where(
            DiscordLink.enabled.is_(True), DiscordLink.channel_id.is_not(None),
            DiscordLink.guild_id == settings.DISCORD_GUILD_ID, User.is_active.is_(True)))).scalars().all()
        for link in links:
            stmt = insert(DiscordReminder).values(id=uuid.uuid4(), link_id=link.id, day=now.date(), bucket=bucket,
                lease_until=now + timedelta(minutes=2))
            stmt = stmt.on_conflict_do_update(constraint="uq_discord_reminder_bucket",
                set_={"lease_until": now + timedelta(minutes=2)},
                where=(DiscordReminder.sent_at.is_(None) & (DiscordReminder.lease_until < now))).returning(DiscordReminder.id)
            reminder_id = (await db.execute(stmt)).scalar_one_or_none()
            if reminder_id:
                jobs.append({"id": str(reminder_id), "bucket": bucket, "discord_user_id": link.discord_user_id,
                    "guild_id": link.guild_id, "channel_id": link.channel_id})
    await db.commit()
    return {"jobs": jobs}


@router.post("/bot/reminders/{reminder_id}/tasks", dependencies=[Depends(require_bot)])
async def reminder_tasks(reminder_id: uuid.UUID, payload: Actor, db: AsyncSession = Depends(get_db)):
    link, user = await identity(db, payload)
    reminder = await db.get(DiscordReminder, reminder_id)
    if not reminder or reminder.link_id != link.id or reminder.day != datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date():
        raise HTTPException(404, "Kujtesa nuk u gjet.")
    return {"tasks": await daily_tasks(db, user, reminder.bucket), "bucket": reminder.bucket}


class Receipt(Actor):
    message_ids: list[str] = Field(max_length=100)


@router.post("/bot/reminders/{reminder_id}/ack", dependencies=[Depends(require_bot)])
async def acknowledge(reminder_id: uuid.UUID, payload: Receipt, db: AsyncSession = Depends(get_db)):
    link, _ = await identity(db, payload)
    reminder = await db.get(DiscordReminder, reminder_id, with_for_update=True)
    if not reminder or reminder.link_id != link.id:
        raise HTTPException(404, "Kujtesa nuk u gjet.")
    reminder.sent_at = datetime.now(timezone.utc)
    reminder.message_ids = payload.message_ids
    await db.commit()
    return {"ok": True}
