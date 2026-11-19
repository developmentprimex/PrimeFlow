"""Store the Notetaker quick summary separately from full notes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0192_mira_quick_summary'
down_revision = '0191_mira_voice_dictation'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discord_voice_meetings', sa.Column('quick_summary', JSONB()))


def downgrade():
    op.drop_column('discord_voice_meetings', 'quick_summary')
