param([int]$Port = 5173)

$ErrorActionPreference = 'Stop'
# 注意：这是“旧生产前端”(control-center\frontend, :5173)，不是 UI-claude 新界面。
# 日常请用 启动.bat / start.ps1（默认 UI-claude :4175）。本脚本仅供对照旧界面或 -Prod 打包预览。
Write-Host '[!] 正在启动【旧前端 :5173】，这不是 UI-claude 新界面。日常请改用项目根目录的 启动.bat。' -ForegroundColor Yellow
Set-Location (Join-Path $PSScriptRoot '..\frontend')
if (-not (Test-Path 'node_modules')) { npm install }
npm run dev -- --host 127.0.0.1 --port $Port
