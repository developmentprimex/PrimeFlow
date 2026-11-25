"""Store the GA staff channel history for Discord mention context."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0207_ga_discord_channel_archive"
down_revision = "0206_discord_ga_reaction_files"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ga_discord_channel_messages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("parent_channel_id", sa.String(32)),
        sa.Column("channel_name", sa.String(200), nullable=False),
        sa.Column("author_discord_id", sa.String(32), nullable=False),
        sa.Column("author_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("jump_url", sa.String(300), nullable=False),
        sa.Column("attachments", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("reply_to_message_id", sa.String(32)),
        sa.Column("reactions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("reactions_synced_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ga_discord_channel_author_time", "ga_discord_channel_messages",
                    ["channel_id", "author_discord_id", "created_at"])
    op.create_index("ix_ga_discord_channel_reply", "ga_discord_channel_messages", ["reply_to_message_id"])
    op.create_table(
        "ga_discord_archive_checkpoints",
        sa.Column("channel_id", sa.String(32), primary_key=True),
        sa.Column("last_message_id", sa.String(32), nullable=False),
    )


def downgrade():
    op.drop_table("ga_discord_archive_checkpoints")
    op.drop_table("ga_discord_channel_messages")
