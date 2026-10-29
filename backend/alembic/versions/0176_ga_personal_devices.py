"""Revocable tablet credentials restricted to the private household module."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0176_ga_personal_devices"
down_revision = "0175_merge_discord_ga_personal"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("authorized_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("device_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["space_id"], ["ga_personal.spaces.id"]),
        sa.ForeignKeyConstraint(["authorized_by"], ["ga_personal.memberships.id"]),
        sa.UniqueConstraint("token_hash"),
        schema="ga_personal", if_not_exists=True)
    op.create_index("ix_ga_personal_devices_space_id", "devices", ["space_id"],
                    schema="ga_personal", if_not_exists=True)
    op.create_table("device_ops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("op_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["space_id"], ["ga_personal.spaces.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["ga_personal.devices.id"]),
        sa.UniqueConstraint("space_id", "op_id"), schema="ga_personal", if_not_exists=True)
    op.create_index("ix_ga_personal_device_ops_space_id", "device_ops", ["space_id"], schema="ga_personal", if_not_exists=True)
    op.create_table("device_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("client_at", sa.BigInteger(), nullable=False),
        sa.Column("op_id", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["space_id"], ["ga_personal.spaces.id"]),
        sa.UniqueConstraint("space_id", "kind", "key"), schema="ga_personal", if_not_exists=True)
    op.create_index("ix_ga_personal_device_records_space_id", "device_records", ["space_id"], schema="ga_personal", if_not_exists=True)


def downgrade():
    # Preserve device/revocation history on rollback.
    pass
