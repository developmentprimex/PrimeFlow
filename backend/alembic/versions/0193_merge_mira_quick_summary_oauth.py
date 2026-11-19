"""Join the Notetaker and MCP OAuth migration branches."""

revision = "0193_merge_mira_quick_oauth"
down_revision = ("0192_mira_quick_summary", "0192_mcp_assistant_oauth")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
