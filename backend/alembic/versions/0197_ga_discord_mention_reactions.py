"""Reactions on GA Discord mentions (who reviewed a message before it reaches the GA).

Additive only: two new columns on ga_discord_mentions; no existing row or column changes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0197_ga_discord_reactions"
down_revision = "0196_task_plan_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ga_discord_mentions",
        sa.Column("reactions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("ga_discord_mentions", sa.Column("reactions_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ga_discord_mentions", "reactions_synced_at")
    op.drop_column("ga_discord_mentions", "reactions")
