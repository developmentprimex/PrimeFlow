"""Merge the INFO PX authorization and marker comment migration branches."""

revision = "0202_merge_mail_comment_heads"
down_revision = ("0201_microsoft_mail_tokens", "0201_marker_comment_created_at")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
