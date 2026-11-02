"""One Discord card can represent several actual PrimeFlow duties atomically."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.models.ga_personal import GaPersonalDiscordDelivery as Delivery, GaPersonalOccurrence as Occurrence, GaPersonalTemplate as Template
from app.services import ga_personal as tasks, ga_personal_discord as bridge


async def bundle_claims(db, cards):
    groups = {}
    for value in cards:
        row = await db.get(Occurrence, value["occurrence_id"])
        routine = row.snapshot.get("routine_key")
        if routine and value["phase"] != "manual":
            key = tasks.document_hash([routine, value["target"], value["assignees"], value["due_at"], value["phase"]])
            groups.setdefault(key, []).append(value)
    remove = set()
    for values in groups.values():
        if len(values) < 2:
            continue
        leader = await db.get(Delivery, values[0]["id"])
        leader.details = {**leader.details, "bundle_members": [v["id"] for v in values[1:]]}
        for value in values[1:]:
            child = await db.get(Delivery, value["id"])
            child.status = "bundled"
            child.details = {**child.details, "bundle_leader": values[0]["id"]}
            remove.add(value["id"])
    return [c for c in cards if c["id"] not in remove]


async def members(db, delivery, row, archived):
    output = [(delivery, row, archived)]
    for identity in delivery.details.get("bundle_members", []):
        result = (await db.execute(select(Delivery, Occurrence, Template.archived).join(Occurrence, Occurrence.id == Delivery.occurrence_id)
            .join(Template, Template.id == Occurrence.template_id).where(Delivery.id == identity,
                Occurrence.space_id == row.space_id, Template.space_id == row.space_id))).one_or_none()
        if result is None:
            raise HTTPException(409, "Rutina ndryshoi. Hapi detyrat në PrimeFlow.")
        output.append(result)
    return output


def matches(delivery, row, archived, cfg, active):
    reference = delivery.details.get("action_key", delivery.schedule_key)
    return not archived and any(delivery.recipient == recipient and reference == bridge.schedule_key(row, cfg, target)
                                for recipient, target in bridge.routes(row, cfg, active))


async def current_card(db, delivery, row, archived, cfg, active):
    values = await members(db, delivery, row, archived)
    valid = all(matches(d, r, a, cfg, active) for d, r, a in values)
    result = bridge.current_card(delivery, row, archived or not valid, cfg, active)
    if result.get("removed"):
        return result
    if len(values) > 1:
        result["title"] = {"morning": "Mëngjesi", "rooms": "Dhomat"}.get(row.snapshot["routine_key"], row.snapshot["title"])
        result["parts"] = [{"title": r.snapshot["title"], "status": r.status} for _, r, _ in values]
        statuses = [r.status for _, r, _ in values]
        result["status"] = "done" if all(s in {"done", "cancelled"} for s in statuses) else "needs_help" if "needs_help" in statuses else "pending"
        result["sync_key"] = tasks.document_hash({k: v for k, v in result.items() if k not in {"lease", "channel_id", "message_id", "sync_key"}})
    return result


async def act(db, delivery, row, archived, cfg, active, action):
    values = await members(db, delivery, row, archived)
    if not all(matches(d, r, a, cfg, active) for d, r, a in values):
        raise HTTPException(409, "Një detyrë e rutinës ndryshoi. Hape kartelën e përditësuar.")
    if action == "steps":
        return {"status": row.status, "description": "Hapat e rutinës", "steps": [
            step for _, r, _ in values for step in [r.snapshot["title"], *r.snapshot.get("steps", [])]]}
    new_status = "rescheduled" if action.startswith("later") else action
    due = bridge.utcnow() + timedelta(minutes=int(action[5:])) if action.startswith("later") else None
    pending = [(d, r) for d, r, _ in values if r.status not in {"done", "cancelled"}]
    if not pending or any(new_status not in tasks.TRANSITIONS[r.status] for _, r in pending):
        raise HTTPException(409, "Ky ndryshim nuk lejohet për gjendjen e rutinës.")
    changed = []
    for item, occurrence in pending:
        old = occurrence.status
        await tasks.change_status(db, occurrence, new_status, due)
        if due:
            item.details = {**item.details, "action_key": bridge.schedule_key(occurrence, cfg, item.details["target"])}
        changed.append({"id": str(occurrence.id), "from": old, "to": new_status})
    return {"changed": changed}
