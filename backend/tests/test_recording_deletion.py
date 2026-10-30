import unittest
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.api.routers.meeting_recordings import delete_recording, load_recording
from app.models.enums import UserRole


class RecordingDeletionTests(unittest.IsolatedAsyncioTestCase):
    def database(self, row):
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        db.execute.return_value = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = row
        return db

    async def test_non_admin_including_creator_cannot_delete(self):
        for role in (UserRole.STAFF, UserRole.MANAGER):
            with self.subTest(role=role):
                user = SimpleNamespace(id=uuid.uuid4(), role=role)
                row = SimpleNamespace(id=uuid.uuid4(), created_by=user.id, status='READY', deleted_at=None)
                db = self.database(row)
                with self.assertRaises(HTTPException) as error:
                    await delete_recording(row.id, db, user)
                self.assertEqual(error.exception.status_code, 403)
                db.execute.assert_not_called()
                db.commit.assert_not_awaited()

    async def test_admin_deletes_with_audit(self):
        for role in (UserRole.ADMIN,):
            row = SimpleNamespace(id=uuid.uuid4(), title='Takimi', status='READY', deleted_at=None)
            db = self.database(row)
            with patch('app.api.routers.meeting_recordings.audit') as audit:
                response = await delete_recording(row.id, db, SimpleNamespace(role=role))
            self.assertEqual(response.status_code, 204)
            self.assertIsNotNone(row.deleted_at)
            db.commit.assert_awaited_once()
            self.assertEqual(audit.call_args.args[3], 'recording_deleted')

    async def test_active_recording_cannot_be_deleted(self):
        row = SimpleNamespace(status='UPLOADING', deleted_at=None)
        db = self.database(row)
        with self.assertRaises(HTTPException) as error:
            await delete_recording(uuid.uuid4(), db, SimpleNamespace(role=UserRole.ADMIN))
        self.assertEqual(error.exception.status_code, 409)
        db.commit.assert_not_awaited()

    async def test_deleted_recording_is_inaccessible_even_to_admin(self):
        db = self.database(None)
        with self.assertRaises(HTTPException) as error:
            await load_recording(db, uuid.uuid4(), SimpleNamespace(role=UserRole.ADMIN))
        self.assertEqual(error.exception.status_code, 404)
        query = str(db.execute.call_args.args[0])
        self.assertIn('meeting_recordings.deleted_at IS NULL', query)

    async def test_staff_can_read_others_recording_but_writes_stay_owner_only(self):
        row = SimpleNamespace(id=uuid.uuid4())
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF)
        db = self.database(row)
        self.assertIs(await load_recording(db, row.id, user), row)
        read_where = str(db.execute.call_args.args[0]).split('WHERE')[1]
        self.assertNotIn('created_by', read_where)
        self.assertNotIn('meeting_participants', read_where)
        self.assertIn('deleted_at IS NULL', read_where)
        await load_recording(db, row.id, user, write=True)
        write_where = str(db.execute.call_args.args[0]).split('WHERE')[1]
        self.assertIn('created_by', write_where)

    def test_missing_source_warning_is_not_repeated_on_every_sweep(self):
        from app.jobs import recording_files_archive as job
        with patch.object(job, '_missing_sources', {}), patch.object(job, 'logger') as logger:
            job.report_missing_sources('archive', {'other-host'}, '/private/local')
            job.report_missing_sources('archive', {'other-host'}, '/private/local')
            logger.warning.assert_called_once()
            logger.exception.assert_not_called()
            job.report_missing_sources('archive', set(), '/private/local')
            logger.info.assert_called_once()

    def test_archive_excludes_old_recordings_and_retains_activation_boundary(self):
        import sqlalchemy as sa
        from app.config import settings
        from app.jobs.recording_files_archive import archive_candidates
        from app.models.meeting_recording import MeetingRecording
        cutoff = settings.MEETING_RECORDINGS_FILES_FROM
        engine = sa.create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        metadata = sa.MetaData()
        table = sa.Table('meeting_recordings', metadata,
                         sa.Column('id', sa.Uuid, primary_key=True), sa.Column('status', sa.String),
                         sa.Column('deleted_at', sa.DateTime), sa.Column('recording_started_at', sa.DateTime))
        metadata.create_all(engine)
        old_id, boundary_id, future_id, deleted_id = [uuid.uuid4() for _ in range(4)]
        with engine.begin() as connection:
            connection.execute(table.insert(), [
                dict(id=old_id, status='READY', deleted_at=None, recording_started_at=cutoff - timedelta(seconds=1)),
                dict(id=boundary_id, status='READY', deleted_at=None, recording_started_at=cutoff),
                dict(id=future_id, status='READY', deleted_at=None, recording_started_at=cutoff + timedelta(seconds=1)),
                dict(id=deleted_id, status='READY', deleted_at=cutoff, recording_started_at=cutoff + timedelta(seconds=1)),
            ])
            query = archive_candidates().with_only_columns(MeetingRecording.id)
            self.assertEqual(set(connection.execute(query).scalars()), {boundary_id, future_id})
            # A later sweep uses the same configured cutoff, including retries.
            self.assertEqual(set(connection.execute(archive_candidates().with_only_columns(MeetingRecording.id)).scalars()),
                             {boundary_id, future_id})
