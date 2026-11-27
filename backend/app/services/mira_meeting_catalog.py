"""Read-only composition of the existing Mira meeting records."""

import re
from collections import defaultdict
from uuid import UUID
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import aliased

from app.models.discord_voice_meeting import DiscordVoiceMeeting as Voice
from app.models.ga_note import GaNote
from app.models.mira_desktop import MiraDesktopSession as Desktop
from app.models.mira_host import Mira1HEvent as HostEvent, Mira1HMeeting as Host, Mira1HTurn as HostTurn
from app.models.mira_memory import MiraMemoryEvent as MemoryEvent, MiraMemoryItem as MemoryItem
from app.models.task import Task
from app.services import discord_one_h, discord_voice_meetings, mira_desktop, mira_host, mira_memory
from app.services.mira_development_name import meeting_note_heading, meeting_title
from app.services.mira_note_groups import note_group

HOST_NOTE_KINDS = ("PX_NOTE", "SUMMARY_NOTE")


def automatic_slot(request_id):
    match = re.fullmatch(r"auto1h-(\d{12})(?:-\d+)?", request_id)
    if not match:
        return None
    try:
        started = datetime.strptime(match[1], "%Y%m%d%H%M")
    except ValueError:
        return None
    # The auto-join schedule starts the recorder two minutes before official staff reporting.
    for candidate in (started, started + timedelta(minutes=2)):
        slot = candidate.strftime("%H:%M")
        if slot in discord_one_h.SLOTS:
            return candidate.date(), slot
    return None


def slot_recordings(voices):
    by_slot = {}
    for voice in sorted(voices, key=lambda row: (
        {"SAVED": 0, "READY": 1, "FAILED": 2}[row.status], row.created_at, row.id,
    )):
        slot = automatic_slot(voice.request_id)
        if slot:
            by_slot.setdefault(slot, voice.id)
    return by_slot


async def voice_for_host(db, host):
    if host.voice_meeting_id:
        return await db.scalar(select(Voice.id).where(Voice.id == host.voice_meeting_id,
            Voice.status.in_(mira_memory.RECORD_STATUSES)))
    if host.is_test:
        return None
    return await voice_for_slot(db, host.meeting_date, host.slot)


async def voice_for_slot(db, day, slot):
    recordings = await db.scalars(select(Voice).where(
        Voice.request_id.startswith(f"auto1h-{day:%Y%m%d}"),
        Voice.status.in_(mira_memory.RECORD_STATUSES)))
    return slot_recordings(recordings).get((day, slot))


def unlinked_notes():
    return select(GaNote).where(
        or_(GaNote.from_mira, GaNote.from_mira_desktop),
        ~select(Voice.id).where(Voice.saved_note_id == GaNote.id,
            Voice.status.in_(mira_memory.RECORD_STATUSES)).exists(),
        ~select(HostEvent.id).where(HostEvent.note_id == GaNote.id,
            HostEvent.kind.in_(HOST_NOTE_KINDS), HostEvent.meeting_id.is_not(None)).exists(),
        ~select(Desktop.id).where(Desktop.note_id == GaNote.id).exists(),
    )


def archived_note(note):
    content = meeting_note_heading(note.content) if note.from_mira and not note.from_mira_desktop else note.content
    return {**saved_note(note, content.split("\n\n", 1)[0].strip() or "Shënim nga Mira"), "content": content}


async def list_unlinked_notes(db, limit, offset, query):
    records = unlinked_notes()
    if query:
        records = records.where(GaNote.content.icontains(query, autoescape=True))
    notes = (await db.scalars(records.order_by(GaNote.created_at.desc(), GaNote.id.desc())
        .limit(limit + 1).offset(offset))).all()
    return {"notes": [archived_note(note) for note in notes[:limit]], "has_more": len(notes) > limit}


async def note_matches(db, user, query):
    saved_text = GaNote.content.icontains(query, autoescape=True)
    voice_ids = set(await db.scalars(select(Voice.id).outerjoin(GaNote, Voice.saved_note_id == GaNote.id)
        .where(or_(saved_text, Voice.draft_text.icontains(query, autoescape=True)))))
    host_ids = set(await db.scalars(select(Host.id).outerjoin(HostEvent, HostEvent.meeting_id == Host.id)
        .outerjoin(GaNote, GaNote.id == HostEvent.note_id)
        .where(or_(Host.summary.icontains(query, autoescape=True),
            select(HostTurn.id).where(HostTurn.meeting_id == Host.id,
                HostTurn.notes.icontains(query, autoescape=True)).exists(),
            HostEvent.kind.in_(HOST_NOTE_KINDS) & saved_text))))
    desktop_ids = set(await db.scalars(select(Desktop.id).outerjoin(GaNote, Desktop.note_id == GaNote.id)
        .where(or_(saved_text, (Desktop.user_id == user.id) & Desktop.notes.icontains(query, autoescape=True)))))
    return voice_ids, host_ids, desktop_ids


async def list_meetings(db, user, *, limit, offset, group, query, follow_up_query):
    hosts = (await db.execute(select(Host.id, Host.meeting_date, Host.slot, Host.started_at,
        Host.is_test, Host.status, Host.voice_meeting_id))).all()
    voices = (await db.execute(select(Voice.id, Voice.title, Voice.mira_title, Voice.created_at, Voice.started_at,
        Voice.partial, Voice.voice_channel_id, Voice.recorder, Voice.request_id, Voice.status)
        .where(Voice.status.in_(mira_memory.RECORD_STATUSES)))).all()
    desktops = (await db.execute(select(Desktop.id, Desktop.title, Desktop.created_at, Desktop.partial, Desktop.status)
        .where(or_(Desktop.user_id == user.id, Desktop.note_id.is_not(None))))).all()
    voice_ids = {voice.id for voice in voices}
    custom_titles = {voice.id: voice.mira_title for voice in voices if voice.mira_title}
    recorded_slots = slot_recordings(voices)
    links = {host.id: host.voice_meeting_id or recorded_slots.get((host.meeting_date, host.slot))
        if not host.is_test else host.voice_meeting_id for host in hosts}
    paired = set(links.values()) & voice_ids
    host_slots = {(host.meeting_date, host.slot) for host in hosts if not host.is_test}
    rows = [
        (voice.started_at or voice.created_at, "discord", voice.id, voice.title,
         "1H" if voice.id in paired or voice.request_id.startswith("auto1h-") else
         "AI_AGENT" if voice.recorder == "ai_agent" else
         note_group({"title": voice.title}, voice.voice_channel_id), voice.status, voice.partial)
        for voice in voices
    ]
    rows.extend((host.started_at or mira_host.slot_at(host.meeting_date, host.slot), "host", host.id,
        f'{"TEST · " if host.is_test else ""}1H {host.slot}', "1H", host.status, False)
        for host in hosts if links[host.id] not in voice_ids)
    rows.extend((mira_host.slot_at(day, slot), "host", discord_one_h.slot_id(day, slot),
        f"1H {slot} · Raportimet e stafit", "1H", "DISCORD_REPORT", False)
        for day, slot in await discord_one_h.slot_groups(db) if (day, slot) not in host_slots and (day, slot) not in recorded_slots)
    rows.extend((row.created_at, "desktop", row.id, row.title, "OTHER", row.status, row.partial)
        for row in desktops)
    if group:
        rows = [row for row in rows if row[4] == group]
    if query:
        voice_matches, host_matches, desktop_matches = await note_matches(db, user, query)
        voice_matches.update(voice_id for host_id, voice_id in links.items() if host_id in host_matches)
        host_matches.update(host_id for host_id, voice_id in links.items() if voice_id in voice_matches)
        matches = {"discord": voice_matches, "host": host_matches, "desktop": desktop_matches}
        needle = query.casefold()
        rows = [row for row in rows if needle in row[3].casefold()
                or needle in custom_titles.get(row[2], "").casefold()
                or (row[4] == "AI_AGENT" and needle in meeting_title(row[3]).casefold())
                or row[2] in matches[row[1]]]
    ordered = sorted(rows, key=lambda row: (row[0], row[1], row[2]), reverse=True)
    page = ordered[offset:offset + limit]
    ids = [row[2] for row in page if row[1] == "discord"]
    counts = dict((await db.execute(select(MemoryEvent.meeting_id, func.count(distinct(MemoryItem.id)))
        .join(MemoryItem, MemoryItem.id == MemoryEvent.item_id)
        .where(MemoryEvent.meeting_id.in_(ids), MemoryEvent.kind.in_(mira_memory.HISTORY),
            MemoryItem.status == "OPEN", MemoryItem.kind.in_(mira_memory.FOLLOW_UP_KINDS))
        .group_by(MemoryEvent.meeting_id))).all()) if ids else {}
    page_ids = {row[2] for row in page}
    host_destinations = {host.id: links[host.id] if links[host.id] in voice_ids else host.id for host in hosts}
    artifacts = await page_artifacts(db, ids, {
        host_id: destination for host_id, destination in host_destinations.items() if destination in page_ids
    })
    recorders = {voice.id: voice.recorder for voice in voices if voice.id in page_ids}
    return {"total": len(ordered), "items": [
        {"id": str(id_), "source": source,
         "title": custom_titles.get(id_) or (meeting_title(title) if group_ == "AI_AGENT" else title),
         "has_custom_title": id_ in custom_titles, "group": group_, "status": status,
         "started_at": when.isoformat(), "partial": partial, "open_count": counts.get(id_, 0),
         "recorder": recorders.get(id_), **artifacts.get(id_, {})}
        for when, source, id_, title, group_, status, partial in page
    ], "follow_up": await mira_memory.upcoming_points(db, follow_up_query) if offset == 0 else [],
        "has_unlinked_notes": bool(await db.scalar(select(unlinked_notes().exists())))}


def saved_note(note, title):
    return {"id": str(note.id), "kind": "PX_NOTE", "title": title, "content": note.content,
        "status": note.status, "note_id": str(note.id), "created_at": note.created_at,
        "shared_to_px": bool(note.mira_shared_to_px)}


async def host_notes(db, meeting):
    event = aliased(HostEvent)
    events = (await db.execute(select(event.kind, GaNote)
        .join(GaNote, event.note_id == GaNote.id)
        .where(event.meeting_id == meeting.id, event.kind.in_(HOST_NOTE_KINDS))
        .order_by(event.created_at, event.id))).all()
    summary_note = next((note for kind, note in events if kind == "SUMMARY_NOTE"), None)
    notes = []
    if summary_note or (meeting.summary is not None and not meeting.is_test):
        notes.append({"id": str(meeting.id), "kind": "1H", "title": "Shënimet 1H",
            "content": summary_note.content if summary_note else await mira_host._meeting_note_content(db, meeting),
            "status": meeting.status, "created_at": meeting.ended_at or meeting.created_at,
            "note_id": str(summary_note.id) if summary_note else None,
            "shared_to_px": bool(summary_note and summary_note.mira_shared_to_px)})
    notes.extend({**saved_note(note, "Shënim gjatë takimit"), "created_during_meeting": True}
                 for kind, note in events if kind == "PX_NOTE")
    return notes


def valid_ids(values):
    ids = set()
    for value in values:
        try:
            ids.add(UUID(str(value)))
        except ValueError:
            continue
    return ids


def dictated_artifact_ids(dictation, kind):
    return valid_ids(item.get("id") for item in dictation if item.get("kind") == kind)


async def page_artifacts(db, voice_ids, host_destinations):
    task_ids, note_ids = defaultdict(set), defaultdict(set)
    if voice_ids:
        recordings = await db.execute(select(Voice.id, Voice.dictation_progress["created"])
            .where(Voice.id.in_(voice_ids)))
        for meeting_id, dictation in recordings:
            task_ids[meeting_id].update(dictated_artifact_ids(dictation or [], "task"))
            note_ids[meeting_id].update(dictated_artifact_ids(dictation or [], "note"))
    if host_destinations:
        events = await db.execute(select(HostEvent.meeting_id, HostEvent.kind, HostEvent.note_id, HostEvent.data)
            .where(HostEvent.meeting_id.in_(host_destinations), HostEvent.kind.in_(("TASK_CREATED", "PX_NOTE"))))
        for host_id, kind, note_id, data in events:
            meeting_id = host_destinations[host_id]
            if kind == "TASK_CREATED":
                task_ids[meeting_id].update(valid_ids([(data or {}).get("task_id")]))
            elif note_id is not None:
                note_ids[meeting_id].add(note_id)

    task_candidates = set().union(*task_ids.values())
    note_candidates = set().union(*note_ids.values())
    tasks = set(await db.scalars(select(Task.id).where(Task.id.in_(task_candidates)))) if task_candidates else set()
    notes = set(await db.scalars(select(GaNote.id).where(GaNote.id.in_(note_candidates)))) if note_candidates else set()
    return {meeting_id: {"created_task_count": len(task_ids[meeting_id] & tasks),
                         "created_note_count": len(note_ids[meeting_id] & notes)}
            for meeting_id in task_ids.keys() | note_ids.keys()}


async def created_tasks(db, hosts, dictation):
    from app.api.routers.tasks import _assignees_for_tasks
    from app.services.tomorrow_print_report import _initials

    host_ids = [host.id for host in hosts]
    task_ids = dictated_artifact_ids(dictation, "task")
    if host_ids:
        events = await db.scalars(select(HostEvent.data).where(
            HostEvent.meeting_id.in_(host_ids), HostEvent.kind == "TASK_CREATED"))
        task_ids.update(valid_ids(event.get("task_id") for event in events))
    if not task_ids:
        return []
    tasks = (await db.execute(select(Task.id, Task.title, Task.start_date, Task.due_date)
        .where(Task.id.in_(task_ids)).order_by(Task.created_at, Task.id))).all()
    assignees = await _assignees_for_tasks(db, [task.id for task in tasks])
    result = []
    for task in tasks:
        names = [person.full_name or person.username for person in assignees.get(task.id, [])]
        result.append({"id": str(task.id), "title": task.title, "assignees": names,
                       "assignee_initials": [_initials(name) for name in names],
                       "start_date": task.start_date, "due_date": task.due_date})
    return result


async def discord_detail(db, meeting_id):
    detail = await discord_voice_meetings.meeting_record(db, meeting_id)
    voice = await db.get(Voice, meeting_id)
    hosts = (await db.scalars(select(Host).where(Host.voice_meeting_id == meeting_id)
        .order_by(Host.meeting_date, Host.slot, Host.id))).all()
    slot = automatic_slot(voice.request_id)
    host_for_slot = None
    if slot:
        host_for_slot = await db.scalar(select(Host).where(
            Host.meeting_date == slot[0], Host.slot == slot[1], Host.is_test.is_(False)))
        if host_for_slot and host_for_slot.voice_meeting_id is None and await voice_for_host(db, host_for_slot) == meeting_id:
            hosts.append(host_for_slot)
    note = await db.get(GaNote, voice.saved_note_id) if voice.saved_note_id else None
    notes = [saved_note(note, "Shënimet e regjistrimit")] if note else []
    if notes and voice.recorder == "ai_agent":
        notes[0]["content"] = meeting_note_heading(notes[0]["content"])
    dictation = (voice.dictation_progress or {}).get("created", [])
    note_ids = dictated_artifact_ids(dictation, "note")
    if note_ids:
        dictated = await db.scalars(select(GaNote).where(GaNote.id.in_(note_ids))
            .order_by(GaNote.created_at, GaNote.id))
        notes.extend({**saved_note(note, "Shënim i diktuar"), "created_during_meeting": True,
                      "shareable": False} for note in dictated)
    for host in hosts:
        for host_note in await host_notes(db, host):
            if not host_note["note_id"] or not any(n["note_id"] == host_note["note_id"] for n in notes):
                notes.append(host_note)
    host_ids = [str(host.id) for host in hosts]
    if (not hosts and not host_for_slot and slot and slot in await discord_one_h.slot_groups(db)
            and await voice_for_slot(db, *slot) == meeting_id):
        host_ids.append(str(discord_one_h.slot_id(*slot)))
    return {**detail, "source": "discord", "title": voice.mira_title or detail["title"],
            "has_custom_title": bool(voice.mira_title), "status": voice.status, "notes": notes, "host_ids": host_ids,
            "created_tasks": await created_tasks(db, hosts, dictation)}


async def rename_discord_meeting(db, meeting_id, title):
    voice = await db.scalar(select(Voice).where(Voice.id == meeting_id,
        Voice.status.in_(mira_memory.RECORD_STATUSES)).with_for_update())
    if voice is None:
        raise HTTPException(404, "Takimi nuk u gjet.")
    voice.mira_title = title
    await db.commit()


async def meeting_detail(db, user, source, meeting_id):
    if source == "discord":
        return await discord_detail(db, meeting_id)
    if source == "host":
        host = await db.get(Host, meeting_id)
        voice_id = await voice_for_host(db, host) if host else None
        if voice_id:
            return await discord_detail(db, voice_id)
        detail = await mira_host.meeting_detail(db, meeting_id)
        return {"id": str(meeting_id), "source": source,
            "title": f'1H {detail["slot"]}', "host": detail, "host_ids": [],
            "notes": await host_notes(db, host) if host else [],
            "created_tasks": await created_tasks(db, [host], []) if host else []}

    desktop = await db.get(Desktop, meeting_id)
    if desktop is None or (desktop.user_id != user.id and desktop.note_id is None):
        raise HTTPException(404, "Takimi nuk u gjet.")
    note = await db.get(GaNote, desktop.note_id) if desktop.note_id else None
    can_read_transcript = desktop.user_id == user.id
    capture = await mira_desktop.view(db, desktop) if can_read_transcript else {}
    return {"id": str(desktop.id), "source": source, "title": desktop.title,
        "started_at": desktop.created_at.isoformat(), "status": desktop.status, "partial": desktop.partial,
        "full_notes": capture.get("notes"), "desktop_transcript": capture.get("transcript"),
        "error": capture.get("error"),
        "transcript_allowed": can_read_transcript, "host_ids": [],
        "notes": [saved_note(note, "Shënimet e regjistrimit")] if note else []}


async def meeting_for_note(db, note_id):
    for source, lookup in (
        ("discord", select(Voice.id).where(Voice.saved_note_id == note_id,
            Voice.status.in_(mira_memory.RECORD_STATUSES))),
        ("host", select(HostEvent.meeting_id).where(HostEvent.note_id == note_id,
            HostEvent.kind.in_(HOST_NOTE_KINDS), HostEvent.meeting_id.is_not(None))),
        ("desktop", select(Desktop.id).where(Desktop.note_id == note_id)),
    ):
        meeting_id = await db.scalar(lookup.limit(1))
        if meeting_id:
            if source == "host":
                host = await db.get(Host, meeting_id)
                voice_id = await voice_for_host(db, host) if host else None
                if voice_id:
                    return {"id": str(voice_id), "source": "discord"}
            return {"id": str(meeting_id), "source": source}
    note = await db.scalar(unlinked_notes().where(GaNote.id == note_id))
    if note:
        return {"archived_note": archived_note(note)}
    raise HTTPException(404, "Takimi burim nuk u gjet.")
