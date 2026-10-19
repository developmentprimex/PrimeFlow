from __future__ import annotations

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
    REDIS_ENABLED: bool = True
    REDIS_URL: str = "redis://localhost:6379/0"
    APP_TIMEZONE: str = "Europe/Budapest"
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
    FILES_SERVER_PATH_ALIASES: str = r"Y:;F:\FILES;\\192.168.10.8\FILES"

    GA_NOTES_UPLOAD_DIR: str = "uploads/ga-notes"
    PLAN_NOTES_UPLOAD_DIR: str = "uploads/plan_notes"
    GA_NOTES_MAX_FILES: int = 20
    GA_NOTES_MAX_FILE_MB: int = 25

    OPENAI_API_KEY: str | None = None
    # Opt-in Discord worker; never starts or sends messages from the API process.
    DISCORD_ASSISTANT_ENABLED: bool = False
    DISCORD_BRIDGE_SECRET: str | None = None
    DISCORD_BOT_TOKEN: str | None = None
    DISCORD_GUILD_ID: str | None = None
    DISCORD_CATEGORY_ID: str | None = None
    DISCORD_MEETING_VOICE_CHANNEL_ID: str | None = None
    # Voice channel of the 1H slot meetings; slot reminders link to it.
    DISCORD_1H_VOICE_CHANNEL_ID: str | None = "1493866120338477119"
    DISCORD_MESSAGE_CONTENT_ENABLED: bool = False
    DISCORD_AI_MODEL: str = "gpt-5.4-mini"
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


