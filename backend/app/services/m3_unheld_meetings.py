"""Canceled INT/EXT occurrences and their day-scoped M3 planning comments."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.services.meetings_report import (
    _clean_task_title, _linked_external_meeting, _local_time, _meeting_occurs_on_date, _meeting_origin_label,
)
from app.services.meeting_palette import meeting_report_color
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting

MEETING_TITLE = "4. TAK INT/EXT TË ANULUARA"
MEETING_COLUMNS = [
    ("nr", "NR", 32), ("time", "KOHA", 55), ("held", "MBAJTUR?", 75),
    ("title", "TITULLI", 420), ("planning_comment", "KUR PLANIFIKOHEN?", 300),
]
CANCELED_STATUSES = {"canceled", "cancelled"}


def is_meeting_comment_key(key: str) -> bool:
    if not key.startswith("meeting_plan:"):
        return False
    try:
        uuid.UUID(key.removeprefix("meeting_plan:"))
    except ValueError:
        return False
    return True


def meeting_appearance(meeting, external_by_id: dict) -> dict:
    linked = _linked_external_meeting(meeting, external_by_id)
    color = meeting_report_color(linked, meeting_type="external") if linked else meeting_report_color(meeting)
    relation = None
    if meeting.meeting_type == "internal":
        if getattr(meeting, "pre_external_meeting_id", None):
            relation = "PARA"
        elif getattr(meeting, "paired_external_meeting_id", None):
            relation = "PAS"
    return {"meeting_relation": relation, "origin": _meeting_origin_label(meeting, linked_external=linked), "fill": color,
            "highlighted": str(meeting.recurrence_type or "").lower() not in {"daily", "weekly"}}


async def add_saved_meeting_appearance(db: AsyncSession, data: dict) -> dict:
    """Fill missing presentation fields without changing the saved report or comments."""
    rows = data.get("unheld_meetings") or []
    missing = [row for row in rows if "meeting_relation" not in row or not row.get("fill")
               or any(key not in row or row[key] is None for key in ("origin", "highlighted"))]
    ids = set()
    for row in missing:
        try:
            ids.add(uuid.UUID(str(row["meeting_id"])))
        except (KeyError, TypeError, ValueError):
            pass
    if not ids:
        return data
    meetings = (await db.execute(select(Meeting).where(Meeting.id.in_(ids)))).scalars().all()
    loaded = {meeting.id for meeting in meetings}
    parent_ids = {parent_id for meeting in meetings
                  for parent_id in (getattr(meeting, "paired_external_meeting_id", None),
                                    getattr(meeting, "pre_external_meeting_id", None))
                  if parent_id and parent_id not in loaded}
    if parent_ids:
        meetings += (await db.execute(select(Meeting).where(Meeting.id.in_(parent_ids)))).scalars().all()
    external_by_id = {str(meeting.id): meeting for meeting in meetings if meeting.meeting_type == "external"}
    appearances = {str(meeting.id): meeting_appearance(meeting, external_by_id) for meeting in meetings}
    missing_ids = {str(row.get("meeting_id")) for row in missing}
    return {**data, "unheld_meetings": [
        {**row, **appearances[str(row["meeting_id"])]}
        if str(row.get("meeting_id")) in missing_ids and str(row.get("meeting_id")) in appearances else row
        for row in rows
    ]}


def select_unheld_meetings(meetings, statuses: dict, day: date) -> list[dict]:
    rows = []
    external_by_id = {str(meeting.id): meeting for meeting in meetings if meeting.meeting_type == "external"}
    for meeting in meetings:
        kind = str(meeting.meeting_type or "").strip().lower()
        status = str(statuses.get(meeting.id) or "").strip().lower()
        if (kind not in {"internal", "external"} or not meeting.starts_at or status not in CANCELED_STATUSES
                or not is_common_view_visible_meeting(meeting) or not _meeting_occurs_on_date(meeting, day)):
            continue
        rows.append({"meeting_id": str(meeting.id), "occurrence_date": day.isoformat(),
                     "meeting_type": "INT" if kind == "internal" else "EXT", "title": _clean_task_title(meeting.title),
                     "time": _local_time(meeting.starts_at), "status": status, "status_label": "Anuluar",
                     **meeting_appearance(meeting, external_by_id)})
    return sorted(rows, key=lambda row: (row["time"], row["meeting_type"], row["title"].casefold(), row["meeting_id"]))


async def build_unheld_meetings(db: AsyncSession, day: date) -> list[dict]:
    meetings = (await db.execute(select(Meeting).where(
        Meeting.starts_at.is_not(None), Meeting.meeting_type.in_(["internal", "external"])
    ))).scalars().all()
    statuses = (await db.execute(select(MeetingOccurrenceStatus).where(
        MeetingOccurrenceStatus.occurrence_date == day
    ))).scalars().all()
    return select_unheld_meetings(meetings, {item.meeting_id: item.status for item in statuses}, day)


def meeting_rows(report: dict) -> list[dict]:
    answers = report.get("manual_answers") or {}
    return [{**row, "planning_comment": answers.get(f"meeting_plan:{row['meeting_id']}") or "-"}
            for row in (report.get("data") or {}).get("unheld_meetings", [])
            if str(row.get("status") or "").strip().lower() in CANCELED_STATUSES
            and row.get("occurrence_date") == report.get("report_date")]


def meeting_groups(report: dict) -> list[tuple[str, list[dict]]]:
    rows = meeting_rows(report)
    return [("TAK EXTERNE", [row for row in rows if row.get("meeting_type") == "EXT"]),
            ("TAK INTERNE", [row for row in rows if row.get("meeting_type") == "INT"])]


def meeting_values(row: dict, index: int) -> list[str]:
    relation = f"[{row['meeting_relation']}] " if row.get("meeting_relation") in {"PARA", "PAS"} else ""
    title = relation + (f"[{row['origin']}] " if row.get("origin") else "") + str(row.get("title") or "-")
    return [str(index), str(row.get("time") or "-"), "✕", title, str(row.get("planning_comment") or "-")]


def meeting_cells(row: dict, index: int) -> list[dict]:
    cells = []
    for column, value in enumerate(meeting_values(row, index)):
        status = column == 2
        title = column == 3
        cells.append({"text": value, "fill": "#fee2e2" if status else row.get("fill") or "#DCECFF",
                      "color": "#991b1b" if status else "#1d4ed8" if title and row.get("highlighted") else "#111827",
                      "bold": status or bool(title and row.get("highlighted")), "divider": False,
                      "meeting_highlight": bool(row.get("highlighted")), "first": column == 0,
                      "last": column == len(MEETING_COLUMNS) - 1})
    return cells
