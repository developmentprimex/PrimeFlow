"""Family commands and notices use the existing PrimeFlow grant and records."""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.models.ga_personal import (GaPersonalDiscordNotice as Notice, GaPersonalDeviceRecord as Record,
    GaPersonalEvent as Event, GaPersonalOccurrence as Occurrence, GaPersonalTemplate as Template,
    GaPersonalDiscordDelivery as Delivery)
from app.services import ga_personal as tasks, ga_personal_discord as bridge


def on_day(event, day):
    """Same dated recurrence as the local app, including monthly repeats."""
    try:
        start = date.fromisoformat(event["date"])
        if day < start or event.get("deleted"):
            return False
        repeat = event.get("repeat")
        if not repeat:
            return start == day
        if repeat.get("until") and day > date.fromisoformat(repeat["until"]):
            return False
        every = int(repeat["every"])
        if every < 1:
            return False
        if repeat["unit"] == "day":
            return (day - start).days % every == 0
        if repeat["unit"] == "week":
            weeks = ((day - timedelta(days=day.weekday())) - (start - timedelta(days=start.weekday()))).days // 7
            return weeks % every == 0 and day.weekday() in (repeat.get("days") or [start.weekday()])
        if repeat["unit"] == "month":
            return ((day.year - start.year) * 12 + day.month - start.month) % every == 0 and day.day == start.day
    except (KeyError, TypeError, ValueError):
        pass
    return False


async def day_rows(db, space, day):
    weekend = tasks.period_key({"frequency": "weekly"}, day)
    period = Occurrence.local_date == day.isoformat()
    if day.weekday() >= 5:
        period = period | ((Occurrence.period_key == weekend) & (Occurrence.status != "done"))
    return (await db.execute(select(Occurrence, Template).join(Template, Template.id == Occurrence.template_id).where(
        Occurrence.space_id == space.id, Template.space_id == space.id, Template.archived.is_(False),
        Occurrence.status != "cancelled", period,
    ).order_by(Occurrence.due_at, Occurrence.id))).all()


def line(row):
    planned = row.snapshot.get("agenda_time")
    when = (tasks.aware(row.due_at).astimezone(tasks.TZ).strftime("%H:%M") if row.due_at else planned[:5] if planned else "")
    when = when + " · " if when else ""
    state = {"done": " ✓", "needs_help": " · duhet ndihmë", "in_progress": " · ka filluar"}.get(row.status, "")
    return f"• {when}{row.snapshot['title']}{state}"


async def candidates(db, space, active):
    moment = bridge.utcnow().astimezone(tasks.TZ)
    day = moment.date()
    cfg = space.config.get("discord", {})
    found = {}

    def add(key, kind, text, target):
        identity = tasks.document_hash([key, target])
        found[identity] = {"kind": kind, "text": text[:1900], "target": target, "guild_id": cfg["guild_id"],
                           "grant_version": cfg.get("version", 0), "local_date": day.isoformat()}

    if cfg.get("daily_agenda") and moment.hour >= 6:
        groups = {}
        for row, _template in await day_rows(db, space, day):
            for recipient, target in bridge.routes(row, cfg, active):
                owners = ", ".join(active[p][1] for p in row.snapshot["assignees"])
                groups.setdefault(recipient, {"target": target, "lines": []})["lines"].append(f"• {owners}: {line(row)[2:]}")
        records = (await db.execute(select(Record).where(Record.space_id == space.id, Record.kind == "event"))).scalars().all()
        for record in records:
            event = record.payload
            if not on_day(event, day):
                continue
            owner = event.get("person_id")
            # Tablet events have no Discord destination: use private DMs by default.
            owners = [owner] if owner in active else list(active) if owner is None else []
            for person in owners:
                uid = cfg.get("user_ids", {}).get("gane" if person == "lirza" else person)
                if not uid:
                    continue
                item = groups.setdefault("dm:" + uid, {"target": {"kind": "dm", "user_id": uid}, "lines": []})
                text = f"• {event.get('start') + ' · ' if event.get('start') else ''}{event['title']}"
                if text not in item["lines"]:
                    item["lines"].append(text)
        notes = space.config.get("kujtesa_family_pack", {}).get("external_notes", [])
        for note in notes:
            if day.weekday() in note["days"]:
                item = groups.setdefault("channel", {"target": {"kind": "channel", "channel_id": cfg["channel_id"]}, "lines": []})
                item["lines"].append(f"• {note['person']}: {note['title']}")
        for recipient, group in groups.items():
            # Chunk rather than silently dropping the end of a long family agenda.
            chunks, text = [], f"Agjenda e ditës · {day:%d/%m}\n"
            for entry in group["lines"]:
                if len(text) + len(entry) + 1 > 1850:
                    chunks.append(text); text = "Agjenda · vazhdim\n"
                text += entry[:1700] + "\n"
            if text.strip(): chunks.append(text)
            for index, text in enumerate(chunks):
                add(["agenda", day.isoformat(), recipient, index], "agenda", text.strip(), group["target"])
    if cfg.get("presence_notifications"):
        events = (await db.execute(select(Event).where(Event.space_id == space.id, Event.kind.in_(["arrived", "woke"]),
            Event.created_at >= datetime.combine(day, datetime.min.time(), tasks.TZ)))).scalars().all()
        for event in events:
            person = event.payload.get("person_key")
            if event.payload.get("day") != day.isoformat() or person not in active:
                continue
            when = (datetime.fromtimestamp(event.payload["at"] / 1000, tasks.TZ) if event.payload.get("at")
                    else tasks.aware(event.created_at).astimezone(tasks.TZ)).strftime("%H:%M")
            verb = "u zgjua" if event.kind == "woke" else "erdhi në shtëpi"
            add([event.kind, str(event.id)], "presence", f"{active[person][1]} {verb}, ora {when}.",
                {"kind": "channel", "channel_id": cfg["channel_id"]})
    return found


def notice_card(row):
    return {**row.details, "id": str(row.id), "lease": row.lease, "kind": "notice", "notice_kind": row.kind}


async def poll_notices(db, space):
    active = await bridge.members(db, space.id)
    current = await candidates(db, space, active)
    existing = (await db.execute(select(Notice).where(Notice.space_id == space.id))).scalars().all()
    known = {n.notice_key for n in existing}
    for row in existing:
        if row.status == "claimed" and tasks.aware(row.leased_until) <= bridge.utcnow():
            row.status = "uncertain"
    batch = []
    for key, data in current.items():
        if key in known or len(batch) >= 20:
            continue
        row = Notice(space_id=space.id, notice_key=key, local_date=data["local_date"], kind=data["kind"],
            status="claimed", lease=secrets.token_hex(24), leased_until=bridge.utcnow() + timedelta(seconds=90), details=data)
        db.add(row); await db.flush()
        batch.append(notice_card(row))
    return batch


async def notice(db, space, identity):
    row = (await db.execute(select(Notice).where(Notice.id == identity, Notice.space_id == space.id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Njoftimi nuk u gjet.")
    return row


async def prepare_notice(db, space, identity, payload):
    row = await notice(db, space, identity)
    if (row.status != "claimed" or not secrets.compare_digest(row.lease, payload.lease)
        or tasks.aware(row.leased_until) <= bridge.utcnow() or not await bridge.granted(db, space)):
        raise HTTPException(409, "Njoftimi ndryshoi ose skadoi.")
    active = await bridge.members(db, space.id)
    current = (await candidates(db, space, active)).get(row.notice_key)
    if current is None or current["grant_version"] != row.details["grant_version"]:
        row.status = "cancelled"; await db.commit()
        raise HTTPException(409, "Njoftimi nuk është më aktiv.")
    row.details = current
    await db.commit()
    return {**notice_card(row), "allowed_user_ids": [uid for person, uid in space.config["discord"].get("user_ids", {}).items() if person in active and uid]}


async def report_notice(db, space, identity, payload):
    row = await notice(db, space, identity)
    if not secrets.compare_digest(row.lease, payload.lease):
        raise HTTPException(403, "Kërkesë e paautorizuar.")
    if row.status == payload.outcome:
        if payload.outcome == "sent" and (payload.channel_id != row.channel_id or payload.message_id != row.message_id):
            raise HTTPException(409, "Njoftimi është regjistruar me një mesazh tjetër.")
        return {"recorded": True}
    if row.status not in {"claimed", "uncertain", "cancelled"}:
        raise HTTPException(409, "Njoftimi është regjistruar tashmë.")
    if payload.outcome == "sent":
        if not payload.channel_id or not payload.message_id:
            raise HTTPException(422, "Mungon referenca e mesazhit.")
        target = row.details["target"]
        if target["kind"] == "channel" and payload.channel_id != target["channel_id"]:
            raise HTTPException(403, "Kanal i paautorizuar.")
        row.channel_id, row.message_id = payload.channel_id, payload.message_id
    row.status = payload.outcome
    row.details = {**row.details, "error": payload.error}
    await db.commit()
    return {"recorded": True}


async def apply_kaki(db, space, day, answer, *, actor_id, request_id, discord_action=None, at=None, op_id=None, allow_historical=False):
    """One answer for the family day; never overwrite an explicit reschedule."""
    stamp = at if at is not None else int(bridge.utcnow().timestamp() * 1000)
    identity = op_id or request_id[-36:]
    key = tasks.document_hash([day])
    record = (await db.execute(select(Record).where(Record.space_id == space.id, Record.kind == "kaki", Record.key == key))).scalar_one_or_none()
    if record and (record.client_at, record.op_id) >= (stamp, identity):
        return
    today = bridge.utcnow().astimezone(tasks.TZ).date().isoformat()
    if day != today and not allow_historical:
        raise HTTPException(409, "PËRGJIGJA e Nalës regjistrohet për ditën e sotme.")
    if record is None:
        record = Record(space_id=space.id, kind="kaki", key=key)
        db.add(record)
    record.payload, record.client_at, record.op_id = {"date": day, "answer": answer, "at": stamp}, stamp, identity
    record.updated_at = tasks.utcnow()
    if day != today:
        await db.flush()
        return
    rows = (await db.execute(select(Occurrence, Template).join(Template, Template.id == Occurrence.template_id).where(
        Occurrence.space_id == space.id, Template.space_id == space.id, Occurrence.local_date == day,
        Template.source_id.in_(["nala_afternoon", "nala_evening"]), Template.archived.is_(False),
    ))).all()
    afternoon = next((r for r, t in rows if t.source_id == "nala_afternoon"), None)
    if afternoon is None:
        if allow_historical:
            await db.flush()
            return
        raise HTTPException(409, "Shëtitja e pasdites nuk është regjistruar për këtë ditë.")
    afternoon.snapshot = {**afternoon.snapshot, "nala_kaki": answer}
    afternoon.version += 1
    for row, template in rows:
        if template.source_id != "nala_evening" or row.status in {"done", "cancelled", "rescheduled"} or not row.due_at:
            continue
        current = tasks.aware(row.due_at).astimezone(tasks.TZ)
        auto_time = row.snapshot.get("nala_auto_due_at")
        if row.snapshot.get("schedule_overridden") or (auto_time and tasks.aware(row.due_at).isoformat() != auto_time):
            continue
        if current.strftime("%H:%M") != "20:30" and not auto_time:
            continue
        wanted = current.replace(hour=19 if answer == "jo" else 20, minute=30, second=0, microsecond=0)
        if wanted <= bridge.utcnow() or wanted == current:
            continue
        row.due_at = wanted
        row.snapshot = {**row.snapshot, "nala_auto_due_at": wanted.astimezone(tasks.timezone.utc).isoformat(),
            "discord_schedule_revision": row.snapshot.get("discord_schedule_revision", 0) + 1}
        row.version += 1
        await tasks.cancel_discord(db, [row.id])
    db.add(Event(space_id=space.id, occurrence_id=afternoon.id, actor_id=actor_id, request_id=request_id,
                 kind="nala_kaki", payload={"day": day, "answer": answer, "discord_action": discord_action}))
    await db.flush()


async def record_wake(db, space, member, day, person, request_id, at=None):
    if person not in await bridge.members(db, space.id):
        raise HTTPException(422, "Personi nuk ka anëtarësi aktive.")
    prior = (await db.execute(select(Event).where(Event.space_id == space.id, Event.request_id == request_id))).scalar_one_or_none()
    if prior and (prior.actor_id != member.user_id or prior.kind != "woke" or prior.payload.get("person_key") != person or prior.payload.get("day") != day):
        raise HTTPException(409, "Ky veprim është përdorur më herët.")
    if prior is None:
        db.add(Event(space_id=space.id, actor_id=member.user_id, request_id=request_id, kind="woke",
                     payload={"day": day, "person_key": person, "at": at or int(bridge.utcnow().timestamp() * 1000)}))
        await db.flush()


async def command(db, space, payload, *, delivery_enabled=False):
    if not await bridge.granted(db, space):
        raise HTTPException(403, "Lidhja e Kujtesës nuk është aktive.")
    cfg = space.config["discord"]
    active = await bridge.members(db, space.id)
    person = next((p for p, uid in cfg.get("user_ids", {}).items() if uid == payload.actor_id and p in active), None)
    if not person or (payload.guild_id is not None and
        (payload.guild_id != cfg["guild_id"] or payload.channel_id != cfg["channel_id"])):
        raise HTTPException(403, "Përdore komandën në bisedën private ose kanalin e familjes.")
    member = active[person][0]
    moment = bridge.utcnow().astimezone(tasks.TZ)
    day = moment.date()
    name = payload.command
    response = {"allowed_user_ids": [uid for p, uid in cfg.get("user_ids", {}).items() if uid and p in active]}
    if name in {"zgjova", "erdha"}:
        request_id = "discord:" + payload.interaction_id
        if name == "erdha":
            await tasks.record_arrival(db, member, day=day, request_id=request_id)
        else:
            await record_wake(db, space, member, day.isoformat(), person, request_id)
            await db.commit()
        return {**response, "text": "U ruajt në PrimeFlow."}
    if name == "kujto":
        if not member.is_admin:
            raise HTTPException(403, "Kartën manuale të Nalës e dërgon administratori i familjes.")
        if not delivery_enabled:
            raise HTTPException(409, "Dërgimi i kujtesave është i ndalur te boti.")
        request_id = "discord-command:" + payload.interaction_id
        previous = (await db.execute(select(Event).where(Event.space_id == space.id, Event.request_id == request_id))).scalar_one_or_none()
        if previous:
            if previous.kind != "family_manual" or previous.actor_id != member.user_id:
                raise HTTPException(409, "Ky veprim është përdorur më herët.")
            return {**response, "text": "Kërkesa për kartën e Nalës është regjistruar tashmë."}
        rows = [(r, t) for r, t in await day_rows(db, space, day) if r.snapshot.get("reminder_group") == "nala" and bridge.live(r, False)]
        rows.sort(key=lambda pair: (tasks.aware(pair[0].due_at) < bridge.utcnow(), tasks.aware(pair[0].due_at)))
        if not rows:
            return {**response, "text": "Sot nuk ka kartë të hapur të Nalës me orar."}
        row, _ = rows[0]
        targets = bridge.routes(row, cfg, active)
        if not targets:
            return {**response, "text": "Karta e Nalës pret konfigurimin e destinacionit ose të llogarisë Discord."}
        for recipient, target in targets:
            key = tasks.document_hash([bridge.schedule_key(row, cfg, target), "manual", payload.interaction_id])
            prior = (await db.execute(select(Delivery).where(Delivery.occurrence_id == row.id, Delivery.schedule_key == key,
                                                          Delivery.phase == "manual", Delivery.recipient == recipient))).scalar_one_or_none()
            if prior is None:
                db.add(Delivery(occurrence_id=row.id, schedule_key=key, phase="manual", recipient=recipient,
                    scheduled_at=bridge.utcnow(), status="pending", details={"target": target, "guild_id": cfg["guild_id"],
                    "action_key": bridge.schedule_key(row, cfg, target)}))
        db.add(Event(space_id=space.id, occurrence_id=row.id, actor_id=member.user_id, request_id=request_id,
                     kind="family_manual", payload={"command": name}))
        await db.commit()
        return {**response, "text": "Karta e Nalës u vendos në radhën e dërgimit."}
    if name in {"sot", "mengjesi"}:
        mine = [r for r, _ in await day_rows(db, space, day) if person in r.snapshot["assignees"]
                or (person == "gane" and "lirza" in r.snapshot["assignees"])]
        if name == "mengjesi": mine = [r for r in mine if r.snapshot.get("reminder_group") == "morning"]
        text = "\n".join(line(r) for r in mine) or "Sot nuk ka detyra të regjistruara për ty."
    elif name == "nala":
        anchor = space.config.get("nala_rotation") or space.config.get("rotation_anchor")
        owner = tasks.rotation_owner(day, anchor) if anchor else None
        text = f"Sot Nalën e ka {active[owner][1]}." if owner in active else "Radha e Nalës ende nuk është konfiguruar."
    elif name == "ore":
        text = f"Ora te shtëpia: {moment:%d/%m/%Y · %H:%M} · Europe/Belgrade."
    elif name == "kush":
        text = "Të lidhur: " + ", ".join(active[p][1] for p in active if cfg.get("user_ids", {}).get(p)) + ".\nMesazhet e Lirzës i shkojnë Ganës."
    elif name == "vikendi":
        text = "Sot është vikend. Pastrimi i thellë bëhet një herë këtë vikend." if day.weekday() >= 5 else "Sot mjafton mirëmbajtja. Pastrimi i thellë bëhet në vikend."
    elif name == "provo":
        text = "Kartë prove. Butonat ndryshojnë vetëm këtë provë; detyrat në PrimeFlow ruhen veçmas."
    elif name in {"zeri", "dil"}:
        text = "Tingulli dëgjohet vetëm nga personat brenda kanalit zanor."
    else:
        text = "E pashë · Po ia nisi · U kry · Më duhet ndihmë.\nTe menuja: hapat dhe shtyrja 15/30/60 minuta.\n/sot · /mengjesi · /nala · /ore · /kush · /vikendi · /zgjova · /erdha · /provo · /zeri · /dil.\n/kujto është për administratorin. Biseda zanore: /kujtesa fillo dhe /kujtesa ndalo."
    return {**response, "text": text}
