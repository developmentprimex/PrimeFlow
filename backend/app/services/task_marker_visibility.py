"""Only actionable tasks contribute symbol/comment inbox alerts."""
from sqlalchemy import and_

MARKER_ALERT_STATUSES = ("TODO", "IN_PROGRESS")


def marker_alert_task(task):
    return and_(task.is_active.is_(True), task.status.in_(MARKER_ALERT_STATUSES))


def marker_alert_enabled(task):
    return bool(task.is_active and task.status in MARKER_ALERT_STATUSES)
