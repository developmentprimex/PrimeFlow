from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from datetime import date, datetime, time, timedelta
from typing import Callable

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from app.db import SessionLocal
from app.models.enums import GaNoteStatus
from app.models.ga_note import GaNote
from app.services.report_note_visibility import is_mira_note, mira_note_expression
from app.models.plan_note import PlanNote
from app.models.primeflow_report_delivery_run import PrimeFlowReportDeliveryRun
from app.models.primeflow_report_recipient import PrimeFlowReportRecipient
from app.models.primeflow_report_snapshot import PrimeFlowReportSnapshot
from app.models.task import Task
from app.models.task_strike_event import TaskStrikeEvent
from app.models.user import User
from app.services.primeflow_report import (
    GmailService, GmailVerificationError, PrimeFlowClient,
    REPORT_SENDER_EMAIL, ReportDocument, ReportReminderQuestion, ReportUndiscussedNote, clean_description, build_report_document,
    predecessor, render_docx, render_html, render_plain_text, render_png, report_subject, report_timezone,
)
from app.services.one_h_ga_attachments import build_ga_only_1h_attachments, render_ga_tables_html
from app.services.task_strike_events import render_text_for_interval
from app.services.task_title_rules import normalize_email_task_title
from app.services.tomorrow_print_report import build_today_print_report

logger = logging.getLogger(__name__)
TERMINAL = {"SENT", "ALREADY_SENT"}
GA_ATTACHMENT_RECIPIENTS = ("ga@primexeu.com",)
STRIKE_INTERVAL_STARTS = {
    "10:00": time(8, 0),
    "11:00": time(10, 0),
    "11:50": time(11, 0),
    "14:10": time(11, 50),
    "14:20": time(11, 50),
    "16:00": time(14, 20),
}
STRIKE_INTERVAL_ENDS = {
    "10:00": time(10, 0),
    "11:00": time(11, 0),
    "11:50": time(11, 50),
    "14:10": time(14, 20),
    "14:20": time(14, 20),
    "16:00": time(16, 0),
}


def split_ga_recipient_map(
    recipients: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]] | None]:
    """Separate GA so the timetable, SHTYPI, and extra PNGs cannot leak."""
    regular = {key: [] for key in ("to", "cc", "bcc")}
    seen: set[str] = set()
    extra_targets = {email.casefold() for email in GA_ATTACHMENT_RECIPIENTS}
    for key in ("to", "cc", "bcc"):
        for raw in recipients.get(key, []):
            email = str(raw).strip()
            normalized = email.casefold()
            if not email or normalized in seen:
                continue
            seen.add(normalized)
            if normalized in extra_targets:
                continue
            regular[key].append(email)

    # SMTP requires a To header. This preserves the recipient set if GA was
    # the only To address and the regular message has only CC/BCC recipients.
    if not regular["to"]:
        for key in ("cc", "bcc"):
            if regular[key]:
                regular["to"].append(regular[key].pop(0))
                break
    ga = {"to": list(GA_ATTACHMENT_RECIPIENTS), "cc": [], "bcc": []} if GA_ATTACHMENT_RECIPIENTS else None
    return regular, ga


def _regular_recipient_document(document: ReportDocument) -> ReportDocument:
    """Remove the two 1H question blocks from the non-GA report variant."""
    return document.model_copy(
        update={"board_reminders": [], "reminders": []},
        deep=True,
    )


def _environment_recipients() -> list[str]:
    raw = os.getenv("PRIMEFLOW_REPORT_RECIPIENTS", "130primex.eu@gmail.com,ga@primexeu.com")
    return [value.strip() for value in raw.split(",") if value.strip()]


def validate_report_config(*, require_gmail: bool = True) -> None:
    required = ["DATABASE_URL", "PRIMEFLOW_API_BASE_URL", "PRIMEFLOW_REPORT_TIMEZONE"]
    if not os.getenv("PRIMEFLOW_ACCESS_TOKEN"):
        required.extend(["PRIMEFLOW_EMAIL", "PRIMEFLOW_PASSWORD"])
    if require_gmail:
        required.append("EMAIL_PASSWORD")
    missing = sorted({name for name in required if not os.getenv(name)})
    if missing:
        raise RuntimeError("Missing required report configuration: " + ", ".join(missing))
    configured_sender = (os.getenv("EMAIL_USER") or REPORT_SENDER_EMAIL).strip()
    if require_gmail and configured_sender.casefold() != REPORT_SENDER_EMAIL.casefold():
        raise RuntimeError(
            f"PrimeFlow reports must be sent from {REPORT_SENDER_EMAIL}; "
            f"configured sender is {configured_sender}"
        )
    report_timezone()


async def configured_recipients(report_type: str = "ONE_H") -> dict[str, list[str]]:
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(PrimeFlowReportRecipient)
            .where(PrimeFlowReportRecipient.is_active.is_(True))
            .where(PrimeFlowReportRecipient.report_type == report_type)
            .order_by(PrimeFlowReportRecipient.sort_order, PrimeFlowReportRecipient.email)
        )).scalars().all()
    if not rows and report_type == "ONE_H":
        return {"to": _environment_recipients(), "cc": [], "bcc": []}
    if not rows:
        return {"to": [], "cc": [], "bcc": []}
    result = {"to": [], "cc": [], "bcc": []}
    for row in rows:
        result[row.recipient_type.lower()].append(row.email)
    return result


async def load_1h_reminder_questions(
    slot: str | None = None, report_day: date | None = None
) -> list[ReportReminderQuestion]:
    """Return the 1H staff steps, including Thursday/Friday week-closing checks."""
    reminders = [
        ReportReminderQuestion(text="Hap doc dhe det"),
        ReportReminderQuestion(text="Share screen side by side DET/REZULTATIN"),
        ReportReminderQuestion(text="Sqaro slotin paraprak pastaj aktual"),
    ]
    if slot == "11:50":
        reminders.append(
            ReportReminderQuestion(text="A ka me dergu dikush doc te GA/KA para pauzes?")
        )
    reminders.append(
        ReportReminderQuestion(
            text="BZ Det nga Stafi per GA",
            guidance="Komunikimi GA teams Det nga Stafi/ KA email",
        )
    )
    if report_day is not None and report_day.weekday() == 3:
        reminders.extend([
            ReportReminderQuestion(
                text="Emails per missing info, per me vazhdu javen tjeter", is_extra=True
            ),
            ReportReminderQuestion(
                text="Shikohen det qe mbesin vetem per neser (te premten)", is_extra=True
            ),
        ])
    elif report_day is not None and report_day.weekday() == 4:
        reminders.extend([
            ReportReminderQuestion(text="BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL", is_extra=True),
            ReportReminderQuestion(text="BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS", is_extra=True),
            ReportReminderQuestion(text="Barazimi i planifikimit javor - next week", is_extra=True),
            ReportReminderQuestion(text="Barazimi i realizimit javor - this week", is_extra=True),
            ReportReminderQuestion(
                text="Emails per missing info, per me vazhdu javen tjeter", is_extra=True
            ),
        ])
    return reminders


def _optional_attachment(
    filename: str,
    content_type: str,
    renderer: Callable[[], bytes],
    warnings: list[str],
) -> tuple[str, bytes, str] | None:
    """Render an attachment without allowing it to cancel the email body."""
    try:
        return filename, renderer(), content_type
    except Exception as exc:
        warning = f"{filename}: {type(exc).__name__}: {exc}"
        warnings.append(warning)
        logger.exception("primeflow_report_optional_attachment_failed filename=%s", filename)
        return None


def _undiscussed_px_notes_statement():
    """Return the active, unconverted, undiscussed rows from the PX Notes page."""
    active_task_exists = (
        select(Task.id)
        .where(Task.ga_note_origin_id == GaNote.id)
        .where(Task.is_active.is_(True))
        .exists()
    )
    return (
        select(GaNote, User.full_name, User.username, User.email)
        .outerjoin(User, User.id == GaNote.created_by)
        .where(GaNote.status != GaNoteStatus.CLOSED)
        .where(GaNote.is_discussed.is_(False))
        .where(GaNote.is_converted_to_task.is_(False))
        .where(~mira_note_expression())
        .where(~active_task_exists)
        .order_by(GaNote.created_at.desc(), GaNote.updated_at.desc())
    )


async def load_undiscussed_notes(*, show_full_mira_notes: bool = False) -> list[ReportUndiscussedNote]:
    """Load the PX Notes rows that still need discussion in the 1H report."""
    # Keep the legacy request option compatible; Mira notes are always excluded.
    async with SessionLocal() as db:
        rows = (await db.execute(_undiscussed_px_notes_statement())).all()
    notes = []
    for note, full_name, username, email in rows:
        if is_mira_note(note):
            continue
        content = clean_description(note.content)
        if not content:
            continue
        notes.append(ReportUndiscussedNote(
            content=content,
            author=(full_name or username or email or "-"),
            created_at=note.created_at,
        ))
    return notes


def _report_task_text(data: dict) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str | None]]:
    """Read task titles and descriptions that can be shown in the report."""

    titles: dict[uuid.UUID, str] = {}
    descriptions: dict[uuid.UUID, str | None] = {}
    for bucket in (data.get("items") or {}).values():
        if not isinstance(bucket, list):
            continue
        for task in bucket:
            if not isinstance(task, dict) or (task.get("task_id") is None and task.get("id") is None):
                continue
            try:
                # Common View uses a date-specific display id (`task:<id>:<day>`)
                # but strike history belongs to the underlying task UUID.
                task_id = uuid.UUID(str(task.get("task_id") or task["id"]))
            except (TypeError, ValueError):
                continue
            title = task.get("title") or task.get("task_title") or task.get("task")
            if title is not None:
                titles[task_id] = str(title)
            if "description" in task:
                descriptions[task_id] = task.get("description")
    return titles, descriptions


def strike_interval_start(day: date, slot: str) -> datetime:
    """Fixed reporting windows agreed for the five weekday 1H emails."""
    try:
        start = STRIKE_INTERVAL_STARTS[slot]
    except KeyError as exc:
        raise ValueError(f"Unsupported 1H report slot: {slot}") from exc
    return datetime.combine(day, start, tzinfo=report_timezone())


def strike_interval_end(day: date, slot: str) -> datetime:
    try:
        end = STRIKE_INTERVAL_ENDS[slot]
    except KeyError as exc:
        raise ValueError(f"Unsupported 1H report slot: {slot}") from exc
    return datetime.combine(day, end, tzinfo=report_timezone())


async def _text_overrides_for_1h_interval(
    data: dict,
    day: date,
    slot: str,
    *,
    interval_end: datetime,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    titles, descriptions = _report_task_text(data)
    task_ids = set(titles) | set(descriptions)
    if not task_ids:
        return {}, {}
    # Load the current task/note text and its strike history in one statement.
    # Common View is fetched through a separate HTTP request and can cross a
    # task-save commit boundary. Using its text together with newer strike
    # events made a fresh report temporarily suppress blue/green strikes until
    # a later regeneration happened to receive matching snapshots.
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(
                Task.id,
                Task.title,
                Task.description,
                Task.system_template_origin_id,
                Task.system_task_slot_id,
                GaNote.content,
                PlanNote.content,
                TaskStrikeEvent,
            )
            .outerjoin(GaNote, Task.ga_note_origin_id == GaNote.id)
            .outerjoin(PlanNote, Task.plan_note_origin_id == PlanNote.id)
            .outerjoin(
                TaskStrikeEvent,
                and_(
                    TaskStrikeEvent.task_id == Task.id,
                    TaskStrikeEvent.occurred_at <= interval_end,
                ),
            )
            .where(Task.id.in_(task_ids))
            .order_by(Task.id, TaskStrikeEvent.occurred_at, TaskStrikeEvent.id)
        )).all()

    by_task: dict[uuid.UUID, list[TaskStrikeEvent]] = {}
    current_titles: dict[uuid.UUID, str] = {}
    current_descriptions: dict[uuid.UUID, str | None] = {}
    for row in rows:
        if len(row) == 8:
            task_id, task_title, task_description, system_template_origin_id, system_task_slot_id, ga_content, plan_content, event = row
        else:  # Compatibility with lightweight report/test row providers.
            task_id, task_title, task_description, ga_content, plan_content, event = row
            system_template_origin_id = system_task_slot_id = None
        source_title = ga_content or plan_content or task_title or ""
        normalized_title = "\n".join(
            " ".join(line.split())
            for line in str(source_title).replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if line.strip()
        )
        current_titles[task_id] = normalize_email_task_title(
            normalized_title,
            is_system_task=system_template_origin_id is not None or system_task_slot_id is not None,
        )
        current_descriptions[task_id] = task_description
        if event is not None:
            by_task.setdefault(task_id, []).append(event)

    # A task removed between the Common View request and this query can safely
    # retain the payload value. Every task still present uses authoritative text
    # from the same database snapshot as the event rows.
    titles.update({task_id: value for task_id, value in current_titles.items() if task_id in titles})
    descriptions.update({
        task_id: value for task_id, value in current_descriptions.items() if task_id in descriptions
    })
    interval_start = strike_interval_start(day, slot)
    title_overrides = {
        str(task_id): render_text_for_interval(
            title,
            by_task.get(task_id, []),
            interval_start=interval_start,
            interval_end=interval_end,
            field_name="TITLE",
        )
        for task_id, title in titles.items()
    }
    description_overrides = {
        str(task_id): render_text_for_interval(
            description,
            by_task.get(task_id, []),
            interval_start=interval_start,
            interval_end=interval_end,
            field_name="DESCRIPTION",
        )
        for task_id, description in descriptions.items()
    }
    return title_overrides, description_overrides


async def load_common_view(day: date) -> dict:
    client = PrimeFlowClient(
        os.environ["PRIMEFLOW_API_BASE_URL"].rstrip("/"),
        os.getenv("PRIMEFLOW_EMAIL"), os.getenv("PRIMEFLOW_PASSWORD"), os.getenv("PRIMEFLOW_ACCESS_TOKEN"),
    )
    return await client.common_view(day)


async def generate_fresh(
    day: date,
    slot: str,
    recipients: dict[str, list[str]] | None = None,
    *,
    data: dict | None = None,
    show_full_mira_notes: bool = False,
) -> ReportDocument:
    data = data or await load_common_view(day)
    reminders = await load_1h_reminder_questions(slot, day)
    undiscussed_notes = await load_undiscussed_notes(show_full_mira_notes=show_full_mira_notes)
    title_overrides, description_overrides = await _text_overrides_for_1h_interval(
        data, day, slot, interval_end=strike_interval_end(day, slot),
    )
    return build_report_document(
        data,
        day,
        slot,
        recipients or await configured_recipients(),
        reminders=reminders,
        undiscussed_notes=undiscussed_notes,
        title_overrides=title_overrides,
        description_overrides=description_overrides,
        completion_window_start=strike_interval_start(day, slot),
        completion_window_end=strike_interval_end(day, slot),
    )


async def render_ga_recipient_email_html(
    db: AsyncSession,
    document: ReportDocument,
    day: date,
    *,
    today_print_html: str | None = None,
    source_data: dict | None = None,
) -> str:
    """Render the same GA-only email body for previews and real delivery."""
    if today_print_html is None:
        source_data = source_data or await load_common_view(day)
        try:
            today_print_report = await build_today_print_report(
                day,
                include_attachment=False,
                payload=source_data,
            )
            today_print_html = today_print_report["content_html"]
        except Exception:
            logger.exception("primeflow_report_ga_preview_today_print_failed")
            today_print_html = ""
    from app.services.today_print_strikes import render_embedded_print_strikes

    today_print_html = await render_embedded_print_strikes(
        db, today_print_html, day, document.report_slot,
    )
    return render_html(
        document,
        pre_sections_html=await render_ga_tables_html(
            db,
            day,
            today_print_html=today_print_html,
        ),
        content_width=1200,
    )


async def deliver_report(
    day: date, slot: str, *, send: bool = True, scheduled_for: datetime | None = None,
    recipient_map: dict[str, list[str]] | None = None, trigger_type: str = "SCHEDULED",
    triggered_by_user_id=None, manual_reason: str | None = None, schedule_id=None,
    schedule_version: int | None = None, recipient_group: str = "default",
    show_full_mira_notes: bool = False,
) -> PrimeFlowReportDeliveryRun:
    if trigger_type == "MANUAL" and recipient_group == "default":
        recipient_group = f"manual-{uuid.uuid4().hex}"
    recipient_map = recipient_map or await configured_recipients()
    recipients = sum(recipient_map.values(), [])
    subject = report_subject(day, slot)
    now = datetime.now(report_timezone())
    async with SessionLocal() as db:
        async with db.begin():
            # Serialize even the first insert; the unique constraint remains the
            # final guard if another application bypasses this service.
            lock_key = f"primeflow_1h|{day.isoformat()}|{slot}|{recipient_group}"
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})
            run = (await db.execute(
                select(PrimeFlowReportDeliveryRun)
                .where(
                    PrimeFlowReportDeliveryRun.report_type == "primeflow_1h",
                    PrimeFlowReportDeliveryRun.report_date == day,
                    PrimeFlowReportDeliveryRun.report_slot == slot,
                    PrimeFlowReportDeliveryRun.recipient_group == recipient_group,
                ).with_for_update()
            )).scalar_one_or_none()
            if run is None:
                run = PrimeFlowReportDeliveryRun(
                    report_date=day, report_slot=slot, recipient_group=recipient_group,
                    subject=subject, recipients=json.dumps(recipients), status="PENDING",
                    scheduled_for=scheduled_for, trigger_type=trigger_type,
                    triggered_by_user_id=triggered_by_user_id, manual_reason=manual_reason,
                    schedule_id=schedule_id, schedule_version=schedule_version,
                    scheduled_execution_time=scheduled_for,
                )
                db.add(run)
                await db.flush()
            if run.status in TERMINAL:
                return run
            if run.status == "RUNNING" and run.started_at and run.started_at > now - timedelta(minutes=30):
                return run
            run.status, run.started_at, run.attempt_count = "RUNNING", now, run.attempt_count + 1
            run.error_code = None
            run.error_message = None

        gmail = GmailService() if send else None
        try:
            if gmail:
                existing = await gmail.find_exact(subject, recipients)
                if existing:
                    run.status = "ALREADY_SENT"
                    run.gmail_message_id, run.gmail_thread_id = existing.get("id"), existing.get("threadId")
                    run.finished_at = datetime.now(report_timezone())
                    await db.commit()
                    return run
            source_data = await load_common_view(day)
            document = await generate_fresh(day, slot, recipient_map, data=source_data, show_full_mira_notes=show_full_mira_notes)
            attachment_warnings: list[str] = []
            try:
                today_print_report = await build_today_print_report(
                    day,
                    include_attachment=True,
                    payload=source_data,
                )
            except Exception as exc:
                attachment_warnings.append(
                    f"today-print attachments: {type(exc).__name__}: {exc}"
                )
                logger.exception("primeflow_report_today_print_attachments_failed")
                # The native HTML report remains deliverable without optional files.
                today_print_report = await build_today_print_report(
                    day,
                    include_attachment=False,
                    payload=source_data,
                )
            ga_body = render_plain_text(document)
            ga_base_html = render_html(document)
            regular_document = _regular_recipient_document(document)
            regular_body = render_plain_text(regular_document)
            regular_html_body = render_html(regular_document)
            run.body_hash = hashlib.sha256(ga_body.encode("utf-8")).hexdigest()
            run.data_generated_at = document.source_generated_at
            snapshot = (await db.execute(
                select(PrimeFlowReportSnapshot).where(PrimeFlowReportSnapshot.delivery_run_id == run.id)
            )).scalar_one_or_none()
            if snapshot is None:
                snapshot = PrimeFlowReportSnapshot(
                    delivery_run_id=run.id,
                    normalized_report_json=document.model_dump(mode="json"),
                    plain_text_body=ga_body,
                    html_body=ga_base_html,
                    content_version=1,
                )
                db.add(snapshot)
            if not send:
                run.status, run.finished_at = "PENDING", datetime.now(report_timezone())
                await db.commit()
                setattr(run, "dry_run_body", ga_body)
                return run
            filename_stem = f"PrimeFlow-1H-{day:%Y-%m-%d}-{slot.replace(':', '')}"
            regular_attachments = [attachment for attachment in [
                _optional_attachment(
                    f"{filename_stem}.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    lambda: render_docx(regular_document),
                    attachment_warnings,
                ),
                _optional_attachment(
                    f"{filename_stem}.png",
                    "image/png",
                    lambda: render_png(regular_document),
                    attachment_warnings,
                ),
            ] if attachment is not None]
            regular_recipients, ga_recipients = split_ga_recipient_map(recipient_map)
            ga_attachments = None
            ga_html_body = ga_base_html
            if ga_recipients is not None:
                # Finish all data/image generation before the first SMTP send,
                # so a rendering error cannot leave only the regular group sent.
                today_print_png = next(
                    (
                        attachment
                        for attachment in today_print_report.get("attachments", [])
                        if attachment[2] == "image/png"
                    ),
                    None,
                )
                try:
                    ga_only_attachments = await build_ga_only_1h_attachments(
                        db,
                        day,
                        today_print_png=today_print_png,
                    )
                except Exception as exc:
                    attachment_warnings.append(
                        f"GA-only PNG attachments: {type(exc).__name__}: {exc}"
                    )
                    logger.exception("primeflow_report_ga_only_attachments_failed")
                    ga_only_attachments = [today_print_png] if today_print_png is not None else []
                ga_attachments = [attachment for attachment in [
                    _optional_attachment(
                        f"{filename_stem}.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        lambda: render_docx(document),
                        attachment_warnings,
                    ),
                    _optional_attachment(
                        f"{filename_stem}.png",
                        "image/png",
                        lambda: render_png(document),
                        attachment_warnings,
                    ),
                ] if attachment is not None] + ga_only_attachments
                ga_html_body = await render_ga_recipient_email_html(
                    db,
                    document,
                    day,
                    today_print_html=today_print_report["content_html"],
                )
            messages: list[dict] = []
            if any(regular_recipients.values()):
                messages.append(await gmail.send_verified(
                    subject,
                    regular_recipients,
                    regular_body,
                    regular_html_body,
                    attachments=regular_attachments,
                    message_id=f"primeflow-1h-{run.id}-regular@primexeu.com",
                ))
            if ga_recipients is not None:
                assert ga_attachments is not None
                messages.append(await gmail.send_verified(
                    subject,
                    ga_recipients,
                    ga_body,
                    ga_html_body,
                    attachments=ga_attachments,
                    message_id=f"primeflow-1h-{run.id}-ga@primexeu.com",
                ))
            if not messages:
                raise ValueError("At least one recipient is required")
            message = messages[-1]
            run.status = "SENT"
            run.gmail_message_id, run.gmail_thread_id = message.get("id"), message.get("threadId")
            if attachment_warnings:
                run.error_code = "ATTACHMENT_WARNING"
                run.error_message = " | ".join(attachment_warnings)[:2000]
        except ValueError as exc:
            run.status, run.error_code, run.error_message = "FAILED_DATA", type(exc).__name__, str(exc)[:2000]
        except GmailVerificationError as exc:
            run.status, run.error_code, run.error_message = "FAILED_VERIFICATION", type(exc).__name__, str(exc)[:2000]
            run.gmail_message_id = exc.response.get("id")
            run.gmail_thread_id = exc.response.get("threadId")
        except Exception as exc:
            run.status, run.error_code, run.error_message = "FAILED_EMAIL", type(exc).__name__, str(exc)[:2000]
        run.finished_at = datetime.now(report_timezone())
        await db.commit()
        logger.info("primeflow_report_run run_id=%s report_date=%s report_slot=%s final_status=%s", run.id, day, slot, run.status)
        return run


async def execute_chain(
    day: date, slot: str, *, schedule_id=None, schedule_version: int | None = None,
    scheduled_for: datetime | None = None,
) -> list[PrimeFlowReportDeliveryRun]:
    if day.weekday() >= 5:
        return []
    preceding_day, preceding_slot = predecessor(day, slot)
    first = await deliver_report(preceding_day, preceding_slot, trigger_type="BACKFILL")
    second = await deliver_report(
        day, slot, schedule_id=schedule_id, schedule_version=schedule_version,
        scheduled_for=scheduled_for, trigger_type="SCHEDULED",
    )
    return [first, second]
