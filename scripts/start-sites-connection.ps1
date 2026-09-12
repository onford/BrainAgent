[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$connectionRoot = Join-Path $projectRoot '.local/sites-connection'
$statePath = Join-Path $connectionRoot 'state.json'
$secretPath = Join-Path $connectionRoot 'secret.json'
$pythonExecutable = Join-Path $projectRoot 'backend/.venv-eeg/Scripts/python.exe'
$tunnelExecutable = Join-Path $connectionRoot 'cloudflared.exe'
New-Item -ItemType Directory -Force -Path $connectionRoot | Out-Null
if (Test-Path -LiteralPath $statePath) { throw 'A connection state already exists. Run scripts/stop-sites-connection.ps1 first.' }
if (-not (Test-Path -LiteralPath $tunnelExecutable)) { throw 'Install the official cloudflared Windows binary at .local/sites-connection/cloudflared.exe first.' }
try { Invoke-RestMethod -Uri 'http://127.0.0.1:8001/health' -NoProxy -TimeoutSec 5 | Out-Null }
catch { & (Join-Path $PSScriptRoot 'start-sites-backend.ps1') }
if (Get-NetTCPConnection -State Listen -LocalPort 8788 -ErrorAction SilentlyContinue) { throw 'Local gateway port 8788 is in use.' }
if (-not (Test-Path -LiteralPath $secretPath)) {
    $randomBytes = [byte[]]::new(48)
    [Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    @{token=[Convert]::ToBase64String($randomBytes)} | ConvertTo-Json | Set-Content -LiteralPath $secretPath -Encoding utf8
}
$oldToken = $env:BRAIN_AGENT_BACKEND_TOKEN
$env:BRAIN_AGENT_BACKEND_TOKEN = (Get-Content -Raw -LiteralPath $secretPath | ConvertFrom-Json).token
$started = @()
try {
    $gateway = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m','uvicorn','app.sites_gateway:create_gateway','--factory','--host','127.0.0.1','--port','8788','--ws-max-size','1048576') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $connectionRoot 'gateway.log') -RedirectStandardError (Join-Path $connectionRoot 'gateway.err.log')
    $started += $gateway
    $tunnel = Start-Process -FilePath $tunnelExecutable -ArgumentList @('tunnel','--url','http://127.0.0.1:8788','--no-autoupdate','--protocol','http2') -WorkingDirectory $connectionRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $connectionRoot 'tunnel.log') -RedirectStandardError (Join-Path $connectionRoot 'tunnel.err.log')
    $started += $tunnel
    $records = foreach ($server in $started) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($server.Id)"
        @{process_id=$info.ProcessId; created=$info.CreationDate.ToUniversalTime().ToString('o'); executable=$info.ExecutablePath}
    }
    @{processes=@($records); started_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Output 'Gateway and tunnel started. Read tunnel.err.log for the HTTPS origin and configure it in Sites.'
} catch {
    foreach ($server in $started) { if (-not $server.HasExited) { Stop-Process -Id $server.Id } }
    throw
} finally { $env:BRAIN_AGENT_BACKEND_TOKEN = $oldToken }
