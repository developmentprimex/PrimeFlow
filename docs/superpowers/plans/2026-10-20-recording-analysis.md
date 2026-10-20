# Recording analysis implementation

Extend the existing recorder branch without deploying. Saved recordings remain independent of AI failures.

1. Add an explicit Alembic migration for durable analysis jobs, timestamped transcript segments and reviewable task proposals.
2. Extract at most 300 seconds of mono 16 kHz audio per request; reuse the existing OpenAI transport, Albanian transcription prompt and bounded meeting summarizer. Checkpoint transcripts and summary progress; use fenced database leases for restart recovery.
3. Authorize reads through recording RBAC, and restrict processing/task creation to the recording owner. Require explicit acknowledgement before sending audio/text to OpenAI.
4. Reuse Tasks creation with an internal transaction hook: commit the proposal/task link together, so retries cannot create duplicates. AI names and deadlines stay suggestions until reviewed.
5. Add an Albanian analysis panel to recording details, progress polling, retry, transcript, summary and editable task confirmation.
6. Verify provider validation, authorization, durable resume, idempotent task creation, migration, scoped frontend checks and local UI. Real provider calls require a configured key and explicit processing action.

Production uses the existing Celery worker/beat. A standalone worker runs the same durable job processor for isolated local development. No changes to existing scheduled modules or automatic task generation.
