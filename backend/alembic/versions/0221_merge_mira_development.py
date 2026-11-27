"""Merge the Mira title and Development report migration branches."""


revision = "0221_merge_mira_development"
down_revision = ("0219_mira_meeting_title", "0220_dev_reorganization_slots")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
