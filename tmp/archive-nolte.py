import asyncio
import json
from pathlib import Path
import sys
import os
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal, engine
from app.models.meeting_recording import MeetingRecording
from app.services.meeting_recording_storage import LocalMeetingStorage, durable_replace
from app.services.recording_files_archive import archive_recording, digest_file, reports_root


async def main():
    async with SessionLocal() as db:
        rows = list((await db.execute(select(MeetingRecording).where(
            MeetingRecording.title == 'TAK NOLTE', MeetingRecording.deleted_at.is_(None),
            MeetingRecording.status == 'READY'))).scalars())
        if len(rows) != 1:
            raise RuntimeError(f'Expected one READY TAK NOLTE recording, found {len(rows)}')
        row = rows[0]
        store = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT)
        extension = 'webm' if row.mime_type == 'video/webm' else 'mp4'
        source = store.path(f'{row.storage_key}/recording.{extension}')
        result = {'id': str(row.id), 'title': row.title, 'storage_key': row.storage_key,
                  'size_bytes': row.size_bytes, 'date': row.recording_started_at.isoformat(),
                  'source': str(source), 'source_exists': source.is_file()}
        if '--download' in sys.argv and not source.is_file():
            # Use the app's normal authentication and owner/management download
            # authorization; never mint or print credentials or bearer tokens.
            async with httpx.AsyncClient(base_url='https://api-flow.primexeu.com/api',
                                          timeout=httpx.Timeout(300, connect=20), trust_env=False) as client:
                login = await client.post('/auth/login', json={'email': settings.ADMIN_EMAIL,
                                                              'password': settings.ADMIN_PASSWORD})
                login.raise_for_status()
                token = login.json()['access_token']
                headers = {'Authorization': 'Bearer ' + token}
                info = await client.get(f'/meeting-recordings/{row.id}', headers=headers)
                info.raise_for_status()
                remote = info.json()
                assert remote['id'] == str(row.id) and remote['title'] == 'TAK NOLTE'
                assert remote['size_bytes'] == row.size_bytes and remote['status'] == 'READY'
                source.parent.mkdir(parents=True, exist_ok=True)
                temporary = source.with_suffix('.download.part')
                try:
                    size = 0
                    async with client.stream('GET', f'/meeting-recordings/{row.id}/download', headers=headers) as response:
                        response.raise_for_status()
                        with temporary.open('wb') as output:
                            async for block in response.aiter_bytes(1024 * 1024):
                                size += len(block)
                                if size > row.size_bytes:
                                    raise RuntimeError('Download exceeds verified recording size')
                                output.write(block)
                            output.flush()
                            os.fsync(output.fileno())
                    assert size == row.size_bytes, 'Incomplete download'
                    durable_replace(temporary, source)
                    result['downloaded_bytes'] = size
                finally:
                    temporary.unlink(missing_ok=True)
        if '--copy' in sys.argv:
            target = reports_root(settings.FILES_SERVER_STORAGE_ROOT, settings.MEETING_RECORDINGS_FILES_SUBDIR)
            destination = await asyncio.to_thread(archive_recording, row, store, target)
            assert digest_file(source) == digest_file(destination)
            result.update(verified=True, destination=str(destination))
        print(json.dumps(result))
    await engine.dispose()

asyncio.run(main())
