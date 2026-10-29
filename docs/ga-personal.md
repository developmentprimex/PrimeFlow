# GA PERSONAL

Private household module at `/ga-personal`, with its own `/api/ga-personal` API and PostgreSQL schema. It is disabled by default. No household UUIDs, password, dataset or Discord credentials ship in the repository.

The separate organizational department **GA PERSONAL** (`GAP`, manual realization)
is available in the user department selector. Department assignment does not grant
module membership. Revision `0172_ga_personal_department`
and the normal seed preserve this department without creating a public work project
for household tasks. No household user accounts are created by this change.

An operator can assign a verified existing account as administrator of this module
using `scripts/set_ga_personal_admin.py --person <key> --user-id <verified-uuid>`.
This previews the target; `--apply --expected-host <host> --expected-database <db>`
provisions only the isolated module tables if needed and persists its membership.
The account's PrimeFlow work role is preserved. It does not create a password,
activate the module, grant other accounts access or alter the deployed migration
stamp. Migration `0171_ga_personal` can adopt those existing tables on deployment.

## Available in this delivery

- Sidebar visibility based on the authenticated server capability, with no implicit company-admin access.
- Members use their existing PrimeFlow login directly. No additional module password, unlock cookie, setup step or separate expiry is required. All read/write endpoints still require an active exact-UUID module membership; module administrator permissions are checked separately.
- Tasks/templates, optional guidance steps, explicit ownership, one or multiple assignees, individual/shared completion, archive/restore, version checks and an append-only event history.
- One-off tasks create their occurrences immediately when enabled with a date/time. Recurring tasks can be generated explicitly or by the opted-in private generation worker. A confirmed recurrence can create an untimed task shown as “Pa orar”; it never invents a deadline or activates a reminder. School-day/conditional/first-home inputs require explicit confirmation; the automatic worker does not infer these.
- Daily, weekend, selected-day and rotation rules using Europe/Belgrade calendar dates. A weekly period is unique across Saturday/Sunday. Unconfigured schedules stay inactive. Imported source times remain suggestions for review, rather than activating alerts.
- Completion persists an event and cancels pending reminder rows in the same transaction. Concurrent generation/actions serialize on the family space row; retries of the same action ID do not duplicate events.
- Dataset preview/apply, stable source-ID mapping, safe repeat import and explicit conflicts when a model has local changes. Existing occurrences retain snapshots after a template changes.
- In-memory UI only: no household data is written to the persistent page cache. Logout and membership revocation clear the page state. A hidden tab masks private content and verifies access on return while preserving unsaved drafts. Temporary connection errors and forbidden edits preserve the current page and drafts. API responses use no-store.
- A compact daily/weekly list provides person, routine, status and text filters, progress, expandable instructions and inline edit entry points. Empty routine columns are omitted.
- **Ndrysho** on an unfinished task changes its date, time and assignee. The default scope is this occurrence only. For a fixed-assignment template, the user can explicitly apply time/assignment changes to future recurrences; other existing occurrences and completed history are preserved. **Përsëritjet** / **Ndrysho përsëritjen** edits full recurrence rules, including rotations. Version checks reject conflicting edits, and generation preserves occurrence identity after reassignment or date changes.

All four allowed module members can read family tasks after signing in to PrimeFlow. A member can create/manage models they created and assigned only to themselves. The explicitly configured module administrator can assign/manage all models. A configured adult administrator may record completion for another person; this retains the actual actor. No automatic sibling-supervisor role is assigned.

## Not activated or provisioned

The dedicated Kujtesa API bridge, reminder outbox and separate bot adapter are implemented. Setup and actual sending are separate: delivery stays disabled until the module administrator grants the limited delegation and the separate bot enables reminders. See `backend/integrations/kujtesa/README.md` for installation, activation, private channel requirements and failure handling. There is no voice playback or family Mira AI tool in this delivery. Existing work Discord/Mira bindings and memory do not receive household data.

No new user accounts are created. Provisioning currently requires four existing accounts selected explicitly by UUID. If household-only accounts are required, introduce and test a server-enforced account scope before creating them; a normal STAFF account has work permissions and must not be used as a substitute for that restriction.

## Configure after identities and administrator are chosen

For the reviewed ZIP handoff, `scripts/seed_ga_personal.py --archive <zip> --mapping <private-uuid-map> --admin-person <selected-admin>` previews the import. Apply requires `--apply --expected-host <host> --expected-database <db>`. The command validates the four exact existing accounts, binds missing normal memberships, preserves the chosen module administrator and password, imports source IDs idempotently, and activates only untouched, ready daily models with known assignments. It preserves local edits and occurrence history. The destructive SQLite rebuild scripts from the handoff are never executed against live data.

The seed opts the private space into automatic occurrence creation from the import date. The API checks once per minute while it is running, using Europe/Belgrade local dates, configured memberships and the persisted recurrence rules. Untimed daily tasks have no deadline and create no notification deliveries. School-day/conditional/first-home rules are not inferred. The module administrator can pause/resume this process from Settings. The same period keys and space-row transaction lock prevent duplicate occurrences across repeated seeds, API workers and restarts.

Once membership is provisioned and the module is enabled, members can open `/ga-personal` directly with their normal PrimeFlow login. The former password setup/unlock/lock/change endpoints have been removed. Existing password/unlock database fields are retained for compatibility with provisioning and bot delegation; they no longer gate browser access.

1. Back up the database and run the normal Alembic upgrade. Revision `0171_ga_personal` creates only the private schema/tables; it inserts no seed or users. It follows `0170_discord_one_h_reports`.
2. Put an exact mapping in a private local JSON file outside source control:

   ```json
   {
     "mrika": "<verified-user-uuid>",
     "lirza": "<verified-user-uuid>",
     "rrita": "<verified-user-uuid>",
     "gane": "<verified-user-uuid>"
   }
   ```

3. From `backend`, preview the selected identities with:

   ```powershell
   .\.venv\Scripts\python.exe scripts/configure_ga_personal.py --mapping <private-file> --admin <explicit-person-key>
   ```

   After reviewing them, repeat with `--apply`. The password is entered using a hidden terminal prompt, not a command-line argument. The apply step resets the module password, revokes old unlocks and replaces memberships. It does not activate schedules or send messages.

4. Set `GA_PERSONAL_ENABLED=true` in the API runtime environment and restart the API. `GA_PERSONAL_UNLOCK_MINUTES` is no longer used for browser access.
5. Open GA PERSONAL while signed in to PrimeFlow. The module administrator uploads the reviewed `data/ga-personal.dataset.json` through Settings, previews the changes and applies the import. Repeat import never silently overwrites local changes. Imported schedules stay disabled until reviewed individually.

The original handoff's manifest has stale hashes for four updated seed/export files. Validate the actual dataset and record its reviewed hash before live import. The import API returns a canonical-content hash used to bind preview/apply; it is intentionally distinct from a raw ZIP-file hash.

## Isolation

Household rows never enter the work `tasks`, `system_task_templates`, `checklists`, PX Notes, report or notification tables. Company search/exports operate on their existing work tables. No new household attachment/export endpoint is exposed; adding one must use the module's membership dependency.

The migration revokes PUBLIC access to the new `ga_personal` schema and does not grant it to the MCP read-only role. Audit actual production roles before enabling: an infrastructure/database owner can still access data they control. In particular, do not grant `USAGE/SELECT` in this schema to the work SQL/MCP reader. Alembic schema comparison includes only the application's default schema and `ga_personal`.

The implementation requires a valid active PrimeFlow account and an active exact-UUID module membership. A company-admin role alone grants no household access. Membership revocation takes effect on API requests independently of sidebar rendering.

## Verification

From `backend`:

```powershell
$env:GA_PERSONAL_TEST_DATABASE_URL="postgresql+asyncpg://<test-user>@127.0.0.1:<test-port>/<disposable-db>"
.\.venv\Scripts\python.exe -m unittest tests.test_ga_personal tests.test_migration_graph
```

Database tests require an explicitly supplied disposable PostgreSQL URL. Each test creates unique public/private test schemas and drops only those generated schemas. They never fall back to `DATABASE_URL`. Without the test URL the database tests are skipped; pure rule/migration tests still run.

From `frontend`: `npm run test:ga-personal` and `node node_modules/typescript/bin/tsc --noEmit`. The browser checks use synthetic identities and mocked API responses. If the Playwright-managed browser is unavailable, set `RECORDINGS_CHROMIUM_EXECUTABLE` to an installed supported Chromium. `GA_PERSONAL_REUSE_SERVER=1` can reuse this test suite's local dev server.

## Kujtesa connection

The local tablet app has a separate device-code integration with state download,
offline operations and revocation. See [Kujtesa local API](ga-personal-kujtesa-api.md)
for the exact routes, card fields, setup and deployment requirements.

The module administrator configures the separate bot under Settings > Kujtesa. Each task/template can choose private DM, the private family channel, or no Discord notification. Existing occurrences default to DM. Missing personal IDs do not block other recipients; Lirza uses Gane as the adult contact. The dedicated token remains exclusively in the bot environment, while a separate server-side bridge key authorizes only GA PERSONAL delivery operations.

Reminders use three phases at -5/0/+5 minutes with a five-minute window per phase. Generation and acknowledgement do not duplicate phases. Timing/owner/destination changes create a new schedule generation and invalidate old cards; snoozing explicitly keeps its own confirmation card usable. Buttons check actor, active membership, exact message/guild/channel, current assignment and explicit module delegation. Completion and help cancel unsent phases in the same transaction. Interaction IDs and durable claims make retries idempotent; ambiguous sends are not replayed blindly. Dirty message acknowledgements keep older cards synchronized, with backoff for inaccessible messages.

Revision `0174_ga_personal_discord` adds only the private outbox. Local configuration can adopt that table without running unrelated migrations or changing the server Alembic stamp, using `scripts/configure_kujtesa_bridge.py` with explicit expected database checks. The module password and all existing task data are preserved. A password change or removal of the authorizing module administrator revokes the bot delegation.
