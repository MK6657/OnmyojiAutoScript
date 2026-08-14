# start-all.ps1 —— 兼容旧入口（保留是为了老文档/习惯还能用）。
# 统一转发到智能启动脚本 start.ps1：
# 跳过 Core（假设你已用原方式启动 OAS），只带起 Bridge + 唯一正式前端，并自动避让端口、复用已在跑的进程。
# 想“连游戏一键全启”，直接双击项目根目录的  启动.bat  即可（它会连 Core 一起处理）。
$ErrorActionPreference = 'Stop'
$start = Join-Path $PSScriptRoot '..\start.ps1'
if (-not (Test-Path $start)) { throw "未找到 $start ；请确认 control-center\start.ps1 存在。" }
Write-Host 'start-all.ps1 已转发到 start.ps1 -SkipCore（Bridge + 正式前端）。' -ForegroundColor Cyan
& $start -SkipCore @args
