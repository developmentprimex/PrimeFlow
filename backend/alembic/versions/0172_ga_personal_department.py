"""Add the GA PERSONAL department; private module access remains separate."""
from alembic import op

revision = "0172_ga_personal_department"
down_revision = "0171_ga_personal"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO departments (id, name, code, realization_mode, created_at)
        VALUES ('b7f8125a-00d5-4d7a-962c-bfb495416eef', 'GA PERSONAL', 'GAP', 'MANUAL', now())
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade():
    # Retain organizational data: users may already be assigned to this row.
    pass
