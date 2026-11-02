"""Durable EN/DE meeting protocols and cached Word downloads."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0179_recording_protocols'
down_revision = '0178_ga_note_is_repetitive'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recording_protocols',
        sa.Column('recording_id', pg.UUID(as_uuid=True), sa.ForeignKey('meeting_recordings.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('language', sa.String(2), primary_key=True),
        sa.Column('requested_by', pg.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('source', pg.JSONB(), nullable=False),
        sa.Column('checkpoint', pg.JSONB()), sa.Column('content', pg.JSONB()),
        sa.Column('document', sa.LargeBinary()), sa.Column('error_message', sa.String(500)),
        sa.Column('lease_token', pg.UUID(as_uuid=True)), sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("language IN ('en','de')", name='protocol_language'),
        sa.CheckConstraint("status IN ('QUEUED','GENERATING','READY','FAILED')", name='protocol_status'))
    op.create_index('ix_recording_protocols_status', 'recording_protocols', ['status'])


def downgrade():
    op.drop_table('recording_protocols')
