"""Keep structured Discord 1H reports independently of the voice host."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0170_discord_one_h_reports'
down_revision = '0169_discord_m3_questions'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discord_reminders', sa.Column('one_h_report', postgresql.JSONB(), nullable=True))
    op.create_index('ix_discord_reminders_day_bucket', 'discord_reminders', ['day', 'bucket'])


def downgrade():
    op.drop_index('ix_discord_reminders_day_bucket', table_name='discord_reminders')
    op.drop_column('discord_reminders', 'one_h_report')
