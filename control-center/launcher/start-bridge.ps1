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
