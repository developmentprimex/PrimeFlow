# The gateway checks these local markers for each new request. Existing
# connections remain attached to their original upstream.
function Get-PrimeFlowRoute([ValidateSet('web','api')][string]$Surface) {
    $root = if ($env:PRIMEFLOW_GATEWAY_STATE) { $env:PRIMEFLOW_GATEWAY_STATE } else { 'C:\PrimeFlowOps\DeploymentGateway\routes' }
    if (-not [IO.Directory]::Exists($root)) { throw "Missing gateway state directory: $root" }
    $marker = Join-Path $root "$Surface-standby"
    $ports = if ($Surface -eq 'web') { @(3000,3301) } else { @(8080,8000) }
    $port = if (Test-Path -LiteralPath $marker -ErrorAction Stop) { $ports[1] } else { $ports[0] }
    return @{ port=$port; marker=$marker; primary=$ports[0]; standby=$ports[1] }
}

function Write-PrimeFlowRoute($Route, [int]$Port) {
    if ($Port -eq $Route.standby) {
        [IO.File]::WriteAllText($Route.marker, '')
    } elseif ($Port -eq $Route.primary) {
        [IO.File]::Delete($Route.marker)
    } else { throw "Invalid gateway port $Port." }
}

function Test-PrimeFlowOrigin([string]$Surface, [int]$Port, [switch]$Public) {
    if ($Surface -eq 'api') {
        $base = if ($Public) { 'https://api-flow.primexeu.com' } else { "http://127.0.0.1:$Port" }
        $path = '/health'
    } else {
        $base = if ($Public) { 'https://primeflow.primexeu.com' } else { "http://127.0.0.1:$Port" }
        $path = '/login'
    }
    $response = Invoke-WebRequest "$base$($path)?origin-check=$([guid]::NewGuid())" -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
    if ($response.StatusCode -ne 200 -or ($Public -and $response.Headers['X-PrimeFlow-Origin'] -ne "$Port")) {
        throw "Public routing or readiness check failed for $Surface on $Port."
    }
    if ($Surface -eq 'api' -and ($response.Content | ConvertFrom-Json).status -ne 'ok') {
        throw "API health check failed on $Port."
    }
}

function Set-PrimeFlowRoute([ValidateSet('web','api')][string]$Surface, [int]$Port) {
    $route = Get-PrimeFlowRoute $Surface
    $valid = if ($Surface -eq 'web') { @(3000,3301) } else { @(8000,8080) }
    if ($Port -notin $valid) { throw "Invalid $Surface port $Port" }
    Test-PrimeFlowOrigin $Surface $Port
    if ($route.port -ne $Port) {
        Write-PrimeFlowRoute $route $Port
    }
    try {
        Test-PrimeFlowOrigin $Surface $Port -Public
    } catch {
        if ($route.port -ne $Port) {
            Test-PrimeFlowOrigin $Surface $route.port
            Write-PrimeFlowRoute $route $route.port
        }
        throw
    }
}

function Wait-PrimeFlowDrain([int]$Port) {
    # Caddy uses a separate upstream connection per request. WebSockets stay
    # established until their clients leave. Never kill them to meet a timeout.
    $deadline = [datetime]::UtcNow.AddMinutes(20)
    do {
        $gatewayPids = @(Get-NetTCPConnection -State Listen -LocalPort 13000,18080 -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
        if ($gatewayPids.Count -ne 1) { throw 'Cannot identify the public gateway for connection draining.' }
        $busy = @(Get-NetTCPConnection -OwningProcess $gatewayPids[0] -ErrorAction Stop |
            Where-Object { $_.RemotePort -eq $Port -and $_.State -in @('Established','SynSent','CloseWait') })
        if ($busy.Count -eq 0) { return }
        Start-Sleep -Seconds 3
    } while ([datetime]::UtcNow -lt $deadline)
    throw "Port $Port still has active connections. Both versions remain available."
}
