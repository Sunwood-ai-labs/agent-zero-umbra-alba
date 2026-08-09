[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$SshTarget = "",
    [string]$SshKeyFile = "",
    [string]$RemoteContainer = "",
    [string]$SubjectId = "",
    [string]$Repository = "",
    [ValidateRange(1, 7776000)]
    [int]$TokenTtlSeconds = 2592000,
    [switch]$RequireMcpToken
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path $PSScriptRoot -Parent
}

function Get-ProjectEnvValue {
    param([string]$Name)

    $path = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $path)) {
        return ""
    }
    foreach ($line in Get-Content -LiteralPath $path) {
        if ($line -match "^$([regex]::Escape($Name))=(.*)$") {
            return $Matches[1].Trim()
        }
    }
    return ""
}

if ([string]::IsNullOrWhiteSpace($SshTarget)) {
    $SshTarget = Get-ProjectEnvValue "NYANKOFACE_SSH_TARGET"
}
if ([string]::IsNullOrWhiteSpace($SshKeyFile)) {
    $SshKeyFile = Get-ProjectEnvValue "NYANKOFACE_SSH_KEY_FILE"
}
if ([string]::IsNullOrWhiteSpace($RemoteContainer)) {
    $RemoteContainer = Get-ProjectEnvValue "NYANKOFACE_MCP_ADMIN_CONTAINER"
}
if ([string]::IsNullOrWhiteSpace($RemoteContainer)) {
    $RemoteContainer = "nyankoface-mcp-admin-1"
}
if ([string]::IsNullOrWhiteSpace($SubjectId)) {
    $SubjectId = Get-ProjectEnvValue "NYANKOFACE_MCP_SERVICE_ACCOUNT"
}
if ([string]::IsNullOrWhiteSpace($SubjectId)) {
    $SubjectId = "service:codex-reader"
}
if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = Get-ProjectEnvValue "NYANKOFACE_MCP_REPOSITORY"
}
if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = "Sunwood-ai-labs/NyankoFace"
}

# NYANKOFACE_SSH_TARGET is also used as an scp-style mirror destination in
# existing deployments. For the provisioning command only the SSH host is
# needed, so accept both `host` and `host:/remote/path` forms.
if ($SshTarget -match '^(?<host>[^:]+):/.+$') {
    $SshTarget = $Matches["host"]
}

if ($SubjectId -notmatch '^[A-Za-z0-9:_.-]{1,128}$') {
    throw "NYANKOFACE MCP service account identifier is invalid."
}
if ($Repository -notmatch '^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$') {
    throw "NYANKOFACE MCP repository constraint is invalid."
}
if ($RemoteContainer -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "NYANKOFACE MCP admin container name is invalid."
}

$agentSpecs = foreach ($faction in @("black", "white")) {
    foreach ($index in 1..10) {
        [pscustomobject]@{
            Faction = $faction
            Index = $index
            AgentId = "agent{0:00}" -f $index
            ClientId = "agent-zero-{0}-agent{1:00}" -f $faction, $index
        }
    }
}

$missing = @()
$existingCount = 0
foreach ($spec in $agentSpecs) {
    $agentDir = Join-Path $ProjectRoot ("runtime\instances\{0}\agents\{1}" -f $spec.Faction, $spec.AgentId)
    $tokenPath = Join-Path $agentDir "nyankoface-mcp-token"
    if (Test-Path -LiteralPath $tokenPath) {
        $value = (Get-Content -Raw -LiteralPath $tokenPath -ErrorAction SilentlyContinue).Trim()
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $existingCount++
            continue
        }
    }
    $missing += [pscustomobject]@{ Spec = $spec; AgentDir = $agentDir; TokenPath = $tokenPath }
}

if ($missing.Count -eq 0) {
    Write-Output ("NyankoFace MCP token provisioning complete: existing={0}, issued=0, total={1}." -f $existingCount, $agentSpecs.Count)
    exit 0
}

if ([string]::IsNullOrWhiteSpace($SshTarget)) {
    if ($RequireMcpToken) {
        throw "NyankoFace MCP tokens are missing and NYANKOFACE_SSH_TARGET is not configured."
    }
    Write-Warning "NyankoFace MCP tokens are not provisioned; Forgejo fallback remains available."
    exit 0
}

$sshArgs = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
if (-not [string]::IsNullOrWhiteSpace($SshKeyFile)) {
    if (-not (Test-Path -LiteralPath $SshKeyFile)) {
        throw "Configured NYANKOFACE_SSH_KEY_FILE does not exist."
    }
    $sshArgs += @("-o", "IdentitiesOnly=yes", "-i", $SshKeyFile)
}

$issuedCount = 0
$reauthenticatedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$scopes = @(
    "catalog:read",
    "repos:read",
    "issues:read",
    "spaces:read",
    "pages:read",
    "pipelines:read",
    "metrics:read"
)

foreach ($item in $missing) {
    $spec = $item.Spec
    $remoteCommandParts = @(
        "docker exec",
        $RemoteContainer,
        "python -m nyankoface_mcp.admin",
        "--registry /run/nyankoface-mcp/registry.json",
        "--audit /run/nyankoface-mcp/lifecycle-audit.jsonl",
        "--actor agent-zero-bootstrap",
        "--reauthenticated-at $reauthenticatedAt",
        "issue-token",
        $SubjectId,
        "--client-id $($spec.ClientId)"
    )
    foreach ($scope in $scopes) {
        $remoteCommandParts += "--scope $scope"
    }
    $remoteCommandParts += @(
        "--repository $Repository",
        "--ttl-seconds $TokenTtlSeconds"
    )
    $remoteCommand = $remoteCommandParts -join " "

    $raw = & ssh @sshArgs $SshTarget $remoteCommand 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw ("NyankoFace MCP token provisioning failed for {0}/{1}." -f $spec.Faction, $spec.AgentId)
    }
    try {
        $issued = ($raw -join "`n") | ConvertFrom-Json
        $token = [string]$issued.token
    }
    catch {
        throw ("NyankoFace MCP token provisioning returned invalid metadata for {0}/{1}." -f $spec.Faction, $spec.AgentId)
    }
    if ([string]::IsNullOrWhiteSpace($token) -or $token.Length -lt 32) {
        throw ("NyankoFace MCP token provisioning returned no usable token for {0}/{1}." -f $spec.Faction, $spec.AgentId)
    }

    New-Item -ItemType Directory -Force -Path $item.AgentDir | Out-Null
    [System.IO.File]::WriteAllText(
        $item.TokenPath,
        $token + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    $issuedCount++
}

Write-Output ("NyankoFace MCP token provisioning complete: existing={0}, issued={1}, total={2}." -f $existingCount, $issuedCount, $agentSpecs.Count)
