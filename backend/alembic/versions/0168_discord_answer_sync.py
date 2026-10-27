"""Durable in-place synchronization of platform answers to Discord questions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0168_discord_answer_sync'
down_revision = '0167_discord_task_postponements'
branch_labels = None
depends_on = None

def upgrade():
    for table in ('discord_m2_questions', 'discord_meeting_alerts'):
        op.add_column(table, sa.Column('sync_hash', sa.String(64), nullable=True))
        op.add_column(table, sa.Column('sync_pending_hash', sa.String(64), nullable=True))
        op.add_column(table, sa.Column('sync_lease_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('discord_m2_questions', sa.Column('platform_answer', postgresql.JSONB(), nullable=True))
    op.add_column('discord_m2_questions', sa.Column('platform_answered_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column('discord_m2_questions', 'platform_answered_at')
    op.drop_column('discord_m2_questions', 'platform_answer')
    for table in ('discord_m2_questions', 'discord_meeting_alerts'):
        for field in ('sync_lease_until', 'sync_pending_hash', 'sync_hash'):
            op.drop_column(table, field)
