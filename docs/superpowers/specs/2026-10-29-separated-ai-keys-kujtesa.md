# Separate AI keys and manual Kujtesa meetings

The user supplied three OpenAI credentials and authorized their use: one for silent Mira notes, one for Mira Host meetings, and one for the separate Kujtesa family bot. Never put credential values in source, documentation, tests, logs or commits. Store deployment credentials as encrypted GitHub Actions secrets; local runtime values belong only in ignored dotenv files.

## Chosen approach

Keep API calls on the server and select a dedicated credential by function. `MIRA_NOTES_OPENAI_API_KEY` serves silent Discord/desktop transcription, notes and the work meeting memory. `MIRA_HOST_OPENAI_API_KEY` serves work Host Realtime, Host summaries and per-person notes. `KUJTESA_OPENAI_API_KEY` serves only the private family host. Existing unrelated AI features keep `OPENAI_API_KEY`. A missing dedicated key disables that role rather than borrowing another role's credential.

Separate processes with a global key override would miss background summaries; a single shared key would not satisfy the user's request. Explicit selection at the server request boundary covers both live and background calls.

## Kujtesa

The user explicitly chose manual Discord commands. Add `/kujtesa fillo` and `/kujtesa ndalo` to the existing separate adapter. The initiating active GA PERSONAL administrator must be in a private family voice channel, in the configured guild. Only mapped active family members and the bot may see the voice channel; stop if anyone else joins. Reuse the established Node audio worker, without importing work meeting services or exposing the long-lived API key to the bot. Start Realtime with a short-lived client secret from the private bridge. The conversation runs in Albanian, reviews today's existing family tasks with the girls in turn, asks about progress/help and does not mark tasks complete from model guesses. Task confirmations continue through existing buttons. No automatic joins, reminders, DMs or test messages are enabled by this work. Bound meetings to 55 minutes, handle stop/start races, close child processes, and recheck the family authorization during a meeting.

Family content must never enter work Mira tables, memory or PX Notes. The first version holds a live conversation with a task brief; it does not introduce a stored recording or a second task database.

## Verification and delivery

Use synthetic credentials/transports and isolated test data. Prove each role's outgoing Authorization header, ensure the general recording feature still uses its general key, and cover missing credentials. Verify private grant, actor/guild validation, family-only context, startup cancellation, duplicate start, stop/timeout and no automatic meeting. Check key validity without printing values. Retain the earlier migration-head fix as a prerequisite until PR #187 is merged. Prepare reviewable changes and install the separate adapter locally only with filesystem approval; do not merge to main without authorization.
