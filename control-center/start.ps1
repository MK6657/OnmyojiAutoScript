<#
  OAS 控制中心 · 一键启动
  ============================
  用法（任选其一）:
    双击项目根目录的  启动.bat          ← 日常推荐
    或 PowerShell:   .\control-center\start.ps1

  行为:
    按 Core -> Bridge -> 界面 的顺序逐层处理。每一层:
      已经在跑  -> 直接复用，绝不重复启动（重复启动 Core 会抢配置和设备）；
      端口被陌生程序占用 -> Bridge/界面 自动换下一个空闲端口；
                            Core 端口是全局约定不自动换，停下来报告占用进程；
      没在跑    -> 在新窗口拉起，并轮询等它就绪（Core 首次含 OCR 初始化，最多等 90 秒）。
    全部就绪后自动打开浏览器。

  可选参数:
    -SkipCore    你已经用别的方式启动了 OAS（如原 QML 界面），跳过 Core 层
    -Prod        使用生产前端(control-center\frontend, :5173)而不是 UI-claude(:4175)
    -NoBrowser   就绪后不自动打开浏览器
    -CoreUrl     Core 不在默认地址时指定，如 -CoreUrl http://127.0.0.1:22270

  注意: 关闭本脚本/各窗口 不等于 停止自动化任务。停止任务请在界面里点「停止」。
#>
param(
  [switch]$SkipCore,
  [switch]$Prod,
  [switch]$NoBrowser,
  [switch]$RestartCore,
  [switch]$RestartAll,
  [switch]$Menu,
  [string]$CoreUrl = 'http://127.0.0.1:22267'
)

# -RestartAll 包含 -RestartCore（全部重启自然也要重启 Core）
if ($RestartAll) { $RestartCore = $true }

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# -Menu：启动.bat 传进来的。菜单放在 PowerShell 里显示而不是写在 .bat 中，
# 因为 .bat 在中文 Windows(GBK 控制台)下解析 UTF-8 中文会串行、把 echo 吞掉导致整行被当命令执行。
# 所以 启动.bat 只保留纯英文，中文一律由这里输出。
if ($Menu) {
  Write-Host ''
  Write-Host '  ================= OAS 控制中心 =================' -ForegroundColor Cyan
  Write-Host '    [1] 正常启动    已在跑的直接复用（日常用这个）'
  Write-Host '    [2] 重启 Core   改了识别/资源等被缓存的代码后用'
  Write-Host '    [3] 全部重启    Core + Bridge + 界面 全部重来'
  Write-Host '  ==============================================='
  Write-Host '    不用选也行：5 秒后自动按 [1] 启动' -ForegroundColor DarkGray
  Write-Host ''
  $picked = '1'
  $deadline = (Get-Date).AddSeconds(5)
  try {
    while ((Get-Date) -lt $deadline) {
      if ($Host.UI.RawUI.KeyAvailable) {
        $key = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        if ('1', '2', '3' -contains "$($key.Character)") { $picked = "$($key.Character)"; break }
      }
      Start-Sleep -Milliseconds 120
    }
  } catch { }   # 某些宿主不支持 KeyAvailable，直接按默认走
  if ($picked -eq '2') {
    $RestartCore = $true
    Write-Host '    -> 重启 Core 后启动' -ForegroundColor Yellow
  } elseif ($picked -eq '3') {
    $RestartCore = $true; $RestartAll = $true
    Write-Host '    -> 全部重启（Core + Bridge + 界面）' -ForegroundColor Yellow
  } else {
    Write-Host '    -> 正常启动' -ForegroundColor Green
  }
}

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$cc   = $PSScriptRoot                     # ...\control-center
$root = Split-Path -Parent $cc            # 项目根 D:\OSAyys

# ------------------------------------------------------------ 工具函数

function Get-PortOwner([int]$Port) {
  try {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
            Select-Object -First 1
  } catch { return $null }
  if (-not $conn) { return $null }
  $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
  $name = 'unknown'
  if ($proc) { $name = $proc.ProcessName }
  return [pscustomobject]@{ Port = $Port; ProcessId = $conn.OwningProcess; Name = $name }
}

function Test-Json([string]$Url) {
  try { return Invoke-RestMethod -Uri $Url -TimeoutSec 3 } catch { return $null }
}

function Test-HttpOk([string]$Url) {
  try {
    $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
    return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
  } catch { return $false }
}

function Find-FreePort([int]$From, [int]$To) {
  for ($p = $From; $p -le $To; $p++) {
    if (-not (Get-PortOwner $p)) { return $p }
  }
  throw ("{0}-{1} 之间没有空闲端口" -f $From, $To)
}

function Start-InNewWindow([string]$Title, [string]$Command) {
  $full  = ("`$Host.UI.RawUI.WindowTitle = '{0}'; {1}" -f $Title, $Command)
  $bytes = [System.Text.Encoding]::Unicode.GetBytes($full)
  Start-Process powershell -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass',
    '-EncodedCommand', [Convert]::ToBase64String($bytes)
  ) | Out-Null
}

function Stop-PortOwner([int]$Port, [string]$Label) {
  # 结束占用指定端口的进程。给 -RestartCore / -RestartAll 用：
  # 省得用户去任务栏里翻那个黑窗口（窗口可能被最小化或标题不一致，很难找）。
  $owner = Get-PortOwner $Port
  if (-not $owner) {
    Write-Host ("      {0} 没有在跑，跳过结束" -f $Label) -ForegroundColor DarkGray
    return $true
  }
  Write-Host ("      结束 {0} 旧进程：{1} (PID {2})" -f $Label, $owner.Name, $owner.ProcessId) -ForegroundColor DarkYellow
  try { Stop-Process -Id $owner.ProcessId -Force -ErrorAction Stop } catch {
    Write-Host ("      结束失败：{0}（可尝试以管理员身份运行）" -f $_.Exception.Message) -ForegroundColor Red
    return $false
  }
  for ($i = 0; $i -lt 25; $i++) {
    if (-not (Get-PortOwner $Port)) { return $true }
    Start-Sleep -Milliseconds 400
  }
  Write-Host ("      端口 {0} 仍被占用" -f $Port) -ForegroundColor Red
  return $false
}

function Wait-Ready([scriptblock]$Probe, [int]$TimeoutSec) {
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $TimeoutSec) {
    if (& $Probe) { Write-Host '' ; return $true }
    Write-Host '.' -NoNewline
    Start-Sleep -Milliseconds 800
  }
  Write-Host ''
  return $false
}

function Initialize-Adb {
  # OAS 通过 adbutils 连模拟器。很多机器没有全局 adb，OAS 自动 `adb start-server` 会报
  # FileNotFoundError（handoff/19 根因），于是连不上任何模拟器、所有账号任务都失败。
  # 这里把 .venv 里 adbutils 自带的 adb 加进 PATH，并起好 adb server。
  # ★ 重要：只有【新拉起】的 Core 才会继承这个 PATH。若 Core 是“复用”的旧窗口，
  #   它那份进程里仍然没有 adb —— 想真正修好，必须先关掉旧「OAS Core」窗口再重跑本脚本。
  $adbDir = Join-Path $root '.venv\Lib\site-packages\adbutils\binaries'
  $adbExe = Join-Path $adbDir 'adb.exe'
  if (-not (Test-Path $adbExe)) {
    Write-Host '[0/3] adb    .venv 里没找到 adb，跳过；连不上模拟器请装 platform-tools 或用模拟器自带 adb' -ForegroundColor DarkYellow
    return
  }
  if (($env:PATH -split ';') -notcontains $adbDir) { $env:PATH = "$adbDir;$env:PATH" }
  # adb start-server 成功时也会把 “daemon started successfully” 打到 stderr，
  # 在 $ErrorActionPreference='Stop' 下会被误判为失败。这里临时放开，用退出码 + adb devices 判断真伪。
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $code = 1
  try { & $adbExe start-server *>$null; $code = $LASTEXITCODE } catch { $code = 1 }
  $devs = ''
  try { $devs = (& $adbExe devices 2>$null | Out-String) } catch { }
  $ErrorActionPreference = $prev
  if ($code -eq 0 -or $devs -match 'List of devices') {
    Write-Host ("[0/3] adb    已加入 PATH，adb server 就绪：{0}" -f $adbExe) -ForegroundColor Green
    $lines = @($devs -split "`r?`n" | Where-Object { $_ -match "`t(device|offline|unauthorized)" })
    if ($lines.Count) { Write-Host ("       已识别设备：{0}" -f (($lines | ForEach-Object { $_.Trim() }) -join '；')) -ForegroundColor Green }
    else { Write-Host '       暂无已连接设备：启动模拟器后 OAS 会自行连接；MuMu12 也可手动跑一次 adb connect 127.0.0.1:16384' -ForegroundColor DarkYellow }
  } else {
    Write-Host ("[0/3] adb    adb 无法启动（退出码 {0}，多半被杀软拦截）。请把这个 adb 加入杀软白名单再重试：{1}" -f $code, $adbExe) -ForegroundColor Red
  }
}

Write-Host ''
Write-Host '=== OAS 控制中心 · 一键启动 ===' -ForegroundColor Cyan
Write-Host ("项目根目录: {0}" -f $root)
Write-Host ''

# adb 必须先就绪，否则 Core 连模拟器会崩（见 handoff/19）
Initialize-Adb
Write-Host ''

# ------------------------------------------------------------ [1/3] OAS Core

$corePort = 22267
try { $corePort = ([Uri]$CoreUrl).Port } catch { }

# -RestartCore：先把占着 Core 端口的旧进程结束掉，再往下走（下面会当作“没在跑”重新拉起）。
# 用途：改了会被 Python import 缓存的模块（module\atom\image.py、tasks\GameUi\assets.py 等）时，
#       只有重开 Core 进程才会重新加载；找不到那个黑窗口时用这个最省事。
if ($RestartCore -and -not $SkipCore) {
  Write-Host '[1/3] Core   按要求重启：先结束旧进程' -ForegroundColor DarkYellow
  if (-not (Stop-PortOwner $corePort 'Core')) { exit 1 }
}
if ($RestartAll) {
  # Bridge 与界面也一并结束，后面各层会当作“没在跑”重新拉起
  Write-Host '[*/3] 全部重启：一并结束 Bridge 与界面' -ForegroundColor DarkYellow
  [void](Stop-PortOwner 22367 'Bridge')
  [void](Stop-PortOwner 5173 '界面(生产)')
  [void](Stop-PortOwner 4175 '界面(UI-claude)')
}

if ($SkipCore) {
  Write-Host '[1/3] Core   已按 -SkipCore 跳过（默认你已在别处启动它）' -ForegroundColor DarkYellow
} else {
  $alive = Test-Json ("{0}/test" -f $CoreUrl)
  if ("$alive" -eq 'success') {
    Write-Host ("[1/3] Core   已在线({0})，复用，不重复启动" -f $CoreUrl) -ForegroundColor Green
  } else {
    $owner = Get-PortOwner $corePort
    if ($owner) {
      Write-Host ("[1/3] Core   端口 {0} 被 {1} (PID {2}) 占用，且它不是可用的 OAS Core（/test 无响应）" -f $corePort, $owner.Name, $owner.ProcessId) -ForegroundColor Red
      Write-Host '      Core 端口是全局约定，不自动更换。若那是卡死的旧 Core，请结束它后重试；'
      Write-Host ("      若你的 Core 用了别的端口，请加参数：-CoreUrl http://127.0.0.1:端口")
      exit 1
    }
    $py = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) { $py = 'python' }
    Write-Host ("[1/3] Core   启动中（{0} server.py，首次含 OCR 初始化，最多等 90 秒）" -f $py)
    Start-InNewWindow ("OAS Core :{0}" -f $corePort) ("Set-Location -LiteralPath '{0}'; & '{1}' server.py" -f $root, $py)
    $ok = Wait-Ready { "$(Test-Json ("{0}/test" -f $CoreUrl))" -eq 'success' } 90
    if (-not $ok) {
      Write-Host '[1/3] Core   90 秒内未就绪。请查看「OAS Core」窗口里的报错。' -ForegroundColor Red
      exit 1
    }
    Write-Host '[1/3] Core   已就绪' -ForegroundColor Green
  }
}

# ------------------------------------------------------------ [2/3] Bridge

$bridgePort = 22367
$health = Test-Json ("http://127.0.0.1:{0}/api/v1/health" -f $bridgePort)
if ($health -and $health.bridge -eq 'ok') {
  Write-Host ("[2/3] Bridge 已在线(:{0} v{1})，复用" -f $bridgePort, $health.version) -ForegroundColor Green
  if ($health.core -ne 'ok') {
    Write-Host ("      提醒：这个 Bridge 连的 Core({0}) 目前不在线；若你刚启动 Core，它会自动恢复" -f $health.core_url) -ForegroundColor DarkYellow
  }
} else {
  $owner = Get-PortOwner $bridgePort
  if ($owner) {
    $bridgePort = Find-FreePort 22368 22390
    Write-Host ("[2/3] Bridge 22367 被 {0} (PID {1}) 占用，自动改用空闲端口 {2}" -f $owner.Name, $owner.ProcessId, $bridgePort) -ForegroundColor DarkYellow
  }
  $bridgeScript = Join-Path $cc 'launcher\start-bridge.ps1'
  Write-Host ("[2/3] Bridge 启动中(:{0})" -f $bridgePort)
  Start-InNewWindow ("OAS Bridge :{0}" -f $bridgePort) ("& '{0}' -Port {1} -CoreUrl '{2}'" -f $bridgeScript, $bridgePort, $CoreUrl)
  $ok = Wait-Ready {
    $h = Test-Json ("http://127.0.0.1:{0}/api/v1/health" -f $bridgePort)
    ($h -and $h.bridge -eq 'ok')
  } 40
  if (-not $ok) {
    Write-Host '[2/3] Bridge 40 秒内未就绪。请查看「OAS Bridge」窗口里的报错。' -ForegroundColor Red
    exit 1
  }
  Write-Host '[2/3] Bridge 已就绪' -ForegroundColor Green
}

# ------------------------------------------------------------ [3/3] 界面

if ($Prod) { $frontPort = 5173 } else { $frontPort = 4175 }
$frontUrl = ("http://127.0.0.1:{0}/" -f $frontPort)

if (Test-HttpOk $frontUrl) {
  Write-Host ("[3/3] 界面   {0} 已有页面在跑，复用（若那不是控制中心页面，请关掉它后重跑本脚本）" -f $frontUrl) -ForegroundColor Green
} else {
  $owner = Get-PortOwner $frontPort
  if ($owner) {
    $frontPort = Find-FreePort ($frontPort + 1) ($frontPort + 15)
    $frontUrl  = ("http://127.0.0.1:{0}/" -f $frontPort)
    Write-Host ("[3/3] 界面   原端口被 {0} 占用，自动改用 {1}" -f $owner.Name, $frontPort) -ForegroundColor DarkYellow
  }
  if ($Prod) {
    $frontScript = Join-Path $cc 'launcher\start-frontend.ps1'
    $cmd = ("`$env:OAS_BRIDGE_URL='http://127.0.0.1:{0}'; & '{1}' -Port {2}" -f $bridgePort, $frontScript, $frontPort)
  } else {
    $frontScript = Join-Path $cc 'desktop\release\UI-claude\start-ui-claude.ps1'
    $cmd = ("& '{0}' -Port {1} -BridgeUrl 'http://127.0.0.1:{2}'" -f $frontScript, $frontPort, $bridgePort)
  }
  Write-Host ("[3/3] 界面   启动中(:{0})。首次运行要安装依赖，可能需要几分钟" -f $frontPort)
  Start-InNewWindow ("OAS 界面 :{0}" -f $frontPort) $cmd
  $ok = Wait-Ready { Test-HttpOk $frontUrl } 120
  if (-not $ok) {
    Write-Host '[3/3] 界面   还没就绪（首次多半在安装依赖，属正常）。' -ForegroundColor DarkYellow
    Write-Host ("      请稍等「OAS 界面」窗口装完，然后手动打开 {0}" -f $frontUrl)
  } else {
    Write-Host '[3/3] 界面   已就绪' -ForegroundColor Green
  }
}

# ------------------------------------------------------------ 汇总

Write-Host ''
Write-Host '================= 启动完成 =================' -ForegroundColor Cyan
Write-Host ("  Core    {0}" -f $CoreUrl)
Write-Host ("  Bridge  http://127.0.0.1:{0}" -f $bridgePort)
Write-Host ("  界面    {0}" -f $frontUrl)
Write-Host '  ------------------------------------------'
Write-Host '  · 停止自动化任务：在界面里点「停止」，关窗口不等于停任务'
Write-Host '  · 三层连通性排查：control-center\check-wiring.ps1'
Write-Host '============================================'

if (-not $NoBrowser) {
  if (Test-HttpOk $frontUrl) { Start-Process $frontUrl | Out-Null }
}
