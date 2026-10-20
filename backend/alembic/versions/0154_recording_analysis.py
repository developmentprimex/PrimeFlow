"""Durable recording transcription, summaries and reviewed task proposals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0154_recording_analysis'
down_revision = '0153_meeting_recordings'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recording_analyses',
        sa.Column('recording_id', UUID(), sa.ForeignKey('meeting_recordings.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('requested_by', UUID(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('language', sa.String(8), nullable=False),
        sa.Column('total_segments', sa.Integer(), nullable=False),
        sa.Column('segments_done', sa.Integer(), nullable=False),
        sa.Column('summary', sa.Text()), sa.Column('summary_progress', JSONB()),
        sa.Column('error_message', sa.String(500)), sa.Column('lease_token', UUID()),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('QUEUED','TRANSCRIBING','SUMMARIZING','READY','FAILED')", name='analysis_status'))
    op.create_index('ix_recording_analyses_status', 'recording_analyses', ['status'])
    op.create_table('recording_transcripts',
        sa.Column('recording_id', UUID(), sa.ForeignKey('recording_analyses.recording_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('index', sa.Integer(), primary_key=True),
        sa.Column('start_seconds', sa.Integer(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False), sa.Column('notes', JSONB()))
    op.create_table('recording_actions',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('recording_id', UUID(), sa.ForeignKey('recording_analyses.recording_id', ondelete='CASCADE'), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('segment_index', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False), sa.Column('description', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False),
        sa.Column('assignee_text', sa.String(200)), sa.Column('deadline_text', sa.String(200)),
        sa.Column('created_task_id', UUID(), sa.ForeignKey('tasks.id', ondelete='SET NULL')),
        sa.Column('confirmed_by', UUID(), sa.ForeignKey('users.id')),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('recording_id', 'fingerprint'))
    op.create_index('ix_recording_actions_recording_id', 'recording_actions', ['recording_id'])


def downgrade():
    op.drop_table('recording_actions')
    op.drop_table('recording_transcripts')
    op.drop_table('recording_analyses')
