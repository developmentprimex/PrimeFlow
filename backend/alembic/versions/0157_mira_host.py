"""Mira Host: 1H meetings led by Mira, their turns, daily mentions and Mira's knowledge."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0157_mira_host'
down_revision = '0156_mira_memory'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('mira_host_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled_until', sa.DateTime(timezone=True)),
        sa.Column('enabled_by_user_id', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('ga_participants', JSONB(), nullable=False, server_default='[]'),
        sa.Column('protocol_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('target_minutes_per_person', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('knowledge_char_budget', sa.Integer(), nullable=False, server_default='24000'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('mira_1h_meetings',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('meeting_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(5), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('staff_started_at', sa.DateTime(timezone=True)),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('voice_meeting_id', UUID(), sa.ForeignKey('discord_voice_meetings.id', ondelete='SET NULL')),
        sa.Column('host_transcript', JSONB(), nullable=False, server_default='[]'),
        sa.Column('summary', sa.Text()),
        sa.Column('summary_status', sa.String(20)),
        sa.Column('error', sa.String(300)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('meeting_date', 'slot', name='uq_mira_1h_meeting_slot'))
    op.create_table('mira_1h_turns',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('meeting_id', UUID(), sa.ForeignKey('mira_1h_meetings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_idx', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('invited_at', sa.DateTime(timezone=True)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.UniqueConstraint('meeting_id', 'user_id', name='uq_mira_1h_turn_user'))
    op.create_index('ix_mira_1h_turns_meeting_id', 'mira_1h_turns', ['meeting_id'])
    op.create_table('mira_1h_mentions',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('meeting_date', sa.Date(), nullable=False),
        sa.Column('task_id', UUID(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('point_key', sa.String(64), nullable=False, server_default=''),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('meeting_id', UUID(), sa.ForeignKey('mira_1h_meetings.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('meeting_date', 'task_id', 'kind', 'point_key', name='uq_mira_1h_mention'))
    op.create_table('mira_1h_events',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('key', sa.String(200), unique=True),
        sa.Column('meeting_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.String(5), nullable=False),
        sa.Column('meeting_id', UUID(), sa.ForeignKey('mira_1h_meetings.id', ondelete='CASCADE')),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('data', JSONB(), nullable=False, server_default='{}'),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_mira_1h_events_day_slot', 'mira_1h_events', ['meeting_date', 'slot'])
    op.create_table('mira_knowledge_items',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('file_name', sa.String(255)),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_by_user_id', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    op.drop_table('mira_knowledge_items')
    op.drop_index('ix_mira_1h_events_day_slot', 'mira_1h_events')
    op.drop_table('mira_1h_events')
    op.drop_table('mira_1h_mentions')
    op.drop_index('ix_mira_1h_turns_meeting_id', 'mira_1h_turns')
    op.drop_table('mira_1h_turns')
    op.drop_table('mira_1h_meetings')
    op.drop_table('mira_host_settings')
