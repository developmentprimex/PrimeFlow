"""Silent Mira voice meetings and durable transcript segments."""
from alembic import op

revision = "0152_discord_voice_meetings"
down_revision = "0151_discord_meeting_alerts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE discord_voice_meetings (
	id UUID NOT NULL,
	link_id UUID NOT NULL,
	user_id UUID NOT NULL,
	department_id UUID,
	guild_id VARCHAR(32) NOT NULL,
	voice_channel_id VARCHAR(32) NOT NULL,
	private_channel_id VARCHAR(32) NOT NULL,
	request_id VARCHAR(32) NOT NULL,
	instance_id UUID NOT NULL,
	capture_token_hash VARCHAR(64) NOT NULL,
	title VARCHAR(200) NOT NULL,
	status VARCHAR(20) NOT NULL,
	partial BOOLEAN NOT NULL,
	error VARCHAR(500),
	expected_segments INTEGER,
	stop_authorized BOOLEAN NOT NULL,
	draft_text TEXT,
	summary_progress JSONB,
	saved_note_id UUID,
	saved_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	stopped_at TIMESTAMP WITH TIME ZONE,
	lease_token UUID,
	lease_until TIMESTAMP WITH TIME ZONE,
	delivery_token UUID,
	delivery_until TIMESTAMP WITH TIME ZONE,
	delivered_at TIMESTAMP WITH TIME ZONE,
	message_ids JSONB,
	CONSTRAINT pk_discord_voice_meetings PRIMARY KEY (id),
	CONSTRAINT fk_discord_voice_meetings_link_id_discord_links FOREIGN KEY(link_id) REFERENCES discord_links (id) ON DELETE CASCADE,
	CONSTRAINT fk_discord_voice_meetings_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	CONSTRAINT fk_discord_voice_meetings_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id),
	CONSTRAINT uq_discord_voice_meetings_request_id UNIQUE (request_id),
	CONSTRAINT fk_discord_voice_meetings_saved_note_id_ga_notes FOREIGN KEY(saved_note_id) REFERENCES ga_notes (id) ON DELETE SET NULL
)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_discord_voice_active_guild ON discord_voice_meetings (guild_id) WHERE status IN ('STARTING','LISTENING')
""")
    op.execute("""
CREATE TABLE discord_voice_segments (
	id UUID NOT NULL,
	session_id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	speaker_id VARCHAR(32) NOT NULL,
	speaker_name VARCHAR(100) NOT NULL,
	start_ms INTEGER NOT NULL,
	end_ms INTEGER NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	status VARCHAR(20) NOT NULL,
	transcript TEXT,
	error VARCHAR(100),
	lease_token UUID,
	lease_until TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_discord_voice_segments PRIMARY KEY (id),
	CONSTRAINT uq_voice_segment_sequence UNIQUE (session_id, sequence),
	CONSTRAINT fk_discord_voice_segments_session_id_discord_voice_meetings FOREIGN KEY(session_id) REFERENCES discord_voice_meetings (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE INDEX ix_discord_voice_segments_session_id ON discord_voice_segments (session_id)
""")


def downgrade():
    op.drop_table("discord_voice_segments")
    op.drop_table("discord_voice_meetings")
