function ConvertTo-EndpointKey([string]$Url) {
  if ([string]::IsNullOrWhiteSpace($Url)) { return $null }
  $uri = $null
  if (-not [Uri]::TryCreate($Url.Trim(), [UriKind]::Absolute, [ref]$uri)) { return $null }
  if ($uri.Scheme -notin @('http', 'https')) { return $null }
  if ($uri.UserInfo -or $uri.Query -or $uri.Fragment) { return $null }
  $path = $uri.AbsolutePath.TrimEnd('/')
  return ('{0}://{1}:{2}{3}' -f $uri.Scheme.ToLowerInvariant(), $uri.Host.ToLowerInvariant(), $uri.Port, $path)
}

function Test-SameEndpoint([string]$Left, [string]$Right) {
  $leftKey = ConvertTo-EndpointKey $Left
  $rightKey = ConvertTo-EndpointKey $Right
  return $null -ne $leftKey -and $null -ne $rightKey -and $leftKey -eq $rightKey
}

function Test-BridgeHealthMatchesCore($Health, [string]$CoreUrl) {
  return $null -ne $Health -and $Health.bridge -eq 'ok' -and
         (Test-SameEndpoint ([string]$Health.core_url) $CoreUrl)
}
