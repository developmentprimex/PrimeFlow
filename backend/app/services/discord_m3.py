"""M3 timing and deterministic tomorrow/slot selectors shared by bot and API."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time
from app.services.one_h_slots import _next_working_day
from app.services.primeflow_report import report_timezone
from app.services.m3_reporting_points import semantic_local_day

SLOTS = ('10:00', '11:00', '11:50', '14:20', '16:00')
KINDS = {'untouched': 'Pse nuk ka progres?', 'delivery': 'Dorëzimi M3',
         'meeting': 'A u mbajt takimi?', 'tomorrow': 'Plani për nesër',
         'tomorrow_task': 'A punohet nesër?', 'slot': 'Sloti 1H për nesër'}


def collection_phase(now: datetime) -> str | None:
    local = now.astimezone(report_timezone())
    clock = local.time().replace(tzinfo=None)
    if local.weekday() >= 5:
        return None
    if time(15, 50) <= clock < time(16, 10):
        return 'm3'
    if time(16, 10) <= clock < time(17):
        return 'tomorrow'
    return None


def regular_delivery_at(day, phase):
    return datetime.combine(day, time(15, 50) if phase == 'm3' else time(16, 10), report_timezone())


def sent_in_regular_window(question, phase):
    return bool(question.sent_at and question.sent_at >= regular_delivery_at(question.day, phase))


def delivery_is_pending(question, now, phase):
    if question.answered_at or sent_in_regular_window(question, phase):
        return False
    # An operator's earlier simulation uses the same durable question but
    # must not consume the scheduled notification or keep its future lease.
    if question.sent_at:
        return True
    return question.lease_until <= now


def context_key(kind: str, row: dict) -> str:
    # A changed plan or slot conflict gets a fresh question; polling an unchanged
    # plan never repeats it. Individual task replies remain bound to that task.
    value = row if kind == 'slot' else {key: row.get(key) for key in ('task_id', 'meeting_id')}
    if kind == 'tomorrow':
        # Work confirmation survives independent slot edits and list reordering.
        value = sorted([{key: task.get(key) for key in ('task_id', 'title', 'status', 'start_date', 'due_date', 'deadline_important')}
            for task in row.get('tasks', [])], key=lambda task: task['task_id'])
    return hashlib.sha256(json.dumps([kind, value], sort_keys=True, default=str).encode()).hexdigest()


def tomorrow_rows(tasks, target: date, overrides: dict) -> list[dict]:
    from app.api.routers.common_view import _get_task_dates
    rows = []
    for task in tasks:
        if not task.is_active or str(task.status) in {'DONE', 'CANCELED', 'CANCELLED'} or task.completed_at:
            continue
        if target not in _get_task_dates(task, str(task.phase) in {'CHECK', 'CONTROL'}, target):
            continue
        start, due = semantic_local_day(task.start_date), semantic_local_day(task.due_date)
        system = bool(task.system_template_origin_id or task.system_task_slot_id)
        # Explicit groups identify copies of the same work; titles alone do not.
        group = str(task.fast_task_group_id or task.id)
        if system and task.system_template_origin_id:
            group = f'system:{task.system_template_origin_id}:{semantic_local_day(task.origin_run_at) or start}'
        rows.append({'task_id': str(task.id), 'title': task.title, 'status': str(task.status),
            'start_date': start.isoformat() if start else None, 'due_date': due.isoformat() if due else None,
            'due_tomorrow': due == target, 'deadline_important': bool(task.is_deadline_important),
            'is_system_task': system, 'is_1h': bool(task.is_1h_report or task.is_r1),
            'slot': overrides.get(task.id, task.one_h_report_slot), 'group': group})
    return sorted(rows, key=lambda row: (not row['due_tomorrow'], row['slot'] or '', row['title'], row['task_id']))


def slot_questions(rows: list[dict], owners: dict, names: dict) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        if row['is_1h']:
            groups[row['group']].append(row)
    result = []
    for group in groups.values():
        slots = {row['slot'] for row in group if row['slot'] in SLOTS}
        for row in group:
            if row['slot'] in SLOTS and len(slots) <= 1 and all(item['slot'] in SLOTS for item in group):
                continue
            peers = [{'task_id': item['task_id'], 'slot': item['slot'],
                      'people': ', '.join(names.get(uid) or '?' for uid in sorted(owners.get(item['task_id'], set()), key=str))}
                     for item in group if item['task_id'] != row['task_id']]
            result.append({**row, 'peers': peers, 'missing_slot': row['slot'] not in SLOTS})
    return result


def target_day(day: date) -> date:
    return _next_working_day(day)
