[CmdletBinding()]
param([string]$Commit = 'HEAD')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot '.local/sites-connection'
$statePath = Join-Path $runtimeRoot 'backend-state.json'
$pythonExecutable = Join-Path $projectRoot 'backend/.venv-eeg/Scripts/python.exe'
if (Test-Path -LiteralPath $statePath) { throw 'A public backend state already exists; inspect it before restarting.' }
if (Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue) { throw 'Public backend port 8001 is in use.' }
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$buildCommit = (& git -C $projectRoot rev-parse --verify "$Commit^{commit}").Trim()
if ($LASTEXITCODE -ne 0 -or $buildCommit -notmatch '^[a-f0-9]{40}$') { throw 'Resolve a local source commit before starting the backend.' }
$buildRoot = Join-Path $projectRoot ".local/service-builds/$buildCommit"
if (-not (Test-Path -LiteralPath $buildRoot)) {
    & git -C $projectRoot worktree add --detach $buildRoot $buildCommit
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the fixed service build.' }
}
$actualCommit = (& git -C $buildRoot rev-parse HEAD).Trim()
$changes = @(& git -C $buildRoot status --porcelain --untracked-files=normal)
if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $buildCommit -or $changes.Count) { throw 'The service build is not the requested clean commit.' }
$buildBackend = Join-Path $buildRoot 'backend'
$overrides = @{
    DATABASE_URL_OVERRIDE = ('sqlite+aiosqlite:///' + (Join-Path $runtimeRoot 'public.db').Replace('\','/'))
    PREPROCESSING_ROOT = (Join-Path $runtimeRoot 'preprocessing')
    WORKFLOW_ROOT = (Join-Path $runtimeRoot 'workflows')
    DEFAULT_OWNER_ID = 'sites-public'
    FRONTEND_ORIGIN = 'https://brain-agent-eeg-workbench.shrewd-root-6935.chatgpt.site'
    LOG_DIR = (Join-Path $runtimeRoot 'backend-logs')
    NO_PROXY = '*'
    PYTHONUTF8 = '1'
    PYTHONPATH = $buildBackend
}
$previous = @{}
$started = @()
try {
    foreach ($name in $overrides.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $overrides[$name], 'Process')
    }
    $api = Start-Process -FilePath $pythonExecutable -ArgumentList @('-P','-m','uvicorn','app.main:create_app','--factory','--app-dir',('"' + $buildBackend + '"'),'--host','127.0.0.1','--port','8001') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'public-api.log') -RedirectStandardError (Join-Path $runtimeRoot 'public-api.err.log')
    $started += $api
    $worker = Start-Process -FilePath $pythonExecutable -ArgumentList @('-P','-m','app.preprocessing.worker') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot 'public-worker.log') -RedirectStandardError (Join-Path $runtimeRoot 'public-worker.err.log')
    $started += $worker
    $records = foreach ($server in $started) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($server.Id)"
        @{process_id=$info.ProcessId; created=$info.CreationDate.ToUniversalTime().ToString('o'); executable=$info.ExecutablePath}
    }
    @{processes=@($records); source_commit=$buildCommit; source_root=$buildRoot} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Output 'Public backend and EEG worker started from one fixed source build with a separate database and output workspace.'
} catch {
    foreach ($server in $started) { if (-not $server.HasExited) { Stop-Process -Id $server.Id } }
    throw
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
