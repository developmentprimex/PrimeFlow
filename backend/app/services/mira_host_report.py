"""Speech facts selected and validated by the same document/strike rules as 1H Reports."""
import hashlib
import uuid
from collections import Counter
from datetime import datetime

from app.services.primeflow_report import build_report_document
from app.services.primeflow_report_delivery import report_task_snapshot, report_text_overrides, strike_interval_start, strike_interval_end
from app.services.task_strike_events import struck_points_for_interval


def completion_time(item, zone):
    try:
        value = datetime.fromisoformat(str(item.get("completed_at") or item.get("completedAt") or "").replace("Z", "+00:00"))
        return (value if value.tzinfo else value.replace(tzinfo=zone)).astimezone(zone)
    except ValueError:
        return None


async def progress(db, meeting, data, user_ids=None, *, for_brief=False):
    from app.services import mira_host as host
    start, end = strike_interval_start(meeting.meeting_date, meeting.slot), strike_interval_end(meeting.meeting_date, meeting.slot)
    source = {**data.payload, "items": {}}
    items = {}
    # Keep the report's display rows (including shared assignments), date and slot filters.
    for bucket, values in (data.payload.get("items") or {}).items():
        if not isinstance(values, list):
            source["items"][bucket] = values
            continue
        rows = []
        for raw in values:
            row = dict(raw)
            tid = str(row.get("task_id") or row.get("id") or "")
            owners = data.owners(row)
            row["person"] = row.get("person") or row.get("employee") or ", ".join(data.name(uid) for uid in owners)
            rows.append(row)
            if tid and tid not in items:
                items[tid] = row
            elif tid:
                previous = items[tid]
                items[tid] = {**previous, "assignees": list(dict.fromkeys(
                    [*(previous.get("assignees") or []), *(row.get("assignees") or [])]))}
        source["items"][bucket] = rows
    snapshot = await report_task_snapshot(source, interval_end=end, db=db)
    titles, descriptions = report_text_overrides(snapshot, interval_start=start, interval_end=end)
    document = build_report_document(source, meeting.meeting_date, meeting.slot,
        title_overrides=titles, description_overrides=descriptions,
        completion_window_start=start, completion_window_end=end)
    selected, report_owners = {}, {}
    for section in document.sections:
        for person in section.employees:
            for task in person.tasks:
                selected.setdefault(task.task_id, task)
                report_owners.setdefault(task.task_id, [])
                if person.name not in report_owners[task.task_id]:
                    report_owners[task.task_id].append(person.name)
    if for_brief and meeting.slot == host.BLOCKED_SLOT:
        # Blocked tasks belong to staff follow-up at 16:00, not the GA report announcement.
        for row in data.blocked:
            tid = str(row.get("task_id") or "")
            if tid:
                selected.setdefault(tid, None)
    task_uuids = {}
    for tid in selected:
        try:
            task_uuids[tid] = uuid.UUID(tid)
        except ValueError:
            continue
    title_counts = Counter(host.plain(snapshot["titles"].get(task_uuids[tid], items.get(tid, {}).get("title", ""))).split("\n", 1)[0]
                           for tid in selected if tid in items and tid in task_uuids)
    done, strikes, mentions = [], [], []
    for tid in selected:
        row = items.get(tid)
        if not row:
            continue
        owners = data.owners(row)
        if user_ids is not None and not set(user_ids).intersection(owners):
            continue
        if not tid:
            continue
        task_uuid = task_uuids.get(tid)
        if task_uuid is None:
            continue
        title = snapshot["titles"].get(task_uuid, row.get("title") or "")
        description = snapshot["descriptions"].get(task_uuid, row.get("description"))
        line = host.task_line({**row, "title": title, "description": description})
        if title_counts[host.plain(title).split("\n", 1)[0]] > 1 and description:
            line["spoken"] += ", " + host.plain(description).split("\n", 1)[0][:100]
        line.update(owners=[host.initials(data.name(uid)) for uid in owners] or report_owners.get(tid, []),
                    people=[data.name(uid) for uid in owners] or report_owners.get(tid, []), slot=meeting.slot)
        completed = completion_time(row, end.tzinfo)
        if line["status"] in ("DONE", "COMPLETED"):
            line.update(completed_at=completed.isoformat() if completed else None,
                        at=completed.strftime("%H:%M") if completed else None, time_unknown=completed is None)
            done.append(dict(line))
            mentions.append({"task_id":tid,"kind":"DONE","point_key":"","text":line["title"]})
        points = []
        for field, text in (("TITLE", title), ("DESCRIPTION", description)):
            for point in struck_points_for_interval(text, snapshot["events"].get(task_uuid, []),
                    interval_start=start, interval_end=end, field_name=field):
                occurred = point["occurred_at"]
                occurred = (occurred if occurred.tzinfo else occurred.replace(tzinfo=end.tzinfo)).astimezone(end.tzinfo)
                key = hashlib.sha256(f"{field}:{point['key']}:{occurred.isoformat()}".encode()).hexdigest()
                actor = data.users.get(str(point["actor_user_id"])) or {}
                points.append({"key":key,"field":field,"text":host.plain(point["text"])[:300],
                    "at":occurred.strftime("%H:%M"),"occurred_at":occurred.isoformat(),
                    "actor_user_id":str(point["actor_user_id"]) if point["actor_user_id"] else None,
                    "by":actor.get("full_name")})
        if points:
            strikes.append({**line,"points":points,"strike_count":len(points)})
            mentions.extend({"task_id":tid,"kind":"STRIKE","point_key":p["key"],"text":p["text"]} for p in points)
    return {"done":done,"strikes":strikes,"mentions":mentions,
            "source":"1H_REPORT","interval_start":start.isoformat(),"interval_end":end.isoformat(),
            "strike_count":sum(len(t["points"]) for t in strikes),"done_count":len(done),
            "report_strike_total":document.strike_total}
