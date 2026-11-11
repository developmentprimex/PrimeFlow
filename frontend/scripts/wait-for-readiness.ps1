function Wait-PrimeFlowFrontend {
    param(
        [string]$ExpectedDeploymentId = "",
        [string]$BaseUri = "http://127.0.0.1:3000",
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 240,
        [ValidateRange(1, 60)][int]$RequestTimeoutSeconds = 15,
        [ValidateRange(1, 30)][int]$RetrySeconds = 2
    )

    # Cold starts on the Windows runner can take over a minute, and the first
    # page request can still be slow after Next prints "Ready". Bound elapsed
    # time rather than counting short requests that all time out during warmup.
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $uri = "$($BaseUri.TrimEnd('/'))/admin-tasks?deploy-check=$ExpectedDeploymentId"
    $attempt = 0
    $lastFailure = "No request completed."
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $attempt++
        $remaining = [Math]::Ceiling($TimeoutSeconds - $timer.Elapsed.TotalSeconds)
        $requestTimeout = [int][Math]::Min($RequestTimeoutSeconds, $remaining)
        try {
            $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -Headers @{ "Cache-Control" = "no-cache" } -TimeoutSec $requestTimeout -ErrorAction Stop
            Write-Host "Frontend readiness attempt ${attempt}: HTTP $($response.StatusCode) after $([int]$timer.Elapsed.TotalSeconds)s"
            if ($response.StatusCode -eq 200) {
                if ([string]::IsNullOrWhiteSpace($ExpectedDeploymentId) -or $response.Content.Contains("?dpl=$ExpectedDeploymentId")) {
                    Write-Host "Frontend is ready (deployment: $ExpectedDeploymentId)."
                    return $true
                }
                $lastFailure = "HTTP 200, but the page does not contain deployment $ExpectedDeploymentId."
            } else {
                $lastFailure = "HTTP $($response.StatusCode)."
            }
        } catch {
            $lastFailure = $_.Exception.Message
        }
        Write-Host "Frontend readiness attempt ${attempt}: $lastFailure"
        $remainingMs = [Math]::Floor(($TimeoutSeconds - $timer.Elapsed.TotalSeconds) * 1000)
        if ($remainingMs -gt 0) {
            Start-Sleep -Milliseconds ([int][Math]::Min($RetrySeconds * 1000, $remainingMs))
        }
    }
    Write-Host "Frontend readiness timed out after $TimeoutSeconds s. Last failure: $lastFailure"
    return $false
}
