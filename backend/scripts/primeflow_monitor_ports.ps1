$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$listeners = @(Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -in 8000,8080 |
    Select-Object LocalPort,OwningProcess)

$parents = @{}
foreach ($listener in $listeners) {
    $owner = [int]$listener.OwningProcess
    while ($owner -gt 0 -and !$parents.ContainsKey("$owner")) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$owner"
        if (!$process) { break }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
        # Windows can reuse the ID of a dead parent for an unrelated new process.
        $parentId = if ($parent -and $parent.CreationDate -le $process.CreationDate) {
            [int]$parent.ProcessId
        } else { 0 }
        $parents["$owner"] = $parentId
        $owner = $parentId
    }
}

@{listeners=$listeners; parents=$parents} | ConvertTo-Json -Depth 4 -Compress
