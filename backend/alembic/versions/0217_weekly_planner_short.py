"""Store Weekly Planner Short decisions and comments by week."""

import sqlalchemy as sa
from alembic import op

revision = "0217_weekly_planner_short"
down_revision = "0216_meeting_all_participants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_planner_short_points",
        sa.Column("week_start", sa.Date(), primary_key=True),
        sa.Column("point", sa.Integer(), primary_key=True),
        sa.Column("decision", sa.String(5)),
        sa.Column("owner", sa.String(120)),
        sa.Column("due_date", sa.Date()),
    )
    op.create_table(
        "weekly_planner_short_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("point", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_weekly_planner_short_comments_week", "weekly_planner_short_comments", ["week_start"])


def downgrade() -> None:
    op.drop_table("weekly_planner_short_comments")
    op.drop_table("weekly_planner_short_points")
