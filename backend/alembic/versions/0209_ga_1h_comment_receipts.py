"""Track which 1H comment revisions each GA assistant user has seen."""

import sqlalchemy as sa

from alembic import op

revision = "0209_ga_1h_comment_receipts"
down_revision = "0208_ga_discord_reply_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ga_1h_comment_receipts",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source", sa.String(8), primary_key=True),
        sa.Column("source_id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
    )
    op.create_index("ix_ga_1h_comment_receipts_task_id", "ga_1h_comment_receipts", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_ga_1h_comment_receipts_task_id", table_name="ga_1h_comment_receipts")
    op.drop_table("ga_1h_comment_receipts")
