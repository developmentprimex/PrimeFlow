"""The three conditional 1H questions, durable answers and Mira history.

Task writes still pass through the existing actor-scoped Discord command API.
The frozen plan survives later date/slot edits; a new slot never inherits all TODOs.
"""
from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
import uuid
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models.discord_assistant import DiscordLink, DiscordReminder
from app.models.user import User
from app.services.discord_task_tools import plain_text

SLOTS = ('10:00', '11:00', '11:50', '14:20', '16:00')
NEXT_QUESTION = 'Me çka ke me vazhdu në slotin tjetër?'


def due_today(due_date, day):
    if not due_date or day is None:
        return False
    try:
        if isinstance(due_date, str) and len(due_date) == 10:
            return date.fromisoformat(due_date) == day
        value = datetime.fromisoformat(due_date.replace('Z', '+00:00')) if isinstance(due_date, str) else due_date
        local = ZoneInfo(settings.APP_TIMEZONE)
        return (value if value.tzinfo else value.replace(tzinfo=local)).astimezone(local).date() == day
    except (ValueError, TypeError, AttributeError):
        return False


def report_day(report):
    value = report.get('created_at')
    return datetime.fromisoformat(value).astimezone(ZoneInfo(settings.APP_TIMEZONE)).date() if value else None


def question(status, title, due_date=None, day=None):
    title = next((line.strip() for line in title.splitlines() if line.strip()), 'detyrën')[:180]
    if status == 'IN_PROGRESS':
        return f'A ke me vazhdu me {title}?' + (' Kur pritet me u kry?' if due_today(due_date, day) else '')
    if status == 'TODO':
        return f'Pse s’ke vazhdu me {title}? Kur vazhdon?'
    return None


def next_options(tasks, slot):
    """Only the owner's active daily plan, deduplicated and ordered for selection."""
    options = {}
    current = SLOTS.index(slot)
    for task in tasks:
        scheduled = task.get('one_h_report_slot')
        status = task.get('status')
        if scheduled not in SLOTS or status not in {'TODO', 'IN_PROGRESS'} or task.get('is_active') is False:
            continue
        rank = SLOTS.index(scheduled)
        group = 'CURRENT' if rank == current and status == 'IN_PROGRESS' else (
            'LATER' if rank > current else 'UNSTARTED' if status == 'TODO' else None)
        if group:
            options[str(task['id'])] = {'id': str(task['id']), 'title': plain_text(task.get('title') or 'Detyrë'),
                                      'slot': scheduled, 'status': status, 'group': group}
    return sorted(options.values(), key=lambda t: ({'CURRENT': 0, 'LATER': 1, 'UNSTARTED': 2}[t['group']], t['slot'], t['title']))


def next_options_key(report):
    return sha256(','.join(f'{t["id"]}:{t["slot"]}:{t["status"]}' for t in report.get('next_options', [])).encode()).hexdigest()[:16]


def snapshot(tasks, at, *, slot='10:00'):
    return {'created_at': at.isoformat(), 'slot': slot, 'next_options': next_options(tasks, slot), 'tasks': [
        {'id': str(t['id']), 'title': plain_text(t.get('title') or 'Detyrë'),
         'planned_status': t['status'], 'status': t['status'], 'available': True,
         'due_date': t.get('due_date'),
         'question': question(t['status'], plain_text(t.get('title') or 'Detyrë'), t.get('due_date'), at.date()),
         'progress_percentage': t.get('progress_percentage'), 'comment': t.get('user_comment'),
         'answer': None, 'expected_at': None, 'skipped': False, 'history': []}
        for t in tasks], 'next': {'answer': None, 'expected_at': None, 'selected_tasks': [], 'selection_kind': None, 'history': []}}


def refresh(report, tasks, *, slot=None):
    result = deepcopy(report)
    result['slot'] = slot or result.get('slot', '10:00')
    result['next_options'] = next_options(tasks, result['slot'])
    current = {str(t['id']): t for t in tasks}
    for entry in result['tasks']:
        task = current.get(entry['id'])
        entry['available'] = task is not None and task.get('is_active') is not False
        if task:
            entry['status'] = task['status']
            entry['due_date'] = task.get('due_date')
    return result


def all_done(report):
    return bool(report['tasks']) and all(t['status'] == 'DONE' for t in report['tasks'])


def report_state(report):
    eligible = [t for t in report['tasks'] if t['available'] and question(t['status'], t['title'])]
    outstanding = [t for t in eligible if not t['answer']]
    needs_next = not report['next']['answer']
    if not outstanding and not needs_next:
        return 'DONE'
    if any(t['answer'] or t['history'] for t in report['tasks']) or report['next']['answer']:
        return 'PARTIAL'
    return 'WAITING'


def presentation(reminder, requested=None):
    report = reminder.one_h_report
    candidates = [{**t, 'question': question(t['status'], t['title'], t.get('due_date'), reminder.day),
                   'asks_completion': due_today(t.get('due_date'), reminder.day)} for t in report['tasks']
                  if t['available'] and question(t['status'], t['title'])]
    next_question = {'id': 'next', 'title': 'Slotin tjetër', 'status': 'DONE', 'question': NEXT_QUESTION, **report['next']}
    selected = next((t for t in candidates if t['id'] == requested), None) if requested else None
    selected = selected or next((t for t in candidates if not t.get('answer') and not t.get('skipped')), None)
    return {'id': str(reminder.id), 'date': reminder.day.isoformat(), 'bucket': reminder.bucket,
            'state': report_state(report), 'tasks': report['tasks'], 'questions': [*candidates, next_question],
            'current': selected, 'next': report['next'], 'next_options': report.get('next_options', []),
            'next_options_key': next_options_key(report)}


def save_answer(report, item_id, text, expected_at, request_id, at, *, skip=False, question_status=None, asks_completion=None):
    result = deepcopy(report)
    item = result['next'] if item_id == 'next' else next((t for t in result['tasks'] if t['id'] == item_id), None)
    if item is None:
        raise HTTPException(404, 'Detyra nuk është pjesë e këtij raportimi.')
    if any(h.get('request_id') == request_id for t in [*result['tasks'], result['next']] for h in t['history']):
        return result
    prompt = NEXT_QUESTION if item_id == 'next' else (
        question(item.get('status'), item.get('title'), item.get('due_date'), report_day(result)) if item.get('available') else None)
    if not prompt:
        raise HTTPException(409, 'Gjendja e detyrave ndryshoi. Rifresko raportimin.')
    if question_status and item_id != 'next' and question_status != item['status']:
        raise HTTPException(409, 'Gjendja e detyrës ndryshoi. Rifresko raportimin.')
    if asks_completion is not None and item_id != 'next' and item['status'] == 'IN_PROGRESS' and asks_completion != due_today(item.get('due_date'), report_day(result)):
        raise HTTPException(409, 'Afati i detyrës ndryshoi. Rifresko raportimin.')
    if not skip and not text.strip():
        raise HTTPException(422, 'Shkruaj përgjigjen.')
    item['skipped'] = skip
    if not skip:
        item['answer'], item['expected_at'] = text.strip(), expected_at.strip() or None
        if item_id == 'next':
            item['selected_tasks'], item['selection_kind'] = [], 'OTHER'
    item['history'].append({'kind': 'SKIP' if skip else 'ANSWER', 'request_id': request_id,
                            'question': prompt, 'answer': text.strip(), 'expected_at': expected_at.strip() or None,
                            'at': at.isoformat()})
    return result


def save_next_choices(report, task_ids, request_id, at, *, page=0, none=False, options_key=None):
    result = deepcopy(report)
    item = result['next']
    if any(h.get('request_id') == request_id for t in [*result['tasks'], item] for h in t['history']):
        return result
    if not none and options_key is not None and options_key != next_options_key(result):
        raise HTTPException(409, 'Lista e detyrave ndryshoi. Rifresko vazhdimin.')
    options = result.get('next_options', [])
    page_ids = {t['id'] for t in options[page * 25:(page + 1) * 25]}
    if not none and (not page_ids or not set(task_ids) <= page_ids):
        raise HTTPException(409, 'Lista e detyrave ndryshoi. Rifresko vazhdimin.')
    keep = {t['id'] for t in item.get('selected_tasks', [])} - page_ids
    chosen = [] if none else [t for t in options if t['id'] in keep | set(task_ids)]
    answer = 'Nuk kam vazhdim të planifikuar.' if none else '\n'.join(t['title'] for t in chosen) or None
    item.update(answer=answer, expected_at=None, selected_tasks=chosen,
                selection_kind='NONE' if none else 'TASKS', skipped=False)
    item['history'].append({'kind': 'ANSWER', 'request_id': request_id, 'question': NEXT_QUESTION,
                            'answer': answer or '', 'selected_tasks': deepcopy(chosen),
                            'selection_kind': item['selection_kind'], 'at': at.isoformat()})
    return result


async def reminder_for(db, reminder_id, link, at, *, lock=False):
    row = await db.get(DiscordReminder, reminder_id, with_for_update=lock, populate_existing=True)
    if not row or row.link_id != link.id or row.bucket not in SLOTS or row.day != at.date():
        raise HTTPException(404, 'Ky raportim nuk është i disponueshëm. Përdor /detyrat.')
    return row


async def capture_action(db, link, action, at):
    """Keep outcomes as outcomes, not as answers or invented successful writes."""
    rows = (await db.execute(select(DiscordReminder).where(
        DiscordReminder.link_id == link.id, DiscordReminder.day == at.date(),
        DiscordReminder.bucket.in_(SLOTS), DiscordReminder.one_h_report.is_not(None),
    ).order_by(DiscordReminder.bucket.desc()).with_for_update())).scalars().all()
    row = next((r for r in rows if any(t['id'] == str(action.task_id) for t in r.one_h_report['tasks'])), None)
    if not row:
        return
    report = deepcopy(row.one_h_report)
    item = next((t for t in report['tasks'] if t['id'] == str(action.task_id)), None)
    if not item or any(h.get('request_id') == action.id for h in item['history']):
        return
    result = action.result or {}
    reply = result.get('reply', {})
    after = reply.get('task')
    if after:
        item['status'] = after['status']
        item['comment'] = after.get('user_comment')
        item['progress_percentage'] = after.get('progress_percentage')
    item['history'].append({'kind': 'ACTION', 'request_id': action.id, 'at': at.isoformat(),
                            'instruction': action.instruction, 'status': action.status,
                            'message': reply.get('message'),
                            'operations': result.get('operations', [])})
    row.one_h_report = report


def slot_id(day, slot):
    return uuid.uuid5(uuid.NAMESPACE_URL, f'primeflow:discord-1h:{day}:{slot}')


async def slot_groups(db):
    rows = (await db.execute(select(DiscordReminder.day, DiscordReminder.bucket).join(
        DiscordLink, DiscordLink.id == DiscordReminder.link_id).where(
        DiscordReminder.one_h_report.is_not(None), DiscordReminder.bucket.in_(SLOTS),
        DiscordLink.guild_id == settings.DISCORD_GUILD_ID,
    ).distinct().order_by(DiscordReminder.day.desc(), DiscordReminder.bucket.desc()))).all()
    return [(day, slot) for day, slot in rows]


async def reports_for(db, day, slot):
    from app.models.discord_m2_postponement import DiscordM2Postponement
    from app.services.discord_m2_postponements import STATUS_LABELS
    rows = (await db.execute(select(DiscordReminder, User.full_name, User.id).join(
        DiscordLink, DiscordLink.id == DiscordReminder.link_id).join(User, User.id == DiscordLink.user_id).where(
        DiscordReminder.day == day, DiscordReminder.bucket == slot,
        DiscordReminder.one_h_report.is_not(None), DiscordLink.guild_id == settings.DISCORD_GUILD_ID,
    ).order_by(User.full_name))).all()
    results = [{'id': str(row.id), 'user_id': str(uid), 'name': name,
             'state': report_state(row.one_h_report), 'sent_at': row.sent_at.isoformat() if row.sent_at else None,
             **deepcopy(row.one_h_report)} for row, name, uid in rows]
    links = {str(row.id): row.link_id for row, _, _ in rows}
    requests = (await db.execute(select(DiscordM2Postponement).where(
        DiscordM2Postponement.day == day, DiscordM2Postponement.requester_link_id.in_(list(links.values())),
    ).order_by(DiscordM2Postponement.created_at))).scalars().all() if links else []
    for report in results:
        for item in report['tasks']:
            item['postponements'] = [{'id': str(r.id), 'status': r.status, 'label': STATUS_LABELS[r.status],
                'comment': r.comment, 'proposed_dates': r.proposed_dates, 'at': r.created_at.isoformat()}
                for r in requests if r.requester_link_id == links[report['id']] and str(r.task_id) == item['id']]
    return results


def virtual_meeting(day, slot):
    return {'id': str(slot_id(day, slot)), 'date': day.isoformat(), 'slot': slot, 'status': 'DISCORD_REPORT',
            'started_at': None, 'staff_started_at': None, 'ended_at': None, 'duration_minutes': None,
            'summary_status': None, 'has_summary': False, 'error': None, 'people': []}
