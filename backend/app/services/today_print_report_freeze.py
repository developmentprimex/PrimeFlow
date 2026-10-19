"""The daily 16:00 archive for 1H SHTYPI Today, independent of email delivery.

Read the source in one PostgreSQL snapshot during the last second before 16:00.
Rendering can finish later: neither HTML nor attachments query live data again.
Never backfill a missed cutoff with the current (post-cutoff) state.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from fastapi import Request, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.enums import UserRole
from app.models.one_h_print_report_snapshot import OneHPrintReportSnapshot
from app.services.one_h_print_report_snapshot import get_one_h_print_snapshot, serialize_one_h_print_snapshot
from app.services.primeflow_report import previous_working_day, report_timezone
from app.services.tomorrow_print_report import build_today_print_report, next_working_day
from app.services.today_print_strikes import payload_task_ids, report_task_ids, task_strike_summary, with_report_strikes

logger = logging.getLogger(__name__)
FROZEN_KIND = "TODAY_FROZEN"
FREEZE_TIME = time(16)
CAPTURE_TIME = time(15, 59, 59)
PREPARE_TIME = time(15, 59, 55)


class TodayPrintFreezeMissing(ValueError):
    pass


def local_now(now: datetime | None = None) -> datetime:
    now = now or datetime.now(report_timezone())
    return now.astimezone(report_timezone()) if now.tzinfo else now.replace(tzinfo=report_timezone())


def freeze_at(day: date) -> datetime:
    return datetime.combine(day, FREEZE_TIME, report_timezone())


def is_closed(day: date, now: datetime | None = None) -> bool:
    return local_now(now) >= freeze_at(day)


def view_metadata(day: date, now: datetime | None = None) -> dict:
    current = local_now(now)
    return {
        "server_now": current.isoformat(),
        "freeze_at": freeze_at(day).isoformat(),
        "is_frozen": is_closed(day, current),
        "next_day_at": datetime.combine(current.date() + timedelta(days=1), time(), report_timezone()).isoformat(),
    }


def pack_report(report: dict) -> dict:
    """Keep the exact email artifacts in JSONB without returning them in previews."""
    stored = {key: value for key, value in report.items() if key != "attachments"}
    stored["frozen_attachments"] = [
        {"filename": name, "content": base64.b64encode(content).decode("ascii"), "mime_type": mime}
        for name, content, mime in report.get("attachments", [])
    ]
    return stored


async def frozen_report(db: AsyncSession, day: date, *, include_attachment: bool = False) -> dict:
    row = await get_one_h_print_snapshot(db, FROZEN_KIND, day)
    if row is None:
        raise TodayPrintFreezeMissing(
            "Kopja e ngrirë në 16:00 nuk është ende në dispozicion për këtë datë. "
            "Raporti nuk rindërtohet me ndryshimet pas 16:00."
        )
    if (row.report_payload or {}).get("freeze_source"):
        row = await _finish_frozen_report(db, day)
    result = await serialize_one_h_print_snapshot(db, row)
    artifacts = result.pop("frozen_attachments", [])
    if include_attachment:
        result["attachments"] = [
            (item["filename"], base64.b64decode(item["content"]), item["mime_type"])
            for item in artifacts
        ]
    return {**result, **view_metadata(day), "is_frozen": True}


async def today_report(db: AsyncSession, day: date, *, include_attachment: bool = False) -> dict:
    if is_closed(day):
        return await frozen_report(db, day, include_attachment=include_attachment)
    if day != local_now().date():
        raise ValueError("1H SHTYPI Today mund të gjenerohet vetëm për datën e sotme.")
    report = await build_today_print_report(day, include_attachment=include_attachment)
    report = await with_report_strikes(db, report, day)
    # An in-flight request must not leak fresh data once the cutoff has passed.
    if is_closed(day):
        return await frozen_report(db, day, include_attachment=include_attachment)
    return {**report, **view_metadata(day)}


async def _source_payload(db: AsyncSession, day: date) -> dict:
    # Use the same all-department Common View as the existing remote client,
    # with caching disabled and no slot freezing. All queries share the same MVCC snapshot.
    from app.api.routers.common_view import get_common_view

    response = await get_common_view(
        request=Request({"type": "http", "headers": [(b"cache-control", b"no-store")]}),
        response=Response(), week_start=day, include=None, department_id=None,
        include_all_departments=True, freeze_one_h_slots=False, max_items_per_bucket=5000,
        debug=0, db=db, user=SimpleNamespace(role=UserRole.ADMIN),
    )
    payload = response.model_dump(mode="json")
    if any((payload.get("guardrails", {}).get("truncated") or {}).values()):
        raise ValueError("Common View contains truncated buckets")
    return payload


async def _finish_frozen_report(db: AsyncSession, day: date) -> OneHPrintReportSnapshot:
    """Finish/recover exports solely from the durably captured source, even after a restart."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                     {"key": f"today_print_freeze_render|{day.isoformat()}"})
    row = await get_one_h_print_snapshot(db, FROZEN_KIND, day)
    await db.refresh(row)
    stored = row.report_payload or {}
    source = stored.get("freeze_source")
    if source:
        def render() -> dict:
            return asyncio.run(build_today_print_report(
                day, include_attachment=True, payload=source["payload"],
                next_day_payload=source["next_day_payload"],
            ))

        report = await asyncio.to_thread(render)
        if "one_h_strikes" in source["payload"]:
            summary = source["payload"]["one_h_strikes"]
            shown_ids = {str(task_id) for task_id in report_task_ids(report)}
            report["one_h_strikes"] = {**summary, "tasks": {
                task_id: counts for task_id, counts in summary.get("tasks", {}).items() if task_id in shown_ids
            }}
        row.report_payload = {**pack_report(report), "is_frozen": True,
                              "frozen_at": stored["frozen_at"],
                              "source_captured_at": stored["source_captured_at"]}
        await db.commit()
    return row


async def capture_today_print_report(now: datetime | None = None) -> bool:
    current = local_now(now)
    day = current.date()
    boundary = freeze_at(day)
    if not boundary - timedelta(seconds=5) <= current < boundary:
        return False
    async with SessionLocal() as db:
        # Establish a repeatable read before the cutoff. Advisory locking makes
        # captures from multiple API workers idempotent, including the absent-row case.
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        delay = (datetime.combine(day, CAPTURE_TIME, report_timezone()) - local_now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        acquired = (await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                                    {"key": f"today_print_freeze|{day.isoformat()}"})).scalar()
        if not acquired:
            return False
        captured_at = local_now()
        if captured_at >= boundary:
            return False
        if await get_one_h_print_snapshot(db, FROZEN_KIND, day) is not None:
            return False
        payload = await _source_payload(db, day)
        if day.weekday() == 0:
            previous = await _source_payload(db, previous_working_day(day))
            for bucket, values in (previous.get("items") or {}).items():
                payload.setdefault("items", {}).setdefault(bucket, []).extend(values)
        # Friday's next-day meetings also come from the same frozen transaction.
        next_day = next_working_day(day)
        next_payload = await _source_payload(db, next_day) if next_day > date.fromisoformat(payload["week_end"]) else payload
        # Capture strike evidence in the same pre-16:00 transaction. Rendering
        # and historical reads must never query newer task or event state.
        payload["one_h_strikes"] = await task_strike_summary(
            db, day, payload_task_ids(payload), now=captured_at, completed_through=boundary,
        )

        stored = {"target_date": day.isoformat(), "is_frozen": True,
                  "frozen_at": boundary.isoformat(), "source_captured_at": captured_at.isoformat(),
                  "freeze_source": {"payload": payload, "next_day_payload": next_payload}}
        db.add(OneHPrintReportSnapshot(report_kind=FROZEN_KIND, report_date=day, target_date=day,
                                     report_payload=stored, generated_by_user_id=None))
        # Commit the data before expensive exports. If rendering fails, later
        # requests can recover from this source without querying current task state.
        await db.commit()
        await _finish_frozen_report(db, day)
        logger.info("today_print_report_frozen day=%s source_captured_at=%s", day, captured_at.isoformat())
        return True


async def run_today_print_report_freeze_scheduler_forever() -> None:
    while True:
        try:
            await capture_today_print_report()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("today_print_report_freeze_failed")
        now = local_now()
        capture = datetime.combine(now.date(), PREPARE_TIME, report_timezone())
        if now >= freeze_at(now.date()):
            capture += timedelta(days=1)
        # Wake precisely for the final pre-cutoff second, not at a 30-second polling offset.
        await asyncio.sleep(min(60, max(0.05, (capture - now).total_seconds())))


async def frozen_history(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(OneHPrintReportSnapshot).where(
        OneHPrintReportSnapshot.report_kind == FROZEN_KIND,
    ).order_by(OneHPrintReportSnapshot.report_date.desc()).limit(50))).scalars().all()
    return [{"report_date": row.report_date.isoformat(),
             "frozen_at": (row.report_payload or {}).get("frozen_at"),
             "source_captured_at": (row.report_payload or {}).get("source_captured_at")} for row in rows]
