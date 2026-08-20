# DeepSeek-14 B4 v3: unified OAS test entry.
# - isolation env set BEFORE any import
# - excludes .venv/__pycache__/backups/work/node_modules/.git
# - reliable suffix removal ([IO.Path]::GetFileNameWithoutExtension)
# - clean top-level packages: tasks.x, module.x, bridge.x (bridge dir on PYTHONPATH)
# - pre-run self check: every module importable, no duplicates, no site-packages
param(
  [string[]]$Roots = @('tasks', 'module', 'control-center\bridge')
)
# Native command stderr (warnings etc.) must not abort the run; failures are
# detected via exit codes instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$iso = Join-Path ([System.IO.Path]::GetTempPath()) ("oas-ds14-iso-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$leaseDir = Join-Path $iso 'leases'
$stateDir = Join-Path $iso 'failure-state'
$logDir = Join-Path $iso 'logs'
New-Item -ItemType Directory -Force -Path $leaseDir, $stateDir, $logDir | Out-Null
$env:OAS_LEASE_DIR = $leaseDir
$env:OAS_FAILURE_STATE_DIR = $stateDir
$env:OAS_TEST_LOGDIR = $logDir
# capture the child output as plain UTF-8 so evidence files stay readable
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $root
$ccDir = Join-Path $root 'control-center'
if (($env:PYTHONPATH -split ';') -notcontains $ccDir) {
  $env:PYTHONPATH = "$env:PYTHONPATH;$ccDir"
}
$ev = Join-Path $root 'work\ds14-evidence'
New-Item -ItemType Directory -Force -Path $ev | Out-Null
Set-Location $root

$excludePattern = '__pycache__|\.venv|\.git|\backups\|\work\|node_modules|site-packages'
# Every test module is run in its own Python process. Bridge tests insert local
# FastAPI/websocket stubs at import time, and several legacy OAS tests retain
# module-level state; process isolation makes results independent of file
# system order and prevents one module from contaminating another.
$orderedRoots = @('tasks', 'module', 'control-center\bridge') |
  Where-Object { $Roots -contains $_ }
$moduleMap = @{}  # dotted-name -> file path
$moduleOrder = New-Object System.Collections.Generic.List[string]
foreach ($testRoot in $orderedRoots) {
  if ($testRoot -eq 'control-center\bridge') {
    # bridge tests live only directly under tests/; recursion here would pull
    # the stubs tree and any bundled venv/site-packages.
    $files = Get-ChildItem (Join-Path $testRoot 'tests') -Filter 'test*.py' -File |
      Where-Object { $_.FullName -notmatch $excludePattern }
  } else {
    $files = Get-ChildItem $testRoot -Recurse -Filter 'test*.py' -File |
      Where-Object { $_.FullName -notmatch $excludePattern } |
      Sort-Object LastWriteTime -Descending
  }
  foreach ($f in $files) {
    $rel = $f.FullName.Substring($root.Length + 1)
    # strip the extension by length (ChangeExtension leaves a trailing dot)
    $noExt = $rel.Substring(0, $rel.Length - [System.IO.Path]::GetExtension($rel).Length)
    $dotted = $noExt.Replace('\', '.')
    if ($testRoot -eq 'control-center\bridge') {
      # clean top-level package: bridge.tests.test_x (drop the hyphenated dir)
      $dotted = $dotted -replace '^control-center\.', ''
    }
    $moduleMap[$dotted] = $f.FullName
    $moduleOrder.Add($dotted)
  }
}
$modules = $moduleOrder.ToArray()

# pre-run self check: importable, no duplicates, no site-packages leakage
# PowerShell 5.1 decodes child output with [Console]::OutputEncoding; pin UTF-8
# so captured stdout/stderr survives as clean text.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$checkPy = Join-Path $iso 'import-check.py'
@'
import importlib, sys
names = sys.argv[1:]
failures = []
for n in names:
    try:
        importlib.import_module(n)
    except Exception as e:
        failures.append((n, type(e).__name__ + ': ' + str(e)[:120]))
if failures:
    for n, msg in failures:
        print("IMPORT_FAIL " + n + " :: " + msg)
    sys.exit(2)
print("IMPORT_OK " + str(len(names)))
'@ | Set-Content -Path $checkPy -Encoding UTF8
$python = Join-Path $root '.venv\Scripts\python.exe'
$checkFailures = New-Object System.Collections.Generic.List[string]
foreach ($module in $modules) {
  $checkOut = @(& $python -B $checkPy $module 2>&1 | ForEach-Object { $_.ToString() })
  $checkCode = $LASTEXITCODE
  if ($checkCode -ne 0) {
    $checkFailures.Add("$module :: $($checkOut | Select-Object -First 1)")
  }
}
if ($checkFailures.Count -gt 0) {
  Write-Output 'self-check failed:'
  Write-Output ($checkFailures | Select-Object -First 10)
  exit 2
}
Write-Output ("self-check: IMPORT_OK " + $modules.Count)
Write-Output ("modules (" + $modules.Count + "):")
Write-Output ($modules -join " ")

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $ev ("oas-tests-all-" + $stamp + ".txt")
Add-Content -Path $out -Value ("# MODULES=" + $modules.Count) -Encoding UTF8
Add-Content -Path $out -Value ("# SELF_CHECK=IMPORT_OK " + $modules.Count) -Encoding UTF8
Add-Content -Path $out -Value ("# " + ($modules -join " ")) -Encoding UTF8
# Run each module in a clean interpreter. Capture explicitly (no Tee-Object:
# PS 5.1 would write UTF-16) and persist as UTF-8 evidence.
$captured = New-Object System.Collections.Generic.List[string]
$failedModules = New-Object System.Collections.Generic.List[string]
foreach ($module in $modules) {
  $captured.Add("===== $module =====")
  $moduleOutput = @(& $python -B -m unittest $module 2>&1 | ForEach-Object { $_.ToString() })
  $moduleCode = $LASTEXITCODE
  foreach ($line in $moduleOutput) { $captured.Add($line) }
  $captured.Add("MODULE_EXIT_CODE=$moduleCode")
  if ($moduleCode -ne 0) { $failedModules.Add($module) }
}
$code = if ($failedModules.Count -eq 0) { 0 } else { 1 }
Add-Content -Path $out -Value $captured -Encoding UTF8
if ($failedModules.Count -gt 0) {
  Add-Content -Path $out -Value ("FAILED_MODULES=" + ($failedModules -join ",")) -Encoding UTF8
  Write-Output 'FAILED_MODULES:'
  Write-Output ($failedModules -join "`n")
}
Add-Content -Path $out -Value ("EXIT_CODE=" + $code) -Encoding UTF8
Write-Output ("EXIT_CODE=" + $code)
exit $code
