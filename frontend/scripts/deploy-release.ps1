param([Parameter(Mandatory)][ValidateSet('Prepare','Activate')][string]$Phase)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'wait-for-readiness.ps1')
. (Join-Path $env:GITHUB_WORKSPACE 'deploy\origins.ps1')
$root = Join-Path $env:PM2_HOME 'primeflow-deploy\frontend-releases'
$legacy = Join-Path $env:GITHUB_WORKSPACE 'frontend'
$slots = @((Join-Path $root 'blue'), (Join-Path $root 'green'))
$sha = $env:GITHUB_SHA
if ($sha -notmatch '^[a-f0-9]{40}$') { throw 'Missing release SHA.' }

# Read only the working directory. PM2 also stores credentials in jlist.
$metadata = & pm2.cmd jlist
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the currently served release.' }
function Get-FrontendDirectory([string]$name) {
    $directory = $metadata | node -e "let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{try{const rows=JSON.parse(s.trim());const p=rows.find(x=>x.name===process.argv[1]);if(p)console.log(p.pm2_env.pm_cwd)}catch{process.exitCode=1}})" $name
    if ($LASTEXITCODE -ne 0) { throw 'Unreadable PM2 process list.' }
    return $directory
}
$active = Get-FrontendDirectory 'frontend'
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
        $standalone = @($slots | Where-Object { $command.Replace('/','\').IndexOf(($_ + '\server.js'), [StringComparison]::OrdinalIgnoreCase) -ge 0 })
        if (-not $standalone -and (-not $owned -or $command -notmatch '\bstart\b')) { throw "Unexpected listener on port 3000: PID $ownerId" }
        Stop-Process -Id $ownerId -Force -ErrorAction Stop
    }
}

function Start-Release([string]$directory, [string]$name='frontend', [int]$port=3000) {
    if (Test-Path -LiteralPath (Join-Path $directory 'server.js')) {
        $env:PORT = "$port"
        $env:HOSTNAME = if ($port -eq 3000) { '0.0.0.0' } else { '127.0.0.1' }
        Invoke-FrontendPm2 "start `"$(Join-Path $directory 'server.js')`" --name $name --cwd `"$directory`" --interpreter node"
        return
    }
    $cli = Join-Path $directory 'node_modules\next\dist\bin\next'
    Invoke-FrontendPm2 "start `"$cli`" --name $name --cwd `"$directory`" --interpreter node -- start --port $port"
}

if ($Phase -eq 'Prepare') {
    # Recover a previous run interrupted after routing to its standby. Keep
    # serving that standby until port 3000 serves the same verified release.
    $standby = Get-FrontendDirectory 'primeflow-frontend-standby'
    if ((Get-PrimeFlowRoute web).port -eq 3301) {
        if ($standby -notin $slots) { throw 'Unknown live standby.' }
        $previousSha = (Get-Content -Raw -LiteralPath (Join-Path $standby '.prepared')).Trim()
        if ($active -ne $standby) {
            Wait-PrimeFlowDrain 3000
            if ($active) { Invoke-FrontendPm2 'delete frontend' }
            Clear-PreviousListener
            Start-Release $standby
            $active = $standby
            $candidate = if ($active -eq $slots[0]) { $slots[1] } else { $slots[0] }
            $stamp = Join-Path $candidate '.prepared'
        } elseif (-not (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)) {
            Invoke-FrontendPm2 'restart frontend'
        }
        if (-not (Wait-PrimeFlowFrontend -ExpectedDeploymentId $previousSha)) { throw 'Canonical frontend has not recovered.' }
        Set-PrimeFlowRoute web 3000
    }
    if ($standby) {
        Wait-PrimeFlowDrain 3301
        Invoke-FrontendPm2 'delete primeflow-frontend-standby'
    }
    if (Test-Path -LiteralPath $candidate) {
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        if ($resolved -notin $slots -or $resolved -eq $active -or
            ((Get-Item -LiteralPath $resolved).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Unsafe release directory: $resolved"
        }
        Remove-Item -LiteralPath ("\\?\" + $resolved) -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $candidate | Out-Null
    $archive = Join-Path $env:RUNNER_TEMP "frontend-$sha.zip"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($archive, $candidate)
    if ((Get-Content -LiteralPath (Join-Path $candidate '.release-sha') -Raw).Trim() -ne $sha) {
        throw 'Frontend artifact SHA mismatch.'
    }
    # Pages opened before the switch can still request a previous lazy chunk.
    # Keep one generation, recording the candidate's own files before merging.
    $static = Join-Path $candidate '.next\static'
    $native = @(Get-ChildItem -LiteralPath $static -Recurse -File | ForEach-Object { $_.FullName.Substring($static.Length + 1) })
    ConvertTo-Json -InputObject $native -Compress | Set-Content -LiteralPath (Join-Path $candidate '.native-static.json') -Encoding UTF8
    if ($active) {
        $previous = Join-Path $active '.next\static'
        $list = Join-Path $active '.native-static.json'
        $files = if (Test-Path -LiteralPath $list) { Get-Content -Raw -LiteralPath $list | ConvertFrom-Json }
                 else { Get-ChildItem -LiteralPath $previous -Recurse -File | ForEach-Object { $_.FullName.Substring($previous.Length + 1) } }
        foreach ($file in $files) {
            if ([IO.Path]::IsPathRooted($file) -or ($file -split '[\\/]' -contains '..')) { throw 'Invalid static asset path.' }
            $target = Join-Path $static $file
            if (-not (Test-Path -LiteralPath $target)) {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
                [IO.File]::Copy((Join-Path $previous $file), $target)
            }
        }
    }
    # Exercise the actual production server and page before releasing port 3000.
    if (Get-NetTCPConnection -State Listen -LocalPort 3301 -ErrorAction SilentlyContinue) {
        throw 'Frontend readiness port 3301 is already in use.'
    }
    $env:PORT = '3301'
    $env:HOSTNAME = '127.0.0.1'
    $probe = Start-Process node.exe -ArgumentList 'server.js' -WorkingDirectory $candidate -WindowStyle Hidden -PassThru
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
Start-Release $candidate 'primeflow-frontend-standby' 3301
if (-not (Wait-PrimeFlowFrontend -ExpectedDeploymentId $sha -BaseUri 'http://127.0.0.1:3301')) { throw 'Standby failed readiness.' }
# A reboot during cutover must resurrect the same standby named by the
# durable gateway marker, even before the workflow's final process-list save.
Invoke-FrontendPm2 'save'
Set-PrimeFlowRoute web 3301
Wait-PrimeFlowDrain 3000
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
        Set-PrimeFlowRoute web 3000
    }
    throw $failure
}
Set-PrimeFlowRoute web 3000
# Keep the standby supervised until the next prepare, allowing existing
# streams to finish. Its directory is also the active release directory.
