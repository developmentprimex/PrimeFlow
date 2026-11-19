# Called at Windows startup and when the collector is first installed.
$ErrorActionPreference = 'Stop'
$name = 'PrimeFlow-ResourceHistory'
$destination = Join-Path $PSScriptRoot 'state\resources.blg'
$logman = Join-Path $env:SystemRoot 'System32\logman.exe'
& $logman query $name *> $null
if ($LASTEXITCODE -ne 0) {
    $counters = @(
        '\Memory\Available MBytes'
        '\Memory\Pages Input/sec'
        '\PhysicalDisk(_Total)\Avg. Disk sec/Transfer'
        '\Processor(_Total)\% Processor Time'
        '\Process(*)\ID Process'
        '\Process(*)\Working Set - Private'
        '\Process(*)\Private Bytes'
        '\Process(*)\% Processor Time'
    )
    & $logman create counter $name -c $counters -si 00:00:10 -f bincirc -max 128 -o $destination
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
& $logman start $name
exit $LASTEXITCODE
