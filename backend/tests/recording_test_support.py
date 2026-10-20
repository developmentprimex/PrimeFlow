"""Isolated PostgreSQL fixtures. Never falls back to the application's DB."""
import os
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

TEST_URL = os.environ.get("RECORDINGS_TEST_DATABASE_URL", "")


def configure_test_environment():
    url = sa.engine.make_url(TEST_URL)
    if url.database != "primeflow_recorder_test" or url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Recorder tests require the isolated localhost primeflow_recorder_test database")
    os.environ["DATABASE_URL"] = TEST_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["JWT_SECRET"] = "recorder-tests-only-not-a-production-secret"
    return url


def prepare_database(*, full_schema=False):
    configure_test_environment()
    # Imports occur only AFTER enforcing and installing the isolated URL.
    from app import models  # noqa: F401
    from app.models.department import Department
    from app.models.user import User
    from app.models.meeting import Meeting, MeetingParticipant
    from app.models.audit_log import AuditLog
    from app.models.enums import UserRole
    from app.auth.security import create_access_token

    engine = sa.create_engine(TEST_URL)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))
        if full_schema:
            from app.db import Base
            exclude = {'meeting_recordings', 'meeting_recording_chunks', 'recording_analyses', 'recording_transcripts', 'recording_actions'}
            Base.metadata.create_all(connection, tables=[t for t in Base.metadata.sorted_tables if t.name not in exclude])
        else:
            Department.__table__.create(connection)
            User.__table__.create(connection)
            connection.execute(sa.text("CREATE TABLE projects (id UUID PRIMARY KEY)"))
            Meeting.__table__.create(connection)
            MeetingParticipant.__table__.create(connection)
            AuditLog.__table__.create(connection)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    # Model prerequisites are isolated fixtures; execute the actual new migration
    # through Alembic, including downgrade and re-upgrade.
    command.stamp(config, "0152_discord_voice_meetings")
    command.upgrade(config, "0153_meeting_recordings")
    command.downgrade(config, "0152_discord_voice_meetings")
    command.upgrade(config, "0153_meeting_recordings")
    if full_schema:
        command.upgrade(config, '0155_recording_analysis_quality')
        command.downgrade(config, '0153_meeting_recordings')
        command.upgrade(config, '0155_recording_analysis_quality')
    with Session(engine) as db:
        department = Department(name="Recorder test", code="REC")
        db.add(department); db.flush()
        people = {}
        for key, role in [("owner", UserRole.STAFF), ("other", UserRole.STAFF), ("participant", UserRole.STAFF), ("manager", UserRole.MANAGER)]:
            person = User(id=uuid.uuid4(), email=f"{key}@example.com", username=key, full_name=key, role=role, password_hash="unused", department_id=department.id, is_active=True)
            db.add(person)
            people[key] = person
        db.flush()
        meeting = Meeting(id=uuid.uuid4(), title="Recorder fixture meeting", department_id=department.id, created_by=people["owner"].id)
        db.add(meeting); db.flush()
        db.add(MeetingParticipant(meeting_id=meeting.id, user_id=people["participant"].id, assignment_source="manual"))
        db.commit()
        fixture = {key: {"id": str(p.id), "token": create_access_token(user_id=p.id, role=p.role.value, department_id=p.department_id)} for key, p in people.items()}
        fixture["meeting_id"] = str(meeting.id)
    engine.dispose()
    return fixture
