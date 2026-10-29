"""Group note listings without changing Mira Host's meeting logic."""
import re
import uuid
from sqlalchemy import select
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting
from app.services import mira_host


def note_group(note, voice_channel_id=None):
    if note.get('source') == '1H' or note.get('kind') == '1H':
        return '1H'
    if note.get('source') == 'DESKTOP':
        return 'OTHER'
    if voice_channel_id and settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID and voice_channel_id == settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID:
        return 'AI_AGENT'
    if voice_channel_id and settings.DISCORD_1H_VOICE_CHANNEL_ID and voice_channel_id == settings.DISCORD_1H_VOICE_CHANNEL_ID:
        return '1H'
    title = note.get('title', '').strip()
    if re.match(r'^AI[\s_-]*AGENT\b', title, re.I):
        return 'AI_AGENT'
    if re.match(r'^1H\b', title, re.I):
        return '1H'
    return 'OTHER'


async def grouped_notes(db, limit, offset=0):
    notes = await mira_host.mira_notes(db, limit, offset)
    ids = {uuid.UUID(note['note_id']) for note in notes if note.get('note_id') and note.get('source') == 'DISCORD'}
    channels = dict((str(note_id), channel_id) for note_id, channel_id in (await db.execute(
        select(DiscordVoiceMeeting.saved_note_id, DiscordVoiceMeeting.voice_channel_id)
        .where(DiscordVoiceMeeting.saved_note_id.in_(ids)))).all()) if ids else {}
    return [{**note, 'meeting_group': note_group(note, channels.get(note.get('note_id')))} for note in notes]
