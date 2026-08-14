$ErrorActionPreference = 'Stop'

. (Join-Path (Split-Path -Parent $PSScriptRoot) 'wiring.ps1')

function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}

Assert-True (Test-SameEndpoint 'http://127.0.0.1:22267' 'http://127.0.0.1:22267/') '尾部斜杠应等价'
Assert-True (Test-SameEndpoint 'HTTP://LOCALHOST:22367' 'http://localhost:22367/') '主机和协议大小写应等价'
Assert-True (-not (Test-SameEndpoint 'http://127.0.0.1:22267' 'http://127.0.0.1:22268')) '不同端口不得等价'
Assert-True (-not (Test-SameEndpoint '' 'http://127.0.0.1:22267')) '空 URL 不得通过'
Assert-True (-not (Test-SameEndpoint 'not-a-url' 'http://127.0.0.1:22267')) '无效 URL 不得通过'

$matchingHealth = [pscustomobject]@{ bridge = 'ok'; core_url = 'http://127.0.0.1:22267/' }
$wrongCoreHealth = [pscustomobject]@{ bridge = 'ok'; core_url = 'http://127.0.0.1:22268' }
$failedHealth = [pscustomobject]@{ bridge = 'failed'; core_url = 'http://127.0.0.1:22267' }
Assert-True (Test-BridgeHealthMatchesCore $matchingHealth 'http://127.0.0.1:22267') '健康 Bridge 应匹配请求的 Core'
Assert-True (-not (Test-BridgeHealthMatchesCore $wrongCoreHealth 'http://127.0.0.1:22267')) '错误 Core 身份不得通过'
Assert-True (-not (Test-BridgeHealthMatchesCore $failedHealth 'http://127.0.0.1:22267')) '非健康 Bridge 不得通过'

Write-Output 'wiring endpoint tests passed'
