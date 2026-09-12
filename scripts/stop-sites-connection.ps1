[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.local/sites-connection/state.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output 'No saved Sites connection.'; exit 0 }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
foreach ($record in $state.processes) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $($record.process_id)"
    if (-not $info) { continue }
    if ($info.ExecutablePath -ne $record.executable -or $info.CreationDate.ToUniversalTime().Ticks -ne ([DateTime]$record.created).ToUniversalTime().Ticks) { throw 'Process identity changed; no unrelated process was stopped.' }
    Stop-Process -Id $record.process_id
}
Remove-Item -LiteralPath $statePath
Write-Output 'Sites gateway and tunnel stopped. Backend and EEG worker remain running.'
