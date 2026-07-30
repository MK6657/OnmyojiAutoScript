<#
  把 UI-claude 提升为生产前端。

  做的事情：
    1. 把 control-center\frontend\src 和 index.html 备份到 frontend\_backup_<时间戳>\
    2. 用 UI-claude 的源码覆盖 control-center\frontend
    3. 提示你重新执行桌面打包

  不会碰 bridge / desktop / module / tasks，也不会删除备份。
  想回退时把备份目录里的文件拷回去即可。

  用法：
    .\promote-to-production.ps1            预览将要发生什么（不改文件）
    .\promote-to-production.ps1 -Apply     真正执行
#>
param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$frontend = (Resolve-Path (Join-Path $root '..\..\..\frontend')).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $frontend "_backup_$stamp"

$files = @(
  @{ From = 'src\App.jsx';        To = 'src\App.jsx' }
  @{ From = 'src\api.js';         To = 'src\api.js' }
  @{ From = 'src\components.jsx'; To = 'src\components.jsx' }
  @{ From = 'src\fields.jsx';     To = 'src\fields.jsx' }
  @{ From = 'src\locale.js';      To = 'src\locale.js' }
  @{ From = 'src\main.jsx';       To = 'src\main.jsx' }
  @{ From = 'src\store.js';       To = 'src\store.js' }
  @{ From = 'src\styles.css';     To = 'src\styles.css' }
  @{ From = 'src\views.jsx';      To = 'src\views.jsx' }
  @{ From = 'index.html';         To = 'index.html' }
)

Write-Host "源目录：  $root"
Write-Host "目标目录：$frontend"
Write-Host "备份目录：$backup"
Write-Host ''

if (-not $Apply) {
  Write-Host '预览模式，不会修改任何文件。加 -Apply 才会真正执行。' -ForegroundColor Yellow
  Write-Host ''
}

foreach ($file in $files) {
  $source = Join-Path $root $file.From
  $target = Join-Path $frontend $file.To
  if (-not (Test-Path $source)) { throw "缺少源文件：$source" }
  $exists = Test-Path $target
  Write-Host ("{0,-22} -> {1}" -f $file.From, $(if ($exists) { '覆盖（先备份）' } else { '新增' }))
  if (-not $Apply) { continue }

  if ($exists) {
    $backupTarget = Join-Path $backup $file.To
    New-Item -ItemType Directory -Force -Path (Split-Path $backupTarget -Parent) | Out-Null
    Copy-Item $target $backupTarget -Force
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
  Copy-Item $source $target -Force
}

if ($Apply) {
  Write-Host ''
  Write-Host "完成。原文件已备份到 $backup" -ForegroundColor Green
  Write-Host '接下来：'
  Write-Host '  Set-Location D:\OSAyys\control-center\desktop'
  Write-Host '  .\build.ps1 -SkipNpmInstall'
}
