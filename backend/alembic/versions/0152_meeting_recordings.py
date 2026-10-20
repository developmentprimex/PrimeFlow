"""Private recording sessions and verified sequential chunk receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0152_meeting_recordings"
down_revision = "0151_discord_meeting_alerts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meeting_recordings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="SET NULL")),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("capture_source_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recording_started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("recording_stopped_at", sa.DateTime(timezone=True)),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("video_width", sa.Integer()),
        sa.Column("video_height", sa.Integer()),
        sa.Column("has_microphone_audio", sa.Boolean(), nullable=False),
        sa.Column("has_system_audio", sa.Boolean(), nullable=False),
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("chunks_received", sa.Integer(), nullable=False),
        sa.Column("upload_completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("error_message", sa.String(500)),
        sa.CheckConstraint("status IN ('CREATED','RECORDING','UPLOADING','FINALIZING','READY','FAILED')", name="recording_status"),
        sa.CheckConstraint("chunks_received >= 0 AND size_bytes >= 0", name="recording_counters"),
    )
    for column in ("meeting_id", "created_by", "status"):
        op.create_index(f"ix_meeting_recordings_{column}", "meeting_recordings", [column])
    op.create_table(
        "meeting_recording_chunks",
        sa.Column("recording_id", UUID(as_uuid=True), sa.ForeignKey("meeting_recordings.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("index", sa.Integer(), primary_key=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
    )


def downgrade():
    op.drop_table("meeting_recording_chunks")
    op.drop_table("meeting_recordings")
