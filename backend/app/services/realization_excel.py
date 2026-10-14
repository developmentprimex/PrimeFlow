from __future__ import annotations

import io
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.realization_calculator import QUESTION_LABELS, REPORT_QUESTION_SECTIONS
from app.config import settings


NAVY = "17365D"
BLUE = "D9EAF7"
GREEN = "C6EFCE"
AMBER = "FFE699"
RED = "F4CCCC"
WHITE = "FFFFFF"
GRAY = "E7E6E6"
CYAN = "CFFAFE"
LEVEL_COLORS = {
    "A+": "00B050",
    "A": "70AD47",
    "B": "C6E0B4",
    "C": "FFD966",
    "M": "F4B183",
    "D": "F8696B",
    "E": "C00000",
}
LEVEL_BONUSES = {"A+": 50, "A": 40, "B": 30, "C": 20, "M": 15, "D": 10, "E": 0}
DEPARTMENT_COLORS = {
    "development": "2E7D32",
    "product content": "1565C0",
    "graphic design": "BF360C",
}


def _department_color(name: str) -> str:
    return DEPARTMENT_COLORS.get(name.strip().lower(), NAVY)
THIN = Side(style="thin", color="A6A6A6")
VALUE_LABELS = {
    "planned": "Planifikuar",
    "weekly_planned": "Në planin javor",
    "weekly_completed": "Të mbyllura deri sot",
    "weekly_remaining": "Të pambyllura",
    "today_planned": "Planifikuar sot",
    "today_completed": "Mbyllur sot",
    "today_in_progress": "Në progres sot",
    "today_no_progress": "Pa progres sot",
    "completed": "Mbyllur",
    "in_progress": "Në progres",
    "no_progress": "Pa progres",
    "count": "Gjithsej",
    "fast_tasks": "Fast tasks",
    "yes": "Ka detyra të reja",
    "approved": "Të konfirmuara",
    "unapproved": "Pa konfirmim",
    "needs_confirmation": "Kërkon konfirmim",
    "verified_categories": "Kategori të verifikuara",
    "additional_tasks_candidate": "Taska shtesë kandidate",
    "all_closed": "Të gjitha të mbyllura",
    "closed": "Të mbyllura",
    "remaining": "Të pambyllura",
    "attendance_tardiness": "Vonesa në prezencë",
    "frequent": "Të shpeshta",
    "threshold": "Pragu",
}
SOURCE_LABELS = {"system": "Sistem", "project": "Projekt", "fast": "Fast task"}
STATUS_LABELS = {
    "completed": "Mbyllur",
    "completed_on_time": "Mbyllur në kohë",
    "completed_late": "Mbyllur me vonesë",
    "in_progress": "Në progres",
    "no_progress": "Pa progres",
    "pending_confirmation": "Në pritje të konfirmimit",
}


def _value(value: Any) -> str | int | float | bool:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Po" if value else "Jo"
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, dict):
        return " · ".join(
            f"{VALUE_LABELS.get(str(key), str(key).replace('_', ' ').title())}: {_value(item)}"
            for key, item in value.items()
        ) or "—"
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(_value(item)) for item in value) or "—"
    return str(value)


def _clean_task_title(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\[\[/?[a-z_]+\]\]", "", str(value or ""), flags=re.I)).strip()


def _title(ws, title: str, subtitle: str, width: int, color: str = NAVY) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    ws.cell(1, 1, title)
    ws.cell(1, 1).font = Font(color=WHITE, bold=True, size=16)
    ws.cell(1, 1).fill = PatternFill("solid", fgColor=color)
    ws.cell(1, 1).alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
    ws.cell(2, 1, subtitle)
    ws.cell(2, 1).font = Font(color="666666", italic=True)
    ws.cell(2, 1).alignment = Alignment(horizontal="center")


def _header(cell, fill: str = NAVY) -> None:
    cell.fill = PatternFill("solid", fgColor=fill)
    cell.font = Font(color=WHITE, bold=True)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _sheet_name(value: str, used: set[str]) -> str:
    base = "".join("-" if char in "[]:*?/\\" else char for char in value)[:31] or "Department"
    candidate = base
    counter = 2
    while candidate in used:
        suffix = f" {counter}"
        candidate = f"{base[:31-len(suffix)]}{suffix}"
        counter += 1
    used.add(candidate)
    return candidate


def _weekly_comments(day: dict) -> list[tuple[str, str, str]]:
    rows = []
    personal = day.get("person_comment") or {}
    if personal.get("comment"):
        rows.append(("Komenti ditor", personal.get("author") or "", personal["comment"]))
    for key, answer in (day.get("manual_answers") or {}).items():
        if answer.get("comment"):
            rows.append((QUESTION_LABELS.get(key, key), answer.get("answered_by_name") or "", answer["comment"]))
    close = day.get("close_event") or {}
    if close.get("daily_comment"):
        rows.append(("Mbyllja ditore", "", close["daily_comment"]))
    for task in day.get("tasks") or []:
        if task.get("daily_report_comment"):
            rows.append((_clean_task_title(task.get("title")), "", task["daily_report_comment"]))
    return rows


def _diamond_date(value: Any) -> str:
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(ZoneInfo(settings.APP_TIMEZONE)).date().isoformat()
    except (ValueError, TypeError):
        return str(value or "")[:10]


def _diamond_counts(person: dict) -> tuple[int, int, int]:
    facts = person.get("facts_json") or {}
    return tuple(int(facts.get(key) or 0) for key in (
        "weekly_diamond_count", "weekly_task_diamond_count", "weekly_proposal_diamond_count",
    ))


def _diamond_arguments(person: dict) -> str:
    lines = []
    for award in (person.get("facts_json") or {}).get("weekly_diamonds") or []:
        review = award.get("review") or {}
        source = "Propozim për përmirësim" if award.get("source") == "REALIZATION_PROPOSAL" else "Taskë e vlerësuar"
        line = f"{_diamond_date(award.get('completed_at'))} · {source} · {_clean_task_title(award.get('task_title'))}"
        if review.get("comment"):
            line += f": {review['comment']}"
        lines.append(line)
    return "\n".join(lines) or "Nuk ka diamanta për këtë javë."


def build_realization_workbook(
    *,
    week_start: str,
    week_end: str,
    departments: list[dict[str, Any]],
) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Përmbledhje"
    has_live_data = any(
        department.get("report_mode") == "LIVE_DAILY" for department in departments
    )
    report_label = (
        "AKTUAL NGA SNAPSHOT-ET DITORE" if has_live_data else "PËRFUNDIMTAR"
    )
    _title(
        summary,
        "RAPORTI I REALIZIMIT JAVOR",
        f"{week_start} — {week_end} | {report_label}",
        13,
    )
    headers = [
        "Departamenti", "Personi", "Në planin javor", "Të mbyllura", "Me vonesë (FINAL)",
        "Shtesë gjatë javës", "Progresi javor", "Vlerësimi", "Simboli", "Statusi",
        "Diamanta gjithsej", "Diamanta nga taskat", "Diamanta nga propozimet",
    ]
    for column, label in enumerate(headers, 1):
        summary.cell(4, column, label)
        _header(summary.cell(4, column))
    row = 5
    for department in departments:
        for person in department.get("people") or []:
            facts = person.get("facts_json") or {}
            is_live = facts.get("report_mode") == "LIVE_DAILY"
            grade = (
                "Në pritje të FINAL"
                if is_live
                else person.get("final_level") or person.get("suggested_level") or "—"
            )
            if "weekly_evaluation" in facts:
                grade = (person.get("weekly_manager_review") or {}).get("level") or (facts.get("weekly_evaluation") or {}).get("level") or "Plotëso përgjigjet"
            values = [
                department["name"], person["user_name"], person.get("planned_count", 0),
                person.get("completed_on_time_count", 0) + person.get("completed_late_count", 0),
                person.get("completed_late_count", 0),
                person.get("additional_count", 0), facts.get("weekly_progress_percent", 0) / 100,
                grade,
                "—" if is_live else person.get("final_symbol") or person.get("suggested_symbol") or "—",
                "AKTUAL" if is_live else department.get("status", "—"),
                *_diamond_counts(person),
            ]
            for column, value in enumerate(values, 1):
                cell = summary.cell(row, column, value)
                cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
            summary.cell(row, 7).number_format = "0.0%"
            level = str(values[7])
            if level in LEVEL_COLORS:
                summary.cell(row, 8).fill = PatternFill("solid", fgColor=LEVEL_COLORS[level])
                summary.cell(row, 8).font = Font(
                    bold=True, color=WHITE if level in {"A+", "A", "E"} else "000000"
                )
            summary.row_dimensions[row].height = 30
            row += 1
    if row == 5:
        summary.merge_cells(start_row=5, start_column=1, end_row=5, end_column=13)
        summary.cell(5, 1, "Nuk ka snapshot ditor ose rezultat FINAL për personat e përzgjedhur.")
        summary.cell(5, 1).alignment = Alignment(horizontal="center")
        summary.cell(5, 1).fill = PatternFill("solid", fgColor=AMBER)
    summary.freeze_panes = "A5"
    summary.auto_filter.ref = f"A4:M{max(4, row - 1)}"
    widths = [22, 24, 16, 14, 17, 16, 16, 22, 10, 16, 18, 20, 23]
    for index, width in enumerate(widths, 1):
        summary.column_dimensions[get_column_letter(index)].width = width

    used_names = {summary.title}
    for department in departments:
        people = department.get("people") or []
        width = max(3, 1 + len(people) * 2)
        ws = workbook.create_sheet(_sheet_name(department["name"], used_names))
        department_color = _department_color(department["name"])
        manager_name = department.get("manager_name")
        subtitle = f"Java {week_start} — {week_end} | {department.get('status', '—')}"
        if manager_name:
            subtitle += f" | Menaxheri: {manager_name}"
        _title(
            ws,
            f"REALIZIMI — {department['name']}",
            subtitle,
            width,
            color=department_color,
        )
        ws.cell(4, 1, "Pyetja / Treguesi")
        _header(ws.cell(4, 1), department_color)
        for index, person in enumerate(people):
            col = 2 + index * 2
            ws.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + 1)
            ws.cell(4, col, person["user_name"])
            _header(ws.cell(4, col), department_color)
            ws.cell(5, col, "Përgjigjja")
            ws.cell(5, col + 1, "Argumenti / Evidenca")
            _header(ws.cell(5, col), "5B9BD5")
            _header(ws.cell(5, col + 1), "5B9BD5")
        ws.cell(5, 1, "Burimi")
        _header(ws.cell(5, 1), "5B9BD5")
        if not people:
            ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=width)
            ws.cell(6, 1, "Pa snapshot ditor dhe pa rezultat FINAL për këtë departament.")
            ws.cell(6, 1).alignment = Alignment(horizontal="center")
            ws.cell(6, 1).fill = PatternFill("solid", fgColor=AMBER)

        current_row = 7 if not people else 6
        source_labels = {
            "AUTO": "Automatik nga databaza",
            "AUTO_NEEDS_CONFIRMATION": "Kërkon konfirmim",
            "MISSING_EVIDENCE": "Kërkon evidencë",
            "MANAGER_CONFIRMED": "Konfirmuar nga menaxheri",
            "MANUAL_ANSWERED": "Përgjigjja e përgjegjësit",
            "MANUAL_UNANSWERED": "Pa përgjigje manuale",
        }
        long_answer_keys = {
            "plan_completed",
            "week_positive",
            "week_problems",
            "repeated_after_clarification",
        }
        for section_title, question_keys in REPORT_QUESTION_SECTIONS:
            ws.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=width,
            )
            ws.cell(current_row, 1, section_title)
            _header(ws.cell(current_row, 1), "1F4E78")
            ws.cell(current_row, 1).alignment = Alignment(horizontal="left", vertical="center")
            ws.row_dimensions[current_row].height = 22
            current_row += 1

            for key in question_keys:
                ws.cell(current_row, 1, QUESTION_LABELS[key])
                ws.cell(current_row, 1).font = Font(bold=True)
                ws.cell(current_row, 1).fill = PatternFill("solid", fgColor=BLUE)
                ws.cell(current_row, 1).alignment = Alignment(vertical="top", wrap_text=True)
                ws.cell(current_row, 1).border = Border(
                    left=THIN, right=THIN, top=THIN, bottom=THIN
                )

                for index, person in enumerate(people):
                    col = 2 + index * 2
                    question = next(
                        (
                            item
                            for item in (person.get("facts_json") or {}).get("questions") or []
                            if item.get("key") == key
                        ),
                        {},
                    )
                    source_status = str(
                        question.get("source_status") or "AUTO_NEEDS_CONFIRMATION"
                    )
                    answer = question.get("final_value")
                    if answer is None and not source_status.startswith("MANUAL"):
                        answer = question.get("auto_value")
                    needs_confirmation = (
                        source_status == "MANUAL_UNANSWERED"
                        or
                        source_status in {"AUTO_NEEDS_CONFIRMATION", "MISSING_EVIDENCE"}
                        and answer is None
                    )
                    answer_cell = ws.cell(
                        current_row,
                        col,
                        (f"PËR KONFIRMIM: {_value(answer)}" if answer is not None else "PËR KONFIRMIM") if needs_confirmation else "Nuk aplikohet / Nuk dihet" if source_status.startswith("MANUAL") and answer is None else _value(answer),
                    )
                    answer_cell.fill = PatternFill(
                        "solid", fgColor=AMBER if needs_confirmation else WHITE
                    )

                    evidence = question.get("evidence_ids") or []
                    explanation = str(question.get("explanation") or "").strip()
                    note_parts = [
                        source_labels.get(source_status, source_status.replace("_", " ").title()),
                        explanation,
                        question.get("manager_comment") or "",
                        f"{len(evidence)} evidencë/a — detajet në fletën Evidenca"
                        if evidence
                        else "",
                    ]
                    ws.cell(
                        current_row,
                        col + 1,
                        " | ".join(item for item in note_parts if item),
                    )
                    for target in (
                        ws.cell(current_row, col),
                        ws.cell(current_row, col + 1),
                    ):
                        target.alignment = Alignment(vertical="top", wrap_text=True)
                        target.border = Border(
                            left=THIN, right=THIN, top=THIN, bottom=THIN
                        )
                ws.row_dimensions[current_row].height = (
                    64 if key in long_answer_keys else 46
                )
                current_row += 1

        # Daily RLZ evidence: the reason + comment each person saved themselves every
        # working day via "Ruaj gjendjen për RLZ" (TaskDailyRlzState). Plus one manual
        # "extra evidence" line the manager can fill in by hand, matching the physical
        # BARAZIMI JAVOR sheet.
        ws.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=width,
        )
        ws.cell(current_row, 1, "5. RLZ DITORE — ARSYEJA, KOMENTI DHE EVIDENCA")
        _header(ws.cell(current_row, 1), "1F4E78")
        ws.cell(current_row, 1).alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[current_row].height = 22
        current_row += 1

        def _daily_rlz_reason_text(items: list[dict[str, Any]]) -> str:
            parts = [
                f"{item.get('date')}: {item.get('reason_label') or item.get('reason_code')}"
                for item in items
                if item.get("reason_label") or item.get("reason_code")
            ]
            return " | ".join(parts) if parts else "—"

        def _daily_rlz_comment_text(items: list[dict[str, Any]]) -> str:
            parts = [
                f"{item.get('date')}: {item.get('comment')}"
                for item in items
                if item.get("comment")
            ]
            return " | ".join(parts) if parts else "—"

        for label, formatter in (
            ("Arsyeja (RLZ ditore)", _daily_rlz_reason_text),
            ("Koment (RLZ ditore)", _daily_rlz_comment_text),
        ):
            ws.cell(current_row, 1, label)
            ws.cell(current_row, 1).font = Font(bold=True)
            ws.cell(current_row, 1).fill = PatternFill("solid", fgColor=BLUE)
            ws.cell(current_row, 1).alignment = Alignment(vertical="top", wrap_text=True)
            ws.cell(current_row, 1).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            for index, person in enumerate(people):
                col = 2 + index * 2
                daily_items = (person.get("facts_json") or {}).get("daily_rlz") or []
                ws.merge_cells(start_row=current_row, start_column=col, end_row=current_row, end_column=col + 1)
                cell = ws.cell(current_row, col, formatter(daily_items))
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            ws.row_dimensions[current_row].height = 46
            current_row += 1

        ws.cell(current_row, 1, "Evidencë shtesë (manuale)")
        ws.cell(current_row, 1).font = Font(bold=True)
        ws.cell(current_row, 1).fill = PatternFill("solid", fgColor=BLUE)
        ws.cell(current_row, 1).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        for index, person in enumerate(people):
            col = 2 + index * 2
            ws.merge_cells(start_row=current_row, start_column=col, end_row=current_row, end_column=col + 1)
            ws.cell(current_row, col, "")
            ws.cell(current_row, col).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        ws.row_dimensions[current_row].height = 28
        current_row += 1

        ws.merge_cells(
            start_row=current_row,
            start_column=1,
            end_row=current_row,
            end_column=width,
        )
        ws.cell(current_row, 1, "6. REALIZIMET DITORE DHE KOMENTET")
        _header(ws.cell(current_row, 1), "1F4E78")
        ws.cell(current_row, 1).alignment = Alignment(horizontal="left", vertical="center")
        current_row += 1
        daily_dates = sorted(
            {
                str(item.get("date"))
                for person in people
                for item in (person.get("facts_json") or {}).get("daily_timeline") or []
                if item.get("date")
            }
        )
        for daily_date in daily_dates:
            daily_row_height = 100
            ws.cell(current_row, 1, f"Snapshot ditor — {daily_date}")
            ws.cell(current_row, 1).font = Font(bold=True)
            ws.cell(current_row, 1).fill = PatternFill("solid", fgColor=GREEN)
            for index, person in enumerate(people):
                col = 2 + index * 2
                snapshot = next(
                    (
                        item
                        for item in (person.get("facts_json") or {}).get("daily_timeline") or []
                        if str(item.get("date")) == daily_date
                    ),
                    None,
                )
                if snapshot:
                    daily_percent = snapshot.get("daily_progress_percent")
                    daily_value = "Pushim" if snapshot.get("on_leave") else "Në vijim" if snapshot.get("future") else "Pa të dhëna" if daily_percent is None else float(daily_percent) / 100
                    ws.cell(current_row, col, daily_value)
                    ws.cell(current_row, col).number_format = "0.0%"
                    attendance = snapshot.get("attendance") or []
                    ws.cell(
                        current_row,
                        col + 1,
                        "Java deri atë ditë: "
                        f"{snapshot.get('weekly_completed_count', 0)}/"
                        f"{snapshot.get('weekly_planned_count', 0)} | "
                        "Sot: "
                        f"{snapshot.get('completed_count', 0)}/"
                        f"{snapshot.get('planned_count', 0)} "
                        f"({str(daily_percent) + '%' if daily_percent is not None else '—'}) | "
                        f"Shtesë sot: {snapshot.get('additional_count', 0)} | "
                        f"Prezenca: {', '.join(str(item.get('type')) for item in attendance) or 'OK'}",
                    )
                    comments = _weekly_comments(snapshot)
                    if comments:
                        comment_text = "KOMENTET E DITËS\n" + "\n\n".join(
                            f"{daily_date} · {label}{' · ' + author if author else ''}: {comment}"
                            for label, author, comment in comments
                        )
                        argument = ws.cell(current_row, col + 1)
                        metrics_text = argument.value
                        argument.value = CellRichText([
                            TextBlock(InlineFont(b=True, color="075985", sz=12), comment_text),
                            TextBlock(InlineFont(color="64748B", sz=10), f"\n\nTË DHËNAT E SNAPSHOT-IT\n{metrics_text}"),
                        ])
                        argument.fill = PatternFill("solid", fgColor=CYAN)
                        comment_lines = sum(max(1, (len(line) + 37) // 38) for line in comment_text.split("\n"))
                        daily_row_height = max(daily_row_height, min(400, 18 * comment_lines + 72))
                else:
                    ws.cell(current_row, col, "—")
                    ws.cell(current_row, col + 1, "Pa snapshot")
                for target in (ws.cell(current_row, col), ws.cell(current_row, col + 1)):
                    target.alignment = Alignment(vertical="top", wrap_text=True)
                    target.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            ws.cell(current_row, 1).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            ws.row_dimensions[current_row].height = daily_row_height
            current_row += 1

        project_keys = sorted(
            {
                str(project.get("project_id") or project.get("project_title"))
                for person in people
                for project in (person.get("facts_json") or {}).get("project_progress") or []
            }
        )
        if project_keys:
            ws.merge_cells(
                start_row=current_row,
                start_column=1,
                end_row=current_row,
                end_column=width,
            )
            ws.cell(current_row, 1, "7. PROJEKTET MST / TT")
            _header(ws.cell(current_row, 1), "1F4E78")
            ws.cell(current_row, 1).alignment = Alignment(
                horizontal="left", vertical="center"
            )
            current_row += 1
        for project_key in project_keys:
            title = next(
                str(project.get("project_title") or "MST/TT")
                for person in people
                for project in (person.get("facts_json") or {}).get("project_progress") or []
                if str(project.get("project_id") or project.get("project_title")) == project_key
            )
            ws.cell(current_row, 1, f"Mesatarja e projektit — {title}")
            ws.cell(current_row, 1).font = Font(bold=True)
            ws.cell(current_row, 1).fill = PatternFill("solid", fgColor=AMBER)
            for index, person in enumerate(people):
                col = 2 + index * 2
                project = next(
                    (
                        item
                        for item in (person.get("facts_json") or {}).get("project_progress") or []
                        if str(item.get("project_id") or item.get("project_title")) == project_key
                    ),
                    None,
                )
                if project:
                    ws.cell(current_row, col, float(project.get("progress_percent") or 0) / 100)
                    ws.cell(current_row, col).number_format = "0.0%"
                    ws.cell(
                        current_row,
                        col + 1,
                        f"{project.get('task_count', 0)} detyra | {project.get('method', '')}",
                    )
                else:
                    ws.cell(current_row, col, "—")
                    ws.cell(current_row, col + 1, "Pa taska në këtë projekt")
                for target in (ws.cell(current_row, col), ws.cell(current_row, col + 1)):
                    target.alignment = Alignment(vertical="top", wrap_text=True)
                    target.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            ws.cell(current_row, 1).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            current_row += 1

        grade_row = current_row + 1
        department_is_live = department.get("report_mode") == "LIVE_DAILY"
        ws.merge_cells(
            start_row=grade_row,
            start_column=1,
            end_row=grade_row,
            end_column=width,
        )
        evaluation_section_number = 8 if project_keys else 7
        ws.cell(
            grade_row,
            1,
            f"{evaluation_section_number}. VLERËSIMI DHE KOMENTET",
        )
        _header(ws.cell(grade_row, 1), "1F4E78")
        ws.cell(grade_row, 1).alignment = Alignment(horizontal="left", vertical="center")

        def _final_level(person: dict[str, Any]) -> str | None:
            if "weekly_evaluation" in (person.get("facts_json") or {}):
                return (person.get("weekly_manager_review") or {}).get("level")
            return person.get("final_level") or person.get("suggested_level")

        evaluation_rows = [
            (
                "Diamanta gjithsej", lambda person: _diamond_counts(person)[0],
                _diamond_arguments, False, True,
            ),
            (
                "Diamanta nga taskat", lambda person: _diamond_counts(person)[1],
                lambda person: "Diamantat e dhënë nga vlerësimi i taskave.", False, False,
            ),
            (
                "Diamanta nga propozimet", lambda person: _diamond_counts(person)[2],
                lambda person: "Po me koment; përgjigjja javore nuk shpërblen propozimin ditor përsëri.", False, False,
            ),
            (
                "Propozimi për nivelin e vlerësimit",
                lambda person: (
                    "Në pritje të FINAL"
                    if department_is_live
                    else person.get("suggested_level") or "—"
                ),
                lambda person: (
                    "Klasifikohet pas ruajtjes FINAL"
                    if department_is_live
                    else str(person.get("auto_narrative") or "")
                ),
                True,
                False,
            ),
            (
                "Vlerësimi final",
                lambda person: (
                    "Në pritje"
                    if department_is_live
                    else _final_level(person) or "—"
                ),
                lambda person: (
                    "Menaxheri e konfirmon pas FINAL"
                    if department_is_live
                    else str(person.get("override_reason") or "")
                ),
                True,
                False,
            ),
            (
                "Simboli",
                lambda person: (
                    "—"
                    if department_is_live
                    else person.get("final_symbol")
                    or person.get("suggested_symbol")
                    or "—"
                ),
                lambda person: "",
                False,
                False,
            ),
            (
                "Bonusi javor (€)",
                lambda person: (
                    "—"
                    if department_is_live
                    else LEVEL_BONUSES.get(str(_final_level(person)), "—")
                ),
                lambda person: (
                    "Sipas nivelit; D deri 10€, sipas gjykimit të menaxherit"
                    if not department_is_live and _final_level(person) == "D"
                    else ""
                ),
                False,
                False,
            ),
            (
                "Komente",
                lambda person: str(person.get("manager_comment") or "—"),
                lambda person: str(person.get("auto_narrative") or "—"),
                False,
                True,
            ),
        ]
        for row_offset, (label, value_builder, note_builder, is_level_row, is_tall) in enumerate(
            evaluation_rows, 1
        ):
            evaluation_row = grade_row + row_offset
            ws.cell(evaluation_row, 1, label)
            ws.cell(evaluation_row, 1).font = Font(bold=True)
            ws.cell(evaluation_row, 1).fill = PatternFill("solid", fgColor=BLUE)
            ws.cell(evaluation_row, 1).border = Border(
                left=THIN, right=THIN, top=THIN, bottom=THIN
            )
            for index, person in enumerate(people):
                col = 2 + index * 2
                value = value_builder(person)
                evaluation = (person.get("facts_json") or {}).get("weekly_evaluation")
                review = person.get("weekly_manager_review") or {}
                if evaluation is not None:
                    if label == "Propozimi për nivelin e vlerësimit":
                        value = evaluation.get("level") or "Plotëso përgjigjet" if not evaluation.get("answers_complete", True) else evaluation.get("level") or "Pa të dhëna"
                    elif label == "Vlerësimi final":
                        value = review.get("level") or "Pa konfirmuar"
                    elif label == "Komente":
                        value = review.get("comment") or "—"
                note = note_builder(person)
                if evaluation is not None and label == "Propozimi për nivelin e vlerësimit":
                    note = "\n".join(evaluation.get("reasons") or [])
                elif evaluation is not None and label == "Vlerësimi final":
                    note = f"{review.get('created_by_name') or ''} · {review.get('created_at') or ''}" if review.get("level") else "Përgjegjësi ende nuk e ka konfirmuar shkronjën."
                fill = (
                    LEVEL_COLORS.get(str(value), GRAY)
                    if is_level_row
                    else WHITE
                )
                for target, target_value in (
                    (ws.cell(evaluation_row, col), value),
                    (ws.cell(evaluation_row, col + 1), note),
                ):
                    target.value = target_value
                    target.fill = PatternFill("solid", fgColor=fill)
                    target.font = Font(bold=is_level_row)
                    target.alignment = Alignment(
                        horizontal="center" if is_level_row else "left",
                        vertical="top",
                        wrap_text=True,
                    )
                    target.border = Border(
                        left=THIN, right=THIN, top=THIN, bottom=THIN
                    )
            ws.row_dimensions[evaluation_row].height = 46 if is_tall else 32
            if label.startswith("Diamanta"):
                for cell in ws[evaluation_row]:
                    cell.fill = PatternFill("solid", fgColor=CYAN)
                if label == "Diamanta gjithsej":
                    for index, person in enumerate(people):
                        col = 2 + index * 2
                        ws.cell(evaluation_row, col).font = Font(bold=True, color="075985", size=14)
                        text = str(ws.cell(evaluation_row, col + 1).value or "")
                        lines = sum(max(1, (len(line) + 47) // 48) for line in text.split("\n"))
                        ws.row_dimensions[evaluation_row].height = max(ws.row_dimensions[evaluation_row].height, min(400, 15 * (lines + 2)))
        last_row = grade_row + len(evaluation_rows)

        # 6. PAGA — filled in manually by the board/HR after the level is confirmed;
        # this system does not track salaries, so these three rows are left blank
        # ("___") exactly like the physical BARAZIMI JAVOR sheet.
        paga_section_row = last_row + 1
        ws.merge_cells(
            start_row=paga_section_row, start_column=1, end_row=paga_section_row, end_column=width
        )
        ws.cell(paga_section_row, 1, "9. PAGA" if project_keys else "8. PAGA")
        _header(ws.cell(paga_section_row, 1), "1F4E78")
        ws.cell(paga_section_row, 1).alignment = Alignment(horizontal="left", vertical="center")
        paga_rows = ["Paga bazë (€)", "Bonus mujor (€)", "TOTAL MUJOR (€)"]
        for offset, label in enumerate(paga_rows, 1):
            paga_row = paga_section_row + offset
            ws.cell(paga_row, 1, label)
            ws.cell(paga_row, 1).font = Font(bold=True)
            ws.cell(paga_row, 1).fill = PatternFill("solid", fgColor=BLUE)
            ws.cell(paga_row, 1).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            for index, person in enumerate(people):
                col = 2 + index * 2
                ws.merge_cells(start_row=paga_row, start_column=col, end_row=paga_row, end_column=col + 1)
                ws.cell(paga_row, col, "___")
                ws.cell(paga_row, col).alignment = Alignment(horizontal="center")
                ws.cell(paga_row, col).border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        last_row = paga_section_row + len(paga_rows)

        totals_row = last_row + 2
        ws.merge_cells(
            start_row=totals_row, start_column=1, end_row=totals_row, end_column=width
        )
        ws.cell(totals_row, 1, f"TOTALI I JAVËS — {department['name'].upper()}")
        _header(ws.cell(totals_row, 1), "1A1A1A")
        level_header_row = totals_row + 1
        levels = ["A+", "A", "B", "C", "M", "D", "E"]
        level_columns = [*levels, "TOTAL", "Komente / Vendim bordi"]
        for offset, label in enumerate(level_columns):
            cell = ws.cell(level_header_row, 1 + offset, label)
            _header(cell, department_color)
        level_counts = Counter(
            str(_final_level(person)) for person in people if _final_level(person)
        )
        counts_row = level_header_row + 1
        ws.cell(counts_row, 1, f"Nr. punëtorësh ({len(people)} gjithsej)")
        ws.cell(counts_row, 1).font = Font(bold=True)
        ws.cell(counts_row, 1).fill = PatternFill("solid", fgColor=GRAY)
        for offset, level in enumerate(levels, 1):
            cell = ws.cell(counts_row, 1 + offset, level_counts.get(level, 0))
            cell.fill = PatternFill("solid", fgColor=LEVEL_COLORS.get(level, WHITE))
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
        ws.cell(counts_row, 1 + len(levels) + 1, len(people)).font = Font(bold=True)
        ws.cell(counts_row, 1 + len(levels) + 1).alignment = Alignment(horizontal="center")
        for row in (level_header_row, counts_row):
            for col_index in range(1, len(level_columns) + 2):
                ws.cell(row, col_index).border = Border(
                    left=THIN, right=THIN, top=THIN, bottom=THIN
                )

        signature_row = counts_row + 2
        ws.cell(signature_row, 1, "Nënshkrimet:")
        ws.cell(signature_row, 1).font = Font(bold=True)
        ws.cell(signature_row, 1).fill = PatternFill("solid", fgColor=GRAY)
        ws.cell(signature_row + 1, 1, "Barazoi: ____________________")
        ws.cell(signature_row + 1, min(4, width), "Konfirmoi (GA): ____________________")

        legend_row = signature_row + 3
        ws.merge_cells(start_row=legend_row, start_column=1, end_row=legend_row, end_column=width)
        ws.cell(
            legend_row,
            1,
            "LEGJENDA:  A+(50€)=gjitha+2+ekstra  A(40€)=gjitha+1ekstra  B(30€)=gjitha,pa ekstra  "
            "C(20€)=vonesa  M(15€)=mungese e miratuar  D(max 10€)=pjeserisht  E(0€)=pa progres",
        )
        ws.cell(legend_row, 1).font = Font(italic=True, size=9)
        ws.cell(legend_row, 1).fill = PatternFill("solid", fgColor=GRAY)
        ws.cell(legend_row, 1).alignment = Alignment(horizontal="left", wrap_text=True)
        ws.row_dimensions[legend_row].height = 22
        last_row = legend_row
        # The totals-by-level table (7 levels + TOTAL + Komente) can be wider
        # than the per-person columns for small departments — make sure the
        # print area and auto-filter cover it.
        width = max(width, len(level_columns) + 1)

        ws.freeze_panes = "B6"
        ws.column_dimensions["A"].width = 44
        for index in range(len(people)):
            ws.column_dimensions[get_column_letter(2 + index * 2)].width = 28
            ws.column_dimensions[get_column_letter(3 + index * 2)].width = 40
        ws.sheet_view.showGridLines = False
        ws.auto_filter.ref = f"A5:{get_column_letter(width)}5"
        ws.print_title_rows = "1:5"
        ws.print_area = f"A1:{get_column_letter(width)}{max(5, last_row)}"

    evidence = workbook.create_sheet("Evidenca")
    _title(evidence, "REGJISTRI I EVIDENCËS", "Çdo përgjigje duhet të jetë e gjurmueshme", 8)
    evidence_headers = [
        "Departamenti", "Personi", "Lloji", "ID", "Kategoria", "Statusi",
        "Përshkrimi", "Verifikuar",
    ]
    for column, label in enumerate(evidence_headers, 1):
        evidence.cell(4, column, label)
        _header(evidence.cell(4, column))
    row = 5
    for department in departments:
        for person in department.get("people") or []:
            facts = person.get("facts_json") or {}
            for task in facts.get("tasks") or []:
                values = [
                    department["name"], person["user_name"], "TASK",
                    task.get("task_id") or task.get("match_key"),
                    SOURCE_LABELS.get(str(task.get("source_type")), task.get("source_type")),
                    STATUS_LABELS.get(str(task.get("classification")), task.get("classification")),
                    _clean_task_title(task.get("title")), "Po",
                ]
                for column, value in enumerate(values, 1):
                    evidence.cell(row, column, _value(value))
                row += 1
            for item in facts.get("observations") or []:
                values = [
                    department["name"], person["user_name"], "OBSERVATION", item.get("id"),
                    item.get("category"), item.get("marker"), item.get("comment"),
                    bool(item.get("verified")),
                ]
                for column, value in enumerate(values, 1):
                    evidence.cell(row, column, _value(value))
                row += 1
    evidence.freeze_panes = "A5"
    evidence.auto_filter.ref = f"A4:H{max(4, row - 1)}"
    for index, width in enumerate([22, 24, 14, 38, 20, 20, 55, 12], 1):
        evidence.column_dimensions[get_column_letter(index)].width = width

    guide = workbook.create_sheet("Udhëzuesi")
    _title(guide, "UDHËZUESI I VLERËSIMIT", "Rregulla deterministe, pa vlera monetare", 4)
    for column, label in enumerate(["Niveli", "Simboli", "Kushti", "Evidenca minimale"], 1):
        guide.cell(4, column, label)
        _header(guide.cell(4, column))
    rules = [
        ("A+", "+", "Plani i plotë + të paktën 2 angazhime ekstra të verifikuara", "Taska + observime të verifikuara"),
        ("A", "+", "Plani i plotë + 1 angazhim ekstra i verifikuar", "Taska + observim i verifikuar"),
        ("B", "+", "Plani normal i plotë", "Snapshot + prezenca"),
        ("C", "+/-", "3+ vonesa, përfundim me vonesë ose ndikim i vogël", "Prezenca/task/audit"),
        ("M", "+/-", "Mungesë personale e aprovuar dhe detyrat e mbuluara", "Aprovim + taska"),
        ("D", "-", "Shtyrje pa aprovim, takim i humbur ose ndikim i madh", "Evidencë e verifikuar"),
        ("E", "-", "Pa progres ose 2+ mungesa të papritura", "Progres + prezenca"),
    ]
    for row, rule in enumerate(rules, 5):
        for column, value in enumerate(rule, 1):
            cell = guide.cell(row, column, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        guide.cell(row, 1).fill = PatternFill("solid", fgColor=LEVEL_COLORS[rule[0]])
        guide.cell(row, 1).font = Font(bold=True)
    guide.merge_cells(start_row=13, start_column=1, end_row=13, end_column=4)
    guide.cell(13, 1, "SI LEXOHET RAPORTI")
    _header(guide.cell(13, 1))
    glossary = [
        ("Progresi javor", "Të mbyllura / në planin javor", "Akumulohet deri në snapshot-in e fundit", "Taskat e PLANNED"),
        ("Progresi ditor", "Të mbyllura sot / të planifikuara sot", "Nuk zëvendëson progresin javor", "Snapshot-i i orës 16:20"),
        ("Shtesë", "Taska pas PLANNED", "Raportohet veç; nuk fsheh planin e pambyllur", "Created_at + audit"),
        ("PV/FEST", "Pushim vjetor i plotë", "Personi përjashtohet nga realizimi", "Common View"),
    ]
    for row, item in enumerate(glossary, 14):
        for column, value in enumerate(item, 1):
            cell = guide.cell(row, column, value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        guide.cell(row, 1).font = Font(bold=True)
        guide.row_dimensions[row].height = 34
    question_row = 20
    guide.merge_cells(
        start_row=question_row,
        start_column=1,
        end_row=question_row,
        end_column=4,
    )
    question_count = sum(
        len(question_keys) for _section_title, question_keys in REPORT_QUESTION_SECTIONS
    )
    guide.cell(question_row, 1, f"{question_count} PYETJET E RAPORTIT")
    _header(guide.cell(question_row, 1))
    question_number = 1
    for section_title, question_keys in REPORT_QUESTION_SECTIONS:
        question_row += 1
        guide.merge_cells(
            start_row=question_row,
            start_column=1,
            end_row=question_row,
            end_column=4,
        )
        guide.cell(question_row, 1, section_title)
        _header(guide.cell(question_row, 1), "1F4E78")
        guide.cell(question_row, 1).alignment = Alignment(horizontal="left")
        for key in question_keys:
            question_row += 1
            values = (
                question_number,
                QUESTION_LABELS[key],
                "AUTO ose MANUAL",
                "Pa provë shënohet PËR KONFIRMIM; nuk hamendësohet.",
            )
            for column, value in enumerate(values, 1):
                cell = guide.cell(question_row, column, value)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            guide.row_dimensions[question_row].height = 30
            question_number += 1
    for index, width in enumerate([18, 24, 65, 45], 1):
        guide.column_dimensions[get_column_letter(index)].width = width
    guide.freeze_panes = "A5"

    detailed_guide = workbook.create_sheet("Udhëzuesi i Vlerësimit")
    _title(
        detailed_guide,
        "UDHËZUESI I VLERËSIMIT — SI VLERËSOHET NJË PUNËTOR ÇDO TË HËNË",
        "Rregulli kyç: A+ fitohet vetëm nëse janë kryer të gjitha detyrat dhe nuk i është "
        "prishur plani asnjë kolegu.",
        4,
    )
    detailed_row = 4

    def _guide_section_header(text: str) -> None:
        nonlocal detailed_row
        detailed_guide.merge_cells(
            start_row=detailed_row, start_column=1, end_row=detailed_row, end_column=4
        )
        detailed_guide.cell(detailed_row, 1, text)
        _header(detailed_guide.cell(detailed_row, 1), "1F4E78")
        detailed_guide.cell(detailed_row, 1).alignment = Alignment(horizontal="left")
        detailed_row += 1

    def _guide_note(text: str, fill: str = AMBER) -> None:
        nonlocal detailed_row
        detailed_guide.merge_cells(
            start_row=detailed_row, start_column=1, end_row=detailed_row, end_column=4
        )
        cell = detailed_guide.cell(detailed_row, 1, text)
        cell.font = Font(bold=True, size=9)
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(horizontal="left", wrap_text=True, vertical="center")
        detailed_guide.row_dimensions[detailed_row].height = 30
        detailed_row += 1

    def _guide_checklist(title: str, items: list[str]) -> None:
        nonlocal detailed_row
        _guide_section_header(title)
        detailed_guide.cell(detailed_row, 1, "Nr")
        detailed_guide.cell(detailed_row, 2, "Pyetja / Hapi i kontrollit")
        detailed_guide.cell(detailed_row, 3, "Kontrolluar (✓)")
        detailed_guide.cell(detailed_row, 4, "Shënime")
        for column in range(1, 5):
            _header(detailed_guide.cell(detailed_row, column), "5B9BD5")
        detailed_row += 1
        for index, item in enumerate(items, 1):
            detailed_guide.cell(detailed_row, 1, index)
            detailed_guide.cell(detailed_row, 2, item)
            for column in range(1, 5):
                cell = detailed_guide.cell(detailed_row, column)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
            detailed_row += 1
        detailed_row += 1

    _guide_note(
        "Bordi e barazon stafin dhe veten me të njëjtat kritere. Në fund, rezultatet "
        "barazohen dhe konfirmohen me Menaxheren (GA)."
    )
    _guide_note(
        "RREGULL KYÇ: A+ fitohet vetëm nëse janë kryer të gjitha detyrat dhe nuk i "
        "është prishur plani asnjë kolegu. Përmbushja e një afati NUK mjafton nëse për "
        "ta arritur i është prishur plani dikujt tjetër — niveli ulet automatikisht.",
        fill=RED,
    )

    _guide_checklist(
        "HAPI 2 — KONTROLLI I DETYRAVE (ditë për ditë, për çdo punëtor)",
        [
            "A janë përfunduar detyrat sipas planit?",
            "A ka detyra që nuk kanë pasur fare progres?",
            "A ka detyra që mbesin në proces edhe për këtë javë?",
            "A i janë shtuar punëtorit detyra të reja gjatë javës?",
            "A ka ndryshuar prioriteti i detyrave / a janë shtyrë detyra për javën "
            "tjetër ME KONFIRMIM?",
        ],
    )
    _guide_checklist(
        "HAPI 3 — KONTROLLI I ANGAZHIMIT",
        [
            "A i ka realizuar të gjitha detyrat e planit?",
            "A ka arritur t'i përfundojë dhe ka kërkuar edhe detyra të tjera?",
            "A ka ndihmuar ndonjë koleg gjatë javës?",
            "A ka dhënë ndonjë propozim për përmirësim?",
        ],
    )
    _guide_checklist(
        "HAPI 4 — KONTROLLI I DISIPLINËS",
        [
            "A i ka respektuar të gjitha oraret e takimeve?",
            "A i ka mbyllur dhe barazuar detyrat me rregull?",
            "A ka pasur vonesa të shpeshta gjatë javës?",
            "A ka pasur mungesa të papritura? (Mungesa e miratuar paraprakisht NUK "
            "penalizohet — shih nivelin M.)",
        ],
    )
    _guide_checklist(
        "HAPI 5 — VLERËSIMI ME + / +/- / -",
        [
            "Jepni + nëse: i ka realizuar të gjitha detyrat e planit, i ka respektuar "
            "oraret e takimeve dhe i ka mbyllur detyrat me rregull.",
            "Jepni + (dallon) nëse përveç realizimit të plotë ka edhe angazhim ekstra "
            "jashtë planit; + (dallon dukshëm) nëse ka disa angazhime ekstra së bashku.",
            "Jepni +/- për rastet e ndërmjetme: detyrat e kryera por me vonesa të "
            "shpeshta (C), ose mungesë e arsyetuar me shtyrje të konfirmuar (M).",
            "Jepni - nëse: nuk i ka kryer detyrat, nuk ka respektuar deadline/takimet, "
            "ose ka pasur mungesa të papritura pa arsye.",
        ],
    )

    _guide_section_header("HAPI 6 — CAKTIMI I NIVELIT TË REALIZIMIT (A+ deri E)")
    detailed_guide.cell(detailed_row, 1, "Niveli")
    detailed_guide.cell(detailed_row, 2, "Kur fitohet (kriteret)")
    detailed_guide.cell(detailed_row, 3, "Shembuj / Kundërshembuj")
    detailed_guide.cell(detailed_row, 4, "Bonusi")
    for column in range(1, 5):
        _header(detailed_guide.cell(detailed_row, column), "5B9BD5")
    detailed_row += 1
    level_rules: list[tuple[str, str, list[str], str]] = [
        (
            "A+",
            "Të gjitha detyrat + deadline + takimet + TË PAKTËN 2 nga: kërkoi shtesë / "
            "ndihmoi koleg / angazhim ekstra / propozim. DHE NUK IA KA PRISHUR PLANIN "
            "ASNJË KOLEGU (as pjesërisht, as edhe nëse vetë ka arritur afatin).",
            [
                "I kreu të gjitha detyrat, kërkoi detyra shtesë dhe propozoi automatizim → A+",
                "Kundërshembull: mbylli gjithçka brenda afatit POR informacioni i vonuar "
                "ia prishi planin një kolegu → NUK merret A+.",
            ],
            "50 €",
        ),
        (
            "A",
            "Të gjitha detyrat + deadline + takimet + VETËM 1 nga: kërkoi shtesë / "
            "ndihmoi koleg / angazhim ekstra / propozim.",
            [
                "Kreu gjithçka me kohë dhe ndihmoi 1 koleg → A",
                "Kundërshembull: ndihmoi 1 koleg POR ia prishi planin një tjetri → "
                "humb ekstrën, zbret në B.",
            ],
            "40 €",
        ),
        (
            "B",
            "Të gjitha detyrat + deadline + takimet. Pa vonesa, pa mungesa, pa ekstra. "
            "(Shtyrja ME konfirmim nuk e ul nivelin.) Pushim vjetor tërë javën → B automatik.",
            [
                "Javë e rregullt: plan i kryer, takime të respektuara, pa ekstra → B",
                "Kundërshembull: pa vonesa vetjake POR vonoi një informacion dhe kolegu "
                "duhej të rirregullonte planin → zbret në C.",
            ],
            "30 €",
        ),
        (
            "C",
            "Të gjitha detyrat + takimet, POR pati vonesa të shpeshta (3+ gjatë javës) "
            "ose mungoi 1 ditë PA njoftim (detyrat u kryen).",
            [
                "Plan i kryer plotësisht, por vonoi çdo ditë → C",
                "Mungoi 1 ditë PA lajmërim, të tjerat i kreu → C.",
            ],
            "20 €",
        ),
        (
            "M",
            "Mungesë/pushim personal E MIRATUAR paraprakisht me bordin. Detyrat e ditëve "
            "të punës të kryera; pjesa tjetër e shtyrë ME konfirmim.",
            [
                "Mungoi 2 ditë me miratim + detyrat e mbetura u shtynë me konfirmim → M",
                "Kundërshembull: mungesë e miratuar, por la pezull një detyrë urgjente "
                "të një kolegu pa njoftim → D, jo M.",
            ],
            "15 €",
        ),
        (
            "D",
            "NUK i kreu të gjitha detyrat pa konfirmim shtyrjeje, OSE nuk respektoi "
            "takimet, OSE mungoi 1 ditë PA njoftim dhe nuk i kreu detyrat.",
            [
                "Kreu 3 nga 5 detyra, 2 mbetën pa konfirmim, mungoi 1 takim → D",
                "RREGULLI D vs M: edhe 1 ditë PA njoftim → D automatikisht.",
            ],
            "max 10 €",
        ),
        (
            "E",
            "PA PROGRES gjatë gjithë javës, OSE mungesa të papritura 2+ ditë pa njoftim "
            "fare (zhdukje e plotë).",
            [
                "Asnjë detyrë e hapur, asnjë komunikim, 2 ditë mungesë pa njoftim → E",
                "Prezent fizikisht por 0 detyra të mbyllura dhe 0 progres → E",
            ],
            "0 €",
        ),
    ]
    for level, condition, examples, bonus in level_rules:
        row_start = detailed_row
        detailed_guide.cell(detailed_row, 1, level)
        detailed_guide.cell(detailed_row, 1).fill = PatternFill("solid", fgColor=LEVEL_COLORS[level])
        detailed_guide.cell(detailed_row, 1).font = Font(
            bold=True, color=WHITE if level in {"A+", "A", "E"} else "000000"
        )
        detailed_guide.cell(detailed_row, 2, condition)
        detailed_guide.cell(detailed_row, 3, "\n".join(f"• {item}" for item in examples))
        detailed_guide.cell(detailed_row, 4, bonus)
        detailed_guide.cell(detailed_row, 4).font = Font(bold=True)
        detailed_guide.cell(detailed_row, 4).alignment = Alignment(horizontal="center", vertical="top")
        for column in range(1, 5):
            cell = detailed_guide.cell(row_start, column)
            cell.alignment = Alignment(
                vertical="top", wrap_text=True,
                horizontal="center" if column in (1, 4) else "left",
            )
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        detailed_guide.row_dimensions[row_start].height = 70
        detailed_row += 1

    detailed_row += 1
    _guide_note(
        "MUNGESA — TABELA E SHPEJTË:  1 ditë ME njoftim → M  |  1 ditë PA njoftim, "
        "detyra kryer → C  |  1 ditë PA njoftim, detyra pa kryer → D  |  2+ ditë PA "
        "njoftim → E",
        fill=BLUE,
    )
    _guide_note(
        "RREGULLI: Fillo nga A+ dhe zbrit poshtë — niveli i parë ku përgjigjja është "
        "'Po' është niveli i punëtorit. Mungesa e miratuar paraprakisht = M, jo D/E.",
        fill=GREEN,
    )
    detailed_guide.freeze_panes = "A5"
    detailed_guide.column_dimensions["A"].width = 10
    detailed_guide.column_dimensions["B"].width = 55
    detailed_guide.column_dimensions["C"].width = 55
    detailed_guide.column_dimensions["D"].width = 16

    comments_sheet = workbook.create_sheet(_sheet_name("Komentet ditore", set(workbook.sheetnames)))
    _title(comments_sheet, "KOMENTET DHE EVIDENCA DITORE", f"{week_start} — {week_end}", 6)
    for column, label in enumerate(["Departamenti", "Punonjësi", "Data", "Burimi / Pyetja", "Autori", "Komenti"], 1):
        _header(comments_sheet.cell(4, column, label))
    comment_row = 5
    for department in departments:
        for person in department.get("people") or []:
            for day in (person.get("facts_json") or {}).get("daily_timeline") or []:
                for label, author, comment in _weekly_comments(day):
                    for column, value in enumerate([department["name"], person["user_name"], day.get("date"), label, author, comment], 1):
                        cell = comments_sheet.cell(comment_row, column, value)
                        cell.alignment = Alignment(vertical="top", wrap_text=True)
                    comments_sheet.row_dimensions[comment_row].height = min(400, max(48, 15 * (len(comment) // 75 + comment.count("\n") + 2)))
                    comment_row += 1
    for column, width in enumerate([24, 26, 15, 42, 24, 90], 1):
        comments_sheet.column_dimensions[get_column_letter(column)].width = width
    comments_sheet.freeze_panes = "C5"
    comments_sheet.auto_filter.ref = f"A4:F{max(4, comment_row - 1)}"

    diamonds_sheet = workbook.create_sheet(_sheet_name("Diamantat", set(workbook.sheetnames)))
    diamond_headers = ["Departamenti", "Punonjësi", "Data", "Burimi", "Taska / Propozimi", "Diamanta", "Komenti", "Dhënë nga", "ID e taskës / Realizimit"]
    _title(diamonds_sheet, "DIAMANTAT E JAVËS", f"{week_start} — {week_end}", len(diamond_headers))
    for column, label in enumerate(diamond_headers, 1):
        _header(diamonds_sheet.cell(4, column, label))
    diamond_row = 5
    for department in departments:
        for person in department.get("people") or []:
            for award in (person.get("facts_json") or {}).get("weekly_diamonds") or []:
                review = award.get("review") or {}
                values = [
                    department["name"], person["user_name"], _diamond_date(award.get("completed_at")),
                    "Propozim për përmirësim" if award.get("source") == "REALIZATION_PROPOSAL" else "Taskë e vlerësuar",
                    _clean_task_title(award.get("task_title")), int(review.get("diamond_score") or 0),
                    review.get("comment") or "", review.get("reviewer_name") or "",
                    award.get("task_id") or award.get("realization_period_id") or "",
                ]
                for column, value in enumerate(values, 1):
                    cell = diamonds_sheet.cell(diamond_row, column, value)
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                    cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
                comment = str(review.get("comment") or "")
                diamonds_sheet.row_dimensions[diamond_row].height = min(400, max(48, 15 * (len(comment) // 75 + comment.count("\n") + 2)))
                diamond_row += 1
    for column, width in enumerate([24, 26, 15, 30, 50, 12, 90, 26, 40], 1):
        diamonds_sheet.column_dimensions[get_column_letter(column)].width = width
    diamonds_sheet.freeze_panes = "C5"
    diamonds_sheet.auto_filter.ref = f"A4:I{max(4, diamond_row - 1)}"

    for ws in workbook.worksheets:
        # Treat user comments as text, including comments beginning with '='.
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f" and isinstance(cell.value, str):
                    cell.data_type = "s"
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
