# PX Desktop Recorder — Phase B preparation

This is a reviewable design/acceptance brief, not an implemented companion.
Phase A works independently. No desktop installer, localhost listener, remote
start/stop protocol, native audio driver or universal audio claim is included.

## Framework and capture adapters

Evaluate Electron using a supported stable release pinned at implementation time.
It can reuse the web library's session/chunk/upload contract and a React control
surface. Keep Node integration disabled in the renderer, enable sandbox/context
isolation, apply a restrictive CSP, validate every IPC payload/sender frame, deny
unexpected navigation/new windows, and allow capture only after an explicit local
user action and OS permission prompt. Do not expose raw filesystem or shell APIs.

Use separate platform adapters with a common lifecycle: select source, request
permissions, start, pause, resume, stop, dispose, and report input availability.
Return actual selected display/window identity and audio availability to the UI.
Do not make a generic Electron `audio:true` setting a universal-capture promise.

| Platform | Candidate capture path | Required verification |
| --- | --- | --- |
| Windows | Supported Windows screen/window capture plus WASAPI loopback and microphone capture, synchronized on a common clock | Whole display and selected-window video; system vs process-loopback scope; headphones/speaker transitions; device removal; sample-rate drift; pause and sleep |
| macOS | ScreenCaptureKit and supported Core Audio capture/tap paths for the selected OS/Electron version, plus microphone | Screen/system-audio/microphone permissions, signed-app usage descriptions and entitlements, denied/revoked access, display/window scope and OS minimum versions |

Electron's system-audio behavior changes with Chromium and macOS. Its current
documentation describes Core Audio tap behavior and separate permission concerns
on newer macOS versions; verify against the chosen pinned version and real signed
builds. Use native ScreenCaptureKit/Core Audio code when Electron cannot meet the
required source/audio contract. Windows requires actual WASAPI loopback validation;
do not assume a bundled FFmpeg build includes an appropriate input device.
Sources: [Electron desktopCapturer](https://www.electronjs.org/docs/latest/api/desktop-capturer),
[Apple ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit),
[Microsoft loopback recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording).

## Shared backend and durable local recovery

Keep PrimeFlow Web as the recording library. Authenticate the companion through
an explicit browser-based pairing/login flow; store narrowly scoped, revocable
device credentials in OS-protected storage (Windows Credential Manager/macOS
Keychain). Do not copy browser localStorage tokens into a desktop config file or
store credentials alongside media. Add device authorization/revocation endpoints
before shipping device credentials; the current Phase A endpoints still require
normal PrimeFlow access tokens.

For each capture, create the existing recording session with a stable UUID and
optional meeting ID. Store encoded fragments and a versioned manifest on local
disk using atomic writes; acknowledge them only after the backend verifies their
index/hash/size. Upload through the existing sequential binary chunk endpoints.
Bound the pending queue, pause on low disk/failed uploads, and retain recoverable
local data across application restarts. Persist a stop marker only after the
encoder's final fragment is safely written. Never append a new encoder's stream
to an interrupted stream: recover it as a separate/partial recording. Verify
finalization and playback using real output from each native adapter.

Keep platform-specific code below that lifecycle/upload boundary. AI processing
can later extract bounded audio segments server-side and reuse existing speech,
Mira/Discord voice services, tasks and 1H workflows. Do not send multi-hour video
to the existing small-file speech endpoint, and do not duplicate task management.

## Optional web-to-desktop controls

Do not open an unrestricted local port. Prefer a signed native messaging bridge
or a similarly authenticated OS channel. If localhost HTTP/WebSocket control is
needed, design and security-review it separately before implementation:

- Bind loopback only, use a random per-install endpoint and expiring one-use
  pairing challenge initiated in the visible app. Pair only to an allowlisted
  company HTTPS origin and authenticated PrimeFlow account/device.
- Validate exact Origin and Host on every handshake/request, defend against DNS
  rebinding, require a session-bound CSRF token and authenticated channel, reject
  wildcard/null origins, and never put credentials in query strings or logs.
- Require user-visible confirmation before starting capture; use OS prompts and
  keep a persistent app/menu-bar/tray indicator with an accessible local stop
  control. Remote commands must never bypass source selection or permissions.
- Rate-limit, expire/revoke pairings, reject replayed commands and mismatched
  accounts, and ship no generic file-read/execute/debug endpoint.

## Separate implementation/release acceptance

1. Prototype native capture adapters on real Windows and macOS machines. Record
   spoken/multitone system audio and microphone independently and together; decode
   the results to verify both sources and timestamp drift over a long meeting.
2. Package/sign notarized macOS and signed Windows builds with reviewed permission
   descriptions, update/revocation policy, isolated renderer/IPC and protected
   device credentials. No hidden startup recording.
3. Reuse and test the Phase A APIs under revoked auth, backend restarts, duplicate
   uploads, offline disk backlog, full disk, device changes and app crashes.
4. Test an entire display and selected application window with real Teams,
   Discord, Meet/browser and ordinary media playback. Document whether audio is
   whole-system or restricted to the selected application on each OS/version.
5. Run multi-hour A/V synchronization and recovery tests and confirm that only
   server-confirmed recordings appear saved in the web library.
6. Review platform findings, privacy/consent, authentication and the optional local
   control protocol in a separate implementation PR before any rollout.
