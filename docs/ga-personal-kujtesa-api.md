# GA PERSONAL → Kujtesa local app

Base address: **https://primeflow.primexeu.com**. This integration requires database migration **0176_ga_personal_devices** and the normal `GA_PERSONAL_ENABLED` flag.

The frontend exposes these two fixed API paths and forwards their explicit device credentials to the configured backend. The tablet does not need the separate `api-flow` address or a browser login cookie.

## Connect a tablet

1. A GA PERSONAL module administrator opens **GA PERSONAL → Cilësimet → Kujtesa · Aplikacioni lokal**.
2. Enter the tablet name and select **Krijo kod pajisjeje**. Copy the code while it is displayed; it cannot be retrieved later.
3. On the tablet, open **Cilësimet → Lidhja me Primeflow** and enter the base address and the device code.
4. The app generates and retains a UUID for the tablet. Every API request sends `Authorization: Bearer <device code>`, `X-Device-Id: <tablet UUID>` and `Accept: application/json`. JSON POSTs also send `Content-Type: application/json`.

The first authenticated request binds the code to that UUID. Another tablet needs its own code. An administrator can revoke a code from the same panel. Deactivating the authorizing account, removing its membership or removing its module-administrator permission also disables the code. Codes do not authenticate the main PrimeFlow API or the Discord bot. They authorize this tablet to read the family module and synchronize family statuses/events/arrivals. Only a hash of the secret is stored in PostgreSQL.

## State

**GET `/api/ga-personal/device/state?since=<cursor>`**

Omit `since` for the initial download or to rebuild local state. Store the returned UTC `cursor` only after applying the entire response, then send it unchanged on the next request. Cursors use server time; client `at` timestamps never control the synchronization boundary. A future or invalid cursor is rejected; retry without it.

The response contains `cursor`, `tasks`, `events`, `statuses` and `arrivals`. `tasks` is always the complete current base-task list and replaces the local base-task list, including removal of archived/disabled templates. The other arrays contain changes since the cursor; the initial response contains their current state. Boundary repeats are harmless. Event deletion is returned as an `id` with `deleted: true` and `at`, including when deletion arrives before creation.

### Task cards

| Field | Meaning |
| --- | --- |
| `id`, `title` | Stable opaque task identifier and Albanian title. Never derive a PrimeFlow UUID or a person from the identifier. |
| `person_id` | `rrita`, `mrika`, `lirza`, `gane`, or `null` for shared family completion. |
| `start`, `end` | `HH:mm` in Europe/Belgrade. Untimed tasks have `start: null`, `end: null`, `alarm: false`; no suggested/imported time is silently activated. When duration is set, `end` is calculated from it. |
| `steps` | Ordered strings. |
| `kind` | `task`, `nala`, `roki`, `activity`, `appointment`, or `event`. |
| `area` | `room`, `bathroom`, `kitchen`, `school`, `home`, `nala`, `roki`, `activity`, `appointment`, or `event`. Personal room/bathroom areas map to their common kind. Other household areas map to `home`. |
| `group` | Routine group; `daily_upkeep` maps to `upkeep`. |
| `speech` | Short English phrase for the area; fallback is “Please complete your household task”. This does not translate arbitrary titles automatically. |
| `days` | Monday `0` through Sunday `6`; `null` for every day. |
| `date` | A one-off date or the anchor of an explicit repeat. |
| `weekend` | One completion for the weekend. Its status period is Saturday, including Sunday-only schedules. |
| `repeat` | `every`, `unit` (`day`, `week`, `month`), `days`, `until`. Nala's confirmed rotation exports one card per person with an anchored three-day repeat. |
| `alarm`, `lead`, `note` | Whether the confirmed time can trigger an alarm, lead minutes (currently `0` for base tasks), and description or `null`. |

Fixed assignments export one card per responsible person; shared completion exports a family card. School-day, conditional and first-home rules are not inferred: only their explicitly generated dated occurrences are exported. The base-card protocol represents template schedules; arbitrary one-occurrence schedule/assignment exceptions on recurring templates are not represented by the provided card fields. Full recurrence changes should be made under **Përsëritjet**.

Statuses contain one current row per `period` + `task_id`: `status`, `step`, `at`. Valid device statuses are `in_progress`, `needs_help`, `done`. No row means unfinished. `step` is progress, not an identity component; it is retained even though today's tablet ignores incoming step progress. A completed GA task reports the task's full step count. Main PrimeFlow status changes are also returned.

Arrivals contain one row per `day` + `person_id`, with the latest `at`. They are household arrival records; they do not alter company attendance or automatically confirm conditional chores.

## Operations

**POST `/api/ga-personal/device/ops`**

The body contains `device_id` (matching the header UUID) and an `ops` array, up to 200 operations and 2 MB per request. Every operation has a UUID `op_id`, a type, and integer Unix milliseconds `at`.

| Type | Additional fields |
| --- | --- |
| `status` | `task_id`, local `period` (`YYYY-MM-DD`), `status`, `step` |
| `event_upsert` | `event` containing a task card with at least `id` and `title` |
| `event_delete` | `id` of the event |
| `arrival` | `person_id`, local `day` (`YYYY-MM-DD`) |

The response is `accepted`, an array of accepted operation UUIDs. Remove only those UUIDs from the local pending queue. A retry of the same operation UUID and body is accepted again without creating another row or another completion event. Reusing a UUID for different content returns `409`. A batch is atomic; a rejected batch does not acknowledge or apply a subset.

For events, arrivals and statuses, a newer client `at` wins. Equal timestamps are resolved consistently by operation UUID. Older offline operations are still acknowledged and logged, without overwriting the current value. Event tombstones remain available for initial sync and incremental deletion. A status applied to a base task updates the actual GA PERSONAL occurrence and its history, and uses the existing cancellation of pending reminders. The tablet can also store statuses for its own synchronized events. A status may create the corresponding confirmed scheduled occurrence, but never invents a school-day/conditional assignment.

The tablet should keep its own pending operation for a `period|task_id` ahead of downloaded statuses until that operation is acknowledged, then merge by newest `at` and persist the returned cursor.

## Responses and deployment

The public frontend handles CORS for both device paths. Browser preflights (`OPTIONS`) do not require device credentials or contact the backend. HTTP/HTTPS loopback origins (`localhost`, `127.0.0.1`, `[::1]`, including `http://localhost:8799`) are allowed on any port. Additional hosted Kujtesa origins must be listed exactly, without a trailing slash, in the frontend server environment variable `GA_PERSONAL_DEVICE_CORS_ORIGINS` (comma-separated).

Preflight and GET/POST responses, including authentication, validation and gateway errors, return the allowed request origin, `Access-Control-Allow-Headers: Authorization, X-Device-Id, Accept, Content-Type`, `Access-Control-Allow-Methods: GET, POST, OPTIONS`, and `Vary: Origin`. Browser cookies are not enabled; actual requests still require both device credentials. Other PrimeFlow routes keep their existing CORS policy.

- `401`: missing/invalid code, invalid/mismatched tablet UUID, revoked code or removed authorizing membership.
- `403`: POST body UUID does not match the authenticated tablet, or a signed-in user lacks device-management permission.
- `404`: module disabled or a management target is absent.
- `409`: reused operation UUID with different content, or an occurrence cancelled in PrimeFlow.
- `422`: invalid request, unsupported status, unknown task, unconfirmed assignment/period or invalid cursor.

All production integration responses use `Cache-Control: private, no-store`. Device secrets are issued only through the authenticated module-admin management endpoints (`GET/POST /api/ga-personal/devices`, `POST /api/ga-personal/devices/{id}/revoke`). No household data is written into work tasks, work calendar events, work reports, attendance or Discord bridge configuration.

Apply the migration and deploy backend + frontend before issuing the real tablet code. No real code is included in source, tests or this handoff.

## Verification

Backend: `tests.test_ga_personal_devices`, `tests.test_ga_personal`, `tests.test_migration_graph`, using an explicitly supplied disposable `GA_PERSONAL_TEST_DATABASE_URL`. Browser: `npm run test:ga-personal`. Origin proxy: `npm run test:ga-personal:proxy`. TypeScript: `tsc --noEmit`.
