<#
  一键启动「无游戏联调栈」：mock Core (:22268) + 隔离 Bridge (:22368) + 正式前端 (:4175)

  用途：不启动游戏、模拟器和真实 OAS Core，就把整套控制中心跑起来——
  用于界面开发、演示、以及上游更新后的快速回归。
  mock Core 的接口与真实 Core 对齐（见 bridge/tests/mock_core.py 顶部说明），
  mock Core 数据在内存里；Bridge 元数据写入 output/dev-stack，不接触正式数据库。

  ★ 这是“演示/联调栈”：界面里显示的“Core 在线”指向的是 mock Core（模拟数据），
    不会控制任何真实设备，也不会读写真实配置。真实使用请改用项目根目录的 启动.bat。

  与真实环境的关系：
    - 真实使用时不要运行本脚本；照常 server.py + start-bridge.ps1 + UI 即可；
    - mock Core 用 22268，测试 Bridge 用 22368，不复用正式 22267/22367；
    - 测试 Bridge 强制使用独立 SQLite 目录，并向测试脚本报告隔离模式。

  用法：
    Set-Location D:\OSAyys
    .\control-center\launcher\start-dev-stack.ps1
    # 打开 http://127.0.0.1:4175/
#>
param(
  [int]$MockCorePort = 22268,
  [int]$BridgePort = 22368,
  [int]$UiPort = 4175
)

$ErrorActionPreference = 'Stop'
$launcher = $PSScriptRoot
$root = (Resolve-Path (Join-Path $launcher '..\..')).Path
$bridgeDir = Join-Path $root 'control-center\bridge'
$uiDir = Join-Path $root 'control-center\frontend'
$testDataDir = Join-Path $root 'output\dev-stack\bridge-data'
New-Item -ItemType Directory -Path $testDataDir -Force | Out-Null

function Test-PortBindable([int]$Port) {
  $listener = $null
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    return $true
  } catch {
    return $false
  } finally {
    if ($listener) { try { $listener.Stop() } catch { } }
  }
}

function Find-BindableUiPort([int]$StartPort, [int]$EndPort) {
  foreach ($candidate in $StartPort..$EndPort) {
    if (Test-PortBindable $candidate) { return $candidate }
  }
  throw "未在 $StartPort-$EndPort 找到可用前端端口"
}

# mock Core 使用根环境；Bridge 子进程由 start-bridge.ps1 优先选择专用环境
$rootPython = Join-Path $root '.venv\Scripts\python.exe'
$bridgePython = Join-Path $bridgeDir '.venv\Scripts\python.exe'
$python = if (Test-Path $rootPython) { (Resolve-Path $rootPython).Path }
          elseif (Test-Path $bridgePython) { (Resolve-Path $bridgePython).Path }
          else { 'python' }

$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $MockCorePort, $BridgePort }
if ($busy) {
  Write-Host "以下端口已被占用，请先处理：" -ForegroundColor Yellow
  $busy | Select-Object LocalPort, OwningProcess | Format-Table | Out-String | Write-Host
  throw '端口冲突'
}

if (-not (Test-PortBindable $UiPort)) {
  $requestedUiPort = $UiPort
  $UiPort = Find-BindableUiPort ($UiPort + 1) ($UiPort + 300)
  Write-Host "前端端口 $requestedUiPort 被占用或由 Windows 保留，自动改用 $UiPort" -ForegroundColor DarkYellow
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
  (Join-Path $launcher 'start-bridge.ps1'), '-Port', "$BridgePort", '-CoreUrl', "http://127.0.0.1:$MockCorePort",
  '-DataDir', $testDataDir, '-IntegrationTest'

Start-Sleep -Seconds 2
Write-Host "[3/3] 前端       -> http://127.0.0.1:$UiPort"
Start-Process powershell -WindowStyle Normal -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File',
  (Join-Path $launcher 'start-frontend.ps1'), '-Port', "$UiPort", '-BridgeUrl', "http://127.0.0.1:$BridgePort"

Write-Host ''
Write-Host "全部拉起。打开 http://127.0.0.1:$UiPort/" -ForegroundColor Green
Write-Host '★ 提醒：这是演示/联调栈。界面里的“Core 在线”是 mock Core（模拟数据），' -ForegroundColor Yellow
Write-Host '        不会控制任何真实设备、也不会读写真实配置。真实使用请改用 启动.bat。' -ForegroundColor Yellow
Write-Host '联调回归：'
Write-Host "  `$env:OAS_TEST_BRIDGE_URL='http://127.0.0.1:$BridgePort'"
Write-Host "  `$env:OAS_TEST_MOCK_URL='http://127.0.0.1:$MockCorePort'"
Write-Host "  接口层：cd control-center\bridge; python tests\test_integration.py"
Write-Host "  界面层：`$env:OAS_UI_BASE='http://127.0.0.1:$UiPort/'; cd $uiDir; node tools\e2e-real.mjs"
