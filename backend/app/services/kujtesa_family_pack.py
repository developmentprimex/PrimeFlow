"""Reviewed household routines, stored as normal editable PrimeFlow templates.

No Discord credentials, second scheduler, SQLite store or downloaded executable
is used. Applying the pack is additive; existing/manual definitions are preserved.
"""
from __future__ import annotations

import unicodedata
import uuid
from datetime import date, datetime, time, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.models.ga_personal import GaPersonalTemplate as Template, GaPersonalEvent as Event, GaPersonalOccurrence as Occurrence
from app.schemas.ga_personal import GenerateRequest, TemplateDefinition
from app.services import ga_personal as tasks

ROTATION = {"weekday_owners_iso": {"0": "rrita", "1": "mrika", "2": "lirza", "3": "rrita", "4": "mrika", "5": "lirza"},
            "sunday_cycle": {"anchor_date": "2026-11-01", "order": ["lirza", "mrika", "rrita"]},
            "notes": "Radha e Kujtesës: ditët fikse dhe rotacioni javor i së dielës."}


def definitions():
    result = []

    def add(source, title, owners=(), at=None, steps=(), days=None, group="daily_upkeep", aliases=(), **extra):
        data = TemplateDefinition(title=title, assignees=list(owners), due_time=at, steps=list(steps),
            frequency="near_daily" if days is not None else "daily", weekdays=list(days or []),
            reminder_group=group, enabled=True, discord_destination="channel", **extra).model_dump(mode="json")
        result.append({"source_id": source, "aliases": list(aliases), "definition": data})

    for source, title, at, steps, aliases in [
        ("nala_morning", "Dalja e mëngjesit", "06:50", ["Deri tani dalja e mëngjesit duhet të jetë kryer.", "Merre zinxhirin dhe qeset.", "Mblidh jashtëqitjen nëse ka."], []),
        ("nala_afternoon", "Shëtitja e gjatë", "16:30", ["Merre zinxhirin dhe qeset.", "Nxirre Nalën për shëtitjen më të gjatë.", "Mblidh jashtëqitjen nëse ka.", "A e ka bërë kakin? Nëse jo, dalja tjetër është në 19:30."], []),
        ("nala_dinner", "Ushqimi i Nalës", "17:00", ["Mbush tasin me ushqim.", "Mbush ujin sipas nevojës."], []),
        ("nala_evening", "Dalja e fundit", "20:30", ["Nxirre Nalën për daljen e fundit.", "Mbush ujin."], []),
        ("nala_next_food", "Ushqimi për nesër", "21:30", ["Përgatite ushqimin e Nalës për ditën tjetër.", "Lëre lart."], ["nala_prepare"]),
        ("nala_balcony", "Kontrolli i ballkonit", None, ["Kontrollo dhe pastro ballkonin."], []),
        ("roki_water", "Uji i Rokit", None, ["Mbush ujin e Rokit."], []),
    ]:
        add(source, title, at=at, steps=steps, aliases=aliases, group="roki" if source == "roki_water" else "nala",
            assignment="rotation", rotation_id="nala")

    rooms = {
        "rrita": [("room", "Dhoma e Rritës"), ("bathroom", "Banjo e madhe"), ("kitchen", "Kuzhina"),
                  ("dishes", "Enët"), ("long_corridor", "Korridori i gjatë")],
        "mrika": [("room", "Dhoma e Mrikës"), ("bathroom", "Tualeti i Mrikës"), ("living", "Dhoma e pritjes"), ("table", "Tavolina e bardhë")],
        "lirza": [("room", "Dhoma e Lirzës"), ("bathroom", "Tualeti i Lirzës"), ("library", "Biblioteka"),
                  ("library_corridor", "Korridori i vogël"), ("corridor", "Korridori i madh")],
    }
    for person in ("rrita", "mrika", "lirza"):
        add(person + "_morning_room", "Rregullo shtratin dhe dhomën", [person], "06:50",
            ["Rregullo shtratin.", "Vendosi teshat dhe lodrat në vend." if person == "lirza" else "Vendosi teshat dhe sendet në vend."],
            list(range(5)), "morning", estimated_minutes=25, routine_key="morning")
        add(person + "_school_items", "Merri çelësat dhe ushqimin", [person], "06:50",
            ["Merri çelësat.", "Merre mëngjesin ose ushqimin për shkollë."], list(range(5)), "morning", estimated_minutes=25, routine_key="morning")
        for key, title in rooms[person]:
            steps = [f"{title}: largo hallakamën", f"{title}: organizoji sipas fotove"]
            if key == "library": steps.append("Lëre stacionin e Rokit të lirë.")
            if person == "lirza" and key == "corridor": steps.append("Xhaketat dhe papuçet në vend.")
            extra = steps + [f"{title}: fshi xhamat", f"{title}: pastro dyert", f"{title}: dyshemeja, nëse do"]
            add(person + "_" + key, title, [person], "20:20", steps,
                aliases=["rrita_long_corridor_daily"] if person == "rrita" and key == "long_corridor" else (),
                routine_key="rooms", weekday_steps={str(day): extra for day in (4, 5, 6)}, area_id="room" if key == "room" else "bathroom" if key == "bathroom" else "home")
        for suffix, title in [("reading", "Lexim"), ("reflection", "Mendim dhe reflektim"), ("study", "Mësim")]:
            add(person + "_" + suffix, title, [person], steps=[title + "."])
        school_time = {"rrita": "14:40", "mrika": "15:00", "lirza": "15:30"}[person]
        # A planned return belongs in the agenda; an actual arrival is a separate event.
        add(person + "_school_return", "Kthimi nga shkolla", [person], days=list(range(5)),
            agenda_time=school_time, description=f"Ora e planifikuar: {school_time}. Kthimi real regjistrohet veçmas.")

    for source, person, title, at, minutes, days in [
        ("lirza_hollywood", "lirza", "Hollywood", "18:40", 100, [0, 2]),
        ("mrika_hollywood", "mrika", "Hollywood", "18:40", 100, [1, 3]),
        ("rrita_hollywood", "rrita", "Hollywood", "18:40", 100, [1, 3]),
        ("mrika_volleyball", "mrika", "Volejboll", "17:30", 105, [2, 4]),
        ("mrika_volleyball_sat", "mrika", "Volejboll", "10:30", None, [5]),
    ]:
        add(source, title, [person], at, ["Përgatite çantën.", "Nisu në kohë."], days, "events", estimated_minutes=minutes, area_id="activity")
    for source, person, title, at in [
        ("nani_heat_on", "gane", "Ndez nxehtësinë", "05:00"),
        ("nani_heat_release", "gane", "Lësho nxehtësinë", "21:00"),
        ("nani_heat_lower", "gane", "Ule temperaturën", "22:00"),
        ("rrita_stop", "rrita", "Ndaloje", "07:15"),
        ("nani_nala_food", "gane", "Ushqimi i mëngjesit i Nalës", "05:00"),
        ("rrita_after_dinner", "rrita", "Kuzhina pas darke", "17:00"),
    ]:
        add(source, title, [person], at, [title + "."])
    add("lirza_sunday_clean", "Pastrim", ["lirza"], "16:00", ["Larja (tushi).", "Prerja e thonjve."], [6])
    for person, title in [("rrita", "Kuzhina: lavamani, enët dhe pjesa e lartë"), ("mrika", "Kuzhina: worktop"),
                          ("lirza", "Kuzhina: tavolina dhe shanku"), ("gane", "Kuzhina: ushqimi dhe furra")]:
        add(person + "_saturday_kitchen", title, [person], steps=[title + "."], days=[5], group="weekend_deep_clean")
    for person in ("mrika", "lirza"):
        add(person + "_flowers", "Lulet e brendshme", [person], steps=["Kujdesu për lulet e brendshme."], days=[5])
    add("lirza_braces", "Zgjerimi i protezave", ["lirza"], steps=["Zgjerimi i protezave sipas udhëzimit."],
        recurrence_interval_days=3, recurrence_anchor_date=date(2026, 11, 2))
    add("braces_wash", "Larja e protezave", ["lirza", "gane"], days=[6], steps=["Pastro protezat."])
    add("nani_laundry", "Teshat për t’u larë", ["gane"], days=[4, 5], steps=["Përgatiti teshat për larje."])
    add("nala_care", "Kujdesi i Nalës", days=[6], group="nala", assignment="rotation", rotation_id="nala",
        recurrence_interval_weeks=6, recurrence_anchor_date=date(2026, 11, 22), steps=["Bëje kujdesin periodik të Nalës."])
    add("nala_sunday_areas", "Hapësirat shtesë të së dielës", days=[6], assignment="rotation", rotation_id="nala",
        steps=["Dhoma e mysafirëve dhe e hekurit: largo hallakamën, organizoji sipas fotove, xhamat dhe dyert.",
               "Dhoma e Kaldasë: largo hallakamën, organizoji sipas fotove, xhamat dhe dyert.",
               "Ballkonet: hiq barin e keq, mblidh lodrat e Nalës, sistemo frutat, rregulloji dhe fshi xhamat."])
    add("nala_first_urine", "Urina e parë e Nalës", list(sorted(tasks.PEOPLE)), group="nala", completion_mode="shared")
    return result


def normalized(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c)).split())


async def install(db, member, *, expected_hash=None):
    space = await tasks.lock_member_space(db, member, need_admin=True)
    rows = (await db.execute(select(Template).where(Template.space_id == space.id).order_by(Template.id))).scalars().all()
    plan, writes = [], []
    used = set()
    for entry in definitions():
        keys = {entry["source_id"], *entry["aliases"]}
        keys.update(new for new, old in tasks.V2_SOURCE_ALIASES.items() if old in keys)
        matches = [r for r in rows if r.source_id in keys]
        if not matches:
            matches = [r for r in rows if normalized(r.definition["title"]) == normalized(entry["definition"]["title"])
                       and r.definition["assignees"] == entry["definition"]["assignees"]]
        # Never create a parallel chore when an existing imported/manual model matches.
        if matches:
            state = "existing"
            matched = matches[0]
            current = matched.definition
            untouched = matched.import_hash in {tasks.document_hash(current), tasks.document_hash({**current, "enabled": False})}
            if len(matches) == 1 and untouched and not matched.archived and matched.id not in used and current != entry["definition"]:
                state = "update"
                writes.append((matched, entry))
            used.update(r.id for r in matches)
        else:
            state = "create"
            writes.append((None, entry))
        plan.append({"source_id": entry["source_id"], "title": entry["definition"]["title"], "action": state,
                     "definition": entry["definition"], "existing_ids": [str(r.id) for r in matches]})
    # Heartbeats and rolling generation checkpoints must not invalidate a review
    # every 15 seconds. Only settings that affect this import belong in its hash.
    generation = space.config.get("automatic_generation", {})
    snapshot = {"pack": plan, "versions": sorted((str(r.id), r.version, tasks.document_hash(r.definition), r.archived) for r in rows),
                "config": {"rotation_anchor": space.config.get("rotation_anchor"), "nala_rotation": space.config.get("nala_rotation"),
                           "family_pack": space.config.get("kujtesa_family_pack"),
                           "automatic_generation": {key: generation.get(key) for key in ("enabled", "starts_on")}}}
    signature = tasks.document_hash(snapshot)
    review = {"hash": signature, "tasks": plan,
              "counts": {action: sum(p["action"] == action for p in plan) for action in ("create", "update", "existing")},
              "rotation_will_change": not bool(space.config.get("nala_rotation") or space.config.get("rotation_anchor")),
              "external_notes": [{"person": "Babi", "title": "Dhoma, banja dhe teshat", "days": [4, 5, 6]}]}
    if expected_hash is None:
        return review
    if expected_hash != signature:
        raise HTTPException(409, "Detyrat ndryshuan. Hape përsëri pamjen e shtesave.")
    from app.services.ga_personal_device_sync import active_people
    people = await active_people(db, space.id)
    if people != tasks.PEOPLE:
        raise HTTPException(409, "Lidhi katër anëtarët e familjes para importimit.")
    refreshed = 0
    today = tasks.utcnow().astimezone(tasks.TZ).date()
    for row, entry in writes:
        data = entry["definition"]
        if row is None:
            db.add(Template(space_id=space.id, source_id=entry["source_id"], created_by=member.user_id,
                            definition=data, import_hash=tasks.document_hash(data)))
        else:
            previous_version = row.version
            row.definition, row.version = data, row.version + 1
            row.import_hash = tasks.document_hash(data)
            upcoming = (await db.execute(select(Occurrence).where(Occurrence.template_id == row.id,
                Occurrence.space_id == space.id, Occurrence.local_date >= today.isoformat(), Occurrence.status == "pending"))).scalars().all()
            for occurrence in upcoming:
                old = occurrence.snapshot
                day = date.fromisoformat(occurrence.local_date)
                if (old.get("template_version") != previous_version or old.get("assignment_overridden")
                    or old.get("schedule_overridden") or old.get("discord_schedule_revision")
                    or tasks.period_key(data, day) != occurrence.period_key
                    or not tasks.scheduled(data, day)
                    or (data["assignment"] == "fixed" and not set(old["assignees"]).issubset(data["assignees"]))):
                    continue
                occurrence.due_at = datetime.combine(day, time.fromisoformat(data["due_time"]), tasks.TZ).astimezone(timezone.utc) if data["due_time"] else None
                occurrence.snapshot = {**data, "steps": data.get("weekday_steps", {}).get(str(day.weekday()), data["steps"]),
                    "assignees": old["assignees"], "template_version": row.version,
                    "discord_schedule_revision": old.get("discord_schedule_revision", 0) + 1}
                occurrence.version += 1
                await tasks.cancel_discord(db, [occurrence.id])
                refreshed += 1
    cfg = {**space.config}
    if review["rotation_will_change"]:
        cfg["nala_rotation"] = ROTATION
    cfg["kujtesa_family_pack"] = {"version": 1, "installed_by": str(member.user_id), "external_notes": review["external_notes"]}
    automatic = cfg.get("automatic_generation", {})
    cfg["automatic_generation"] = {**automatic, "enabled": True,
        "starts_on": automatic.get("starts_on") or tasks.utcnow().astimezone(tasks.TZ).date().isoformat()}
    cfg["automatic_generation"].pop("future_generated_through", None)
    space.config = cfg
    db.add(Event(space_id=space.id, actor_id=member.user_id, request_id=str(uuid.uuid4()), kind="family_pack_installed",
                 payload={"counts": review["counts"], "hash": signature}))
    await db.flush()
    await tasks.generate(db, member, GenerateRequest(day=tasks.utcnow().astimezone(tasks.TZ).date()), automatic=True, commit=False)
    await db.commit()
    return {**review, "applied": True, "refreshed_pending_occurrences": refreshed}
