"""Short durable processing ticks; remote work runs at OpenAI, not in Celery."""
from __future__ import annotations

import asyncio
import logging
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import HTTPException
from sqlalchemy import or_, select

from app.api.routers import discord_assistant as bridge
from app.db import SessionLocal
from app.models.discord_agent_run import DiscordAgentRun
from app.models.discord_assistant import DiscordLink
from app.services import discord_agent_openai as provider
from app.services.discord_agent_openai import build_request, extract_result
from app.services.discord_agents import TERMINAL

log = logging.getLogger(__name__)
RECOVERY_DIR = Path(__file__).resolve().parents[2] / ".discord-agent-recovery"


class MissingRun(LookupError):
    pass


def spool_response(work, response_id):
    """Keep only recovery IDs on disk before touching the database again."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", response_id):
        raise ValueError("OpenAI ktheu ID të pavlefshme për punën.")
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    path = RECOVERY_DIR / f"{work.id}.{response_id}.json"
    temporary = RECOVERY_DIR / f"{uuid.uuid4()}.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump({"run_id": str(work.id), "response_id": response_id,
            "lease_token": str(work.lease_token) if work.lease_token else None}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return path


async def remember_response(work, response_id):
    """Persist remote identity even if the original processing lease is gone."""
    async with SessionLocal() as db:
        current = await db.get(DiscordAgentRun, work.id, with_for_update=True, populate_existing=True)
        if not current:
            raise MissingRun(str(work.id))
        known = current.response_id == response_id
        owned = current.lease_token == work.lease_token and current.status not in TERMINAL
        if not current.response_id:
            current.response_id = response_id
        if not owned and not (known and current.status in {"RUNNING", "CANCEL_REQUESTED", "READY"}):
            current.cleanup_response_id = response_id
        elif owned and current.status == "SUBMITTING":
            current.status = "RUNNING"
        await db.commit()
        return owned


async def cancel_response(response_id):
    try:
        return await provider.cancel(response_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
        return await provider.retrieve(response_id)


async def recover_responses():
    if not RECOVERY_DIR.exists():
        return
    for path in RECOVERY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            response_id = data["response_id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", response_id):
                raise ValueError("Invalid recovery ID")
            work = SimpleNamespace(id=uuid.UUID(data["run_id"]),
                lease_token=uuid.UUID(data["lease_token"]) if data.get("lease_token") else None)
            try:
                await remember_response(work, response_id)
            except MissingRun:
                # Deleting a linked account must not orphan its provider work.
                response = await cancel_response(response_id)
                if response.get("status") not in {"completed", "cancelled", "failed", "incomplete"}:
                    continue
            path.unlink(missing_ok=True)
        except Exception as exc:
            log.warning("Agent response recovery pending: %s", type(exc).__name__)


async def finish_cleanup(work):
    async with SessionLocal() as db:
        current = await db.get(DiscordAgentRun, work.id, with_for_update=True)
        if current and current.lease_token == work.lease_token and current.cleanup_response_id == work.cleanup_response_id:
            current.cleanup_response_id = None
            await db.commit()


async def process_cleanup(work):
    try:
        response = await cancel_response(work.cleanup_response_id)
        if response.get("status") in {"completed", "cancelled", "failed", "incomplete"}:
            await finish_cleanup(work)
    except (httpx.HTTPError, ValueError):
        # The ID stays durable and claimable even when the public run is FAILED.
        log.warning("Agent response cleanup will retry for run %s", work.id)


def claim_query(now):
    return select(DiscordAgentRun).where(or_(DiscordAgentRun.status.not_in(TERMINAL), DiscordAgentRun.cleanup_response_id.is_not(None)),
        or_(DiscordAgentRun.lease_until.is_(None), DiscordAgentRun.lease_until < now))\
        .order_by(DiscordAgentRun.created_at).limit(10).with_for_update(skip_locked=True)


async def claim_runs():
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        rows = (await db.execute(claim_query(now))).scalars().all()
        for row in rows:
            row.lease_token, row.lease_until = uuid.uuid4(), now + timedelta(minutes=2)
        await db.commit()
        return rows


async def save_claim(work, values):
    async with SessionLocal() as db:
        current = await db.get(DiscordAgentRun, work.id, with_for_update=True, populate_existing=True)
        if not current or current.lease_token != work.lease_token:
            return False
        if current.status in TERMINAL:
            return False
        for name, value in values.items():
            if name == "status" and current.status == "CANCEL_REQUESTED" and value in {"SUBMITTING", "RUNNING"}:
                continue
            setattr(current, name, value)
        await db.commit()
        return True


async def is_authorized(work):
    if not bridge.configured():
        return False
    async with SessionLocal() as db:
        link = await db.get(DiscordLink, work.link_id)
        if not link or not link.enabled or link.user_id != work.user_id or not link.channel_id or not work.task_id:
            return False
        actor = bridge.Actor(discord_user_id=link.discord_user_id, guild_id=link.guild_id, channel_id=link.channel_id)
        try:
            _, user = await bridge.identity(db, actor)
            await bridge.owned_task(db, user, work.task_id)
        except HTTPException as exc:
            if exc.status_code in {401, 403, 404}:
                return False
            raise
        return True


async def _apply_response(work, response):
    status = response.get("status")
    if status in {"queued", "in_progress"}:
        await save_claim(work, {"status": "CANCEL_REQUESTED" if work.status == "CANCEL_REQUESTED" else "RUNNING"})
    elif status == "completed":
        result = extract_result(response, research=work.mode == "RESEARCH")
        await save_claim(work, {"status": "READY", "result_text": result["text"], "sources": result["sources"],
            "usage": result["usage"], "error": None, "finished_at": datetime.now(timezone.utc)})
    elif status == "cancelled":
        await save_claim(work, {"status": "CANCELLED", "finished_at": datetime.now(timezone.utc)})
    elif status in {"failed", "incomplete"}:
        await save_claim(work, {"status": "FAILED", "error": "OpenAI nuk e përfundoi punën. Mund të nisësh një punë të re nga rezultati.", "finished_at": datetime.now(timezone.utc)})
    else:
        raise ValueError("OpenAI ktheu një gjendje të panjohur.")


async def process_claim(work):
    if work.cleanup_response_id:
        await process_cleanup(work)
        return
    submitting = False
    try:
        allowed = await is_authorized(work)
        cancel_requested = work.status == "CANCEL_REQUESTED" or not allowed
        if cancel_requested:
            if work.response_id:
                work.status = "CANCEL_REQUESTED"
                await save_claim(work, {"status": "CANCEL_REQUESTED"})
                response = await cancel_response(work.response_id)
                await _apply_response(work, response)
            elif work.status == "SUBMITTING" or work.started_at:
                await save_claim(work, {"status": "FAILED", "error": "Nisja është e paqartë; kontrollo OpenAI para se të nisësh punë të re.", "finished_at": datetime.now(timezone.utc)})
            else:
                await save_claim(work, {"status": "CANCELLED", "finished_at": datetime.now(timezone.utc)})
            return
        if work.response_id:
            await _apply_response(work, await provider.retrieve(work.response_id))
            return
        if work.status != "QUEUED":
            await save_claim(work, {"status": "FAILED", "error": "Nisja është e paqartë; nuk u përsërit kërkesa me pagesë.", "finished_at": datetime.now(timezone.utc)})
            return
        if not await save_claim(work, {"status": "SUBMITTING", "started_at": datetime.now(timezone.utc)}):
            return
        submitting = True
        response = await provider.submit(build_request(work))
        response_id = response.get("id")
        if not response_id:
            raise ValueError("OpenAI nuk ktheu ID për punën; nisja është e paqartë.")
        work.response_id = response_id
        path = spool_response(work, response_id)
        owned = await remember_response(work, response_id)
        path.unlink(missing_ok=True)
        if not owned:
            return
        if not await save_claim(work, {"status": "RUNNING"}):
            # A terminal transition after remembering the ID still needs cleanup.
            await remember_response(work, response_id)
            return
        await _apply_response(work, response)
    except (httpx.HTTPError, ValueError) as exc:
        transient = isinstance(exc, (httpx.TimeoutException, httpx.TransportError)) or (
            isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code >= 500 or exc.response.status_code == 429))
        if transient and work.response_id:
            await save_claim(work, {"status": "CANCEL_REQUESTED" if work.status == "CANCEL_REQUESTED" else "RUNNING"})
        else:
            message = ("Nisja është e paqartë; kërkesa nuk do të përsëritet automatikisht." if submitting and transient else
                str(exc) if isinstance(exc, ValueError) else "OpenAI e refuzoi punën. Kontrollo konfigurimin, modelin dhe aksesin e llogarisë.")
            await save_claim(work, {"status": "FAILED", "error": message, "finished_at": datetime.now(timezone.utc)})
    except Exception:
        # Keep the existing ID/lease for recovery rather than resubmitting.
        log.exception("Discord agent processing failed for run %s", work.id)


async def _release(work):
    async with SessionLocal() as db:
        row = await db.get(DiscordAgentRun, work.id, with_for_update=True)
        if row and row.lease_token == work.lease_token:
            row.lease_token, row.lease_until = None, None
            await db.commit()


async def process_agent_runs():
    await recover_responses()
    rows = await claim_runs()
    async def process(row):
        try:
            await process_claim(row)
        finally:
            await _release(row)
    await asyncio.gather(*(process(row) for row in rows))
    return {"processed": len(rows)}
