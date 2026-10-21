from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import date
from typing import TypeVar

from app.celery_app import celery_app
from app.config import settings
from app.db import engine
from app.jobs.carryover import run_carryover as _run_carryover
from app.jobs.ga_notes_cleanup import cleanup_old_closed_ga_notes as _cleanup_old_closed_ga_notes
from app.jobs.internal_notes_cleanup import cleanup_old_done_internal_notes as _cleanup_old_done_internal_notes
from app.jobs.internal_meeting_sessions import (
    reset_expired_internal_meeting_sessions as _reset_expired_internal_meeting_sessions,
)
from app.jobs.overdue import process_overdue as _process_overdue
from app.jobs.realization import (
    capture_daily_realization_baselines as _capture_daily_realization_baselines,
    generate_daily_realization_snapshots as _generate_daily_realization_snapshots,
    generate_weekly_realization_results as _generate_weekly_realization_results,
)
from app.jobs.reminders import process_reminders as _process_reminders
from app.jobs.system_tasks import (
    generate_system_tasks as _generate_system_tasks,
    pregenerate_system_tasks_today as _pregenerate_system_tasks_today,
    reconcile_system_task_slots_daily as _reconcile_system_task_slots_daily,
)
from app.services.weekly_planning_audit_delivery import (
    WeeklyPlanningAuditEmailError,
    cleanup_expired_report_files,
    generate_and_send_scheduled,
)
from app.services.px_jav_weekly_report import deliver_px_jav_weekly_report


T = TypeVar("T")


def _run_async(awaitable: Awaitable[T]) -> T:
    """Run a Celery coroutine without reusing asyncpg connections across loops."""

    async def _run_with_fresh_pool() -> T:
        # Celery's solo worker calls each sync task in the same process, while
        # asyncio.run() creates and closes a new event loop for every call.
        # Any asyncpg connection left in SQLAlchemy's pool belongs to the
        # previous, now-closed loop and cannot safely be reused on Windows.
        await engine.dispose()
        try:
            return await awaitable
        finally:
            await engine.dispose()

    return asyncio.run(_run_with_fresh_pool())


@celery_app.task(name="app.celery_tasks.process_discord_agent_runs")
def process_discord_agent_runs() -> dict[str, int]:
    from app.jobs.discord_agents import process_agent_runs
    return _run_async(process_agent_runs())


@celery_app.task(name="app.celery_tasks.generate_system_tasks")
def generate_system_tasks() -> int:
    return _run_async(_generate_system_tasks())


@celery_app.task(name="app.celery_tasks.pregenerate_system_tasks_today")
def pregenerate_system_tasks_today() -> int:
    return _run_async(_pregenerate_system_tasks_today())


@celery_app.task(name="app.celery_tasks.reconcile_system_task_slots_daily")
def reconcile_system_task_slots_daily() -> dict[str, int]:
    return _run_async(_reconcile_system_task_slots_daily())


@celery_app.task(name="app.celery_tasks.process_reminders")
def process_reminders() -> int:
    return _run_async(_process_reminders())


@celery_app.task(name="app.celery_tasks.process_overdue")
def process_overdue() -> int:
    return _run_async(_process_overdue())


@celery_app.task(name="app.celery_tasks.run_carryover")
def run_carryover() -> dict:
    return _run_async(_run_carryover())


@celery_app.task(name="app.celery_tasks.cleanup_old_closed_ga_notes")
def cleanup_old_closed_ga_notes() -> int:
    return _run_async(_cleanup_old_closed_ga_notes())


@celery_app.task(name="app.celery_tasks.cleanup_old_done_internal_notes")
def cleanup_old_done_internal_notes() -> int:
    return _run_async(_cleanup_old_done_internal_notes())


@celery_app.task(name="app.celery_tasks.reset_expired_internal_meeting_sessions")
def reset_expired_internal_meeting_sessions() -> int:
    return _run_async(_reset_expired_internal_meeting_sessions())


@celery_app.task(name="app.celery_tasks.capture_daily_realization_baselines")
def capture_daily_realization_baselines() -> dict[str, int]:
    return _run_async(_capture_daily_realization_baselines())


@celery_app.task(name="app.celery_tasks.generate_daily_realization_snapshots")
def generate_daily_realization_snapshots() -> dict[str, int]:
    return _run_async(_generate_daily_realization_snapshots())


@celery_app.task(name="app.celery_tasks.generate_weekly_realization_results")
def generate_weekly_realization_results() -> dict[str, int]:
    return _run_async(_generate_weekly_realization_results())


@celery_app.task(
    bind=True,
    name="app.celery_tasks.send_weekly_planning_audit_report",
    max_retries=4,
)
def send_weekly_planning_audit_report(
    self,
    slot: str,
    week_start: str | None = None,
) -> str | None:
    parsed_week_start = date.fromisoformat(week_start) if week_start else None
    try:
        run_id = _run_async(generate_and_send_scheduled(slot, parsed_week_start))
        return str(run_id) if run_id else None
    except WeeklyPlanningAuditEmailError as exc:
        countdown = min(1800, 60 * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=countdown)


@celery_app.task(name="app.celery_tasks.cleanup_weekly_planning_audit_files")
def cleanup_weekly_planning_audit_files() -> int:
    return _run_async(cleanup_expired_report_files())


@celery_app.task(
    bind=True,
    name="app.celery_tasks.send_px_jav_weekly_report",
    max_retries=4,
)
def send_px_jav_weekly_report(self) -> str | None:
    if not settings.PX_JAV_WEEKLY_REPORT_ENABLED:
        return None
    run = _run_async(deliver_px_jav_weekly_report())
    if run.status not in {"SENT", "ALREADY_SENT"}:
        countdown = min(1800, 60 * (2 ** self.request.retries))
        raise self.retry(
            exc=RuntimeError(run.error_message or f"PX JAV delivery failed: {run.status}"),
            countdown=countdown,
        )
    return str(run.id)



@celery_app.task(name="app.celery_tasks.process_discord_voice_meetings")
def process_discord_voice_meetings():
    from app.jobs.discord_voice_meetings import process_voice_meetings
    return _run_async(process_voice_meetings())


@celery_app.task(name="app.celery_tasks.process_mira_memory")
def process_mira_memory():
    from app.jobs.mira_memory import process_mira_memory as process
    return _run_async(process())


@celery_app.task(name="app.celery_tasks.process_recording_analyses")
def process_recording_analyses():
    from app.jobs.recording_analysis import process_recording_analyses as process
    return _run_async(process())
