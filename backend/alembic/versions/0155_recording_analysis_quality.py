"""Meeting-level decisions, automatic retries and prefilled task suggestions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0155_recording_analysis_quality'
down_revision = '0154_recording_analysis'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('recording_analyses', sa.Column('decisions', JSONB()))
    op.add_column('recording_analyses', sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('recording_actions', sa.Column('suggested_assignee_id', UUID(), sa.ForeignKey('users.id', ondelete='SET NULL')))
    op.add_column('recording_actions', sa.Column('suggested_due_date', sa.Date()))


def downgrade():
    op.drop_column('recording_actions', 'suggested_due_date')
    op.drop_column('recording_actions', 'suggested_assignee_id')
    op.drop_column('recording_analyses', 'attempts')
    op.drop_column('recording_analyses', 'decisions')
