from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab

from app.config import settings


def _realization_now() -> datetime:
    """Return the realization-local time without an unpickleable lambda."""
    return datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE))


celery_app = Celery(
    "primex_nexus",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.celery_tasks"],
)

celery_app.conf.enable_utc = True
celery_app.conf.timezone = settings.WEEKLY_PLANNING_AUDIT_TIMEZONE
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

celery_app.conf.beat_schedule = {
    "process-discord-voice-meetings": {"task": "app.celery_tasks.process_discord_voice_meetings", "schedule": 30.0},
    "process-discord-agent-runs": {
        "task": "app.celery_tasks.process_discord_agent_runs",
        "schedule": 30.0,
    },
    "capture-daily-realization-baselines": {
        "task": "app.celery_tasks.capture_daily_realization_baselines",
        "schedule": crontab(
            day_of_week="mon-fri",
            hour=settings.REALIZATION_BASELINE_HOUR,
            minute=settings.REALIZATION_BASELINE_MINUTE,
            nowfun=_realization_now,
        ),
    },
    "process-reminders": {
        "task": "app.celery_tasks.process_reminders",
        "schedule": crontab(minute="*/5"),
    },
    "process-overdue": {
        "task": "app.celery_tasks.process_overdue",
        "schedule": crontab(minute="*/30"),
    },
    "run-carryover": {
        "task": "app.celery_tasks.run_carryover",
        "schedule": crontab(minute=5, hour=0),
    },
    "cleanup-old-closed-ga-notes": {
        "task": "app.celery_tasks.cleanup_old_closed_ga_notes",
        "schedule": crontab(minute=0, hour=2),  # Run daily at 2 AM UTC
    },
    "cleanup-old-done-internal-notes": {
        "task": "app.celery_tasks.cleanup_old_done_internal_notes",
        "schedule": crontab(minute=30, hour=2),  # Run daily at 2:30 AM UTC
    },
    "reset-expired-internal-meeting-sessions": {
        "task": "app.celery_tasks.reset_expired_internal_meeting_sessions",
        "schedule": crontab(minute="*/15"),
    },
    "generate-daily-realization-snapshots": {
        "task": "app.celery_tasks.generate_daily_realization_snapshots",
        "schedule": crontab(
            day_of_week="mon-fri",
            hour=settings.REALIZATION_DAILY_HOUR,
            minute=settings.REALIZATION_DAILY_MINUTE,
        ),
    },
    "generate-weekly-realization-results": {
        "task": "app.celery_tasks.generate_weekly_realization_results",
        "schedule": crontab(day_of_week="fri", hour=17, minute=25),
    },
    "weekly-planning-audit-1030": {
        "task": "app.celery_tasks.send_weekly_planning_audit_report",
        "schedule": crontab(day_of_week="fri", hour=10, minute=30),
        "args": ("10:30",),
    },
    "weekly-planning-audit-cleanup": {
        "task": "app.celery_tasks.cleanup_weekly_planning_audit_files",
        "schedule": crontab(day_of_week="sun", hour=3, minute=15),
    },
    "px-jav-weekly-report-thursday-1550": {
        "task": "app.celery_tasks.send_px_jav_weekly_report",
        "schedule": crontab(day_of_week="thu", hour=15, minute=50),
    },
}

