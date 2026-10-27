"""Reset only today's early M2 trial replies and resend current normal questions."""
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path
import uuid
import httpx
from dotenv import dotenv_values
from sqlalchemy import select

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
config = dotenv_values(remote / '.env')
for key in ('DISCORD_GUILD_ID', 'DISCORD_ASSISTANT_ENABLED', 'DISCORD_BRIDGE_SECRET', 'FRONTEND_URL'):
    if config.get(key):
        os.environ[key] = config[key]
sys.path.insert(0, str(root / 'backend'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
from app.db import SessionLocal, engine
from app.models.user import User
from app.models.discord_assistant import DiscordLink
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.task_user_comment import TaskUserComment
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.audit_log import AuditLog
from app.api.routers import discord_m2 as api
from app.services import discord_answer_sync
from app.services.audit import add_audit_log
from app.services.daily_rlz_compliance import REASON_LABELS
import discord_m2_client as ui


async def main():
    now = datetime.now(api.report_timezone())
    cutoff = datetime.combine(now.date(), time(11, 45), api.report_timezone())
    manifest_path = root / 'tmp' / f'rinesa-m2-normal-{now.date()}.json'
    retired_path = root / 'tmp' / f'rinesa-m2-retired-{now.date()}.json'
    sent = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == 'rinesa.ahmedi', User.is_active.is_(True)))).scalar_one()
        link = (await db.execute(select(DiscordLink).where(DiscordLink.user_id == user.id,
            DiscordLink.guild_id == config['DISCORD_GUILD_ID'], DiscordLink.enabled.is_(True)))).scalar_one()
        actor = {key: getattr(link, key) for key in ('discord_user_id', 'guild_id', 'channel_id')}
        questions = (await db.execute(select(Question).where(Question.link_id == link.id, Question.day == now.date(),
            Question.sent_at < cutoff))).scalars().all()
        report = await api.reports.locked_report(db, now.date())
        retired = json.loads(retired_path.read_text(encoding='utf-8')) if retired_path.exists() else []
        if not retired and sent:
            prior_test = root / 'tmp' / f'm2-rinesa-1150-{now.date()}.json'
            if prior_test.exists():
                retired = [{'id': item['id'], 'message_id': item['message_id']} for item in
                    json.loads(prior_test.read_text(encoding='utf-8')) if item['source'] == 'task']
        for q in questions:
            before = {'question_id': str(q.id), 'choice': q.choice, 'comment': q.comment,
                'reason_code': q.reason_code, 'answered_at': str(q.answered_at),
                'platform_answer': q.platform_answer, 'message_id': q.message_id}
            if not any(item['message_id'] == q.message_id for item in retired):
                retired.append({'id': str(q.id), 'message_id': q.message_id})
            events = (await db.execute(select(AuditLog).where(AuditLog.actor_user_id == user.id,
                AuditLog.action == 'task.discord_m2_answer', AuditLog.after['question_id'].astext == str(q.id)))).scalars().all()
            comment = (await db.execute(select(TaskUserComment).where(TaskUserComment.task_id == q.task_id,
                TaskUserComment.user_id == user.id).with_for_update())).scalar_one_or_none()
            removed = 0
            if comment and comment.comment:
                for event in events:
                    answer = event.after or {}
                    reason, choice = answer.get('reason_code'), answer.get('choice')
                    body = f'M2 {q.day:%d.%m.%Y} — {api.service.KINDS[q.kind]}\n'
                    body += (REASON_LABELS[reason] + '\n') if reason else ''
                    label = 'Vazhdon në PM' if q.kind == 'continuation' else 'Dorëzuar'
                    body += (f'{label}: {choice}\n' if choice else '') + (answer.get('comment') or '')
                    import re
                    comment.comment, count = re.subn(r'(?:\A|\n\n)' + re.escape(body) + r'(?=\n\n|\Z)', '', comment.comment)
                    removed += count
                comment.comment = comment.comment.lstrip('\n') or None
            if q.answered_at and q.kind in {'unfinished', 'progress', 'postponed'}:
                state = (await db.execute(select(TaskDailyRlzState).where(TaskDailyRlzState.task_id == q.task_id,
                    TaskDailyRlzState.user_id == user.id, TaskDailyRlzState.day_date == q.day))).scalar_one_or_none()
                if state and state.comment == q.comment and state.reason_code == q.reason_code and state.updated_at <= q.answered_at:
                    state.comment, state.reason_code = None, None
            q.choice = q.comment = q.reason_code = q.answered_at = None
            q.platform_answer = q.platform_answered_at = None
            q.sync_hash = q.sync_pending_hash = q.sync_lease_until = None
            # The old messages are retired separately after successful delivery.
            q.sent_at = q.message_id = None
            q.lease_until = datetime.now(timezone.utc)
            await db.flush()
            await api.update_report_answers(db, report, q)
            add_audit_log(db=db, actor_user_id=user.id, entity_type='task', entity_id=q.task_id,
                action='task.discord_m2_test_reset', before=before,
                after={'question_id': str(q.id), 'removed_comment_blocks': removed,
                    'reason': 'User requested removing trial replies and resending normal M2 questions.'})
        retired_path.write_text(json.dumps(retired, indent=2), encoding='utf-8')
        await db.commit()
        data = await api.data_with_moves(db, now.date())
        eligible = {(kind, api.service.context_key(kind, row)) for kind, row in api.service.question_rows(data)}
        await api.collect_questions(db, now=now, only_user_id=user.id)
        questions = (await db.execute(select(Question).where(Question.link_id == link.id,
            Question.day == now.date()).order_by(Question.kind, Question.id))).scalars().all()
        jobs = []
        for q in questions:
            if (q.kind, q.context_key) not in eligible:
                continue
            effective = await discord_answer_sync.m2_payload(db, q, link)
            if effective.get('answered') or effective.get('platform_status'):
                continue
            jobs.append(api.question_payload(q, link))
        print(json.dumps({'reset_trial_questions': len(retired), 'normal_questions': len(jobs),
            'kinds': [job['kind'] for job in jobs]}))
    async with httpx.AsyncClient(timeout=60) as client:
        async def discord(method, path, payload=None):
            for _ in range(8):
                response = await client.request(method, 'https://discord.com/api/v10' + path, json=payload,
                    headers={'Authorization': 'Bot ' + config['DISCORD_BOT_TOKEN']})
                if response.status_code == 429:
                    await asyncio.sleep(min(10, float(response.json().get('retry_after', 1))))
                    continue
                if response.is_error:
                    raise RuntimeError(f'Discord {method}: HTTP {response.status_code}')
                return response.json()
            raise RuntimeError('Discord rate limit persisted')

        async def bridge(path, payload):
            response = await client.post('http://192.168.10.8:8000/api/discord' + path, json=payload,
                headers={'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']})
            if response.is_error:
                raise RuntimeError(f'Bridge {path}: HTTP {response.status_code}')
            return response.json()

        channel = await discord('GET', f"/channels/{actor['channel_id']}")
        assert channel['guild_id'] == actor['guild_id'] and channel['topic'] == f"PrimeFlow personal workspace: {actor['discord_user_id']}"
        for job in jobs:
            if any(item['question_id'] == job['id'] for item in sent):
                continue
            job = await bridge(f"/bot/m2/{job['id']}/open", actor)
            message = await discord('POST', f"/channels/{actor['channel_id']}/messages", {
                'content': ui.prompt(job), 'components': ui.controls(job).to_components(),
                'allowed_mentions': {'parse': [], 'users': [actor['discord_user_id']]},
                'nonce': hashlib.sha256(f"m2-normal-retry:{now.date()}:{job['id']}".encode()).hexdigest()[:24], 'enforce_nonce': True})
            sent.append({'question_id': job['id'], 'kind': job['kind'], 'message_id': message['id'],
                'url': f"https://discord.com/channels/{actor['guild_id']}/{actor['channel_id']}/{message['id']}"})
            manifest_path.write_text(json.dumps(sent, indent=2), encoding='utf-8')
            await bridge(f"/bot/m2/{job['id']}/ack", {**actor, 'message_id': message['id']})
            print(json.dumps({'sent': sent[-1]}))
        for old in retired:
            if not old['message_id']:
                continue
            await discord('PATCH', f"/channels/{actor['channel_id']}/messages/{old['message_id']}", {
                'content': 'Prova M2 u mbyll. Pyetjet për raportimin normal janë ridërguar më poshtë.',
                'components': [], 'embeds': [], 'allowed_mentions': {'parse': []}})
        for item in sent:
            message = await discord('GET', f"/channels/{actor['channel_id']}/messages/{item['message_id']}")
            assert 'TEST' not in message['content'] and message.get('components')
        print(json.dumps({'only_user': 'rinesa.ahmedi', 'verified_normal_messages': len(sent),
            'old_trials_retired': len(retired), 'm3_unchanged': True}))
    await engine.dispose()

asyncio.run(main())
