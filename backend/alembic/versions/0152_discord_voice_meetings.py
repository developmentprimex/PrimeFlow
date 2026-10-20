"""Silent Mira voice meetings and durable transcript segments."""
from alembic import op

revision="0152_discord_voice_meetings"
down_revision="0151_discord_meeting_alerts"
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE discord_voice_meetings (\n\tid UUID NOT NULL, \n\tlink_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tdepartment_id UUID, \n\tguild_id VARCHAR(32) NOT NULL, \n\tvoice_channel_id VARCHAR(32) NOT NULL, \n\tprivate_channel_id VARCHAR(32) NOT NULL, \n\trequest_id VARCHAR(32) NOT NULL, \n\tinstance_id UUID NOT NULL, \n\tcapture_token_hash VARCHAR(64) NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tpartial BOOLEAN NOT NULL, \n\terror VARCHAR(500), \n\texpected_segments INTEGER, \n\tstop_authorized BOOLEAN NOT NULL, \n\tdraft_text TEXT, \n\tsaved_note_id UUID, \n\tsaved_at TIMESTAMP WITH TIME ZONE, \n\theartbeat_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tstopped_at TIMESTAMP WITH TIME ZONE, \n\tlease_token UUID, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tdelivery_token UUID, \n\tdelivery_until TIMESTAMP WITH TIME ZONE, \n\tdelivered_at TIMESTAMP WITH TIME ZONE, \n\tmessage_ids JSONB, \n\tCONSTRAINT pk_discord_voice_meetings PRIMARY KEY (id), \n\tCONSTRAINT fk_discord_voice_meetings_link_id_discord_links FOREIGN KEY(link_id) REFERENCES discord_links (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_discord_voice_meetings_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_discord_voice_meetings_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), \n\tCONSTRAINT uq_discord_voice_meetings_request_id UNIQUE (request_id), \n\tCONSTRAINT fk_discord_voice_meetings_saved_note_id_ga_notes FOREIGN KEY(saved_note_id) REFERENCES ga_notes (id) ON DELETE SET NULL\n)\n\n')
    op.execute("CREATE UNIQUE INDEX uq_discord_voice_active_guild ON discord_voice_meetings (guild_id) WHERE status IN ('STARTING','LISTENING')")
    op.execute('\nCREATE TABLE discord_voice_segments (\n\tid UUID NOT NULL, \n\tsession_id UUID NOT NULL, \n\tsequence INTEGER NOT NULL, \n\tspeaker_id VARCHAR(32) NOT NULL, \n\tspeaker_name VARCHAR(100) NOT NULL, \n\tstart_ms INTEGER NOT NULL, \n\tend_ms INTEGER NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\ttranscript TEXT, \n\terror VARCHAR(100), \n\tlease_token UUID, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tCONSTRAINT pk_discord_voice_segments PRIMARY KEY (id), \n\tCONSTRAINT uq_voice_segment_sequence UNIQUE (session_id, sequence), \n\tCONSTRAINT fk_discord_voice_segments_session_id_discord_voice_meetings FOREIGN KEY(session_id) REFERENCES discord_voice_meetings (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_discord_voice_segments_session_id ON discord_voice_segments (session_id)')

def downgrade():
    op.drop_table("discord_voice_segments")
    op.drop_table("discord_voice_meetings")
