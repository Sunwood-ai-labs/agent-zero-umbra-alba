param(
  [ValidateSet("black", "white")]
  [string]$Faction = "black"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $repoRoot "runtime\instances\$Faction\agents"
$dbService = if ($Faction -eq "black") { "dctf-black-db" } else { "dctf-white-db" }
$dbContainer = docker ps -q --filter "label=com.docker.compose.project=agent-zero-umbra-alba" --filter "label=com.docker.compose.service=$dbService" | Select-Object -First 1
$port = if ($Faction -eq "black") { 8400 } else { 8401 }
$bank = if ($Faction -eq "black") { "CTFd-B" } else { "CTFd-W" }

if ([string]::IsNullOrWhiteSpace($dbContainer)) {
  throw "CTFd database container is not running for service: $dbService"
}
$dbEnv = (docker inspect $dbContainer | ConvertFrom-Json)[0].Config.Env
$dbPassword = (($dbEnv | Where-Object { $_ -like 'MARIADB_PASSWORD=*' }) -replace '^MARIADB_PASSWORD=', '') | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($dbPassword)) {
  throw "MARIADB_PASSWORD is not available on container: $dbContainer"
}

for ($index = 1; $index -le 10; $index++) {
  $agentName = "agent{0:D2}" -f $index
  $agentDir = Join-Path $runtimeRoot $agentName
  New-Item -ItemType Directory -Force -Path $agentDir | Out-Null
  $tokenPath = Join-Path $agentDir "ctfd-api-token"
  $token = if (Test-Path -LiteralPath $tokenPath) {
    ([IO.File]::ReadAllText($tokenPath)).Trim()
  } else { "" }
  if ($token -notmatch '^ctfd_[0-9a-f]{64}$') {
    $bytes = [byte[]]::new(32)
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $token = "ctfd_" + ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
  }

  # CTFd's API token lookup is backed by the UserTokens model. The existing
  # faction admin (user id 1) is intentionally used only for that faction;
  # every agent still receives a distinct token value and token description.
  $description = "agent-$Faction-$agentName direct challenge API"
  $sql = "INSERT INTO tokens (type,user_id,created,expiration,value,description) SELECT 'user',1,NOW(),DATE_ADD(NOW(), INTERVAL 3650 DAY),'$token','$description' WHERE NOT EXISTS (SELECT 1 FROM tokens WHERE value='$token'); UPDATE tokens SET expiration=DATE_ADD(NOW(), INTERVAL 3650 DAY), type='user', user_id=1, description='$description' WHERE value='$token';"
  & docker exec $dbContainer mariadb -uctfd "-p$dbPassword" ctfd -e $sql | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "failed to provision CTFd token for $Faction/$agentName" }

  [IO.File]::WriteAllText($tokenPath, $token, [Text.UTF8Encoding]::new($false))
  $config = [ordered]@{
    faction = $Faction
    bank = $bank
    api_url = "http://dctf-$Faction`:8000/api/v1"
    base_url = "http://dctf-$Faction`:8000"
    token_file = "/opt/data/ctfd-api-token"
    timeout_seconds = 20
  }
  $configPath = Join-Path $agentDir "ctfd-api.json"
  [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}

Write-Output "Provisioned 10 distinct CTFd API tokens for $Faction (token values omitted)."
