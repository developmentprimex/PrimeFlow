"""Allow paused tasks originating from GA notes."""

import sqlalchemy as sa
from alembic import op

revision = "0203_allow_paused_note_tasks"
down_revision = "0202_merge_mail_comment_heads"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_tasks_ga_note_status_valid"


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("resumed_from_pause", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_constraint(CONSTRAINT, "tasks", type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "tasks",
        "ga_note_origin_id IS NULL OR status IN ('TODO', 'IN_PROGRESS', 'PAUSED', 'DONE')",
    )


def downgrade() -> None:
    op.execute("UPDATE tasks SET status = 'IN_PROGRESS' WHERE status = 'PAUSED'")
    op.execute(
        "UPDATE task_daily_progress SET daily_status = 'IN_PROGRESS' WHERE daily_status = 'PAUSED'"
    )
    op.drop_constraint(CONSTRAINT, "tasks", type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "tasks",
        "ga_note_origin_id IS NULL OR status IN ('TODO', 'IN_PROGRESS', 'DONE')",
    )
    op.drop_column("tasks", "resumed_from_pause")
