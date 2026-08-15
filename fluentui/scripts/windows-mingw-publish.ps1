[CmdletBinding()]
param (
    [string] $archiveName, [string] $targetName
)
# 外部环境变量包括:
# archiveName: ${{ matrix.qt_ver }}-${{ matrix.qt_arch }}


# archiveName: 5.15.2-win64_mingw81

$scriptDir = $PSScriptRoot

# Migration 2026-08-15: all file deletions go to the Recycle Bin for rollback.
function Remove-ItemRecycleBin {
  param([Parameter(Mandatory=$true)][string]$LiteralPath)
  if (-not (Test-Path -LiteralPath $LiteralPath)) { return }
  Add-Type -AssemblyName Microsoft.VisualBasic
  if ((Get-Item -LiteralPath $LiteralPath -Force).PSIsContainer) {
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($LiteralPath, 'OnlyErrorDialogs', 'SendToRecycleBin')
  } else {
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($LiteralPath, 'OnlyErrorDialogs', 'SendToRecycleBin')
  }
}
$currentDir = Get-Location
Write-Host "currentDir" $currentDir
Write-Host "scriptDir" $scriptDir

function Main() {

    New-Item -ItemType Directory $archiveName
    # 拷贝exe
    Copy-Item bin\release\* $archiveName\ -Force -Recurse | Out-Null
    # 拷贝依赖
    windeployqt --qmldir . --plugindir $archiveName\plugins --no-translations --compiler-runtime $archiveName\$targetName
    # 删除不必要的文件
    $excludeList = @("*.qmlc", "*.ilk", "*.exp", "*.lib", "*.pdb")
    Get-ChildItem -Path $archiveName -Include $excludeList -Recurse -Force | ForEach-Object { Remove-ItemRecycleBin -LiteralPath $_.FullName }
    # 打包zip
    Compress-Archive -Path $archiveName $archiveName'.zip'
}

if ($null -eq $archiveName || $null -eq $targetName) {
    Write-Host "args missing, archiveName is" $archiveName ", targetName is" $targetName
    return
}
Main
