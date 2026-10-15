from __future__ import annotations

import html
import re
from typing import Any, Iterable

from pydantic import BaseModel

from app.services.note_markup import parse_marked_note_content
from app.services.personal_task_owner import personal_task_owner


TITLE = "DET ME GA SIPAS PERSONAVE — P / GA / M2 / F / NR"


class GaTaskCounts(BaseModel):
    person: str
    department: str
    personal: int = 0
    ga: int = 0
    m2: int = 0
    physical: int = 0
    total: int = 0


def _initials(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Z]{1,4}", value):
        return value
    return "".join(part[0] for part in re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)).upper()


def build_ga_summary(payload: dict, entries: Iterable[tuple[dict, bool]]) -> list[GaTaskCounts]:
    # Use the same department aliases and Weekly Planner order as Common View.
    from app.services.meetings_report import _weekly_planner_department_code, WEEKLY_PLANNER_DEPARTMENT_ORDER

    departments = {str(row["id"]): row.get("code") or row.get("name")
                   for row in payload.get("departments") or [] if row.get("id") is not None}
    people: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    ids: dict[str, str] = {}
    excluded_names: set[str] = set()
    excluded_ids: set[str] = set()
    for user in payload.get("users") or []:
        if user.get("is_active") is False or str(user.get("role") or "").upper() == "ADMIN":
            excluded_ids.add(str(user.get("id")))
            excluded_names.update(str(value).strip().casefold() for value in (
                user.get("full_name"), user.get("username"), user.get("email"),
                _initials(str(user.get("full_name") or "")),
            ) if value)
            continue
        name = str(user.get("full_name") or user.get("username") or user.get("email") or "")
        person = _initials(name)
        department = _weekly_planner_department_code(str(user.get("department_id") or ""), departments)
        if not person or department not in WEEKLY_PLANNER_DEPARTMENT_ORDER:
            continue
        key = str(user.get("id") or name.casefold())
        order = user.get("weekly_planner_sort_order")
        people[key] = {"person": person, "department": department,
                       "sort": (WEEKLY_PLANNER_DEPARTMENT_ORDER[department], department.casefold(),
                                order is None, int(order or 0), name.casefold()), "sets": {}}
        ids[str(user.get("id"))] = key
        for value in (name, person, user.get("username"), user.get("email")):
            if value:
                aliases[str(value).strip().casefold()] = key

    for item, personal_bucket in entries:
        marker = str(item.get("one_h_marker") or item.get("oneHMarker") or "").upper()
        title = parse_marked_note_content(str(item.get("title") or item.get("task_title") or "")).text
        is_personal = personal_bucket and item.get("is_personal_task", item.get("isPersonalTask", True)) is not False
        categories = []
        if is_personal and personal_task_owner(title) == "GA":
            categories.append("personal")
        if marker in {"FLAG", "GA"}:
            categories.append("ga")
        if marker in {"M2", "M2_M3"}:
            categories.append("m2")
        if marker == "F":
            categories.append("physical")
        if not categories:
            continue
        owners = item.get("assignees")
        if not isinstance(owners, list) or not owners:
            owner = item.get("employee") or item.get("person") or item.get("owner") or ""
            owners = [part.strip() for part in str(owner).split(",") if part.strip()]
        owner_keys = set()
        for owner in owners:
            name = str(owner).strip()
            if name.casefold() in excluded_names:
                continue
            key = aliases.get(name.casefold()) or aliases.get(_initials(name).casefold())
            if key is None:
                key = ids.get(str(item.get("user_id") or item.get("userId"))) if len(owners) == 1 else None
            if key is None:
                person = _initials(name)
                if not person:
                    continue
                department = _weekly_planner_department_code(str(item.get("department_id") or item.get("departmentId") or ""), departments)
                raw_sort = item.get("weekly_planner_sort") or item.get("weeklyPlannerSort")
                sort = tuple(raw_sort[:5]) if isinstance(raw_sort, (list, tuple)) and len(raw_sort) >= 5 else (
                    WEEKLY_PLANNER_DEPARTMENT_ORDER.get(department, 99), department.casefold(), 1, 10**6, name.casefold())
                key = name.casefold()
                people.setdefault(key, {"person": person, "department": department, "sort": sort, "sets": {}})
                aliases[name.casefold()] = key
            owner_keys.add(key)
        if (not owner_keys and str(item.get("user_id") or item.get("userId")) not in excluded_ids
                and (key := ids.get(str(item.get("user_id") or item.get("userId"))))):
            owner_keys.add(key)
        task_id = str(item.get("task_id") or item.get("taskId") or item.get("id") or id(item))
        for key in owner_keys:
            counts = people[key]["sets"]
            for category in [*categories, "total"]:
                counts.setdefault(category, set()).add(task_id)

    return [GaTaskCounts(person=person["person"],
                         department={"DEV": "ZHV", "GD": "DSG"}.get(person["department"], person["department"]),
                         **{key: len(values) for key, values in person["sets"].items()})
            for person in sorted(people.values(), key=lambda row: row["sort"])
            if person["sets"].get("total")]


def person_counts_text(row: GaTaskCounts) -> str:
    return f"{row.person} ({row.department}): P {row.personal} · GA {row.ga} · M2 {row.m2} · F {row.physical} · NR {row.total}"


def summary_text(rows: list[GaTaskCounts]) -> str:
    return " | ".join(person_counts_text(row) for row in rows)


def summary_html(rows: list[GaTaskCounts]) -> str:
    if not rows:
        return ""
    cells = "".join(
        '<td style="border:1px solid #cbd5e1;padding:7px 9px;vertical-align:top;white-space:nowrap;'
        'font-family:Arial,sans-serif;font-size:11px;background:#eff6ff;color:#0f172a;">'
        f'<strong>{html.escape(row.person)}</strong> <span style="color:#64748b">({html.escape(row.department)})</span><br>'
        f'P {row.personal} · GA {row.ga} · M2 {row.m2} · F {row.physical}<br>'
        f'<strong>NR DET ME GA: {row.total}</strong></td>' for row in rows)
    return ('<div data-ga-task-summary="true" style="margin:12px 0;overflow-x:auto;">'
            f'<div style="font:bold 12px Arial,sans-serif;margin-bottom:5px;">{html.escape(TITLE)}</div>'
            f'<table style="border-collapse:collapse;"><tbody><tr>{cells}</tr></tbody></table></div>')
