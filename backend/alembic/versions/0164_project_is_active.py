"""Add independent project activity flag; existing projects remain active."""
from alembic import op
import sqlalchemy as sa

revision = "0164_project_is_active"
down_revision = "0163_discord_m2_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("projects", "is_active")
