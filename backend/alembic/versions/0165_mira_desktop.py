"""Independent owner-scoped desktop capture text and recovery leases."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0165_mira_desktop'
down_revision = '0164_project_is_active'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('mira_desktop_sessions',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('department_id', UUID(), sa.ForeignKey('departments.id')),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('partial', sa.Boolean(), nullable=False),
        sa.Column('error', sa.String(100)),
        sa.Column('expected_segments', sa.Integer()),
        sa.Column('notes', sa.Text()),
        sa.Column('note_id', UUID(), sa.ForeignKey('ga_notes.id', ondelete='SET NULL')),
        sa.Column('summary_progress', JSONB()),
        sa.Column('lease_token', UUID()),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_mira_desktop_sessions_user_id', 'mira_desktop_sessions', ['user_id'])
    op.create_table('mira_desktop_segments',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('session_id', UUID(), sa.ForeignKey('mira_desktop_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('start_ms', sa.Integer(), nullable=False),
        sa.Column('end_ms', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('transcript', sa.Text()),
        sa.Column('error', sa.String(100)),
        sa.Column('lease_token', UUID()),
        sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('session_id', 'sequence', name='uq_mira_desktop_segment_sequence'))
    op.create_index('ix_mira_desktop_segments_session_id', 'mira_desktop_segments', ['session_id'])


def downgrade():
    op.drop_table('mira_desktop_segments')
    op.drop_table('mira_desktop_sessions')
