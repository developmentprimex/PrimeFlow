# Mira Host: faster, direct staff conversations

Status: approved by the user ("implemento"); implemented and locally verified. Live voice validation and deployment remain outside this change.

## Intent

Make the speaking Primex Discord bot conduct short, natural Albanian conversations: current-slot task first, relevant progress and completion questions next, then unfinished earlier-slot tasks. Avoid repeated acknowledgements, repeating the employee's answer, and asking for information already supplied.

## Approach

Proposed: adjust the existing Realtime host instructions, provide task-specific progress evidence, and correct response scheduling in the existing worker. Keep the present model, voice, Discord bots, GA workflow, meeting slots, and permissions.

Changing only the prompt would leave the response-scheduling stall and slow turn detection. Rebuilding the voice stack or changing provider introduces unnecessary scope for this request.

## Conversation contract

- Address the person and go directly to a current-slot task: “Elsa, për këtë slot e ke ofertën. Ku ke mbërri?” This is an example, not a repeated script.
- If the task has no recorded progress/strike in the relevant reporting interval, ask neutrally about the missing update. Do not equate absence of a recorded update with proof that no work happened.
- Ask only the missing follow-up: why, when work continues, or when it finishes. Ask one short question at a time; an answer giving all three must not trigger three more questions.
- When progress exists, ask what remains and when it will finish; do not ask why nothing was done.
- Handle unfinished earlier-slot tasks after current-slot tasks: whether the person continues and when completion is expected. Keep the existing 11:50 earlier-slots and 16:00 blocked-task coverage.
- Do not repeat a task in both groups. Acknowledge completed tasks briefly; if all are complete, cover earlier outstanding work before asking what comes next.
- No mandatory “super”, “okej”, or thanks after every answer. Do not paraphrase an answer aloud. Move directly to the next unresolved question or person.
- The operational protocol can request opening documents and sharing a screen; it must not override the new current-first discussion order.

## Latency and correctness

- Use semantic VAD with medium eagerness instead of low, preserving custom interruption handling and the protection against a brief “aha/po”. Do not claim a fixed end-to-end response time.
- Resume exactly once after all tool results and the originating Realtime response have finished, regardless of which arrives first. Handle silence-only tools without producing an extra spoken answer.
- Supply the first/current task context with the turn handoff; avoid a redundant lookup when the needed facts are already present.
- Progress evidence for staff questioning must remain available even after GA has read it. Keep GA announcement deduplication intact.

## Boundaries

No changes to staff task statuses, postponement permissions, recording, web stop behavior, daily enablement, or deployment. No live Discord calls or staff notifications during verification.

## Verification

Use deterministic worker tests for both tool-result arrival orders, multiple tools, silence, queued system messages, and interruptions. Use backend tests for current-first handoff, task-specific progress evidence, GA deduplication, earlier outstanding tasks, and existing scheduling. A real Albanian voice check is still required after deployment to assess perceived pacing and naturalness.
