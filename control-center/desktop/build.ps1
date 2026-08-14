param(
  [switch]$SkipNpmInstall,
  [switch]$SkipBridge
)

$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$root = Join-Path $desktop '..\..'
$frontend = Join-Path $root 'control-center\frontend'
$bridge = Join-Path $root 'control-center\bridge'
$ui = Join-Path $desktop 'ui'
$bridgeDist = Join-Path $desktop 'bridge-dist'
$pyWork = Join-Path $desktop 'build\pyinstaller'
$dataSeed = Join-Path $desktop 'data-seed'

Write-Host ("[build] 唯一前端来源：{0}" -f $frontend) -ForegroundColor Cyan

Set-Location $root
$env:VITE_BRIDGE_URL = 'http://127.0.0.1:22367'
# 第一次打包时按需安装前端依赖（可用 -SkipNpmInstall 跳过）。
if (-not $SkipNpmInstall -and -not (Test-Path (Join-Path $frontend 'node_modules'))) {
  Write-Host ("[build] 安装前端依赖：{0}" -f $frontend) -ForegroundColor Cyan
  npm --prefix $frontend install
}
npm --prefix $frontend run build -- --mode desktop

Remove-Item $ui -Recurse -Force -ErrorAction SilentlyContinue
New-Item $ui -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $frontend 'dist\*') $ui -Recurse -Force

if (-not $SkipBridge) {
    $rootPython = Join-Path $root '.venv\Scripts\python.exe'
    $bridgePython = Join-Path $bridge '.venv\Scripts\python.exe'
    $python = $null
    # Keep Bridge packaging dependencies isolated from the OAS Core environment.
    foreach ($candidate in @($bridgePython, $rootPython, 'python')) {
        if ($candidate -ne 'python' -and -not (Test-Path $candidate)) { continue }
        try {
            & $candidate -c 'import PyInstaller' 2>&1 | Out-Null
        } catch {
            continue
        }
        if ($LASTEXITCODE -eq 0) {
            $python = if ($candidate -eq 'python') { $candidate } else { (Resolve-Path $candidate).Path }
            break
        }
    }
    if (-not $python) { throw '未找到带 PyInstaller 的 Python，请先运行 python -m pip install pyinstaller' }
    Remove-Item $bridgeDist -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $pyWork -Recurse -Force -ErrorAction SilentlyContinue
    New-Item $bridgeDist -ItemType Directory -Force | Out-Null
    & $python -m PyInstaller --noconfirm --clean --onefile --name oas-control-bridge --distpath $bridgeDist --workpath $pyWork --specpath (Join-Path $desktop 'build') --paths $bridge (Join-Path $bridge 'serve.py')
}

Remove-Item $dataSeed -Recurse -Force -ErrorAction SilentlyContinue
New-Item $dataSeed -ItemType Directory -Force | Out-Null
$database = Join-Path $root 'control-center\data\control_center.db'
if (Test-Path $database) { Copy-Item $database (Join-Path $dataSeed 'control_center.db') -Force }

Set-Location $desktop
if (-not $SkipNpmInstall -and -not (Test-Path 'node_modules')) { npm install }
if (-not (Test-Path 'node_modules\.bin\electron-builder.cmd')) { throw 'electron-builder 未安装，请先运行 npm install' }
& (Join-Path $desktop 'node_modules\.bin\electron-builder.cmd') --win portable --publish never
