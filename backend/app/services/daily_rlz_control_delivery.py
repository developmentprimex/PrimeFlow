from __future__ import annotations

import hashlib
import html
import json
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models.primeflow_report_delivery_run import PrimeFlowReportDeliveryRun
from app.models.primeflow_report_schedule import PrimeFlowReportSchedule
from app.models.primeflow_report_snapshot import PrimeFlowReportSnapshot
from app.services.daily_rlz_compliance import REASON_LABELS, build_daily_rlz_control, tirana_now
from app.services.daily_realization_report import (
    add_optional_ai_narrative,
    build_daily_realization_report,
    report_delta,
)
from app.services.primeflow_report import GmailService
from app.services.primeflow_report_delivery import configured_recipients
from app.services.note_markup import marked_task_html, marked_task_plain_lines, parse_marked_note_content

REPORT_TYPE = "rlz_daily_control"
SCHEDULE_TYPE = "RLZ_DAILY_CONTROL"
REPORT_SLOT = "16:10"
DEFAULT_VARIANT_TIMES = {"PRECHECK": "16:10", "FINAL": "16:40", "CORRECTION": "17:05"}
FINAL_REQUIRED_RECIPIENTS = ("ga@primexeu.com", "130primex.eu@gmail.com")


def final_recipient_map(recipients: dict[str, list[str]]) -> dict[str, list[str]]:
    """Ensure scheduled FINAL always reaches the mandated manager addresses."""
    result = {key: [] for key in ("to", "cc", "bcc")}
    seen: set[str] = set()
    for key in ("to", "cc", "bcc"):
        for raw in recipients.get(key, []):
            email = str(raw).strip()
            normalized = email.casefold()
            if email and normalized not in seen:
                result[key].append(email)
                seen.add(normalized)
    for email in FINAL_REQUIRED_RECIPIENTS:
        if email.casefold() not in seen:
            result["to"].append(email)
            seen.add(email.casefold())
    return result
TERMINAL = {"SENT", "ALREADY_SENT", "SKIPPED_NO_CHANGES"}


def subject_for(day: date, report_time: str = REPORT_SLOT, variant: str = "PRECHECK") -> str:
    labels = {
        "PRECHECK": "Kontrolli ditor RLZ",
        "FINAL": "Realizimi ditor FINAL",
        "CORRECTION": "Korrigjime të realizimit ditor",
    }
    return f"[PrimeFlow] {labels.get(variant, labels['PRECHECK'])} - {day:%d/%m/%Y} - {report_time}"


def _close_state_reason(status: str) -> str:
    return {
        "NOT_SAVED": "Dita është ende e hapur.",
        "CLOSED_EDIT_WINDOW": "Dita nuk u mbyll brenda afatit.",
        "STALE": "Ka ndryshime pas mbylljes; dita duhet rimbyllur.",
        "SAVED": "Dita është mbyllur, por kanë mbetur pika të paplotësuara.",
    }.get(status, "Gjendja për RLZ javor kërkon kontroll.")


def _task_title(title: str) -> str:
    clean = parse_marked_note_content(title).text
    return next((line.strip() for line in clean.splitlines() if line.strip()), clean)


CLASSIFICATION_LABELS = {
    "REALIZED_AS_PLANNED": "Kryer sipas planit", "IN_PROGRESS": "Në progres",
    "NO_PROGRESS": "Pa progres", "POSTPONED_APPROVED": "Shtyrë · aprovuar",
    "POSTPONED_UNAPPROVED": "Shtyrë · pret aprovim", "WAITING_CONFIRMATION": "WFC INT",
    "COMPLETED_LATE": "Kryer me vonesë", "COMPLETED_EARLY": "Kryer para kohe",
    "ADDITIONAL_COMPLETED": "Ekstra e kryer", "ADDED_DURING_DAY": "Shtuar gjatë ditës",
    "REOPENED": "Rihapur", "REASSIGNED_OUT": "Transferuar jashtë", "REASSIGNED_IN": "Transferuar brenda",
}

CLOSE_STATE_LABELS = {
    "NOT_SAVED": "DITA E HAPUR", "SAVED": "DITA E MBYLLUR", "STALE": "KA NDRYSHIME PAS MBYLLJES",
    "REOPENED": "DITA ËSHTË RIHAPUR", "CLOSED_EDIT_WINDOW": "AFATI I MBYLLJES KA PËRFUNDUAR", "CLOSED": "DITA E MBYLLUR",
}
APPROVAL_LABELS = {
    "APPROVED": "Aprovuar", "PENDING": "Pret aprovim", "REJECTED": "Refuzuar",
    "STALE": "Duhet rishikuar", "NOT_REQUIRED": "Nuk kërkohet", "REVOKED": "Pret aprovim",
}


def _percent(value) -> str:
    return "—" if value is None else f"{value}%"


def _deadline_display(task: dict) -> str:
    changes = [row for row in task.get("timeline", []) if row.get("type") in {"POSTPONED", "POSTPONED_AGAIN", "MOVED_BACK_TO_TODAY", "MOVED_EARLIER"}]
    values: list[str] = []
    for row in changes:
        old, new = row.get("old_value"), row.get("new_value")
        if old and (not values or values[-1] != str(old)[:10]):
            values.append(str(old)[:10])
        if new and (not values or values[-1] != str(new)[:10]):
            values.append(str(new)[:10])
    if values:
        return " → ".join(values)
    baseline, current = task.get("planned_due_date"), task.get("due_date")
    return str(current or baseline or "—") if baseline == current or not baseline else f"{baseline} → {current or '—'}"


def _human_close_state(value: str | None) -> str:
    return CLOSE_STATE_LABELS.get(str(value or ""), "Gjendje për kontroll")


def _human_approval(value: str | None) -> str:
    return APPROVAL_LABELS.get(str(value or ""), "Nuk kërkohet")


def _task_result_label(task: dict) -> str:
    if task.get("adjustment_status") == "REJECTED":
        return "Shtyrë · refuzuar"
    return CLASSIFICATION_LABELS.get(task.get("classification"), "Rezultat ditor")


def _human_control(value: str | None) -> str:
    return "KËRKON VEPRIM" if value == "ACTION_REQUIRED" else "DITA NË RREGULL"


def _close_evidence(person: dict) -> str:
    state = person.get("rlz_close_state") or {}
    saved_at = state.get("saved_at")
    pieces: list[str] = []
    if saved_at:
        try:
            pieces.append(datetime.fromisoformat(saved_at).astimezone(tirana_now().tzinfo).strftime("%H:%M"))
        except (TypeError, ValueError):
            pass
    if state.get("closed_by_name"):
        pieces.insert(0, str(state["closed_by_name"]))
    return f' · {" · ".join(pieces)}' if pieces else ""


def _close_evidence_html(person: dict) -> str:
    return html.escape(_close_evidence(person))


def _short_date(value: str | None) -> str:
    text_value = str(value or "—")
    if len(text_value) >= 10 and text_value[4:5] == "-" and text_value[7:8] == "-":
        return f"{text_value[8:10]}.{text_value[5:7]}"
    return text_value


def _short_deadline_display(task: dict) -> str:
    return " → ".join(_short_date(value.strip()) for value in _deadline_display(task).split("→"))


def _task_issue_state(task: dict) -> dict[str, bool]:
    issues = set(task.get("issues") or [])
    return {
        "reason": bool(task.get("reason_missing")) or bool(issues & {"MISSING_REASON", "REASON_MISSING"}),
        "comment": bool(task.get("comment_missing")) or bool(issues & {"MISSING_REQUIRED_COMMENT", "COMMENT_MISSING"}),
        "due": "DUE_DATE_NOT_MOVED" in issues,
        "slot": "ONE_H_SLOT_MISSING" in issues,
    }


def _reason_label(task: dict) -> str | None:
    return task.get("reason_label") or REASON_LABELS.get(task.get("reason_code"))


def _control_summary(summary: dict) -> str:
    messages = []
    not_saved = summary.get("employees_not_saved", 0)
    missing = summary.get("tasks_missing_reason", 0) + summary.get("tasks_missing_comment", 0)
    open_deadlines = summary.get("deadlines_open_count", 0)
    if not_saved:
        messages.append(f"{not_saved} {'person nuk e ka' if not_saved == 1 else 'persona nuk e kanë'} mbyllur ditën")
    if missing:
        messages.append(f"{missing} {'fushë sqarimi mungon' if missing == 1 else 'fusha sqarimi mungojnë'}")
    if open_deadlines:
        messages.append(f"{open_deadlines} deadline {'është ende i hapur' if open_deadlines == 1 else 'janë ende të hapura'}")
    return " · ".join(messages[:2]) or "Kontrollo rastet që kërkojnë vëmendje"


def _manager_plain(report: dict, report_time: str) -> str:
    summary = report["summary"]
    lines = [
        subject_for(date.fromisoformat(report["day"]), report_time, report["variant"]),
        "PËRMBLEDHJA E REALIZIMIT",
        f"Stafi {summary.get('employees_checked', 0)} | Planifikuar {summary.get('original_planned_count', 0)} | "
        f"Kryer nga plani {summary.get('planned_completed_today_count', 0)} | Në progres {summary.get('in_progress_count', 0)} | "
        f"Shtyrë {summary.get('postponed_count', 0)} | Pa progres {summary.get('no_progress_count', 0)} | "
        f"Ekstra {summary.get('additional_completed_count', 0)} | Total kryer {summary.get('total_completed_today_count', 0)} | "
        f"Plan RLZ {_percent(summary.get('raw_plan_realization'))} | E rregulluar {_percent(summary.get('adjusted_plan_realization'))}",
        "KONTROLLI I AFATEVE",
        f"Deadline sot {summary.get('deadlines_today_count', 0)} | Kryer {summary.get('deadlines_completed_count', 0)} | "
        f"Shtyrë {summary.get('deadlines_postponed_count', 0)} | Hapur {summary.get('deadlines_open_count', 0)} | "
        f"Të vonuara {summary.get('overdue_open_count', 0)} | Kritike hapur {summary.get('critical_deadlines_open_count', 0)} | "
        f"Deadline Compliance {_percent(summary.get('deadline_compliance_percentage'))}",
        f"{_human_control(summary.get('daily_control_state'))}: {_control_summary(summary)}", "",
    ]
    for person in report.get("people", []):
        metrics = person["metrics"]
        lines.extend([
            f"{person['employee']} — {person['department']}",
            f"Plan {metrics['original_planned_count']} | Kryer {metrics['planned_completed_today_count']} | "
            f"Në progres {metrics['in_progress_count']} | Shtyrë {metrics['postponed_count']} | "
            f"Pa progres {metrics['no_progress_count']} | Ekstra {metrics['additional_completed_count']} | "
            f"Total kryer {metrics['total_completed_today_count']} | Plan RLZ {_percent(metrics['raw_plan_realization'])}",
            f"Deadline sot {metrics['deadlines_today_count']} | Kryer {metrics['deadlines_completed_count']} | "
            f"Shtyrë {metrics['deadlines_postponed_count']} | Hapur {metrics['deadlines_open_count']} | "
            f"Deadline Compliance {_percent(metrics['deadline_compliance_percentage'])}",
            f"RLZ: {_human_close_state(person['rlz_close_state'].get('status'))}{_close_evidence(person)} | "
            f"Aprovimi: {_human_approval(person['manager_approval'].get('status'))} | {_human_control(person['control_state'])}",
        ])
        for ordinal, task in enumerate(person.get("tasks", []), 1):
            label = _task_result_label(task)
            issue_state = _task_issue_state(task)
            reason = _reason_label(task)
            if issue_state["reason"] or issue_state["comment"]:
                missing = "Mungon arsyeja dhe komenti" if issue_state["reason"] and issue_state["comment"] else "Mungon arsyeja" if issue_state["reason"] else "Mungon komenti"
                explanation = f"Kërkon sqarim — {missing}"
            else:
                explanation = " · ".join(value for value in (reason, task.get("comment")) if value) or "—"
            controls = []
            if task.get("one_h_report_slot"): controls.append(f"1H {task['one_h_report_slot']}")
            if task.get("adjustment_status"):
                decision = task.get("manager_decision") or {}
                approval = _human_approval(task.get("adjustment_status"))
                if decision.get("decided_by_name"):
                    decision_time = ""
                    if decision.get("decided_at"):
                        try:
                            decision_time = datetime.fromisoformat(decision["decided_at"]).astimezone(tirana_now().tzinfo).strftime("%H:%M")
                        except (TypeError, ValueError):
                            pass
                    approval += f" · {decision['decided_by_name']}{f' · {decision_time}' if decision_time else ''}"
                if decision.get("comment"):
                    approval += f" · Koment: {decision['comment']}"
                controls.append(approval)
            if task.get("deadline_is_overdue"): controls.append("Afat i kaluar")
            if task.get("deadline_critical") and not task.get("deadline_completed"): controls.append("Kritike")
            if issue_state["due"]: controls.append("Afati duhet përditësuar")
            if issue_state["slot"]: controls.append("Mungon 1H sloti")
            task_lines = marked_task_plain_lines(task.get("title"), ordinal)
            lines.extend(f"  {line}" for line in task_lines)
            lines.append(f"    Rezultati {label}{' · BLL' if task.get('is_bllok') else ''}")
            lines.append(
                f"    Plan {task.get('original_daily_plan') or 'Ekstra'} | Afati {_deadline_display(task)} | "
                f"Sqarimi {explanation} | Kontrolli {' · '.join(controls) or '—'}"
            )
        lines.append("")
    return "\n".join(lines)


def _status_color(task: dict) -> str:
    classification = task.get("classification")
    if classification in {"REALIZED_AS_PLANNED", "ADDITIONAL_COMPLETED", "COMPLETED_LATE", "COMPLETED_EARLY"}:
        return "#C4FDC4"
    if classification == "IN_PROGRESS":
        return "#FFFF00"
    if classification == "WAITING_CLIENT":
        return "#E2C15B"
    if classification == "WAITING_CONFIRMATION":
        return "#CCFBF1"
    if classification in {"POSTPONED_APPROVED", "POSTPONED_UNAPPROVED"}:
        return "#FED7AA"
    return "#FFC4ED"


def _section_title(label: str) -> str:
    return f'<div style="margin:18px 0 8px;background-color:#EEF2FF;border-left:5px solid #2563EB;padding:10px 12px;font:700 14px Arial;color:#111827">{html.escape(label)}</div>'


def _kpi_table(values: list[tuple[str, object, str]], *, plan_metrics: dict | None = None) -> str:
    rows = []
    for start in range(0, len(values), 4):
        cells = []
        for label, value, accent in values[start:start + 4]:
            secondary = ""
            if label == "PLAN RLZ" and plan_metrics is not None:
                raw = plan_metrics.get("raw_plan_realization")
                adjusted = plan_metrics.get("adjusted_plan_realization")
                completed = max(0, min(100, float(raw or 0)))
                remaining = 100 - completed
                secondary = (
                    f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:6px"><tr>'
                    f'<td width="{completed:.2f}%" bgcolor="#2563EB" style="height:5px;background:#2563EB"></td>'
                    f'<td width="{remaining:.2f}%" bgcolor="#E2E8F0" style="height:5px;background:#E2E8F0"></td></tr></table>'
                    + (f'<div style="margin-top:4px;font-size:9px;color:#64748B">E rregulluar: {_percent(adjusted)}</div>' if adjusted is not None else "")
                )
            cells.append(
                f'<td width="25%" valign="top" style="padding:9px 10px;border:1px solid #CBD5E1;border-top:3px solid {accent};background:#FFFFFF;text-align:center">'
                f'<div style="font:700 20px Arial;color:#111827">{html.escape(str(value))}</div>'
                f'<div style="margin-top:2px;font:700 10px Arial;color:#64748B;letter-spacing:.3px">{html.escape(label)}</div>{secondary}</td>'
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<table role="presentation" width="100%" cellspacing="4" cellpadding="0" style="table-layout:fixed;border-collapse:separate">' + "".join(rows) + "</table>"


def _source_label(value: str | None) -> str:
    return {"project": "Projekt", "fast": "Fast", "system": "Sistem"}.get(str(value or "").lower(), "Burim tjetër")


def _task_control(task: dict) -> str:
    issue_state = _task_issue_state(task)
    values = []
    if task.get("one_h_report_slot"):
        values.append(f"1H {html.escape(str(task['one_h_report_slot']))}")
    decision = task.get("manager_decision") or {}
    if task.get("adjustment_status"):
        decision_line = html.escape(_human_approval(task.get("adjustment_status")))
        if decision.get("decided_by_name"):
            decision_time = ""
            if decision.get("decided_at"):
                try:
                    decision_time = datetime.fromisoformat(decision["decided_at"]).astimezone(tirana_now().tzinfo).strftime("%H:%M")
                except (TypeError, ValueError):
                    decision_time = ""
            decision_line += f'<br><span style="font-size:8px;color:#64748B">{html.escape(decision["decided_by_name"])}{f" · {decision_time}" if decision_time else ""}</span>'
        if decision.get("comment"):
            decision_line += f'<br><span style="font-size:8px;color:#64748B">{html.escape(decision["comment"])}</span>'
        values.append(decision_line)
    if task.get("deadline_is_overdue"):
        values.append('<span style="color:#DC2626;font-weight:700">Afat i kaluar</span>')
    if task.get("deadline_critical") and not task.get("deadline_completed"):
        values.append('<span style="color:#DC2626;font-weight:700">Kritike</span>')
    if issue_state["due"]:
        values.append("Afati duhet përditësuar")
    if issue_state["slot"]:
        values.append("Mungon 1H sloti")
    return "<br>".join(values) or "—"


def _explanation_html(task: dict) -> tuple[str, str]:
    issue_state = _task_issue_state(task)
    if issue_state["reason"] or issue_state["comment"]:
        detail = "Mungon arsyeja dhe komenti" if issue_state["reason"] and issue_state["comment"] else "Mungon arsyeja" if issue_state["reason"] else "Mungon komenti"
        return "#FFFBEB", f'<div style="font-weight:700;color:#92400E">⚠ Kërkon sqarim</div><div style="margin-top:3px;color:#92400E">{detail}</div>'
    reason = _reason_label(task)
    content = f'<div style="font-weight:700;color:#111827">{html.escape(reason)}</div>' if reason else ""
    if task.get("comment"):
        content += f'<div style="margin-top:3px;color:#64748B">{html.escape(str(task["comment"]))}</div>'
    return "#FFFFFF", content or "—"


def _person_control_summary(person: dict) -> str:
    missing = sum(any(_task_issue_state(task)[key] for key in ("reason", "comment")) for task in person.get("tasks", []))
    open_deadlines = person["metrics"].get("deadlines_open_count", 0)
    values = []
    if missing:
        values.append(f"{missing} {'detyrë kërkon' if missing == 1 else 'detyra kërkojnë'} sqarim")
    if open_deadlines:
        values.append(f"{open_deadlines} deadline {'i hapur' if open_deadlines == 1 else 'të hapura'}")
    return " · ".join(values) or "Kontrollo gjendjen e RLZ"


def _manager_html(report: dict, report_time: str) -> str:
    summary = report["summary"]
    report_day = date.fromisoformat(report["day"])
    variant = report.get("variant", "FINAL")
    variant_label = "FINAL" if variant == "FINAL" else "KORRIGJIM"
    variant_description = "Raporti përfundimtar i realizimit ditor" if variant == "FINAL" else "Korrigjimet pas raportit përfundimtar"
    realization = [
        ("PLANIFIKUAR", summary.get("original_planned_count", 0), "#2563EB"),
        ("KRYER NGA PLANI", summary.get("planned_completed_today_count", 0), "#86D486"),
        ("NË PROGRES", summary.get("in_progress_count", 0), "#D6D600"),
        ("PA PROGRES", summary.get("no_progress_count", 0), "#E89BD0"),
        ("SHTYRË", summary.get("postponed_count", 0), "#A78BFA"),
        ("EKSTRA", summary.get("additional_completed_count", 0), "#2563EB"),
        ("TOTAL KRYER", summary.get("total_completed_today_count", 0), "#86D486"),
        ("PLAN RLZ", _percent(summary.get("raw_plan_realization")), "#2563EB"),
    ]
    deadline_values = [
        ("DEADLINE SOT", summary.get("deadlines_today_count", 0), "#64748B"),
        ("KRYER", summary.get("deadlines_completed_count", 0), "#86D486"),
        ("SHTYRË", summary.get("deadlines_postponed_count", 0), "#A78BFA"),
        ("ENDE HAPUR", summary.get("deadlines_open_count", 0), "#DC2626" if summary.get("deadlines_open_count", 0) else "#CBD5E1"),
        ("TË VONUARA", summary.get("overdue_open_count", 0), "#DC2626" if summary.get("overdue_open_count", 0) else "#CBD5E1"),
        ("KRITIKE HAPUR", summary.get("critical_deadlines_open_count", 0), "#DC2626" if summary.get("critical_deadlines_open_count", 0) else "#CBD5E1"),
        ("DEADLINE COMPLIANCE", _percent(summary.get("deadline_compliance_percentage")), "#2563EB"),
        ("GJENDJA", _human_control(summary.get("daily_control_state")), "#F59E0B" if summary.get("daily_control_state") == "ACTION_REQUIRED" else "#86D486"),
    ]
    overview = []
    details = []
    for person in report.get("people", []):
        m = person["metrics"]
        close_label = _human_close_state(person.get("rlz_close_state", {}).get("status"))
        close_color = "#15803D" if close_label == "DITA E MBYLLUR" else "#B45309" if close_label in {"DITA E HAPUR", "KA NDRYSHIME PAS MBYLLJES"} else "#DC2626"
        overview.append(
            '<tr>'
            f'<td style="padding:7px;border-bottom:1px solid #CBD5E1"><b>{html.escape(person["employee"])}</b><br><span style="font-size:9px;color:#64748B">{html.escape(person["department"])}</span><br><span style="font-size:9px;color:{close_color}">{close_label}{_close_evidence_html(person)}</span></td>'
            + "".join(f'<td align="center" style="padding:7px 3px;border-bottom:1px solid #CBD5E1">{value}</td>' for value in (
                m.get("original_planned_count", 0), m.get("planned_completed_today_count", 0), m.get("in_progress_count", 0),
                m.get("no_progress_count", 0), m.get("additional_completed_count", 0), _percent(m.get("raw_plan_realization")),
            ))
            + f'<td style="padding:7px 4px;border-bottom:1px solid #CBD5E1;font-size:9px;color:{"#B45309" if person.get("control_state") == "ACTION_REQUIRED" else "#15803D"}">{_human_control(person.get("control_state"))}</td></tr>'
        )
        task_rows = []
        for ordinal, task in enumerate(person.get("tasks", []), 1):
            explanation_bg, explanation = _explanation_html(task)
            classification = _task_result_label(task)
            deadline_problem = task.get("deadline_is_overdue") or (task.get("deadline_critical") and not task.get("deadline_completed"))
            source = f'{html.escape(task.get("project_title") or "Pa projekt")} · {_source_label(task.get("source_type"))}'
            if task.get("is_bllok"):
                source += ' · <span style="color:#2563EB;font-weight:700">BLL</span>'
            task_rows.append(
                '<tr>'
                f'<td width="38%" valign="top" style="padding:6px;border-bottom:1px solid #CBD5E1;font:700 11px/1.25 Arial;color:#111827">{marked_task_html(task.get("title"), ordinal)}<div style="margin:4px 0 0 22px;font:400 9px/1.25 Arial;color:#64748B">{source}</div></td>'
                f'<td width="14%" valign="top" style="padding:6px;border-bottom:1px solid #CBD5E1;background:{_status_color(task)};font:700 10px/1.25 Arial;color:#111827">{html.escape(classification)}</td>'
                f'<td width="16%" valign="top" style="padding:6px;border-bottom:1px solid #CBD5E1;font:10px/1.35 Arial;color:{"#DC2626" if deadline_problem else "#111827"}"><span style="font-size:9px;color:#64748B">Plan</span><br>{html.escape(_short_date(task.get("original_daily_plan")) if task.get("in_original_plan", not task.get("extra")) else "Ekstra")}<br><span style="font-size:9px;color:#64748B">Afati</span><br><b>{html.escape(_short_deadline_display(task))}</b></td>'
                f'<td width="20%" valign="top" style="padding:6px;border-bottom:1px solid #CBD5E1;background:{explanation_bg};font:10px/1.3 Arial">{explanation}</td>'
                f'<td width="12%" valign="top" style="padding:6px;border-bottom:1px solid #CBD5E1;font:9px/1.35 Arial;color:#475569">{_task_control(task)}</td></tr>'
            )
        person_control = person.get("control_state") == "ACTION_REQUIRED"
        details.append(
            '<div style="height:18px;line-height:18px">&nbsp;</div>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td style="background:#EEF2FF;border-left:5px solid #2563EB;padding:10px 12px"><div style="font:700 14px Arial;color:#111827">{html.escape(person["employee"].upper())}</div><div style="margin-top:2px;font:10px Arial;color:#64748B">{html.escape(person["department"])}</div><div style="margin-top:4px;font:700 10px Arial;color:{close_color}">{close_label}{_close_evidence_html(person)}</div></td></tr></table>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:7px 0 8px;background:#F8FAFC"><tr><td style="padding:7px;font:10px Arial"><b>Plan</b> {m.get("original_planned_count", 0)} &nbsp; <b>Kryer</b> {m.get("planned_completed_today_count", 0)} &nbsp; <b>Në progres</b> {m.get("in_progress_count", 0)} &nbsp; <b>Pa progres</b> {m.get("no_progress_count", 0)} &nbsp; <b>Ekstra</b> {m.get("additional_completed_count", 0)} &nbsp; <b>Plan RLZ</b> {_percent(m.get("raw_plan_realization"))}</td></tr><tr><td style="padding:0 7px 7px;font:10px Arial"><b>Deadline</b> {m.get("deadlines_completed_count", 0)} / {m.get("deadlines_today_count", 0)} &nbsp; <b>Compliance</b> {_percent(m.get("deadline_compliance_percentage"))} &nbsp; <b>Gjendja:</b> <span style="color:{"#B45309" if person_control else "#15803D"};font-weight:700">{_human_control(person.get("control_state"))}</span> &nbsp; <b>RLZ:</b> {close_label} &nbsp; <b>Aprovimi:</b> {_human_approval(person.get("manager_approval", {}).get("status"))}</td></tr>'
            + (f'<tr><td style="padding:0 7px 7px;font:9px Arial;color:#64748B">{html.escape(_person_control_summary(person))}</td></tr>' if person_control else "")
            + '</table><table width="100%" cellspacing="0" cellpadding="0" style="table-layout:fixed;border-collapse:collapse"><tr style="background:#F8FAFC">'
            '<th width="38%" style="padding:6px;text-align:left;border-bottom:2px solid #CBD5E1;font:700 10px Arial">DETYRA</th><th width="14%" style="padding:6px;text-align:left;border-bottom:2px solid #CBD5E1;font:700 10px Arial">REZULTATI</th><th width="16%" style="padding:6px;text-align:left;border-bottom:2px solid #CBD5E1;font:700 10px Arial">PLAN / AFATI</th><th width="20%" style="padding:6px;text-align:left;border-bottom:2px solid #CBD5E1;font:700 10px Arial">SQARIMI</th><th width="12%" style="padding:6px;text-align:left;border-bottom:2px solid #CBD5E1;font:700 10px Arial">KONTROLLI</th></tr>'
            + "".join(task_rows) + '</table>'
        )
    action = summary.get("daily_control_state") == "ACTION_REQUIRED"
    control_box = (
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px"><tr><td style="padding:9px 12px;background:{"#FFFBEB" if action else "#F0FDF4"};border:1px solid {"#FCD34D" if action else "#BBF7D0"};font:700 11px Arial;color:{"#92400E" if action else "#166534"}">{"⚠" if action else "✓"} {_human_control(summary.get("daily_control_state"))}<div style="margin-top:3px;font-weight:400;color:#64748B">{html.escape(_control_summary(summary)) if action else "Nuk ka veprime të hapura për këtë ditë."}</div></td></tr></table>'
    )
    return (
        '<!doctype html><html><body style="margin:0;background:#F8FAFC;color:#111827;font-family:Arial,sans-serif">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:14px 8px">'
        '<table role="presentation" width="940" cellspacing="0" cellpadding="0" style="width:940px;max-width:100%;background:#FFFFFF;border-collapse:collapse;border-top:5px solid #2563EB"><tr><td style="padding:15px 18px 10px">'
        '<div style="font:700 11px Arial;color:#2563EB;letter-spacing:1px">PRIMEFLOW</div>'
        f'<div style="margin-top:4px;font:700 20px Arial;color:#111827">REALIZIMI DITOR — {variant_label}</div>'
        f'<div style="margin-top:5px;font:12px Arial;color:#64748B">{report_day:%d.%m.%Y} · {html.escape(report_time)}<br>{variant_description}</div>'
        + _section_title("PËRMBLEDHJA E REALIZIMIT") + _kpi_table(realization, plan_metrics=summary)
        + _section_title("KONTROLLI I AFATEVE") + _kpi_table(deadline_values) + control_box
        + _section_title("PËRMBLEDHJA SIPAS STAFIT")
        + '<table width="100%" cellspacing="0" cellpadding="0" style="table-layout:fixed;border-collapse:collapse;font:10px Arial"><tr style="background:#F8FAFC"><th width="30%" style="padding:7px;text-align:left;border-bottom:2px solid #CBD5E1">STAFI</th><th>PLAN</th><th>KRYER</th><th>NË PROGRES</th><th>PA PROGRES</th><th>EKSTRA</th><th>PLAN RLZ</th><th>GJENDJA</th></tr>' + "".join(overview) + '</table>'
        + _section_title("DETAJET SIPAS STAFIT") + "".join(details)
        + '</td></tr></table></td></tr></table></body></html>'
    )


def render_plain(report: dict, report_time: str = REPORT_SLOT) -> str:
    if report.get("variant", "PRECHECK") != "PRECHECK":
        return _manager_plain(report, report_time)
    summary = report["summary"]
    lines = [
        subject_for(date.fromisoformat(report["day"]), report_time, "PRECHECK"), "",
        f"Departments checked: {summary['departments_checked']}",
        f"Employees checked: {summary['employees_checked']}",
        f"Employees not saved: {summary['employees_not_saved']}",
        f"Employees stale: {summary['employees_stale']}",
        f"Manager approval pending: {summary.get('employees_approval_pending', 0)}",
        f"Manager approval stale: {summary.get('employees_approval_stale', 0)}",
        f"Tasks missing reason: {summary['tasks_missing_reason']}",
        f"Tasks missing comment: {summary.get('tasks_missing_comment', 0)}",
        f"Tasks deadline not moved: {summary['tasks_deadline_not_moved']}",
        f"Tasks missing slot: {summary['tasks_missing_slot']}", "",
    ]
    if report["all_good"]:
        return "\n".join(lines + ["Kontrolli ditor RLZ përfundoi pa probleme."])
    for person in report["people"]:
        close_status = person["rlz_close_state"]["status"]
        lines.extend([
            person.get("department", "—"), person["employee"],
            f"RLZ State: {close_status}", f"Arsyeja: {_close_state_reason(close_status)}",
            f"Manager approval: {person.get('manager_approval', {}).get('status', 'PENDING')}",
        ])
        for blocker in person["blockers"]:
            lines.append(f"  {_task_title(blocker['title'])} ({blocker['status']})")
            lines.append(
                f"    Deadline: {blocker.get('due_date') or '—'} | Slot: {blocker.get('one_h_report_slot') or '—'} | "
                f"Arsyeja: {blocker.get('reason_label') or 'Empty'} | Koment: {blocker.get('comment') or '—'}"
            )
            for issue in blocker["issues"]:
                lines.append(f"    - {issue['message']} [{issue['code']}]")
        lines.append("")
    return "\n".join(lines)


def render_html(report: dict, report_time: str = REPORT_SLOT) -> str:
    """Outlook-safe colored RLZ control email, aligned with other PrimeFlow reports."""

    if report.get("variant", "PRECHECK") != "PRECHECK":
        return _manager_html(report, report_time)

    summary = report["summary"]
    metrics = (
        ("Punonjës të kontrolluar", summary["employees_checked"], "#dbeafe", "#1d4ed8"),
        ("Ditë të hapura", summary["employees_not_saved"], "#fee2e2", "#b91c1c"),
        ("Me ndryshime", summary["employees_stale"], "#fef3c7", "#b45309"),
        ("Pa aprovim", summary.get("employees_approval_pending", 0), "#fee2e2", "#b91c1c"),
        ("Aprovim stale", summary.get("employees_approval_stale", 0), "#fef3c7", "#b45309"),
        ("Pa arsye", summary["tasks_missing_reason"], "#fee2e2", "#b91c1c"),
        ("Pa koment", summary.get("tasks_missing_comment", 0), "#ffe4e6", "#be123c"),
        ("Deadline pa shtyrë", summary["tasks_deadline_not_moved"], "#ffedd5", "#c2410c"),
        ("Pa 1H slot", summary["tasks_missing_slot"], "#ede9fe", "#6d28d9"),
        ("Departamente", summary["departments_checked"], "#e2e8f0", "#334155"),
    )
    metric_cells = "".join(
        f'<td bgcolor="{background}" style="background-color:{background};padding:10px;'
        f'border:4px solid #ffffff;font-family:Arial,sans-serif;text-align:center;">'
        f'<div style="font-size:22px;font-weight:800;color:{color};">{value}</div>'
        f'<div style="font-size:11px;line-height:1.25;color:#475569;">{html.escape(label)}</div></td>'
        for label, value, background, color in metrics
    )

    state_colors = {
        "NOT_SAVED": ("#fee2e2", "#dc2626", "Dita e hapur"),
        "CLOSED_EDIT_WINDOW": ("#fee2e2", "#991b1b", "Afati i mbylljes përfundoi"),
        "STALE": ("#fef3c7", "#d97706", "Duhet rimbyllur"),
        "SAVED": ("#dcfce7", "#16a34a", "Ruajtur"),
    }
    people_html: list[str] = []
    for person in report["people"]:
        close_status = person["rlz_close_state"]["status"]
        background, accent, state_label = state_colors.get(
            close_status, ("#f1f5f9", "#64748b", close_status)
        )
        blocker_rows: list[str] = []
        for blocker in person["blockers"]:
            task_status = blocker.get("status") or "—"
            status_background = {
                "TODO": "#f9a8d4",
                "IN_PROGRESS": "#ffff00",
            }.get(task_status, "#ffffff")
            issue_labels = "".join(
                f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:3px 7px;'
                f'background:#ffffff;border:1px solid {accent};color:{accent};font-size:11px;font-weight:700;">'
                f'{html.escape(issue["message"])}</span>'
                for issue in (blocker.get("issues") or [])
            )
            blocker_rows.append(
                '<tr>'
                f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;'
                f'font-size:12px;font-weight:700;color:#0f172a;">{html.escape(_task_title(blocker["title"]))}</td>'
                f'<td bgcolor="{status_background}" style="background-color:{status_background};padding:9px;'
                f'border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:12px;">{html.escape(task_status)}</td>'
                f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:12px;">{html.escape(blocker.get("due_date") or "—")}</td>'
                f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:12px;">{html.escape(blocker.get("one_h_report_slot") or "—")}</td>'
                f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:12px;">{html.escape(blocker.get("reason_label") or "Empty")}</td>'
                f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:12px;">{html.escape(blocker.get("comment") or "—")}</td>'
                f'<td style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;">{issue_labels}</td>'
                '</tr>'
            )
        if not blocker_rows:
            blocker_rows.append(
                '<tr><td colspan="7" style="padding:10px;border:1px solid #cbd5e1;'
                'font-family:Arial,sans-serif;font-size:12px;color:#64748b;">'
                'Nuk ka task të paplotësuar; mungon vetëm ruajtja e gjendjes për RLZ javor.</td></tr>'
            )
        people_html.append(
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;margin:14px 0 20px;">'
            '<tr>'
            f'<td width="7" bgcolor="{accent}" style="width:7px;background-color:{accent};">&nbsp;</td>'
            f'<td bgcolor="{background}" style="background-color:{background};padding:11px 13px;'
            f'font-family:Arial,sans-serif;border:1px solid {accent};border-left:0;">'
            f'<div style="font-size:15px;font-weight:800;color:#0f172a;">{html.escape(person["employee"])}</div>'
            f'<div style="font-size:12px;color:#475569;margin-top:3px;">{html.escape(person.get("department") or "—")} · '
            f'<strong style="color:{accent};">{html.escape(state_label)}</strong></div>'
            f'<div style="font-size:12px;color:#334155;margin-top:4px;">Aprovimi i menaxherit: '
            f'<strong>{html.escape(person.get("manager_approval", {}).get("status", "PENDING"))}</strong></div>'
            f'<div style="font-size:12px;color:#334155;margin-top:5px;">{html.escape(_close_state_reason(close_status))}</div>'
            '</td></tr>'
            '<tr><td></td><td style="padding-top:8px;">'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;">'
            '<tr bgcolor="#e2e8f0">'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">TASK</th>'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">STATUS</th>'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">DEADLINE</th>'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">1H SLOT</th>'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">ARSYEJA</th>'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">KOMENT</th>'
            '<th style="padding:7px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-size:11px;text-align:left;">ÇFARË KA MBETUR</th>'
            '</tr>' + ''.join(blocker_rows) + '</table></td></tr></table>'
        )

    content = ''.join(people_html)
    if report["all_good"]:
        content = (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;margin:16px 0;">'
            '<tr><td bgcolor="#dcfce7" style="background-color:#dcfce7;border:1px solid #16a34a;'
            'padding:16px;font-family:Arial,sans-serif;font-weight:700;color:#166534;">'
            'Kontrolli ditor RLZ përfundoi pa probleme.</td></tr></table>'
        )

    subject = subject_for(date.fromisoformat(report["day"]), report_time, "PRECHECK")
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:#f8fafc;border-collapse:collapse;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="760" cellspacing="0" cellpadding="0" border="0" style="width:760px;max-width:100%;background:#ffffff;border:1px solid #e5e7eb;border-collapse:collapse;">
<tr><td bgcolor="#2563eb" style="background-color:#2563eb;padding:18px 20px;font-family:Arial,sans-serif;">
<div style="font-size:22px;line-height:1.25;font-weight:800;color:#ffffff;">{html.escape(subject)}</div>
<div style="font-size:13px;color:#dbeafe;margin-top:4px;">Raporti automatik tregon kush nuk e ka mbyllur ditën dhe çfarë ka mbetur pa plotësuar.</div>
</td></tr>
<tr><td style="padding:14px 16px;background:#ffffff;font-family:Arial,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;border-collapse:collapse;"><tr>{metric_cells}</tr></table>
{content}
</td></tr></table>
</td></tr></table></body></html>'''


async def generate_fresh(day: date, variant: str = "PRECHECK") -> dict:
    async with SessionLocal() as db:
        if variant == "PRECHECK":
            report = await build_daily_rlz_control(db, day=day)
            report["variant"] = "PRECHECK"
            report["content_version"] = 2
            return report
        if variant == "CORRECTION":
            final_snapshot = await _final_snapshot_for_day(db, day)
            if final_snapshot is None:
                raise ValueError("Cannot preview correction without a stored FINAL report")
            current = await build_daily_realization_report(db, day=day, variant="FINAL")
            return report_delta(final_snapshot.normalized_report_json, current)
        report = await build_daily_realization_report(db, day=day, variant=variant)
        return await add_optional_ai_narrative(report)


async def _final_snapshot_for_day(db, day: date) -> PrimeFlowReportSnapshot | None:
    return (await db.execute(
        select(PrimeFlowReportSnapshot)
        .join(PrimeFlowReportDeliveryRun, PrimeFlowReportDeliveryRun.id == PrimeFlowReportSnapshot.delivery_run_id)
        .join(PrimeFlowReportSchedule, PrimeFlowReportSchedule.id == PrimeFlowReportDeliveryRun.schedule_id)
        .where(
            PrimeFlowReportDeliveryRun.report_type == REPORT_TYPE,
            PrimeFlowReportDeliveryRun.report_date == day,
            PrimeFlowReportSchedule.report_variant == "FINAL",
            PrimeFlowReportDeliveryRun.status.in_(["SENT", "ALREADY_SENT"]),
        )
        .order_by(PrimeFlowReportDeliveryRun.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


async def deliver_daily_rlz_control(
    day: date, *, send: bool = True, scheduled_for: datetime | None = None,
    recipient_map: dict[str, list[str]] | None = None, trigger_type: str = "SCHEDULED",
    triggered_by_user_id=None, manual_reason: str | None = None, schedule_id=None,
    schedule_version: int | None = None, recipient_group: str = "default",
    report_time: str | None = None, variant: str = "PRECHECK",
) -> PrimeFlowReportDeliveryRun:
    variant = variant.upper()
    if trigger_type == "MANUAL" and recipient_group == "default":
        recipient_group = f"manual-{uuid.uuid4().hex}"
    recipients_by_kind = recipient_map or await configured_recipients(SCHEDULE_TYPE)
    if variant == "FINAL" and trigger_type == "SCHEDULED":
        recipients_by_kind = final_recipient_map(recipients_by_kind)
    recipients = sum(recipients_by_kind.values(), [])
    report_time = report_time or (
        scheduled_for.strftime("%H:%M") if scheduled_for else DEFAULT_VARIANT_TIMES.get(variant, REPORT_SLOT)
    )
    subject = subject_for(day, report_time, variant)
    now = tirana_now()
    async with SessionLocal() as db:
        async with db.begin():
            lock_key = f"{REPORT_TYPE}|{day.isoformat()}|{report_time}|{recipient_group}"
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})
            run = (await db.execute(select(PrimeFlowReportDeliveryRun).where(
                PrimeFlowReportDeliveryRun.report_type == REPORT_TYPE,
                PrimeFlowReportDeliveryRun.report_date == day,
                PrimeFlowReportDeliveryRun.report_slot == report_time,
                PrimeFlowReportDeliveryRun.recipient_group == recipient_group,
            ).with_for_update())).scalar_one_or_none()
            if run is None:
                run = PrimeFlowReportDeliveryRun(
                    report_type=REPORT_TYPE, report_date=day, report_slot=report_time,
                    recipient_group=recipient_group, subject=subject, recipients=json.dumps(recipients),
                    scheduled_for=scheduled_for, scheduled_execution_time=scheduled_for,
                    trigger_type=trigger_type, triggered_by_user_id=triggered_by_user_id,
                    manual_reason=manual_reason, schedule_id=schedule_id, schedule_version=schedule_version,
                )
                db.add(run)
                await db.flush()
            if run.status in TERMINAL:
                return run
            if run.status == "RUNNING" and run.started_at and run.started_at > now - timedelta(minutes=30):
                return run
            run.status, run.started_at, run.attempt_count = "RUNNING", now, run.attempt_count + 1
        try:
            if send and not recipients:
                raise ValueError("RLZ Daily Control has no active database-managed recipients")
            gmail = GmailService() if send else None
            if gmail:
                existing = await gmail.find_exact(subject, recipients)
                if existing:
                    run.status = "ALREADY_SENT"
                    run.gmail_message_id, run.gmail_thread_id = existing.get("id"), existing.get("threadId")
                    run.finished_at = tirana_now()
                    await db.commit()
                    return run
            report = await generate_fresh(day, "FINAL" if variant == "CORRECTION" else variant)
            if variant == "CORRECTION":
                final_snapshot = await _final_snapshot_for_day(db, day)
                if final_snapshot is None:
                    raise ValueError("Cannot create correction without a stored FINAL report")
                report = report_delta(final_snapshot.normalized_report_json, report)
            body, html_body = render_plain(report, report_time), render_html(report, report_time)
            run.body_hash = hashlib.sha256(body.encode()).hexdigest()
            run.data_generated_at = now
            snapshot = (await db.execute(select(PrimeFlowReportSnapshot).where(
                PrimeFlowReportSnapshot.delivery_run_id == run.id
            ))).scalar_one_or_none()
            if snapshot is None:
                db.add(PrimeFlowReportSnapshot(
                    delivery_run_id=run.id, normalized_report_json=report,
                    plain_text_body=body, html_body=html_body, content_version=2,
                ))
            if variant == "CORRECTION" and not report.get("people"):
                run.status = "SKIPPED_NO_CHANGES"
                run.finished_at = tirana_now()
                await db.commit()
                return run
            if send:
                message = await gmail.send_verified(subject, recipients_by_kind, body, html_body)
                run.status = "SENT"
                run.gmail_message_id, run.gmail_thread_id = message.get("id"), message.get("threadId")
            else:
                run.status = "PENDING"
                setattr(run, "dry_run_body", body)
        except Exception as exc:
            run.status, run.error_code, run.error_message = "FAILED_EMAIL", type(exc).__name__, str(exc)[:2000]
        run.finished_at = tirana_now()
        await db.commit()
        return run
