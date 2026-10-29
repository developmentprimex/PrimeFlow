"""Narrow delegation to Kujtesa; no Discord token or work-bot access here."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, update, func

from app.config import settings
from app.models.ga_personal import (
    GaPersonalDiscordDelivery as Outbox, GaPersonalOccurrence as Occurrence,
    GaPersonalTemplate as Template, GaPersonalMember as Member,
    GaPersonalSpace as Space, GaPersonalEvent as Event,
)
from app.models.user import User
from app.services import ga_personal as tasks

utcnow = tasks.utcnow
PHASES = (("before", -5), ("due", 0), ("after", 5))
OPEN = {"pending", "acknowledged", "in_progress", "rescheduled"}
UPDATE_BATCH_LIMIT = 200


async def members(db, space_id):
    rows = (await db.execute(select(Member, User.full_name).join(User, User.id == Member.user_id).where(
        Member.space_id == space_id, Member.active.is_(True), User.is_active.is_(True),
    ))).all()
    return {m.person_key: (m, name) for m, name in rows}


async def granted(db, space):
    cfg = space.config.get("discord", {})
    if not cfg.get("enabled") or cfg.get("password_version") != space.password_version:
        return False
    active = await members(db, space.id)
    return any(str(m.user_id) == cfg.get("authorized_by") and m.is_admin for m, _ in active.values())


def public_status(space):
    cfg = space.config.get("discord", {})
    last = cfg.get("last_seen_at")
    connected = bool(last and utcnow() - datetime.fromisoformat(last) < timedelta(seconds=90))
    return {"connected": connected, "messages_enabled": bool(cfg.get("enabled") and cfg.get("password_version") == space.password_version),
            "configured": bool(settings.GA_PERSONAL_DISCORD_BRIDGE_SECRET), "last_seen_at": last,
            "version": cfg.get("version", 0)}


async def get_settings(db, member):
    space = await db.get(Space, member.space_id)
    cfg = space.config.get("discord", {})
    counts = (await db.execute(select(Outbox.status, func.count(Outbox.id)).join(Occurrence, Occurrence.id == Outbox.occurrence_id)
        .where(Occurrence.space_id == space.id).group_by(Outbox.status))).all()
    return {**public_status(space), "enabled": await granted(db, space), "guild_id": cfg.get("guild_id", ""),
            "channel_id": cfg.get("channel_id", ""), "user_ids": cfg.get("user_ids", {}),
            "missing_people": [p for p in ("rrita", "mrika", "gane") if not cfg.get("user_ids", {}).get(p)],
            "delivery_counts": dict(counts)}


async def save_settings(db, member, payload):
    space = await tasks.lock_member_space(db, member, need_admin=True)
    cfg = space.config.get("discord", {})
    if payload.expected_version != cfg.get("version", 0):
        raise HTTPException(409, "Cilësimet ndryshuan. Rifreskoji para ruajtjes.")
    if payload.enabled and not settings.GA_PERSONAL_DISCORD_BRIDGE_SECRET:
        raise HTTPException(409, "Çelësi i lidhjes ende nuk është konfiguruar në server.")
    data = payload.model_dump(exclude={"expected_version"})
    data["user_ids"] = {p: uid for p, uid in data["user_ids"].items() if uid}
    current = {key: cfg.get(key) for key in data}
    current["user_ids"] = {p: uid for p, uid in cfg.get("user_ids", {}).items() if uid}
    if current == data and cfg.get("password_version") == space.password_version and (not payload.enabled or await granted(db, space)):
        return await get_settings(db, member)
    space.config = {**space.config, "discord": {**cfg,
        **data, "version": cfg.get("version", 0) + 1,
        "authorized_by": str(member.user_id), "password_version": space.password_version,
    }}
    ids = select(Occurrence.id).where(Occurrence.space_id == space.id)
    await cancel(db, ids)
    db.add(Event(space_id=space.id, actor_id=member.user_id, request_id=str(tasks.uuid.uuid4()),
        kind="discord_configured", payload={"enabled": payload.enabled, "version": cfg.get("version", 0) + 1}))
    await db.commit()
    return await get_settings(db, member)


async def cancel(db, occurrence_ids):
    await db.execute(update(Outbox).where(Outbox.occurrence_id.in_(occurrence_ids),
        Outbox.status.in_(["pending", "claimed"])).values(status="cancelled"))


def routes(row, cfg, active):
    owners = row.snapshot["assignees"]
    if not owners or not set(owners).issubset(active):
        return []
    destination = row.snapshot.get("discord_destination", "dm")
    if destination == "off":
        return []
    if destination == "channel":
        return [("channel", {"kind": "channel", "channel_id": cfg["channel_id"]})]
    targets = {}
    for person in owners:
        contact = "gane" if person == "lirza" else person
        uid = cfg.get("user_ids", {}).get(contact)
        if uid and contact in active:
            targets[uid] = (f"dm:{uid}", {"kind": "dm", "user_id": uid})
    return list(targets.values())


def schedule_key(row, cfg, target):
    return tasks.document_hash({"due_at": tasks.aware(row.due_at).isoformat() if row.due_at else None,
        "assignees": sorted(row.snapshot["assignees"]), "target": target, "guild": cfg.get("guild_id"),
        "revision": row.snapshot.get("discord_schedule_revision", 0), "grant_version": cfg.get("version", 0)})


def live(row, archived):
    return row.due_at is not None and row.status in OPEN and not archived


def card(delivery, row, active):
    result = {"id": str(delivery.id), "lease": delivery.lease, "occurrence_id": str(row.id),
        "phase": delivery.phase, "target": delivery.details["target"], "guild_id": delivery.details["guild_id"],
        "title": row.snapshot["title"], "assignees": row.snapshot["assignees"],
        "names": [active[p][1] if p in active else p for p in row.snapshot["assignees"]],
        "due_at": tasks.aware(row.due_at).isoformat() if row.due_at else None,
        "status": row.status, "version": row.version,
        "channel_id": delivery.channel_id, "message_id": delivery.message_id}
    result["sync_key"] = tasks.document_hash({k: v for k, v in result.items() if k not in {"lease", "channel_id", "message_id"}})
    return result


def current_card(delivery, row, archived, cfg, active):
    reference = delivery.details.get("action_key", delivery.schedule_key)
    matches = any(delivery.recipient == recipient and reference == schedule_key(row, cfg, target)
                  for recipient, target in routes(row, cfg, active))
    if matches and not archived:
        return card(delivery, row, active)
    result = {"id": str(delivery.id), "channel_id": delivery.channel_id, "message_id": delivery.message_id,
              "removed": True, "target": delivery.details["target"], "guild_id": delivery.details["guild_id"]}
    result["sync_key"] = tasks.document_hash(result)
    return result


async def occurrence(db, space, delivery_id):
    result = (await db.execute(select(Outbox, Occurrence, Template.archived).join(Occurrence,
        Occurrence.id == Outbox.occurrence_id).join(Template, Template.id == Occurrence.template_id).where(
        Outbox.id == delivery_id, Occurrence.space_id == space.id, Template.space_id == space.id,
    ))).one_or_none()
    if result is None:
        raise HTTPException(404, "Kujtesa nuk u gjet.")
    return result


def valid_target(delivery, row, archived, cfg, active):
    return live(row, archived) and any(delivery.recipient == recipient and delivery.schedule_key == schedule_key(row, cfg, target)
        for recipient, target in routes(row, cfg, active))


async def poll(db, space, *, delivery_enabled=True, health_only=False):
    moment = utcnow()
    cfg = space.config.get("discord", {})
    if health_only:
        return {"ok": True, "enabled": await granted(db, space), "guild_id": cfg.get("guild_id"),
                "deliveries": [], "updates": [], "missing_people": []}
    space.config = {**space.config, "discord": {**cfg, "last_seen_at": moment.isoformat()}}
    if not await granted(db, space):
        await cancel(db, select(Occurrence.id).where(Occurrence.space_id == space.id))
        await db.commit()
        return {"enabled": False, "deliveries": [], "updates": [], "missing_people": []}
    if not delivery_enabled:
        await db.commit()
        return {"enabled": True, "deliveries": [], "updates": [], "missing_people": []}
    active = await members(db, space.id)
    rows = (await db.execute(select(Occurrence, Template.archived).join(Template, Template.id == Occurrence.template_id).where(
        Occurrence.space_id == space.id, Template.space_id == space.id,
        Occurrence.due_at >= moment - timedelta(days=1), Occurrence.due_at <= moment + timedelta(days=2),
    ))).all()
    existing = (await db.execute(select(Outbox).join(Occurrence, Occurrence.id == Outbox.occurrence_id).where(
        Occurrence.space_id == space.id, Outbox.status.in_(["pending", "claimed"]),
    ))).scalars().all()
    row_map = {row.id: (row, archived) for row, archived in rows}
    for delivery in existing:
        current = row_map.get(delivery.occurrence_id)
        if not current or not valid_target(delivery, *current, cfg, active):
            delivery.status = "cancelled"
        elif delivery.status == "claimed" and tasks.aware(delivery.leased_until) <= moment:
            # An interrupted worker may already have sent. Never replay blindly.
            delivery.status = "uncertain"
    known = {(d.occurrence_id, d.schedule_key, d.phase, d.recipient) for d in (await db.execute(
        select(Outbox).join(Occurrence, Occurrence.id == Outbox.occurrence_id).where(Occurrence.space_id == space.id)
    )).scalars()}
    deliveries = []
    for row, archived in rows:
        if not live(row, archived):
            continue
        for recipient, target in routes(row, cfg, active):
            fingerprint = schedule_key(row, cfg, target)
            for phase, offset in PHASES:
                scheduled = tasks.aware(row.due_at) + timedelta(minutes=offset)
                key = (row.id, fingerprint, phase, recipient)
                if key in known:
                    continue
                # Do not queue future phases: later edits/status changes are reread.
                if scheduled > moment:
                    continue
                status = "skipped" if moment >= scheduled + timedelta(minutes=5) else "claimed"
                if status == "claimed" and len(deliveries) >= 20:
                    continue
                entry = Outbox(occurrence_id=row.id, schedule_key=fingerprint, phase=phase, recipient=recipient,
                    scheduled_at=scheduled, status=status, lease=secrets.token_hex(24),
                    leased_until=moment + timedelta(seconds=90), details={"target": target, "guild_id": cfg["guild_id"]})
                db.add(entry); await db.flush(); known.add(key)
                if status == "claimed":
                    deliveries.append(card(entry, row, active))
    sent = (await db.execute(select(Outbox, Occurrence, Template.archived).join(Occurrence, Occurrence.id == Outbox.occurrence_id)
        .join(Template, Template.id == Occurrence.template_id).where(Occurrence.space_id == space.id,
        Outbox.status == "sent").order_by(Outbox.scheduled_at, Outbox.id))).all()
    updates = []
    for delivery, row, archived in sent:
        if delivery.details.get("sync_terminal"):
            continue
        retry_at = delivery.details.get("sync_retry_at")
        if retry_at and datetime.fromisoformat(retry_at) > moment:
            continue
        updated = current_card(delivery, row, archived, cfg, active)
        if delivery.details.get("synced_key") != updated["sync_key"]:
            updates.append(updated)
            if len(updates) >= UPDATE_BATCH_LIMIT:
                break
    await db.commit()
    return {"enabled": True, "deliveries": deliveries, "updates": updates,
            "allowed_user_ids": [uid for p, uid in cfg.get("user_ids", {}).items() if uid and p in active],
            "missing_people": [p for p in active if p != "lirza" and not cfg.get("user_ids", {}).get(p)]}


async def prepare(db, space, delivery_id, payload):
    delivery, row, archived = await occurrence(db, space, delivery_id)
    active = await members(db, space.id)
    if (delivery.status != "claimed" or not secrets.compare_digest(delivery.lease or "", payload.lease)
        or tasks.aware(delivery.leased_until) <= utcnow() or not await granted(db, space)
        or not valid_target(delivery, row, archived, space.config["discord"], active)):
        raise HTTPException(409, "Kjo kujtesë ndryshoi ose skadoi; nuk duhet dërguar.")
    return {**card(delivery, row, active), "allowed_user_ids": [uid for p, uid in space.config["discord"].get("user_ids", {}).items() if uid and p in active]}


async def report(db, space, delivery_id, payload):
    delivery, row, _ = await occurrence(db, space, delivery_id)
    if not secrets.compare_digest(delivery.lease or "", payload.lease):
        raise HTTPException(403, "Kërkesë e paautorizuar.")
    if delivery.status == payload.outcome:
        if payload.outcome == "sent" and (delivery.message_id != payload.message_id or delivery.channel_id != payload.channel_id):
            raise HTTPException(409, "Kujtesa u regjistrua me një mesazh tjetër.")
        return {"recorded": True}
    if delivery.status not in {"claimed", "uncertain", "cancelled"}:
        raise HTTPException(409, "Kujtesa është regjistruar tashmë.")
    if payload.outcome == "sent":
        if not payload.channel_id or not payload.message_id:
            raise HTTPException(422, "Mungon referenca e mesazhit.")
        target = delivery.details["target"]
        if target["kind"] == "channel" and target["channel_id"] != payload.channel_id:
            raise HTTPException(403, "Kanal i paautorizuar.")
        delivery.channel_id, delivery.message_id = payload.channel_id, payload.message_id
    delivery.status = payload.outcome
    delivery.details = {**delivery.details, "error": payload.error}
    if payload.outcome == "sent" and payload.sync_key:
        delivery.details = {**delivery.details, "synced_key": payload.sync_key}
    await db.commit()
    return {"recorded": True}


async def synced(db, space, delivery_id, payload):
    delivery, row, archived = await occurrence(db, space, delivery_id)
    if delivery.status != "sent" or delivery.channel_id != payload.channel_id or delivery.message_id != payload.message_id:
        raise HTTPException(403, "Mesazh i paautorizuar.")
    if payload.error:
        delivery.details = {**delivery.details, "sync_error": payload.error, "sync_terminal": payload.error == "not_found",
                            "sync_retry_at": (utcnow() + timedelta(minutes=5)).isoformat()}
        await db.commit()
        return {"recorded": True}
    active = await members(db, space.id)
    updated = current_card(delivery, row, archived, space.config.get("discord", {}), active)
    if updated["sync_key"] != payload.sync_key:
        return {"recorded": False}
    delivery.details = {**delivery.details, "synced_key": payload.sync_key, "sync_error": None, "sync_retry_at": None}
    await db.commit()
    return {"recorded": True}


async def action(db, space, delivery_id, payload):
    if not await granted(db, space):
        raise HTTPException(403, "Lidhja me Discord është çaktivizuar.")
    delivery, row, archived = await occurrence(db, space, delivery_id)
    cfg = space.config["discord"]
    active = await members(db, space.id)
    person = next((p for p, uid in cfg.get("user_ids", {}).items() if uid == payload.actor_id and p in active), None)
    target = delivery.details["target"]
    expected_guild = cfg["guild_id"] if target["kind"] == "channel" else None
    if (not person or delivery.status != "sent" or payload.message_id != delivery.message_id
        or payload.channel_id != delivery.channel_id or payload.guild_id != expected_guild
        or (target["kind"] == "dm" and target["user_id"] != payload.actor_id)):
        raise HTTPException(403, "Ky mesazh ose veprim nuk është i autorizuar për ty.")
    if person not in row.snapshot["assignees"] and not (person == "gane" and "lirza" in row.snapshot["assignees"]):
        raise HTTPException(403, "Kjo detyrë i përket një personi tjetër.")
    member = active[person][0]
    request_id = "discord:" + payload.interaction_id
    previous = (await db.execute(select(Event).where(Event.space_id == space.id, Event.request_id == request_id))).scalar_one_or_none()
    signature = payload.model_dump(mode="json")
    if previous:
        if previous.actor_id != member.user_id or previous.occurrence_id != row.id or previous.payload.get("discord_action") != signature:
            raise HTTPException(409, "Ky veprim është përdorur më herët.")
        return {"status": row.status, "card": card(delivery, row, active)}
    # Check retries first: a successful snooze necessarily changed the schedule.
    # New interactions from stale cards must still be rejected.
    reference = delivery.details.get("action_key", delivery.schedule_key)
    if archived or not any(delivery.recipient == r and reference == schedule_key(row, cfg, t) for r, t in routes(row, cfg, active)):
        raise HTTPException(409, "Detyra ndryshoi. Hape kartelën e përditësuar.")
    if payload.action == "steps":
        return {"status": row.status, "steps": row.snapshot.get("steps", []), "description": row.snapshot.get("description", "")}
    new_status = payload.action
    reschedule_at = None
    if new_status.startswith("later"):
        minutes = int(new_status[5:])
        reschedule_at = utcnow() + timedelta(minutes=minutes)
        new_status = "rescheduled"
    old = row.status
    await tasks.change_status(db, row, new_status, reschedule_at)
    if new_status == "rescheduled":
        delivery.details = {**delivery.details, "action_key": schedule_key(row, cfg, target)}
    db.add(Event(space_id=space.id, occurrence_id=row.id, actor_id=member.user_id, request_id=request_id,
        kind="status_changed", payload={"from": old, "to": row.status, "via": "kujtesa",
            "completion_method": "self_report" if row.status == "done" else None,
            "on_behalf_of": "lirza" if person == "gane" and person not in row.snapshot["assignees"] else None,
            "discord_action": signature}))
    await db.commit()
    return {"status": row.status, "card": card(delivery, row, active)}
