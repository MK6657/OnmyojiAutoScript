<#
  一键启动「无游戏联调栈」：mock Core (:22268) + 真实 Bridge (:22367) + UI-claude (:4175)

  用途：不启动游戏、模拟器和真实 OAS Core，就把整套控制中心跑起来——
  用于界面开发、演示、以及上游更新后的快速回归。
  mock Core 的接口与真实 Core 对齐（见 bridge/tests/mock_core.py 顶部说明），
  数据全在内存里，不写任何真实配置文件。

  ★ 这是“演示/联调栈”：界面里显示的“Core 在线”指向的是 mock Core（模拟数据），
    不会控制任何真实设备，也不会读写真实配置。真实使用请改用项目根目录的 启动.bat。

  与真实环境的关系：
    - 真实使用时不要运行本脚本；照常 server.py + start-bridge.ps1 + UI 即可；
    - mock Core 用 22268 端口，即使真实 Core (:22267) 在跑也互不冲突；
      但 Bridge 端口 22367 是共用的，联调前先关掉已有 Bridge。

  用法：
    Set-Location D:\OSAyys
    .\control-center\launcher\start-dev-stack.ps1
    # 打开 http://127.0.0.1:4175/
#>
param(
  [int]$MockCorePort = 22268,
  [int]$BridgePort = 22367,
  [int]$UiPort = 4175
)

$ErrorActionPreference = 'Stop'
$launcher = $PSScriptRoot
$root = (Resolve-Path (Join-Path $launcher '..\..')).Path
$bridgeDir = Join-Path $root 'control-center\bridge'
$uiDir = Join-Path $root 'control-center\desktop\release\UI-claude'

# 与 start-bridge.ps1 相同的解释器选择顺序
$rootPython = Join-Path $root '.venv\Scripts\python.exe'
$bridgePython = Join-Path $bridgeDir '.venv\Scripts\python.exe'
$python = if (Test-Path $rootPython) { (Resolve-Path $rootPython).Path }
          elseif (Test-Path $bridgePython) { (Resolve-Path $bridgePython).Path }
          else { 'python' }

$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $MockCorePort, $BridgePort, $UiPort }
if ($busy) {
  Write-Host "以下端口已被占用，请先处理：" -ForegroundColor Yellow
  $busy | Select-Object LocalPort, OwningProcess | Format-Table | Out-String | Write-Host
  throw '端口冲突'
}

Write-Host "[1/3] mock Core  -> http://127.0.0.1:$MockCorePort（模拟数据，非真实 OAS）"
Start-Process powershell -WindowStyle Normal -ArgumentList '-NoExit', '-Command', @"
`$Host.UI.RawUI.WindowTitle = '演示 mock Core :$MockCorePort（模拟数据，非真实 OAS）'
Set-Location '$bridgeDir'
& '$python' -m uvicorn tests.mock_core:app --host 127.0.0.1 --port $MockCorePort
"@

Start-Sleep -Seconds 2
Write-Host "[2/3] Bridge     -> http://127.0.0.1:$BridgePort（指向 mock Core）"
Start-Process powershell -WindowStyle Normal -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File',
  (Join-Path $launcher 'start-bridge.ps1'), '-Port', "$BridgePort", '-CoreUrl', "http://127.0.0.1:$MockCorePort"

Start-Sleep -Seconds 2
Write-Host "[3/3] UI-claude  -> http://127.0.0.1:$UiPort"
Start-Process powershell -WindowStyle Normal -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File',
  (Join-Path $uiDir 'start-ui-claude.ps1'), '-Port', "$UiPort", '-BridgeUrl', "http://127.0.0.1:$BridgePort"

Write-Host ''
Write-Host "全部拉起。打开 http://127.0.0.1:$UiPort/" -ForegroundColor Green
Write-Host '★ 提醒：这是演示/联调栈。界面里的“Core 在线”是 mock Core（模拟数据），' -ForegroundColor Yellow
Write-Host '        不会控制任何真实设备、也不会读写真实配置。真实使用请改用 启动.bat。' -ForegroundColor Yellow
Write-Host '联调回归：'
Write-Host "  接口层：cd control-center\bridge; python tests\test_integration.py"
Write-Host "  界面层：cd $uiDir; node tools\e2e-real.mjs"
