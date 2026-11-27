"""Allow the weekly planning reason in daily realization evidence."""
from alembic import op

revision = "0218_weekly_planning_reason"
down_revision = "0217_weekly_planner_short"
branch_labels = None
depends_on = None

TABLE = "task_daily_rlz_states"
CONSTRAINT = "ck_task_daily_rlz_states_ck_task_daily_rlz_state_reason_code"
PREVIOUS_REASONS = (
    "'TOOK_LONGER','OTHER_URGENCY','WAITING_CLIENT','PRIORITY_CHANGE','TECHNICAL_PROBLEM',"
    "'MISSING_INFORMATION','REQUEST_CHANGE','NEW_REQUESTS','ABSENCE','OTHER','PV'"
)


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), TABLE,
        f"reason_code IS NULL OR reason_code IN ({PREVIOUS_REASONS},'WEEKLY_PLANNING')",
    )


def downgrade() -> None:
    op.execute("UPDATE task_daily_rlz_states SET reason_code = 'OTHER' WHERE reason_code = 'WEEKLY_PLANNING'")
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, f"reason_code IS NULL OR reason_code IN ({PREVIOUS_REASONS})")
