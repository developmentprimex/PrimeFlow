"""Merge daily RLZ and iPhone reminder migration branches."""

revision = "0214_merge_rlz_iphone_heads"
down_revision = ("0210_daily_rlz_reason_pv", "0213_iphone_reminder_completion")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
