[CmdletBinding()]
param(
    [string]$ContainerName = "open-webui-litellm",
    [string]$OutputPath = (Join-Path (Split-Path $PSScriptRoot -Parent) ".env")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found."
}

$containerJson = docker inspect $ContainerName 2>$null
if ($LASTEXITCODE -ne 0 -or -not $containerJson) {
    throw "LiteLLM container '$ContainerName' was not found."
}

$container = ($containerJson | ConvertFrom-Json)[0]
$environment = @{}
foreach ($entry in $container.Config.Env) {
    $parts = $entry -split "=", 2
    if ($parts.Count -eq 2) {
        $environment[$parts[0]] = $parts[1]
    }
}

$masterKey = $environment["LITELLM_MASTER_KEY"]
if ([string]::IsNullOrWhiteSpace($masterKey)) {
    throw "LITELLM_MASTER_KEY is not set in '$ContainerName'."
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

$values = [ordered]@{
    MISSKEY_PORT = "3200"
    MISSKEY_URL = "http://localhost:3200"
    MISSKEY_INTERNAL_URL = "http://misskey:3000"
    POSTGRES_DB = "misskey"
    POSTGRES_USER = "misskey"
    POSTGRES_PASSWORD = (New-RandomSecret)
    MISSKEY_SETUP_PASSWORD = (New-RandomSecret)
    MISSKEY_ADMIN_USERNAME = "admin"
    LITELLM_CONTAINER = $ContainerName
    LITELLM_API_BASE = "http://host.docker.internal:4000/v1"
    LITELLM_MODELS = "glm-5.2,glm-4.7"
    LITELLM_MASTER_KEY = $masterKey
    HERMES_API_SERVER_KEY = (New-RandomSecret)
    RANDOM_INTERVAL_MINUTES_MIN = "2"
    RANDOM_INTERVAL_MINUTES_MAX = "30"
    RANDOM_FAST_MAX_MINUTES = "10"
    RANDOM_FAST_PROBABILITY = "0.75"
    RANDOM_INITIAL_MAX_SECONDS = "90"
}

if (Test-Path -LiteralPath $OutputPath) {
    foreach ($line in [IO.File]::ReadAllLines($OutputPath)) {
        if ($line -match "^\s*([^#=\s]+)=(.*)$" -and $values.Contains($Matches[1])) {
            $values[$Matches[1]] = $Matches[2]
        }
    }
    # Always refresh the key from the live LiteLLM container.
    $values["LITELLM_MASTER_KEY"] = $masterKey
}

$lines = foreach ($item in $values.GetEnumerator()) {
    "$($item.Key)=$($item.Value)"
}
[IO.File]::WriteAllLines($OutputPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Imported the LiteLLM master key into .env without displaying it."
