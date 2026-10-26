$ErrorActionPreference = 'Stop'
$env:PM2_HOME = 'C:\pm2-system'
$env:PATH = 'C:\npm-global;C:\Program Files\nodejs;' + $env:PATH
$m2Pm2 = 'C:\npm-global\pm2.cmd'
foreach ($api in @(@{Name='primex-backend';Port=8000}, @{Name='backend-api-flow';Port=8080})) {
    & $m2Pm2 stop $api.Name | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Unable to stop $($api.Name)" }
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $listeners = @(Get-NetTCPConnection -LocalPort $api.Port -State Listen -ErrorAction SilentlyContinue)
        if (-not $listeners.Count) { break }
        foreach ($listenerId in @($listeners.OwningProcess | Sort-Object -Unique)) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerId"
            if ($process.ExecutablePath -ne 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe') {
                throw "Unexpected process on port $($api.Port): $listenerId"
            }
            Write-Output "Stopping stale $($api.Name) listener $listenerId"
            Stop-Process -Id $listenerId -Force
        }
        Start-Sleep -Milliseconds 500
    }
    if (@(Get-NetTCPConnection -LocalPort $api.Port -State Listen -ErrorAction SilentlyContinue).Count) {
        throw "API port $($api.Port) remains occupied"
    }
    & $m2Pm2 restart $api.Name | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Unable to restart $($api.Name)" }
}
Write-Output 'M2_FAST_API_RESTART_OK'
