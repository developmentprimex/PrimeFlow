"""OAuth 2.1 authorization-server tables and GA assistant per-day item times.

Additive only: creates four new tables and touches no existing table or row.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0191_mcp_assistant_oauth"
down_revision = "0190_discord_ga_reply_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=True),
        sa.Column("redirect_uris", postgresql.JSONB(), nullable=False),
        sa.Column("grant_types", postgresql.JSONB(), nullable=False),
        sa.Column("scope", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True)

    op.create_table(
        "oauth_authorization_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=200), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_oauth_authorization_requests_client_id", "oauth_authorization_requests", ["client_id"])
    op.create_index("ix_oauth_authorization_requests_user_id", "oauth_authorization_requests", ["user_id"])
    op.create_index(
        "ix_oauth_authorization_requests_code_hash", "oauth_authorization_requests", ["code_hash"], unique=True
    )

    op.create_table(
        "oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_type", sa.String(length=10), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(length=200), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_oauth_tokens_token_hash", "oauth_tokens", ["token_hash"], unique=True)
    op.create_index("ix_oauth_tokens_client_id", "oauth_tokens", ["client_id"])
    op.create_index("ix_oauth_tokens_user_id", "oauth_tokens", ["user_id"])
    op.create_index("ix_oauth_tokens_family_id", "oauth_tokens", ["family_id"])

    op.create_table(
        "ga_assistant_item_times",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_key", sa.String(length=120), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("time_value", sa.String(length=5), nullable=True),
        sa.Column("has_time_override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("removed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("removed_reason", sa.String(length=1000), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "item_key", "day_date", name="uq_ga_assistant_item_time"),
    )
    op.create_index("ix_ga_assistant_item_times_user_id", "ga_assistant_item_times", ["user_id"])
    op.create_index("ix_ga_assistant_item_times_day_date", "ga_assistant_item_times", ["day_date"])


def downgrade() -> None:
    op.drop_table("ga_assistant_item_times")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_requests")
    op.drop_table("oauth_clients")
