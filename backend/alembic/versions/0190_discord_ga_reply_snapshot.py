"""Persist staff-to-GA reply evidence separately from task reporting."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0190_discord_ga_reply_snapshot"
down_revision = "0189_two_task_markers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discord_ga_reply_snapshots",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("channel_id", sa.String(32), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("discord_ga_reply_snapshots")
