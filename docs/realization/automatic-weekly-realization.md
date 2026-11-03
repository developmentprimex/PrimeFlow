# Automatic weekly Realization implementation

## Dated daily summary and suggested letter

Weekly rows include expandable daily percentages, personal comments (with author),
dated task comments, checklist comments and close comments. Percentages come from
the live Daily metrics (`raw_plan_realization`); weekly task deduplication never
recalculates them with a different denominator. Leave, future days and missing
metrics are displayed explicitly instead of as zero. Weekly percentages continue
to use unique weekly obligations and the existing penalty/WFE rules.

The weekly review requires all nine saved boolean answers (including dated
rollups) before showing a proposal. Form defaults are not saved answers. The
first save keeps the dialog open and refreshes the proposal; a separate action
accepts it or saves a different letter. Editing answers hides the proposal until
the updated answers have been saved and the refreshed result received. The API
also rejects letter confirmation while answers are incomplete.

`facts_json.weekly_evaluation` proposes an advisory letter with its reason,
missing evidence and rule version. Complete plans start at B; one extra engagement
category permits A, and two permit A+. Recorded problems, repetition or impact on
another person's plan cap the suggestion at C. Three delay days or one explicitly
unexcused absence also cap complete work at C. A missed meeting or incomplete plan
gives D; a plan with no recorded completion/progress gives E. Two verified
unexcused absences give E. Approved personal absence with covered work gives M,
while full annual leave gives B. A missing baseline/report has no suggested letter.
Free-text comments alone never classify misconduct. Unclassified absences and
missing checklist answers are marked for review. Suggestions are provisional
while evidence is incomplete or the week has future days.

Managers can select A+/A/B/C/M/D/E in the weekly review. The selected letter is
stored as `review_level` in the existing append-only manager-review evidence,
with author, timestamp and supersession history. An explicit null restores the
automatic suggestion; omitting the field during a comment edit preserves it.
Recalculation cannot overwrite the manager selection. Locked weeks reject writes.
These letters are advisory review evidence and do not change payroll or the
existing formal approval workflow. No database migration is required.

## M3 manager review

Weekly M3 includes an optional, qualitative responsible-manager review for the
person's **Planning** and **Realization** dimensions. Each dimension is stored as
auditable `RealizationObservation` evidence for that weekly `period_id`; it is
separate from every Daily review and the two dimensions never overwrite each other.

The responsible manager can choose **Mirë**, **Shumë mirë**, **Kërkon veprim**,
or **Keq**. The rating is stored as `review_rating` in observation evidence; the
first two map to `POSITIVE`, and the last two map to `NEGATIVE`. A rating is never
implied: a manager may save a comment or checklist answers alone, in which case
`review_rating` is stored as `null` and the review reads back as **Pa vlerësim**.
Legacy reviews written before `review_rating` existed (the key is absent from
evidence) still derive a compatible rating from their marker.
No row means **Pa vërejtje**;
the system does not create a neutral/default observation. Edits supersede/void the
previous active observation so manager, timestamp, comment, and history remain
explainable.

This management judgment is excluded from automatic evidence calculations. It does
not change weekly progress, Plan Realization, Deadline Compliance, task
classification, outcome, grade, or symbol. Department managers are restricted to
their own department, STAFF cannot write reviews, and ADMIN retains broad access.

## Daily and weekly evaluation checklist

The reference evaluation checklist is represented as 17 explicit questions in
both Daily and Weekly Realization. Eight answers come from system evidence:

- completion of the plan;
- tasks with no progress;
- tasks still in progress;
- newly added tasks, split into completed, in progress, to do, and postponed;
- extra-task realization: total, completed, in progress, and without progress;
- closed tasks;
- attendance tardiness;
- unexpected absences.

The remaining nine are manager inputs because they require human judgment:
confirmed postponements,
respecting meeting times,
requested extra tasks, helped a colleague, gave a proposal,
the week's positive contribution, problems caused, impact on another
person's plan, and repetition after clarification. Boolean inputs accept Yes,
No. The manager can edit the final weekly narratives.

New answers entered in Daily are stored against that daily period/result.
Weekly gathers the latest answer per person, date and question. Existence
questions use any explicit Yes; a No requires all applicable elapsed days to be
answered. Meeting compliance uses any explicit No; a Yes requires complete
coverage. Missing answers are not silently treated as No. Leave and future days
are excluded from daily-answer coverage. Direct weekly answers override the
daily rollup without erasing its dated history; clearing an override restores it.
Legacy weekly answers remain weekly and are never assigned invented daily dates.
Corrections remain append-only, parent-week locks block daily answers, and saves
invalidate the daily and weekly AI analyses. The user-based question endpoint can
create a weekly result before a FINAL snapshot exists.

Daily Realization shows the same checklist after selecting a person. Automatic
facts still describe the selected day's task counts, extra-task status, and
attendance evidence; manual inputs describe the selected day. Managers fill them
in from either view, staff can read the result, and weekly completeness requires
all nine answers from dated rollups or direct weekly decisions. Ambiguous postponements or absences are
marked as automatic facts that still need manager confirmation rather than being
silently treated as resolved. The manual judgment does not change task
percentages, payroll, or deterministic policy grades.

The weekly page displays a compact table with filtered totals followed by a row
per employee. Managers and administrators can filter all departments or one
department, and all employees or one employee. The realization percentage counts
all completed work, including extras, against the baseline planned count, capped at
100% before subtracting a postponement penalty. Each unfinished postponed planned
task deducts `25 / planned_count` percentage points unless its postponement or daily penalty has been confirmed by Laurent Hoxha or Diellza Veliu. Deadline penalties use their existing higher weights; confirmed task/day evidence waives those too.
The final percentage is `max(0, min(100, completed_total / planned_count * 100)
- unconfirmed_penalty_points / planned_count)`, rounded to one decimal.
For example, five planned tasks, three completed planned tasks, two completed
extras, and two unconfirmed postponed planned tasks yield 90%. Confirming both removes those penalties and yields 100%. Completed tasks no
longer carry this penalty, even if they were postponed earlier in the week.
With no planned work, extras form the denominator and there is no plan penalty. Extras that remain
open do not add completion credit. Snapshot task facts and daily timeline entries
are deduplicated by task identity. Totals sum employee obligations, so shared
assignments contribute once per employee; they are not unique department tasks.

The Daily staff table lists tasks in separate columns using the exact categories
of the Plan RLZ popover. Columns without tasks among the filtered people are
hidden. Each penalized task has a confirmation action for Laurent Hoxha or
Diellza Veliu only, enforced by the API as well as the UI. The daily table fits
the page width with relative column sizes and compact comment/review controls.
Clicking a postponed or penalized task opens its original and new Start/Due,
dated postponement history, actor, reason and comment. Confirmation and revocation
are available inside that dialog, with no inline confirmation buttons.
Historical Start dates are recovered from audit events for the selected day.
Confirming removes its
penalty without completion credit or a change to the task status or plan weight.
Confirmations are per task/person/day, audited, revocable, and require renewed
confirmation after the evidence changes. Approved postponements also carry no
penalty in raw Plan RLZ. Weekly daily percentages and daily control reports read
the same live metrics; the Excel export includes a `Konfirmimet RLZ` evidence
sheet. Historical close-event snapshots remain unchanged; later decisions make
the live close state stale.
Quantity and deadline cells use completed/total with the remaining difference.
The manager comment is edited in the evaluation modal and only a short saved
preview remains in the table.
Automatic A+–E grading and verification requirements remain separate.

## Extra task counts and estimated progress

Daily and weekly tables distinguish **Ekstra gjithsej** (all report obligations
outside the initial plan, at any outcome) from **Ekstra të kryera** (the completed
subset). Daily extras can include newly added, reassigned, or carried-over tasks
absent from the day's baseline when they have execution evidence for that day.
Old overdue backlog and tasks created while planning a future day are excluded.
Extra completions include early and late work
outside that baseline. Weekly extras are deduplicated across the week.

Weekly extras are decided by **when the task was created**, not by the weekly plan
snapshot: a task created on or after Monday is extra, one that predates the week is
plan. The snapshot cannot decide it, because a plan saved mid-week already contains
the work added during that week, which used to collapse the extra count to near zero.
Creation dates are read from the database, and the weekly page warns when the plan
snapshot was captured after Monday.

An extra that was added, never started, and then pushed to a later date is left out
of `weekly_additional_count` and reported separately as
`weekly_additional_deferred_count`, shown next to the extra count as `+N shtyrë`.
It was never this week's work, so it belongs to the week it actually gets done. An
extra that was pushed but had progress still counts, as does one left untouched
without being pushed.
**Kryer gjithsej** already includes completed extras; do not add them again.
**Plan** displays the baseline count plus all extras, for example `5+2` when two
extra obligations exist, even if only one is completed. The realization denominator
remains the initial planned count.

The **Ekstra** column group has four subcolumns in order: **Të kryera**,
**Në progres**, **Pa progres**, **Gjithsej**. These three states partition the total.
Completed daily extras take precedence over progress; progress includes status,
classification, or positive progress recorded that day. The remaining unfinished
extras go under **Pa progres**, including waiting or postponed work without
recorded progress. Weekly extras use deduplicated task facts and their latest
state, preserving completed work across repeated daily entries.

Click any daily extra count to open that employee's tasks filtered to that state
or all extras. Extra tasks also show a badge identifying them as outside the
initial plan.

The daily staff table places the person and department filters in a header row
above **Emri mbiemri** and **DEP**. Person filtering keeps the staff table visible
and updates the summary; clicking a name or extra count separately opens task
details. Changing department resets the person filter and closes task details.
Staff rows are grouped in **DEV → GD → PCM** order, then other departments.
The chosen daily sort applies within each department, with name as the tie-breaker.

The daily staff table shows **Afat sot**, **Kryer**, and **Pa kryer** for every
task whose due date was the report date. A thick red border around **Afat sot**
indicates that the person has at least one task marked as deadline important on
that date. Immutable daily deadline evidence keeps a task in the report-date
population when its due date is moved later. **Pa kryer** is
`gjithsej - kryer` and includes postponed deadlines. Clicking a number opens
the person's task list with the matching deadline filter. Each task badge
explicitly says `Deadline` or `Deadline Important`, followed by `kryer`,
`pa kryer`, or `shtyrë`.

The daily staff table also shows **Sasi · produkte / pika**, with **Planifikuar**,
**Kryer**, and **+ / −**. These are unit quantities, separate from task counts
and the status-based realization percentages. Clicking a person's name shows
the quantities and their source for each task.

- A title such as `EF: FRG: 2/17 SHTO 2 KZH TE REJA` plans **2** units. The
  smaller number is always the daily target: `40/4` plans **4**, `17/4` plans
  **4**, and both `117/20` and `20/117` plan **20**. The current title supplies
  the target, so title corrections immediately update the quantity. Formatting markers
  are removed before reading the fraction. A deleted task falls back to its
  captured title.
  Completed units are distinct struck checklist points for the selected local
  day. Mirrored title/description points count once. Strike timestamps/history
  exclude previous-day work; reopened points do not count. Undated legacy
  strikes fall back only to the task's due/completion day. Striking the whole
  single-line quantity heading marks all its planned units complete. An explicit
  `DONE` recorded on the report day always marks all planned units complete,
  even when checklist strikes are partial or absent; older completions do not.
- Project tasks in the `PRODUCT` phase use the M3 product-count parser:
  `daily_products` is planned and `completed_products=N` is completed. A daily
  product progress record overrides current live values for its report day.
  Current notes do not credit completed products to a different day. Copied
  totals on `CONTROL` or nonproject tasks do not count as product production.
- Difference is completed minus planned: plan 2/done 1 displays **−1**;
  plan 2/done 2 displays **0 ✓**; plan 2/done 3 displays **+1**. Rows without
  quantitative targets display **—**. Transferred-out obligations are excluded
  from the previous owner's quantity totals.
Weekly rows follow the same department order and sort by name within each group.

## Boundary

Realization is an additive read model over existing PrimeFlow evidence. The
implementation does not mutate tasks, daily progress, meetings, attendance, or
weekly planner snapshots. It writes only the five existing Realization tables
and workflow audit entries.

## Weekly baseline

- Normalize the requested date to Monday and use Friday as the weekly end.
- Select the earliest PLANNED snapshot for the department/week.
- Select the latest FINAL snapshot for the same department/week.
- Idempotently create the WEEKLY/ALL period and pin the applicable policy.
- Pin snapshot IDs only while the period is OPEN. Later workflow states retain
  their historical snapshot references.
- A missing FINAL keeps the period OPEN and disables calculation.

## Evidence and attribution

Snapshot `task_items` and their existing `match_key` are the comparison source.
The historical employee set is the union of users captured in the PLANNED and
FINAL snapshot payloads. Planned obligations remain attributed to PLANNED
assignees. Additional work is attributed to FINAL assignees. When the final
assignee differs, the planned owner keeps the obligation and a separate actual
work-credit fact is added only when completion or positive progress supports
it. Live task rows, task audit logs, daily progress, attendance, meeting-linked
tasks, and append-only Realization observations supplement (but never replace)
snapshot facts.

Deadline and postponement decisions are conservative. A due-date edit alone is
not approval; where the existing audit trail cannot prove approval or rejection,
the fact is marked `NEEDS_REVIEW`. Deadline priority is snapshot due date,
original due date, last planned occurrence plus the pinned policy AM/PM cutoff,
then the week-end PM cutoff. Audit/progress evidence is bounded by the FINAL
snapshot timestamp so later task edits cannot become retroactive evidence.
Meeting participant rows are invitation evidence only and do not prove
attendance.

Additional work is visible as soon as it appears in FINAL without PLANNED. It
cannot raise A/A+ unless a verified `COMPLETED_EXTRA_TASK` observation proves a
completed or explicitly high-impact task and explicitly records that the work
is neither a duplicate nor a replacement for an unfinished planned obligation.

## Deterministic calculation

The policy service validates versioned JSON and applies first-matching rules.
The calculator upserts one existing `RealizationPersonResult` per snapshot user
and one existing `RealizationDepartmentResult`. It preserves review/final fields
and refuses recalculation after CALCULATED has advanced to REVIEWED.

Normalized question answers, classification reasons, IDs, source status, and
evidence are stored in `facts_json`. The Albanian narrative is produced by a
deterministic formatter. Department task totals de-duplicate snapshot match keys
instead of summing multi-assignee person counters.

## API and MCP boundary

The PrimeFlow API is the only workflow authority:

- `GET /api/realization/weekly` ensures and reads the pinned weekly period.
- `POST /api/realization/weekly/calculate` collects evidence and applies policy.
- result review, observation create/verify/void, approval, and locking use
  dedicated Realization endpoints with backend role checks and transactional
  audit entries.

The MCP server exposes matching high-level tools for ChatGPT. MCP resolves names
and calls these API endpoints; it never reads the database to write results and
never calculates a grade in the model. PrimeFlow remains fully usable without
MCP through the `/realization` page, including missing snapshot guidance,
calculation, evidence inspection, structured observations, question
confirmation, manager review, approval, and locking.

The dedicated MCP tools are:

- `get_weekly_realization`
- `calculate_weekly_realization`
- `review_weekly_realization_person`
- `add_realization_observation`
- `verify_realization_observation`
- `void_realization_observation`
- `approve_weekly_realization`
- `lock_weekly_realization`

Calculation and every later state-changing tool require an explicit user request
and still use the connected PrimeFlow account's normal permissions.

## Review, approval, and locking

- The **Vlerësimi** table cell opens one combined person modal. It contains the
  qualitative rating (including **Shumë mirë**), the manager summary, automatic
  facts as read-only context, and the manual checklist answers.
- Manual checklist rows offer explicit `E paplotësuar`, `Po`, and `Jo` values.
  Daily rollups and dated history
  are visible in the modal before a weekly override is saved.
- MANAGER: review results and verify observations in their department.
- ADMIN: same access across departments, plus approve and lock.
- Override requires a reason.
- Every review, approval, lock, observation verification, and void writes an
  `AuditLog` entry in the same transaction.
- LOCKED periods reject all mutations.

The status flow is `OPEN -> CALCULATED -> REVIEWED -> APPROVED -> LOCKED`.

Migration `0105_merge_realization_batches` merges the Realization policy branch
with the concurrently added question-task-batch branch without rewriting either
already-created migration.

