"""Add informational repetitive flag to system task templates."""

from alembic import op

revision = "0165_system_task_is_repetitive"
down_revision = "0164_project_is_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE system_task_templates "
        "ADD COLUMN IF NOT EXISTS is_repetitive BOOLEAN DEFAULT false NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("system_task_templates", "is_repetitive")
