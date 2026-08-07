[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$WorldHttpsPort = 8470,

    [ValidateRange(1, 65535)]
    [int]$BlackHttpsPort = 8471,

    [ValidateRange(1, 65535)]
    [int]$WhiteHttpsPort = 8472,

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

$routes = @(
    @{ Key = "WORLD_PUBLIC_URL"; HttpsPort = $WorldHttpsPort; LocalPort = 3310 },
    @{ Key = "BLACK_PUBLIC_URL"; HttpsPort = $BlackHttpsPort; LocalPort = 3311 },
    @{ Key = "WHITE_PUBLIC_URL"; HttpsPort = $WhiteHttpsPort; LocalPort = 3312 }
)

foreach ($route in $routes) {
    tailscale serve --bg --yes --https=$($route.HttpsPort) "http://127.0.0.1:$($route.LocalPort)"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to configure Tailscale Serve on HTTPS port $($route.HttpsPort)."
    }
}

$lines = [Collections.Generic.List[string]]::new()
$updated = $false
foreach ($line in [IO.File]::ReadAllLines($EnvPath)) {
    $matched = $false
    foreach ($route in $routes) {
        if ($line -match "^$($route.Key)=") {
            $lines.Add("$($route.Key)=https://${dnsName}:$($route.HttpsPort)")
            $matched = $true
            $updated = $true
            break
        }
    }
    if (-not $matched) {
        $lines.Add($line)
    }
}
foreach ($route in $routes) {
    if (-not ($lines | Where-Object { $_ -match "^$($route.Key)=" })) {
        $lines.Add("$($route.Key)=https://${dnsName}:$($route.HttpsPort)")
    }
}

[IO.File]::WriteAllLines($EnvPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Configured Tailnet-only URLs: world=https://${dnsName}:$WorldHttpsPort, black=https://${dnsName}:$BlackHttpsPort, white=https://${dnsName}:$WhiteHttpsPort"
