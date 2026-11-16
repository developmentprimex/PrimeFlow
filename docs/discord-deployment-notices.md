# Automatic deployment notices

The production deployment workflow sends a notice to every active PrimeFlow user
with an enabled Discord link and an existing personal channel in the configured
guild. This includes the person who pushed the change. Accounts without a linked
personal channel cannot receive this notice.

After checkout and change detection, before replacing environment files or
stopping services, `backend/scripts/notify_discord_deploy.py` sends:

> PrimeFlow po përditësohet (PUSH). Ju lutemi, mos bëni ndryshime për rreth
> 7 minuta. Ndryshimet gjatë përditësimit mund të mos ruhen.

Each recipient is mentioned individually. No broadcast role or `@everyone`
permission is needed. The script uses HTTP login only and does not start a second
Gateway bot or depend on the API being online. It reads the existing deployment
environment and uses a read-only database connection to find recipients.

The final workflow step sends a completion notice only after all deployment steps
and readiness checks succeed. A failed/cancelled deployment instead asks users
to wait for the technical team. There is no automatic “ready” message after a
fixed seven-minute timer. This is a notice, not an application editing lock.

Start and result delivery attempts are recorded in a JSON file in `RUNNER_TEMP`,
keyed by workflow run ID and attempt. The file contains channel/user IDs and
delivery outcomes, never credentials. A result is sent only to recipients whose
start message succeeded. An interrupted or failed delivery is not automatically
replayed, because its outcome may be uncertain. A fresh workflow attempt has its
own state and warns users again. Notification failures produce workflow warnings
and do not prevent deployment or service recovery.

The manual `/push` command and its bot-start completion behavior remain separate
and unchanged. Automatic notices do not create `discord_actions` records, so bot
startup cannot prematurely mark the whole deployment successful.

Verification: notification tests cover interrupted sends, partial delivery,
replays, completion recipients, failure wording and workflow ordering. Live
read-only verification checks the selected personal channels and bot send
permissions without posting test messages.

## Marker migration dependency

Migration `0189_two_task_markers` temporarily drops and recreates
`trg_sync_task_one_h_marker_history` in the same Alembic transaction before and
after resizing marker columns. PostgreSQL otherwise refuses to alter a column
referenced by an `UPDATE OF` trigger. The trigger function and history data are
preserved. Downgrade validates marker lengths before dropping the trigger.

The migration was verified in an isolated PostgreSQL schema, reproducing the
original error and checking upgrade, trigger-generated history, downgrade refusal
for combined markers, successful downgrade, and manual-clear history. The test
transaction was rolled back without modifying application rows.
