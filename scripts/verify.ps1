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

$nyankofaceKeyValues = @()
$forgejoUsers = @()
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
            $manifest.nyankoface.mode -ne "forgejo-canonical-content-with-agent-metrics"
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
            $githubIssueHelperPath = Join-Path $agentRoot "skills\nyankoface-commons\scripts\github-issues.py"
            $navigatorSkillPath = Join-Path $agentRoot "skills\nyankoface-navigator\SKILL.md"
            if (
                -not (Test-Path -LiteralPath $nyankoSkillPath) -or
                -not (Test-Path -LiteralPath $nyankoScriptPath) -or
                -not (Test-Path -LiteralPath $githubIssueHelperPath) -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'NYANKOFACE_PUBLIC_URL' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'agent-view' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'artifact-contract' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'NYANKOFACE_FORGEJO_TOKEN_FILE' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'publish-file' -or
                 (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'set-topics' -or
                 (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'preflight --mode write' -or
                 (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'Read, contribute, verify, share' -or
                 (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'misskey_social\.py' -or
                 (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'repo --owner' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'file --owner' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'nyankoface\.py report' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'Sunwood-ai-labs/NyankoFace' -or
                (Get-Content -Raw -LiteralPath $nyankoSkillPath) -notmatch 'github-issues\.py' -or
                 -not (Test-Path -LiteralPath $navigatorSkillPath) -or
                 (Get-Content -Raw -LiteralPath $navigatorSkillPath) -notmatch 'Forgejo' -or
                 (Get-Content -Raw -LiteralPath $navigatorSkillPath) -notmatch 'preflight --mode write' -or
                 (Get-Content -Raw -LiteralPath $navigatorSkillPath) -notmatch 'search alone is not a contribution'
            ) {
                throw "NyankoFace commons skill is not installed for $service."
            }
            $agentEnvPath = Join-Path $agentRoot ".env"
            $agentEnvText = Get-Content -Raw -LiteralPath $agentEnvPath
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_PUBLIC_URL=') {
                throw "NyankoFace public URL is not configured for $service."
            }
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_FORGEJO_URL=https://madesk\.tail8be30\.ts\.net/git\s*$') {
                throw "NyankoFace Forgejo URL is not configured for $service."
            }
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_MCP_URL=https://madesk\.tail8be30\.ts\.net/mcp\s*$') {
                throw "NyankoFace MCP URL is not configured for $service."
            }
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_FORGEJO_TOKEN_FILE=/opt/data/nyankoface-forgejo-token\s*$') {
                throw "Per-agent Forgejo token path contract is missing for $service."
            }
            if ($agentEnvText -match '(?m)^NYANKOFACE_MCP_TOKEN_FILE=') {
                throw "Separate per-agent MCP token path must not be configured for $service."
            }
            if ($agentEnvText -notmatch '(?m)^NYANKOFACE_AGENT_API_KEY_FILE=/opt/data/nyankoface-agent-api-key\s*$') {
                throw "Per-agent NyankoFace key path contract is missing for $service."
            }
            $envKeyMatch = [regex]::Match($agentEnvText, '(?m)^NYANKOFACE_AGENT_API_KEY=(\S+)\s*$')
            if (-not $envKeyMatch.Success -or $envKeyMatch.Groups[1].Value -notmatch '^of_agent_[A-Za-z0-9_-]{20,}$') {
                throw "Per-agent NyankoFace API key is not present in the home .env for $service."
            }
            if ($agentEnvText -match '(?m)^(?:GITHUB_TOKEN|GH_TOKEN|GITHUB_PAT)=') {
                throw "GitHub PAT must not be copied into the home .env for $service."
            }
            $expectedSlug = "{0}-{1}" -f $instance.Name, $manifest.agents[$index - 1].username
            if ($agentEnvText -notmatch "(?m)^NYANKOFACE_AGENT_SLUG=$([regex]::Escape($expectedSlug))\s*$") {
                throw "Per-agent NyankoFace identity slug is missing for $service."
            }
            $expectedForgejoUser = "{0}-{1}" -f $instance.Name, $manifest.agents[$index - 1].username
            if ($agentEnvText -notmatch "(?m)^NYANKOFACE_FORGEJO_USER=$([regex]::Escape($expectedForgejoUser))\s*$") {
                throw "Per-agent Forgejo identity is missing for $service."
            }
            $keyPath = Join-Path $agentRoot "nyankoface-agent-api-key"
            if (-not (Test-Path -LiteralPath $keyPath) -or [string]::IsNullOrWhiteSpace((Get-Content -Raw -LiteralPath $keyPath))) {
                throw "Per-agent NyankoFace API key is not provisioned for $service."
            }
            $fileKey = (Get-Content -Raw -LiteralPath $keyPath).Trim()
            if ($fileKey -ne $envKeyMatch.Groups[1].Value) {
                throw "NyankoFace API key in .env does not match the protected key file for $service."
            }
            $forgejoTokenPath = Join-Path $agentRoot "nyankoface-forgejo-token"
            if (-not (Test-Path -LiteralPath $forgejoTokenPath) -or [string]::IsNullOrWhiteSpace((Get-Content -Raw -LiteralPath $forgejoTokenPath))) {
                throw "Per-agent Forgejo content token is not provisioned for $service."
            }
            try {
                $forgejoFileToken = (Get-Content -Raw -LiteralPath $forgejoTokenPath).Trim()
                $forgejoMe = Invoke-RestMethod -Method Get -Uri "https://madesk.tail8be30.ts.net/git/api/v1/user" `
                    -Headers @{ Authorization = "token $forgejoFileToken" } -TimeoutSec 30
            }
            catch {
                throw "Per-agent Forgejo content token is not accepted by the public NyankoFace Forgejo API for $service."
            }
            if ($forgejoMe.login -ne $expectedForgejoUser) {
                throw "Forgejo token identity does not match $expectedForgejoUser for $service."
            }
            $legacyMcpTokenPath = Join-Path $agentRoot "nyankoface-mcp-token"
            if (Test-Path -LiteralPath $legacyMcpTokenPath) {
                throw "Legacy separate NyankoFace MCP token file still exists for $service."
            }
            $nyankofaceKeyValues += $envKeyMatch.Groups[1].Value
            $forgejoUsers += $expectedForgejoUser
        }
    }
    if ($nyankofaceKeyValues.Count -ne 20 -or @($nyankofaceKeyValues | Sort-Object -Unique).Count -ne 20) {
        throw "Expected 20 distinct per-agent NyankoFace API keys in the agent home .env files."
    }
    if ($forgejoUsers.Count -ne 20 -or @($forgejoUsers | Sort-Object -Unique).Count -ne 20) {
        throw "Expected 20 distinct per-agent Forgejo identities."
    }
    $reportPublisher = Join-Path $projectRoot "scripts\publish-nyankoface-reports.ps1"
    if (-not (Test-Path -LiteralPath $reportPublisher)) {
        throw "NyankoFace report publisher is missing: $reportPublisher"
    }

    $agentServices = @(
        (1..10 | ForEach-Object { "black-agent{0:00}" -f $_ })
    ) + @(
        (1..10 | ForEach-Object { "white-agent{0:00}" -f $_ })
    )
    foreach ($service in $agentServices) {
        docker compose --project-directory $projectRoot -f $compose exec -T $service `
            python /opt/data/skills/nyankoface-commons/scripts/github-issues.py token-status | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub agent secret/helper is not available in $service."
        }
        $nyankofaceSourceJson = docker compose --project-directory $projectRoot -f $compose exec -T $service `
            python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py source
        if ($LASTEXITCODE -ne 0) {
            throw "NyankoFace agent key check failed in $service."
        }
        $nyankofaceSource = $nyankofaceSourceJson | ConvertFrom-Json
        if (-not $nyankofaceSource.character_agent_key_configured) {
            throw "Per-agent NyankoFace API key is not visible through the home .env in $service."
        }
        if (-not $nyankofaceSource.forgejo_user_configured -or -not $nyankofaceSource.forgejo_content_token_configured -or -not $nyankofaceSource.forgejo_token_configured) {
            throw "Per-agent NyankoFace Forgejo identity/token is not visible as the shared MCP credential in $service."
        }
        $nyankofacePreflightJson = docker compose --project-directory $projectRoot -f $compose exec -T $service `
            python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py preflight --mode write
        if ($LASTEXITCODE -ne 0) {
            throw "NyankoFace write preflight failed in $service."
        }
        $nyankofacePreflight = $nyankofacePreflightJson | ConvertFrom-Json
        if (-not $nyankofacePreflight.ok -or $nyankofacePreflight.errors.Count -ne 0) {
            throw "NyankoFace write preflight did not satisfy the local command contract in $service."
        }
    }
    foreach ($service in @("black-agent01", "white-agent01")) {
        $mcpCheckJson = docker compose --project-directory $projectRoot -f $compose exec -T $service `
            python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py mcp-check
        if ($LASTEXITCODE -ne 0) {
            throw "NyankoFace MCP live check failed in $service."
        }
        $mcpCheck = $mcpCheckJson | ConvertFrom-Json
        if (-not $mcpCheck.ok -or $mcpCheck.initialize.status -ne 200 -or $mcpCheck.tools_list.status -ne 200 -or $mcpCheck.resources_list.status -ne 200) {
            throw "NyankoFace MCP live check did not satisfy the protocol contract in $service."
        }
    }
    $repoCheckJson = docker compose --project-directory $projectRoot -f $compose exec -T black-agent01 `
        python /opt/data/skills/nyankoface-commons/scripts/github-issues.py repo-check
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub agent repository check failed in black-agent01."
    }
    $repoCheck = $repoCheckJson | ConvertFrom-Json
    if (-not $repoCheck.accessible -or -not $repoCheck.issues_enabled) {
        throw "GitHub agent token cannot access the configured NyankoFace Issue repository."
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

    Write-Host "Verified Misskey $($instances[0].Name)/$($instances[1].Name)/$($instances[2].Name), 10 black + 10 white Hermes APIs, GM watcher, faction-scoped twin-moon-basin premise and RPG map contract, autonomous competition guidance, NyankoFace Forgejo-canonical knowledge/app/Skill integration, one shared per-agent Forgejo credential for Forgejo and MCP, memory review every 10 turns, 40-note self-history review, and 15-90 minute autonomous scheduling."
    $scheduleSummary | ForEach-Object { Write-Host $_ }
}
finally {
    $sha256.Dispose()
}
