"""Allow the 1H and AI Agent recorders to run concurrently in the same server."""
from alembic import op
import sqlalchemy as sa

revision = '0174_discord_separate_recorders'
down_revision = '0173_merge_mira_ga_personal'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('discord_voice_meetings', sa.Column('recorder', sa.String(16), nullable=False, server_default='primary'))
    op.create_index('uq_discord_voice_active_recorder', 'discord_voice_meetings', ['guild_id', 'recorder'],
        unique=True, postgresql_where=sa.text("status IN ('STARTING','LISTENING')"))
    op.drop_index('uq_discord_voice_active_guild', table_name='discord_voice_meetings')


def downgrade():
    # Recreating the old uniqueness rule fails safely if both bots are active.
    op.create_index('uq_discord_voice_active_guild', 'discord_voice_meetings', ['guild_id'],
        unique=True, postgresql_where=sa.text("status IN ('STARTING','LISTENING')"))
    op.drop_index('uq_discord_voice_active_recorder', table_name='discord_voice_meetings')
    op.drop_column('discord_voice_meetings', 'recorder')
