"""Process one durable protocol job using the existing recording worker."""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, select
from app.config import settings
from app.models.meeting_recording import MeetingRecording
from app.models.recording_protocol import RecordingProtocol
from app.services import recording_protocol as provider

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


async def process_recording_protocols(session_factory):
    if not settings.RECORDING_ANALYSIS_ENABLED or not settings.OPENAI_API_KEY:
        return 0
    async with session_factory() as db:
        job = (await db.execute(select(RecordingProtocol).join(MeetingRecording,
            MeetingRecording.id == RecordingProtocol.recording_id).where(MeetingRecording.deleted_at.is_(None),
            RecordingProtocol.status.in_(['QUEUED', 'GENERATING']),
            or_(RecordingProtocol.lease_until.is_(None), RecordingProtocol.lease_until < now()))
            .order_by(RecordingProtocol.updated_at).with_for_update(skip_locked=True, of=RecordingProtocol).limit(1))).scalar_one_or_none()
        if not job:
            return 0
        sid, language, token = job.recording_id, job.language, uuid.uuid4()
        source, cache, content = job.source, job.checkpoint, job.content
        job.status, job.lease_token, job.lease_until = 'GENERATING', token, now() + timedelta(minutes=20)
        await db.commit()

    async def fenced(db):
        # Same lock order as requests/deletion: recording then protocol.
        row = (await db.execute(select(MeetingRecording).where(MeetingRecording.id == sid)
            .with_for_update())).scalar_one_or_none()
        if not row or row.deleted_at is not None:
            raise ValueError('protocol_recording_deleted')
        current = (await db.execute(select(RecordingProtocol).where(RecordingProtocol.recording_id == sid,
            RecordingProtocol.language == language).with_for_update())).scalar_one_or_none()
        if not current or current.lease_token != token:
            raise ValueError('protocol_lease_changed')
        current.lease_until = now() + timedelta(minutes=20)
        return current

    async def checkpoint(value):
        async with session_factory() as db:
            current = await fenced(db)
            current.checkpoint = value
            await db.commit()

    try:
        if content is None:
            content = await provider.generate_content(source, language, cache, checkpoint)
            async with session_factory() as db:
                current = await fenced(db)
                current.content = content
                await db.commit()
        document = await asyncio.to_thread(provider.render_protocol, content, source, language)
        async with session_factory() as db:
            current = await fenced(db)
            current.document, current.status = document, 'READY'
            current.error_message, current.lease_until = None, None
            await db.commit()
    except Exception as exc:
        # Do not log private source content or provider response bodies.
        logger.warning('Protocol generation failed: recording=%s language=%s type=%s', sid, language, type(exc).__name__)
        async with session_factory() as db:
            try:
                current = await fenced(db)
            except ValueError:
                return 1
            current.status, current.lease_until = 'FAILED', None
            current.error_message = 'Protokolli nuk u përfundua ose përmbajtja nuk u verifikua. Riprovo gjenerimin.'
            if isinstance(exc, provider.ProviderError) and exc.status in (401, 403):
                current.error_message = 'Shërbimi AI refuzoi autorizimin. Administratori duhet të kontrollojë çelësin API në server.'
            await db.commit()
    return 1
