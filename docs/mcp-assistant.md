# PrimeFlow MCP për asistenten e GA-së

Connector-i i largët që GA e lidh si **custom connector** në llogarinë e saj Claude.
Claude lexon agjendën e GA-së dhe zbaton përgjigjet e saj (“4 kryer”, “5 shtyje”,
“2 në 11:00”) **në emër të GA-së**.

## Arkitektura

```
claude.ai ──HTTPS──> Cloudflare Tunnel (mcp-flow.primexeu.com)
                      └─> Caddy 127.0.0.1:18011 (/mcp, /.well-known/oauth-protected-resource)
                           └─> primeflow-mcp-assistant 127.0.0.1:8011/mcp   (Streamable HTTP)
                                 │  1. verifikon token-in OAuth  ──> POST /api/oauth/internal/session
                                 │     (sekret i brendshëm; kthen një JWT PrimeFlow 15-min për atë përdorues)
                                 └─ 2. thërret API-në me JWT-në e GA-së ──> /api/ga-assistant/*, /api/tasks …
claude.ai ──HTTPS──> api-flow.primexeu.com  /.well-known/oauth-authorization-server, /oauth/*
                      └─> login + pëlqimi në primeflow.primexeu.com/oauth/consent
```

- Procesi i vjetër `primeflow-mcp` (8010, SSE, llogaria e shërbimit, 75 tools) mbetet si ishte.
  Tani lidhet vetëm në `127.0.0.1`, dhe `DELETE` te `primeflow_api_request` është i bllokuar
  (`PRIMEFLOW_MCP_ALLOW_DELETE=false`).
- `primeflow-mcp-assistant` është i njëjti `mcp_server.py` me `PRIMEFLOW_MCP_PROFILE=assistant`.
  Ekspozon vetëm allowlist-ën (43 tools) dhe s'e përdor kurrë llogarinë e shërbimit.
  Ekzekutohet nga `backend\.venv-mcp-assistant`, sepse kërkon `mcp==1.28.1`
  (`requirements-mcp-assistant.txt`), ndërsa 8010 mbetet me `mcp==1.10.1`.
- Çdo shkrim ekzekutohet me JWT-në e GA-së. Prandaj `created_by`, `audit_logs.actor_user_id`
  dhe komentet shënojnë GA-në. Çdo veprim i asistentit shton edhe një rresht
  `audit_logs` me `entity_type="ga_assistant"` dhe `after.via="mcp_assistant"`.

## OAuth 2.1 (MCP authorization 2025-06-18)

| Pika | Rruga |
|---|---|
| Protected resource metadata | `https://mcp-flow.primexeu.com/.well-known/oauth-protected-resource/mcp` (nga SDK-ja) |
| Authorization server metadata | `https://api-flow.primexeu.com/.well-known/oauth-authorization-server` |
| Dynamic Client Registration | `POST /oauth/register` (klientë publikë, `token_endpoint_auth_method=none`) |
| Authorize | `GET /oauth/authorize`: vetëm `code` + PKCE `S256`, `resource` = URL-ja e MCP-së |
| Login + pëlqimi | `primeflow.primexeu.com/oauth/consent?request_id=…` (faqja ekzistuese e login-it, pastaj “Lejo / Refuzo”) |
| Token | `POST /oauth/token`: `authorization_code` dhe `refresh_token` (rrotullim; përsëritja e një refresh token-i të vjetër revokon gjithë familjen) |
| Revokimi | `POST /oauth/revoke` |

**Rregullat e sigurisë:**
- Redirect URI lejohen vetëm nga `OAUTH_ALLOWED_REDIRECT_URIS` (parazgjedhja
  `https://claude.ai/api/mcp/auth_callback`) ose `http://127.0.0.1|localhost:*` (për testim).
- Qasja jepet vetëm për email-et në `MCP_ASSISTANT_ALLOWED_EMAILS`. Ky kontroll bëhet në
  pëlqim, në refresh dhe në çdo verifikim token-i.
- Kodet dhe token-at ruhen vetëm si SHA-256. Access token jeton 60 min, refresh token 30 ditë.
- Gjithçka kthen 404 derisa `MCP_ASSISTANT_ENABLED=true`.

## Tools e reja

ID-të mbajnë burimin:
- `pf_task:<uuid>`
- `pf_meeting:<uuid>@YYYY-MM-DD`
- `ms_event:<id>`
- `todo:<list_id>::<task_id>`

Koha është në `GA_TIMEZONE` (`Europe/Belgrade`).

| Tool | Çfarë bën |
|---|---|
| `ga_agenda(start, end, include_untimed=false)` | Elementet me orë në `[start, end)`, të të gjitha burimeve |
| `ga_leftovers(as_of)` | Të papërfunduarat para `as_of`, më të vjetrat së pari, me ditët e vonesës |
| `ga_untimed_today(date)` | Detyrat pa orë për ditën |
| `ga_item_done(item_id, comment?, override_reason?)` | Detyrë → DONE. Detyrat normale kërkojnë komentin e rezultatit të GA-së (rregulli RLZ, si në UI); 1H/speciale jo. BZ ku GA s'është assignee → “BZ u mbajt” (koment + audit), pa e mbyllur detyrën e kolegut. Takim → “Mbajtur”. To Do → completed |
| `ga_item_postpone(item_id, new_date, new_time?, reason_code?, reason_comment?)` | Ndryshon `due_date` (ruhet `original_due_date`). Për detyra që s'janë të GA-së, PrimeFlow mund të kërkojë arsyen e shtyrjes. BZ dhe takimet s'shtyhen nga këtu |
| `ga_item_set_time(item_id, time\|null, date?)` | Orë për ditë **vetëm në agjendën e GA-së** (`ga_assistant_item_times`); s'prek `due_date` apo orën BZ të template-it. To Do → orari i kujtesës |
| `ga_item_remove_from_day(item_id, reason, date?)` | E fsheh elementin nga agjenda e GA-së për atë ditë (soft; s'fshihet asgjë) |
| `ga_add_comment(item_id, text)` | Detyrë → shtohet te komenti i GA-së; To Do → te shënimet |
| `todo_list / todo_create / todo_update / todo_complete / todo_set_steps` | Microsoft To Do i `info@` |

### Si klasifikohen elementet

- **GA TASKS** dhe **BZ ME GA TASKS**: të njëjtat rregulla si tabela e parë e `/admin-tasks`
  (`frontend/src/app/(app)/admin-tasks/page.tsx`, `allTasksTableRows`):
  - GA TASKS = GA është assignee real ose konfirmuesi te WAITING_CONFIRMATION.
  - BZ = GA është vetëm person alignment (në detyrë ose në template). `koha_bz` = `system_task_templates.alignment_time`.
  - Dita = `due_date` (përndryshe `start_date`); detyrat sistemore të kryera mbajnë ditën origjinale.
- **F**: simboli `F` te `tasks.one_h_marker` = “DET FIZIKISHT (ME GA)”.
  - Zgjedhet si te M1 “FIZIKISHT ME GA?”: çdo ditë që mbulon intervali Start–Due
    (`after_break_report._task_covers_day`), një rresht për çdo grup kopjesh (`morning_report._marked_task_identity`).
  - Pranohen edhe simbolet e kombinuara (p.sh. `M2,F`).
- **Takimet**: si GA Time Table, pra takimet externe të dukshme dhe takimet interne manuale.
  Statusi “Mbajtur/Anuluar” merret nga `meeting_occurrence_statuses`.
- **Outlook events**: kutia `MS_ORGANIZER_EMAIL`. Eventet që janë importuar si takime nuk përsëriten.
- **Koha** sipas përparësisë:
  1. ora e vendosur nga asistenti
  2. `koha_bz`
  3. slot-i 1H
  4. ora e `due_date`, kur s'është 00:00 ose 23:59

  Në mungesë të tyre elementi del pa orë, me AM/PM kur dihet.

## Microsoft To Do (iPhone Reminders)

| Fusha Graph | Kuptimi në iPhone |
|---|---|
| `dueDateTime` | data e kujtesës; dërgohet si `YYYY-MM-DDT00:00:00` UTC që të mos zhvendoset data |
| `reminderDateTime` + `isReminderOn` | ora (“me orë”); dërgohet në UTC |
| `status=completed` | ✓ |
| `body` (text) | shënimet; hapat ruhen si rreshta `☐`/`☑`, sepse `checklistItems` nuk sinkronizohen me iPhone |

Leja `Tasks.ReadWrite` kërkohet **vetëm në autorizim dhe vetëm kur `MS_TODO_ENABLED=true`**
(`authorize_scope_str()`). Refresh-i i token-it
vazhdon me scope-t e kalendarit, që sinkronizimi ekzistues i kalendarit të mos prishet para
ri-autorizimit.

> Rastet në iPhone **nuk janë testuar ende** (kërkojnë llogarinë reale). Plotësoje këtë
> tabelë pas testit:
>
> | Rasti | Pritja | Rezultati |
> |---|---|---|
> | me orë | data + ora + njoftim | ☐ |
> | pa orë | vetëm data | ☐ |
> | pa orë → me orë (`ga_item_set_time`) | merr orën | ☐ |
> | ✓ nga iPhone | `status=completed`, del nga agjenda | ☐ |
> | hapat te shënimet (`todo_set_steps`) | rreshtat ☐/☑ te Notes | ☐ |

## Env vars të reja (vetëm emrat)

| Variabla | Ku | Shënim |
|---|---|---|
| `MCP_ASSISTANT_ENABLED` | Actions **variable** → `backend\.env` | `true` ndez OAuth-in, venv-in dhe procesin PM2 |
| `MCP_ASSISTANT_ALLOWED_EMAILS` | Actions variable | fillimisht vetëm email-i i GA-së |
| `MCP_ASSISTANT_INTERNAL_SECRET` | Actions **secret** | sekret i gjatë i rastësishëm, i ndarë mes API-së dhe procesit 8011 |
| `MCP_ASSISTANT_RESOURCE_URL` | `.env` | `https://mcp-flow.primexeu.com/mcp` |
| `OAUTH_ISSUER_URL` | `.env` | `https://api-flow.primexeu.com` |
| `OAUTH_ALLOWED_REDIRECT_URIS` | opsionale | parazgjedhja: callback-u i claude.ai |
| `OAUTH_ACCESS_TOKEN_MINUTES`, `OAUTH_REFRESH_TOKEN_DAYS`, `OAUTH_AUTH_CODE_SECONDS`, `OAUTH_PENDING_REQUEST_SECONDS` | opsionale | 60 / 30 / 300 / 900 |
| `GA_USER_EMAIL`, `GA_USERNAME` | opsionale | identiteti i GA-së, një vend i vetëm; parazgjedhjet = vlerat e mëparshme |
| `GA_TIMEZONE` | `.env` | `Europe/Belgrade` |
| `PRIMEFLOW_MCP_PROFILE` | PM2 | `assistant` vetëm për 8011 |
| `PRIMEFLOW_MCP_ALLOW_DELETE` | opsionale | `false` si parazgjedhje |
| `PRIMEFLOW_MCP_ASSISTANT_HOST`, `PRIMEFLOW_MCP_ASSISTANT_PORT` | opsionale | `127.0.0.1` / `8011` |
| `INSTALL_BACKEND_REQUIREMENTS` | Actions variable | parazgjedhja `false`; `true` e ndez `pip install -r requirements.txt` në deploy |
| `MS_TODO_ENABLED` | Actions variable → `.env` | parazgjedhja `false`: lidhja Microsoft kërkon të njëjtat leje si më parë dhe tools e To Do janë të fikura. Vendose `true` vetëm pasi Azure ka `Tasks.ReadWrite`, pastaj ri-autorizo `info@` |

## Hapat manualë

1. **Migrimi**: `alembic upgrade head` (0192, katër tabela të reja, pa prekur tabelat ekzistuese).
   E ekzekuton deploy-i.
2. **Azure app registration**: shto lejen delegated `Tasks.ReadWrite` (Microsoft Graph).
   Jep admin consent nëse tenant-i e kërkon.
3. **`MS_TODO_ENABLED=true`** (Actions variable), pastaj **ri-autorizimi i Microsoft**: hyr në PrimeFlow → lidhja Microsoft → lidhu përsëri me
   `info@primexeu.com`. Pa këtë, tools e To Do kthejnë “no Tasks.ReadWrite permission”,
   ndërsa kalendari vazhdon të punojë.
4. **GitHub Actions**:
   - secret `MCP_ASSISTANT_INTERNAL_SECRET`
   - variables `MCP_ASSISTANT_ALLOWED_EMAILS` dhe `MCP_ASSISTANT_ENABLED=true`
5. **Caddy**: kopjo `deploy/Caddyfile` te `C:\PrimeFlowOps\DeploymentGateway\Caddyfile`,
   `caddy validate`, pastaj rinis task-un “PrimeFlow Deployment Gateway”. Shtohet listener-i
   `127.0.0.1:18011`.
6. **Cloudflare Tunnel**: public hostname `mcp-flow.primexeu.com` → `http://127.0.0.1:18011`.
   Verifiko që **asnjë** hostname s'shkon te `127.0.0.1:8010`.
7. **PM2**: deploy-i e nis `primeflow-mcp-assistant`. Me dorë: `pm2 start ecosystem.config.cjs --only primeflow-mcp-assistant`.

## Testimi

**Lokalisht:**
- `tests.test_oauth_server`, `tests.test_ga_assistant` (pa DB).
- `tests.test_mcp_assistant_profile` (me `.venv-mcp-assistant`).
- `tests.test_ga_assistant_db`: me `PRIMEFLOW_DB_TESTS=1` dhe `DATABASE_URL` drejt një DB-je
  `*_test`; testi e pastron vetë DB-në.

**MCP Inspector:** `npx @modelcontextprotocol/inspector` → Streamable HTTP →
`https://mcp-flow.primexeu.com/mcp` → “Open Auth Settings” → “Quick OAuth Flow”.

**Claude Code:**

```
claude mcp add --transport http primeflow-ga https://mcp-flow.primexeu.com/mcp
```

Pastaj `/mcp` → Authenticate.

**claude.ai:** Settings → Connectors → Add custom connector → URL
`https://mcp-flow.primexeu.com/mcp`. Lidhu si GA dhe zgjidh “Lejo”.
