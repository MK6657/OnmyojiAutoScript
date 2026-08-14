param(
  [int]$Port = 4175,
  [string]$BridgeUrl = 'http://127.0.0.1:22367'
)

$ErrorActionPreference = 'Stop'
$frontend = (Resolve-Path (Join-Path $PSScriptRoot '..\frontend')).Path
$env:OAS_BRIDGE_URL = $BridgeUrl
Set-Location -LiteralPath $frontend
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
  Write-Host '首次运行，正在安装前端依赖（可能需要几分钟）...' -ForegroundColor Yellow
  npm install
}
Write-Host ("OAS 控制中心前端：http://127.0.0.1:{0}/  (Bridge {1})" -f $Port, $BridgeUrl) -ForegroundColor Cyan
npm run dev -- --host 127.0.0.1 --port $Port --strictPort
