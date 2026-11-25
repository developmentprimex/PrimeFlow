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
  Ekspozon vetëm mjetet në `ASSISTANT_TOOLS`. Thirrjet përdorin identitetin OAuth të përdoruesit.
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
- `tt:<source_external_id>`: reminder i iPhone-it nga GA Time Table (“R:”), vetëm lexim
- `dc:<discord message id>`: mesazh Discord që e përmend GA-në

Koha është në `GA_TIMEZONE` (`Europe/Belgrade`).

| Tool | Çfarë bën |
|---|---|
| `ga_agenda(start, end, include_untimed=false, include_live_microsoft=true)` | Elementet me orë në `[start, end)`, të të gjitha burimeve |
| `ga_leftovers(as_of)` | Të papërfunduarat para `as_of`, më të vjetrat së pari, me ditët e vonesës |
| `ga_untimed_today(date)` | Detyrat pa orë për ditën |
| `ga_item_done(item_id, comment?, override_reason?)` | Detyrë → DONE. Detyrat normale kërkojnë komentin e rezultatit të GA-së (rregulli RLZ, si në UI); 1H/speciale jo. BZ ku GA s'është assignee → “BZ u mbajt” (koment + audit), pa e mbyllur detyrën e kolegut. Takim → “Mbajtur”. To Do → completed |
| `ga_item_postpone(item_id, new_date, new_time?, reason_code?, reason_comment?)` | Ndryshon `due_date` (ruhet `original_due_date`). Për detyra që s'janë të GA-së, PrimeFlow mund të kërkojë arsyen e shtyrjes. BZ dhe takimet s'shtyhen nga këtu |
| `ga_item_set_time(item_id, time\|null, date?)` | Orë për ditë **vetëm në agjendën e GA-së** (`ga_assistant_item_times`); s'prek `due_date` apo orën BZ të template-it. To Do → orari i kujtesës |
| `ga_item_remove_from_day(item_id, reason, date?)` | E fsheh elementin nga agjenda e GA-së për atë ditë (soft; s'fshihet asgjë) |
| `ga_add_comment(item_id, text)` | Detyrë → shtohet te komenti i GA-së; To Do → te shënimet |
| `todo_list / todo_create / todo_update / todo_complete / todo_set_steps` | Microsoft To Do i `info@` |
| `ga_time_table(week_start?)` | GA Time Table e javës (H–P), si te faqja: rreshtat e orëve me shënimet, hyrjet e template-it dhe rreshtat e iPhone Sync (“R: …”, “CALENDAR …”). Takimet/detyrat janë te `ga_agenda` |
| `ga_discord_mentions(since?, until?, only_open=true)` | Mesazhet në kanalet e serverit që e përmendin GA-në, një rol të saj, ose i përgjigjen asaj: kush (emri + inicialet), kanali, koha, teksti, linku, bashkëngjitjet, statusi |
| `ga_discord_mentions_feed(before?, limit=25)` | Lista vetëm për lexim për Claude Artifact, me përmendjet direkte të GA-së nga `#det-nga-stafi-per-ga` dhe reagimet e tyre aktuale |
| `ga_discord_mention_attachments(id)` | Linket e freskëta të bashkëngjitjeve nga një mesazh i listës, me emër dhe lloj skedari |
| `ga_discord_attachment_content(id, name)` | Lexon skedarin me emrin e saktë te një përmendje ose mesazh konteksti. Excel/CSV kthejnë `sheets` me `name`, `csv`, `row_count`; DOCX/PDF/TXT kthejnë `text`; PNG/JPG kthejnë imazh MCP. |
| `ga_discord_reply(id, text)` | Boti dërgon `GA: <text>` si reply në Discord dhe kthen `id` e `url` të përgjigjes |
| `ga_discord_react(id, emoji, remove=false)` | Shton ose heq reagimin e botit për 👍, ✅, 👀 ose ❌. Kthen `id`, `emoji` dhe `removed` |
| `ga_discord_mark(id, status)` | `seen` / `done` (ose `new`); në Discord s'ndryshon asgjë |

## Raportet ASIST GA – DET GA

| Mjeti | Fushat dhe përdorimi |
|---|---|
| `ga_report_links(date)` | `links[]` me `key`, `title`, `url`, `available`. Gjashtë faqet M1/M2/M3 dhe PIKAT, plus 1H SHTYPI Sot/Nesër, hapen në datën e kërkuar. `available` tregon se faqja ka një link, ndërsa vetë faqja tregon nëse raporti është ruajtur për atë ditë. |
| `ga_m1_reorg_get(date)` dhe `ga_m1_reorg(date, answer, comment?)` | Lexojnë dhe ruajnë përgjigjen e M1 Pikat. Kthejnë `date`, `answer` (`po`, `jo` ose `null`) dhe `comment`. Kur përgjigjja ekzistuese është vetëm tekst i lirë, kthehet te `comment`. |
| `ga_1h_comments(since?, only_new=false)` dhe `ga_1h_comment_mark(id, status)` | `items[]` me `id`, `task: {id, title, link}`, `author: {name, initials}`, `time`, `text`, `status: new/seen`. Përdor ID-në e plotë të kthyer nga lista. Redaktimi krijon një version për t'u lexuar përsëri. |
| `ga_agenda(...)` | Detyrat përfshijnë simbolet GA dhe F, `symbols` dhe `daypart: AM/PM/null`. Takimet japin `type: EXT/INT/BZ`, `held`, `join_url` për Teams dhe `notes_url` kur gjenden shënimet. |
| `ga_devices(date)` dhe `ga_device_mark(id, status, comment?)` | Detyrat me titullin GA Devices kthejnë `id`, `title`, `category`, `person`, `time`, `link`, `status`. `reacted` ruan reagimin në listën GA Devices. `done` përdor rregullat e zakonshme të përfundimit të detyrës. |
| `list_ga_notes(note_type="GA", unconverted_only=true, since?)` | Lexon shënimet e ruajtura sipas kohës së krijimit. Fushat përfshijnë `status`, `is_discussed`, `is_converted_to_task`, `author`, `created_at`. |
| `ga_px_tasks(date, until)` | Detyrat e GA-së me afat nga fillimi i datës deri te ora lokale `until`, përfshirë vetë orën. `items[]` me `id`, `title`, `due_at`, `status`, `link` dhe `scope: "PX"`. Afatet pa orë nuk futen në një raport të ndërmjetëm. |
| `ga_discord_mentions_feed(...)` | Çdo përmendje ka `ga_replied`, `ga_reacted`, `others_reacted_before_ga`, `others_reacted_before_ga_names` dhe `others_reacted_before_ga_known`. Lexo edhe fushën `known` për reagimet e vjetra ose kur renditja nuk mund të verifikohet. |

Për rifreskimin çdo dy minuta, përdor `include_live_microsoft=false` te agjenda,
`since` te komentet e shënimet dhe faqen e parë të feed-it Discord. Takimet e
sinkronizuara, iPhone Sync dhe Discord vazhdojnë të lexohen nga PrimeFlow.

## Reminders “R:” të iPhone-it (GA Time Table)

- Burimi: rreshtat që iPhone Sync i importon te `ga_time_slot_entries` (`source_type=reminder`),
  me `source: iphone_sync`, `kind: REMINDER`, id `tt:…` (i qëndrueshëm mes sinkronizimeve).
- Ora merret nga “R: HH:MM”. “R: 00:00” = pa orë → untimed për ditën e kolonës.
  Reminder pa datë (iPhone Sync e vendos në ditën e parë të dritares) del si untimed **çdo ditë**
  derisa të kryhet.
- Pas një importi që sjell titullin dhe datën e origjinës, `ga_item_done` për një
  `tt:…` kthen `pending_complete`. Agjenda shfaq «✓ në pritje për iPhone» derisa
  Shortcut-i ta kryejë në telefon dhe ta konfirmojë. Ndryshimi i orës dhe i tekstit
  bëhen në iPhone. `ga_item_remove_from_day` mund ta fshehë për një ditë.
- Të pakryerat e ditëve të kaluara dalin te `ga_leftovers` me `days_late`, vetëm brenda dritares
  së fundit të sinkronizimit (sot − 7 ditë); më të vjetrat s'rifreskohen më nga telefoni.
  Kur sinkronizimi i fundit është më i vjetër se 24 orë, del një warning.
- I njëjti reminder në To Do dhe në iPhone Sync (titull + ditë) kthehet një herë.
  Agjenda përdor elementin To Do zakonisht dhe elementin e iPhone-it gjatë pritjes
  për konfirmim. `linked_ids` përmban ID-në tjetër.

## Microsoft To Do: rregulla shtesë

- Lista “Flagged Emails” (`wellknownListName=flaggedEmails`) s'lexohet si reminders.
- To Do pa datë del te `ga_untimed_today` (dhe te `ga_agenda` me `include_untimed`) çdo ditë
  derisa të kryhet.

## Discord: mentions e GA-së

`ga_discord_attachment_content` lexon deri në 2 000 rreshta në total dhe
shënon `truncated` kur rezultati shkurtohet. PDF-ja përdor tekstin e
integruar. Për PDF të skanuara pa tekst kthehet një shpjegim. Për fotot
limiti është 4 MB, për skedarët e tjerë 12 MB.

- Procesi i leximit të botit: `backend/discord_ga_mentions.py`, procesi PM2
  `primeflow-ga-discord-mentions`. Intents: Guilds, Guild Messages, Guild Message Reactions, Message Content.
  Lejet për mbledhjen: View Channels + Read Message History. Leximi mbulon kanalet e serverit dhe thread-et publike të disponueshme.
- Ruan te `ga_discord_mentions` (migrimi 0195) çdo mesazh që përmend GA-në (`@` e saj ose një
  rol që ka), ose që i përgjigjet një mesazhi të saj. GA-ja njihet nga lidhja e saj Discord
  në PrimeFlow (`discord_links`) ose nga `GA_DISCORD_USER_ID`.
- Pas çdo rilidhjeje lexon edhe mesazhet e humbura (deri në `GA_DISCORD_MENTIONS_BACKFILL_HOURS`).
- Arkivi i stafit (migrimi 0207) ruan mesazhet e `#det-nga-stafi-per-ga` dhe të thread-eve publike
  ku boti ka qasje. Importi fillestar lexon historikun e disponueshëm. Pas rilidhjes, çdo
  kanal ose thread vazhdon nga grupi i fundit i ruajtur. Mesazhet e reja dhe reagimet
  regjistrohen gjatë punës normale të botit.
- Boti flet me API-në te `/api/ga-discord-bot/*` me sekret që nxirret nga `JWT_SECRET`
  (s'ka sekret të ri për t'u vendosur).
- Te `ga_agenda` (me `include_untimed`) dhe `ga_untimed_today`: `kind: DISCORD`, pa orë, në ditën
  kur u shkrua, derisa të shënohet `done`. Te `ga_leftovers`: vetëm ato me status `new`.
  `ga_item_done("dc:…")` = `done`.
- **Reactions** (migrimi 0197): çdo mesazh ka `reactions` (`[{emoji, count, users:[{name, initials}]}]`),
  `reviewed_by` (inicialet e kolegëve që reaguan me emoji aprovimi, pa autorin dhe pa GA-në) dhe
  `ready_for_ga` (`true` kur `reviewed_by` s'është bosh). `ga_discord_mentions(only_ready=true)` kthen
  vetëm ato gati. Boti dëgjon reaction add/remove/clear për mentions e 30 ditëve të fundit dhe e lexon
  mesazhin me REST (`GET /channels/{id}/messages/{id}`); mentions e vjetra pa reactions lexohen një herë
  pas nisjes. Emoji aprovimi: `GA_DISCORD_APPROVAL_EMOJIS` (default `✅,👍,✔️,☑️`; ngjyra e lëkurës s'ka
  rëndësi); emoji të tjera shfaqen, por s'e bëjnë mesazhin gati. Te agjenda, një mesazh gati ka markerin
  `✅ LH`.

### Lista e Discord-it për Claude Artifact

- Lidhe connector-in ekzistues `https://mcp-flow.primexeu.com/mcp` me OAuth si GA. Në lejet e Artifact-it për këtë kanal zgjidh `ga_discord_mentions_feed` dhe `ga_discord_mention_attachments`. Të dyja mjetet janë vetëm për lexim.
- Thirr `ga_discord_mentions_feed({})` kur hapet ose rifreskohet lista. Përmendjet direkte nga `#det-nga-stafi-per-ga` vijnë nga më e reja te më e vjetra, përfshirë statusin `done`. API-ja përdor `DISCORD_GA_REPLIES_CHANNEL_ID` për të zbatuar filtrin e kanalit. Përmendjet e roleve dhe përgjigjet hyjnë në listë vetëm kur i njëjti mesazh përmban edhe përmendje direkte.
- Rezultati i strukturuar MCP përmban `channel_id`, `timezone`, `bot_configured`, `items` dhe `next_before`. Çdo rresht përmban ID-në `dc:…`, dërguesin, kanalin, kohën, tekstin, linkun origjinal dhe reagimet me emoji, numër dhe emra. `reactions_synced_at: null` tregon që leximi i reagimeve është ende në pritje. `bot_configured` tregon praninë e konfigurimit të botit.
- Shfaq `items[].attachments[].name` te mesazhi. Kur përdoruesi hap skedarët, thirr `ga_discord_mention_attachments` me ID-në `dc:…` të atij rreshti. Mjeti kontrollon mesazhin aktual në Discord dhe kthen `attachments: [{name, url, content_type}]`. Kërko link të ri nëse bie afati i tij. Linku `items[].url` hap mesazhin origjinal në Discord.
- Të dy mjetet e përmendjeve kthejnë `context` për çdo rresht. Për një përmendje direkte në këtë kanal:
  - `para` dhe `pas` përmbajnë mesazhet e të njëjtit autor në të njëjtin kanal, deri në dy minuta nga përmendja.
  - `reply` përmban mesazhin origjinal të cilit i përgjigjet përmendja, pa kufi kohe, ose `null`.
  - `përgjigjet` përmban reply-t direkte ndaj përmendjes dhe mesazhet nga thread-i publik që nis te përmendja.
  - Çdo mesazh i kontekstit ka ID `dc:…`, autor, kohë, tekst, emra skedarësh, reagime dhe linkun te Discord.
    Përdor të njëjtin `ga_discord_mention_attachments` me ID-në e mesazhit të kontekstit.
- Për faqen pasuese, ktheje `next_before` si `before` dhe përdor të njëjtin `limit` (1–50). `next_before: null` shënon fundin. Për të marrë ndryshime të reja, rifresko faqen e parë pa `before`; përditëso rreshtat ekzistues sipas `id` që shtimi ose heqja e reagimeve të shfaqet te i njëjti mesazh.
- Për veprime nga Artifact-i, aktivizo `ga_discord_reply` dhe `ga_discord_react`. Vetëm llogaria GA mund t'i thërrasë. Të dy mjetet pranojnë ID-të `dc:…` të përmendjeve nga `#det-nga-stafi-per-ga` dhe të mesazheve të kontekstit. Veprimet kryhen me identitetin e botit dhe ruhen në auditin e PrimeFlow.
- Thirr `ga_discord_reply` vetëm kur GA klikon **Dërgo**. Kalo tekstin që ajo ka shkruar. Boti shton prefiksin `GA: `. Përgjigjja lidhet në Discord me mesazhin e zgjedhur dhe shfaqet te `context["përgjigjet"]` në rifreskimin pasues, edhe kur mesazhi i zgjedhur është pjesë e kontekstit.
- Për reagimet, përdor `remove=false` për shtim dhe `remove=true` për heqjen e reagimit të botit. Reagimi shfaqet pasi boti sinkronizon ndryshimin nga Discord. Reagimet e këtij boti nuk numërohen si aprovim nga kolegët. Boti kërkon **Send Messages** dhe **Add Reactions** në kanalin e stafit, si edhe **Send Messages in Threads** për t'u përgjigjur në thread-et publike.
- Pas deployment-it, provoje me një përmendje direkte dhe një skedar në kanal, shto një reaction dhe hiqe. Verifiko që skedari hapet me linkun e kërkuar nga mjeti dhe që `reactions` ndryshon duke ruajtur të njëjtin `id`.

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

Listat: agjenda dhe `todo_list` lexojnë **të gjitha** listat e `info@`. `todo_create` pa `list_name` krijon te
lista me aktivitetin më të fundit, pra aty ku sinkronizohen kujtesat e iPhone-it (te `info@` ka dy lista "Tasks").
Lista mund të fiksohet me `MS_TODO_CREATE_LIST` (id e listës, ose emër unik). Datat e kujtesave lexohen në
`GA_TIMEZONE`. iPhone e ruan mesnatën lokale si 23:00 UTC të ditës para, dhe pa konvertim kujtesat do të dilnin një ditë më herët.

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
| `GA_DISCORD_MENTIONS_BOT_TOKEN` | Actions **secret** → `backend\.env` (deploy-i e rikrijon `.env` çdo herë) | tokeni i botit të ri; pa të procesi s'niset |
| `GA_DISCORD_USER_ID` | opsionale | ID-ja Discord e GA-së, nëse s'ka lidhje Discord në PrimeFlow |
| `GA_DISCORD_MENTIONS_BACKFILL_HOURS` | opsionale | 72 |
| `GA_DISCORD_APPROVAL_EMOJIS` | opsionale (default në `config.py`) | `✅,👍,✔️,☑️` |
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
8. **Bot Discord për mentions** (Discord Developer Portal):
   - New Application → Bot → kopjo tokenin → GitHub Actions **secret** `GA_DISCORD_MENTIONS_BOT_TOKEN` (jo me dorë te `.env`: deploy-i e mbishkruan).
   - Bot → Privileged Gateway Intents: ndiz **Message Content Intent** (Server Members s'duhet).
   - Bot → çaktivizo “Public Bot”.
   - OAuth2 → URL Generator: scope `bot`, leje **View Channels** + **Read Message History**
     (permissions=66560), hape linkun dhe shtoje në serverin PrimEx.
   - Nëse ka kanale private ku GA përmendet, jepi botit leje leximi edhe atje.
   - Deploy-i i radhës (ose `pm2 start ecosystem.config.cjs --only primeflow-ga-discord-mentions`) e nis.

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
