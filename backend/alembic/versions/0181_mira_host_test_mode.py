"""Allow repeatable Mira Host rehearsals without consuming the real meeting slot."""
from alembic import op
import sqlalchemy as sa

revision = "0181_mira_host_test_mode"
down_revision = "0180_kujtesa_family"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mira_1h_meetings", sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint("uq_mira_1h_meeting_slot", "mira_1h_meetings", type_="unique")
    op.create_index("uq_mira_1h_meeting_slot", "mira_1h_meetings", ["meeting_date", "slot"], unique=True,
                    postgresql_where=sa.text("is_test IS FALSE"))


def downgrade():
    # Never silently delete rehearsals to restore the older one-row-per-slot schema.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM mira_1h_meetings WHERE is_test)")).scalar():
        raise RuntimeError("Export and remove test meetings explicitly before downgrading Mira Host test mode.")
    op.drop_index("uq_mira_1h_meeting_slot", table_name="mira_1h_meetings")
    op.create_unique_constraint("uq_mira_1h_meeting_slot", "mira_1h_meetings", ["meeting_date", "slot"])
    op.drop_column("mira_1h_meetings", "is_test")
