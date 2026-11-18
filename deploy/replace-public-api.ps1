$ErrorActionPreference = 'Stop'
. ./deploy/origins.ps1
Set-PrimeFlowRoute api 8000
Wait-PrimeFlowDrain 8080
Set-Location backend

$python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
$port = 8080
$processName = "backend-api-flow"

Write-Host "Replacing public API backend on port $port from current checkout..."
cmd /c "pm2 delete backend-api-flow || ver > NUL" | Out-Host
cmd /c "pm2 delete primex-public-api || ver > NUL" | Out-Host

# Kill any orphaned process still holding the port (a squatter outside PM2
# keeps serving stale code and makes health checks pass against old builds).
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object {
    Write-Host "Killing stale listener PID $_ on port $port"
    Stop-Process -Id $_ -Force
  }

# The public API terminates browser WebSocket connections and must
# consume Redis notification events for realtime alerts and sounds.
$env:REDIS_ENABLED = "true"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:APP_TIMEZONE = "Europe/Budapest"
# The primary API on port 8000 exclusively owns the shared Outlook
# calendar scheduler. Running it here as well causes duplicate imports
# and competing long-lived database work.
$env:MS_CALENDAR_SYNC_ENABLED = "false"
# This process serves every browser request with several workers, and
# each worker runs the startup hooks. All schedulers therefore belong
# to the primary API on port 8000 (or their own PM2 process) only;
# leaving one enabled here would run it once per worker.
$env:SYSTEM_TASK_SCHEDULER_ENABLED = "false"
$env:REPORT_SCHEDULERS_ENABLED = "false"
$env:TOMORROW_PRINT_REPORT_SCHEDULER_ENABLED = "false"
$env:TODAY_PRINT_REPORT_SCHEDULER_ENABLED = "false"
$env:STD_FEEDBACK_SYNC_ENABLED = "false"
$env:MEETING_REMINDER_SCHEDULER_ENABLED = "false"
# Keep the total across workers well under PostgreSQL's connection limit.
$env:DB_POOL_SIZE = "5"
$env:DB_MAX_OVERFLOW = "5"
$env:APP_BUILD_SHA = "$env:GITHUB_SHA"
$env:RUNNER_TRACKING_ID = ""
# The server has 8 slow cores and one Python process can use only one,
# so a single worker stalled every user behind any heavy request.
cmd /c "pm2 start `"$python`" --name $processName --cwd `"$PWD`" -- -m uvicorn app.main:app --host 0.0.0.0 --port $port --workers 4 --timeout-keep-alive 15 --backlog 2048"
if ($LASTEXITCODE -ne 0) { Write-Error "PM2 public API start failed"; exit 1 }

$ok = $false
$expected = "$env:GITHUB_SHA"
$lastBuild = "<no response>"
$uri = "http://127.0.0.1:$port/health"
for ($i = 0; $i -lt 40; $i++) {
  try {
    $resp = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 3
    $body = $resp.Content | ConvertFrom-Json
    $lastBuild = "$($body.build)"
    Write-Host "Public API health check attempt $($i + 1)/40: HTTP $($resp.StatusCode) build=$lastBuild"
    if ($resp.StatusCode -eq 200 -and $lastBuild -eq $expected) {
      $ok = $true
      break
    }
    Start-Sleep -Seconds 2
  } catch {
    Write-Host "Public API health check attempt $($i + 1)/40: no response yet"
    Start-Sleep -Seconds 2
  }
}
if (-not $ok) {
  Write-Error "Public API /health not serving deployed build $expected (last seen: $lastBuild). A stale process may be holding port $port."
  exit 1
}

Set-PrimeFlowRoute api 8080
