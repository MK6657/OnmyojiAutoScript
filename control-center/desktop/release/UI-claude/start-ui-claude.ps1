<#
  UI-claude 前端启动脚本(由 control-center\start.ps1 调用,也可单独运行)
  参数: -Port 前端端口(默认4175)  -BridgeUrl Bridge地址(默认 http://127.0.0.1:22367)
#>
param([int]$Port = 4175, [string]$BridgeUrl = 'http://127.0.0.1:22367')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
Set-Location -LiteralPath $here
$env:OAS_BRIDGE_URL = $BridgeUrl
if (-not (Test-Path (Join-Path $here 'node_modules'))) {
  Write-Host '首次运行,正在安装前端依赖(可能几分钟)...' -ForegroundColor Yellow
  npm install
}
Write-Host ("UI-claude 前端: http://127.0.0.1:{0}/  (Bridge {1})" -f $Port, $BridgeUrl) -ForegroundColor Cyan
npm run dev -- --host 127.0.0.1 --port $Port --strictPort
