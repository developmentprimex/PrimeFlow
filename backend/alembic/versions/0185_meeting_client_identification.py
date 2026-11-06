"""Optional client name for meeting identification, independent of projects."""
from alembic import op
import sqlalchemy as sa

revision = "0185_meeting_client_label"
down_revision = "0184_meeting_notes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meetings", sa.Column("client_name", sa.String(length=200), nullable=True))


def downgrade():
    op.drop_column("meetings", "client_name")
