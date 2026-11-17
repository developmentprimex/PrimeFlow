$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$testDir = Join-Path $repo 'tmp/mailbox-probe-tests'
New-Item -ItemType Directory -Path $testDir -Force | Out-Null
$csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe' }
$testExe = Join-Path $testDir 'ProbeTests.exe'
& $csc /nologo /target:exe /platform:anycpu /utf8output /main:ProbeTests /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:Microsoft.CSharp.dll "/out:$testExe" (Join-Path $PSScriptRoot 'MailboxProbe.cs') (Join-Path $PSScriptRoot 'tests/ProbeTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Test compilation failed.' }
& $testExe (Join-Path $testDir 'synthetic-ui.png')
if ($LASTEXITCODE -ne 0) { throw 'Mailbox probe tests failed.' }
