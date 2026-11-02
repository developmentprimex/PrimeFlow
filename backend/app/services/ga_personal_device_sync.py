"""Kujtesa's offline protocol, isolated from company tasks, events and arrivals."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.models.ga_personal import (
    GaPersonalDevice as Device, GaPersonalDeviceOp as Operation, GaPersonalDeviceRecord as Record,
    GaPersonalEvent as Event, GaPersonalOccurrence as Occurrence, GaPersonalTemplate as Template,
    GaPersonalMember as Member,
)
from app.models.user import User
from app.schemas.ga_personal import GenerateRequest
from app.schemas.ga_personal_devices import CardRepeat, DeviceCard
from app.services import ga_personal as tasks
from app.services import ga_personal_devices as devices

CARD_ID = re.compile(r"ga_([0-9a-f]{32})_(mrika|lirza|rrita|gane|family)(?:__(\d{4}-\d{2}-\d{2}))?\Z")
DEVICE_STATUSES = {"in_progress", "needs_help", "done"}
AREAS = {"room", "bathroom", "kitchen", "school", "home", "nala", "roki", "activity", "appointment", "event"}
SPEECH = {"room": "Tidy your room", "bathroom": "Clean your bathroom", "kitchen": "Help in the kitchen",
          "school": "Get ready for school", "nala": "Time to care for Nala", "roki": "Time to care for Roki"}


def millis(value):
    return int(tasks.aware(value).timestamp() * 1000)


def card_id(template_id, owner, concrete_date=None):
    return f"ga_{template_id.hex}_{owner or 'family'}" + (f"__{concrete_date}" if concrete_date else "")


def concrete_template(definition, space=None):
    return (bool(definition.get("recurrence_anchor_date"))
            or definition.get("recurrence_interval_weeks", 1) > 1
            or definition["frequency"] in {"conditional", "school_day", "unresolved"}
            or (definition["assignment"] == "rotation" and space and space.config.get("nala_rotation"))
            or definition["assignment"] in {"first_home", "unassigned"}
            or (definition["assignment"] == "rotation" and definition["frequency"] not in {"daily", "near_daily"}))


def occurrence_owner(row):
    if row.assignment_key in {"rotation", "first_home"}:
        return row.snapshot["assignees"][0]
    return None if row.assignment_key == "shared" else row.assignment_key


def area_for(definition):
    area = definition.get("area_id", "home")
    if definition.get("reminder_group") == "nala":
        return "nala"
    if definition.get("reminder_group") == "roki":
        return "roki"
    if area in AREAS:
        return area
    if area.endswith("_bathroom"):
        return "bathroom"
    if area.endswith("_room") and area != "living_room":
        return "room"
    return "home"


def make_card(template, definition, owner, *, day=None, start=None):
    area = area_for(definition)
    start = (start if start is not None else definition.get("due_time"))
    start = start[:5] if start else None
    end = None
    if start and definition.get("estimated_minutes"):
        end = (datetime.combine(date(2000, 1, 1), time.fromisoformat(start))
               + timedelta(minutes=definition["estimated_minutes"])).strftime("%H:%M")
    return DeviceCard(id=card_id(template.id, owner, day), title=definition["title"], person_id=owner,
        start=start, end=end, steps=definition.get("steps", []),
        kind=area if area in {"nala", "roki", "activity", "appointment", "event"} else "task",
        area=area, group={"daily_upkeep": "upkeep"}.get(definition.get("reminder_group"), definition.get("reminder_group")),
        speech=definition.get("speech") or SPEECH.get(area, "Please complete your household task"),
        days=(definition.get("weekdays") or None) if definition.get("frequency") in {"weekly", "near_daily"} else None,
        weekend=definition.get("frequency") == "weekly",
        date=day or (definition.get("on_date") if definition.get("frequency") == "once" else None),
        alarm=bool(start), note=definition.get("description") or None)


async def locked_device_space(db, device):
    space = await tasks.lock_space(db, device.space_id)
    current = await db.get(Device, device.id, populate_existing=True)
    member = await devices.authorized_member(db, current) if current and not current.revoked_at else None
    if member is None:
        raise HTTPException(401, "Lidhja e pajisjes është çaktivizuar.", headers={"WWW-Authenticate": "Bearer"})
    return space, member


async def active_people(db, space_id):
    return set((await db.execute(select(Member.person_key).join(User, User.id == Member.user_id).where(
        Member.space_id == space_id, Member.active.is_(True), User.is_active.is_(True),
    ))).scalars().all())


def exported_cards(templates, occurrences, space, people):
    cards = []
    for template in templates:
        d = template.definition
        if template.archived or not d.get("enabled") or d.get("readiness") != "ready_after_setup":
            continue
        if concrete_template(d, space):
            for row in occurrences:
                if row.template_id != template.id or row.status == "cancelled":
                    continue
                owner = occurrence_owner(row)
                if owner and owner not in people:
                    continue
                start = tasks.aware(row.due_at).astimezone(tasks.TZ).strftime("%H:%M") if row.due_at else None
                card = make_card(template, row.snapshot, owner, day=row.local_date)
                card.start = start; card.alarm = bool(start); card.days = None
                cards.append(card.model_dump(mode="json"))
            continue
        if d["assignment"] == "rotation":
            anchor = space.config.get("rotation_anchor")
            if not anchor:
                continue
            for offset, owner in enumerate(["rrita", "mrika", "lirza"]):
                if owner not in people:
                    continue
                card = make_card(template, d, owner)
                card.date = date.fromisoformat(anchor) + timedelta(days=offset)
                card.repeat = CardRepeat(every=3, unit="day", days=card.days)
                cards.append(card.model_dump(mode="json"))
        else:
            if not set(d["assignees"]).issubset(people):
                continue
            owners = [None] if d.get("completion_mode") == "shared" else d["assignees"]
            for owner in owners:
                cards.append(make_card(template, d, owner).model_dump(mode="json"))
    return sorted(cards, key=lambda item: item["id"])


def record_key(*parts):
    return tasks.document_hash(list(parts))


async def get_record(db, space_id, kind, *parts):
    return (await db.execute(select(Record).where(Record.space_id == space_id, Record.kind == kind,
                                                  Record.key == record_key(*parts)))).scalar_one_or_none()


async def write_record(db, space_id, kind, key_parts, payload, op):
    row = await get_record(db, space_id, kind, *key_parts)
    if row and (row.client_at, row.op_id) >= (op.at, str(op.op_id)):
        row.updated_at = tasks.utcnow()
        return False
    if row is None:
        row = Record(space_id=space_id, kind=kind, key=record_key(*key_parts))
        db.add(row)
    row.payload, row.client_at, row.op_id, row.updated_at = payload, op.at, str(op.op_id), tasks.utcnow()
    await db.flush()
    return True


async def read_state(db, device, since=None):
    space, _member = await locked_device_space(db, device)
    cursor = tasks.utcnow()
    if since and since > cursor:
        raise HTTPException(422, "Cursor-i është në të ardhmen; rifillo pa since.")
    templates = (await db.execute(select(Template).where(Template.space_id == space.id))).scalars().all()
    occurrences = (await db.execute(select(Occurrence).where(Occurrence.space_id == space.id))).scalars().all()
    records = (await db.execute(select(Record).where(Record.space_id == space.id))).scalars().all()
    changed = [r for r in records if since is None or tasks.aware(r.updated_at) >= since]
    statuses = {(r.payload["period"], r.payload["task_id"]): r.payload for r in changed if r.kind == "status"}
    by_id = {t.id: t for t in templates}
    # Include changes made in PrimeFlow itself, not just operations from tablets.
    events = (await db.execute(select(Event).where(Event.space_id == space.id,
        Event.kind.in_(["status_changed", "device_status"])).order_by(Event.created_at.desc(), Event.id.desc()))).scalars().all()
    latest = {}
    for event in events:
        if event.occurrence_id not in latest:
            latest[event.occurrence_id] = event
    people = await active_people(db, space.id)
    for row in occurrences:
        if row.status not in DEVICE_STATUSES or row.template_id not in by_id:
            continue
        event = latest.get(row.id)
        template = by_id[row.template_id]
        d = template.definition
        owner = occurrence_owner(row)
        identity = card_id(template.id, owner, row.local_date if concrete_template(d, space) else None)
        period = (date.fromisoformat(row.period_key[8:]) + timedelta(days=5)).isoformat() if row.period_key.startswith("weekend:") else row.local_date
        if since and (not event or tasks.aware(event.created_at) < since) and (period, identity) not in statuses:
            continue
        timestamp = event.payload.get("device_at", millis(event.created_at)) if event else millis(row.completed_at or cursor)
        value = {"task_id": identity, "period": period, "status": row.status,
                 "step": len(row.snapshot.get("steps", [])) if row.status == "done" else (event.payload.get("step", 0) if event else 0), "at": timestamp}
        old = statuses.get((period, identity))
        if old is None or old["at"] <= timestamp:
            statuses[(period, identity)] = value
    return {"cursor": cursor.isoformat().replace("+00:00", "Z"),
        # Sending tasks always replaces the tablet's complete base list, including removals.
        "tasks": exported_cards(templates, occurrences, space, people),
        "events": [r.payload for r in changed if r.kind == "event"],
        "statuses": sorted(statuses.values(), key=lambda item: (item["period"], item["task_id"])),
        "arrivals": [r.payload for r in changed if r.kind == "arrival"]}


async def status_occurrence(db, member, op):
    match = CARD_ID.fullmatch(op.task_id)
    if not match:
        return None
    template_id, owner, concrete_date = match.groups()
    template = (await db.execute(select(Template).where(Template.id == uuid.UUID(hex=template_id),
                                                       Template.space_id == member.space_id))).scalar_one_or_none()
    if template is None:
        raise HTTPException(422, "Detyra nuk i përket kësaj hapësire.")
    d = template.definition
    if d["frequency"] == "weekly" and op.period.weekday() != 5:
        raise HTTPException(422, "Periudha e vikendit duhet të jetë e shtuna.")
    period = tasks.period_key(d, op.period)
    assigned = d["assignment"] if d["assignment"] != "fixed" else ("shared" if owner == "family" else owner)
    row = (await db.execute(select(Occurrence).where(Occurrence.space_id == member.space_id,
        Occurrence.template_id == template.id, Occurrence.period_key == period, Occurrence.assignment_key == assigned))).scalar_one_or_none()
    if row is None:
        if d["frequency"] == "weekly":
            day = op.period + timedelta(days=min(d["weekdays"]) - 5)
        else:
            day = op.period
        if concrete_date or template.archived or not tasks.scheduled(d, day):
            raise HTTPException(422, "Detyra nuk është e konfirmuar për këtë periudhë.")
        await tasks.generate(db, member, GenerateRequest(day=day), commit=False)
        row = (await db.execute(select(Occurrence).where(Occurrence.space_id == member.space_id,
            Occurrence.template_id == template.id, Occurrence.period_key == period, Occurrence.assignment_key == assigned))).scalar_one_or_none()
    if row is None or (concrete_date and concrete_date != row.local_date) or occurrence_owner(row) != (None if owner == "family" else owner):
        raise HTTPException(422, "Përgjegjësi ose periudha e detyrës nuk përputhet.")
    return row


async def resolve_status_identity(db, member, op):
    if CARD_ID.fullmatch(op.task_id) or await get_record(db, member.space_id, "event", op.task_id):
        return op
    # Older Kujtesa queues use the imported dataset ID instead of the downloaded
    # card ID. Resolve only explicit source identities in this family's space.
    sources = {op.task_id}
    sources.update(new for new, old in tasks.V2_SOURCE_ALIASES.items() if old == op.task_id)
    sources.update(old for new, old in tasks.V2_SOURCE_ALIASES.items() if new == op.task_id)
    templates = (await db.execute(select(Template).where(
        Template.space_id == member.space_id, Template.source_id.in_(sources),
    ))).scalars().all()
    template = next((row for row in templates if row.source_id == op.task_id), None)
    if template is None:
        if len(templates) != 1:
            return op
        template = templates[0]
    space = await tasks.lock_space(db, member.space_id)
    occurrences = (await db.execute(select(Occurrence).where(
        Occurrence.space_id == member.space_id, Occurrence.template_id == template.id,
    ))).scalars().all()
    cards = exported_cards([template], occurrences, space, await active_people(db, member.space_id))
    if concrete_template(template.definition, space):
        cards = [card for card in cards if card["date"] == op.period.isoformat()]
    elif template.definition["assignment"] == "rotation":
        anchor = space.config.get("rotation_anchor")
        owner = tasks.rotation_owner(op.period, anchor) if anchor else None
        cards = [card for card in cards if card["person_id"] == owner]
    if len(cards) != 1:
        raise HTTPException(422, f"ID lokale '{op.task_id}' nuk ka një detyrë të vetme të konfirmuar për {op.period}. Përdor ID nga device/state.")
    return op.model_copy(update={"task_id": cards[0]["id"]})


async def apply_status(db, device, member, op):
    op = await resolve_status_identity(db, member, op)
    old = await get_record(db, device.space_id, "status", op.period.isoformat(), op.task_id)
    if old and (old.client_at, old.op_id) >= (op.at, str(op.op_id)):
        # Echo the canonical value after an offline loser is acknowledged.
        old.updated_at = tasks.utcnow()
        return
    row = await status_occurrence(db, member, op)
    if row is None:
        event = await get_record(db, device.space_id, "event", op.task_id)
        if event is None:
            raise HTTPException(422, f"Detyra ose eventi nuk u gjet: task_id='{op.task_id}', op_id='{op.op_id}'. Shkarko detyrat nga device/state; për event lokal dërgo event_upsert para statusit.")
    else:
        latest = (await db.execute(select(Event).where(Event.space_id == device.space_id,
            Event.occurrence_id == row.id, Event.kind.in_(["status_changed", "device_status"]))
            .order_by(Event.created_at.desc(), Event.id.desc()).limit(1))).scalar_one_or_none()
        if latest and latest.payload.get("device_at", millis(latest.created_at)) > op.at:
            timestamp = latest.payload.get("device_at", millis(latest.created_at))
            if row.status in DEVICE_STATUSES:
                canonical = {"task_id": op.task_id, "period": op.period.isoformat(), "status": row.status,
                    "step": len(row.snapshot.get("steps", [])) if row.status == "done" else latest.payload.get("step", 0), "at": timestamp}
                if old is None:
                    old = Record(space_id=device.space_id, kind="status", key=record_key(op.period.isoformat(), op.task_id))
                    db.add(old)
                old.payload, old.client_at, old.op_id, old.updated_at = canonical, timestamp, str(latest.id), tasks.utcnow()
            return
        if row.status == "cancelled":
            raise HTTPException(409, "Kjo kryerje është anuluar në PrimeFlow.")
        before = row.status
        if row.status != op.status:
            # The tablet protocol explicitly resolves its three statuses by at.
            # Normalize transitions that the browser's more restrictive UI lacks.
            if op.status not in tasks.TRANSITIONS[row.status]:
                row.status = "pending"
            await tasks.change_status(db, row, op.status)
        db.add(Event(space_id=device.space_id, occurrence_id=row.id, actor_id=member.user_id,
            request_id="device:" + str(op.op_id), kind="device_status",
            payload={"from": before, "to": row.status, "device_id": device.device_id,
                     "device_at": op.at, "step": op.step}))
    payload = {"task_id": op.task_id, "period": op.period.isoformat(), "status": op.status,
               "step": op.step, "at": op.at}
    if row is not None and op.status == "done":
        payload["step"] = len(row.snapshot.get("steps", []))
    elif row is None and op.status == "done":
        payload["step"] = len(event.payload.get("steps", []))
    await write_record(db, device.space_id, "status", (payload["period"], op.task_id), payload, op)


async def apply_ops(db, device, payload):
    if str(payload.device_id) != device.device_id:
        raise HTTPException(403, "device_id nuk përputhet me X-Device-Id.")
    space, member = await locked_device_space(db, device)
    # Offline queues may contain a status before its event's upsert. Establish
    # event identities first, keeping mutation order and the whole batch atomic.
    for op in sorted(payload.ops, key=lambda item: item.type == "status"):
        data = op.model_dump(mode="json")
        previous = (await db.execute(select(Operation).where(Operation.space_id == space.id,
                                                             Operation.op_id == op.op_id))).scalar_one_or_none()
        if previous:
            if previous.payload != data:
                raise HTTPException(409, "op_id është përdorur për një veprim tjetër.")
            if op.type == "status":
                try:
                    status_op = await resolve_status_identity(db, member, op)
                except HTTPException as exc:
                    if exc.status_code != 422:
                        raise
                    # A committed retry stays acknowledged even if its legacy
                    # identity is no longer exported (for example, archived).
                    status_op = op
                record = await get_record(db, space.id, "status", op.period.isoformat(), status_op.task_id)
                if record is None:
                    record = (await db.execute(select(Record).where(
                        Record.space_id == space.id, Record.kind == "status", Record.op_id == str(op.op_id),
                    ))).scalar_one_or_none()
            elif op.type == "arrival":
                record = await get_record(db, space.id, "arrival", op.day.isoformat(), op.person_id)
            else:
                record = await get_record(db, space.id, "event", op.event.id if op.type == "event_upsert" else op.id)
            if record:
                # A tablet may have skipped a downloaded value while this op
                # was pending. Acknowledge the retry and resend current state.
                record.updated_at = tasks.utcnow()
            continue
        if op.type == "status":
            await apply_status(db, device, member, op)
        elif op.type == "arrival":
            await write_record(db, space.id, "arrival", (op.day.isoformat(), op.person_id),
                {"person_id": op.person_id, "day": op.day.isoformat(), "at": op.at}, op)
            await tasks.record_arrival(db, member, day=op.day, person=op.person_id,
                                       request_id="arrival:" + str(op.op_id), commit=False)
        elif op.type == "event_upsert":
            if CARD_ID.fullmatch(op.event.id):
                raise HTTPException(422, "ID e eventit është e rezervuar për detyrat e GA PERSONAL.")
            await write_record(db, space.id, "event", (op.event.id,),
                {**op.event.model_dump(mode="json"), "deleted": False, "at": op.at}, op)
        else:
            if CARD_ID.fullmatch(op.id):
                raise HTTPException(422, "Detyrat bazë ndryshohen te GA PERSONAL.")
            await write_record(db, space.id, "event", (op.id,), {"id": op.id, "deleted": True, "at": op.at}, op)
        db.add(Operation(space_id=space.id, device_id=device.id, op_id=op.op_id, payload=data))
        await db.flush()
    await db.commit()
    return {"accepted": [str(op.op_id) for op in payload.ops]}
