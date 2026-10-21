const path = require("path");
const fs = require("fs");

const cwd = __dirname;
const pythonCandidate =
  process.env.PM2_PYTHON_PATH ||
  "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
const python = fs.existsSync(pythonCandidate)
  ? pythonCandidate
  : "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe";
const redisEnabled = (process.env.REDIS_ENABLED ?? "false").toLowerCase() === "true";
const redisUrl = process.env.REDIS_URL ?? "redis://127.0.0.1:6379/0";
const appTimezone = process.env.APP_TIMEZONE ?? "Europe/Budapest";

const sharedEnv = {
  REDIS_ENABLED: String(redisEnabled),
  REDIS_URL: redisUrl,
  APP_TIMEZONE: appTimezone,
  MEETING_REMINDER_SCHEDULER_ENABLED:
    process.env.MEETING_REMINDER_SCHEDULER_ENABLED ?? "true",
  MEETING_REMINDER_POLL_SECONDS:
    process.env.MEETING_REMINDER_POLL_SECONDS ?? "30",
  APP_BUILD_SHA: process.env.APP_BUILD_SHA ?? "unknown",
  WEEKLY_PLANNING_AUDIT_ENABLED: process.env.WEEKLY_PLANNING_AUDIT_ENABLED ?? "true",
  WEEKLY_PLANNING_AUDIT_TIMEZONE: process.env.WEEKLY_PLANNING_AUDIT_TIMEZONE ?? "Europe/Tirane",
  WEEKLY_PLANNING_AUDIT_RECIPIENTS:
    process.env.WEEKLY_PLANNING_AUDIT_RECIPIENTS ??
    "130primex.eu@gmail.com,info@primexeu.com,ga@primexeu.com",
  PX_JAV_WEEKLY_REPORT_ENABLED: process.env.PX_JAV_WEEKLY_REPORT_ENABLED ?? "true",
  PX_JAV_WEEKLY_REPORT_TIMEZONE:
    process.env.PX_JAV_WEEKLY_REPORT_TIMEZONE ?? "Europe/Tirane",
  PX_JAV_WEEKLY_REPORT_RECIPIENT:
    process.env.PX_JAV_WEEKLY_REPORT_RECIPIENT ?? "334primex.eu@gmail.com",
  REPORT_STORAGE_DIR: process.env.REPORT_STORAGE_DIR ?? "uploads/reports",
  REPORT_RETENTION_DAYS: process.env.REPORT_RETENTION_DAYS ?? "90",
  STD_FEEDBACK_API_BASE_URL:
    process.env.STD_FEEDBACK_API_BASE_URL ??
    "https://std.primexeu.com/api/integrations/primeflow/v1",
  STD_FEEDBACK_API_TOKEN: process.env.STD_FEEDBACK_API_TOKEN ?? "",
  STD_FEEDBACK_SYNC_ENABLED: process.env.STD_FEEDBACK_SYNC_ENABLED ?? "true",
  TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED:
    process.env.TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED ?? "true",
  TODAY_PRINT_REPORT_SCHEDULER_ENABLED:
    process.env.TODAY_PRINT_REPORT_SCHEDULER_ENABLED ?? "true",
  STD_FEEDBACK_SYNC_INTERVAL_MINUTES:
    process.env.STD_FEEDBACK_SYNC_INTERVAL_MINUTES ?? "5",
  STD_FEEDBACK_EXTERNAL_DOMAINS:
    process.env.STD_FEEDBACK_EXTERNAL_DOMAINS ?? "staudmoebel.de",
  STD_FEEDBACK_PROJECT_KEYWORDS:
    process.env.STD_FEEDBACK_PROJECT_KEYWORDS ?? "STD",
  EMAIL_HOST: process.env.EMAIL_HOST ?? "smtp.gmail.com",
  EMAIL_PORT: process.env.EMAIL_PORT ?? "587",
  EMAIL_USER: process.env.EMAIL_USER ?? "",
  EMAIL_PASSWORD: process.env.EMAIL_PASSWORD ?? "",
};

const apiProcess = {
  cwd,
  script: python,
  autorestart: true,
  max_restarts: 10,
  min_uptime: "5s",
  listen_timeout: 10000,
  instances: 1,
  exec_mode: "fork",
};

module.exports = {
  apps: [
    {
      ...apiProcess,
      name: "primeflow-recording-timing",
      args: "-m app.jobs.recording_timing",
      env: sharedEnv,
    },
    {
      ...apiProcess,
      name: "primex-backend",
      args: "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 15 --backlog 2048",
      env: {
        ...sharedEnv,
        // Tomorrow SHTYPI delivery runs in its own supervised process below.
        TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED: "false",
      },
    },
    {
      ...apiProcess,
      name: "primex-public-api",
      args: "-m uvicorn app.main:app --host 0.0.0.0 --port 8080 --timeout-keep-alive 15 --backlog 2048",
      env: {
        ...sharedEnv,
        // Only one API instance should run the weekly system-task scheduler.
        SYSTEM_TASK_SCHEDULER_ENABLED: "false",
        // The primary API owns the STD sync loop; the public fallback stays read-only.
        STD_FEEDBACK_SYNC_ENABLED: "false",
        // The primary API exclusively owns the shared Outlook calendar sync.
        MS_CALENDAR_SYNC_ENABLED: "false",
        // The primary API exclusively owns the meeting reminder loop.
        MEETING_REMINDER_SCHEDULER_ENABLED: "false",
        // The primary API exclusively owns the daily 1H SHTYPI delivery loop.
        TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED: "false",
        TODAY_PRINT_REPORT_SCHEDULER_ENABLED: "false",
      },
    },
    {
      ...apiProcess,
      name: "primex-tomorrow-shtypi-scheduler",
      args: "tomorrow_shtypi_scheduler.py",
      env: {
        ...sharedEnv,
        // Use the fallback API so report delivery does not depend on the
        // primary API process that previously owned this scheduler.
        PRIMEFLOW_API_BASE_URL:
          process.env.PRIMEFLOW_API_BASE_URL ?? "http://127.0.0.1:8080",
        TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED: "true",
        TODAY_PRINT_REPORT_SCHEDULER_ENABLED: "false",
      },
    },
    {
      ...apiProcess,
      name: "primeflow-mcp",
      args: "mcp_server.py",
      env: {
        ...sharedEnv,
        PRIMEFLOW_API_BASE_URL: process.env.PRIMEFLOW_API_BASE_URL ?? "https://api-flow.primexeu.com",
        PRIMEFLOW_WEB_BASE_URL: process.env.PRIMEFLOW_WEB_BASE_URL ?? "https://primeflow.primexeu.com",
        PRIMEFLOW_MCP_TRANSPORT: process.env.PRIMEFLOW_MCP_TRANSPORT ?? "sse",
        PRIMEFLOW_MCP_HOST: process.env.PRIMEFLOW_MCP_HOST ?? "0.0.0.0",
        PRIMEFLOW_MCP_PORT: process.env.PRIMEFLOW_MCP_PORT ?? "8010",
        PRIMEFLOW_ACCESS_TOKEN: process.env.PRIMEFLOW_ACCESS_TOKEN ?? "",
        PRIMEFLOW_EMAIL: process.env.PRIMEFLOW_EMAIL ?? "",
        PRIMEFLOW_PASSWORD: process.env.PRIMEFLOW_PASSWORD ?? "",
        PRIMEFLOW_READONLY_DATABASE_URL: process.env.PRIMEFLOW_READONLY_DATABASE_URL ?? "",
      },
    },
    {
      ...apiProcess,
      name: "primeflow-discord",
      args: "discord_bot.py",
      // The worker reads its Discord secrets from backend/.env. Never put
      // those secrets in command-line arguments or the ecosystem source.
      env: {
        ...sharedEnv,
        PRIMEFLOW_API_BASE_URL: "http://127.0.0.1:8000",
      },
    },
    {
      ...apiProcess,
      name: "primeflow-report-scheduler",
      args: "report_scheduler.py",
      env: {
        ...sharedEnv,
        PRIMEFLOW_API_BASE_URL: process.env.PRIMEFLOW_API_BASE_URL ?? "https://api-flow.primexeu.com",
        PRIMEFLOW_ACCESS_TOKEN: process.env.PRIMEFLOW_ACCESS_TOKEN ?? "",
        PRIMEFLOW_EMAIL: process.env.PRIMEFLOW_EMAIL ?? "",
        PRIMEFLOW_PASSWORD: process.env.PRIMEFLOW_PASSWORD ?? "",
        PRIMEFLOW_REPORT_TIMEZONE: process.env.PRIMEFLOW_REPORT_TIMEZONE ?? "Europe/Tirane",
        PRIMEFLOW_REPORT_RECIPIENTS: process.env.PRIMEFLOW_REPORT_RECIPIENTS ?? "130primex.eu@gmail.com,ga@primexeu.com",
        EMAIL_HOST: process.env.EMAIL_HOST ?? "smtp.gmail.com",
        EMAIL_PORT: process.env.EMAIL_PORT ?? "587",
        EMAIL_USER: process.env.EMAIL_USER ?? "",
        EMAIL_PASSWORD: process.env.EMAIL_PASSWORD ?? "",
      },
    },
    {
      name: "celery_worker",
      cwd,
      script: python,
      args: "-m celery -A app.celery_app.celery_app worker -l info --pool=solo",
      autorestart: true,
      max_restarts: 10,
      env: sharedEnv,
    },
    {
      name: "celery_beat",
      cwd,
      script: python,
      args: "-m celery -A app.celery_app.celery_app beat -l info",
      autorestart: true,
      max_restarts: 10,
      env: sharedEnv,
    },
  ],
};
