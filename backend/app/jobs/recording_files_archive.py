"""Restart-safe FILES archiving; READY rows remain the durable pending queue."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models.meeting_recording import MeetingRecording
from app.services.meeting_recording_storage import LocalMeetingStorage, StorageBusy, StorageError
from app.services.recording_files_archive import MissingRecordingSource, archive_recording, purge_recording, reports_root

logger = logging.getLogger(__name__)
_missing_sources = {}


def report_missing_sources(operation, missing, root):
    """Warn on changes, rather than printing the same traceback every minute."""
    current = frozenset(missing)
    previous = _missing_sources.get(operation, frozenset())
    if current != previous:
        if current:
            logger.warning(
                "FILES %s: %d recording(s) have no media under %s; pending on the API host "
                "that holds the original media. Verify MEETING_RECORDINGS_ROOT. IDs: %s",
                operation, len(current), root, ", ".join(sorted(current)))
        else:
            logger.info("FILES %s: previously missing local recording sources are resolved", operation)
        _missing_sources[operation] = current


def archive_candidates():
    return select(MeetingRecording).where(
        MeetingRecording.status == "READY", MeetingRecording.deleted_at.is_(None),
        MeetingRecording.recording_started_at >= settings.MEETING_RECORDINGS_FILES_FROM)


async def archive_ready_recordings():
    target = await asyncio.to_thread(reports_root, settings.FILES_SERVER_STORAGE_ROOT,
                                     settings.MEETING_RECORDINGS_FILES_SUBDIR)
    store = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT)
    cursor = None
    missing = set()
    while True:
        async with SessionLocal() as db:
            query = archive_candidates()
            if cursor is not None:
                query = query.where(MeetingRecording.id > cursor)
            rows = list((await db.execute(query.order_by(MeetingRecording.id).limit(100))).scalars())
        if not rows:
            report_missing_sources("archive", missing, store.root)
            return
        for row in rows:
            try:
                async with SessionLocal() as db:
                    current = (await db.execute(archive_candidates().where(MeetingRecording.id == row.id)
                        .with_for_update(skip_locked=True))).scalar_one_or_none()
                    if current is not None:
                        await asyncio.to_thread(archive_recording, current, store, target)
                    await db.commit()
            except StorageBusy:
                pass  # Another API worker owns this recording; retry next sweep.
            except MissingRecordingSource:
                missing.add(str(row.id))
            except Exception:
                logger.exception("FILES archive pending for recording %s", row.id)
        cursor = rows[-1].id


async def purge_deleted_recordings():
    store = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT)
    missing = set()
    async with SessionLocal() as db:
        rows = list((await db.execute(select(MeetingRecording).where(
            MeetingRecording.deleted_at.is_not(None), MeetingRecording.files_purged_at.is_(None))
            .order_by(MeetingRecording.deleted_at).limit(100))).scalars())
    for row in rows:
        try:
            async with SessionLocal() as db:
                current = (await db.execute(select(MeetingRecording).where(
                    MeetingRecording.id == row.id, MeetingRecording.files_purged_at.is_(None))
                    .with_for_update(skip_locked=True))).scalar_one_or_none()
                if current is None:
                    continue
                target = await asyncio.to_thread(reports_root, settings.FILES_SERVER_STORAGE_ROOT,
                                                 settings.MEETING_RECORDINGS_FILES_SUBDIR)
                await asyncio.to_thread(purge_recording, current, store, target)
                current.files_purged_at = datetime.now(timezone.utc)
                await db.commit()
        except MissingRecordingSource:
            missing.add(str(row.id))
        except Exception:
            logger.exception("Recording deletion pending for %s; will retry", row.id)
    report_missing_sources("deletion", missing, store.root)


async def run_recording_files_archive_forever():
    while True:
        try:
            await purge_deleted_recordings()
            if settings.MEETING_RECORDINGS_FILES_ENABLED:
                await archive_ready_recordings()
        except StorageError as exc:
            logger.warning("FILES archive pending: %s; will retry in 60 seconds", exc)
        except Exception:
            logger.exception("FILES archive unavailable; local recordings retained for retry")
        await asyncio.sleep(60)
