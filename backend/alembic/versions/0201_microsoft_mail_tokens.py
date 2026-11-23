"""Store a separate encrypted Microsoft authorization for INFO PX mail."""

import sqlalchemy as sa
from alembic import op

revision = "0201_microsoft_mail_tokens"
down_revision = "0200_discord_ga_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "microsoft_mail_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("microsoft_mail_tokens")
