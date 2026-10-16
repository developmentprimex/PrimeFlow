"""Targets and authorized lifecycle of delegated Discord work."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.api.routers import discord_assistant as bridge
from app.config import settings
from app.models.discord_agent_run import DiscordAgentRun
from app.models.discord_assistant import DiscordAction
from app.services import discord_task_tools as tools
from app.services.task_strike_events import _point_entries

TERMINAL = {"READY", "FAILED", "CANCELLED"}


def resolve_target(task: dict, field: str | None, number: int | None) -> dict:
    if field is None and number is None:
        return {"field": None, "number": None, "key": None, "text": None}
    if field not in {"title", "description"} or type(number) is not int:
        raise ValueError("Zgjidh një pikë titulli ose përshkrimi.")
    entries = _point_entries(task.get(field), field_name=field.upper())
    if not 1 <= number <= len(entries):
        raise ValueError("Pika nuk ekziston më; rifresko detyrën.")
    point = entries[number - 1][0]
    return {"field": field, "number": number, "key": point.key, "text": point.text}


def snapshot_context(task: dict, target: dict) -> dict:
    return {**{key: task.get(key) for key in ("id", "title", "description", "user_comment")}, "target": target}


def serialize_run(run) -> dict:
    def date(value):
        return value.isoformat() if value else None
    return {"id": str(run.id), "task_id": str(run.task_id) if run.task_id else None,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "mode": run.mode, "model": run.model, "instruction": run.instruction,
        "target": run.target, "fingerprint": run.fingerprint[:16], "status": run.status,
        "result_text": run.result_text, "sources": run.sources or [], "error": run.error,
        "accepted_at": date(run.accepted_at), "created_at": date(run.created_at),
        "started_at": date(run.started_at), "finished_at": date(run.finished_at)}


async def authorized_run(db, actor, run_id, *, lock=False):
    link, user = await bridge.identity(db, actor, lock=lock)
    run = await db.get(DiscordAgentRun, run_id, populate_existing=True, with_for_update=lock)
    if not run or run.link_id != link.id or run.user_id != user.id or not run.task_id:
        raise HTTPException(404, "Puna e agjentit nuk u gjet për këtë llogari.")
    task = await bridge.owned_task(db, user, run.task_id)
    return run, link, user, task


async def create_run(db, payload):
    link, user = await bridge.identity(db, payload, lock=True)
    existing = (await db.execute(select(DiscordAgentRun).where(DiscordAgentRun.request_id == payload.request_id))).scalar_one_or_none()
    if existing:
        if existing.link_id != link.id or existing.user_id != user.id:
            raise HTTPException(409, "Kërkesë e përsëritur me identitet tjetër.")
        if not existing.task_id:
            raise HTTPException(404, "Detyra nuk ekziston më.")
        await bridge.owned_task(db, user, existing.task_id)
        return serialize_run(existing)
    task = await bridge.owned_task(db, user, payload.task_id)
    version = tools.fingerprint(task)
    if version[:16] != payload.expected_fingerprint:
        raise HTTPException(409, "Detyra ndryshoi. Rifresko kartën dhe zgjidh pikën përsëri.")
    try:
        target = resolve_target(task, payload.field, payload.number)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    context = snapshot_context(task, target)
    if payload.parent_run_id:
        parent, _, _, _ = await authorized_run(db, payload, payload.parent_run_id)
        if parent.task_id != payload.task_id or parent.target != target or parent.status != "READY" or not parent.result_text:
            raise HTTPException(409, "Rezultati i mëparshëm nuk i përket këtij objektivi ose ende nuk është gati.")
        context["previous_result"] = {"text": parent.result_text, "sources": parent.sources or []}
    run = DiscordAgentRun(id=uuid.uuid4(), link_id=link.id, user_id=user.id,
        task_id=payload.task_id, parent_run_id=payload.parent_run_id,
        request_id=payload.request_id, mode=payload.mode, model=settings.DISCORD_AGENT_MODEL,
        instruction=payload.instruction.strip(), fingerprint=version, target=target, context=context,
        status="QUEUED", created_at=datetime.now(timezone.utc))
    db.add(run)
    await db.commit()
    return serialize_run(run)


async def cancel_run(db, run_id, actor):
    run, _, _, _ = await authorized_run(db, actor, run_id, lock=True)
    if run.status == "QUEUED":
        run.status, run.finished_at = "CANCELLED", datetime.now(timezone.utc)
    elif run.status not in TERMINAL:
        run.status = "CANCEL_REQUESTED"
    await db.commit()
    return serialize_run(run)


def task_detail(task):
    return {"task": task, "fingerprint": tools.fingerprint(task)[:16],
        "title_points": tools.text_points(task.get("title"), "title"),
        "description_points": tools.text_points(task.get("description"), "description")}


async def accept_run(db, run_id, payload):
    run, link, _, task = await authorized_run(db, payload, run_id, lock=True)
    if run.status != "READY":
        raise HTTPException(409, "Rezultati ende nuk është gati për pranim.")
    if not payload.mark_point_done:
        run.accepted_at = run.accepted_at or datetime.now(timezone.utc)
        if not run.acceptance_status:
            run.acceptance_status = "ACCEPTED"
        await db.commit()
        return {"run": serialize_run(run)}
    if run.acceptance_status == "POINT_DONE":
        return {"run": serialize_run(run), "task_detail": task_detail(task)}
    if not run.target.get("field"):
        raise HTTPException(422, "Kjo punë është për detyrën e plotë. Mbyllja bëhet nga karta e detyrës.")
    # A reservation survives an interrupted normal-API command. Never start
    # another mutation until the reserved command's durable result is known.
    result = None
    if run.acceptance_status == "APPLYING":
        action = await db.get(DiscordAction, run.acceptance_request_id)
        if action and action.link_id == link.id and action.result:
            result = action.result.get("reply")
        if not result:
            raise HTTPException(409, "Pranimi është në përpunim ose kërkon kontroll në PrimeFlow; nuk përsëritet.")
    else:
        current_target = resolve_target(task, run.target["field"], run.target["number"])
        if tools.fingerprint(task) != run.fingerprint or current_target["key"] != run.target["key"]:
            raise HTTPException(409, "Detyra ose pika ndryshoi. Kontrollo rezultatin dhe pikën aktuale në PrimeFlow.")
        run.acceptance_request_id, run.acceptance_status = payload.request_id, "APPLYING"
        await db.commit()
        command = bridge.Command(**payload.model_dump(include={"discord_user_id", "guild_id", "channel_id"}),
            request_id=run.acceptance_request_id, task_id=run.task_id,
            expected_fingerprint=run.fingerprint[:16], instruction="Prano rezultatin e agjentit dhe shëno pikën të kryer.",
            direct_actions=[tools.ToolAction(tool="set_points", arguments_json=__import__("json").dumps({
                "field": run.target["field"], "numbers": [run.target["number"]], "done": True}))])
        result = await bridge.command(command, db)
    if result.get("status") != "DONE":
        run.acceptance_status = "FAILED" if not result.get("applied") else "APPLYING"
        await db.commit()
        raise HTTPException(409, result.get("message", "Kontrollo ndryshimin në PrimeFlow para se të riprovosh."))
    run.accepted_at, run.acceptance_status = datetime.now(timezone.utc), "POINT_DONE"
    await db.commit()
    return {"run": serialize_run(run), "task_detail": task_detail(result["task"]) if result.get("task") else task_detail(task)}

