from __future__ import annotations

from datetime import datetime, timezone
from pydantic import AwareDatetime
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.15.118:3000",
    "http://192.168.15.117:3000",
    "http://primeflow.primexeu.com",
    "https://primeflow.primexeu.com",
    "https://www.primeflow.primexeu.com",
]
DEFAULT_CORS_ORIGINS_CSV = ",".join(DEFAULT_CORS_ORIGINS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True,  extra="ignore")

    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    MEETING_RECORDINGS_ROOT: str = "uploads/meeting-recordings"
    MEETING_RECORDINGS_FILES_ENABLED: bool = True
    # Fixed activation boundary; restarts must not move it or backfill old media.
    MEETING_RECORDINGS_FILES_FROM: AwareDatetime = datetime(2026, 10, 23, 9, 55, 36, tzinfo=timezone.utc)
    MEETING_RECORDINGS_FILES_SUBDIR: str = (
        "10_ZHVILLIM/04_PROJECTS/26_PRIMEFLOW/08_TAKIMET"
    )
    MEETING_RECORDINGS_MAX_CHUNK_BYTES: int = 32 * 1024 * 1024
    MEETING_RECORDINGS_MAX_SESSION_BYTES: int = 20 * 1024 * 1024 * 1024
    MEETING_RECORDINGS_MAX_DURATION_SECONDS: int = 12 * 60 * 60
    MEETING_RECORDINGS_MAX_OPEN_SESSIONS: int = 3
    MEETING_RECORDINGS_FFMPEG: str = "ffmpeg"
    MEETING_RECORDINGS_FFPROBE: str = "ffprobe"
    RECORDING_ANALYSIS_ENABLED: bool = True
    RECORDING_TIMING_ENABLED: bool = False
    RECORDING_TIMING_PYTHON: str = ""
    RECORDING_TIMING_MODEL_CACHE: str = "private-data/alignment-pilot/model-cache"
    RECORDING_ANALYSIS_MODEL: str = "gpt-6-luna"
    RECORDING_TRANSCRIBE_MODEL: str = "gpt-transcribe"
    # Sends the chosen language code to the transcription API; disable if a model rejects it.
    RECORDING_TRANSCRIBE_LANGUAGE_HINT: bool = True
    # Product and client terms added to transcription prompts, next to staff and department names.
    RECORDING_TRANSCRIPTION_VOCABULARY: str = "PrimeFlow, PrimEx, PX, Mendex, MX, GA, PX Notes, Mira"
    REDIS_ENABLED: bool = True
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_TIMEZONE: str = "Europe/Budapest"
    GA_PERSONAL_ENABLED: bool = False
    GA_PERSONAL_UNLOCK_MINUTES: int = 60
    MEETING_REMINDER_SCHEDULER_ENABLED: bool = True
    MEETING_REMINDER_POLL_SECONDS: int = 30
    SYSTEM_TASK_SCHEDULER_ENABLED: bool = True
    # Disable API-owned report delivery loops when running a local API.
    REPORT_SCHEDULERS_ENABLED: bool = True
    TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED: bool = True
    TODAY_PRINT_REPORT_SCHEDULER_ENABLED: bool = True
    PRIMEFLOW_API_BASE_URL: str = "http://127.0.0.1:8000"
    PRIMEFLOW_EMAIL: str | None = None
    PRIMEFLOW_PASSWORD: str | None = None
    PRIMEFLOW_ACCESS_TOKEN: str | None = None
    SYSTEM_TASK_SCHEDULER_HOUR: int = 6
    SYSTEM_TASK_SCHEDULER_MINUTE: int = 0
    SYSTEM_TASK_SCHEDULER_DAY_OF_WEEK: str = "fri"
    SYSTEM_TASK_GENERATE_AHEAD_DAYS: int = 7
    SYSTEM_TASK_DAILY_RECONCILE_HOUR: int = 6
    SYSTEM_TASK_DAILY_RECONCILE_MINUTE: int = 5
    WEEKLY_PLANNING_AUDIT_ENABLED: bool = True
    WEEKLY_PLANNING_AUDIT_TIMEZONE: str = "Europe/Tirane"
    WEEKLY_PLANNING_AUDIT_RECIPIENTS: str = (
        "130primex.eu@gmail.com,info@primexeu.com,ga@primexeu.com"
    )
    # Exact user IDs, usernames, or email addresses that are intentionally
    # excluded from the report. Active accounts are reportable by default.
    WEEKLY_PLANNING_AUDIT_EXCLUDED_ACCOUNTS: str = ""
    STD_FEEDBACK_API_BASE_URL: str = "https://std.primexeu.com/api/integrations/primeflow/v1"
    STD_FEEDBACK_API_TOKEN: str | None = None
    STD_FEEDBACK_SYNC_ENABLED: bool = True
    STD_FEEDBACK_SYNC_INTERVAL_MINUTES: int = 5
    STD_FEEDBACK_EXTERNAL_DOMAINS: str = "staudmoebel.de"
    STD_FEEDBACK_PROJECT_KEYWORDS: str = "STD"
    STD_FEEDBACK_REQUEST_TIMEOUT_SECONDS: int = 30
    STD_FEEDBACK_REQUEST_RETRIES: int = 3

    # Legacy names remain readable during a rolling server deployment.
    STD_PRIMEFLOW_API_BASE_URL: str | None = None
    STD_PRIMEFLOW_API_TOKEN: str | None = None
    REPORT_STORAGE_DIR: str = "uploads/reports"
    REPORT_RETENTION_DAYS: int = 90

     # Add these three lines:
    ADMIN_EMAIL: str | None = None
    ADMIN_USERNAME: str | None = None
    ADMIN_PASSWORD: str | None = None

    JWT_SECRET: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    AUTH_COOKIE_SECURE: bool | None = None
    AUTH_COOKIE_SAMESITE: str | None = None
    AUTH_COOKIE_DOMAIN: str | None = None

    CORS_ORIGINS: str = DEFAULT_CORS_ORIGINS_CSV

    # Microsoft Teams/Graph API Configuration
    MS_CLIENT_ID: str | None = None
    MS_CLIENT_SECRET: str | None = None
    MS_TENANT_ID: str | None = None
    MS_REDIRECT_URI: str | None = None
    MS_ORGANIZER_EMAIL: str = "info@primexeu.com"
    MS_CALENDAR_SYNC_ENABLED: bool = True
    MS_CALENDAR_SYNC_INTERVAL_MINUTES: int = 5
    MS_CALENDAR_SYNC_PAST_DAYS: int = 0
    MS_CALENDAR_SYNC_FUTURE_DAYS: int = 14
    MS_CALENDAR_DEFAULT_DEPARTMENT_CODE: str = "DEV"

    FRONTEND_URL: str = "http://localhost:3000"
    FILE_ACCESS_API_BASE_URL: str = "http://192.168.10.8:5080"
    FILE_ACCESS_API_KEY: str | None = "XeiMrYgncS2EkpQZ4tTqs73RfIU8Cub91oAwB5zPxyjOJDVd"
    FILES_SERVER_STORAGE_ROOT: str = r"F:\FILES"
    FILES_SERVER_PATH_ALIASES: str = r"Y:;Z:;F:\FILES;\\192.168.10.8\FILES"

    GA_NOTES_UPLOAD_DIR: str = "uploads/ga-notes"
    PLAN_NOTES_UPLOAD_DIR: str = "uploads/plan_notes"
    GA_NOTES_MAX_FILES: int = 20
    GA_NOTES_MAX_FILE_MB: int = 25

    OPENAI_API_KEY: str | None = None
    VOICE_ASSISTANT_MODEL: str = "gpt-realtime-2.1"
    VOICE_ASSISTANT_VOICE: str = "marin"
    # Opt-in Discord worker; never starts or sends messages from the API process.
    DISCORD_ASSISTANT_ENABLED: bool = False
    DISCORD_MEETING_NOTES_ENABLED: bool = False
    DISCORD_VOICE_NODE_BINARY: str = "node"
    DISCORD_BRIDGE_SECRET: str | None = None
    DISCORD_BOT_TOKEN: str | None = None
    DISCORD_GUILD_ID: str | None = None
    DISCORD_CATEGORY_ID: str | None = None
    DISCORD_MEETING_VOICE_CHANNEL_ID: str | None = None
    # Voice channel of the 1H slot meetings; slot reminders link to it.
    DISCORD_1H_VOICE_CHANNEL_ID: str | None = "1493866120338477119"
    # Mira joins the 1H channel on weekdays at these local times (2 minutes before
    # each slot) and saves the notes to PX Notes as this organizer. Empty disables it.
    DISCORD_1H_AUTO_JOIN_TIMES: str = "09:58,10:58,11:48,14:18,15:58"
    DISCORD_1H_AUTO_OWNER_DISCORD_ID: str | None = "1425896175839608933"
    DISCORD_MESSAGE_CONTENT_ENABLED: bool = False
    DISCORD_AI_MODEL: str = "gpt-5.4-mini"
    DISCORD_MEETING_TRANSCRIBE_MODEL: str = "gpt-transcribe"
    # Mira's living memory register of meetings; off keeps notes exactly as before.
    MIRA_MEMORY_ENABLED: bool = False
    MIRA_MEMORY_QUIET_DAYS: int = 30
    MIRA_MEMORY_RECENT_CLOSED_DAYS: int = 14
    MIRA_MEMORY_MAX_ATTEMPTS: int = 5
    MIRA_MEMORY_WAIT_MINUTES: int = 15
    MIRA_MEMORY_CONTEXT_CHARS: int = 40000
    # Mira Host (test): a second Discord bot that speaks and leads the 1H meetings.
    # Off by default; even when on it only runs after /mira mbaj-takimet.
    MIRA_HOST_ENABLED: bool = False
    MIRA_HOST_BOT_TOKEN: str | None = None
    MIRA_HOST_PRE_BRIEF_MINUTES: int = 5
    MIRA_HOST_GA_CALL_MINUTES: int = 2
    # Mira joins this early (silent), so a failed connection is retried before she must talk.
    MIRA_HOST_CONNECT_MINUTES: int = 6
    MIRA_HOST_VOICE: str = "marin"
    MIRA_HOST_SPEED: float = 1.05
    # minimal/low/medium/high/xhigh; higher answers better but later. Empty = the model's default.
    MIRA_HOST_REASONING_EFFORT: str = "low"
    DISCORD_AI_TIMEOUT_SECONDS: int = 45
    DISCORD_AGENT_MODEL: str = "gpt-6-luna"
    SKILLS_AI_MODEL: str = "gpt-5.4-nano"
    SKILLS_AI_TIMEOUT_SECONDS: int = 20
    SPEECH_TRANSCRIBE_MODEL: str = "whisper-1"
    SPEECH_ALBANIAN_TRANSCRIBE_MODEL: str = "gpt-4o-transcribe"
    SPEECH_MAX_FILE_MB: int = 20
    SPEECH_ALLOWED_MIME: str | None = None
    REALIZATION_TIMEZONE: str = "Europe/Tirane"
    REALIZATION_DAILY_ENABLED: bool = True
    REALIZATION_DAILY_HOUR: int = 16
    REALIZATION_DAILY_MINUTE: int = 20
    REALIZATION_BASELINE_HOUR: int = 7
    REALIZATION_BASELINE_MINUTE: int = 0
    REALIZATION_AI_ENABLED: bool = False
    REALIZATION_AI_MODEL: str = "gpt-5.2"
    REALIZATION_AI_TIMEOUT_SECONDS: int = 45
    REALIZATION_DAILY_REPORT_AI_ENABLED: bool = False
    REALIZATION_DAILY_REPORT_AI_MODEL: str = "gpt-5.4-mini"
    REALIZATION_DAILY_REPORT_AI_TIMEOUT_SECONDS: int = 30
    WEEKLY_PLANNING_AUDIT_AI_ENABLED: bool = True
    WEEKLY_PLANNING_AUDIT_AI_MODEL: str = "gpt-5.2"
    WEEKLY_PLANNING_AUDIT_AI_TIMEOUT_SECONDS: int = 90
    PX_JAV_WEEKLY_REPORT_ENABLED: bool = True
    PX_JAV_WEEKLY_REPORT_TIMEZONE: str = "Europe/Tirane"
    PX_JAV_WEEKLY_REPORT_RECIPIENT: str = "334primex.eu@gmail.com"
    EMAIL_HOST: str = "smtp.gmail.com"
    EMAIL_PORT: int = 587
    EMAIL_USER: str | None = None
    EMAIL_PASSWORD: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        env_origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        merged: list[str] = []
        seen: set[str] = set()
        for origin in [*DEFAULT_CORS_ORIGINS, *env_origins]:
            if origin in seen:
                continue
            seen.add(origin)
            merged.append(origin)
        return merged

    @property
    def auth_cookie_secure(self) -> bool:
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.FRONTEND_URL.startswith("https://") or any(
            origin.startswith("https://") for origin in self.cors_origin_list
        )

    @property
    def auth_cookie_samesite(self) -> str:
        value = (self.AUTH_COOKIE_SAMESITE or "").strip().lower()
        if value not in {"lax", "strict", "none"}:
            return "none" if self.auth_cookie_secure else "lax"
        if value == "none" and not self.auth_cookie_secure:
            return "lax"
        return value

    @property
    def std_feedback_external_domain_list(self) -> list[str]:
        return [
            value.strip().lower().lstrip("@")
            for value in self.STD_FEEDBACK_EXTERNAL_DOMAINS.split(",")
            if value.strip()
        ]

    @property
    def std_feedback_project_keyword_list(self) -> list[str]:
        return [
            value.strip().lower()
            for value in self.STD_FEEDBACK_PROJECT_KEYWORDS.split(",")
            if value.strip()
        ]


settings = Settings()


