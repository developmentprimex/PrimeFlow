"""Record GA reactions observed by the Discord worker."""

import sqlalchemy as sa
from alembic import op

revision = "0200_discord_ga_reactions"
down_revision = "0199_ga_note_attachment_contents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discord_ga_reactions",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("staff_name", sa.String(100), nullable=False),
        sa.Column("message_excerpt", sa.String(280), nullable=False),
        sa.Column("emoji", sa.String(100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discord_ga_reactions_window", "discord_ga_reactions",
                    ["guild_id", "channel_id", "observed_at"])


def downgrade() -> None:
    op.drop_table("discord_ga_reactions")
