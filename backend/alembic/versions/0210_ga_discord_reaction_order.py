"""Record live reaction order for the GA staff-channel feed."""

import sqlalchemy as sa
from alembic import op

revision = "0210_ga_discord_reaction_order"
down_revision = "0209_ga_1h_comment_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ga_discord_channel_messages", sa.Column("reaction_session_id", sa.String(32)))
    op.add_column("ga_discord_channel_messages", sa.Column("reaction_sequence", sa.BigInteger()))
    op.create_table(
        "ga_discord_reaction_events",
        sa.Column("message_id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("user_id", sa.String(32)),
        sa.Column("emoji_key", sa.String(100)),
        sa.Column("burst", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_table("ga_discord_reaction_events")
    op.drop_column("ga_discord_channel_messages", "reaction_sequence")
    op.drop_column("ga_discord_channel_messages", "reaction_session_id")
