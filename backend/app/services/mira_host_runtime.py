"""Durable host control and delivery state, stored in the existing meeting event log."""
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.mira_host import Mira1HEvent, Mira1HMeeting, Mira1HTurn
from app.models.ga_note import GaNote
from app.models.user import User


async def request_stop(db, user_id):
    from app.services.mira_host import now
    meetings = (await db.execute(select(Mira1HMeeting).where(
        Mira1HMeeting.status.in_(("GA_PHASE", "STAFF_PHASE"))).with_for_update())).scalars().all()
    for meeting in meetings:
        await db.execute(insert(Mira1HEvent).values(id=uuid.uuid4(), key=f"stop:{meeting.id}",
            meeting_id=meeting.id, meeting_date=meeting.meeting_date, slot=meeting.slot,
            kind="STOP_REQUEST", user_id=user_id, data={}, sent_at=now()).on_conflict_do_update(
                index_elements=["key"], set_={"sent_at": now(), "user_id": user_id}))
    return len(meetings)


async def stop_requests(db):
    return [str(mid) for mid in (await db.execute(select(Mira1HEvent.meeting_id).join(
        Mira1HMeeting, Mira1HMeeting.id == Mira1HEvent.meeting_id).where(
        Mira1HEvent.kind == "STOP_REQUEST", Mira1HEvent.sent_at >= Mira1HMeeting.started_at,
        Mira1HMeeting.status.in_(("GA_PHASE", "STAFF_PHASE"))))).scalars().all()]


async def acknowledge_notes(db, meeting, token):
    event = await db.get(Mira1HEvent, token, with_for_update=True)
    if not event or event.meeting_id != meeting.id or event.kind not in ("NOTES_PENDING", "NOTES_READ", "NOTES_DEFERRED"):
        raise HTTPException(404, "Nuk u gjet njoftimi i shënimeve.")
    if event.kind == "NOTES_READ":
        return {"ok": True}
    if not meeting.is_test:
        for note_id in event.data.get("note_ids", []):
            if await db.get(GaNote, uuid.UUID(note_id), with_for_update=True) is None:
                continue
            await db.execute(insert(Mira1HEvent).values(id=uuid.uuid4(), key=f"note-read:{meeting.id}:{note_id}",
                meeting_id=meeting.id, meeting_date=meeting.meeting_date, slot=meeting.slot,
                kind="NOTE_MENTION", note_id=uuid.UUID(note_id),
                sent_at=datetime.fromisoformat(event.data["fetched_at"]), data={})
                .on_conflict_do_nothing(index_elements=["key"]))
    event.kind = "NOTES_READ"
    return {"ok": True}


async def defer_announcement(db, meeting, token):
    event = await db.get(Mira1HEvent, token, with_for_update=True)
    if not event or event.meeting_id != meeting.id:
        raise HTTPException(404, "Njoftimi nuk i përket këtij takimi.")
    if event.kind in ("NOTES_PENDING", "PROGRESS_PENDING"):
        event.kind = event.kind.replace("PENDING", "DEFERRED")
    return {"ok": True}


async def notification_result(db, key, delivered, *, at):
    event = (await db.execute(select(Mira1HEvent).where(Mira1HEvent.key == key).with_for_update())).scalar_one_or_none()
    if not event or event.kind not in ("BRIEF", "GA_CALL", "GA_FALLBACK"):
        raise HTTPException(404, "Nuk u gjet ftesa.")
    state = dict(event.data or {})
    if state.get("delivery_status") != "SENT":
        state["delivery_status"] = "SENT" if delivered else "PENDING"
        if not delivered:
            state["retry_at"] = at.isoformat()
        event.data = state
        if delivered:
            event.sent_at = at
    return {"ok": True}


def pm_state(event):
    from app.services.mira_host import excluded_host_turn, PM_REVIEW_SLOT
    queue = [p for p in event.data.get("queue", [])
             if not excluded_host_turn(PM_REVIEW_SLOT, p.get("name") or p.get("person"))] if event else []
    return {"initialized": event is not None, "current": next((p for p in queue if p["status"] == "ACTIVE"), None),
            "deferred": [p for p in queue if p["status"] == "DEFERRED"], "turns": queue}


async def pm_event(db, meeting):
    if meeting.slot != "11:50" or meeting.status != "STAFF_PHASE":
        raise HTTPException(409, "Rishikimi PM nuk është aktiv.")
    return (await db.execute(select(Mira1HEvent).where(
        Mira1HEvent.key == f"pm:{meeting.id}").with_for_update())).scalar_one_or_none()


async def finish_pm(db, meeting, at):
    event = (await db.execute(select(Mira1HEvent).where(
        Mira1HEvent.key == f"pm:{meeting.id}").with_for_update())).scalar_one_or_none()
    if event:
        event.data = {**event.data, "queue": [
            {**person, "status": "SKIPPED", "ended_at": at.isoformat()}
            if person["status"] in ("ACTIVE", "WAITING", "DEFERRED") else person for person in event.data.get("queue", [])]}


async def next_pm_turn(db, meeting, *, expected_turn_id, outcome="DONE", summary=None, available_discord_ids=None):
    from app.services import mira_host as host
    event = await pm_event(db, meeting)
    at = host.now().isoformat()
    if event is None:
        if expected_turn_id:
            raise HTTPException(409, "Radha PM ka ndryshuar.")
        unfinished = (await db.execute(select(Mira1HTurn.id, User.full_name).join(User, User.id == Mira1HTurn.user_id)
            .where(Mira1HTurn.meeting_id == meeting.id, Mira1HTurn.status.in_(("ACTIVE", "WAITING", "DEFERRED"))))).all()
        if any(not host.excluded_host_turn(meeting.slot, name) for _, name in unfinished):
            raise HTTPException(409, "Raportimi i stafit ende nuk përfundoi.")
        data = host.SlotData(await host.common_payload(db, meeting.meeting_date, fresh=True), meeting.meeting_date)
        people = data.pm_open()
        targets = await host.discord_targets(db, [p["user_id"] for p in people])
        queue = [{**p, "id": "PM_" + p["user_id"], "name": p["person"], "status": "WAITING",
                  "discord": targets.get(p["user_id"])} for p in people]
        event = Mira1HEvent(id=uuid.uuid4(), key=f"pm:{meeting.id}", meeting_id=meeting.id,
            meeting_date=meeting.meeting_date, slot=meeting.slot, kind="PM_REVIEW",
            data={"queue": queue, "join_attempt": meeting.join_attempts or 1})
        db.add(event)
    queue = [dict(p) for p in event.data.get("queue", [])]
    attempt = meeting.join_attempts or 1
    if attempt > event.data.get("join_attempt", 1):
        for person in queue:
            if person["status"] == "SKIPPED" and not host.excluded_host_turn(meeting.slot, person.get("name") or person.get("person")):
                person.update(status="WAITING", ended_at=None)
        event.data = {**event.data, "join_attempt": attempt}
    excluded_active = {p["id"] for p in queue if host.excluded_host_turn(meeting.slot, p.get("name") or p.get("person")) and p["status"] == "ACTIVE"}
    for person in queue:
        if host.excluded_host_turn(meeting.slot, person.get("name") or person.get("person")) and person["status"] in {"ACTIVE", "WAITING", "DEFERRED"}:
            person.update(status="SKIPPED", ended_at=at)
    active = next((p for p in queue if p["status"] == "ACTIVE"), None)
    if not active and expected_turn_id in excluded_active:
        expected_turn_id = None
    if (active or {}).get("id") != expected_turn_id:
        raise HTTPException(409, "Radha PM ka ndryshuar; mos e përfundo personin e ri.")
    if active:
        if outcome == "DONE" and not active.get("discussion"):
            raise HTTPException(409, "Ruaj record_pm_review për personin aktual përpara kalimit.")
        active.update(status=outcome, ended_at=at, summary=summary)
    available = set(available_discord_ids) if available_discord_ids is not None and not meeting.is_test else None
    skipped = []
    for person in queue:
        discord_id = (person.get("discord") or {}).get("discord_user_id")
        if person["status"] == "WAITING" and available is not None and discord_id and discord_id not in available:
            person["status"] = "DEFERRED"
            skipped.append(person)
    waiting = [p for p in queue if p["status"] == "WAITING"] + [p for p in queue if p["status"] == "DEFERRED"
        and available is not None and (p.get("discord") or {}).get("discord_user_id") in available and p is not active]
    if waiting:
        waiting[0].update(status="ACTIVE", started_at=at)
    event.data = {**event.data, "queue": queue}
    return {**pm_state(event), "skipped": skipped, "ended": active}


async def record_pm_review(db, meeting, args, actor):
    event = await pm_event(db, meeting)
    current = pm_state(event)["current"]
    if not current or current["id"] != args.turn_id:
        return {"success": False, "error": "Kjo nuk është radha PM aktive."}
    if actor is not None and str(actor.id) != current["user_id"] and not meeting.is_test:
        return {"success": False, "error": "Raportimin PM e ruan vetëm personi i radhës."}
    facts = {k: v for k, v in args.model_dump().items() if k != "turn_id" and v is not None}
    if not args.unclear and not (args.continuation or args.postponement):
        return {"success": False, "error": "Nuk ka raportim PM për të ruajtur."}
    queue = [{**p, "discussion": {**p.get("discussion", {}), **facts}} if p["id"] == current["id"] else p
             for p in event.data["queue"]]
    event.data = {**event.data, "queue": queue}
    return {"success": True, "discussion": facts, "next_step": "end_person_turn", "turn_id": current["id"]}
