# Kujtesa / PrimeFlow bridge

The separate Kujtesa bot reads due GA PERSONAL reminders through a dedicated,
secret-authenticated API. It never reads the work Mira database, a seed dataset,
or a household SQLite task store in PrimeFlow mode.

## Runtime

### Server deployment, like work Mira

The PrimeFlow Actions workflow manages a separate PM2 process named
`primeflow-kujtesa`. Work Mira remains `primeflow-discord`. This setup does not
need the Desktop handoff folder or an open PowerShell window.

In the repository that runs the deployment (`developmentprimex/PrimeFlow`), set:

| Actions setting | Name | Value |
| --- | --- | --- |
| Secret | `KUJTESA_DISCORD_TOKEN` | The new dedicated Kujtesa token from the existing local bot `.env` |
| Secret | `GA_PERSONAL_DISCORD_BRIDGE_SECRET` | The same existing private `PRIMEFLOW_GA_BRIDGE_KEY` used by the bot and API |
| Variable | `KUJTESA_ENABLED` | `true` |
| Variable | `KUJTESA_REMINDERS_ENABLED` | `true` to deliver; `false` for connection-only operation |

Never overwrite Mira's `DISCORD_BOT_TOKEN` or `DISCORD_BRIDGE_SECRET`.
The bot token is optional until configuring Kujtesa; without it the existing
deployment continues with Kujtesa disabled. Explicitly enabling with missing
secrets fails configuration rather than using work Mira's credentials.

After pushing these changes, the workflow writes a separate private file at
`C:/PrimeFlowData/Kujtesa/.env`, installs its dependencies, checks the API bridge,
starts one PM2 worker and verifies a fresh heartbeat for the deployed build.
The worker uses `http://127.0.0.1:8000/api` on the same server. This leaves the
browser-facing API URL and the work bot unchanged.

Delivery receipts and the readiness file live under `C:/PrimeFlowData/Kujtesa`,
outside the Actions checkout, and survive deployments. The existing PM2 save
and boot recovery also restore this process after a server restart. The module's
existing administrator grant and task destinations still apply.

Wait for the **Start Kujtesa Worker** step to pass, then stop the Desktop copy
with Ctrl+C. Keep only the server worker active. The persistent outbox claims
prevent the same reminder phase being sent twice during handover.

To inspect on the server:

```powershell
pm2 status primeflow-kujtesa
pm2 logs primeflow-kujtesa --lines 30 --nostream
```

To disable it, set `KUJTESA_ENABLED=false` in Actions Variables and run the deploy
workflow manually. To pause outgoing reminders while retaining the connection,
use `KUJTESA_REMINDERS_ENABLED=false` instead. Manual workflow runs reconfigure
and restart the worker even without new backend code.

### Standalone/local development

Install `primeflow_bot.py` beside `kujtesa.py`. Use Python 3.11+ and the bot's
existing `discord.py` / `aiohttp` dependencies. Install the bridge dependencies
with `python -m pip install -r bot/requirements-primeflow.txt`; this includes
`tzdata` for Europe/Belgrade on Windows.

Keep these values only in `bot/.env`:

```dotenv
DISCORD_TOKEN=<new dedicated bot token>
PRIMEFLOW_API_URL=http://127.0.0.1:8000/api
PRIMEFLOW_GA_BRIDGE_KEY=<same private key as API server>
REMINDERS_ENABLED=0
SEND_PRACTICE_ON_STARTUP=0
```

The API server uses `GA_PERSONAL_DISCORD_BRIDGE_SECRET` and the existing
`GA_PERSONAL_ENABLED=true`. A remote API URL must use HTTPS. The bot token is
never sent to PrimeFlow. Never reuse work Mira's token or bridge key.

Run `python bot/primeflow_bot.py --check` to test only API authentication. This
does not connect to Discord, claim reminders, change task state or send messages.
After installation, the existing `python bot/kujtesa.py` entry point also selects
PrimeFlow mode whenever `PRIMEFLOW_API_URL` is set. Do not run both processes.

## Activation

1. Deploy the API and apply migration `0174_ga_personal_discord`. It creates only
   the private outbox. Existing provisioned outboxes are adopted non-destructively.
2. In GA PERSONAL, the unlocked module administrator opens Settings > Kujtesa,
   enters the server/channel and eligible user IDs, and explicitly grants access.
   Missing IDs are allowed. Lirza's private reminders go to Gane's mapped account.
3. Set each task's destination to private DM, family channel, or off. Existing
   snapshots without a destination default to DM. Untimed tasks never notify.
4. Replace any exposed bot token locally. Install the bot in the configured guild.
   For channel delivery, deny View Channel to @everyone; allow only the mapped
   family members and the bot. Other role/member channel grants are rejected.
   Discord server administrators inherently retain their infrastructure access.
5. Start one bot process with `REMINDERS_ENABLED=0` first. The UI shows heartbeat
   status but no cards are sent. Set `REMINDERS_ENABLED=1` and restart only when
   ready for actual reminders. Both the bot switch and administrator grant must
   be enabled. Test actual channel/DM permissions before relying on delivery.

## Behavior and limits

- Polls every 15 seconds: reminders are claimed at -5, 0 and +5 minutes in UTC,
  rendered using Europe/Belgrade. Each phase has a five-minute delivery window;
  expired phases are skipped instead of flooding after downtime.
- Acknowledgement/start does not regenerate phases. Completion/help/archive and
  edits cancel pending/claimed reminders. Before every send the bot revalidates
  the latest time, ownership, membership, destination and delegation.
- Buttons write to the same PrimeFlow occurrence. Actor, exact sent message,
  guild/channel and latest assignment are rechecked; interaction IDs deduplicate
  retries. Snooze schedules the new time; old cards become inactive.
- Sent cards are refreshed from PrimeFlow. Changes in ownership/destination
  replace obsolete content with a brief notice and disable their buttons.
  Deleted cards are retired; inaccessible cards retry after five minutes so
  they cannot block updates for the rest of the family.
- Failed/blocked private messages never fall back to the shared channel. The UI
  reports failures and uncertain sends. A worker crash during sending is treated
  as uncertain and never automatically replayed, avoiding duplicate reminders.
  Local `.primeflow-receipts.json` holds only delivery receipts until the API
  acknowledges them; keep it private and preserve it across restarts.
- A change of module password, removal of the delegating administrator, or an
  explicit disable revokes the bot grant. Browser extra-password checks remain
  unchanged. The UI administrator can regrant the limited bot access afterward.
- This adapter delivers task reminders and buttons. It does not use AI, provide
  work Mira conversations, make ringing calls, or change phone notification tones.

For local adoption use `backend/scripts/configure_kujtesa_bridge.py` in preview
mode first. Apply requires the exact database host/name. It creates only this
private table, preserves task/history data and the Alembic stamp, installs the
adapter and keeps sending disabled. Restart the local API after updating its key.
