# Primex Nexus

Production-ready internal task & project management platform (Trello-like) with:
- Department Kanban boards (Boards → Projects → Tasks)
- Common View entries with manager approval + optional task generation
- RBAC (Admin / Manager / Staff) enforced server-side
- Weekly + monthly planners, automatic carry-over, system task templates
- Notifications (REST + WebSockets) including 1h in-app reminders
- Exports (CSV / XLSX / PDF summary)

## Requirements (No Docker)

- Python 3.11 or 3.12 recommended
- Node.js 20+
- PostgreSQL 14+
- Redis 6+

## Setup

### 1) Backend

```powershell
cd backend
copy .env.example .env
```

Edit `backend/.env`:
- `DATABASE_URL` must be `postgresql+asyncpg://...`
- Set `JWT_SECRET`
- Set `APP_TIMEZONE` (default `Europe/Budapest`)
- Optional for cloud dictation: `OPENAI_API_KEY`, `SPEECH_MAX_FILE_MB` (default 20)
- Albanian cloud dictation uses `SPEECH_ALBANIAN_TRANSCRIBE_MODEL` (default `gpt-4o-transcribe`) with an Albanian transcription prompt, including Kosovo speech. The hosted API rejects `language=sq`, so the language is specified in the prompt. Other languages use `SPEECH_TRANSCRIBE_MODEL` (default `whisper-1`). See [OpenAI transcription prompting](https://developers.openai.com/api/docs/guides/speech-to-text#prompting).
- For scheduled email reports, set `EMAIL_USER=130primex.eu@gmail.com` and `EMAIL_PASSWORD` in `backend/.env` (or the backend process environment). `EMAIL_PASSWORD` must be that account's Google app password. Restart the backend after changing either value. The production deploy requires both GitHub Actions secrets.

Install deps:
```powershell
python -m pip install -r requirements.txt
```

Run migrations:
```powershell
alembic -c alembic.ini upgrade head
```

Seed default departments/boards/statuses (and optionally an initial admin):
```powershell
$env:ADMIN_EMAIL="admin@example.com"
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="change-me-now"
python -m app.seed
```

Start API:
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start background jobs (system tasks, reminders, overdue, carry-over):
```powershell
celery -A app.celery_app.celery_app worker -l info
celery -A app.celery_app.celery_app beat -l info
```

System task scheduling notes:
- `generate-system-tasks`: weekly on Friday at `06:00` local (`APP_TIMEZONE`)
- By default, generation creates scheduled system task instances through the next `7` days

### 2) Frontend

```powershell
cd frontend
copy .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

### Local API using the server database

When `DATABASE_URL` points to the server database, let the server own background
jobs. Set these values in the local `backend/.env` before starting the API:

```dotenv
REPORT_SCHEDULERS_ENABLED=false
SYSTEM_TASK_SCHEDULER_ENABLED=false
MS_CALENDAR_SYNC_ENABLED=false
STD_FEEDBACK_SYNC_ENABLED=false
MEETING_REMINDER_SCHEDULER_ENABLED=false
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
```

`REPORT_SCHEDULERS_ENABLED` controls all six API-owned report delivery loops
and the M3 reporting points capture at 16:15,
including morning and today/tomorrow print reports. It defaults to `true` on the
server and does not control standalone report scheduler or Celery processes.
Scheduled email failures do not prevent the API from starting. Manual report
email still requires `EMAIL_USER=130primex.eu@gmail.com` and that account's Gmail
app password in `EMAIL_PASSWORD`.

## MCP for ChatGPT / Codex

Personal Discord assistant setup, supported task actions, reminder schedule and
deployment instructions: [Discord assistant](docs/discord-assistant.md).

This repo includes an MCP server that lets an MCP-capable client call Primeflow through the existing FastAPI API. Local MCP clients can use stdio. ChatGPT Apps/connectors need the server deployed as a reachable HTTPS remote MCP endpoint.

Install backend dependencies, start the API, then set a Primeflow access token.

Local stdio mode:

```powershell
cd backend
python -m pip install -r requirements.txt
$token = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/auth/login" -ContentType "application/json" -Body '{"email":"admin@example.com","password":"change-me-now"}').access_token
$env:PRIMEFLOW_API_BASE_URL="http://127.0.0.1:8000"
$env:PRIMEFLOW_ACCESS_TOKEN=$token
python mcp_server.py
```

Example local MCP client config:

```json
{
  "mcpServers": {
    "primeflow": {
      "command": "python",
      "args": ["C:\\Users\\Admin\\Documents\\GitHub\\Primex-TaskManager\\backend\\mcp_server.py"],
      "env": {
        "PRIMEFLOW_API_BASE_URL": "http://127.0.0.1:8000",
        "PRIMEFLOW_ACCESS_TOKEN": "<access token>"
      }
    }
  }
}
```

Hosted SSE mode for ChatGPT/App testing:

```powershell
cd backend
$env:PRIMEFLOW_API_BASE_URL="https://api-flow.primexeu.com"
$env:PRIMEFLOW_WEB_BASE_URL="https://primeflow.primexeu.com"
$env:PRIMEFLOW_EMAIL="<service account email>"
$env:PRIMEFLOW_PASSWORD="<service account password>"
$env:PRIMEFLOW_MCP_TRANSPORT="sse"
$env:PRIMEFLOW_MCP_PORT="8010"
python mcp_server.py
```

In this repo's GitHub Actions deploy, backend changes start a `primeflow-mcp` PM2 process on port `8010`. Add GitHub Actions secrets named `PRIMEFLOW_MCP_EMAIL` and `PRIMEFLOW_MCP_PASSWORD` before deploying, then expose port `8010` through HTTPS, for example `https://mcp-flow.primexeu.com/sse`. Add that URL in ChatGPT's Apps & Connectors developer setup. For production, replace the service-account prototype with OAuth so each ChatGPT user authorizes their own Primeflow account.

Available tools include ChatGPT-compatible `search`/`fetch`, task/project search, list/get/create/update tasks, list/get projects, list users, and current user lookup. The MCP server uses the normal Primeflow API, so existing backend permissions still apply.

Optional read-only database tools:

```sql
CREATE USER primeflow_mcp_reader WITH PASSWORD 'use-a-strong-password';
GRANT CONNECT ON DATABASE primex_nexus TO primeflow_mcp_reader;
GRANT USAGE ON SCHEMA public TO primeflow_mcp_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO primeflow_mcp_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO primeflow_mcp_reader;
```

Then add the GitHub Actions secret:

```text
PRIMEFLOW_READONLY_DATABASE_URL=postgresql://primeflow_mcp_reader:password@localhost:5433/primex_nexus
```

The MCP database tools only expose schema inspection and read-only SQL. App writes should still go through the Primeflow API tools.

## Production notes

- Frontend: `cd frontend; npm run build; npm start`
- Backend: run all backend processes with PM2 from `backend/ecosystem.config.cjs`.
- Keep `REDIS_ENABLED=true` in environments where Celery background generation is expected.
- WebSocket notifications: frontend connects to `ws(s)://<API_HOST>/ws/notifications?token=<access_token>`.
- Ensure `REDIS_URL` points to a reachable Redis instance and `APP_TIMEZONE=Europe/Budapest` (or your business timezone).

PM2 commands:
```powershell
cd backend
pm2 start ecosystem.config.cjs
pm2 status
pm2 logs backend-celery-beat --lines 200
pm2 save
```

Useful ops checks:
```powershell
celery -A app.celery_app.celery_app inspect ping
celery -A app.celery_app.celery_app inspect stats
```

