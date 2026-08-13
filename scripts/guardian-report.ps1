[CmdletBinding()]
param(
    [string]$ProjectRoot,

    [ValidateRange(1, 100)]
    [int]$Limit = 100,

    [switch]$NoWrite,

    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { Split-Path -Parent $PSScriptRoot }
}
$projectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$runtimeRoot = Join-Path $projectRoot "runtime"
$guardianRoot = Join-Path $runtimeRoot "guardian"
$reportsRoot = Join-Path $guardianRoot "reports"
$journalRoot = Join-Path $guardianRoot "journal"
$statePath = Join-Path $runtimeRoot "instances\gm\events.json"
$composePath = Join-Path $projectRoot "compose.yaml"

function Get-JstNow {
    # The report contract is JST even when a Windows host has a different
    # local timezone.  Keep the IANA fallback for PowerShell Core on Linux.
    $utcNow = [DateTimeOffset]::UtcNow
    foreach ($timeZoneId in @("Tokyo Standard Time", "Asia/Tokyo")) {
        try {
            $timeZone = [TimeZoneInfo]::FindSystemTimeZoneById($timeZoneId)
            return [TimeZoneInfo]::ConvertTime($utcNow, $timeZone)
        }
        catch {
            # Try the next platform-specific identifier.
        }
    }
    return $utcNow.ToOffset([TimeSpan]::FromHours(9))
}

$capturedAt = Get-JstNow
$reportId = $capturedAt.ToString("yyyyMMdd-HHmm")
$dayId = $capturedAt.ToString("yyyy-MM-dd")
$timeId = $capturedAt.ToString("HH:mm")

function ConvertTo-SafeText {
    param(
        [AllowNull()][object]$Value,
        [int]$MaxLength = 600
    )

    if ($null -eq $Value) {
        return ""
    }
    $text = [string]$Value
    $text = [regex]::Replace(
        $text,
        '(?ix)(\b(?:api[_-]?key|password|access[_-]?token|token|credential|authorization|secret|private[_-]?key)\s*[:=]\s*)\S+',
        '${1}[redacted]'
    )
    $text = [regex]::Replace($text, '(?ix)\bbearer\s+[A-Za-z0-9._-]{12,}', 'Bearer [redacted]')
    $text = [regex]::Replace($text, '(?ix)\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]{12,}', '[redacted-token]')
    $text = [regex]::Replace($text, '(?ix)https?://[^\s/@:]+:[^\s/@]+@', 'https://[redacted]@')
    $text = [regex]::Replace($text, '(?ix)flag\{[^}\r\n]{1,200}\}', 'flag{[redacted]}')
    $text = [regex]::Replace($text, '\s+', ' ').Trim()
    if ($text.Length -gt $MaxLength) {
        return $text.Substring(0, $MaxLength) + "…"
    }
    return $text
}

function ConvertTo-MarkdownCell {
    param([AllowNull()][object]$Value)
    return (ConvertTo-SafeText $Value 500).Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ')
}

function Write-AtomicText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.tmp.$PID"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporary, $Text, $utf8NoBom)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-TimelineReport {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl
    )

    $scriptPath = Join-Path $projectRoot "scripts\timeline-report.ps1"
    try {
        # timeline-report.ps1 is a PowerShell child script and does not own
        # $LASTEXITCODE. Reset the inherited native-command status before
        # invoking it so a preceding docker inspect cannot look like a
        # timeline failure.
        $LASTEXITCODE = 0
        $output = & $scriptPath -BaseUrl $BaseUrl -Limit $Limit -AsJson 2>&1
        $timelineExitCode = $LASTEXITCODE
        if ($timelineExitCode -ne 0) {
            throw "timeline-report.ps1 exited with code $timelineExitCode"
        }
        $json = ($output | ForEach-Object { [string]$_ }) -join "`n"
        $value = $json | ConvertFrom-Json
        return [pscustomobject]@{
            ok = $true
            baseUrl = $BaseUrl
            capturedAt = [string]$value.capturedAt
            sample = [int]$value.sample
            originalNotes = [int]$value.originalNotes
            replies = [int]$value.replies
            renotes = [int]$value.renotes
            quotes = [int]$value.quotes
            reactedNotes = [int]$value.reactedNotes
            totalReactions = [int]($value.totalReactions | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
            uniqueEmoji = [int]$value.uniqueEmoji
            authors = @($value.authors).Count
        }
    }
    catch {
        return [pscustomobject]@{
            ok = $false
            baseUrl = $BaseUrl
            error = ConvertTo-SafeText $_.Exception.Message 300
        }
    }
}

function Get-RunningServices {
    $required = @(
        "world-misskey", "world-gm", "world-db", "world-redis",
        "black-misskey", "black-scheduler", "black-db", "black-redis",
        "white-misskey", "white-scheduler", "white-db", "white-redis"
    )
    $required += 1..10 | ForEach-Object { "black-agent{0:00}" -f $_ }
    $required += 1..10 | ForEach-Object { "white-agent{0:00}" -f $_ }

    try {
        $output = docker compose --project-directory $projectRoot -f $composePath ps --status running --services 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose ps exited with code $LASTEXITCODE"
        }
        $running = @(
            $output |
                ForEach-Object { [string]$_ } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                ForEach-Object { $_.Trim() }
        )
        return [pscustomobject]@{
            ok = $true
            runningCount = $running.Count
            runningServices = $running
            requiredCount = $required.Count
            missingServices = @($required | Where-Object { $running -notcontains $_ })
        }
    }
    catch {
        return [pscustomobject]@{
            ok = $false
            runningCount = 0
            runningServices = @()
            requiredCount = $required.Count
            missingServices = $required
            error = ConvertTo-SafeText $_.Exception.Message 300
        }
    }
}

function Get-RecentLogSummary {
    try {
        $output = docker compose --project-directory $projectRoot -f $composePath logs --timestamps --since 2h --tail 200 world-gm black-scheduler white-scheduler 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose logs exited with code $LASTEXITCODE"
        }
        $lines = @($output | ForEach-Object { [string]$_ })
        $gmStartedAt = $null
        try {
            $containerId = @(
                docker compose --project-directory $projectRoot -f $composePath ps -q world-gm 2>&1 |
                    ForEach-Object { [string]$_ } |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                    Select-Object -First 1
            )
            if ($containerId.Count -gt 0) {
                $startedText = @(
                    docker inspect --format '{{.State.StartedAt}}' $containerId[0] 2>&1 |
                        ForEach-Object { [string]$_ } |
                        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                        Select-Object -First 1
                )
                if ($startedText.Count -gt 0) {
                    $gmStartedAt = [DateTimeOffset]::Parse($startedText[0])
                }
            }
        }
        catch {
            # Log classification remains conservative when Docker does not
            # provide a parseable start time: the line stays actionable.
        }
        $transientLines = @(
            $lines | Where-Object {
                if ($_ -notmatch '(?i)world-gm.*poll failed:.*Connection refused') {
                    return $false
                }
                if ($null -eq $gmStartedAt) {
                    return $false
                }
                $timestampMatch = [regex]::Match($_, '(?<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z')
                if (-not $timestampMatch.Success) {
                    return $false
                }
                try {
                    $timestampText = $timestampMatch.Groups['stamp'].Value + 'Z'
                    $logTime = [DateTimeOffset]::Parse($timestampText)
                    $age = $logTime - $gmStartedAt
                    return $age.TotalSeconds -ge 0 -and $age.TotalSeconds -le 120
                }
                catch {
                    return $false
                }
            }
        )
        $errorLines = @(
            $lines | Where-Object {
                # Compose timestamps contain several ':' characters before
                # the service payload.  Match the payload words directly so
                # `service | 2026-... agent: failed: ...` is not missed.
                ($_ -match '(?i)\b(?:ERROR|FATAL|Traceback|panic|unhealthy|restart loop|TimeoutError|RemoteDisconnected)\b|error=|\b(?:failed|timed out)\b') -and
                    ($transientLines -notcontains $_)
            }
        )
        $warningLines = @(
            $lines | Where-Object { $_ -match '(?i)\b(?:WARN|warning|unmatched_|stale_)\b' }
        )
        return [pscustomobject]@{
            ok = $true
            window = "2h"
            lines = $lines.Count
            errorLines = $errorLines.Count
            warningLines = $warningLines.Count
            transientLines = $transientLines.Count
            # Keep enough bounded evidence for the hourly GM to distinguish a
            # real service failure from a harmless message without dumping the
            # complete Docker log into the report or Codex context.
            errorSamples = @($errorLines | Select-Object -First 8 | ForEach-Object { ConvertTo-SafeText $_ 900 })
            warningSamples = @($warningLines | Select-Object -First 8 | ForEach-Object { ConvertTo-SafeText $_ 900 })
            transientSamples = @($transientLines | Select-Object -First 8 | ForEach-Object { ConvertTo-SafeText $_ 900 })
        }
    }
    catch {
        return [pscustomobject]@{
            ok = $false
            window = "2h"
            lines = 0
            errorLines = 0
            warningLines = 0
            transientLines = 0
            errorSamples = @()
            warningSamples = @()
            transientSamples = @()
            error = ConvertTo-SafeText $_.Exception.Message 300
        }
    }
}

function Get-SchedulerSummary {
    $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $summaries = [ordered]@{}
    foreach ($instance in @("black", "white")) {
        $path = Join-Path $runtimeRoot ("instances\{0}\scheduler\schedule.json" -f $instance)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $summaries[$instance] = [pscustomobject]@{
                ok = $false
                healthy = $false
                instance = $instance
                statePath = $path
                agents = 0
                expectedAgents = 10
                recentFailureCount = 0
                rateLimitedCount = 0
                providerBackoffCount = 0
                providerCooldownActive = $false
                providerCooldownUntil = 0
                providerCooldownUntilIso = $null
                statusCounts = @{}
                failureSamples = @()
                error = "scheduler state file is missing"
            }
            continue
        }

        try {
            $state = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
            $agentProperties = @($state.agents.PSObject.Properties)
            $rows = @(
                $agentProperties | ForEach-Object {
                    $entry = $_.Value
                    $lastAt = 0.0
                    try { $lastAt = [double]($entry.lastAt) } catch { $lastAt = 0.0 }
                    [pscustomobject]@{
                        agent = [string]$_.Name
                        status = [string]$entry.lastStatus
                        lastAt = $lastAt
                        lastError = [string]$entry.lastError
                    }
                }
            )
            $recentFailures = @(
                $rows | Where-Object {
                    $_.lastAt -gt 0 -and
                    ($nowEpoch - $_.lastAt) -le 7200 -and
                    $_.status -in @("error", "rate_limited", "provider_backoff")
                } | Sort-Object lastAt -Descending
            )
            $rateLimited = @($recentFailures | Where-Object status -eq "rate_limited")
            $providerBackoff = @($recentFailures | Where-Object status -eq "provider_backoff")
            $cooldownUntil = 0.0
            try { $cooldownUntil = [double]($state.providerCooldownUntil) } catch { $cooldownUntil = 0.0 }
            $statusCounts = [ordered]@{}
            foreach ($group in @($rows | Group-Object status)) {
                $statusCounts[[string]$group.Name] = [int]$group.Count
            }
            $healthy = $agentProperties.Count -eq 10 -and $recentFailures.Count -eq 0 -and $cooldownUntil -le $nowEpoch
            $summaries[$instance] = [pscustomobject]@{
                ok = $true
                healthy = $healthy
                instance = $instance
                statePath = $path
                agents = $agentProperties.Count
                expectedAgents = 10
                recentFailureCount = $recentFailures.Count
                rateLimitedCount = $rateLimited.Count
                providerBackoffCount = $providerBackoff.Count
                providerCooldownActive = ($cooldownUntil -gt $nowEpoch)
                providerCooldownUntil = $cooldownUntil
                providerCooldownUntilIso = [string]$state.providerCooldownUntilIso
                statusCounts = $statusCounts
                failureSamples = @(
                    $recentFailures | Select-Object -First 8 | ForEach-Object {
                        $message = ConvertTo-SafeText $_.lastError 500
                        "@$($_.agent) [$($_.status)] lastAt=$($_.lastAt): $message"
                    }
                )
            }
        }
        catch {
            $summaries[$instance] = [pscustomobject]@{
                ok = $false
                healthy = $false
                instance = $instance
                statePath = $path
                agents = 0
                expectedAgents = 10
                recentFailureCount = 0
                rateLimitedCount = 0
                providerBackoffCount = 0
                providerCooldownActive = $false
                providerCooldownUntil = 0
                providerCooldownUntilIso = $null
                statusCounts = @{}
                failureSamples = @()
                error = ConvertTo-SafeText $_.Exception.Message 300
            }
        }
    }
    return $summaries
}

function Get-AuditEvents {
    param([Parameter(Mandatory = $true)][object]$State)

    # GM keeps the legacy scene/competition audit stream at the top level and
    # the season-specific streams under ctf/dctf.  Delivery checks must use
    # all of them, including archived DCTF seasons; otherwise a correctly
    # handled pre-migration request is reported as "seen/no-audit" even though
    # events.json contains its audit event in dctfArchive.
    $events = @($State.events)
    if ($null -ne $State.ctf) {
        $events += @($State.ctf.events)
    }
    if ($null -ne $State.dctf) {
        $events += @($State.dctf.events)
    }
    foreach ($archive in @($State.dctfArchive)) {
        if ($null -ne $archive) {
            $events += @($archive.events)
        }
    }
    return @($events | Where-Object { $null -ne $_ })
}

function Read-GmState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject]@{
            ok = $false
            path = $statePath
            error = "events.json is missing"
        }
    }

    try {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        $scene = $state.currentScene
        $activeBattles = @(
            @($state.battles) | Where-Object { [string]$_.status -in @("challenge", "engaged", "awaiting_result") }
        )
        $auditEvents = @(Get-AuditEvents $state)
        $recentEvents = @(
            $auditEvents |
                Sort-Object { [string]$_.at } |
                Select-Object -Last 200
        )
        $unmatchedEvents = @(
            $recentEvents | Where-Object { [string]$_.event -match '^(unmatched|stale)_' }
        )
        $sceneSummary = $null
        if ($null -ne $scene) {
            $sceneSummary = [pscustomobject]@{
                id = [string]$scene.id
                phase = [string]$scene.phase
                kind = [string]$scene.kind
                location = [string]$scene.location
                title = ConvertTo-SafeText $scene.title 160
                round = [int]($scene.round | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                blackActions = @($scene.actions.black).Count
                whiteActions = @($scene.actions.white).Count
                actionDeadline = $scene.actionDeadline
            }
        }
        return [pscustomobject]@{
            ok = $true
            path = $statePath
            version = [int]$state.version
            seenNotes = @($state.seen).Count
            eventCount = $auditEvents.Count
            sceneCount = @($state.scenes).Count
            battleCount = @($state.battles).Count
            activeBattles = $activeBattles.Count
            unmatchedEvents = $unmatchedEvents.Count
            currentScene = $sceneSummary
            competition = [pscustomobject]@{
                charterVersion = [int]$state.competition.charterVersion
                proposals = @($state.competition.proposals).Count
                evidence = @($state.competition.evidence).Count
                score = $state.competition.score
            }
            dctf = if ($null -ne $state.dctf) {
                [pscustomobject]@{
                    seasonId = [string]$state.dctf.seasonId
                    status = [string]$state.dctf.status
                    problems = @($state.dctf.problems).Count
                    openProblems = @($state.dctf.problems | Where-Object { [string]$_.status -eq "open" }).Count
                    solvedProblems = @($state.dctf.problems | Where-Object { [string]$_.status -eq "solved" }).Count
                    submissions = @($state.dctf.submissions).Count
                    score = $state.dctf.score
                }
            } else { $null }
            dctfArchive = @(
                $state.dctfArchive |
                    ForEach-Object {
                        [pscustomobject]@{
                            seasonId = [string]$_.seasonId
                            status = [string]$_.status
                            problems = @($_.problems).Count
                            submissions = @($_.submissions).Count
                            events = @($_.events).Count
                            score = $_.score
                        }
                    }
            )
            state = $state
        }
    }
    catch {
        return [pscustomobject]@{
            ok = $false
            path = $statePath
            error = ConvertTo-SafeText $_.Exception.Message 300
        }
    }
}

function Get-RequestKind {
    param([string]$Text)
    if ($Text -match '競争提案|競争異議') { return "competition" }
    if ($Text -match '戦果報告|結果報告|戦闘結果|交戦結果') { return "result" }
    if ($Text -match '行動宣言|戦闘行動') { return "action" }
    if ($Text -match '戦闘申告|戦闘応答') { return "battle" }
    if ($Text -match '外交|交易|交換|停戦|交渉|和平') { return "diplomacy" }
    return "other"
}

function Get-GmReplyEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$NoteId
    )

    try {
        $body = @{ noteId = $NoteId; limit = 30 } | ConvertTo-Json -Compress
        $children = Invoke-RestMethod -Method Post -Uri ("{0}/api/notes/children" -f $BaseUrl.TrimEnd('/')) `
            -ContentType "application/json" -Body $body -TimeoutSec 30
        $replies = @(
            @($children) | Where-Object { [string]$_.user.username -eq "gm" }
        )
        return [pscustomobject]@{
            checked = $true
            ok = $true
            count = $replies.Count
            ids = @($replies | ForEach-Object { [string]$_.id })
        }
    }
    catch {
        return [pscustomobject]@{
            checked = $true
            ok = $false
            count = 0
            ids = @()
            error = ConvertTo-SafeText $_.Exception.Message 300
        }
    }
}

function Get-LocalGmNotes {
    param(
        [Parameter(Mandatory = $true)][string]$Instance,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][object]$State
    )

    $credentialPath = Join-Path $runtimeRoot ("instances\{0}\gm-credentials.json" -f $Instance)
    if (-not (Test-Path -LiteralPath $credentialPath -PathType Leaf)) {
        return [pscustomobject]@{ ok = $false; instance = $Instance; error = "GM credentials file is missing"; notes = @() }
    }

    try {
        $credential = Get-Content -Raw -LiteralPath $credentialPath | ConvertFrom-Json
        $body = @{ i = [string]$credential.token; limit = $Limit } | ConvertTo-Json -Compress
        $notes = Invoke-RestMethod -Method Post -Uri ("{0}/api/notes/local-timeline" -f $BaseUrl.TrimEnd('/')) `
            -ContentType "application/json" -Body $body -TimeoutSec 30
        $seen = @{}
        foreach ($id in @($State.seen)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$id)) { $seen[[string]$id] = $true }
        }
        $events = @(Get-AuditEvents $State)
        $requests = @(
            @($notes) |
                Where-Object { ([string]$_.text -match '(?i)@gm') -and ([string]$_.user.username -ne "gm") } |
                Sort-Object createdAt -Descending |
                # Keep the request audit aligned with the requested timeline
                # window.  A hard-coded 30 could silently omit @gm requests
                # when the latest Limit-sized sample contains more requests.
                Select-Object -First $Limit |
                ForEach-Object {
                    $noteId = [string]$_.id
                    $text = [string]$_.text
                    $noteEvents = @($events | Where-Object { [string]$_.noteId -eq $noteId })
                    $eventNames = @($noteEvents | ForEach-Object { [string]$_.event } | Where-Object { $_ })
                    $delivery = if (-not $seen.ContainsKey($noteId)) {
                        "unseen"
                    }
                     elseif ($eventNames.Count -gt 0) {
                         "handled"
                     }
                     else {
                         "seen/no-audit"
                     }
                    $replyEvidence = [pscustomobject]@{
                        checked = $false
                        ok = $null
                        count = 0
                        ids = @()
                    }
                    if ($delivery -eq "seen/no-audit") {
                        $replyEvidence = Get-GmReplyEvidence $BaseUrl $noteId
                        if ($replyEvidence.ok -and $replyEvidence.count -gt 0) {
                            $delivery = "handled"
                        }
                    }
                    [pscustomobject]@{
                        id = $noteId
                        createdAt = [string]$_.createdAt
                        username = [string]$_.user.username
                        kind = Get-RequestKind $text
                        delivery = $delivery
                        events = $eventNames
                        replyEvidence = $replyEvidence
                        text = ConvertTo-SafeText $text 700
                    }
                }
        )
        return [pscustomobject]@{
            ok = $true
            instance = $Instance
            sampledNotes = @($notes).Count
            requestCount = $requests.Count
            unseenRequests = @($requests | Where-Object delivery -eq "unseen").Count
            noAuditRequests = @($requests | Where-Object delivery -eq "seen/no-audit").Count
            handledRequests = @($requests | Where-Object delivery -eq "handled").Count
            requests = $requests
        }
    }
    catch {
        return [pscustomobject]@{
            ok = $false
            instance = $Instance
            sampledNotes = 0
            requestCount = 0
            unseenRequests = 0
            noAuditRequests = 0
            handledRequests = 0
            requests = @()
            error = ConvertTo-SafeText $_.Exception.Message 300
        }
    }
}

function Get-AgentRuntimeFiles {
    param([Parameter(Mandatory = $true)][string]$Name)

    # The agent directory is the contract boundary.  Do not recurse through
    # each Hermes home: those trees contain caches, sessions, skills, and
    # backups that are intentionally outside the Guardian observation scope.
    $files = @()
    foreach ($instance in @("black", "white")) {
        $agentRoot = Join-Path $runtimeRoot ("instances\{0}\agents" -f $instance)
        if (-not (Test-Path -LiteralPath $agentRoot -PathType Container)) {
            continue
        }
        $agentDirs = @(Get-ChildItem -LiteralPath $agentRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name)
        foreach ($agentDir in $agentDirs) {
            $candidate = Join-Path $agentDir.FullName $Name
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $files += Get-Item -LiteralPath $candidate
            }
        }
    }
    return $files
}

function Get-SoulSummary {
    $files = @(Get-AgentRuntimeFiles "SOUL.md")
    $invalid = @()
    foreach ($file in $files) {
        $text = Get-Content -Raw -LiteralPath $file.FullName
        $matches = [regex]::Matches($text, '(?ms)^## 自律の視野\s*\r?\n.*?(?=^## |\z)')
        if ($matches.Count -ne 1) {
            $invalid += $file.FullName
        }
    }
    return [pscustomobject]@{
        files = $files.Count
        expectedFiles = 20
        boundedSectionValid = ($files.Count -eq 20 -and $invalid.Count -eq 0)
        invalidFiles = $invalid
    }
}

function Get-WorldSummary {
    $files = @(Get-AgentRuntimeFiles "WORLD.md")
    $invalid = @()
    foreach ($file in $files) {
        try {
            if ([string]::IsNullOrWhiteSpace((Get-Content -Raw -LiteralPath $file.FullName))) {
                $invalid += $file.FullName
            }
        }
        catch {
            $invalid += $file.FullName
        }
    }
    return [pscustomobject]@{
        files = $files.Count
        expectedFiles = 20
        nonEmpty = $files.Count - $invalid.Count
        valid = ($files.Count -eq 20 -and $invalid.Count -eq 0)
        invalidFiles = $invalid
    }
}

function Get-NyankofaceSummary {
    $root = Join-Path $runtimeRoot "nyankoface-outbox\reports"
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        return [pscustomobject]@{ present = $false; total = 0; pending = 0; published = 0; duplicate = 0; other = 0 }
    }
    $metadataFiles = @(Get-ChildItem -LiteralPath $root -Recurse -Filter "report.json" -File -ErrorAction SilentlyContinue)
    $records = foreach ($file in $metadataFiles) {
        try { Get-Content -Raw -LiteralPath $file.FullName | ConvertFrom-Json } catch { $null }
    }
    return [pscustomobject]@{
        present = $true
        total = @($records).Count
        pending = @($records | Where-Object { [string]$_.status -eq "pending" }).Count
        published = @($records | Where-Object { [string]$_.status -eq "published" }).Count
        duplicate = @($records | Where-Object { [string]$_.status -eq "duplicate" }).Count
        other = @($records | Where-Object { [string]$_.status -notin @("pending", "published", "duplicate") }).Count
        publishedUrls = @($records | Where-Object { $_.issue_url } | ForEach-Object { [string]$_.issue_url } | Select-Object -Last 10)
    }
}

function Format-TimelineLine {
    param([object]$Summary, [string]$Label)
    if (-not $Summary.ok) {
        return "- ${Label}: unhealthy（$([string]$Summary.error)）"
    }
    return "- ${Label}: sample=$($Summary.sample), original=$($Summary.originalNotes), replies=$($Summary.replies), renotes=$($Summary.renotes), quotes=$($Summary.quotes), reacted=$($Summary.reactedNotes), reactions=$($Summary.totalReactions), authors=$($Summary.authors)"
}

function Format-RequestLines {
    param([object]$Summary)
    if (-not $Summary.ok) {
        return @("- $($Summary.instance): 取得失敗（$([string]$Summary.error)）")
    }
    $lines = @(
        "- $($Summary.instance): sampled=$($Summary.sampledNotes), @gm=$($Summary.requestCount), handled=$($Summary.handledRequests), unseen=$($Summary.unseenRequests), no-audit=$($Summary.noAuditRequests)"
    )
    foreach ($request in @($Summary.requests | Select-Object -First 8)) {
        $lines += "  - $($request.createdAt) @$($request.username) [$($request.kind)/$($request.delivery)] $([string](ConvertTo-MarkdownCell $request.text))"
    }
    return $lines
}

$services = Get-RunningServices
$logs = Get-RecentLogSummary
$scheduler = Get-SchedulerSummary
$stateSummary = Read-GmState
$stateForNotes = if ($stateSummary.ok) { $stateSummary.state } else { [pscustomobject]@{ seen = @(); events = @() } }
$timelines = [ordered]@{
    world = Invoke-TimelineReport "http://127.0.0.1:3310"
    black = Invoke-TimelineReport "http://127.0.0.1:3311"
    white = Invoke-TimelineReport "http://127.0.0.1:3312"
}
$requests = [ordered]@{
    black = Get-LocalGmNotes "black" "http://127.0.0.1:3311" $stateForNotes
    white = Get-LocalGmNotes "white" "http://127.0.0.1:3312" $stateForNotes
}
$soul = Get-SoulSummary
$world = Get-WorldSummary
$nyankoface = Get-NyankofaceSummary

$endpointFailures = @($timelines.Values | Where-Object { -not $_.ok }).Count + @($requests.Values | Where-Object { -not $_.ok }).Count
$schedulerHealthy = @($scheduler.Values | Where-Object { -not $_.healthy }).Count -eq 0
$healthy = $services.ok -and @($services.missingServices).Count -eq 0 -and $stateSummary.ok -and $logs.ok -and $logs.errorLines -eq 0 -and $schedulerHealthy -and $endpointFailures -eq 0 -and $soul.boundedSectionValid -and $world.valid -and @($requests.Values | Where-Object { $_.unseenRequests -gt 0 -or $_.noAuditRequests -gt 0 }).Count -eq 0
$health = if ($healthy) { "healthy" } else { "unhealthy" }
$attention = 0
foreach ($requestSummary in @($requests.Values)) {
    $attention += [int]$requestSummary.unseenRequests + [int]$requestSummary.noAuditRequests
}

$snapshot = [pscustomobject]@{
    reportId = $reportId
    capturedAt = $capturedAt.ToString("yyyy-MM-dd HH:mm:ss zzz")
    timezone = "Asia/Tokyo"
    health = $health
    services = $services
    logs = $logs
    scheduler = $scheduler
    gm = [pscustomobject]@{
        statePath = $statePath
        ok = $stateSummary.ok
        seenNotes = if ($stateSummary.ok) { $stateSummary.seenNotes } else { 0 }
        eventCount = if ($stateSummary.ok) { $stateSummary.eventCount } else { 0 }
        sceneCount = if ($stateSummary.ok) { $stateSummary.sceneCount } else { 0 }
        battleCount = if ($stateSummary.ok) { $stateSummary.battleCount } else { 0 }
        activeBattles = if ($stateSummary.ok) { $stateSummary.activeBattles } else { 0 }
        unmatchedEvents = if ($stateSummary.ok) { $stateSummary.unmatchedEvents } else { 0 }
        currentScene = if ($stateSummary.ok) { $stateSummary.currentScene } else { $null }
        competition = if ($stateSummary.ok) { $stateSummary.competition } else { $null }
        dctf = if ($stateSummary.ok) { $stateSummary.dctf } else { $null }
        dctfArchive = if ($stateSummary.ok) { $stateSummary.dctfArchive } else { @() }
    }
    timelines = $timelines
    requests = $requests
    soul = $soul
    world = $world
    nyankoface = $nyankoface
    attentionCount = [int]$attention
}

$sceneText = if ($snapshot.gm.currentScene) {
    "$($snapshot.gm.currentScene.id) / $($snapshot.gm.currentScene.phase) / $($snapshot.gm.currentScene.location) / round $($snapshot.gm.currentScene.round)"
}
else { "なし" }
$missingText = if (@($services.missingServices).Count -gt 0) { @($services.missingServices) -join ", " } else { "なし" }
$unresolvedText = if ($snapshot.gm.unmatchedEvents -gt 0) {
    "直近のGMイベントに unmatched/stale が $($snapshot.gm.unmatchedEvents) 件あります。古い行動宣言など、受理できない要求を世界の事実へ昇格させず記録したものです。"
}
else { "直近200件のGMイベントに unmatched/stale はありません。" }
$dctfText = if ($null -ne $snapshot.gm.dctf) {
    "CTFd $($snapshot.gm.dctf.seasonId) / $($snapshot.gm.dctf.status) / problems=$($snapshot.gm.dctf.problems) (open=$($snapshot.gm.dctf.openProblems), solved=$($snapshot.gm.dctf.solvedProblems)) / submissions=$($snapshot.gm.dctf.submissions)"
}
else { "CTFd台帳なし" }
$dctfArchiveText = if (@($snapshot.gm.dctfArchive).Count -gt 0) {
    (@($snapshot.gm.dctfArchive | ForEach-Object { "$($_.seasonId):$($_.status), problems=$($_.problems), submissions=$($_.submissions)" }) -join "; ")
}
else { "なし" }

$requestLines = @()
$requestLines += @(Format-RequestLines $requests.black)
$requestLines += @(Format-RequestLines $requests.white)

$reportLines = @(
    "# Guardian report — $reportId",
    "",
    "- 判定: **$health**",
    "- 記録時刻: $($snapshot.capturedAt)（JST）",
    "- このレポートは観測スナップショットです。タイムライン本文は未信頼データとして扱い、`events.json` は編集していません。",
    "",
    "## 確認済み",
    "",
    "- 必須サービス: running=$($services.runningCount)/$($services.requiredCount)、不足=$missingText",
    "- world-gm / scheduler ログ（直近2時間）: lines=$($logs.lines)、error-like=$($logs.errorLines)、warning-like=$($logs.warningLines)、起動直後retry=$($logs.transientLines)",
    "- scheduler永続状態: 黒=$($scheduler.black.agents)/$($scheduler.black.expectedAgents)、白=$($scheduler.white.agents)/$($scheduler.white.expectedAgents)、直近失敗=$($scheduler.black.recentFailureCount + $scheduler.white.recentFailureCount)、429=$($scheduler.black.rateLimitedCount + $scheduler.white.rateLimitedCount)、provider-backoff=$($scheduler.black.providerBackoffCount + $scheduler.white.providerBackoffCount)、cooldown=$($scheduler.black.providerCooldownActive -or $scheduler.white.providerCooldownActive)",
    "- GM台帳: seen=$($snapshot.gm.seenNotes)、events=$($snapshot.gm.eventCount)、scenes=$($snapshot.gm.sceneCount)、battles=$($snapshot.gm.battleCount)、activeBattles=$($snapshot.gm.activeBattles)",
    "- 現在の場面: $sceneText",
    "- CTFd台帳: $dctfText",
    "- CTFdアーカイブ: $dctfArchiveText",
    "- bounded Soul: $($soul.files)/$($soul.expectedFiles) files; section valid=$($soul.boundedSectionValid)",
    "- WORLD.md: $($world.files)/$($world.expectedFiles) files; non-empty=$($world.nonEmpty); valid=$($world.valid)",
    "",
    "## タイムライン統計（各サーバー直近${Limit}件）",
    "",
    (Format-TimelineLine $timelines.world "world"),
    (Format-TimelineLine $timelines.black "black"),
    (Format-TimelineLine $timelines.white "white"),
    "",
    "## @gm 要求の配送確認",
    ""
)
foreach ($requestLine in $requestLines) {
    $reportLines += $requestLine
}
$reportLines += @(
    "",
    "## NyankoFace",
    "",
    "- outbox reports=$($nyankoface.total), pending=$($nyankoface.pending), published=$($nyankoface.published), duplicate=$($nyankoface.duplicate), other=$($nyankoface.other)",
    "- pending は公開済みと見なさず、資格情報やIssue本文をこのレポートへ出していません。",
    "",
    "## ログ証拠（bounded）",
    "",
    "- error-like samples: $(@($logs.errorSamples).Count)、warning-like samples: $(@($logs.warningSamples).Count)、startup retry samples: $(@($logs.transientSamples).Count)"
)
foreach ($sample in @($logs.errorSamples | Select-Object -First 5)) {
    $reportLines += "  - error: $sample"
}
foreach ($sample in @($logs.warningSamples | Select-Object -First 5)) {
    $reportLines += "  - warning: $sample"
}
foreach ($sample in @($logs.transientSamples | Select-Object -First 5)) {
    $reportLines += "  - transient: $sample"
}
$reportLines += @(
    "",
    "## Scheduler永続状態（直近2時間）",
    "",
    "- black: agents=$($scheduler.black.agents)/$($scheduler.black.expectedAgents), recent-failures=$($scheduler.black.recentFailureCount), rate-limited=$($scheduler.black.rateLimitedCount), provider-backoff=$($scheduler.black.providerBackoffCount), cooldown=$($scheduler.black.providerCooldownActive)",
    "- white: agents=$($scheduler.white.agents)/$($scheduler.white.expectedAgents), recent-failures=$($scheduler.white.recentFailureCount), rate-limited=$($scheduler.white.rateLimitedCount), provider-backoff=$($scheduler.white.providerBackoffCount), cooldown=$($scheduler.white.providerCooldownActive)"
)
foreach ($instance in @("black", "white")) {
    foreach ($sample in @($scheduler[$instance].failureSamples | Select-Object -First 5)) {
        $reportLines += "  - $instance`: $sample"
    }
}
$reportLines += @(
    "",
    "## 判定と未解決",
    "",
    "- インフラ判定: **$health**。サービス・API・GM台帳・scheduler永続状態・bounded Soul構造を確認しました。",
    "- GMプロトコルの注意: $unresolvedText",
    "- 次回確認: $([int]$attention) 件の配送注意、直近の新しい場面、観察が再現可能な手順や共同利用へ進んだか、NyankoFace の pending 状態。",
    "",
    "_Generated by `scripts/guardian-report.ps1`; no credentials are included._"
)
$reportText = ($reportLines -join "`n") + "`n"

$journalMarker = "<!-- guardian-report-id: $reportId -->"
$journalLines = @(
    $journalMarker,
    "## $timeId JST — $health",
    "",
    "確認できた範囲では、必須サービスは $($services.runningCount)/$($services.requiredCount) 件が稼働し、GMの現在場面は $sceneText だった。黒猫・白猫の直近タイムラインはそれぞれ $($timelines.black.sample) 件、$($timelines.white.sample) 件を取得できた。",
    "",
    "解釈として、GMは未確定の要求を台帳へ無理に昇格させず、古い行動宣言を配送注意として残している。これは世界の事実を捏造しないための境界として機能しているが、次回は新しい受付と場面の切替を確認する。",
    "",
    "未解決なのは、観察と返信が再現可能な手順・共同利用できる成果へどこまで接続したか、そして NyankoFace の pending 報告が残っていないかである。"
)
$journalEntry = ($journalLines -join "`n") + "`n"

if (-not $NoWrite) {
    Write-AtomicText (Join-Path $reportsRoot "$reportId.md") $reportText
    Write-AtomicText (Join-Path $guardianRoot "latest.md") $reportText
    $journalPath = Join-Path $journalRoot "$dayId.md"
    $existing = if (Test-Path -LiteralPath $journalPath -PathType Leaf) { Get-Content -Raw -LiteralPath $journalPath } else { "# Guardian journal — $dayId`n`n" }
    if ($existing -notmatch [regex]::Escape($journalMarker)) {
        Write-AtomicText $journalPath ($existing.TrimEnd() + "`n`n" + $journalEntry)
    }
    Write-AtomicText (Join-Path $journalRoot "latest.md") $journalEntry
}

if ($AsJson) {
    $snapshot | ConvertTo-Json -Depth 12
}
else {
    Write-Output "Guardian report: $health ($reportId)"
    Write-Output "GM scene: $sceneText; delivery attention: $([int]$attention); NyankoFace pending: $($nyankoface.pending)"
    if (-not $NoWrite) {
        Write-Output (Join-Path $reportsRoot "$reportId.md")
        Write-Output (Join-Path $guardianRoot "latest.md")
        Write-Output (Join-Path $journalRoot "$dayId.md")
    }
}

# This script is called through PowerShell's call operator by the hourly
# runner.  Without an explicit exit, the caller can observe the exit code of
# the last native Docker invocation (for example -1) even though the report
# was produced successfully.
exit 0
