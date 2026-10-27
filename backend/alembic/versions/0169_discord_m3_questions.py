"""M3 and next-workday Discord collection."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0169_discord_m3_questions'
down_revision = '0168_discord_answer_sync'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('discord_m3_questions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('link_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('discord_links.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tasks.id', ondelete='CASCADE')),
        sa.Column('meeting_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('meetings.id', ondelete='CASCADE')),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('context_key', sa.String(64), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('message_id', sa.String(32)),
        sa.Column('answer', postgresql.JSONB()),
        sa.Column('comment', sa.Text()),
        sa.Column('answered_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('link_id', 'day', 'kind', 'context_key', name='uq_discord_m3_question'))
    for name in ('link_id', 'task_id', 'meeting_id', 'day'):
        op.create_index(f'ix_discord_m3_questions_{name}', 'discord_m3_questions', [name])


def downgrade():
    op.drop_table('discord_m3_questions')
