$ErrorActionPreference = 'Stop'
$env:PM2_HOME = 'C:\pm2-system'
$env:PATH = 'C:\npm-global;C:\Program Files\nodejs;' + $env:PATH
$m2Pm2 = 'C:\npm-global\pm2.cmd'
& $m2Pm2 stop primex-backend | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Unable to stop the primary API' }
# The authenticated M2 probe identified this listener as the stale PrimeFlow API.
# PM2 on Windows can leave its uvicorn child holding the old socket.
for ($attempt = 0; $attempt -lt 3; $attempt++) {
    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if (-not $listeners.Count) { break }
    foreach ($listenerId in @($listeners.OwningProcess | Sort-Object -Unique)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerId"
        if ($process.ExecutablePath -ne 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe') {
            throw "Unexpected process on the primary API port: $listenerId"
        }
        Write-Output "Stopping stale PrimeFlow port 8000 listener $listenerId"
        Stop-Process -Id $listenerId -Force
    }
    Start-Sleep -Milliseconds 500
}
if (@(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count) {
    throw 'Primary API port is still occupied'
}
& $m2Pm2 restart primex-backend | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Unable to restart the primary API' }
Write-Output 'M2_PRIMARY_RESTART_OK'
