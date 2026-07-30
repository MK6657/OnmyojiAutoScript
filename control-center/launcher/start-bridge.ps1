param(
  [int]$Port = 22367,
  [string]$CoreUrl = $env:OAS_CORE_URL
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\bridge')
if ([string]::IsNullOrWhiteSpace($CoreUrl)) { $CoreUrl = 'http://127.0.0.1:22267' }
$env:OAS_CORE_URL = $CoreUrl
$rootPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
$bridgePython = Join-Path $PSScriptRoot '..\bridge\.venv\Scripts\python.exe'
$python = if (Test-Path $rootPython) {
  (Resolve-Path $rootPython).Path
} elseif (Test-Path $bridgePython) {
  (Resolve-Path $bridgePython).Path
} else {
  'python'
}
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
