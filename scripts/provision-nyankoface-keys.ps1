[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SshKeyPath,

    [Parameter(Mandatory = $true)]
    [string]$SshTarget,

    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),

    [switch]$RotateMissing
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedKey = (Resolve-Path -LiteralPath $SshKeyPath).Path
$sshArgs = @(
    "-i", $resolvedKey,
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no"
)
$remoteTemp = "/tmp/nyankoface-agent-credentials-$PID.json"
$localTemp = Join-Path ([IO.Path]::GetTempPath()) "nyankoface-agent-credentials-$PID.json"

function Invoke-Remote([string]$Command) {
    & ssh @sshArgs $SshTarget $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Remote NyankoFace operation failed."
    }
}

function Assert-UnderRoot([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $prefix = $resolvedRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside the Agent Zero project runtime: $Path"
    }
    return $full
}

try {
    $provisionArgs = "docker exec nyankoface-spaces-runner python /app/provision_agent_identities.py"
    if ($RotateMissing) {
        $provisionArgs += " --rotate-missing"
    }
    Invoke-Remote $provisionArgs | Out-Null
    Invoke-Remote "docker cp nyankoface-spaces-runner:/data/agents/credentials.json $remoteTemp"

    & scp @sshArgs "${SshTarget}:$remoteTemp" $localTemp
    if ($LASTEXITCODE -ne 0) {
        throw "Could not retrieve the protected credential store."
    }

    $credentials = Get-Content -Raw -LiteralPath $localTemp | ConvertFrom-Json
    $bindings = @()
    foreach ($side in @("black", "white")) {
        $manifestPath = Join-Path $resolvedRoot ("runtime\instances\{0}\manifest.json" -f $side)
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        $index = 1
        foreach ($agent in @($manifest.agents)) {
            $slug = "{0}-{1}" -f $side, $agent.username
            $keyPath = Join-Path $resolvedRoot ("runtime\instances\{0}\agents\agent{1:00}\nyankoface-agent-api-key" -f $side, $index)
            $bindings += [pscustomobject]@{ Slug = $slug; KeyPath = (Assert-UnderRoot $keyPath) }
            $index++
        }
    }
    if ($bindings.Count -ne 20 -or @($bindings.Slug | Sort-Object -Unique).Count -ne 20) {
        throw "Expected exactly 20 unique black/white agent bindings."
    }

    $written = 0
    foreach ($binding in $bindings) {
        $property = $credentials.PSObject.Properties[$binding.Slug]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "NyankoFace did not provision a key for $($binding.Slug)."
        }
        $value = [string]$property.Value
        if ($value -notmatch '^of_agent_[A-Za-z0-9_-]{20,}$') {
            throw "NyankoFace returned an invalid key shape for $($binding.Slug)."
        }
        [IO.File]::WriteAllText($binding.KeyPath, $value, [Text.UTF8Encoding]::new($false))
        $written++
    }
    Write-Host "Provisioned $written per-agent NyankoFace key files; key contents were not displayed."
}
finally {
    if (Test-Path -LiteralPath $localTemp) {
        Remove-Item -LiteralPath $localTemp -Force
    }
    try {
        & ssh @sshArgs $SshTarget "rm -f -- $remoteTemp" | Out-Null
    }
    catch {
        Write-Warning "Could not remove the temporary remote credential export. Remove $remoteTemp on the remote host."
    }
}
