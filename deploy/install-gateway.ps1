# Run once on the Windows origin, alongside the currently serving processes.
param([Parameter(Mandatory)][string]$CaddyExe)
$ErrorActionPreference = 'Stop'
$directory = 'C:\PrimeFlowOps\DeploymentGateway'
$taskName = 'PrimeFlow Deployment Gateway'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Gateway task already exists. Inspect its status before changing it.'
}
foreach ($port in @(13000,18080)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Gateway port $port already has a listener."
    }
}
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$exe = Join-Path $directory 'caddy.exe'
$config = Join-Path $directory 'Caddyfile'
if ((Resolve-Path -LiteralPath $CaddyExe).Path -ne $exe) { Copy-Item -LiteralPath $CaddyExe -Destination $exe }
$sourceConfig = Join-Path $PSScriptRoot 'Caddyfile'
if ((Resolve-Path -LiteralPath $sourceConfig).Path -ne $config) { Copy-Item -LiteralPath $sourceConfig -Destination $config }
$env:PRIMEFLOW_GATEWAY_STATE = Join-Path $directory 'routes'
New-Item -ItemType Directory -Force -Path $env:PRIMEFLOW_GATEWAY_STATE | Out-Null
& $exe validate --config $config --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Invalid gateway configuration.' }
# Route markers persist across reboots. The listener configuration stays static.
$launcher = Join-Path $directory 'run.cmd'
@(
    '@echo off',
    "set PRIMEFLOW_GATEWAY_STATE=$env:PRIMEFLOW_GATEWAY_STATE",
    "set APPDATA=$directory\state",
    "set XDG_CONFIG_HOME=$directory\state",
    "set XDG_DATA_HOME=$directory\data",
    "`"$exe`" run --config `"$config`" --adapter caddyfile"
) | Set-Content -LiteralPath $launcher -Encoding ascii
$action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/d /c $launcher" -WorkingDirectory $directory
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $taskName
