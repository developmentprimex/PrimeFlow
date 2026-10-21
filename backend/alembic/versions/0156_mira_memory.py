"""Mira's living memory register; existing meetings are never backfilled."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0156_mira_memory'
down_revision = '0155_recording_analysis_quality'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('mira_memory_items',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('people', JSONB(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('mention_count', sa.Integer(), nullable=False),
        sa.Column('last_mentioned_at', sa.DateTime(timezone=True)),
        sa.Column('human_edited', sa.Boolean(), nullable=False),
        sa.Column('updated_by_user_id', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_mira_memory_items_status_mentioned', 'mira_memory_items', ['status', 'last_mentioned_at'])
    op.create_table('mira_memory_events',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('item_id', UUID(), sa.ForeignKey('mira_memory_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('meeting_id', UUID(), sa.ForeignKey('discord_voice_meetings.id', ondelete='SET NULL')),
        sa.Column('user_id', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('partial', sa.Boolean(), nullable=False),
        sa.Column('refs', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_mira_memory_events_item_id', 'mira_memory_events', ['item_id'])
    op.add_column('discord_voice_meetings', sa.Column('memory_status', sa.String(20)))
    op.add_column('discord_voice_meetings', sa.Column('memory_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('discord_voice_meetings', sa.Column('memory_error', sa.String(100)))
    op.add_column('discord_voice_meetings', sa.Column('memory_lease_until', sa.DateTime(timezone=True)))
    # No backfill: Mira remembers only meetings that end after activation.
    op.execute("UPDATE discord_voice_meetings SET memory_status = 'SKIPPED'")


def downgrade():
    for column in ('memory_lease_until', 'memory_error', 'memory_attempts', 'memory_status'):
        op.drop_column('discord_voice_meetings', column)
    op.drop_index('ix_mira_memory_events_item_id', 'mira_memory_events')
    op.drop_table('mira_memory_events')
    op.drop_index('ix_mira_memory_items_status_mentioned', 'mira_memory_items')
    op.drop_table('mira_memory_items')
