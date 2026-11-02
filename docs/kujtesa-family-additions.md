# Kujtesa: family routines in PrimeFlow

The downloaded bot's family functions are integrated into the existing private
GA PERSONAL bridge. PrimeFlow remains the task/status/schedule store. The bot
does not execute the downloaded scripts, open their SQLite database, load their
dataset, or use the Cloudflare device token. Existing Discord and Realtime
credentials, delegation, DM routing and manual AI conversations are preserved.

## Install and select the routines

Apply migration `0180_kujtesa_family` with the normal backend migration process,
then install the updated adapter and its dependencies together:
`primeflow_bot.py`, `family_commands.py`, `voice_host.py`, and
`requirements-primeflow.txt`. The repository's existing PM2 deployment runs the
adapter from these files. No separate process or scheduler is added.

In GA PERSONAL → Cilësimet → Kujtesa · Discord, choose **Shiko shtesat para
importimit**. The preview lists every definition and the create/update/preserve
decision. **Importo rutinat në PrimeFlow** applies that exact version of the plan;
a concurrent edit requires a new preview. Imported source aliases retain the
existing template UUID. Untouched imported definitions can be updated; manually
edited and archived definitions remain as they are. Completion history and
interacted-with or explicitly rescheduled occurrences are preserved. Untouched
pending occurrences from today onward receive the reviewed time and steps,
including dates already generated in the rolling window; obsolete reminder
claims are cancelled. Importing twice does not create parallel templates.

The pack includes Nala's five timed duties, balcony and Roki water, morning
preparation, assigned rooms with extra Friday–Sunday steps, reading/reflection/
study, planned school returns, Hollywood and volleyball, heating, food, kitchen,
flowers, braces, laundry, Sunday spaces and the six-week care cycle. Planned
returns have an agenda time without triggering an alarm or recording an actual
arrival. Braces use a three-calendar-day cycle from 2026-11-02; care uses a
six-calendar-week cycle from Sunday 2026-11-22. Both can be edited in PrimeFlow.

Existing configured Nala rotations are preserved and used by **all** functions.
If none exists, the pack installs Monday–Saturday fixed owners and the Sunday
cycle from the downloaded bot. It never silently substitutes a second rotation
for `/nala`, cards or agendas. Babi's Friday–Sunday chore is an agenda note:
the established four-person account model is unchanged, and the note does not
create an account or falsely attribute completion to another family member.

## Sending and commands

Enable **Dërgo agjendën e ditës** and/or **Njofto zgjimin dhe kthimin në shtëpi**
in the same Discord settings. Both the existing administrator grant and the
bot's `REMINDERS_ENABLED=1` are required for every automatic send, including
agendas and presence. Setting the bot switch to `0` prevents all outgoing
scheduled messages. Explicit commands still receive private replies.

Agendas are sent once per date and destination after 06:00, using actual
PrimeFlow occurrences including untimed tasks, plus synchronized local-app
events. DM tasks remain private; off tasks are omitted. Extra local-app events
default to DM, including Lirza → Gane. Shared event text is deduplicated per DM.
Presence is explicitly opted into the configured private family channel.
Long agendas are split into bounded messages.

`/sot`, `/mengjesi`, `/nala`, `/ore`, `/kush`, `/vikendi`, `/ndihme` read the
current authorized family state. `/zgjova` and `/erdha` record actual presence
with retry deduplication. `/kujto` is administrator-only and queues the next
open timed Nala task through the existing prepare/result delivery mechanism;
it respects the sending switch. `/provo` uses a private temporary demo and
cannot change actual tasks. Commands work in the configured family text
channel or a mapped user's DM. Replies never mention everyone or roles.

Morning and room duties with the same routine key, time, owner, destination and
phase share one Discord card. Buttons change all unfinished member duties in
one transaction with a separate history entry for each. A changed owner,
schedule or destination invalidates the old routine. Individual duties remain
visible and editable in PrimeFlow. Existing -5/0/+5 reminder phases and snooze
from the current time are retained.

Nala's afternoon card offers **Po, e ka bërë kakin** and **Jo, dalja në 19:30**,
including after completion. A current-day “jo” moves an unmodified 20:30 evening
walk to 19:30 if that time is still in the future; “po” restores an automatically
changed walk to 20:30. Explicit reschedules/edits and closed tasks are preserved.
Old schedule phases are cancelled and sent cards refresh from PrimeFlow.

`/zeri` plays a two-note chime for people already in the private family voice
channel. It requires libopus and the Python voice dependencies. It never joins
automatically or interrupts an AI conversation. `/dil` disconnects only this
short chime connection. The existing `/kujtesa fillo` and `/kujtesa ndalo` remain
the manual AI conversation controls. Voice privacy checks are reused.

## Local app and delivery reliability

The existing `/api/ga-personal/device/state` and `/device/ops` protocol is
extended additively with `wakes` and `kaki` state arrays and two operations:

```json
{"type":"wake","op_id":"<UUID>","at":1793602800000,"person_id":"rrita","day":"2026-11-02"}
{"type":"kaki","op_id":"<UUID>","at":1793602800001,"date":"2026-11-02","answer":"jo"}
```

They use the same device authorization, atomic batch and accepted-UUID retry
protocol. Kaki answers merge by `(at, op_id)`; historical offline answers never
reschedule today's walk. Discord answers are exported in this same state.
Arrivals and wakes recorded through PrimeFlow/Discord are also returned to
devices. Weekday-specific and multi-day definitions export concrete dated
occurrences, preserving their actual steps and dates.

The private `ga_personal.discord_notices` table holds agenda/presence claims and
delivery outcomes. Every send rechecks the current grant, active members,
destination and latest content. The existing receipt file durably records
uncertainty before sending. Restarted or expired claims are never blindly
replayed. Failed private deliveries do not fall back to a shared channel.

Changes in this work are local: no production migration, import, restart,
Discord send or Git push is performed by the implementation itself.
