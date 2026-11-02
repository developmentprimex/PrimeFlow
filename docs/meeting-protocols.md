# Meeting protocol downloads

Recording details offer English / Deutsch and Generate and download Word after
analysis is READY. Editing happens in the downloaded DOCX, not in the application.
Generation is explicit and owner-only. Downloads follow the existing recording
read policy (currently all authenticated active accounts). Deleted recordings
cannot be downloaded or processed.

The source EN/DE templates are included in `backend/app/templates/meeting-protocol`.
They were copied from the user's FINAL meeting protocol templates on Z:. Runtime
generation does not require that drive. Only document.xml and settings.xml are
modified; header, logo, footer, relationships and other template parts are
preserved byte-for-byte. Word updates the existing page-number fields on open.
Rows expand with content; the table header repeats across pages.

The existing recording analysis worker processes durable protocol jobs before
each analysis tick. Each language has one cached DOCX in PostgreSQL. Repeated
requests/downloads reuse it. Failed jobs preserve source snapshots, paid response
checkpoints and completed content. There is no regeneration/editor endpoint and
no automatic task creation. Backups must include recording_protocols; its rows
cascade when recording metadata is hard-deleted.

The transcript is the factual source; summaries and action proposals guide the
extraction. Original evidence quotes are validated against the transcript for
every generated field, including responsibility, dates and status. Quotes are
retained internally and omitted from Word. This validates provenance, not the
semantic accuracy of every claim or the accuracy of transcription. Unknown
fields remain Not specified / Nicht festgelegt. Long transcripts are chunked
with overlap and checkpointed reduction.

## Activation

Apply migration `0179_recording_protocols` before starting the updated API and
recording worker. Use the normal deployment migration workflow; do not run
unrelated migrations blindly against a shared database. Include both DOCX files
in the backend deployment. Restart API and the existing recording-analysis
worker (or Celery workers), and deploy the frontend. No new dependencies are
required. Existing RECORDING_ANALYSIS_ENABLED, RECORDING_ANALYSIS_MODEL and
OPENAI_API_KEY settings are reused.

## Verification on 2026-11-02

- Six protocol unit/integration tests passed against isolated local PostgreSQL,
  including migration upgrade/downgrade, EN/DE cache isolation, access, deletion,
  expired leases and retry after render failure without another AI call.
- Four existing recording-analysis API tests and eighteen provider tests passed.
- Six Chromium browser tests passed, including direct Word downloads in both
  languages, no editor and cached downloads after reload.
- Scoped TypeScript and ESLint passed.
- Template package preservation and dynamic rows were checked structurally.
  Full visual Word QA remains pending; native Word automation was unreliable and
  the bundled document-rendering dependencies were unavailable in this environment.
- A live request with invented test text was rejected with HTTP 401 by OpenAI:
  the configured general API key is invalid. No real meeting was sent. Real-model
  output quality and schema acceptance remain unverified until configuration is
  corrected. No shared-database migration or production deployment was performed.
