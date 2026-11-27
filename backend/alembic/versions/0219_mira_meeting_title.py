"""Add a catalog title for Mira recordings."""

import sqlalchemy as sa
from alembic import op


revision = "0219_mira_meeting_title"
down_revision = "0218_weekly_planning_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discord_voice_meetings", sa.Column("mira_title", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("discord_voice_meetings", "mira_title")
