param([string] $Url)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0
} catch [System.Net.WebException] {
    if ($_.Exception.Response) {
        @{status=[string][int]$_.Exception.Response.StatusCode} | ConvertTo-Json -Compress
    } else {
        @{error=[string]$_.Exception.Status} | ConvertTo-Json -Compress
    }
    exit 0
}

$result = @{status=[string][int]$response.StatusCode}
if ($response.StatusCode -eq 200) {
    try {
        $data = $response.Content | ConvertFrom-Json
        if ($data.status -ceq 'ok') {
            $result.ok = $true
            $result.build = [string]$data.build
        }
    } catch {
        # A successful HTTP status with a different payload is not API health.
    }
}
$result | ConvertTo-Json -Compress
