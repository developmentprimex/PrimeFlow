from __future__ import annotations

from app.services.report_attendance import load_report_attendance

import json
import uuid
from datetime import date
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.department import Department
from app.models.enums import UserRole
from app.models.user import User
from app.services.daily_rlz_compliance import (
    REASON_LABELS,
    build_daily_rlz_compliance,
)
from app.services.daily_realization_live import build_live_daily_realization
from app.services.daily_realization_metrics import calculate_daily_metrics


REPORT_VARIANTS = {"PRECHECK", "FINAL", "CORRECTION"}


def _summary(people: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [task for person in people for task in person.get("tasks", [])]
    metrics = calculate_daily_metrics(rows)
    return {
        **metrics,
        "departments_checked": len({person["department_id"] for person in people}),
        "employees_checked": len(people),
        "employees_not_saved": sum(person["rlz_close_state"]["status"] not in {"SAVED", "CLOSED"} for person in people),
        "employees_stale": sum(person["rlz_close_state"]["status"] == "STALE" for person in people),
        "employees_approval_pending": sum(person["manager_approval"]["status"] in {"PENDING", "REVOKED"} for person in people),
        "employees_approval_stale": sum(person["manager_approval"]["status"] == "STALE" for person in people),
        "tasks_missing_reason": sum("MISSING_REASON" in task.get("issues", []) for task in rows),
        "tasks_missing_comment": sum("MISSING_REQUIRED_COMMENT" in task.get("issues", []) for task in rows),
        "tasks_deadline_not_moved": sum("DUE_DATE_NOT_MOVED" in task.get("issues", []) for task in rows),
        "tasks_missing_slot": sum("ONE_H_SLOT_MISSING" in task.get("issues", []) for task in rows),
    }


async def _build_authoritative_report(db: AsyncSession, *, day: date, variant: str) -> dict[str, Any]:
    """Adapt the live Daily Realization domain for delivery without recalculation."""
    users = (await db.execute(select(User).where(User.work_staff_filter()).where(
        User.is_active.is_(True), User.department_id.is_not(None), User.role == UserRole.STAFF,
    ).order_by(User.department_id, User.full_name, User.email))).scalars().all()
    policy = await load_report_attendance(db, day)
    users = [user for user in users if not policy.excludes(user.id)]
    users_by_id = {user.id: user for user in users}
    department_ids = sorted({user.department_id for user in users if user.department_id}, key=str)
    department_names = {
        row.id: row.name for row in (await db.execute(
            select(Department).where(Department.id.in_(department_ids))
        )).scalars().all()
    } if department_ids else {}
    live_people: dict[uuid.UUID, dict[str, Any]] = {}
    baseline_available: dict[uuid.UUID, bool] = {}
    for department_id in department_ids:
        live = await build_live_daily_realization(db, department_id=department_id, day=day)
        for person in live.get("people", []):
            try:
                person_id = uuid.UUID(str(person["user_id"]))
            except (KeyError, ValueError):
                continue
            if person_id in users_by_id:
                live_people[person_id] = person
                baseline_available[person_id] = bool(live.get("baseline_available"))

    people: list[dict[str, Any]] = []
    for user in users:
        live_person = live_people.get(user.id, {"tasks": [], "metrics": calculate_daily_metrics([])})
        compliance = await build_daily_rlz_compliance(db, user_id=user.id, day=day)
        evidence = {str(item["task_id"]): item for item in compliance.get("tasks", [])}
        blocker_codes = {
            str(item["task_id"]): [issue["code"] for issue in item.get("issues", [])]
            for item in compliance.get("blockers", [])
        }
        tasks: list[dict[str, Any]] = []
        for task in live_person.get("tasks", []):
            item = evidence.get(str(task["task_id"]), {})
            issues = list(dict.fromkeys([*task.get("issues", []), *blocker_codes.get(str(task["task_id"]), [])]))
            tasks.append({
                **task,
                "status": task.get("current_status"),
                "planned_today": bool(task.get("in_original_plan")),
                "completed_today": task.get("classification") in {
                    "REALIZED_AS_PLANNED", "ADDITIONAL_COMPLETED", "COMPLETED_LATE", "COMPLETED_EARLY",
                },
                "extra": not bool(task.get("in_original_plan")),
                "postponed": bool(task.get("postponed_today")),
                "planned_due_date": task.get("baseline_due_date"),
                "due_date": task.get("current_due_date"),
                "reason_label": item.get("reason_label") or REASON_LABELS.get(task.get("reason_code")),
                "one_h_report_slot": item.get("one_h_report_slot") or task.get("one_h_report_slot"),
                "issues": issues,
                "flags": issues,
            })
        metrics = dict(live_person.get("metrics") or calculate_daily_metrics(tasks))
        close_state = compliance["rlz_close_state"]
        if close_state.get("closed_by_user_id") == str(user.id):
            close_state = {**close_state, "closed_by_name": user.full_name or user.username or user.email}
        approval = compliance["manager_approval"]
        control_state = metrics.get("daily_control_state", "CLEAN_DAY")
        if compliance.get("blockers") or close_state["status"] not in {"SAVED", "CLOSED"} or approval.get("status") not in {"APPROVED", "NOT_REQUIRED"}:
            control_state = "ACTION_REQUIRED"
        metrics["daily_control_state"] = control_state
        people.append({
            "user_id": str(user.id), "employee": user.full_name or user.username or user.email,
            "department_id": str(user.department_id), "department": department_names.get(user.department_id, "—"),
            "snapshot_available": baseline_available.get(user.id, False),
            "rlz_close_state": close_state, "manager_approval": approval,
            "daily_progress_percent": metrics.get("raw_plan_realization") or 0,
            "weekly_progress_percent": 0, "metrics": metrics, "control_state": control_state,
            "tasks": tasks, "blockers": compliance.get("blockers") or [], "narrative": None, "risks": [],
        })
    summary = _summary(people)
    if any(person["control_state"] == "ACTION_REQUIRED" for person in people):
        summary["daily_control_state"] = "ACTION_REQUIRED"
    return {
        "content_version": 3, "variant": variant, "day": day.isoformat(),
        "summary": summary, "people": people,
        "all_good": summary["daily_control_state"] == "CLEAN_DAY",
        "narrative": None, "ai": {"status": "DETERMINISTIC", "model": None},
    }


async def build_daily_realization_report(
    db: AsyncSession,
    *,
    day: date,
    variant: str = "FINAL",
) -> dict[str, Any]:
    variant = variant.upper()
    if variant not in REPORT_VARIANTS:
        raise ValueError(f"Unsupported Daily RLZ report variant: {variant}")

    return await _build_authoritative_report(db, day=day, variant=variant)

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["user_id", "summary", "risks"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "people"],
    "additionalProperties": False,
}


def _output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    for output in payload.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    raise ValueError("OpenAI response did not contain output_text")


async def add_optional_ai_narrative(report: dict[str, Any]) -> dict[str, Any]:
    if (
        report.get("variant") != "FINAL"
        or not settings.REALIZATION_DAILY_REPORT_AI_ENABLED
        or not settings.OPENAI_API_KEY
    ):
        return report
    safe_people = []
    for person in report.get("people") or []:
        safe_people.append({
            "user_id": person["user_id"],
            "daily_progress_percent": person["daily_progress_percent"],
            "weekly_progress_percent": person["weekly_progress_percent"],
            "rlz_state": person["rlz_close_state"]["status"],
            "manager_approval": person["manager_approval"]["status"],
            "tasks": [
                {
                    "task_id": task["task_id"],
                    "title": task["title"],
                    "status": task["status"],
                    "reason": task["reason_label"],
                    "comment": task["comment"],
                    "flags": task["flags"],
                }
                for task in person["tasks"]
            ],
        })
    request = {
        "model": settings.REALIZATION_DAILY_REPORT_AI_MODEL,
        "store": False,
        "reasoning": {"effort": "none"},
        "input": [
            {"role": "system", "content": (
                "Summarize the supplied deterministic PrimeFlow daily realization facts in concise Albanian. "
                "Never invent facts, scores, reasons, or task states. Names are intentionally absent. "
                "Mention completed work, unfinished work, extras, carryover and postponements only when present."
            )},
            {"role": "user", "content": json.dumps({"summary": report["summary"], "people": safe_people}, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_schema", "name": "daily_realization_narrative", "strict": True, "schema": NARRATIVE_SCHEMA}},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.REALIZATION_DAILY_REPORT_AI_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
                json=request,
            )
        response.raise_for_status()
        narrative = json.loads(_output_text(response.json()))
        by_user = {item["user_id"]: item for item in narrative["people"]}
        report["narrative"] = narrative["summary"]
        for person in report["people"]:
            item = by_user.get(person["user_id"])
            if item:
                person["narrative"] = item["summary"]
                person["risks"] = item["risks"]
        report["ai"] = {
            "status": "AI_GENERATED",
            "model": settings.REALIZATION_DAILY_REPORT_AI_MODEL,
            "prompt_version": 1,
            "store": False,
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        report["ai"] = {
            "status": "DETERMINISTIC_FALLBACK",
            "model": settings.REALIZATION_DAILY_REPORT_AI_MODEL,
            "prompt_version": 1,
            "store": False,
            "error": type(exc).__name__,
        }
    return report


def report_delta(final_report: dict[str, Any], current_report: dict[str, Any]) -> dict[str, Any]:
    before = {
        (person["user_id"], task["task_id"]): task
        for person in final_report.get("people") or []
        for task in person.get("tasks") or []
    }
    before_people = {person["user_id"]: person for person in final_report.get("people") or []}
    changed_people: list[dict[str, Any]] = []
    for person in current_report.get("people") or []:
        changed = []
        current_keys: set[tuple[str, str]] = set()
        for task in person.get("tasks") or []:
            current_keys.add((person["user_id"], task["task_id"]))
            previous = before.get((person["user_id"], task["task_id"]))
            material = {
                key: task.get(key)
                for key in ("status", "due_date", "reason_code", "comment", "one_h_report_slot", "flags", "adjustment_status", "manager_decision")
            }
            old_material = {
                key: previous.get(key)
                for key in material
            } if previous else None
            if previous is None or material != old_material:
                changed.append({**task, "previous": old_material, "change_type": "ADDED" if previous is None else "UPDATED"})
        for (user_id, task_id), previous in before.items():
            if user_id == person["user_id"] and (user_id, task_id) not in current_keys:
                changed.append({**previous, "previous": previous, "change_type": "REMOVED"})
        old_person = before_people.get(person["user_id"]) or {}
        state_changed = any(
            person.get(key) != old_person.get(key)
            for key in ("daily_progress_percent", "weekly_progress_percent", "rlz_close_state", "manager_approval")
        )
        if changed or state_changed:
            changed_people.append({**person, "tasks": changed})
    delta = {**current_report, "variant": "CORRECTION", "people": changed_people}
    delta["summary"] = _summary(changed_people)
    delta["all_good"] = not changed_people
    delta["narrative"] = "Ndryshimet pas raportit të orës 16:40."
    return delta
