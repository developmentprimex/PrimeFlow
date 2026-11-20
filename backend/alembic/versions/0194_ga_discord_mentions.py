"""GA Discord mentions (read-only bot evidence for the GA assistant).

Additive only: creates one new table and touches no existing table or row.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0194_ga_discord_mentions"
down_revision = "0193_merge_mira_quick_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ga_discord_mentions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("channel_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("author_discord_id", sa.String(length=32), nullable=False),
        sa.Column("author_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("jump_url", sa.String(length=300), nullable=False),
        sa.Column("attachments", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("reasons", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("reply_to_message_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="new", nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ga_discord_mentions_created_at", "ga_discord_mentions", ["created_at"])
    op.create_index("ix_ga_discord_mentions_status_created", "ga_discord_mentions", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ga_discord_mentions_status_created", table_name="ga_discord_mentions")
    op.drop_index("ix_ga_discord_mentions_created_at", table_name="ga_discord_mentions")
    op.drop_table("ga_discord_mentions")
