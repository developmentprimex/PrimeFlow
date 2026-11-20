"""Store next-workday task responses from PrimeFlow."""

import sqlalchemy as sa
from alembic import op

revision = "0196_task_plan_feedback"
down_revision = "0195_ga_discord_mentions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_plan_feedback",
        sa.Column("target_date", sa.Date(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("continuation", sa.String(2)),
        sa.Column("comment", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("task_plan_feedback")
