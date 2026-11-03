"""Task/day penalty confirmations by the two designated reviewers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0183_rlz_task_confirmations"
down_revision = "0182_recording_project"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "realization_task_confirmations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("evidence_key", sa.String(64), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "user_id", "day_date", name="uq_rlz_confirmation_task_user_day"),
    )
    op.create_index("ix_realization_task_confirmations_user_id", "realization_task_confirmations", ["user_id"])
    op.create_index("ix_realization_task_confirmations_day_date", "realization_task_confirmations", ["day_date"])


def downgrade():
    op.drop_table("realization_task_confirmations")
