"""Keep Development M1 and M2 reorganization answers separate."""

import sqlalchemy as sa
from alembic import op


revision = "0220_dev_reorganization_slots"
down_revision = "0219_dev_m1_reorganization"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "development_m2_reorganization",
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("development_m2_reorganization")
