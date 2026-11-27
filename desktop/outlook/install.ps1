param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$protocol = 'HKCU:\Software\Classes\primeflow-outlook'
$installDirectory = Join-Path $env:LOCALAPPDATA 'PrimeFlow\OutlookClassic'
$handler = Join-Path $installDirectory 'open-message.ps1'

if ($Uninstall) {
    if (Test-Path -LiteralPath $protocol) { Remove-Item -LiteralPath $protocol -Recurse }
    if (Test-Path -LiteralPath $handler) { Remove-Item -LiteralPath $handler }
    return
}

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'open-message.ps1') -Destination $handler -Force
$commandKey = "$protocol\shell\open\command"
New-Item -Path $commandKey -Force | Out-Null
Set-Item -LiteralPath $protocol -Value 'URL:PrimeFlow Outlook Classic'
New-ItemProperty -LiteralPath $protocol -Name 'URL Protocol' -Value '' -Force | Out-Null
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$command = '"{0}" -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -STA -WindowStyle Hidden -File "{1}" "%1"' -f $powershell, $handler
Set-Item -LiteralPath $commandKey -Value $command

if ((Get-Item -LiteralPath $commandKey).GetValue('') -cne $command -or
    'URL Protocol' -notin (Get-Item -LiteralPath $protocol).GetValueNames() -or
    -not (Test-Path -LiteralPath $handler -PathType Leaf)) {
    throw 'The Outlook Classic protocol could not be verified.'
}
Write-Output 'PrimeFlow Outlook Classic protocol installed and verified.'
