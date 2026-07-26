[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$HttpsPort = 8446,

    [ValidateRange(1, 65535)]
    [int]$LocalPort = 3200,

    [string]$EnvPath = (Join-Path (Split-Path $PSScriptRoot -Parent) ".env")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    throw "Tailscale CLI was not found."
}
if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw ".env is missing. Run scripts/import-litellm-key.ps1 first."
}

$status = tailscale status --json | ConvertFrom-Json
if (-not $status.Self.Online) {
    throw "This Tailscale node is offline."
}

$dnsName = ([string]$status.Self.DNSName).TrimEnd(".")
if ([string]::IsNullOrWhiteSpace($dnsName)) {
    throw "Tailscale DNS name was not available. Enable MagicDNS for the tailnet."
}

$publicUrl = "https://${dnsName}:$HttpsPort"

tailscale serve --bg --yes --https=$HttpsPort "http://127.0.0.1:$LocalPort"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to configure Tailscale Serve on HTTPS port $HttpsPort."
}

$lines = [Collections.Generic.List[string]]::new()
$updated = $false
foreach ($line in [IO.File]::ReadAllLines($EnvPath)) {
    if ($line -match "^MISSKEY_URL=") {
        $lines.Add("MISSKEY_URL=$publicUrl")
        $updated = $true
    }
    else {
        $lines.Add($line)
    }
}
if (-not $updated) {
    $lines.Add("MISSKEY_URL=$publicUrl")
}

[IO.File]::WriteAllLines($EnvPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Configured Tailnet-only Misskey URL: $publicUrl"
