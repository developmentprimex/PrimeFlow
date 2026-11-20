"""Restore the task-plan feedback revision already applied in production."""

from alembic import op
import sqlalchemy as sa


revision = "0196_task_plan_feedback"
down_revision = "0195_ga_discord_mentions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_plan_feedback",
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("continuation", sa.String(length=2), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("target_date", "task_id", "user_id", name="pk_task_plan_feedback"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_task_plan_feedback_task_id_tasks",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_task_plan_feedback_user_id_users",
                                ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("task_plan_feedback")
