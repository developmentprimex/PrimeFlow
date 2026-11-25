"""Store comments for Discord delivery report rows."""

import sqlalchemy as sa
from alembic import op

revision = "0209_discord_delivery_comments"
down_revision = "0208_ga_discord_reply_context"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discord_task_delivery_comments",
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column("row_id", sa.String(73), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
    )
    op.create_index("ix_discord_task_delivery_comments_task_id", "discord_task_delivery_comments", ["task_id"])


def downgrade():
    op.drop_table("discord_task_delivery_comments")
