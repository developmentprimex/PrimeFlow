"""Personal Discord links, reminder delivery leases and action audit."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0148_discord_assistant"
down_revision = "0147_m1_reporting_points"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("discord_links",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("selected_task_id", pg.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("pending_instruction", sa.Text()),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
        sa.Column("selected_fingerprint", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "discord_user_id", name="uq_discord_link_identity"))
    op.create_table("discord_link_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_discord_link_codes_user_id", "discord_link_codes", ["user_id"])
    op.create_table("discord_reminders",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("discord_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("bucket", sa.String(16), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("message_ids", pg.JSONB()),
        sa.UniqueConstraint("link_id", "day", "bucket", name="uq_discord_reminder_bucket"))
    op.create_table("discord_actions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("discord_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True)),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", pg.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_discord_actions_link_id", "discord_actions", ["link_id"])


def downgrade():
    op.drop_table("discord_actions")
    op.drop_table("discord_reminders")
    op.drop_table("discord_link_codes")
    op.drop_table("discord_links")
