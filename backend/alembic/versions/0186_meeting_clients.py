"""Reusable clients for identifying multiple meetings independently of projects."""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0186_meeting_clients"
down_revision = "0185_meeting_client_label"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meeting_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name_key", name="uq_meeting_clients_name_key"),
    )
    op.add_column("meetings", sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_meetings_client_id_meeting_clients", "meetings", "meeting_clients", ["client_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_meetings_client_id", "meetings", ["client_id"])

    bind = op.get_bind()
    names = bind.execute(sa.text("SELECT DISTINCT client_name FROM meetings WHERE client_name IS NOT NULL ORDER BY client_name")).scalars().all()
    clients = {}
    for old_name in names:
        name = " ".join(old_name.split())
        if not name:
            continue
        key = name.casefold()
        if key not in clients:
            client_id = uuid.uuid4()
            bind.execute(sa.text("INSERT INTO meeting_clients (id, name, name_key) VALUES (:id, :name, :key)"), {"id": client_id, "name": name, "key": key})
            clients[key] = (client_id, name)
        client_id, name = clients[key]
        bind.execute(sa.text("UPDATE meetings SET client_id = :id, client_name = :name WHERE client_name = :old"), {"id": client_id, "name": name, "old": old_name})


def downgrade():
    op.drop_index("ix_meetings_client_id", table_name="meetings")
    op.drop_constraint("fk_meetings_client_id_meeting_clients", "meetings", type_="foreignkey")
    op.drop_column("meetings", "client_id")
    op.drop_table("meeting_clients")
