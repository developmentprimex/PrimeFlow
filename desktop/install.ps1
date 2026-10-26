param([string]$Source = (Join-Path (Split-Path -Parent $PSScriptRoot) 'output\mira-windows\Mira'))
$ErrorActionPreference = 'Stop'
$miraSource = [System.IO.Path]::GetFullPath($Source)
if (-not (Test-Path -LiteralPath (Join-Path $miraSource 'Mira.exe'))) { throw 'Build Mira first' }
$miraPrograms = [System.IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs'))
$miraTarget = [System.IO.Path]::GetFullPath((Join-Path $miraPrograms 'PrimeFlowMira'))
if (-not $miraTarget.StartsWith($miraPrograms + [System.IO.Path]::DirectorySeparatorChar,[System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected install path' }
$miraMarker = Join-Path $miraTarget '.mira-install.json'
if ((Test-Path -LiteralPath $miraTarget) -and -not (Test-Path -LiteralPath $miraMarker)) { throw 'Refusing to overwrite an unrecognized application folder' }
New-Item -ItemType Directory -Path $miraTarget -Force | Out-Null
Get-ChildItem -LiteralPath $miraSource -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $miraTarget -Recurse -Force }
$miraExe = Join-Path $miraTarget 'Mira.exe'
if ((Get-FileHash -LiteralPath $miraExe).Hash -ne (Get-FileHash -LiteralPath (Join-Path $miraSource 'Mira.exe')).Hash) { throw 'Executable copy failed' }
$miraShell = New-Object -ComObject WScript.Shell
$miraShortcuts = @(
    (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Mira - PrimeFlow.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Mira - PrimeFlow.lnk')
)
foreach ($miraLinkPath in $miraShortcuts) {
    $miraLink = $miraShell.CreateShortcut($miraLinkPath)
    if ((Test-Path -LiteralPath $miraLinkPath) -and $miraLink.TargetPath -ne $miraExe) { throw 'Refusing to replace an unrelated shortcut' }
    $miraLink.TargetPath = $miraExe
    $miraLink.WorkingDirectory = $miraTarget
    $miraLink.Description = 'Mira: shënime nga thirrjet, me PrimeFlow'
    $miraLink.IconLocation = $miraExe + ',0'
    $miraLink.Save()
}
$miraRecord = @{ executable=$miraExe; shortcuts=$miraShortcuts; installed_at=[DateTime]::UtcNow.ToString('o') }
$miraRecord | ConvertTo-Json | Set-Content -LiteralPath $miraMarker -Encoding UTF8
$miraRecord | ConvertTo-Json -Compress
