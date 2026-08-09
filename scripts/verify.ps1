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
$competitionHeading = "## 競争ゲームの地平"
$mapContractPath = Join-Path $projectRoot "seed\scenarios\twin-moon-basin-map.md"
$mapSvgPath = Join-Path $projectRoot "assets\maps\twin-moon-basin-map.svg"
$mapPngPath = Join-Path $projectRoot "assets\maps\twin-moon-basin-map.png"
if (-not (Test-Path -LiteralPath $mapContractPath) -or -not (Test-Path -LiteralPath $mapSvgPath) -or -not (Test-Path -LiteralPath $mapPngPath)) {
    throw "World map contract or source assets are missing."
}
try {
    [xml](Get-Content -Raw -LiteralPath $mapSvgPath) | Out-Null
}
catch {
    throw "World map SVG is not valid XML: $mapSvgPath"
}
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
        if (
            $manifest.nyankoface.publicUrl -ne "https://madesk.tail8be30.ts.net" -or
            $manifest.nyankoface.githubRepository -ne "Sunwood-ai-labs/NyankoFace" -or
            $manifest.nyankoface.mode -ne "public-read-with-optional-agent-metrics"
        ) {
            throw "$($instance.Name) manifest does not contain the NyankoFace commons contract."
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
            if ($worldText -notmatch '暫定地図の扱い') {
                throw "World map guidance is missing for $service."
            }
            $soulPath = Join-Path $agentRoot "SOUL.md"
            $soulText = Get-Content -Raw -LiteralPath $soulPath
            if (
                $soulText -notmatch [regex]::Escape($competitionHeading) -or
                $soulText -notmatch '競争提案' -or
                $soulText -notmatch 'NyankoFace共有地'
            ) {
                throw "Autonomous competition guidance is missing for $service."
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
            $nyankoSkillPath = Join-Path $agentRoot "skills\nyankoface-commons\SKILL.md"
            $nyankoScriptPath = Join-Path $agentRoot "skills\nyankoface-commons\scripts\nyankoface.py"
            if (
                -not (Test-Path -LiteralPath $nyankoSkillPath) -or
                -not (Test-Path -LiteralPath $nyankoScriptPath) -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'NYANKOFACE_PUBLIC_URL' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'agent-view'
            ) {
                throw "NyankoFace commons skill is not installed for $service."
            }
            $agentEnvPath = Join-Path $agentRoot ".env"
            $agentEnvText = Get-Content -Raw -LiteralPath $agentEnvPath
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_PUBLIC_URL=') {
                throw "NyankoFace public URL is not configured for $service."
            }
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_AGENT_API_KEY_FILE=/opt/data/nyankoface-agent-api-key\s*$') {
                throw "Per-agent NyankoFace key path contract is missing for $service."
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

    $gmStatePath = Join-Path $projectRoot "runtime\instances\gm\events.json"
    if (-not (Test-Path -LiteralPath $gmStatePath)) {
        throw "GM state is missing: $gmStatePath"
    }
    $gmState = Get-Content -Raw -LiteralPath $gmStatePath | ConvertFrom-Json
    if ($gmState.competition.objective -ne "相手陣営を上回る文明を築く") {
        throw "GM competition objective is missing from runtime state."
    }
    $competitionAxes = @("military", "territory", "resources", "technology", "knowledge", "cohesion", "influence")
    foreach ($side in @("black", "white")) {
        foreach ($axis in $competitionAxes) {
            if ($null -eq $gmState.competition.score.$side.$axis) {
                throw "GM competition score axis '$axis' is missing for $side."
            }
        }
    }

    Write-Host "Verified Misskey $($instances[0].Name)/$($instances[1].Name)/$($instances[2].Name), 10 black + 10 white Hermes APIs, GM watcher, faction-scoped twin-moon-basin premise and RPG map contract, autonomous competition guidance and evidence board, memory review every 10 turns, 40-note self-history review, and 15-90 minute autonomous scheduling."
    $scheduleSummary | ForEach-Object { Write-Host $_ }
}
finally {
    $sha256.Dispose()
}
