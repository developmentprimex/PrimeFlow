"""Store Development M1 reorganization answers by report date."""

import sqlalchemy as sa
from alembic import op


revision = "0219_dev_m1_reorganization"
down_revision = "0218_weekly_planning_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_m1_reorganization",
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("development_m1_reorganization")
