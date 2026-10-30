from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, update

from app.models.ga_personal import (
    GaPersonalDelivery as Delivery, GaPersonalEvent as Event, GaPersonalImport as ImportRun,
    GaPersonalMember as Member, GaPersonalOccurrence as Occurrence,
    GaPersonalSpace as Space, GaPersonalTemplate as Template,
    GaPersonalDiscordDelivery as DiscordDelivery,
)
from app.schemas.ga_personal import TemplateDefinition
from app.models.user import User

TZ = ZoneInfo("Europe/Belgrade")
PEOPLE = {"mrika", "lirza", "rrita", "gane"}
TRANSITIONS = {
    "pending": {"acknowledged", "in_progress", "needs_help", "rescheduled", "done", "cancelled"},
    "acknowledged": {"in_progress", "needs_help", "rescheduled", "done", "cancelled"},
    "in_progress": {"needs_help", "rescheduled", "done", "cancelled"},
    "needs_help": {"in_progress", "rescheduled", "cancelled"},
    "rescheduled": {"pending", "acknowledged", "in_progress", "done", "needs_help", "cancelled"}, "done": set(), "cancelled": set(),
}


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def document_hash(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def rotation_owner(day: date, anchor: str | dict):
    if isinstance(anchor, dict):
        if day.weekday() != 6:
            return anchor["weekday_owners_iso"].get(str(day.weekday()))
        cycle = anchor["sunday_cycle"]
        start = date.fromisoformat(cycle["anchor_date"])
        if day < start:
            return None
        return cycle["order"][((day - start).days // 7) % len(cycle["order"])]
    start = date.fromisoformat(anchor)
    if day < start:
        return None
    return ["rrita", "mrika", "lirza"][(day - start).days % 3]


def period_key(definition, day):
    if definition["frequency"] == "weekly":
        monday = day - timedelta(days=day.weekday())
        return "weekend:" + monday.isoformat()
    return day.isoformat()


def template_out(row, member=None):
    return {"id": str(row.id), "definition": row.definition, "version": row.version,
            "archived": row.archived, "source_id": row.source_id,
            "can_manage": may_manage(member, row.definition, row.created_by) if member else False}


def occurrence_out(row, *, can_edit=False):
    return {"id": str(row.id), "template_id": str(row.template_id), "period_key": row.period_key,
            "local_date": row.local_date, "due_at": aware(row.due_at).isoformat() if row.due_at else None,
            "snapshot": row.snapshot, "status": row.status, "version": row.version,
            "completed_at": aware(row.completed_at).isoformat() if row.completed_at else None,
            "can_edit": can_edit and row.status not in {"done", "cancelled"}}


async def lock_space(db, space_id):
    # All mutating paths share this lock; generation, actions and imports serialize
    # for this small family space, including across API/worker processes.
    return (await db.execute(select(Space).where(Space.id == space_id).with_for_update().execution_options(populate_existing=True))).scalar_one()


async def lock_member_space(db, member, *, need_admin=False):
    space = await lock_space(db, member.space_id)
    current = (await db.execute(select(Member).join(User, User.id == Member.user_id).where(
        Member.id == member.id, Member.user_id == member.user_id, Member.active.is_(True), User.is_active.is_(True),
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if current is None or (need_admin and not current.is_admin):
        raise HTTPException(403, "Autorizimi i modulit ka ndryshuar.")
    return space


def may_manage(member, definition, created_by):
    return member.is_admin or (
        created_by == member.user_id and definition["assignment"] == "fixed"
        and definition["assignees"] == [member.person_key]
    )


def may_edit_occurrence(member, template, row):
    return may_manage(member, template.definition, template.created_by) and (
        member.is_admin or row.snapshot["assignees"] == [member.person_key]
    )


async def checked_definition(db, member, definition):
    data = definition.model_dump(mode="json")
    allowed = set((await db.execute(select(Member.person_key).join(User, User.id == Member.user_id).where(
        Member.space_id == member.space_id, Member.active.is_(True), User.is_active.is_(True),
    ))).scalars().all())
    if not set(data["assignees"]).issubset(allowed):
        raise HTTPException(422, "Përgjegjësi nuk ka anëtarësi aktive.")
    if not member.is_admin and (data["assignment"] != "fixed" or data["assignees"] != [member.person_key]):
        raise HTTPException(403, "Caktimi te persona të tjerë kërkon administratorin e modulit.")
    return data


async def get_template(db, space_id, template_id):
    row = (await db.execute(select(Template).where(
        Template.id == template_id, Template.space_id == space_id,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Modeli nuk u gjet.")
    return row


async def save_template(db, member, payload, template_id=None):
    await lock_member_space(db, member)
    data = await checked_definition(db, member, payload.definition)
    if template_id:
        row = await get_template(db, member.space_id, template_id)
        if not may_manage(member, row.definition, row.created_by):
            raise HTTPException(403, "Nuk ke leje ta ndryshosh këtë model.")
        if row.version != payload.expected_version:
            raise HTTPException(409, "Modeli ndryshoi; rifreskoje.")
        row.definition, row.version, row.import_hash = data, row.version + 1, None
    else:
        row = Template(space_id=member.space_id, created_by=member.user_id, definition=data)
        db.add(row)
    await db.flush()
    existing_once = (await db.execute(select(Occurrence.id).where(Occurrence.template_id == row.id).limit(1))).scalar_one_or_none() if data["frequency"] == "once" else None
    if existing_once is None and data["enabled"] and data["frequency"] == "once":
        owners = [data["assignees"]] if data["completion_mode"] == "shared" else [[p] for p in data["assignees"]]
        for assigned in owners:
            db.add(Occurrence(space_id=member.space_id, template_id=row.id, period_key=data["on_date"],
                assignment_key="shared" if data["completion_mode"] == "shared" else assigned[0], local_date=data["on_date"],
                due_at=datetime.combine(date.fromisoformat(data["on_date"]), time.fromisoformat(data["due_time"]), TZ) if data["due_time"] else None,
                snapshot={**data, "assignees": assigned, "template_version": row.version}))
    db.add(Event(space_id=member.space_id, actor_id=member.user_id, request_id=str(uuid.uuid4()),
                 kind="template_updated" if template_id else "template_created",
                 payload={"template_id": str(row.id), "version": row.version}))
    await db.commit()
    return template_out(row, member)


async def archive_template(db, member, template_id, payload):
    await lock_member_space(db, member)
    row = await get_template(db, member.space_id, template_id)
    if not may_manage(member, row.definition, row.created_by):
        raise HTTPException(403, "Nuk ke leje për këtë model.")
    if row.version != payload.expected_version:
        raise HTTPException(409, "Modeli ndryshoi; rifreskoje.")
    row.archived, row.version = payload.archived, row.version + 1
    if payload.archived:
        ids = select(Occurrence.id).where(Occurrence.template_id == row.id, Occurrence.space_id == member.space_id)
        await db.execute(update(Delivery).where(Delivery.occurrence_id.in_(ids), Delivery.status == "pending").values(status="cancelled"))
        await cancel_discord(db, ids)
    db.add(Event(space_id=member.space_id, actor_id=member.user_id, request_id=str(uuid.uuid4()),
                 kind="template_archived" if payload.archived else "template_restored", payload={"template_id": str(row.id)}))
    await db.commit()
    return template_out(row, member)


def scheduled(definition, day, *, school_day=False, condition=False):
    # A known recurrence can create an untimed task. Missing times never become
    # invented deadlines or an authorization to send reminders.
    if not definition["enabled"] or definition["readiness"] != "ready_after_setup":
        return False
    anchor = definition.get("recurrence_anchor_date")
    interval = definition.get("recurrence_interval_weeks", 1)
    if anchor:
        start = date.fromisoformat(anchor)
        if day < start:
            return False
        start_monday = start - timedelta(days=start.weekday())
        day_monday = day - timedelta(days=day.weekday())
        if ((day_monday - start_monday).days // 7) % interval:
            return False
    elif interval > 1:
        return False
    frequency = definition["frequency"]
    if frequency == "once":
        return definition["on_date"] == day.isoformat()
    if frequency == "daily":
        return True
    if frequency == "weekly":
        return day.weekday() in definition["weekdays"] and day.weekday() in (5, 6)
    if frequency == "school_day":
        return school_day and day.weekday() in (definition["weekdays"] or list(range(5)))
    if frequency == "near_daily":
        return day.weekday() in definition["weekdays"]
    return frequency == "conditional" and condition


async def generate(db, member, payload, *, automatic=False, commit=True):
    if not member.is_admin:
        raise HTTPException(403, "Gjenerimi i orarit kërkon administratorin e modulit.")
    space = await lock_member_space(db, member, need_admin=True)
    templates = (await db.execute(select(Template).where(
        Template.space_id == member.space_id, Template.archived.is_(False),
    ).order_by(Template.id))).scalars().all()
    periods = {payload.day.isoformat(), period_key({"frequency": "weekly"}, payload.day)}
    existing = (await db.execute(select(Occurrence).where(Occurrence.space_id == member.space_id, Occurrence.period_key.in_(periods)))).scalars().all()
    identities = {(o.template_id, o.period_key, o.assignment_key) for o in existing}
    # An explicit reassignment keeps the original occurrence identity while
    # covering its new owner too, even if the template is changed for the future.
    identities.update((o.template_id, o.period_key, p) for o in existing
                      if o.snapshot.get("assignment_overridden") for p in o.snapshot["assignees"])
    once_templates = [t.id for t in templates if t.definition["frequency"] == "once"]
    existing_once = set((await db.execute(select(Occurrence.template_id).where(
        Occurrence.space_id == member.space_id, Occurrence.template_id.in_(once_templates),
    ))).scalars().all()) if once_templates else set()
    coverage = {(o.period_key, p, o.snapshot.get("coverage_key")) for o in existing
                if o.status != "cancelled" for p in o.snapshot["assignees"] if o.snapshot.get("coverage_key")}
    members = set((await db.execute(select(Member.person_key).join(User, User.id == Member.user_id).where(Member.space_id == member.space_id, Member.active.is_(True), User.is_active.is_(True)))).scalars().all())
    count, skipped = 0, []
    for row in templates:
        d = row.definition
        if d["frequency"] == "once" and row.id in existing_once:
            continue
        if not scheduled(d, payload.day, school_day=payload.school_day, condition=row.id in payload.conditions):
            continue
        owners = d["assignees"]
        if d["assignment"] == "rotation":
            anchor = space.config.get("nala_rotation") or space.config.get("rotation_anchor")
            owner = rotation_owner(payload.day, anchor) if anchor else None
            owners = [owner] if owner else []
        elif d["assignment"] == "first_home":
            owners = [payload.first_home] if payload.first_home else []
        if not owners or not set(owners).issubset(members):
            skipped.append({"template_id": str(row.id), "reason": "Përgjegjësi ose rotacioni nuk është konfiguruar."})
            continue
        period = period_key(d, payload.day)
        assignments = [owners] if d["completion_mode"] == "shared" else [[p] for p in owners]
        for assigned in assignments:
            key = "shared" if d["completion_mode"] == "shared" else assigned[0]
            # Rotation/first-home represent a single duty, even if reassigned.
            if d["assignment"] != "fixed":
                key = d["assignment"]
            identity = (row.id, period, key)
            if identity in identities:
                continue
            if d.get("coverage_key") and any((period, p, d["coverage_key"]) in coverage for p in assigned):
                skipped.append({"template_id": str(row.id), "reason": "Kjo punë është mbuluar në këtë periudhë."})
                continue
            due = datetime.combine(payload.day, time.fromisoformat(d["due_time"]), TZ).astimezone(timezone.utc) if d["due_time"] else None
            occurrence = Occurrence(space_id=member.space_id, template_id=row.id, period_key=period,
                assignment_key=key, local_date=payload.day.isoformat(), due_at=due,
                snapshot={**d, "assignees": assigned, "template_version": row.version})
            db.add(occurrence)
            identities.add(identity)
            coverage.update((period, p, d.get("coverage_key")) for p in assigned if d.get("coverage_key"))
            count += 1
    if count or not automatic:
        db.add(Event(space_id=member.space_id, actor_id=member.user_id, request_id=str(uuid.uuid4()),
                     kind="auto_generated" if automatic else "generated",
                     payload={"day": payload.day.isoformat(), "created": count, "automatic": automatic}))
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {"created": count, "skipped": skipped}


async def cancel_discord(db, occurrence_ids):
    await db.execute(update(DiscordDelivery).where(DiscordDelivery.occurrence_id.in_(occurrence_ids),
        DiscordDelivery.status.in_(["pending", "claimed"])).values(status="cancelled"))


async def record_arrival(db, member, *, day, request_id, person=None, commit=True):
    await lock_member_space(db, member)
    person = person or member.person_key
    if person not in PEOPLE:
        raise HTTPException(422, "Personi nuk është i vlefshëm.")
    previous = (await db.execute(select(Event).where(
        Event.space_id == member.space_id, Event.request_id == request_id))).scalar_one_or_none()
    if previous and (previous.kind != "arrived" or previous.actor_id != member.user_id
                     or previous.payload != {"day": day.isoformat(), "person_key": person}):
        raise HTTPException(409, "Ky identifikues është përdorur për një veprim tjetër.")
    first = (await db.execute(select(Event).where(
        Event.space_id == member.space_id, Event.kind == "arrived",
        Event.payload["day"].as_string() == day.isoformat(),
    ).order_by(Event.created_at, Event.id).limit(1))).scalar_one_or_none()
    first_person = first.payload["person_key"] if first else person
    if not previous:
        db.add(Event(space_id=member.space_id, actor_id=member.user_id, request_id=request_id,
                     kind="arrived", payload={"day": day.isoformat(), "person_key": person}))
        await db.flush()
    administrator = (await db.execute(select(Member).join(User, User.id == Member.user_id).where(
        Member.space_id == member.space_id, Member.active.is_(True), Member.is_admin.is_(True),
        User.is_active.is_(True),
    ).order_by(Member.id).limit(1))).scalar_one_or_none()
    created = 0
    if administrator:
        templates = (await db.execute(select(Template).where(
            Template.space_id == member.space_id, Template.archived.is_(False)))).scalars().all()
        # An arrival confirms this condition only; other unresolved conditions
        # and school days stay untouched, as do inactive first-home templates.
        conditions = [t.id for t in templates if t.definition["assignment"] == "first_home"]
        from app.schemas.ga_personal import GenerateRequest
        result = await generate(db, administrator, GenerateRequest(
            day=day, first_home=first_person, conditions=conditions), automatic=True, commit=False)
        created = result["created"]
    if commit:
        await db.commit()
    return {"day": day.isoformat(), "first_home": first_person, "created": created}


async def change_status(db, row, status, reschedule_at=None):
    if status not in TRANSITIONS[row.status]:
        raise HTTPException(409, "Ky ndryshim gjendjeje nuk lejohet.")
    if status == "rescheduled":
        if not reschedule_at or reschedule_at <= utcnow():
            raise HTTPException(422, "Zgjidh një orë të ardhshme.")
        row.due_at = reschedule_at
        row.local_date = reschedule_at.astimezone(TZ).date().isoformat()
        row.snapshot = {**row.snapshot, "discord_schedule_revision": row.snapshot.get("discord_schedule_revision", 0) + 1}
    row.status, row.version = status, row.version + 1
    row.completed_at = utcnow() if status == "done" else None
    if status in {"done", "cancelled", "needs_help", "rescheduled"}:
        await db.execute(update(Delivery).where(Delivery.occurrence_id == row.id, Delivery.status == "pending").values(status="cancelled"))
        await cancel_discord(db, [row.id])


async def act(db, member, occurrence_id, payload):
    await lock_member_space(db, member)
    row = (await db.execute(select(Occurrence).where(Occurrence.id == occurrence_id, Occurrence.space_id == member.space_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Detyra nuk u gjet.")
    if member.person_key not in row.snapshot["assignees"] and not (member.is_admin and member.person_key == "gane"):
        raise HTTPException(403, "Vetëm përgjegjësi ose i rrituri i autorizuar mund ta ndryshojë detyrën.")
    prior = (await db.execute(select(Event).where(Event.space_id == member.space_id, Event.request_id == str(payload.request_id)))).scalar_one_or_none()
    if prior:
        if prior.actor_id != member.user_id or prior.occurrence_id != row.id or prior.payload.get("action") != payload.model_dump(mode="json", exclude={"request_id"}):
            raise HTTPException(409, "Ky identifikues është përdorur për një veprim tjetër.")
        return occurrence_out(row)
    if row.version != payload.expected_version:
        raise HTTPException(409, "Detyra ndryshoi ndërkohë. Rifreskoje.")
    old = row.status
    await change_status(db, row, payload.status, payload.reschedule_at)
    db.add(Event(space_id=member.space_id, occurrence_id=row.id, actor_id=member.user_id,
        request_id=str(payload.request_id), kind="status_changed", payload={"from": old, "to": row.status,
            "completion_method": "self_report" if row.status == "done" else None,
            "action": payload.model_dump(mode="json", exclude={"request_id"})}))
    await db.commit()
    return occurrence_out(row)


async def edit_occurrence(db, member, occurrence_id, payload):
    await lock_member_space(db, member)
    row = (await db.execute(select(Occurrence).where(
        Occurrence.id == occurrence_id, Occurrence.space_id == member.space_id,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Detyra nuk u gjet.")
    template = await get_template(db, member.space_id, row.template_id)
    if not may_edit_occurrence(member, template, row):
        raise HTTPException(403, "Ndryshimi i orës ose përgjegjësit kërkon leje për këtë detyrë.")
    action = payload.model_dump(mode="json", exclude={"request_id"})
    previous = (await db.execute(select(Event).where(
        Event.space_id == member.space_id, Event.request_id == str(payload.request_id),
    ))).scalar_one_or_none()
    if previous:
        if (previous.actor_id != member.user_id or previous.occurrence_id != row.id
            or previous.kind != "occurrence_updated" or previous.payload.get("action") != action):
            raise HTTPException(409, "Ky identifikues është përdorur për një veprim tjetër.")
        return occurrence_out(row, can_edit=True)
    if row.version != payload.expected_version:
        raise HTTPException(409, "Detyra ndryshoi ndërkohë. Mbylle formularin dhe hape përsëri.")
    if row.status in {"done", "cancelled"}:
        raise HTTPException(409, "Detyra e përfunduar mbetet në historik; ndrysho përsëritjen për të ardhmen.")
    if row.snapshot["completion_mode"] == "individual" and len(payload.assignees) != 1:
        raise HTTPException(422, "Një kryerje individuale ka një përgjegjës.")
    active = set((await db.execute(select(Member.person_key).join(User, User.id == Member.user_id).where(
        Member.space_id == member.space_id, Member.active.is_(True), User.is_active.is_(True),
    ))).scalars().all())
    if not set(payload.assignees).issubset(active):
        raise HTTPException(422, "Përgjegjësi nuk ka anëtarësi aktive.")
    if not member.is_admin and payload.assignees != [member.person_key]:
        raise HTTPException(403, "Caktimi te persona të tjerë kërkon administratorin e modulit.")
    peers = (await db.execute(select(Occurrence).where(
        Occurrence.space_id == member.space_id, Occurrence.template_id == row.template_id,
        Occurrence.period_key == row.period_key, Occurrence.id != row.id, Occurrence.status != "cancelled",
    ))).scalars().all()
    if any(set(payload.assignees).intersection(p.snapshot["assignees"]) for p in peers):
        raise HTTPException(409, "Ky person e ka tashmë këtë detyrë në këtë periudhë.")
    due = None
    if payload.due_time:
        local_due = datetime.combine(payload.local_date, payload.due_time, TZ)
        due = local_due.astimezone(timezone.utc)
        if due.astimezone(TZ).replace(tzinfo=None) != local_due.replace(tzinfo=None):
            raise HTTPException(422, "Kjo orë nuk ekziston në datën e zgjedhur për shkak të ndryshimit të orës.")
    before = {"local_date": row.local_date, "due_at": aware(row.due_at).isoformat() if row.due_at else None,
              "assignees": row.snapshot["assignees"]}
    schedule_changed = (row.local_date != payload.local_date.isoformat()
        or (aware(row.due_at) if row.due_at else None) != due
        or set(row.snapshot["assignees"]) != set(payload.assignees)
        or (payload.discord_destination is not None and row.snapshot.get("discord_destination", "dm") != payload.discord_destination))
    if payload.apply_to_future:
        if template.archived or template.version != payload.expected_template_version:
            raise HTTPException(409, "Përsëritja ndryshoi ose është arkivuar. Rifreskoje para ruajtjes.")
        if template.definition["assignment"] != "fixed":
            raise HTTPException(422, "Për rotacionin ndrysho këtë kryerje; rregullat e ardhshme ndryshohen te Përsëritjet.")
        replaced = set(row.snapshot["assignees"])
        if row.assignment_key in PEOPLE:
            replaced.add(row.assignment_key)
        remaining = [p for p in template.definition["assignees"] if p not in replaced] if row.snapshot["completion_mode"] == "individual" else []
        owners = list(dict.fromkeys(remaining + payload.assignees))
        data = {**template.definition, "assignees": owners,
                "due_time": payload.due_time.isoformat() if payload.due_time else None}
        if payload.discord_destination is not None:
            data["discord_destination"] = payload.discord_destination
        if data["frequency"] == "once":
            data["on_date"] = payload.local_date.isoformat()
        from pydantic import ValidationError
        try:
            data = await checked_definition(db, member, TemplateDefinition.model_validate(data))
        except ValidationError as exc:
            raise HTTPException(422, "Kontrollo datën, orën dhe përgjegjësit e përsëritjes.") from exc
        template.definition, template.version, template.import_hash = data, template.version + 1, None
    row.local_date, row.due_at = payload.local_date.isoformat(), due
    row.snapshot = {**row.snapshot, "assignees": payload.assignees,
                    "due_time": payload.due_time.isoformat() if payload.due_time else None,
                    "assignment_overridden": True, "schedule_overridden": True}
    if payload.discord_destination is not None:
        row.snapshot = {**row.snapshot, "discord_destination": payload.discord_destination}
    if schedule_changed:
        row.snapshot = {**row.snapshot, "discord_schedule_revision": row.snapshot.get("discord_schedule_revision", 0) + 1}
    row.version += 1
    await db.execute(update(Delivery).where(Delivery.occurrence_id == row.id, Delivery.status == "pending").values(status="cancelled"))
    if schedule_changed:
        await cancel_discord(db, [row.id])
    db.add(Event(space_id=member.space_id, occurrence_id=row.id, actor_id=member.user_id,
        request_id=str(payload.request_id), kind="occurrence_updated", payload={"before": before,
            "after": {"local_date": row.local_date, "due_at": due.isoformat() if due else None, "assignees": payload.assignees},
            "action": action, "template_id": str(template.id), "template_version": template.version}))
    await db.commit()
    return occurrence_out(row, can_edit=True)


def validate_dataset(dataset):
    try:
        return _validate_dataset(dataset)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "Struktura e dataset-it nuk është e vlefshme.") from exc


def _validate_dataset(dataset):
    if dataset.get("format") != "mira.ga_personal.dataset" or dataset.get("format_version") not in (1, 2):
        raise HTTPException(422, "Formati i dataset-it nuk mbështetet.")
    if dataset.get("module", {}).get("timezone") != "Europe/Belgrade":
        raise HTTPException(422, "Zona kohore duhet të jetë Europe/Belgrade.")
    people = dataset.get("people", [])
    if len(people) != 4 or {p.get("id") for p in people} != PEOPLE:
        raise HTTPException(422, "Dataset-i duhet të përmbajë katër personat e familjes.")
    # Identity comes exclusively from verified memberships, never imported IDs.
    if any(p.get("primeflow_user_id") or p.get("discord_user_id") for p in people):
        raise HTTPException(422, "Identitetet lidhen në konfigurim, jo nga dataset-i.")
    templates = dataset.get("task_templates", [])
    if not 1 <= len(templates) <= 500 or len({t.get("id") for t in templates}) != len(templates):
        raise HTTPException(422, "Modelet mungojnë ose kanë ID të përsëritura.")
    areas = {a.get("id") for a in dataset.get("areas", [])}
    parsed = []
    for t in templates:
        if not isinstance(t.get("id"), str) or not 1 <= len(t["id"]) <= 100 or t.get("area_id") not in areas:
            raise HTTPException(422, "Referencë e pavlefshme e modelit/hapësirës.")
        try:
            data = TemplateDefinition(
                title=t["title"], short_code=t.get("short_code"), recurrence_label=t.get("recurrence_label"),
                description=t.get("notes") or "", area_id=t["area_id"],
                completion_definition=t.get("completion_definition") or "Kryerja konfirmohet nga përgjegjësi.",
                schedule_hints=[{"trigger_type": r["trigger_type"], "start_time": r.get("start_time"),
                    "end_time": r.get("end_time"), "notes": r.get("notes") or "",
                    "weekdays": dataset_weekdays(r.get("weekdays")),
                    "suggested_start_time": r.get("suggested_start_time"),
                    "suggested_end_time": r.get("suggested_end_time")} for r in t.get("schedule_rules", [])],
                assignment=t["assignment"], assignees=[t["person_id"]] if t.get("person_id") else [],
                recurrence_interval_weeks=t.get("recurrence_interval_weeks", 1),
                recurrence_anchor_date=t.get("recurrence_anchor_date"),
                frequency=t["frequency"], steps=[s["instruction"] for s in sorted(t["steps"], key=lambda x: x["position"])],
                reminder_group=t["details"]["reminder_group"], readiness=t["readiness"],
                rotation_id=t.get("rotation_id"), enabled=False,
                estimated_minutes=t.get("estimated_duration_minutes"),
                weekdays=sorted({d for r in t.get("schedule_rules", []) for d in dataset_weekdays(r.get("weekdays"))}),
                coverage_key=(t["area_id"] + ":normal") if t["id"].endswith(("_morning_room", "_room", "_room_daily")) else None,
            ).model_dump(mode="json")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "Model i pavlefshëm në dataset.") from exc
        parsed.append((t["id"], data))
    rotation = next((r for r in dataset.get("rotations", []) if r.get("id") == "nala"), None)
    expected_order = ["lirza", "rrita", "mrika"] if dataset["format_version"] == 2 else ["rrita", "mrika", "lirza"]
    if not rotation or [m.get("person_id") for m in sorted(rotation["members"], key=lambda m: m["position"])] != expected_order:
        raise HTTPException(422, "Rotacioni Nala duhet të ruajë tre anëtaret dhe rendin e tyre.")
    if dataset["format_version"] == 2:
        cycle = rotation["sunday_cycle"]
        if (rotation.get("kind") != "weekday_fixed_sunday_cycle"
            or rotation.get("timezone") != "Europe/Belgrade"
            or rotation["weekday_owners_iso"] != dict(zip(map(str, range(6)), ["rrita", "mrika", "lirza"] * 2))
            or cycle["order"] != expected_order
            or date.fromisoformat(cycle["anchor_date"]).weekday() != 6):
            raise HTTPException(422, "Rotacioni Nala nuk ka ditët dhe ciklin e së dielës të vlefshëm.")
    try:
        if rotation.get("anchor_date"):
            date.fromisoformat(rotation["anchor_date"])
    except ValueError as exc:
        raise HTTPException(422, "Data e rotacionit nuk është e vlefshme.") from exc
    return parsed, rotation


def dataset_weekdays(value):
    days = [] if value is None else [int(d) for d in value.split(",")] if isinstance(value, str) else value
    if not isinstance(days, list) or any(type(d) is not int or d not in range(7) for d in days) or len(set(days)) != len(days):
        raise ValueError("Invalid weekdays")
    return days


# Explicit identity changes in the reviewed v2 handoff. UUIDs and occurrences
# stay attached to their original templates, including when a source ID changes.
V2_SOURCE_ALIASES = {
    "rrita_room_daily": "rrita_room", "rrita_bathroom_daily": "rrita_bathroom",
    "mrika_room_daily": "mrika_room", "mrika_bathroom_daily": "mrika_bathroom",
    "lirza_room_daily": "lirza_room", "lirza_bathroom_daily": "lirza_bathroom",
    "mrika_living_daily": "mrika_living", "mrika_white_table_daily": "mrika_table",
    "lirza_large_corridor_daily": "lirza_corridor", "lirza_library_daily": "lirza_library",
    "lirza_library_corridor_daily": "lirza_library_corridor", "rrita_dishes_daily": "rrita_dishes",
    "rrita_kitchen_daily": "rrita_kitchen", "rrita_long_corridor_daily": "rrita_corridor",
    "mrika_living_deep": "living_room_deep", "mrika_white_table_deep": "white_table_deep",
    "lirza_large_corridor_deep": "large_corridor_deep", "lirza_library_deep": "library_deep",
    "lirza_library_corridor_deep": "library_corridor_deep", "rrita_kitchen_deep": "kitchen_deep",
    "rrita_long_corridor_deep": "long_corridor_deep", "nala_prepare_before_sleep": "nala_prepare",
    "roki_program_1": "roki_kitchen", "roki_program_2": "roki_weekend",
}


def untouched_import(row):
    # Check the stored shape too: earlier imports predate new optional fields.
    return bool(row.import_hash) and row.import_hash == document_hash({**row.definition, "enabled": False})


async def import_dataset(db, member, dataset, *, apply=False, expected_hash=None, commit=True):
    if not member.is_admin:
        raise HTTPException(403, "Importimi kërkon administratorin e modulit.")
    parsed, rotation = validate_dataset(dataset)
    source_hash = document_hash(dataset)
    if apply and source_hash != expected_hash:
        raise HTTPException(409, "Dataset-i ndryshoi; bëj preview përsëri.")
    space = await lock_member_space(db, member, need_admin=True)
    if dataset["format_version"] < space.config.get("dataset_version", 1):
        raise HTTPException(409, "Dataset-i është më i vjetër se importi aktual.")
    existing = {t.source_id: t for t in (await db.execute(select(Template).where(Template.space_id == member.space_id, Template.source_id.is_not(None)))).scalars().all()}
    active_members = set((await db.execute(select(Member.person_key).join(User, User.id == Member.user_id).where(Member.space_id == member.space_id, Member.active.is_(True), User.is_active.is_(True)))).scalars().all())
    conflicts, created, unchanged, updated, renamed, retired = [], [], [], [], {}, []
    aliases = V2_SOURCE_ALIASES if dataset["format_version"] == 2 else {}
    matched = {}
    for key, data in parsed:
        current = existing.get(key) or existing.get(aliases.get(key))
        matched[key] = current
        if key in existing and aliases.get(key) in existing:
            conflicts.append(key)
            continue
        if current is None:
            created.append(key)
        elif (TemplateDefinition.model_validate(current.definition).model_dump(mode="json") == data or (
            current.import_hash == document_hash(data)
            and {**TemplateDefinition.model_validate(current.definition).model_dump(mode="json"), "enabled": False} == data
        )) and current.source_id == key:
            # A reviewed seed can opt an otherwise untouched model into daily
            # generation. Re-import preserves that activation rather than
            # treating it as a source conflict or disabling it again.
            unchanged.append(key)
        elif untouched_import(current) and not current.archived:
            updated.append(key)
            if current.source_id != key:
                renamed[key] = current.source_id
        else:
            # Deliberately preserve local edits/activation on every re-import.
            conflicts.append(key)
    # These two generic v1 preparation tasks are replaced by explicit v2 zone
    # instructions. Archive them; never delete templates or completion history.
    if dataset["format_version"] == 2:
        for key in ("dust", "robot_prep"):
            current = existing.get(key)
            if current and not current.archived:
                (retired if untouched_import(current) and not current.definition["enabled"] else conflicts).append(key)
    result = {"dataset_hash": source_hash, "templates": len(parsed), "steps": sum(len(d["steps"]) for _, d in parsed),
        "create": created, "unchanged": unchanged, "conflicts": conflicts,
        "update": updated, "rename": renamed, "archive": retired,
        "unresolved_members": sorted(PEOPLE - active_members), "schedules_enabled": False,
        "open_decisions": dataset.get("open_decisions", [])}
    if not apply:
        return result
    if result["unresolved_members"] or conflicts:
        raise HTTPException(409, "Plotëso lidhjet dhe zgjidh konfliktet e preview para importimit.")
    prior = (await db.execute(select(ImportRun).where(ImportRun.space_id == member.space_id, ImportRun.dataset_hash == source_hash))).scalar_one_or_none()
    if prior:
        return {**result, "applied": True, "already_applied": True}
    for key, data in parsed:
        current = matched[key]
        if current is None:
            db.add(Template(space_id=member.space_id, source_id=key, created_by=member.user_id, definition=data, import_hash=document_hash(data)))
        elif key in updated:
            enabled = current.definition["enabled"] and data["readiness"] == "ready_after_setup" and data["assignment"] != "unassigned"
            current.source_id, current.definition = key, {**data, "enabled": enabled}
            current.import_hash, current.version = document_hash(data), current.version + 1
    for key in retired:
        existing[key].archived = True
        existing[key].version += 1
    space.config = {**space.config, "rotation_anchor": rotation.get("anchor_date"),
        "nala_rotation": rotation if dataset["format_version"] == 2 else None,
        "dataset_version": dataset["format_version"],
        "abbreviation_legend": dataset.get("abbreviation_legend", {}),
        "areas": dataset.get("areas", []), "activities": dataset.get("activities", []),
        "seed_settings": dataset.get("settings", {}),
        "open_decisions": dataset.get("open_decisions", []), "reminders_enabled": False}
    db.add(ImportRun(space_id=member.space_id, dataset_hash=source_hash, actor_id=member.user_id, summary=result))
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {**result, "applied": True, "already_applied": False}
