$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$outDir = Join-Path $repo 'output/mailbox-probe'
$csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe' }
if (-not (Test-Path -LiteralPath $csc)) { throw '.NET Framework C# compiler was not found.' }
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$exe = Join-Path $outDir 'PrimeFlow-Outlook-Test.exe'
& $csc /nologo /target:winexe /platform:anycpu /optimize+ /utf8output /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:Microsoft.CSharp.dll "/out:$exe" (Join-Path $PSScriptRoot 'MailboxProbe.cs')
if ($LASTEXITCODE -ne 0) { throw 'Mailbox probe compilation failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LEXO-PARA.txt') -Destination (Join-Path $outDir 'LEXO-PARA.txt') -Force
$checksum = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
[IO.File]::WriteAllText((Join-Path $outDir 'SHA256.txt'), "$checksum  PrimeFlow-Outlook-Test.exe`r`n", [Text.Encoding]::ASCII)
$archive = Join-Path $repo 'output/PrimeFlow-Outlook-Test-50.zip'
Compress-Archive -LiteralPath $exe,(Join-Path $outDir 'LEXO-PARA.txt'),(Join-Path $outDir 'SHA256.txt') -DestinationPath $archive -Force
Write-Output "Prepared: $archive"
Write-Output "EXE SHA256: $checksum"
