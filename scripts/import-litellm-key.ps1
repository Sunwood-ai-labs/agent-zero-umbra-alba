[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$EnvPath = (Join-Path (Split-Path $PSScriptRoot -Parent) ".env"),
    [string]$ProviderEnvPath = (Join-Path (Split-Path $PSScriptRoot -Parent) ".env.litellm")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found."
}

function New-RandomSecret {
    $bytes = [byte[]]::new(32)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return $values
    }
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*([^#=\s]+)=(.*)$') {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    return $values
}

function Set-DotEnvValues {
    param(
        [string]$Path,
        [hashtable]$Values
    )

    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @([IO.File]::ReadAllLines($Path))
    }
    foreach ($name in $Values.Keys) {
        $replacement = "$name=$($Values[$name])"
        $replaced = $false
        for ($index = 0; $index -lt $lines.Count; $index++) {
            if ($lines[$index] -match "^\s*$([regex]::Escape($name))=") {
                $lines[$index] = $replacement
                $replaced = $true
                break
            }
        }
        if (-not $replaced) {
            $lines += $replacement
        }
    }
    [IO.File]::WriteAllLines($Path, $lines, [Text.UTF8Encoding]::new($false))
}

if (-not (Test-Path -LiteralPath $EnvPath)) {
    $examplePath = Join-Path $ProjectRoot ".env.example"
    if (-not (Test-Path -LiteralPath $examplePath)) {
        throw ".env and .env.example are both missing."
    }
    Copy-Item -LiteralPath $examplePath -Destination $EnvPath
}

$envValues = Read-DotEnv -Path $EnvPath
$generatedValues = @{}
foreach ($name in @("POSTGRES_PASSWORD", "MISSKEY_SETUP_PASSWORD", "HERMES_API_SERVER_KEY")) {
    if ([string]::IsNullOrWhiteSpace($envValues[$name]) -or $envValues[$name] -match '^replace-with-') {
        $generatedValues[$name] = New-RandomSecret
    }
}
if ([string]::IsNullOrWhiteSpace($envValues["LITELLM_MASTER_KEY"]) -or $envValues["LITELLM_MASTER_KEY"] -match '^replace-with-') {
    $generatedValues["LITELLM_MASTER_KEY"] = "sk-$([guid]::NewGuid().ToString('N'))$(New-RandomSecret)"
}
$generatedValues["LITELLM_CONTAINER"] = "agent-zero-umbra-alba-litellm"
$generatedValues["LITELLM_API_BASE"] = "http://litellm:4000/v1"
$generatedValues["LITELLM_PROVIDER_ENV_FILE"] = ".env.litellm"
$generatedValues["LITELLM_HOST_PORT"] = if ([string]::IsNullOrWhiteSpace($envValues["LITELLM_HOST_PORT"])) { "4002" } else { $envValues["LITELLM_HOST_PORT"] }
$generatedValues["LITELLM_TAG"] = if ([string]::IsNullOrWhiteSpace($envValues["LITELLM_TAG"])) { "v1.93.0" } else { $envValues["LITELLM_TAG"] }
Set-DotEnvValues -Path $EnvPath -Values $generatedValues

if (-not (Test-Path -LiteralPath $ProviderEnvPath)) {
    $providerExamplePath = Join-Path $ProjectRoot ".env.litellm.example"
    if (-not (Test-Path -LiteralPath $providerExamplePath)) {
        throw "LiteLLM provider env is missing: $ProviderEnvPath"
    }
    Copy-Item -LiteralPath $providerExamplePath -Destination $ProviderEnvPath
    throw "Created '$ProviderEnvPath' from the template. Fill the provider key(s) and run start.ps1 again."
}

$providerValues = Read-DotEnv -Path $ProviderEnvPath
$models = (Read-DotEnv -Path $EnvPath)["LITELLM_MODELS"] -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }
if (($models | Where-Object { $_ -match '^glm-' }).Count -gt 0 -and [string]::IsNullOrWhiteSpace($providerValues["ZAI_API_KEY"])) {
    throw "ZAI_API_KEY is required in '$ProviderEnvPath' for the configured GLM models."
}

foreach ($path in @($EnvPath, $ProviderEnvPath)) {
    $relativePath = Resolve-Path -LiteralPath $path -Relative
    git -C $ProjectRoot check-ignore --quiet -- $relativePath
    if ($LASTEXITCODE -ne 0) {
        throw "Secret-bearing file is not ignored by Git: $path"
    }
}

Write-Host "Local LiteLLM configuration is ready. Provider credentials were not displayed."
