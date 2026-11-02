"""Restore the deployed GA note repetitive flag revision."""
from alembic import op

revision = "0178_ga_note_is_repetitive"
down_revision = "0177_task_is_repetitive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some installations already have this column and revision stamp.
    op.execute(
        "ALTER TABLE ga_notes "
        "ADD COLUMN IF NOT EXISTS is_repetitive BOOLEAN DEFAULT false NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("ga_notes", "is_repetitive")
