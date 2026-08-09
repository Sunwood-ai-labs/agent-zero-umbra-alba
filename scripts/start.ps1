[CmdletBinding()]
param(
    [switch]$PublishWithTailscale,
    [ValidateRange(1, 65535)]
    [int]$TailscaleHttpsPort = 8470,
    [switch]$SkipNyankoFaceMcpProvisioning
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent

& (Join-Path $PSScriptRoot "import-litellm-key.ps1")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($PublishWithTailscale) {
    & (Join-Path $PSScriptRoot "publish-tailscale.ps1") `
        -WorldHttpsPort $TailscaleHttpsPort
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not $SkipNyankoFaceMcpProvisioning) {
    & (Join-Path $PSScriptRoot "provision-nyankoface-mcp-tokens.ps1") `
        -ProjectRoot $projectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "NyankoFace MCP token provisioning failed."
    }
}

docker compose --project-directory $projectRoot -f (Join-Path $projectRoot "compose.yaml") config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Compose validation failed."
}

docker compose --project-directory $projectRoot -f (Join-Path $projectRoot "compose.yaml") up -d
if ($LASTEXITCODE -ne 0) {
    throw "Compose startup failed."
}

& (Join-Path $PSScriptRoot "verify.ps1")
