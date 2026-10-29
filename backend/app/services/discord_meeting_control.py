"""Team controls are scoped to one configured text channel and two fixed voices."""
from fastapi import HTTPException
from sqlalchemy import select
from app.config import settings
from app.models.audit_log import AuditLog
from app.models.discord_assistant import DiscordLink
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.models.user import User


def is_control(actor):
    return bool(settings.DISCORD_MEETING_CONTROL_CHANNEL_ID and
                actor.channel_id == settings.DISCORD_MEETING_CONTROL_CHANNEL_ID)


def validate_scope(actor):
    if not is_control(actor) or actor.guild_id != settings.DISCORD_GUILD_ID:
        raise HTTPException(403, 'Përdor kanalin mira-kontrolli të PrimeFlow.')


def voice_id(recorder):
    if recorder not in ('primary', 'ai_agent'):
        raise HTTPException(422, 'Regjistrues i panjohur.')
    value = settings.DISCORD_1H_VOICE_CHANNEL_ID if recorder == 'primary' else settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID
    if not value:
        raise HTTPException(503, 'Kanali zanor nuk është konfiguruar.')
    return value


def validate_voice(recorder, channel_id):
    if channel_id != voice_id(recorder):
        raise HTTPException(403, 'Paneli kontrollon vetëm kanalin e vet zanor.')


async def control_identity(db, actor):
    validate_scope(actor)
    link = (await db.execute(select(DiscordLink).where(
        DiscordLink.discord_user_id == actor.discord_user_id, DiscordLink.guild_id == actor.guild_id,
        DiscordLink.enabled.is_(True)))).scalar_one_or_none()
    if not link:
        raise HTTPException(403, 'Lidhe llogarinë me PrimeFlow për ta përdorur panelin.')
    user = await db.get(User, link.user_id, populate_existing=True)
    if not user or not user.is_active:
        raise HTTPException(403, 'Llogaria PrimeFlow nuk është aktive.')
    return link, user


async def authorize_shared_session(db, actor, session_id, *, operation):
    from app.services.discord_voice_meetings import locked
    _, user = await control_identity(db, actor)
    row = await locked(db, session_id)
    validate_voice(row.recorder, row.voice_channel_id)
    if row.guild_id != actor.guild_id or (row.private_channel_id != actor.channel_id and operation != 'stop'):
        raise HTTPException(403, 'Ky takim nuk i përket panelit të përbashkët.')
    return row, user


def audit(db, row, user, actor, action):
    db.add(AuditLog(actor_user_id=user.id, entity_type='discord_voice_meeting', entity_id=row.id,
        action='CONTROL_' + action, after={'discord_user_id': actor.discord_user_id,
        'channel_id': actor.channel_id, 'recorder': row.recorder, 'voice_channel_id': row.voice_channel_id}))


async def panel_state(db, scope, recorder):
    from app.services.discord_voice_meetings import view
    validate_scope(scope)
    channel = voice_id(recorder)
    base = select(Meeting).where(Meeting.guild_id == scope.guild_id, Meeting.recorder == recorder,
        Meeting.voice_channel_id == channel)
    active = (await db.execute(base.where(Meeting.status.in_(['STARTING','LISTENING','FINALIZING']))
        .order_by(Meeting.created_at.desc()).limit(1))).scalar_one_or_none()
    row = active or (await db.execute(base.where(Meeting.private_channel_id == scope.channel_id)
        .order_by(Meeting.created_at.desc()).limit(1))).scalar_one_or_none()
    if not row:
        return {'meeting': None, 'voice_channel_id': channel, 'activity': []}
    # A personal session can be stopped here, but its private notes are never exposed.
    result = view(row) if row.private_channel_id == scope.channel_id else {
        'id': str(row.id), 'status': row.status, 'title': row.title, 'private': True}
    events = (await db.execute(select(AuditLog).where(AuditLog.entity_type == 'discord_voice_meeting',
        AuditLog.entity_id == row.id, AuditLog.action.in_(['CONTROL_START','CONTROL_STOP','CONTROL_SAVE']))
        .order_by(AuditLog.created_at))).scalars().all()
    return {'meeting': result, 'voice_channel_id': channel,
        'activity': [{'action': event.action, 'discord_user_id': event.after['discord_user_id']} for event in events]}
