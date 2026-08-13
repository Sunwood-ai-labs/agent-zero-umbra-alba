param(
    [switch]$Down,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $repo 'compose.yaml'
$rootEnvFile = Join-Path $repo '.env'
$envFile = Join-Path $repo '.env.dctf'

if (-not (Test-Path -LiteralPath $envFile)) {
    $dataDirs = @(
        (Join-Path $repo 'runtime\dctf\black\mysql'),
        (Join-Path $repo 'runtime\dctf\white\mysql')
    ) | Where-Object { Test-Path -LiteralPath $_ }

    if ($dataDirs.Count -eq 0) {
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        function New-Secret {
            param([int]$Length = 32)
            $bytes = New-Object byte[] $Length
            $rng.GetBytes($bytes)
            return (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
        }
        @(
            'DCTF_BLACK_PORT=8400'
            'DCTF_WHITE_PORT=8401'
            "DCTF_BLACK_DB_ROOT_PASSWORD=$(New-Secret)"
            "DCTF_BLACK_DB_PASSWORD=$(New-Secret)"
            "DCTF_BLACK_SECRET_KEY=$(New-Secret)"
            "DCTF_WHITE_DB_ROOT_PASSWORD=$(New-Secret)"
            "DCTF_WHITE_DB_PASSWORD=$(New-Secret)"
            "DCTF_WHITE_SECRET_KEY=$(New-Secret)"
        ) | Set-Content -LiteralPath $envFile -Encoding ascii
        $rng.Dispose()
        Write-Output "Generated private $envFile"
    } else {
        Write-Output 'Existing DCTF data detected; using Compose defaults until .env.dctf is provisioned.'
    }
}

$composeArgs = @('--project-name', 'agent-zero-umbra-alba', '--file', $compose)
if (Test-Path -LiteralPath $rootEnvFile) {
    $composeArgs += @('--env-file', $rootEnvFile)
}
if (Test-Path -LiteralPath $envFile) {
    $composeArgs += @('--env-file', $envFile)
}

if ($Down) {
    & docker compose @composeArgs down
    exit $LASTEXITCODE
}

if ($Status) {
    & docker compose @composeArgs ps
    Write-Output 'Black CTFd: http://127.0.0.1:8400'
    Write-Output 'White CTFd: http://127.0.0.1:8401'
    exit $LASTEXITCODE
}

& docker compose @composeArgs up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output 'Black CTFd: http://127.0.0.1:8400/setup (first-run setup)'
Write-Output 'White CTFd: http://127.0.0.1:8401/setup (first-run setup)'
