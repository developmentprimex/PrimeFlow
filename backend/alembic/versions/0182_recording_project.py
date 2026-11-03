"""Link meeting recordings to projects."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0182_recording_project"
down_revision = "0181_mira_host_test_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meeting_recordings", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_recording_project", "meeting_recordings", "projects", ["project_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_meeting_recordings_project_id", "meeting_recordings", ["project_id"])


def downgrade():
    op.drop_index("ix_meeting_recordings_project_id", table_name="meeting_recordings")
    op.drop_constraint("fk_recording_project", "meeting_recordings", type_="foreignkey")
    op.drop_column("meeting_recordings", "project_id")
