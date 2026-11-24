"""Merge the paused note tasks and M1 symbol comment migrations."""

revision = "0204_merge_pause_symbol_comments"
down_revision = ("0203_allow_paused_note_tasks", "0203_task_symbol_comment_events")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
