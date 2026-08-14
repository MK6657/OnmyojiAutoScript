[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$ArchiveName = 'legacy-root-20260811'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$handoffRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$archiveRoot = [IO.Path]::GetFullPath((Join-Path $handoffRoot (Join-Path 'archive' $ArchiveName)))
if (-not $archiveRoot.StartsWith($handoffRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
  throw "Archive path escapes handoff root: $archiveRoot"
}

$keepNames = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
@(
  'README.md',
  'coordinates-to-calibrate-20260809.md',
  'MDAt5b2T5YmN54q25oCBLm1k',
  'MDEt6L+Q6KGM5LiO5YGc5q2iLm1k',
  'MDIt6YWN572u5LiO5pWw5o2u5b2S5bGeLm1k',
  'MDMt5Lu75Yqh55Sf5ZG95ZGo5pyfLm1k',
  'MDQt5rWL6K+V5LiO57uT5qGI6KeE6IyDLm1k',
  'Q29kZXgt5b6F5YGa5LqL6aG55oC76KGoLm1k'
) | ForEach-Object {
  $name = if ($_ -match '^[A-Za-z0-9+/]+={0,2}$' -and $_ -notlike '*.md') {
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_))
  } else {
    $_
  }
  [void]$keepNames.Add($name)
}

$candidates = @(
  Get-ChildItem -LiteralPath $handoffRoot -File |
    Where-Object { -not $keepNames.Contains($_.Name) } |
    Sort-Object Name
)
Write-Verbose ("Root files={0}, keep_names={1}, candidates={2}" -f @(Get-ChildItem -LiteralPath $handoffRoot -File).Count, $keepNames.Count, $candidates.Count)
Write-Verbose (($candidates | Group-Object { $_.GetType().FullName } | ForEach-Object { "type=$($_.Name),count=$($_.Count)" }) -join '; ')
if ($candidates.Count -eq 0) {
  Write-Output 'No root history files need archiving.'
  exit 0
}

$pathMap = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($file in $candidates) {
  $destination = [IO.Path]::GetFullPath((Join-Path $archiveRoot $file.Name))
  if (Test-Path -LiteralPath $destination) {
    throw "Archive destination already exists: $destination"
  }
  $pathMap[$file.FullName] = $destination
}

function Get-RelativeMarkdownPath([string]$SourceFile, [string]$TargetFile) {
  $sourceDirectory = [IO.Path]::GetDirectoryName($SourceFile) + [IO.Path]::DirectorySeparatorChar
  $sourceUri = [Uri]::new($sourceDirectory)
  $targetUri = [Uri]::new($TargetFile)
  return [Uri]::UnescapeDataString($sourceUri.MakeRelativeUri($targetUri).ToString())
}

function Get-RewrittenTarget([string]$RawTarget, [string]$OldSource, [string]$NewSource) {
  $wasBracketed = $RawTarget.StartsWith('<') -and $RawTarget.EndsWith('>')
  $target = if ($wasBracketed) { $RawTarget.Substring(1, $RawTarget.Length - 2) } else { $RawTarget }
  if ([string]::IsNullOrWhiteSpace($target) -or $target.StartsWith('#') -or
      $target.StartsWith('/') -or $target -match '^[A-Za-z][A-Za-z0-9+.-]*:') {
    return $RawTarget
  }

  $fragment = ''
  $fragmentIndex = $target.IndexOf('#')
  if ($fragmentIndex -ge 0) {
    $fragment = $target.Substring($fragmentIndex)
    $target = $target.Substring(0, $fragmentIndex)
  }
  $decodedTarget = [Uri]::UnescapeDataString($target)
  $oldTarget = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetDirectoryName($OldSource)) $decodedTarget))
  $targetMoved = $pathMap.ContainsKey($oldTarget)
  $sourceMoved = -not $OldSource.Equals($NewSource, [StringComparison]::OrdinalIgnoreCase)
  if (-not $sourceMoved -and -not $targetMoved) { return $RawTarget }
  if (-not $targetMoved -and -not (Test-Path -LiteralPath $oldTarget)) { return $RawTarget }

  $newTarget = if ($targetMoved) { $pathMap[$oldTarget] } else { $oldTarget }
  $relative = (Get-RelativeMarkdownPath $NewSource $newTarget) + $fragment
  if ($wasBracketed) { return '<' + $relative + '>' }
  return $relative
}

$rewrites = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::OrdinalIgnoreCase)
$markdownFiles = @(Get-ChildItem -LiteralPath $handoffRoot -Recurse -File -Filter '*.md')
foreach ($source in $markdownFiles) {
  $oldSource = $source.FullName
  $newSource = if ($pathMap.ContainsKey($oldSource)) { $pathMap[$oldSource] } else { $oldSource }
  $content = Get-Content -LiteralPath $oldSource -Raw -Encoding UTF8

  $inlinePattern = '(?<prefix>!?\[[^\]\r\n]*\]\()(?<target><[^>\r\n]+>|[^)\s]+)(?<suffix>(?:\s+["''][^"'']*["''])?\))'
  $content = [regex]::Replace($content, $inlinePattern, {
    param($match)
    $rewritten = Get-RewrittenTarget $match.Groups['target'].Value $oldSource $newSource
    return $match.Groups['prefix'].Value + $rewritten + $match.Groups['suffix'].Value
  })

  $referencePattern = '(?m)^(?<prefix>\s*\[[^\]]+\]:\s*)(?<target><[^>\r\n]+>|\S+)'
  $content = [regex]::Replace($content, $referencePattern, {
    param($match)
    $rewritten = Get-RewrittenTarget $match.Groups['target'].Value $oldSource $newSource
    return $match.Groups['prefix'].Value + $rewritten
  })

  $original = Get-Content -LiteralPath $oldSource -Raw -Encoding UTF8
  if ($content -cne $original) { $rewrites[$newSource] = $content }
}

$bytes = ($candidates | Measure-Object Length -Sum).Sum
Write-Output ("Archive plan: files={0}, bytes={1}, markdown_rewrites={2}, target={3}" -f $candidates.Count, $bytes, $rewrites.Count, $archiveRoot)
Write-Verbose ("Rewrite files: " + (($rewrites.Keys | Sort-Object) -join '; '))
if (-not $PSCmdlet.ShouldProcess($archiveRoot, "Move $($candidates.Count) root history files and rewrite $($rewrites.Count) Markdown files")) {
  exit 0
}

New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
$manifest = foreach ($file in $candidates) {
  [pscustomobject]@{
    name = $file.Name
    bytes = $file.Length
    sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    archived_at = (Get-Date).ToString('o')
  }
}
$manifest | Export-Csv -LiteralPath (Join-Path $archiveRoot 'MANIFEST.csv') -NoTypeInformation -Encoding UTF8

foreach ($file in $candidates) {
  Move-Item -LiteralPath $file.FullName -Destination $pathMap[$file.FullName]
}
foreach ($entry in $rewrites.GetEnumerator()) {
  Set-Content -LiteralPath $entry.Key -Value $entry.Value -Encoding UTF8 -NoNewline
}

Write-Output ("Archived {0} files to {1}" -f $candidates.Count, $archiveRoot)
