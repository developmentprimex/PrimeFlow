param([Parameter(Mandatory)][ValidateSet('Prepare','Activate')][string]$Phase)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'wait-for-readiness.ps1')
$root = Join-Path $env:PM2_HOME 'primeflow-deploy\frontend-releases'
$legacy = Join-Path $env:GITHUB_WORKSPACE 'frontend'
$slots = @((Join-Path $root 'blue'), (Join-Path $root 'green'))
$sha = $env:GITHUB_SHA
if ($sha -notmatch '^[a-f0-9]{40}$') { throw 'Missing release SHA.' }

# Read only the working directory. PM2 also stores credentials in jlist.
$metadata = & pm2.cmd jlist
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the currently served release.' }
$active = $metadata | node -e "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{let p=JSON.parse(s).find(x=>x.name==='frontend');if(p)console.log(p.pm2_env.pm_cwd)})"
if ($LASTEXITCODE -ne 0) { throw 'Unreadable PM2 process list.' }
if ($active -and $active -notin ($slots + $legacy)) { throw "Unexpected frontend directory: $active" }
$candidate = if ($active -eq $slots[0]) { $slots[1] } else { $slots[0] }
$stamp = Join-Path $candidate '.prepared'

# Wait for the CLI only. A supervised Next process can inherit its parent's
# output handles on Windows and keep a synchronous Actions step open.
function Invoke-FrontendPm2([string]$arguments) {
    $process = Start-Process $env:ComSpec -ArgumentList "/d /c pm2 $arguments" -WindowStyle Hidden -PassThru
    $null = $process.Handle
    if (-not $process.WaitForExit(90000)) { throw "PM2 timed out: $arguments" }
    if ($process.ExitCode -ne 0) { throw "PM2 failed: $arguments" }
}

function Clear-PreviousListener {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)
    foreach ($ownerId in @($listeners.OwningProcess | Where-Object { $_ } | Select-Object -Unique)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId"
        $allowed = @($legacy) + $slots
        $command = [string]$process.CommandLine
        $owned = @($allowed | Where-Object { $command.Replace('/','\').IndexOf(($_ + '\node_modules\next\'), [StringComparison]::OrdinalIgnoreCase) -ge 0 })
        if (-not $owned -or $command -notmatch '\bstart\b') { throw "Unexpected listener on port 3000: PID $ownerId" }
        Stop-Process -Id $ownerId -Force -ErrorAction Stop
    }
}

function Start-Release([string]$directory) {
    $cli = Join-Path $directory 'node_modules\next\dist\bin\next'
    Invoke-FrontendPm2 "start `"$cli`" --name frontend --cwd `"$directory`" --interpreter node -- start --port 3000"
}

if ($Phase -eq 'Prepare') {
    if (Test-Path -LiteralPath $candidate) {
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        if ($resolved -notin $slots -or $resolved -eq $active -or
            ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Unsafe release directory: $resolved"
        }
        Remove-Item -LiteralPath ("\\?\" + $resolved) -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $candidate | Out-Null
    $archive = Join-Path $env:RUNNER_TEMP "frontend-$env:GITHUB_RUN_ID-$env:GITHUB_RUN_ATTEMPT.tar"
    git archive --format=tar "--output=$archive" "${sha}:frontend"
    if ($LASTEXITCODE -ne 0) { throw 'Frontend source export failed.' }
    tar.exe -xf $archive -C $candidate
    if ($LASTEXITCODE -ne 0) { throw 'Frontend source extraction failed.' }
    Remove-Item -LiteralPath $archive
    Copy-Item -LiteralPath (Join-Path $legacy '.env.local') -Destination $candidate
    Set-Location -LiteralPath $candidate
    npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend install failed.' }
    $env:NEXT_DEPLOYMENT_ID = $sha
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    # Exercise the actual production server and page before releasing port 3000.
    if (Get-NetTCPConnection -State Listen -LocalPort 3301 -ErrorAction SilentlyContinue) {
        throw 'Frontend readiness port 3301 is already in use.'
    }
    $probe = Start-Process node.exe -ArgumentList 'node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3301' -WorkingDirectory $candidate -WindowStyle Hidden -PassThru
    try {
        if (-not (Wait-PrimeFlowFrontend -ExpectedDeploymentId $sha -BaseUri 'http://127.0.0.1:3301') -or $probe.HasExited) {
            throw 'Candidate frontend failed its readiness check.'
        }
    } finally {
        if (-not $probe.HasExited) { $probe.Kill(); $probe.WaitForExit() }
    }
    Set-Content -LiteralPath $stamp -Value $sha
    return
}

if ((Get-Content -LiteralPath $stamp -Raw).Trim() -ne $sha) { throw 'Prepared frontend does not match this run.' }
if ($active) {
    Invoke-FrontendPm2 'delete frontend'
}
try {
    Clear-PreviousListener
    Start-Release $candidate
    if (-not (Wait-PrimeFlowFrontend -ExpectedDeploymentId $sha)) { throw 'Activated frontend failed readiness.' }
} catch {
    $failure = $_
    & pm2.cmd delete frontend
    if ($active) {
        Clear-PreviousListener
        Start-Release $active
        if (-not (Wait-PrimeFlowFrontend)) { throw "Previous frontend failed to recover after: $failure" }
    }
    throw $failure
}
