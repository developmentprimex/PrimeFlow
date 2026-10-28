"""Private household module; contains no seed identities or household data."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import Text

revision = "0171_ga_personal"
down_revision = "0170_discord_one_h_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS ga_personal")
    op.execute("REVOKE ALL ON SCHEMA ga_personal FROM PUBLIC")
    op.create_table('spaces',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('password_version', sa.Integer(), nullable=False),
    sa.Column('config', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_spaces')),
    sa.UniqueConstraint('key', name=op.f('uq_spaces_key')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('unlock_throttles',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_unlock_throttles')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('import_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('dataset_hash', sa.String(length=64), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=False),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_import_runs_actor_id_users')),
    sa.ForeignKeyConstraint(['space_id'], ['ga_personal.spaces.id'], name=op.f('fk_import_runs_space_id_spaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_runs')),
    sa.UniqueConstraint('space_id', 'dataset_hash', name=op.f('uq_import_runs_space_id')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('memberships',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('person_key', sa.String(length=20), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.CheckConstraint("person_key IN ('mrika','lirza','rrita','gane')", name=op.f('ck_memberships_family_person')),
    sa.ForeignKeyConstraint(['space_id'], ['ga_personal.spaces.id'], name=op.f('fk_memberships_space_id_spaces')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships')),
    sa.UniqueConstraint('space_id', 'person_key', name='uq_ga_member_person'),
    sa.UniqueConstraint('space_id', 'user_id', name='uq_ga_member_user'),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('task_templates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.String(length=100), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('definition', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('import_hash', sa.String(length=64), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_task_templates_created_by_users')),
    sa.ForeignKeyConstraint(['space_id'], ['ga_personal.spaces.id'], name=op.f('fk_task_templates_space_id_spaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_templates')),
    sa.UniqueConstraint('space_id', 'source_id', name=op.f('uq_task_templates_space_id')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('unlock_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('login_session_id', sa.String(length=64), nullable=False),
    sa.Column('password_version', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['space_id'], ['ga_personal.spaces.id'], name=op.f('fk_unlock_sessions_space_id_spaces')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_unlock_sessions_user_id_users')),
    sa.PrimaryKeyConstraint('token_hash', name=op.f('pk_unlock_sessions')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('occurrences',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('template_id', sa.Uuid(), nullable=False),
    sa.Column('period_key', sa.String(length=64), nullable=False),
    sa.Column('assignment_key', sa.String(length=100), nullable=False),
    sa.Column('local_date', sa.String(length=10), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('snapshot', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending','acknowledged','in_progress','needs_help','rescheduled','done','cancelled')", name=op.f('ck_occurrences_occurrence_status')),
    sa.ForeignKeyConstraint(['space_id'], ['ga_personal.spaces.id'], name=op.f('fk_occurrences_space_id_spaces')),
    sa.ForeignKeyConstraint(['template_id'], ['ga_personal.task_templates.id'], name=op.f('fk_occurrences_template_id_task_templates')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_occurrences')),
    sa.UniqueConstraint('space_id', 'template_id', 'period_key', 'assignment_key', name=op.f('uq_occurrences_space_id')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('reminder_deliveries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('occurrence_id', sa.Uuid(), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.ForeignKeyConstraint(['occurrence_id'], ['ga_personal.occurrences.id'], name=op.f('fk_reminder_deliveries_occurrence_id_occurrences')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reminder_deliveries')),
    sa.UniqueConstraint('occurrence_id', 'channel', 'sequence', name=op.f('uq_reminder_deliveries_occurrence_id')),
    schema='ga_personal', if_not_exists=True
    )
    op.create_table('task_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('space_id', sa.Uuid(), nullable=False),
    sa.Column('occurrence_id', sa.Uuid(), nullable=True),
    sa.Column('actor_id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.String(length=100), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_task_events_actor_id_users')),
    sa.ForeignKeyConstraint(['occurrence_id'], ['ga_personal.occurrences.id'], name=op.f('fk_task_events_occurrence_id_occurrences')),
    sa.ForeignKeyConstraint(['space_id'], ['ga_personal.spaces.id'], name=op.f('fk_task_events_space_id_spaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_events')),
    sa.UniqueConstraint('space_id', 'request_id', name=op.f('uq_task_events_space_id')),
    schema='ga_personal', if_not_exists=True
    )
    for table, columns in {
        "import_runs": ["space_id"], "memberships": ["space_id", "user_id"],
        "task_templates": ["space_id"], "unlock_sessions": ["space_id", "user_id"],
        "occurrences": ["space_id", "template_id", "local_date"],
        "task_events": ["space_id"], "reminder_deliveries": ["occurrence_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_ga_personal_{table}_{column}", table, [column], schema="ga_personal", if_not_exists=True)


def downgrade():
    op.drop_table('task_events', schema="ga_personal")
    op.drop_table('reminder_deliveries', schema="ga_personal")
    op.drop_table('occurrences', schema="ga_personal")
    op.drop_table('unlock_sessions', schema="ga_personal")
    op.drop_table('task_templates', schema="ga_personal")
    op.drop_table('memberships', schema="ga_personal")
    op.drop_table('import_runs', schema="ga_personal")
    op.drop_table('unlock_throttles', schema="ga_personal")
    op.drop_table('spaces', schema="ga_personal")
    op.execute("DROP SCHEMA ga_personal")
