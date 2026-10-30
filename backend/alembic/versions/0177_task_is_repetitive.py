"""Add informational repetitive flag to ordinary tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0177_task_is_repetitive"
down_revision = "0176_ga_personal_devices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("is_repetitive", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tasks", "is_repetitive")
