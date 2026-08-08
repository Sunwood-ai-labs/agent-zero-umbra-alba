[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$compose = Join-Path $projectRoot "compose.yaml"

$instances = @(
    [pscustomobject]@{ Name = "world"; Faction = "world"; Url = "http://127.0.0.1:3310"; ExpectedAgents = 0 },
    [pscustomobject]@{ Name = "black"; Faction = "black"; Url = "http://127.0.0.1:3311"; ExpectedAgents = 10 },
    [pscustomobject]@{ Name = "white"; Faction = "white"; Url = "http://127.0.0.1:3312"; ExpectedAgents = 10 }
)
$agentInstances = @($instances | Where-Object ExpectedAgents -gt 0)

$premisePath = Join-Path $projectRoot "seed\scenarios\twin-moon-basin.md"
$premiseText = ((Get-Content -Raw -LiteralPath $premisePath) -replace "`r`n", "`n" -replace "`r", "`n").Trim()
$sha256 = [System.Security.Cryptography.SHA256]::Create()

try {
    $services = @(docker compose --project-directory $projectRoot -f $compose ps --status running --services)
    $requiredServices = @(
        "world-misskey", "world-gm",
        "black-misskey", "black-scheduler",
        "white-misskey", "white-scheduler"
    ) + @(
        1..10 | ForEach-Object { "black-agent{0:00}" -f $_ }
    ) + @(
        1..10 | ForEach-Object { "white-agent{0:00}" -f $_ }
    )
    $missingServices = @($requiredServices | Where-Object { $services -notcontains $_ })
    if ($missingServices.Count -gt 0) {
        throw "Required running services are missing: $($missingServices -join ', ')"
    }

    foreach ($instance in $instances) {
        $instanceRoot = Join-Path $projectRoot ("runtime\instances\{0}" -f $instance.Name)
        $manifestPath = Join-Path $instanceRoot "manifest.json"
        if (-not (Test-Path -LiteralPath $manifestPath)) {
            throw "Bootstrap manifest is missing: $manifestPath"
        }
        $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
        if ($manifest.faction -ne $instance.Faction) {
            throw "$($instance.Name) manifest faction is '$($manifest.faction)', expected '$($instance.Faction)'."
        }
        if ($manifest.species -ne "catfolk") {
            throw "$($instance.Name) manifest does not identify the inhabitants as catfolk."
        }
        $expectedCoat = switch ($instance.Name) {
            "black" { "黒猫族" }
            "white" { "白猫族" }
            default { "猫族" }
        }
        if ($manifest.coat -ne $expectedCoat) {
            throw "$($instance.Name) manifest coat is '$($manifest.coat)', expected '$expectedCoat'."
        }
        if ([int]$manifest.agentCount -ne $instance.ExpectedAgents) {
            throw "$($instance.Name) expected $($instance.ExpectedAgents) agents, found $($manifest.agentCount)."
        }

        $fullPremise = $premiseText + "`n`nこのサーバーの視点: $($instance.Faction)。これは担当や勝利条件ではなく、他の視点と異なる情報の境界です。"
        $premiseHash = ([BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($fullPremise)))).Replace("-", "").ToLowerInvariant()
        if ($manifest.worldPremise.name -ne "twin-moon-basin" -or $manifest.worldPremise.sha256 -ne $premiseHash) {
            throw "$($instance.Name) runtime manifest does not contain the current faction-scoped twin-moon-basin premise."
        }

        $meta = Invoke-RestMethod -Method Post -Uri "$($instance.Url)/api/meta" `
            -ContentType "application/json" -Body '{"detail":false}' -TimeoutSec 30
        if (-not $meta.version) {
            throw "$($instance.Name) Misskey meta endpoint did not return a version."
        }

        if ($instance.ExpectedAgents -eq 0) {
            continue
        }

        $agents = @($manifest.agents)
        if ($agents.Count -ne $instance.ExpectedAgents) {
            throw "$($instance.Name) manifest agent list has $($agents.Count) entries."
        }
        foreach ($index in 1..$instance.ExpectedAgents) {
            $service = "{0}-agent{1:00}" -f $instance.Name, $index
            $agentRoot = Join-Path $instanceRoot ("agents\agent{0:00}" -f $index)
            $jobsPath = Join-Path $agentRoot "cron\jobs.json"
            $jobs = @(Get-Content -Raw -LiteralPath $jobsPath | ConvertFrom-Json)
            if (@($jobs | Where-Object id -eq ("social-{0:00}" -f $index)).Count -gt 0) {
                throw "Legacy fixed-interval social job still exists for $service."
            }
            $worldPath = Join-Path $agentRoot "WORLD.md"
            $worldText = ((Get-Content -Raw -LiteralPath $worldPath) -replace "`r`n", "`n" -replace "`r", "`n").Trim()
            if ($worldText -ne $fullPremise) {
                throw "Faction-scoped world premise differs for $service."
            }
            $configPath = Join-Path $agentRoot "config.yaml"
            $configText = Get-Content -Raw -LiteralPath $configPath
            if (
                $configText -notmatch '(?m)^  memory_enabled: true\s*$' -or
                $configText -notmatch '(?m)^  nudge_interval: 10\s*$'
            ) {
                throw "Hermes memory review is not configured for every 10 turns in $service."
            }
            $socialSkillPath = Join-Path $agentRoot "skills\misskey-social\SKILL.md"
            if (
                -not (Test-Path -LiteralPath $socialSkillPath) -or
                (Get-Content -Raw -LiteralPath $socialSkillPath) -notmatch 'history --limit 40'
            ) {
                throw "40-note self-history review is not installed for $service."
            }
        }
    }

    foreach ($instance in $agentInstances) {
        $scheduler = "$($instance.Name)-scheduler"
        docker compose --project-directory $projectRoot -f $compose exec -T $scheduler `
            python /app/verify_runtime.py
        if ($LASTEXITCODE -ne 0) {
            throw "Hermes API or skill-distribution verification failed in $scheduler."
        }
    }

    $scheduleSummary = foreach ($instance in $agentInstances) {
        $schedulePath = Join-Path $projectRoot ("runtime\instances\{0}\scheduler\schedule.json" -f $instance.Name)
        if (-not (Test-Path -LiteralPath $schedulePath)) {
            throw "Scheduler state is missing: $schedulePath"
        }
        $state = Get-Content -Raw -LiteralPath $schedulePath | ConvertFrom-Json
        $entries = @($state.agents.PSObject.Properties | ForEach-Object Value)
        if ($entries.Count -ne $instance.ExpectedAgents) {
            throw "$($instance.Name) scheduler tracks $($entries.Count) agents, expected $($instance.ExpectedAgents)."
        }
        # A fresh stack has not executed every agent yet, so null is expected
        # until the first scheduled run records its interval.
        $intervals = @(
            $entries |
                Where-Object { $null -ne $_.lastIntervalMinutes } |
                ForEach-Object { [int]$_.lastIntervalMinutes }
        )
        if ($intervals.Count -gt 0 -and (($intervals | Measure-Object -Minimum).Minimum -lt 15 -or ($intervals | Measure-Object -Maximum).Maximum -gt 90)) {
            throw "$($instance.Name) scheduler interval is outside the configured 15-90 minute range."
        }
        "{0}: {1} agents scheduled" -f $instance.Name, $entries.Count
    }

    Write-Host "Verified Misskey $($instances[0].Name)/$($instances[1].Name)/$($instances[2].Name), 10 black + 10 white Hermes APIs, GM watcher, faction-scoped twin-moon-basin premise, memory review every 10 turns, 40-note self-history review, and 15-90 minute autonomous scheduling."
    $scheduleSummary | ForEach-Object { Write-Host $_ }
}
finally {
    $sha256.Dispose()
}
