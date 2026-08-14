[CmdletBinding(SupportsShouldProcess)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if ($root -ne 'D:\OSAyys') { throw "Unexpected project root: $root" }

$targets = @(
  Get-ChildItem -LiteralPath $root -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -in @('__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache') -and
      $_.FullName -notmatch '\\.venv(\\|$)' -and
      $_.FullName -notlike (Join-Path $root 'backups\*') -and
      $_.FullName -notlike (Join-Path $root 'output\*') -and
      $_.FullName -notlike (Join-Path $root 'log\*')
    } |
    Sort-Object FullName -Unique
)

$fileCount = 0L
$byteCount = 0L
foreach ($target in $targets) {
  $path = $target.FullName
  $resolved = (Resolve-Path -LiteralPath $path).Path
  if (-not $resolved.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Target escapes project root: $resolved"
  }
  if ($resolved -match '\\.venv(\\|$)' -or $resolved -like (Join-Path $root 'backups\*') -or
      $resolved -like (Join-Path $root 'output\*') -or $resolved -like (Join-Path $root 'log\*')) {
    throw "Protected project path selected: $resolved"
  }
  $item = Get-Item -LiteralPath $resolved -Force
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Refusing reparse point: $resolved"
  }
  $files = @(Get-ChildItem -LiteralPath $resolved -File -Recurse -Force -ErrorAction SilentlyContinue)
  $fileCount += $files.Count
  $byteCount += ($files | Measure-Object Length -Sum).Sum
}

Write-Output ("Cleanup plan: targets={0}, files={1}, bytes={2}" -f $targets.Count, $fileCount, $byteCount)
foreach ($path in @($targets | ForEach-Object FullName | Sort-Object Length -Descending)) {
  if ($PSCmdlet.ShouldProcess($path, 'Remove reproducible Python cache')) {
    Remove-Item -LiteralPath $path -Recurse -Force
  }
}
