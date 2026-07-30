param(
  [int]$Port = 4173,
  [int]$BridgePort = 22368
)

$ErrorActionPreference = 'Stop'
$previewRoot = $PSScriptRoot
$projectRoot = Split-Path $previewRoot -Parent
$frontend = Join-Path $projectRoot 'control-center\frontend'
$mockBridge = Join-Path $previewRoot 'mock-bridge.mjs'

$node = Get-Command node -ErrorAction SilentlyContinue
$npm = Get-Command npm -ErrorAction SilentlyContinue
if (-not $node) { throw 'Node.js is required to run the real frontend preview.' }
if (-not $npm) { throw 'npm is required to run the real frontend preview.' }
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
  throw 'Frontend dependencies are missing. Run npm install in control-center\frontend first.'
}

$env:OAS_BRIDGE_URL = "http://127.0.0.1:$BridgePort"
$mockProcess = Start-Process -FilePath $node.Source `
  -ArgumentList @($mockBridge, '--port', "$BridgePort") `
  -WorkingDirectory $previewRoot -WindowStyle Hidden -PassThru

try {
  Write-Host "Starting the real OAS frontend from $frontend"
  Write-Host "Mock Bridge: http://127.0.0.1:$BridgePort"
  Write-Host "Frontend:    http://127.0.0.1:$Port"
  & $npm.Source --prefix $frontend run dev -- --host 127.0.0.1 --port $Port
  exit $LASTEXITCODE
}
finally {
  if ($mockProcess -and -not $mockProcess.HasExited) {
    Stop-Process -Id $mockProcess.Id -Force -ErrorAction SilentlyContinue
  }
}
