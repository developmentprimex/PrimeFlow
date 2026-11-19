# PrimeFlow API monitoring

The Windows task `PrimeFlow-ApiMonitor` runs under SYSTEM once per minute.
It checks HTTP health for ports `8000`, `8080`, and the public API. It compares
the live PM2 process list with the Windows listeners. On `8080`, a listener in
the Uvicorn process tree is valid. It also detects an active legacy public API
service competing with `backend-api-flow`.

Two consecutive observations open or resolve an alert. HTTP and listener
failures on one local port share one incident. A changed diagnostic or PID
within an open incident updates the log. The monitor sends a Windows event
and a Discord message when the incident opens or clears. Each message includes
the service, port, error, time in UTC, and PM2 status. The monitor tracks
delivery separately and retries a failed delivery on the next run.

- Windows Application log source `PrimeFlowApiMonitor`, event `901` for issues
  and `902` for recovery.
- Discord `#primeflow-monitorim`, using the existing bot identity. The
  destination ID comes from `discord-channel.txt` beside the monitor. The
  monitor checks the channel name and guild before delivery.
- Rotating diagnostics and alert state in `C:\PrimeFlowOps\PrimeFlowApiMonitor\state`.

The monitoring files live outside the Actions checkout. The monitor queries the
existing PM2 daemon through its local RPC pipe. It does not start a daemon or
stop or restart any services. `/health` covers HTTP availability. Database
readiness requires a separate check. A host outage also stops this monitor, so
the independent probe keeps its own observations during a host outage.

The Windows logon task `PrimeFlow-ExternalMonitor` on DESKTOP-0I1307I runs
`primeflow_external_monitor.py` every 30 seconds while the account is signed
in and the computer is awake. It checks the public API health payload and the
public login HTML in parallel. UTC timestamps, HTTP status (when available),
and elapsed milliseconds are retained in rotating logs under
`%LOCALAPPDATA%\PrimeFlowOps\ExternalMonitor\state\external.log`. It publishes
the latest sample to the server monitor's state directory as `external.json`.
The server checks its age and reports external endpoint failures or missing
measurements through the existing delivery channels. Discord delivery requires
the server monitor to be running.

To review a deploy, take the UTC start and finish times from GitHub Actions.
Compare the external samples before, during, and after that window with
`monitor.log` on PX. Each server cycle records CPU utilization during
collection, available physical memory in MiB, and milliseconds per probe.
Keep gaps and failed samples visible when reporting availability.
