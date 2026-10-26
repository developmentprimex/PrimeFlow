# Mira Windows verification — 26 October 2026

- 24 desktop and deployment tests passed with the pinned capture/client/numerical dependencies.
  Covers mixed sample rates, clipping, silence, short tails, late audio, lazy
  flushing, suspend both before and during queue wait, DPAPI encryption, corrupt
  encryption rejection, offline recovery, durable receipt deletion/crash windows,
  account scope, immutable finish arguments, token refresh, HTTPS/redirect
  handling, login UI locking and asynchronous account disposal.
- 21 backend tests passed on explicitly disposable local PostgreSQL 17,
  including migration upgrade/downgrade/upgrade, API auth and owner isolation,
  WAV bounds/timings, ordering, concurrent replay, transcription retries,
  summary checkpoint recovery/lease fencing and exactly-once PX Note creation.
  Temporary PostgreSQL was stopped afterward. The small API-only subset was
  rerun after exposing the configured frontend URL: 7 passed.
- Independent read-only review findings were corrected. Suspend recovery emits
  only valid bounded chunks and marks missing capture as partial.
- Windows executable built with PyInstaller; packaged self-check loaded the
  WASAPI driver and round-tripped encrypted synthetic PCM. Packaged GUI opened
  and closed successfully with device capture disabled.
- Device inventory recognized 2 WASAPI loopback devices and 1 microphone on
  this computer. Enumeration did not open recording streams.
- `git diff --check` passed. No Discord or Teams call was recorded for verification.

## Production activation

- Migration `0165_mira_desktop` applied after the original project-activity
  migration `0164_project_is_active` was restored from the canonical repository.
  Existing M2 additions in model/router registration were preserved.
- Both API ports 8000 and 8080 expose the new routes. Public HTTPS
  `https://api-flow.primexeu.com/openapi.json` includes desktop sessions and
  finalization; unauthenticated capabilities returns 401 as expected.
- An older API listener on port 8000 was replaced after explicit user approval.
  Discord bot source hashes remained unchanged; the bot was not restarted.
- App installed to `%LOCALAPPDATA%\Programs\PrimeFlowMira\Mira.exe` with
  Desktop and Start-menu shortcuts. Installed synthetic self-check passed.
- PX Notes integration updated: desktop notes reuse the existing Mira avatar,
  violet styling and Mira notes filter. The note's transcript link resolves
  unnamed passages for its owner. The marker applies to existing saved notes.
  25 focused backend tests passed, including the actual PostgreSQL marker query
  and transcript ownership checks. Deployment preserves revision166's existing
  system-task changes and performs no additional migration.

Not yet verified: a real call using the user's actual headset/Teams/Discord
configuration, multi-hour acoustic drift, OS device changes, or an authenticated
real-call save using the user's account. The app deliberately stops on capture faults/suspend; it does not
claim uninterrupted recording through those events. The public connection is
active; the user logs into the companion normally to start a real call.
