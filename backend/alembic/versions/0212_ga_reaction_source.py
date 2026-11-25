"""Ensure Discord GA reactions have source message identifiers."""

from alembic import op


revision = "0212_ga_reaction_source"
down_revision = "0211_ga_device_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some databases received these columns in a different version of 0206.
    op.execute(
        "ALTER TABLE discord_ga_reactions "
        "ADD COLUMN IF NOT EXISTS message_channel_id VARCHAR(32), "
        "ADD COLUMN IF NOT EXISTS message_author_id VARCHAR(32)"
    )


def downgrade() -> None:
    op.drop_column("discord_ga_reactions", "message_author_id")
    op.drop_column("discord_ga_reactions", "message_channel_id")
