"""Merge the deployed Mira Desktop and system task repetitive branches."""

revision = "0166_merge_mira_repetitive"
down_revision = ("0165_mira_desktop", "0165_system_task_is_repetitive")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
