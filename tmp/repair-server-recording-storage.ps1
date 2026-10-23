$ErrorActionPreference = 'Stop'
$log = 'C:\Scripts\PrimeFlowRecordingStorageRepair-20261023.log'
Start-Transcript -LiteralPath $log -Force | Out-Null
try {
    $legacyRoot = 'C:\actions-runner\_work\Primex-TaskManager\Primex-TaskManager\backend\uploads\meeting-recordings'
    $activeBackend = 'C:\actions-runner\_work\PrimeFlow\PrimeFlow\backend'
    $activeRoot = Join-Path $activeBackend 'uploads\meeting-recordings'
    $persistentRoot = 'C:\PrimeFlowData\MeetingRecordings'
    $recordingId = '78e048ae-6965-407d-96d4-99f21fe315fa'
    $relativeVideo = '2026\10\78e048ae-6965-407d-96d4-99f21fe315fa\recording.webm'
    $originalVideo = Join-Path $legacyRoot $relativeVideo
    if (-not (Test-Path -LiteralPath $originalVideo -PathType Leaf)) { throw 'Original TAK NOLTE video is missing' }
    if ((Get-Item -LiteralPath $originalVideo).Length -ne 206912001) { throw 'Unexpected TAK NOLTE size' }
    $originalHash = (Get-FileHash -LiteralPath $originalVideo -Algorithm SHA256).Hash
    # Preserve originals. Copy finalized media, receipts and chunks, never move
    # or delete the old tree. Abort rather than overwrite conflicting data.
    New-Item -ItemType Directory -Path $persistentRoot -Force | Out-Null
    $sourcePrefix = [IO.Path]::GetFullPath($legacyRoot).TrimEnd('\') + '\'
    $targetPrefix = [IO.Path]::GetFullPath($persistentRoot).TrimEnd('\') + '\'
    $count = 0
    foreach ($file in Get-ChildItem -LiteralPath $legacyRoot -Recurse -File) {
        if ($file.Name -eq '.finalize.lock' -or $file.Extension -eq '.part') { continue }
        $sourcePath = [IO.Path]::GetFullPath($file.FullName)
        if (-not $sourcePath.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid source path' }
        $relative = $sourcePath.Substring($sourcePrefix.Length)
        $target = [IO.Path]::GetFullPath((Join-Path $persistentRoot $relative))
        if (-not $target.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid target path' }
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
        if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath $sourcePath -Destination $target }
        if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
            throw "Persistent copy mismatch: $relative"
        }
        $count++
    }
    Write-Output "Verified persistent files: $count"
    $persistentVideo = Join-Path $persistentRoot $relativeVideo
    if ((Get-FileHash -LiteralPath $persistentVideo -Algorithm SHA256).Hash -ne $originalHash) { throw 'TAK NOLTE copy mismatch' }
    # The live API still uses its checkout-relative default. A junction repairs
    # that path immediately without restarting services or deploying code.
    if (Test-Path -LiteralPath $activeRoot) {
        $existing = Get-Item -LiteralPath $activeRoot -Force
        if ($existing.LinkType -ne 'Junction' -or $existing.Target -notcontains $persistentRoot) {
            throw 'Active storage appeared or differs; refusing to replace it'
        }
    } else {
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($activeRoot)) -Force | Out-Null
        New-Item -ItemType Junction -Path $activeRoot -Target $persistentRoot | Out-Null
    }
    if ((Get-FileHash -LiteralPath (Join-Path $activeRoot $relativeVideo) -Algorithm SHA256).Hash -ne $originalHash) {
        throw 'Active API path cannot read the verified video'
    }
    # Persist the absolute root for future API/worker restarts. Back up config
    # locally on the server; never print credentials or copy them into FILES.
    $envPath = Join-Path $activeBackend '.env'
    $backup = Join-Path $persistentRoot '.repair-backup-20261023'
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $envBackup = Join-Path $backup 'backend.env.before'
    if (-not (Test-Path -LiteralPath $envBackup)) { Copy-Item -LiteralPath $envPath -Destination $envBackup }
    $lines = [IO.File]::ReadAllLines($envPath) | Where-Object { $_ -notmatch '^MEETING_RECORDINGS_ROOT=' }
    [IO.File]::WriteAllLines($envPath, @($lines) + 'MEETING_RECORDINGS_ROOT=C:/PrimeFlowData/MeetingRecordings', (New-Object Text.UTF8Encoding($false)))
    # Export just the explicitly requested historical recording to FILES.
    $filesRoot = (Get-SmbShare -Name 'files').Path
    $reports = Join-Path $filesRoot '10_ZHVILLIM\04_PROJECTS\26_PRIMEFLOW\08_TAKIMET'
    if (-not (Test-Path -LiteralPath $reports -PathType Container)) { throw 'Configured FILES meetings folder does not exist' }
    $destination = Join-Path $reports 'REGJISTRIM TAK NOLTE_22.10.2026.webm'
    if (Test-Path -LiteralPath $destination) {
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $originalHash) { throw 'Different FILES video already exists' }
    } else {
        $temporary = Join-Path $reports '.REGJISTRIM TAK NOLTE_22.10.2026.webm.part'
        Copy-Item -LiteralPath $persistentVideo -Destination $temporary
        if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ne $originalHash) { throw 'FILES copy verification failed' }
        Move-Item -LiteralPath $temporary -Destination $destination
    }
    $receipt = @{recording_id=$recordingId; title='TAK NOLTE'; path=$destination; size_bytes=206912001; sha256=$originalHash.ToLowerInvariant()}
    $receiptPath = Join-Path ([IO.Path]::GetDirectoryName($persistentVideo)) 'files-archive.json'
    [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Write-Output "SUCCESS: active storage repaired; TAK NOLTE exported to $destination; SHA256=$originalHash"
} catch {
    Write-Output "FAILED: $($_.Exception.Message)"
    throw
} finally {
    Stop-Transcript | Out-Null
}
