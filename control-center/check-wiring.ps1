<#
  三层连通性自检：OAS Core → Bridge → 前端契约

  回答的是「前端和后端到底有没有接上」这个问题，只做只读请求：
  不启动任务、不修改配置、不绑定窗口。

  用法：
    Set-Location D:\OSAyys
    .\control-center\check-wiring.ps1
    .\control-center\check-wiring.ps1 -CoreUrl http://127.0.0.1:22270 -BridgeUrl http://127.0.0.1:22367
#>
param(
  [string]$CoreUrl = 'http://127.0.0.1:22267',
  [string]$BridgeUrl = 'http://127.0.0.1:22367',
  [int]$TimeoutSec = 8
)

$ErrorActionPreference = 'Continue'
$script:pass = 0
$script:fail = 0

function Step {
  param([string]$Name, [scriptblock]$Body, [switch]$Optional)
  try {
    $detail = & $Body
    Write-Host ("  [OK]   {0}{1}" -f $Name, $(if ($detail) { "  -  $detail" } else { '' })) -ForegroundColor Green
    $script:pass++
  } catch {
    if ($Optional) {
      Write-Host ("  [跳过] {0}  -  {1}" -f $Name, $_.Exception.Message) -ForegroundColor DarkYellow
    } else {
      Write-Host ("  [失败] {0}  -  {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red
      $script:fail++
    }
  }
}

function Get-Json {
  param([string]$Url, [string]$Method = 'GET')
  return Invoke-RestMethod -Uri $Url -Method $Method -TimeoutSec $TimeoutSec
}

Write-Host ''
Write-Host '== 第一层：OAS Core ==' -ForegroundColor Cyan
Step 'Core 存活 (GET /test)' {
  $result = Get-Json "$CoreUrl/test"
  if ("$result" -ne 'success') { throw "返回了 $result，期望 success" }
  $CoreUrl
}
Step 'Core 返回配置列表 (GET /config_list)' {
  $list = Get-Json "$CoreUrl/config_list"
  if (-not $list) { throw 'Core 没有返回任何配置' }
  "$($list.Count) 个账号：$($list -join ', ')"
}
Step 'Core 返回任务菜单 (GET /script_menu)' {
  $menu = Get-Json "$CoreUrl/script_menu"
  $count = ($menu.PSObject.Properties | ForEach-Object { $_.Value.Count } | Measure-Object -Sum).Sum
  "$count 项任务"
}

Write-Host ''
Write-Host '== 第二层：Bridge ==' -ForegroundColor Cyan
$bridgeHealth = $null
Step 'Bridge 存活 (GET /api/v1/health)' {
  $script:bridgeHealth = Get-Json "$BridgeUrl/api/v1/health"
  if ($script:bridgeHealth.bridge -ne 'ok') { throw "bridge 字段为 $($script:bridgeHealth.bridge)" }
  "版本 $($script:bridgeHealth.version)"
}
Step 'Bridge 已经连上 Core' {
  if (-not $script:bridgeHealth) { throw 'Bridge 未响应，跳过' }
  if ($script:bridgeHealth.core -ne 'ok') { throw "Bridge 认为 Core 是 $($script:bridgeHealth.core)（它连的是 $($script:bridgeHealth.core_url)）" }
  $script:bridgeHealth.core_url
}

$accounts = @()
Step 'Bridge 能读出账号（这一步会真的穿透到 Core）' {
  $started = Get-Date
  $script:accounts = @(Get-Json "$BridgeUrl/api/v1/accounts")
  $elapsed = [int]((Get-Date) - $started).TotalMilliseconds
  if (-not $script:accounts) { throw 'Bridge 返回了空账号列表' }
  "$($script:accounts.Count) 个账号，耗时 ${elapsed}ms"
}
Step '第二次读账号应该走缓存（明显更快）' {
  if (-not $script:accounts) { throw '上一步没拿到账号' }
  $started = Get-Date
  Get-Json "$BridgeUrl/api/v1/accounts" | Out-Null
  $elapsed = [int]((Get-Date) - $started).TotalMilliseconds
  "耗时 ${elapsed}ms（明显高于首次说明缓存没生效，请检查 Bridge 是否为新版）"
}
Step 'Bridge 返回任务目录' {
  $catalog = @(Get-Json "$BridgeUrl/api/v1/tasks/catalog")
  $english = @($catalog | Where-Object { $_.category -match '[A-Za-z]' })
  if ($english.Count -gt 0) { throw "有 $($english.Count) 个分类没翻译：$(($english.category | Select-Object -Unique) -join ', ')" }
  "$($catalog.Count) 项任务，分类均已中文化"
}

if ($accounts) {
  $first = $accounts[0].id
  Write-Host ''
  Write-Host "== 第三层：前端会用到的接口（以账号 $first 为例，只读） ==" -ForegroundColor Cyan
  Step "已启用任务 (GET /accounts/$first/tasks)" {
    $tasks = @(Get-Json "$BridgeUrl/api/v1/accounts/$first/tasks")
    "$($tasks.Count) 项已启用"
  }
  Step "任务配置 (GET /accounts/$first/tasks/Script/config)" {
    $config = Get-Json "$BridgeUrl/api/v1/accounts/$first/tasks/Script/config"
    $groups = @($config.groups.PSObject.Properties.Name)
    "分组：$($groups -join ', ')"
  }
  Step "调度快照 (GET /accounts/$first/schedule) — 新增接口" {
    $schedule = Get-Json "$BridgeUrl/api/v1/accounts/$first/schedule"
    "待执行 $(@($schedule.pending).Count) 项 / 等待 $(@($schedule.waiting).Count) 项"
  }
  Step "日志 (GET /accounts/$first/logs)" {
    $logs = @(Get-Json "$BridgeUrl/api/v1/accounts/$first/logs?limit=20")
    "$($logs.Count) 条"
  }
  Step '配置模板 (GET /templates) — 新增接口' {
    $templates = @(Get-Json "$BridgeUrl/api/v1/templates")
    "$($templates.Count) 个模板"
  }
  Step '窗口列表 (GET /windows)' -Optional {
    $windows = @(Get-Json "$BridgeUrl/api/v1/windows")
    "$($windows.Count) 个可绑定窗口"
  }
}

Write-Host ''
Write-Host '== 事件通道 ==' -ForegroundColor Cyan
Step 'WebSocket /api/v1/events 可以握手' {
  $wsUrl = ($BridgeUrl -replace '^http', 'ws') + '/api/v1/events'
  $client = [System.Net.WebSockets.ClientWebSocket]::new()
  try {
    $cancel = [System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($TimeoutSec))
    $client.ConnectAsync([Uri]$wsUrl, $cancel.Token).GetAwaiter().GetResult()
    $buffer = [ArraySegment[byte]]::new((New-Object byte[] 4096))
    $received = $client.ReceiveAsync($buffer, $cancel.Token).GetAwaiter().GetResult()
    $text = [Text.Encoding]::UTF8.GetString($buffer.Array, 0, $received.Count)
    if ($text -notmatch 'bridge.ready') { throw "首条事件不是 bridge.ready：$text" }
    '收到 bridge.ready'
  } finally {
    if ($client.State -eq 'Open') {
      $client.CloseAsync('NormalClosure', 'done', [Threading.CancellationToken]::None).GetAwaiter().GetResult() | Out-Null
    }
    $client.Dispose()
  }
}

Write-Host ''
if ($fail -eq 0) {
  Write-Host "全部通过（$pass 项）。前端连上 Bridge 后应当能正常工作。" -ForegroundColor Green
} else {
  Write-Host "$pass 项通过，$fail 项失败。先按上面失败的那一层排查。" -ForegroundColor Red
  Write-Host '常见原因：Core 没启动 / Bridge 没启动 / Bridge 连的 Core 地址不对（看 core_url）。'
}
Write-Host ''
exit $(if ($fail -eq 0) { 0 } else { 1 })
