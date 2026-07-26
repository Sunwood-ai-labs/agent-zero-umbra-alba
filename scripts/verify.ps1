[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$compose = Join-Path $projectRoot "compose.yaml"

$manifestPath = Join-Path $projectRoot "runtime\manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Bootstrap manifest is missing: $manifestPath"
}
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.agentCount -ne 10) {
    throw "Expected 10 agents, found $($manifest.agentCount)."
}
$premisePath = Join-Path $projectRoot "seed\scenarios\blank-basin.md"
$premiseText = (Get-Content -Raw -LiteralPath $premisePath).Trim()
$premiseBytes = [System.Text.Encoding]::UTF8.GetBytes($premiseText)
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$premiseHash = ([BitConverter]::ToString($sha256.ComputeHash($premiseBytes))).Replace("-", "").ToLowerInvariant()
$sha256.Dispose()
if ($manifest.worldPremise.name -ne "blank-basin" -or $manifest.worldPremise.sha256 -ne $premiseHash) {
    throw "Runtime manifest does not contain the current blank-basin premise."
}
$modelCounts = @($manifest.agents | Group-Object model)
foreach ($requiredModel in @("glm-5.2", "glm-4.7")) {
    $count = ($modelCounts | Where-Object Name -eq $requiredModel).Count
    if ($count -ne 5) {
        throw "Expected 5 agents on $requiredModel, found $count."
    }
}

$services = docker compose --project-directory $projectRoot -f $compose ps --status running --services
$runningAgents = @($services | Where-Object { $_ -match "^agent\d{2}$" })
if ($runningAgents.Count -ne 10) {
    throw "Expected 10 running Hermes services, found $($runningAgents.Count)."
}
if ($services -notcontains "random-scheduler") {
    throw "Random scheduler is not running."
}

$meta = Invoke-RestMethod -Method Post -Uri "$($manifest.misskeyUrl)/api/meta" `
    -ContentType "application/json" -Body '{"detail":false}' -TimeoutSec 30
if (-not $meta.version) {
    throw "Misskey meta endpoint did not return a version."
}

foreach ($service in $runningAgents) {
    $jobPath = Join-Path $projectRoot "runtime\agents\$service\cron\jobs.json"
    $jobs = @(Get-Content -Raw -LiteralPath $jobPath | ConvertFrom-Json)
    if ($jobs | Where-Object id -eq ("social-" + $service.Substring(5))) {
        throw "Legacy fixed-interval social job still exists for $service."
    }
    $worldPath = Join-Path $projectRoot "runtime\agents\$service\WORLD.md"
    if (-not (Test-Path -LiteralPath $worldPath)) {
        throw "Shared world premise is missing for $service."
    }
    if ((Get-Content -Raw -LiteralPath $worldPath).Trim() -ne $premiseText) {
        throw "Shared world premise differs for $service."
    }
    $configPath = Join-Path $projectRoot "runtime\agents\$service\config.yaml"
    if (-not (Test-Path -LiteralPath $configPath)) {
        throw "Hermes config is missing for $service."
    }
    $configText = Get-Content -Raw -LiteralPath $configPath
    if (
        $configText -notmatch '(?m)^  memory_enabled: true\s*$' -or
        $configText -notmatch '(?m)^  nudge_interval: 10\s*$'
    ) {
        throw "Hermes memory review is not configured for every 10 turns in $service."
    }
    $socialSkillPath = Join-Path $projectRoot "runtime\agents\$service\skills\misskey-social\SKILL.md"
    if (
        -not (Test-Path -LiteralPath $socialSkillPath) -or
        (Get-Content -Raw -LiteralPath $socialSkillPath) -notmatch 'history --limit 40'
    ) {
        throw "40-note self-history review is not installed for $service."
    }
}

docker compose --project-directory $projectRoot -f $compose exec -T random-scheduler `
    python /app/verify_runtime.py
if ($LASTEXITCODE -ne 0) {
    throw "Hermes API or skill-distribution verification failed."
}

$statePath = Join-Path $projectRoot "runtime\scheduler\schedule.json"
$deadline = (Get-Date).AddMinutes(5)
do {
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        $entries = @($state.agents.PSObject.Properties | ForEach-Object Value)
        if ($entries.Count -eq 10 -and @($entries | Where-Object { $_.runCount -lt 1 }).Count -eq 0) {
            break
        }
    }
    if ((Get-Date) -ge $deadline) {
        throw "Timed out waiting for all 10 random-scheduler agents to complete an activity cycle."
    }
    Start-Sleep -Seconds 10
} while ($true)

$failed = @($entries | Where-Object { $_.lastStatus -eq "error" })
if ($failed.Count -gt 0) {
    throw "$($failed.Count) random-scheduler agent runs did not finish successfully."
}
$intervals = @($entries | ForEach-Object { [int]$_.lastIntervalMinutes })
if (($intervals | Measure-Object -Minimum).Minimum -lt 2 -or ($intervals | Measure-Object -Maximum).Maximum -gt 30) {
    throw "A randomized interval fell outside 2-30 minutes."
}

Write-Host "Verified Misskey $($meta.version), 5x GLM 5.2 + 5x GLM 4.7, Hermes memory review every 10 turns, 40-note self-history review, the shared blank-basin premise, autonomous random activity, and the distributed Misskey skill."
