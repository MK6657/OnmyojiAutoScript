[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$handoffRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$missing = [Collections.Generic.List[object]]::new()

function Test-LinkTarget([string]$RawTarget, [string]$SourceFile) {
  $target = if ($RawTarget.StartsWith('<') -and $RawTarget.EndsWith('>')) {
    $RawTarget.Substring(1, $RawTarget.Length - 2)
  } else {
    $RawTarget
  }
  if ([string]::IsNullOrWhiteSpace($target) -or $target.StartsWith('#') -or
      $target.StartsWith('/') -or $target -match '^[A-Za-z][A-Za-z0-9+.-]*:') {
    return
  }
  $fragmentIndex = $target.IndexOf('#')
  if ($fragmentIndex -ge 0) { $target = $target.Substring(0, $fragmentIndex) }
  $decoded = [Uri]::UnescapeDataString($target)
  $resolved = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetDirectoryName($SourceFile)) $decoded))
  if (-not (Test-Path -LiteralPath $resolved)) {
    $missing.Add([pscustomobject]@{ source = $SourceFile; target = $RawTarget; resolved = $resolved })
  }
}

foreach ($source in Get-ChildItem -LiteralPath $handoffRoot -Recurse -File -Filter '*.md') {
  $content = Get-Content -LiteralPath $source.FullName -Raw -Encoding UTF8
  $inlinePattern = '(?<prefix>!?\[[^\]\r\n]*\]\()(?<target><[^>\r\n]+>|[^)\s]+)(?<suffix>(?:\s+["''][^"'']*["''])?\))'
  foreach ($match in [regex]::Matches($content, $inlinePattern)) {
    Test-LinkTarget $match.Groups['target'].Value $source.FullName
  }
  $referencePattern = '(?m)^\s*\[[^\]]+\]:\s*(?<target><[^>\r\n]+>|\S+)'
  foreach ($match in [regex]::Matches($content, $referencePattern)) {
    Test-LinkTarget $match.Groups['target'].Value $source.FullName
  }
}

$unique = @($missing | Sort-Object source, target -Unique)
if ($unique.Count -gt 0) {
  $unique | Format-Table -AutoSize
  throw "Missing local Markdown targets: $($unique.Count)"
}
Write-Output 'Markdown local links: PASS'
