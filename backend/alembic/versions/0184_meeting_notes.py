"""Takimet: meeting notes, their screenshots, training flag and dismissed recording proposals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0184_meeting_notes"
down_revision = "0183_rlz_task_confirmations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meetings", sa.Column("is_training", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("meeting_schedule_requests", sa.Column("is_training", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("recording_actions", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "meeting_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="NOTE"),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="MANUAL"),
        sa.Column("recording_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meeting_recordings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recording_action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recording_actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recording_seconds", sa.Float(), nullable=True),
        sa.Column("assignee_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("ga_note_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ga_notes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('NOTE','QUESTION')", name="meeting_note_kind"),
        sa.CheckConstraint("source IN ('MANUAL','RECORDING')", name="meeting_note_source"),
    )
    op.create_index("ix_meeting_notes_meeting_id", "meeting_notes", ["meeting_id"])
    op.create_index("ix_meeting_notes_occurrence_date", "meeting_notes", ["occurrence_date"])
    op.create_index("ix_meeting_notes_recording_id", "meeting_notes", ["recording_id"])
    op.create_index("ix_meeting_notes_recording_action_id", "meeting_notes", ["recording_action_id"])
    op.create_index("ix_meeting_notes_ga_note_id", "meeting_notes", ["ga_note_id"])

    op.create_table(
        "meeting_note_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meeting_notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meeting_note_attachments_note_id", "meeting_note_attachments", ["note_id"])


def downgrade():
    op.drop_index("ix_meeting_note_attachments_note_id", table_name="meeting_note_attachments")
    op.drop_table("meeting_note_attachments")
    for name in ("ga_note_id", "recording_action_id", "recording_id", "occurrence_date", "meeting_id"):
        op.drop_index(f"ix_meeting_notes_{name}", table_name="meeting_notes")
    op.drop_table("meeting_notes")
    op.drop_column("recording_actions", "dismissed_at")
    op.drop_column("meeting_schedule_requests", "is_training")
    op.drop_column("meetings", "is_training")
