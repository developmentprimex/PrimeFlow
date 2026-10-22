"""Mira Host: count join attempts so a failed connection is retried a few times."""
from alembic import op
import sqlalchemy as sa

revision = '0159_mira_host_join_attempts'
down_revision = '0158_recording_timing_merge'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mira_1h_meetings', sa.Column('join_attempts', sa.Integer(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('mira_1h_meetings', 'join_attempts')
