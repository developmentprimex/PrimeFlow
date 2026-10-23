$ErrorActionPreference = 'Stop'

function Test-PrimeFlowVoiceWorker {
    param([string]$CommandLine, [string]$VoiceDirectory)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $command = $CommandLine.Replace('/', '\')
    $root = [IO.Path]::GetFullPath($VoiceDirectory).TrimEnd('\')
    foreach ($file in @('worker.mjs', 'host-worker.mjs')) {
        $pattern = '(?i)(?:^|[\s"])' + [regex]::Escape((Join-Path $root $file)) + '(?:$|[\s"])'
        if ($command -match $pattern) { return $true }
    }
    return $false
}

function Stop-PrimeFlowVoiceWorkers {
    $voiceDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\discord-voice'))
    if (-not (Test-Path -LiteralPath (Join-Path $voiceDirectory 'worker.mjs'))) {
        throw 'PrimeFlow voice directory could not be verified.'
    }
    $pm2 = (Get-Command pm2.cmd -ErrorAction Stop).Source
    & $pm2 describe primeflow-discord *> $null
    if ($LASTEXITCODE -eq 0) {
        & $pm2 stop primeflow-discord | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the Mira voice supervisor.' }
        Start-Sleep -Seconds 2
    }
    # Windows locks the DAVE native library while a Node child has it loaded.
    # The Python supervisor can leave children behind when PM2 stops it.
    $workers = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object {
        Test-PrimeFlowVoiceWorker -CommandLine $_.CommandLine -VoiceDirectory $voiceDirectory
    })
    foreach ($worker in $workers) {
        Write-Host "Stopping PrimeFlow voice worker PID $($worker.ProcessId) before npm ci."
        Stop-Process -Id $worker.ProcessId -Force -ErrorAction SilentlyContinue
    }
    foreach ($attempt in 1..20) {
        $remaining = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object {
            Test-PrimeFlowVoiceWorker -CommandLine $_.CommandLine -VoiceDirectory $voiceDirectory
        })
        if ($remaining.Count -eq 0) { return }
        Start-Sleep -Milliseconds 250
    }
    throw 'A PrimeFlow voice worker still holds the dependency directory.'
}

if ($MyInvocation.InvocationName -ne '.') { Stop-PrimeFlowVoiceWorkers }
