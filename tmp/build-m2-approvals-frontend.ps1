$ErrorActionPreference = 'Stop'
$env:PM2_HOME = 'C:\pm2-system'
$env:PATH = 'C:\npm-global;C:\Program Files\nodejs;' + $env:PATH
$m2Frontend = 'C:\actions-runner\_work\PrimeFlow\PrimeFlow\frontend'
$m2State = 'C:\PrimeFlowOps\M2Approvals-20261026\frontend-state.json'
Set-Location -LiteralPath $m2Frontend
$m2Candidate = '.next-m2-approvals-' + (Get-Date -Format 'yyyyMMddHHmmss')
$m2CandidatePath = [System.IO.Path]::GetFullPath((Join-Path $m2Frontend $m2Candidate))
if (-not $m2CandidatePath.StartsWith($m2Frontend + '\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid candidate path' }
if (Test-Path -LiteralPath $m2CandidatePath) { throw 'Candidate already exists' }
$env:NEXT_DIST_DIR = $m2Candidate
$env:NEXT_DEPLOYMENT_ID = 'm2-approvals-20261026'
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Candidate build failed; live frontend remains unchanged' }
$m2Manifest = Join-Path $m2CandidatePath 'BUILD_ID'
if (-not (Test-Path -LiteralPath $m2Manifest)) { throw 'No candidate BUILD_ID' }
$m2Pm2 = 'C:\npm-global\pm2.cmd'
# Preserve a small rollback record; do not copy PM2's credential-bearing environment.
$m2Meta = & $m2Pm2 jlist | & node.exe -e "let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{const p=JSON.parse(s).find(x=>x.name==='frontend');if(!p)process.exit(2);console.log(JSON.stringify({dist_dir:p.pm2_env.NEXT_DIST_DIR||'.next',deployment_id:p.pm2_env.NEXT_DEPLOYMENT_ID||''}));});"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the current frontend configuration' }
$m2Current = ($m2Meta -join "`n") | ConvertFrom-Json
$m2Previous = $m2Current.dist_dir
if (-not $m2Previous) { $m2Previous = '.next' }
@{previous=$m2Previous; candidate=$m2Candidate; deployment='m2-approvals-20261026'} | ConvertTo-Json | Set-Content -LiteralPath $m2State -Encoding UTF8
& $m2Pm2 stop frontend | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Cannot stop the managed frontend' }
$m2Listeners = @(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)
foreach ($m2ListenerId in @($m2Listeners.OwningProcess | Sort-Object -Unique)) {
    $m2Process = Get-CimInstance Win32_Process -Filter "ProcessId=$m2ListenerId"
    if ($m2Process.ExecutablePath -ne 'C:\Program Files\nodejs\node.exe') { throw 'Unexpected frontend listener' }
    Stop-Process -Id $m2ListenerId -Force
}
& $m2Pm2 restart frontend --update-env | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'Frontend restart failed' }
$m2Ready = $false
for ($m2Attempt = 0; $m2Attempt -lt 15; $m2Attempt++) {
    try {
        $m2Response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:3000/m2-reporting-points' -TimeoutSec 3
        if ($m2Response.StatusCode -eq 200 -and $m2Response.Content.Contains('m2-approvals-20261026')) { $m2Ready=$true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $m2Ready) {
    $env:NEXT_DIST_DIR = $m2Previous
    $env:NEXT_DEPLOYMENT_ID = $m2Current.deployment_id
    & $m2Pm2 restart frontend --update-env | Out-Host
    throw 'Candidate readiness failed; previous frontend configuration restored'
}
& $m2Pm2 save | Out-Host
Write-Output 'M2_APPROVALS_FRONTEND_READY'
