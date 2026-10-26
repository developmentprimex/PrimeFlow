"""M2 PM continuation and date-change approval queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision = '0163_discord_m2_approvals'
down_revision = '0162_discord_m2_questions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('discord_m2_postponements',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('question_id', UUID(), sa.ForeignKey('discord_m2_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('requester_link_id', UUID(), sa.ForeignKey('discord_links.id', ondelete='CASCADE'), nullable=False),
        sa.Column('approver_user_id', UUID(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('task_id', UUID(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('request_id', sa.String(32), nullable=False, unique=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('change_kind', sa.String(16), nullable=False),
        sa.Column('proposed_dates', JSONB(), nullable=False),
        sa.Column('original_tasks', JSONB(), nullable=False),
        sa.Column('reason_code', sa.String(40), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True)),
        sa.Column('decided_by', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('decision_detail', sa.Text()),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('review_sent_at', sa.DateTime(timezone=True)),
        sa.Column('review_message_id', sa.String(32)),
        sa.Column('review_updated_at', sa.DateTime(timezone=True)),
        sa.Column('requester_notified_at', sa.DateTime(timezone=True)))
    op.create_index('ix_discord_m2_postponements_task_id', 'discord_m2_postponements', ['task_id'])
    op.create_index('ix_discord_m2_postponements_status', 'discord_m2_postponements', ['status'])
    op.create_index('uq_discord_m2_pending_task', 'discord_m2_postponements', ['task_id'], unique=True,
                    postgresql_where=sa.text("status = 'PENDING'"))


def downgrade():
    op.drop_table('discord_m2_postponements')
