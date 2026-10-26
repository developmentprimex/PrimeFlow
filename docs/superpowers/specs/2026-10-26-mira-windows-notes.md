# Mira Windows call notes

Approved direction: Windows companion with manual Start/Finish, audio from the
call and microphone, Albanian transcript and Mira-style notes in PX Notes.
No speaker identification. Works independently of Discord/Teams meeting APIs.
Do not change or deploy the existing Discord Mira behavior for this feature.

Implement a Python/Tkinter Windows application with WASAPI loopback and microphone
device selection, visible recording state, source levels, and explicit recording
notice acknowledgement. Audio scope is the selected output device (including
other apps on it); recommend headphones. No auto-start or call detection.

Reuse existing PrimeFlow login/refresh over HTTPS; keep credentials/tokens only
in memory. Explicit login, no browser credential extraction or local listener.
Use a separate authenticated /api/mira-desktop API and dedicated tables; no bot
tokens or Discord session reuse. Reuse Mira's transcription transport and notes
rules with an explicit no-speaker instruction in the new service only.

Persist encrypted pending WAV segments and session metadata under the current
Windows user's local application data using DPAPI. Bound audio chunks to 10 s,
buffer memory and local backlog to 512 MiB, total session to 4 h. Stop visibly on
device/capture/storage faults. Keep incomplete sessions recoverable on restart,
never claim missed audio was captured, and never merge two encoder lifetimes.
Retry pending uploads; sequence and SHA-256 make server acceptance idempotent.
User may recover the selected stopped session after logging back in to its owner.
Finish checks all chunks, produces notes, and saves exactly one PX Note even if
the response is lost. Show transcript and notes and allow copying/opening PX Notes.
Keep raw audio only in the encrypted local pending queue and remove acknowledged
chunks; backend never persists raw audio. Preserve transcript and final notes.

Deliver source, launcher, and a reproducible Windows packaging command; build an
executable if dependencies are available. Verify synthetic capture, encryption,
offline recovery, API ownership/idempotency, and packaging. Live Teams/Discord
call acceptance requires a user-started call and explicit recording action; do
not silently record the user's devices for testing. Document unverified hardware.
