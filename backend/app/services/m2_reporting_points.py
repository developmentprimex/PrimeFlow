from __future__ import annotations

import asyncio
import html
from datetime import date, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.services.after_break_report import UNFINISHED_PRIORITY_TABLE_LABEL, build_unfinished_priority_task_rows
from app.services.daily_realization_events import semantic_local_day
from app.services import m3_reporting_points as m3
from app.services.m3_reporting_points import planned_for_report_day
from app.services.meetings_report import _clean_task_title, _m3_am_pm_label, _m3_task_type_label
from app.services.note_markup import parse_marked_note_content
from app.services.personal_task_owner import personal_task_owner
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import GmailService, report_timezone
from app.services.task_marker import active_one_h_marker, active_one_h_marker_by_ga, one_h_marker_label

TITLE = "PIKAT PER RAPORTIM M2"
MANUAL_POINTS = {
    "reorganization": "1. RIORGANIZIM? (PARA PAUZES- PAS KO TE DET PM)- PAS PAUZES, TAKIM INT, NDARJE E DET",
}
AUTO_TITLES = {
    "unfinished_priority": f"2. {UNFINISHED_PRIORITY_TABLE_LABEL}/AM",
    "postponed": "3. A KA DET QE SHTYHEN (SOT/SOT) OSE DEADLINE?",
    "postponed_am": "DET QE JANE SHTYER SOT AM - PARA PAUZES",
    "ga_progress": "4. PROGRESI I DET ME GA (AM)",
    "delivery": "5. SA PER DOREZIM M2?",
}
DELIVERY_MARKERS = {"M2", "M2_M3"}


def subject_for(day: date) -> str:
    return f"{TITLE} - {day:%d.%m.%Y}"


def select_task_sections(tasks, events, day: date, *, personal_titles: dict | None = None) -> dict:
    # M2 reports outstanding postponements; completed tasks no longer need follow-up.
    sections = {"postponed": [row for row in m3.select_task_sections(tasks, events, day)["ga_postponed"]
                              if row["status"] != "DONE"],
                "postponed_am": [row for row in m3.select_task_sections(tasks, events, day, postponement_period="AM")["postponed"]
                                 if row["status"] != "DONE" and planned_for_report_day(row, day)],
                "ga_progress": [], "delivery": []}
    for task in tasks:
        marker = active_one_h_marker(task, day)
        system = bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None))
        title = _clean_task_title(task.title, is_system_task=system)
        personal_title = parse_marked_note_content(
            (personal_titles or {}).get(getattr(task, "ga_note_origin_id", None))
            or (personal_titles or {}).get(getattr(task, "plan_note_origin_id", None)) or title
        ).text.strip()
        personal_ga = bool(getattr(task, "is_personal", False) and personal_task_owner(personal_title) == "GA")
        am_pm = _m3_am_pm_label(task)
        ga_progress = am_pm in {"AM", "AM/PM"} and (marker in {"F", "FLAG"} or personal_ga)
        if marker not in DELIVERY_MARKERS and not ga_progress:
            continue
        start, due, created, completed = (semantic_local_day(getattr(task, field, None))
                                         for field in ("start_date", "due_date", "created_at", "completed_at"))
        status = str(getattr(task.status, "value", task.status)).upper()
        # Membership uses the inclusive planning interval, including completed tasks.
        if (created and created > day) or start is None or due is None or not start <= day <= due:
            continue
        row = {
            "task_id": str(task.id), "title": title,
            "status": status, "progress": task.progress_percentage or 0,
            "start_date": start.isoformat(), "due_date": due.isoformat(),
            "created_date": created.isoformat() if created else None, "completed_date": completed.isoformat() if completed else None,
            "am_pm": am_pm, "task_type": _m3_task_type_label(task),
            "deadline_important": bool(task.is_deadline_important), "is_system_task": system,
            "marker": one_h_marker_label(marker, active_one_h_marker_by_ga(task, day)),
        }
        if ga_progress:
            sections["ga_progress"].append(dict(row, title=personal_title if personal_ga else parse_marked_note_content(title).text))
        if marker in DELIVERY_MARKERS:
            sections["delivery"].append(row)
    return sections


async def build_task_data(db: AsyncSession, day: date) -> dict:
    # Common View classifies note-based personal tasks using the original note text.
    personal_titles = {}
    for model, origin in ((GaNote, Task.ga_note_origin_id), (PlanNote, Task.plan_note_origin_id)):
        personal_titles.update((await db.execute(select(model.id, model.content).join(
            Task, origin == model.id,
        ).where(Task.is_active.is_(True), Task.is_personal.is_(True)))).all())
    data = await m3.build_task_data(db, day, section_selector=lambda tasks, events, report_day:
        select_task_sections(tasks, events, report_day, personal_titles=personal_titles))
    rows = await build_unfinished_priority_task_rows(db, day)
    data["unfinished_priority"] = [
        {"assignees": row[1], "department": row[2], "am_pm": row[3], "status": row[4],
         "priority": row[5], "task_type": row[6], "title": row[7], "due_label": row[8],
         "deadline_important": "DEADLINE" in row[5], "eight_am": "08:00" in row[5]}
        for row in rows
    ]
    return data


async def get_settings(db: AsyncSession):
    from types import SimpleNamespace
    from app.services.reporting_points_settings import get_delivery_settings, manual_recipients
    settings = await get_delivery_settings(db, "M2")
    return SimpleNamespace(recipients=await manual_recipients(db, "M2", settings))


async def locked_report(db: AsyncSession, day: date, *, wait: bool = True) -> M2ReportingPointsReport | None:
    function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
    acquired = (await db.execute(text(f"SELECT {function}(hashtext(:key))"),
                                {"key": f"m2_reporting_points|{day.isoformat()}"})).scalar()
    if not wait and not acquired:
        return None
    row = (await db.execute(select(M2ReportingPointsReport).where(M2ReportingPointsReport.report_date == day))).scalar_one_or_none()
    if row is None:
        row = M2ReportingPointsReport(report_date=day, manual_answers={}, data={}, status="DRAFT")
        db.add(row)
        await db.flush()
    return row


async def refresh_report(db: AsyncSession, row: M2ReportingPointsReport, now: datetime | None = None) -> None:
    now = (now or datetime.now(report_timezone())).astimezone(report_timezone())
    if row.report_date != now.date():
        raise ValueError("Raportet historike perdorin te dhenat e ruajtura te asaj dite.")
    row.data = await build_task_data(db, row.report_date)
    row.generated_at = now


def report_payload(row: M2ReportingPointsReport) -> dict:
    data = dict(row.data or {})
    if "postponed_am" in data:
        data["postponed_am"] = [item for item in data["postponed_am"]
                                if planned_for_report_day(item, row.report_date)]
    return {"id": str(row.id), "report_date": row.report_date.isoformat(), "subject": subject_for(row.report_date),
            "manual_answers": {key: value for key, value in (row.manual_answers or {}).items() if key != "ga_reply"},
            "data": data, "status": row.status,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None, "last_error": row.last_error}


def table_groups(report, key):
    return m3.task_table_groups(report.get("data", {}).get(key, []), "ga_postponed" if key in {"postponed", "postponed_am"} else key)


def table_columns(key, movement=""):
    if key == "unfinished_priority":
        return [("nr", "NR", 28), ("assignees", "KUSH", 72), ("department", "DEP", 44),
                ("am_pm", "AM/PM", 60), ("priority", "LLOJI", 120), ("task_type", "TIPI", 48),
                ("title", "TITULLI", 450), ("due_label", "DUE DATE", 80)]
    if key == "ga_progress":
        return [("nr", "NR", 28), ("assignees", "KUSH", 42), ("department", "DEP", 44),
                ("project", "PRJK", 96), ("am_pm", "AM/PM", 60), ("task_type", "LLOJI", 48),
                ("marker", "SIMBOLI", 60), ("title", "TITULLI", 450)]
    if key in {"postponed", "postponed_am"}:
        return [(field, label, 60 if field == "am_pm" else width) for field, label, width in m3.report_table_columns("ga_postponed", movement)
                if field not in {"reason", "comment", "category"}] + [("manual_comment", "KOMENT MANUAL", 220)]
    return [("nr", "NR", 28), ("assignees", "KUSH", 42), ("department", "DEP", 44),
            ("project", "PRJK", 96), ("am_pm", "AM/PM", 60), ("task_type", "LLOJI", 48),
            ("marker", "SIMBOLI", 60), ("title", "TITULLI", 450), ("choice", "PO/JO", 50), ("answer", "PERGJIGJJA MANUALE", 300)]


def table_value(report, row, column, index, movement):
    if column == "manual_comment":
        return report.get("manual_answers", {}).get(f"postponed_comment:{row['task_id']}") or "-"
    if column == "choice":
        return report.get("manual_answers", {}).get(f"delivery_choice:{row['task_id']}") or "-"
    if column == "answer":
        return report.get("manual_answers", {}).get(f"delivery:{row['task_id']}") or "Pa pergjigje"
    if not movement and column == "title":
        return row.get("title") or "-"
    if column == "marker":
        return row.get("marker") or "-"
    return m3.report_table_value(row, column, index, movement)


def export_blocks(report):
    blocks = [{"kind": "text", "text": TITLE, "level": 1},
              {"kind": "text", "text": f"Data: {report['report_date']}", "level": 0}]
    for key, title in MANUAL_POINTS.items():
        blocks.extend([{"kind": "text", "text": title, "level": 2},
                       {"kind": "text", "text": report.get("manual_answers", {}).get(key) or "Pa pergjigje", "level": 0}])
    for key, title in AUTO_TITLES.items():
        blocks.append({"kind": "text", "text": title, "level": 2})
        if key == "delivery":
            rows = report.get("data", {}).get("delivery", [])
            delivered = sum(report.get("manual_answers", {}).get(f"delivery_choice:{row['task_id']}") == "PO" for row in rows)
            blocks.append({"kind": "text", "text": f"SA/TOTALI: {delivered}/{len(rows)}", "level": 3, "font_size": 14})
        if key in {"postponed", "postponed_am"}:
            blocks.append({"kind": "legend", "runs": [
                ("Shtyrjet e bëra gjatë ditës. ", None, "#000000"),
                ("Brenda javës: OK.", "#dcfce7", "#14532d"),
                (" Për të premten ose javën tjetër: RREZIK.", "#fee2e2", "#7f1d1d"),
            ]})
        for caption, movement, rows in table_groups(report, key):
            if caption:
                blocks.append({"kind": "text", "text": caption, "level": 3})
            if not rows:
                blocks.append({"kind": "text", "text": "Asnje detyre.", "level": 0})
                continue
            columns = table_columns(key, movement)
            rendered = []
            for index, row in enumerate(rows, 1):
                fill, color, eight_am = m3.task_row_appearance(row)
                cells = []
                for column_index, (column, _, _) in enumerate(columns):
                    value = str(table_value(report, row, column, index, movement))
                    cell_fill, cell_color = fill, color
                    if column in {"answer", "manual_comment", "choice"}:
                        cell_fill, cell_color = "#ffffff", "#000000"
                    if column == "choice" and value in {"PO", "JO"}:
                        cell_fill, cell_color = ("#16a34a" if value == "PO" else "#dc2626"), "#ffffff"
                    if column == "risk":
                        cell_fill, cell_color = ("#fee2e2", "#7f1d1d") if value == "RREZIK" else ("#dcfce7", "#14532d")
                    cells.append({
                        "text": value, "fill": cell_fill, "color": cell_color,
                        "bold": column in {"title", "marker", "choice", "risk"}, "marker": row.get("marker") if key in {"postponed", "postponed_am"} and column == "title" else None,
                        "eight_am": eight_am, "first": column_index == 0, "last": column_index == len(columns) - 1,
                        "divider": column in {"from", "to"} and movement == "start_due",
                    })
                rendered.append(cells)
            blocks.append({"kind": "table", "columns": columns, "rows": rendered})
    return blocks


def render_html(report):
    def escaped(value):
        return html.escape(str(value), quote=True).replace("\n", "<br>")
    parts = ["<!doctype html><html><head><meta charset='utf-8'></head><body style='font-family:Arial,sans-serif;color:#0f172a'>"]
    for block in export_blocks(report):
        if block["kind"] == "text":
            tag = "h1" if block["level"] == 1 else "h3" if block["level"] else "p"
            style = f" style='font-size:{block['font_size']}pt;font-weight:bold'" if block.get("font_size") else ""
            parts.append(f"<{tag}{style}>{escaped(block['text'])}</{tag}>")
        elif block["kind"] == "legend":
            parts.append("<p style='font-weight:bold'>" + "".join(
                f"<span style='background:{fill or 'transparent'};color:{color};padding:2px 4px'>{escaped(value)}</span>"
                for value, fill, color in block["runs"]) + "</p>")
        else:
            header = "".join(f"<th width='{width}' style='border:1px solid #000;padding:6px;background:#e2e8f0;text-align:left'>{escaped(label)}</th>" for _, label, width in block["columns"])
            def render_cell(cell):
                style = f"border:1px solid #000;padding:6px;vertical-align:top;background:{cell['fill']};color:{cell['color']};overflow-wrap:anywhere"
                if cell.get("bold"):
                    style += ";font-weight:bold"
                if cell.get("eight_am"):
                    style += ";border-top:3px solid #dc2626;border-bottom:3px solid #dc2626"
                    if cell.get("first"):
                        style += ";border-left:3px solid #dc2626"
                    if cell.get("last"):
                        style += ";border-right:3px solid #dc2626"
                value = escaped(cell["text"])
                if cell.get("divider"):
                    first, _, last = cell["text"].partition("\n")
                    value = f"<div style='border-bottom:2px solid #000;padding-bottom:3px;margin-bottom:3px'>{escaped(first)}</div>{escaped(last)}"
                return f"<td style='{style}'>{value}</td>"
            rows = "".join("<tr>" + "".join(render_cell(cell) for cell in row) + "</tr>" for row in block["rows"])
            parts.append(f"<table width='100%' cellspacing='0' style='border-collapse:collapse;font-size:12px'><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>")
    return "".join(parts) + "</body></html>"


def render_plain_text(report):
    return "\n\n".join(block["text"] if block["kind"] == "text" else
        "".join(value for value, _, _ in block["runs"]) if block["kind"] == "legend" else "\n".join(
        " | ".join(f"{column[1]}: {cell['text']}" for column, cell in zip(block["columns"], row))
        for row in block["rows"]) for block in export_blocks(report))


def report_attachments(report):
    from app.services.m3_reporting_points_attachments import render_docx, render_png, DOCX_MIME
    from app.services.reporting_points_excel import render_xlsx, XLSX_MIME
    blocks = export_blocks(report)
    stem = f"pikat_m2_{report['report_date']}"
    return [(stem + ".docx", render_docx(report, blocks=blocks), DOCX_MIME),
            (stem + ".png", render_png(report, blocks=blocks), "image/png"),
            (stem + ".xlsx", render_xlsx(blocks, sheet_name="PIKAT M2"), XLSX_MIME)]


async def send_report(db, row, recipients, *, automatic: bool = False):
    recipients = normalize_recipients(recipients)
    if not recipients["to"]:
        raise ValueError("Shto te pakten nje marres To ne konfigurimin e M2.")
    report = report_payload(row)
    try:
        gmail = GmailService()
        html_body = render_html(report)
        attachments = await asyncio.to_thread(report_attachments, report)
        # Every manual send is a new delivery, including an unchanged report.
        message = await gmail.send_verified(report["subject"], recipients, render_plain_text(report), html_body,
            attachments=[(f"pikat_m2_{row.report_date.isoformat()}.html", html_body.encode("utf-8"), "text/html"), *attachments])
    except Exception as exc:
        row.status, row.last_error = "FAILED", str(exc)[:2000]
        await db.commit()
        raise
    row.status, row.sent_at = "SENT", datetime.now(report_timezone())
    row.gmail_message_id, row.last_error = message.get("id"), None
    if automatic:
        row.auto_sent_at = row.sent_at
    await db.commit()
