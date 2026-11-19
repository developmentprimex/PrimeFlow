"""Store voice dictation progress and the PX Note recorder source."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0191_mira_voice_dictation"
down_revision = "0190_discord_ga_reply_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("discord_voice_meetings", sa.Column("dictation_progress", JSONB()))
    op.add_column("ga_notes", sa.Column("mira_dictation_source", sa.String(16)))


def downgrade():
    op.drop_column("ga_notes", "mira_dictation_source")
    op.drop_column("discord_voice_meetings", "dictation_progress")
