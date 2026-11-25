"""Allow PV as a daily realization reason."""
from alembic import op

revision = "0210_daily_rlz_reason_pv"
down_revision = "0209_discord_delivery_comments"
branch_labels = None
depends_on = None

TABLE = "task_daily_rlz_states"
CONSTRAINT = "ck_task_daily_rlz_states_ck_task_daily_rlz_state_reason_code"
REASONS = (
    "'TOOK_LONGER','OTHER_URGENCY','WAITING_CLIENT','PRIORITY_CHANGE','TECHNICAL_PROBLEM',"
    "'MISSING_INFORMATION','REQUEST_CHANGE','NEW_REQUESTS','ABSENCE','OTHER'"
)


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, f"reason_code IS NULL OR reason_code IN ({REASONS},'PV')")


def downgrade() -> None:
    op.execute("UPDATE task_daily_rlz_states SET reason_code = 'OTHER' WHERE reason_code = 'PV'")
    op.drop_constraint(op.f(CONSTRAINT), TABLE, type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), TABLE, f"reason_code IS NULL OR reason_code IN ({REASONS})")
