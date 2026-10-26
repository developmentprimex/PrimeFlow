"""Validation and snapshots for reviewer-gated M2 date changes."""
from datetime import datetime, timezone
from fastapi import HTTPException
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.primeflow_report import report_timezone

APPROVER_USERNAME = 'diellza.veliu'
FIELDS = {'start': ('start_date',), 'due': ('due_date',), 'start_due': ('start_date', 'due_date')}
STATUS_LABELS = {'PENDING': 'Në pritje të Diellzës', 'APPROVED': 'Shtyrja u konfirmua',
                 'REJECTED': 'Shtyrja u refuzua — datat nuk ndryshuan', 'STALE': 'Kërkesa u vjetrua — datat nuk ndryshuan'}


def iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def proposed_dates(task, change_kind, values, reason_code, comment):
    if reason_code not in REASON_LABELS or not comment.strip():
        raise HTTPException(422, 'Zgjidh arsyen dhe plotëso komentin.')
    if change_kind not in FIELDS or set(values) != set(FIELDS[change_kind]):
        raise HTTPException(422, 'Zgjidh vetëm Start, vetëm Due, ose Start dhe Due.')
    result = {}
    for field in FIELDS[change_kind]:
        old = getattr(task, field)
        new = values[field]
        if old is None or new is None or new.tzinfo is None:
            raise HTTPException(422, 'Data aktuale dhe data e re duhet të jenë të vlefshme.')
        if new.astimezone(report_timezone()).date() <= old.astimezone(report_timezone()).date():
            raise HTTPException(422, 'Shtyrja duhet të jetë në një ditë pas datës aktuale.')
        result[field] = iso(new)
    start = result.get('start_date', iso(task.start_date))
    due = result.get('due_date', iso(task.due_date))
    if start and due and datetime.fromisoformat(start) > datetime.fromisoformat(due):
        raise HTTPException(422, 'Start nuk mund të jetë pas Due. Shtyji të dyja nëse është e nevojshme.')
    return result


def assert_snapshot_unchanged(original, current):
    before = {row['id']: row for row in original}
    after = {row['id']: row for row in current}
    if before.keys() != after.keys() or any(
        any(before[key].get(field) != after[key].get(field) for field in ('start_date', 'due_date', 'owners'))
        or not after[key]['active'] or after[key]['status'] == 'DONE' for key in before
    ):
        raise HTTPException(409, {'code': 'M2_POSTPONEMENT_STALE', 'message': 'Datat, përgjegjësit ose gjendja kanë ndryshuar. Kërko një shtyrje të re.'})
