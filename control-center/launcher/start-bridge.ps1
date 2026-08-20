param(
  [int]$Port = 22367,
  [string]$CoreUrl = $env:OAS_CORE_URL,
  [string]$DataDir = $env:OAS_CONTROL_CENTER_DATA_DIR,
  [switch]$IntegrationTest
)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..\bridge')
if ([string]::IsNullOrWhiteSpace($CoreUrl)) { $CoreUrl = 'http://127.0.0.1:22267' }
$env:OAS_CORE_URL = $CoreUrl
if (-not [string]::IsNullOrWhiteSpace($DataDir)) {
  $env:OAS_CONTROL_CENTER_DATA_DIR = [System.IO.Path]::GetFullPath($DataDir)
}
if ($IntegrationTest) { $env:OAS_INTEGRATION_TEST = '1' }
$bridgePython = Join-Path $PSScriptRoot '..\bridge\.venv\Scripts\python.exe'
$rootPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
# Keep development and packaged Bridge on the same interpreter.  The root OAS
# environment has a different FastAPI/Uvicorn dependency set and must only be
# used as a fallback when the dedicated Bridge environment is absent.
$python = if (Test-Path $bridgePython) {
  (Resolve-Path $bridgePython).Path
} elseif (Test-Path $rootPython) {
  (Resolve-Path $rootPython).Path
} else {
  'python'
}
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
