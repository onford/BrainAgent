[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot '.local/sites-connection'
$statePath = Join-Path $runtimeRoot 'backend-state.json'
$pythonExecutable = Join-Path $projectRoot 'backend/.venv-eeg/Scripts/python.exe'
if (Test-Path -LiteralPath $statePath) { throw 'A public backend state already exists; inspect it before restarting.' }
if (Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue) { throw 'Public backend port 8001 is in use.' }
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$overrides = @{
    DATABASE_URL_OVERRIDE = ('sqlite+aiosqlite:///' + (Join-Path $runtimeRoot 'public.db').Replace('\','/'))
    PREPROCESSING_ROOT = (Join-Path $runtimeRoot 'preprocessing')
    WORKFLOW_ROOT = (Join-Path $runtimeRoot 'workflows')
    DEFAULT_OWNER_ID = 'sites-public'
    FRONTEND_ORIGIN = 'https://brain-agent-eeg-workbench.shrewd-root-6935.chatgpt.site'
    LOG_DIR = (Join-Path $runtimeRoot 'backend-logs')
    NO_PROXY = '*'
    PYTHONUTF8 = '1'
}
$previous = @{}
$started = @()
try {
    foreach ($name in $overrides.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $overrides[$name], 'Process')
    }
    $api = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m','uvicorn','app.main:create_app','--factory','--host','127.0.0.1','--port','8001') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'public-api.log') -RedirectStandardError (Join-Path $runtimeRoot 'public-api.err.log')
    $started += $api
    $worker = Start-Process -FilePath $pythonExecutable -ArgumentList @('-m','app.preprocessing.worker') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'public-worker.log') -RedirectStandardError (Join-Path $runtimeRoot 'public-worker.err.log')
    $started += $worker
    $records = foreach ($server in $started) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($server.Id)"
        @{process_id=$info.ProcessId; created=$info.CreationDate.ToUniversalTime().ToString('o'); executable=$info.ExecutablePath}
    }
    @{processes=@($records)} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Output 'Public backend and EEG worker started with a separate database and output workspace.'
} catch {
    foreach ($server in $started) { if (-not $server.HasExited) { Stop-Process -Id $server.Id } }
    throw
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
