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
detecting a host outage requires a probe on another host.
