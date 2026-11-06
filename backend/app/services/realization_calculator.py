from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RealizationPeriodStatus
from app.models.realization import (
    RealizationDepartmentResult,
    RealizationPeriod,
    RealizationPersonResult,
    RealizationPolicyVersion,
)
from app.services.realization_evidence import collect_weekly_evidence
from app.services.realization_narrative import build_albanian_narrative
from app.services.realization_periods import require_recalculable, transition_period
from app.services.realization_pulse import build_recovery, calculate_pulse
from app.services.realization_policy import evaluate_policy


QUESTION_LABELS = {
    "task_status": "Statusi i detyrave",
    "plan_completed": "A janë përfunduar detyrat sipas planit?",
    "no_progress_tasks": "A ka detyra që nuk kanë pasur fare progres?",
    "in_progress_tasks": "A ka detyra që mbesin në proces edhe për këtë javë?",
    "new_tasks_added": "A i janë shtuar punëtorit detyra të reja gjatë javës?",
    "approved_postponement": "A ka ndryshuar prioriteti ose ka shtyrje me konfirmim?",
    "requested_extra_tasks": "Kërkoi detyra shtesë?",
    "helped_colleague": "Ndihmoi koleg?",
    "extra_engagement": "A pati detyra ekstra?",
    "gave_proposal": "Dha propozim?",
    "respected_meetings": "Respektoi takimet?",
    "closed_tasks": "Mbylli detyrat?",
    "frequent_delays": "Vonesa të shpeshta?",
    "unexpected_absences": "Mungesa të papritura?",
    "week_positive": "A solli diçka pozitive?",
    "week_problems": "A shkaktoi problem te kolegu ose në punë?",
    "affected_other_plan": "A ja ka prishur dikujt tjetër planin?",
    "repeated_after_clarification": "A ka pasur përsëritje të detyrave edhe pas sqarimeve?",
    "current_level": "Niveli",
    "suggested_evaluation_level": "Propozimi për nivelin e vlerësimit",
    "evaluation": "Vlerësimi",
    "comments": "Komente",
}

REPORT_QUESTION_SECTIONS = [
    (
        "1. DETYRAT",
        [
            "plan_completed",
            "no_progress_tasks",
            "in_progress_tasks",
            "new_tasks_added",
            "approved_postponement",
        ],
    ),
    (
        "2. ANGAZHIMI",
        ["requested_extra_tasks", "helped_colleague", "extra_engagement", "gave_proposal"],
    ),
    (
        "3. DISIPLINA DHE PËRGJEGJËSIA",
        ["respected_meetings", "closed_tasks", "frequent_delays", "unexpected_absences"],
    ),
    (
        "4. NDIKIMI POZITIV / NEGATIV",
        ["week_positive", "week_problems", "affected_other_plan", "repeated_after_clarification"],
    ),
]

MANUAL_BOOLEAN_QUESTION_KEYS = {
    "approved_postponement",
    "respected_meetings",
    "requested_extra_tasks",
    "helped_colleague",
    "gave_proposal",
    "week_positive",
    "week_problems",
    "affected_other_plan",
    "repeated_after_clarification",
}
MANUAL_TEXT_QUESTION_KEYS: set[str] = set()
MANDATORY_MANUAL_QUESTION_KEYS = (
    MANUAL_BOOLEAN_QUESTION_KEYS | MANUAL_TEXT_QUESTION_KEYS
)


def missing_manual_question_keys(answered_keys: set[str]) -> list[str]:
    return sorted(MANDATORY_MANUAL_QUESTION_KEYS - answered_keys)


def _question(
    key: str,
    auto_value: Any,
    *,
    source_status: str = "AUTO",
    evidence_ids: list[str] | None = None,
    explanation: str = "",
    answer_type: str = "value",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": QUESTION_LABELS[key],
        "answer_type": answer_type,
        "auto_value": auto_value,
        "final_value": None,
        "source_status": source_status,
        "evidence_ids": evidence_ids or [],
        "explanation": explanation,
    }


def _manual_question(
    key: str,
    auto_facts: Any,
    *,
    evidence_ids: list[str] | None = None,
    explanation: str = "",
    source_status: str | None = None,
    answer_type: str | None = None,
) -> dict[str, Any]:
    """Manager judgment stays manual; automatic facts are supporting context only."""
    return _question(
        key,
        auto_facts,
        source_status="MANUAL_UNANSWERED",
        evidence_ids=evidence_ids,
        explanation=explanation,
        answer_type="text" if key in MANUAL_TEXT_QUESTION_KEYS else "boolean",
    )


def build_live_questions(person: dict[str, Any]) -> list[dict[str, Any]]:
    """Build all reference questions from live daily facts without guessing."""
    counters = person.get("counters") or {}
    tasks = person.get("tasks") or []
    observations = person.get("observations") or []
    timeline = person.get("daily_timeline") or []
    verified = [item for item in observations if item.get("verified") is True]
    positive = [item for item in verified if item.get("marker") in {"POSITIVE", "DIAMOND"}]
    negative = [item for item in verified if item.get("marker") == "NEGATIVE"]

    def ids(items: list[dict[str, Any]]) -> list[str]:
        return [str(item["id"]) for item in items if item.get("id")]

    def category(items: list[dict[str, Any]], value: str) -> list[dict[str, Any]]:
        return [item for item in items if item.get("category") == value]

    task_ids = sorted({str(item["task_id"]) for item in tasks if item.get("task_id")})
    added_ids = sorted(
        {
            str(item["task_id"])
            for item in tasks
            if item.get("task_id")
            and item.get("attribution") == "added_after_weekly_plan"
        }
    )
    def count(name: str, fallback: int = 0) -> int:
        return int(person.get(name, counters.get(name, fallback)) or 0)

    question_scope = str(person.get("question_scope") or "").upper()
    is_daily = question_scope == "DAILY" or (
        not question_scope and bool(person.get("date"))
    )
    weekly_planned = count(
        "daily_planned_count" if is_daily else "weekly_planned_count"
    )
    weekly_completed = count(
        "daily_completed_count" if is_daily else "weekly_completed_count"
    )
    weekly_added = (
        int(counters.get("additional_count", 0) or 0)
        if is_daily
        else count("weekly_additional_count")
    )
    additional_completed = count(
        "additional_completed_count" if is_daily else "weekly_additional_completed_count"
    )
    additional_in_progress = count(
        "additional_in_progress_count" if is_daily else "weekly_additional_in_progress_count"
    )
    additional_no_progress = count(
        "additional_no_progress_count" if is_daily else "weekly_additional_no_progress_count",
        max(0, weekly_added - additional_completed - additional_in_progress),
    )
    additional_postponed = count(
        "additional_postponed_count" if is_daily else "weekly_additional_postponed_count"
    )
    additional_todo = count(
        "additional_todo_count" if is_daily else "weekly_additional_todo_count",
        max(
            0,
            weekly_added
            - additional_completed
            - additional_in_progress
            - additional_postponed,
        ),
    )
    no_progress_count = (
        int(counters.get("no_progress_count", 0) or 0)
        if is_daily
        else count("weekly_no_progress_count", int(counters.get("no_progress_count", 0) or 0))
    )
    in_progress_count = (
        int(counters.get("in_progress_count", 0) or 0)
        if is_daily
        else count("weekly_in_progress_count", int(counters.get("in_progress_count", 0) or 0))
    )

    timeline_attendance = [
        item
        for snapshot in timeline
        for item in snapshot.get("attendance") or []
    ]
    raw_attendance = person.get("attendance") or []
    if isinstance(raw_attendance, dict):
        fallback_attendance = [
            {"id": str(attendance_id), **(item if isinstance(item, dict) else {})}
            for attendance_id, item in raw_attendance.items()
        ]
    elif isinstance(raw_attendance, list):
        fallback_attendance = [item for item in raw_attendance if isinstance(item, dict)]
    else:
        fallback_attendance = []
    attendance = timeline_attendance or fallback_attendance
    tardiness = sum(
        str(item.get("type") or "").upper() == "VONESE" for item in attendance
    )
    delay_threshold = 1 if is_daily else 3
    raw_absences = [
        item
        for item in attendance
        if str(item.get("type") or "").upper() == "MUNGESE"
    ]
    verified_absences = category(verified, "ABSENCE")

    def _day_key(value: object) -> str | None:
        if value is None:
            return None
        isoformat = getattr(value, "isoformat", None)
        if callable(isoformat):
            try:
                return str(isoformat())[:10]
            except TypeError:
                return None
        text = str(value).strip()
        return text[:10] if text else None

    excused_days: set[str] = set()
    unexcused_observation_days: set[str] = set()
    for item in verified_absences:
        classification = str(
            (item.get("evidence_json") or {}).get("classification") or ""
        ).upper()
        evidence = item.get("evidence_json") or {}
        day_key = _day_key(
            evidence.get("date") or evidence.get("occurrence_date") or item.get("relevant_date")
        )
        if not day_key:
            continue
        if classification in {"APPROVED_PERSONAL", "ANNUAL_LEAVE"}:
            excused_days.add(day_key)
        elif classification == "UNEXCUSED":
            unexcused_observation_days.add(day_key)
    attendance_absence_days = {
        day_key
        for item in raw_absences
        if (day_key := _day_key(item.get("date")))
    }
    undated_absences = sum(1 for item in raw_absences if not _day_key(item.get("date")))
    unexpected_absences = (
        len((attendance_absence_days | unexcused_observation_days) - excused_days)
        + undated_absences
    )
    requested = [
        item
        for item in category(positive, "EXTRA_TASK")
        if (item.get("evidence_json") or {}).get("kind") == "REQUESTED_EXTRA_TASK"
    ]
    helped = category(positive, "HELPED_COLLEAGUE")
    proposals = category(positive, "PROPOSAL")
    missed_meetings = category(negative, "MISSED_MEETING")
    blockers = [
        item
        for item in category(negative, "BLOCKER")
        if (item.get("evidence_json") or {}).get("affected_user_id")
    ]
    repeated = category(negative, "REPEATED_PROBLEM")
    positive_comments = [
        str(item["comment"]).strip()
        for item in positive
        if item.get("comment") and str(item["comment"]).strip()
    ]
    problem_comments = [
        str(item["comment"]).strip()
        for item in negative
        if item.get("comment") and str(item["comment"]).strip()
    ]
    postponements = [item for item in tasks if item.get("postponement")]
    approved = [
        item for item in postponements if item.get("postponement") == "approved_postponement"
    ]
    unapproved = [
        item
        for item in postponements
        if item.get("postponement") in {"unapproved_postponement", "rejected_postponement"}
    ]
    postponement_ids = sorted(
        {
            str(evidence_id)
            for item in postponements
            for evidence_id in item.get("postponement_evidence_ids") or []
        }
    )

    return [
        _question(
            "plan_completed",
            {
                "answer": weekly_planned > 0 and weekly_completed >= weekly_planned,
                "planned": weekly_planned,
                "completed": weekly_completed,
                "remaining": max(0, weekly_planned - weekly_completed),
            },
            evidence_ids=task_ids,
            answer_type="object",
        ),
        _question(
            "no_progress_tasks",
            {"answer": no_progress_count > 0, "count": no_progress_count},
            evidence_ids=task_ids,
            answer_type="object",
        ),
        _question(
            "in_progress_tasks",
            {"answer": in_progress_count > 0, "count": in_progress_count},
            evidence_ids=task_ids,
            answer_type="object",
        ),
        _question(
            "new_tasks_added",
            {
                "yes": weekly_added > 0,
                "total": weekly_added,
                "completed": additional_completed,
                "in_progress": additional_in_progress,
                "todo": additional_todo,
                "postponed": additional_postponed,
            },
            evidence_ids=added_ids,
            answer_type="object",
        ),
        _manual_question(
            "approved_postponement",
            {
                "approved": len(approved),
                "unapproved": len(unapproved),
            },
            evidence_ids=postponement_ids,
            explanation="Numrat e aprovuar dhe pa aprovim janë fakte automatike; PËRGJIGJA Po/Jo jepet nga menaxheri.",
        ),
        _manual_question(
            "requested_extra_tasks",
            bool(requested),
            evidence_ids=ids(requested),
            answer_type="boolean",
        ),
        _manual_question(
            "helped_colleague",
            bool(helped),
            evidence_ids=ids(helped),
            answer_type="boolean",
        ),
        _question(
            "extra_engagement",
            {
                "answer": weekly_added > 0,
                "total": weekly_added,
                "completed": additional_completed,
                "in_progress": additional_in_progress,
                "no_progress": additional_no_progress,
            },
            evidence_ids=added_ids,
            answer_type="object",
        ),
        _manual_question(
            "gave_proposal",
            bool(proposals),
            evidence_ids=ids(proposals),
            answer_type="boolean",
        ),
        _manual_question(
            "respected_meetings",
            {"missed_meeting_evidence": len(missed_meetings)},
            evidence_ids=ids(missed_meetings),
            explanation="Ka evidencë për takim të humbur." if missed_meetings else "",
            answer_type="boolean",
        ),
        _question(
            "closed_tasks",
            {
                "all_closed": weekly_planned > 0 and weekly_completed >= weekly_planned,
                "closed": weekly_completed,
                "planned": weekly_planned,
                "remaining": max(0, weekly_planned - weekly_completed),
            },
            evidence_ids=task_ids,
            explanation="Gjendje operative deri në snapshot-in e fundit, jo FINAL.",
            answer_type="object",
        ),
        _question(
            "frequent_delays",
            {
                "answer": tardiness >= delay_threshold,
                "attendance_tardiness": tardiness,
                "frequent": tardiness >= delay_threshold,
                "threshold": delay_threshold,
            },
            evidence_ids=[str(item.get("id")) for item in attendance if item.get("id")],
            answer_type="object",
        ),
        _question(
            "unexpected_absences",
            unexpected_absences,
            evidence_ids=[
                *[str(item.get("id")) for item in raw_absences if item.get("id")],
                *ids(verified_absences),
            ],
            answer_type="integer",
        ),
        _manual_question(
            "week_positive",
            positive_comments,
            evidence_ids=ids(positive),
            answer_type="list",
        ),
        _manual_question(
            "week_problems",
            problem_comments,
            evidence_ids=ids(negative),
            answer_type="list",
        ),
        _manual_question(
            "affected_other_plan",
            bool(blockers),
            evidence_ids=ids(blockers),
            answer_type="boolean",
        ),
        _manual_question(
            "repeated_after_clarification",
            bool(repeated),
            evidence_ids=ids(repeated),
            explanation="Kërkon problemin, sqarimin paraprak dhe koment.",
            answer_type="boolean",
        ),
    ]


def build_daily_questions_from_live(
    stored_facts: dict[str, Any], live_person: dict[str, Any]
) -> list[dict[str, Any]]:
    """Use the Daily table's baseline and outcomes for automatic questions.

    Manual answers remain sourced from the saved checklist. This prevents an
    older weekly-snapshot calculation from disagreeing with the immutable daily
    baseline shown in the staff table.
    """
    metrics = live_person.get("metrics") or {}
    live_tasks = live_person.get("tasks") or []
    question_tasks = []
    for raw in live_tasks:
        task = dict(raw)
        task["attribution"] = (
            "planned_today" if task.get("in_original_plan") else "added_after_weekly_plan"
        )
        classification = str(task.get("classification") or "").upper()
        if classification == "POSTPONED_APPROVED":
            task["postponement"] = "approved_postponement"
        elif classification == "POSTPONED_UNAPPROVED":
            task["postponement"] = "unapproved_postponement"
        question_tasks.append(task)

    counters = dict(stored_facts.get("counters") or {})
    extra_postponed_count = sum(
        not task.get("in_original_plan")
        and str(task.get("classification") or "").upper().startswith("POSTPONED_")
        for task in live_tasks
    )
    extra_todo_count = max(
        0,
        int(metrics.get("additional_count") or 0)
        - int(metrics.get("additional_completed_count") or 0)
        - int(metrics.get("additional_in_progress_count") or 0)
        - extra_postponed_count,
    )
    counters.update({
        "planned_count": int(metrics.get("original_planned_count") or 0),
        "completed_count": int(metrics.get("planned_completed_today_count") or 0),
        "additional_count": int(metrics.get("additional_count") or 0),
        "additional_completed_count": int(
            metrics.get("additional_completed_count") or 0
        ),
        "additional_in_progress_count": int(
            metrics.get("additional_in_progress_count") or 0
        ),
        "additional_no_progress_count": int(
            metrics.get("additional_no_progress_count") or 0
        ),
        "additional_postponed_count": extra_postponed_count,
        "additional_todo_count": extra_todo_count,
        "in_progress_count": int(metrics.get("in_progress_count") or 0),
        "no_progress_count": int(metrics.get("no_progress_count") or 0),
    })
    live_facts = {
        **stored_facts,
        "question_scope": "DAILY",
        "tasks": question_tasks,
        "counters": counters,
        "daily_planned_count": counters["planned_count"],
        "daily_completed_count": counters["completed_count"],
    }
    if live_person.get("attendance"):
        live_facts["attendance"] = live_person["attendance"]
    fresh_questions = build_live_questions(live_facts)
    saved_manual = {
        str(question.get("key")): question
        for question in stored_facts.get("questions") or []
        if str(question.get("source_status") or "").startswith("MANUAL")
    }
    return [
        saved_manual.get(str(question.get("key")), question)
        if str(question.get("source_status") or "").startswith("MANUAL")
        else question
        for question in fresh_questions
    ]


def build_questions(person: dict[str, Any], decision: Any, narrative: str) -> list[dict[str, Any]]:
    c = person["counters"]
    tasks = person["tasks"]
    observations = person["observations"]
    verified = [item for item in observations if item["verified"]]
    additional_ids = [
        str(item["task_id"])
        for item in tasks
        if str(item["classification"]).startswith("additional_") and item.get("task_id")
    ]
    planned_task_ids = sorted(
        {
            str(item["task_id"])
            for item in tasks
            if item.get("attribution") == "planned_owner" and item.get("task_id")
        }
    )
    postponement_evidence_ids = sorted(
        {
            evidence_id
            for item in tasks
            for evidence_id in item.get("postponement_evidence_ids") or []
        }
    )
    meeting_task_ids = sorted(
        {
            str(item["task_id"])
            for item in tasks
            if item.get("meeting_origin_id") and item.get("task_id")
        }
    )
    absence_evidence_ids = sorted(
        attendance_id
        for attendance_id, item in (person.get("attendance") or {}).items()
        if item.get("type") == "MUNGESE"
    )
    verified_ids = [str(item["id"]) for item in verified]
    positive = [item for item in verified if item["marker"] in {"POSITIVE", "DIAMOND"}]
    negative = [item for item in verified if item["marker"] == "NEGATIVE"]
    requested = [
        item for item in positive
        if item["category"] == "EXTRA_TASK"
        and (item.get("evidence_json") or {}).get("kind") == "REQUESTED_EXTRA_TASK"
    ]
    helped = [item for item in positive if item["category"] == "HELPED_COLLEAGUE"]
    proposals = [item for item in positive if item["category"] == "PROPOSAL"]
    blockers = [
        item for item in negative
        if item["category"] == "BLOCKER"
        and (item.get("evidence_json") or {}).get("affected_user_id")
    ]
    repeated = [item for item in negative if item["category"] == "REPEATED_PROBLEM"]
    missed_meetings = [item for item in negative if item["category"] == "MISSED_MEETING"]
    planned_count = int(c.get("planned_count", 0) or 0)
    completed_count = int(c.get("completed_on_time_count", 0) or 0) + int(
        c.get("completed_late_count", 0) or 0
    )
    no_progress_count = int(c.get("no_progress_count", 0) or 0)
    in_progress_count = int(c.get("in_progress_count", 0) or 0)
    closed = (
        c.get("planned_count", 0) == c.get("accounted_planned_count", 0)
    )
    absence_needs_review = c.get("absence_needs_review_count", 0)
    questions = [
        _question(
            "plan_completed",
            {
                "answer": planned_count > 0 and completed_count >= planned_count,
                "planned": planned_count,
                "completed": completed_count,
                "remaining": max(0, planned_count - completed_count),
            },
            evidence_ids=planned_task_ids,
            answer_type="object",
        ),
        _question(
            "no_progress_tasks",
            {"answer": no_progress_count > 0, "count": no_progress_count},
            evidence_ids=planned_task_ids,
            answer_type="object",
        ),
        _question(
            "in_progress_tasks",
            {"answer": in_progress_count > 0, "count": in_progress_count},
            evidence_ids=planned_task_ids,
            answer_type="object",
        ),
        _question(
            "new_tasks_added",
            {
                "yes": bool(c.get("additional_count", 0)),
                "total": c.get("additional_count", 0),
                "completed": c.get("additional_completed_count", 0),
                "in_progress": c.get("additional_in_progress_count", 0),
                "todo": c.get(
                    "additional_todo_count",
                    max(
                        0,
                        int(c.get("additional_count", 0) or 0)
                        - int(c.get("additional_completed_count", 0) or 0)
                        - int(c.get("additional_in_progress_count", 0) or 0)
                        - int(c.get("additional_postponed_count", 0) or 0),
                    ),
                ),
                "postponed": c.get("additional_postponed_count", 0),
                "task_ids": additional_ids,
            },
            evidence_ids=additional_ids,
            answer_type="object",
        ),
        _manual_question(
            "approved_postponement",
            {
                "approved": c.get("approved_postponement_count", 0),
                "unapproved": c.get("unapproved_postponement_count", 0),
                "needs_review": c.get("postponement_needs_review_count", 0),
            },
            evidence_ids=postponement_evidence_ids,
            explanation="Numrat e aprovuar dhe pa aprovim janë fakte automatike; PËRGJIGJA Po/Jo jepet nga menaxheri.",
        ),
        _manual_question(
            "requested_extra_tasks",
            bool(requested),
            evidence_ids=[str(item["id"]) for item in requested],
            answer_type="boolean",
        ),
        _manual_question(
            "helped_colleague",
            bool(helped),
            evidence_ids=[str(item["id"]) for item in helped],
            answer_type="boolean",
        ),
        _question(
            "extra_engagement",
            {
                "answer": int(c.get("additional_count", 0) or 0) > 0,
                "total": int(c.get("additional_count", 0) or 0),
                "completed": int(c.get("additional_completed_count", 0) or 0),
                "in_progress": int(c.get("additional_in_progress_count", 0) or 0),
                "no_progress": int(
                    c.get(
                        "additional_no_progress_count",
                        max(
                            0,
                            int(c.get("additional_count", 0) or 0)
                            - int(c.get("additional_completed_count", 0) or 0)
                            - int(c.get("additional_in_progress_count", 0) or 0),
                        ),
                    )
                    or 0
                ),
            },
            evidence_ids=additional_ids,
            answer_type="object",
        ),
        _manual_question(
            "gave_proposal",
            bool(proposals),
            evidence_ids=[str(item["id"]) for item in proposals],
            answer_type="boolean",
        ),
        _manual_question(
            "respected_meetings",
            {"missed_meeting_evidence": c.get("meeting_missed_count", 0)},
            evidence_ids=sorted(
                set(meeting_task_ids)
                | {str(item["id"]) for item in missed_meetings}
            ),
            explanation=(
                "Ka evidencë të konfirmuar për takim të humbur."
                if c.get("meeting_missed_count", 0)
                else "Pa evidencë për takim të humbur."
            ),
            answer_type="boolean",
        ),
        _question(
            "closed_tasks",
            closed,
            evidence_ids=planned_task_ids,
            answer_type="boolean",
        ),
        _question(
            "frequent_delays",
            {
                "answer": int(c.get("tardiness_count", 0) or 0) >= 3,
                "attendance_tardiness": c.get("tardiness_count", 0),
                "tasks_completed_late": c.get("completed_late_count", 0),
                "tasks_late_open": c.get("late_open_count", 0),
                "threshold": 3,
            },
            answer_type="object",
        ),
        _question(
            "unexpected_absences",
            None if absence_needs_review else c.get("unexcused_absence_days", 0),
            source_status="AUTO_NEEDS_CONFIRMATION" if absence_needs_review else "AUTO",
            evidence_ids=absence_evidence_ids,
            explanation=(
                "Burimi aktual i prezencës nuk dallon mungesën e arsyetuar nga ajo e papritur."
                if absence_needs_review else ""
            ),
            answer_type="integer",
        ),
        _manual_question("week_positive", narrative, evidence_ids=[str(item["id"]) for item in positive]),
        _manual_question(
            "week_problems",
            [item.get("comment") for item in negative if item.get("comment")],
            evidence_ids=[str(item["id"]) for item in negative],
            answer_type="list",
        ),
        _manual_question(
            "affected_other_plan",
            bool(blockers),
            evidence_ids=[str(item["id"]) for item in blockers],
            answer_type="boolean",
        ),
        _manual_question(
            "repeated_after_clarification",
            bool(repeated),
            evidence_ids=[str(item["id"]) for item in repeated],
            answer_type="boolean",
        ),
        _question(
            "current_level",
            "—",
            source_status="NOT_APPLICABLE",
            explanation="Niveli aktual i punonjësit nuk ruhet ende në profil.",
        ),
        _question(
            "suggested_evaluation_level",
            decision.level.value,
            answer_type="level",
        ),
        _question("evaluation", decision.symbol.value, answer_type="symbol"),
        _question(
            "comments",
            {"automatic_narrative": narrative, "manager_comment": None, "override_reason": None},
            evidence_ids=verified_ids,
            answer_type="object",
        ),
    ]
    return questions


COUNTER_FIELDS = {
    "planned_count": "planned_count",
    "completed_on_time_count": "completed_on_time_count",
    "completed_late_count": "completed_late_count",
    "in_progress_count": "in_progress_count",
    "pending_confirmation_count": "pending_count",
    "no_progress_count": "no_progress_count",
    "additional_count": "additional_count",
    "approved_postponement_count": "approved_postponement_count",
    "unapproved_postponement_count": "unapproved_postponement_count",
    "tardiness_count": "tardiness_count",
    "approved_absence_days": "approved_absence_days",
    "unexcused_absence_days": "unexcused_absence_days",
    "diamond_count": "diamond_count",
    "positive_count": "positive_count",
    "negative_count": "negative_count",
    "neutral_count": "neutral_count",
    "proposal_count": "proposal_count",
    "helped_colleague_count": "helped_colleague_count",
    "time_saved_minutes": "time_saved_minutes",
    "repeated_problem_count": "repeated_problem_count",
}


def _task_progress_percent(task: dict[str, Any]) -> float:
    rows = task.get("daily_progress") or []
    usable = [row for row in rows if int(row.get("total_value") or 0) > 0]
    if usable:
        latest = usable[-1]
        completed = int(latest.get("completed_value") or 0)
        total = int(latest["total_value"])
        return round(min(100.0, max(0.0, completed * 100.0 / total)), 1)
    return 100.0 if task.get("classification") in {
        "completed_on_time",
        "completed_late",
        "additional_completed",
    } else 0.0


def build_project_progress(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate MST/TT projects; all other projects remain task-level evidence."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        title = str(task.get("project_title") or "").strip()
        normalized = title.upper()
        if not title or not (
            "MST" in normalized or normalized == "TT" or normalized.startswith("TT ")
        ):
            continue
        key = str(task.get("project_id") or title)
        grouped.setdefault(key, []).append(task)

    projects: list[dict[str, Any]] = []
    for project_key, project_tasks in sorted(grouped.items(), key=lambda item: item[0]):
        percentages = [_task_progress_percent(task) for task in project_tasks]
        projects.append(
            {
                "project_id": project_key,
                "project_title": project_tasks[0].get("project_title") or "MST/TT",
                "task_count": len(project_tasks),
                "progress_percent": round(sum(percentages) / len(percentages), 1),
                "method": "latest_daily_quantity_or_completed_task_average",
                "task_ids": [
                    str(task.get("task_id"))
                    for task in project_tasks
                    if task.get("task_id")
                ],
            }
        )
    return projects


async def calculate_weekly_period(
    db: AsyncSession,
    *,
    period: RealizationPeriod,
    planned_snapshot: Any,
    final_snapshot: Any,
    actor_id: uuid.UUID,
) -> tuple[list[RealizationPersonResult], RealizationDepartmentResult]:
    require_recalculable(period)
    if planned_snapshot is None or final_snapshot is None:
        raise ValueError("PLANNED and FINAL snapshots are required before calculation")
    policy = (
        await db.execute(
            select(RealizationPolicyVersion).where(
                RealizationPolicyVersion.id == period.policy_version_id
            )
        )
    ).scalar_one()
    evidence = await collect_weekly_evidence(
        db,
        period=period,
        planned_snapshot=planned_snapshot,
        final_snapshot=final_snapshot,
        am_cutoff=policy.am_cutoff,
        pm_cutoff=policy.pm_cutoff,
    )
    existing = {
        row.user_id: row
        for row in (
            await db.execute(
                select(RealizationPersonResult).where(
                    RealizationPersonResult.period_id == period.id
                )
            )
        ).scalars().all()
    }
    eligible_user_ids = {uuid.UUID(user_id) for user_id in evidence["people"]}
    for user_id, stale_result in existing.items():
        if user_id not in eligible_user_ids and stale_result.reviewed_at is None:
            await db.delete(stale_result)
    results: list[RealizationPersonResult] = []
    level_counts: Counter[str] = Counter()
    all_task_keys: set[str] = set()
    for user_id_raw, person in sorted(evidence["people"].items()):
        user_id = uuid.UUID(user_id_raw)
        result = existing.get(user_id)
        if person.get("availability_status"):
            if result is None:
                result = RealizationPersonResult(
                    period_id=period.id,
                    user_id=user_id,
                    department_id=period.department_id,
                )
                db.add(result)
            person["questions"] = []
            person["weekly_progress_percent"] = 0.0
            person["project_progress"] = []
            result.facts_json = person
            for _, model_key in COUNTER_FIELDS.items():
                setattr(result, model_key, 0)
            result.system_task_count = 0
            result.system_task_completed_count = 0
            result.meeting_missed_count = 0
            result.suggested_level = None
            result.suggested_symbol = None
            result.suggested_bonus = None
            result.auto_narrative = (
                "Pushim vjetor gjatë gjithë javës."
                if person["availability_status"] == "PV"
                else "Mungesë gjatë gjithë javës."
                if person["availability_status"] == "MUNGESE"
                else "PV / Mungesë gjatë gjithë javës."
            )
            results.append(result)
            continue
        if result is not None and result.reviewed_at is not None:
            # A manager's review is a final decision for this person this
            # week — recalculating (e.g. because a colleague's evidence
            # changed) must not silently overwrite it. Keep their stored
            # facts/level/bonus as-is; only reviewed rows are frozen, the
            # rest of the department still recalculates normally.
            results.append(result)
            reviewed_level = result.final_level or result.suggested_level
            if reviewed_level:
                level_counts[reviewed_level] += 1
            all_task_keys.update(
                item["match_key"] for item in (result.facts_json or {}).get("tasks") or []
            )
            continue
        counters = dict(person["counters"])
        decision = evaluate_policy({"counters": counters}, policy.criteria_json, policy.bonus_json)
        narrative = build_albanian_narrative({"counters": counters})
        person["questions"] = build_questions(person, decision, narrative)
        person["decision"] = {
            "triggered_rule": decision.triggered_rule,
            "reasons": list(decision.reasons),
            "policy_suggested_level": decision.level.value,
            "hard_cap_level": (
                decision.level.value
                if decision.triggered_rule in {
                    "unexpected_absence",
                    "no_real_progress",
                    "unapproved_or_major_failure",
                    "partial_failure",
                    "delay_or_minor_impact",
                }
                else None
            ),
        }
        planned_count = int(counters.get("planned_count", 0))
        accounted_count = int(counters.get("accounted_planned_count", 0))
        person["weekly_progress_percent"] = (
            round(accounted_count * 100.0 / planned_count, 1)
            if planned_count
            else 0.0
        )
        person["expected_cumulative_count"] = planned_count
        person["actual_cumulative_count"] = int(counters.get("completed_on_time_count", 0)) + int(
            counters.get("completed_late_count", 0)
        )
        person["unresolved_pink_count"] = int(counters.get("no_progress_count", 0))
        pulse = calculate_pulse(person)
        person["pulse"] = pulse.to_dict()
        person["recovery"] = build_recovery(
            decision=pulse,
            weekly_planned_count=planned_count,
            as_of_day=period.end_date,
            week_end=period.end_date,
        )
        person["project_progress"] = build_project_progress(person["tasks"])
        if result is None:
            result = RealizationPersonResult(
                period_id=period.id,
                user_id=user_id,
                department_id=period.department_id,
            )
            db.add(result)
        else:
            # Recalculating (e.g. after new evidence is added) rebuilds facts
            # from scratch — carry forward any AI analyses generated earlier
            # this week instead of silently losing them.
            previous_facts = result.facts_json or {}
            if previous_facts.get("ai_analysis"):
                person["ai_analysis"] = previous_facts["ai_analysis"]
            if previous_facts.get("ai_analysis_history"):
                person["ai_analysis_history"] = previous_facts["ai_analysis_history"]
            if previous_facts.get("ai_analysis"):
                result.ai_analysis_stale = True
        result.facts_json = person
        for source_key, model_key in COUNTER_FIELDS.items():
            setattr(result, model_key, int(counters.get(source_key, 0)))
        result.system_task_count = sum(1 for item in person["tasks"] if item["source_type"] == "system")
        result.system_task_completed_count = sum(
            1
            for item in person["tasks"]
            if item["source_type"] == "system"
            and item["classification"] in {"completed_on_time", "completed_late", "additional_completed"}
        )
        result.meeting_missed_count = int(counters.get("meeting_missed_count", 0))
        result.suggested_level = decision.level.value
        result.suggested_symbol = decision.symbol.value
        result.suggested_bonus = decision.bonus
        result.auto_narrative = narrative
        results.append(result)
        level_counts[decision.level.value] += 1
        all_task_keys.update(item["match_key"] for item in person["tasks"])

    department_result = (
        await db.execute(
            select(RealizationDepartmentResult).where(
                RealizationDepartmentResult.period_id == period.id,
                RealizationDepartmentResult.department_id == period.department_id,
            )
        )
    ).scalar_one_or_none()
    if department_result is None:
        department_result = RealizationDepartmentResult(
            period_id=period.id,
            department_id=period.department_id,
        )
        db.add(department_result)
    count = len(results)
    unique_department_tasks: dict[str, dict[str, Any]] = {}
    for person in evidence["people"].values():
        for task in person.get("tasks") or []:
            unique_department_tasks.setdefault(str(task.get("match_key")), task)
    department_result.facts_json = {
        "unique_task_count": len(evidence["department_unique_task_keys"]),
        "unique_planned_task_count": len(evidence["department_planned_task_keys"]),
        "unique_final_task_count": len(evidence["department_final_task_keys"]),
        "unique_additional_task_count": len(evidence["department_additional_task_keys"]),
        "unique_attributed_task_count": len(all_task_keys),
        "unassigned": evidence["unassigned"],
        "excluded_people": evidence["excluded_people"],
        "planned_snapshot_id": evidence["planned_snapshot_id"],
        "final_snapshot_id": evidence["final_snapshot_id"],
        "project_progress": build_project_progress(list(unique_department_tasks.values())),
    }
    department_result.a_plus_count = level_counts["A+"]
    department_result.a_count = level_counts["A"]
    department_result.b_count = level_counts["B"]
    department_result.c_count = level_counts["C"]
    department_result.m_count = level_counts["M"]
    department_result.d_count = level_counts["D"]
    department_result.e_count = level_counts["E"]
    department_result.a_rate = (
        Decimal((level_counts["A+"] + level_counts["A"]) * 100) / Decimal(count)
        if count
        else Decimal(0)
    )
    department_result.total_bonus = None
    department_result.average_bonus = None
    department_result.proposal_count = sum(row.proposal_count for row in results)
    department_result.time_saved_minutes = sum(row.time_saved_minutes for row in results)
    department_result.repeated_problem_count = sum(row.repeated_problem_count for row in results)
    department_result.department_suggestion = (
        f"{count} punonjës; {level_counts['A+'] + level_counts['A']} rezultate A/A+."
    )
    if period.status == RealizationPeriodStatus.OPEN.value:
        transition_period(period, RealizationPeriodStatus.CALCULATED, actor_id=actor_id)
    else:
        period.calculated_at = datetime.now(timezone.utc)
    await db.flush()
    return results, department_result
