[CmdletBinding()]
param(
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$statePath = Join-Path $projectRoot "runtime\instances\gm\events.json"

function Get-JstNow {
    $utcNow = [DateTimeOffset]::UtcNow
    foreach ($timeZoneId in @("Tokyo Standard Time", "Asia/Tokyo")) {
        try {
            $timeZone = [TimeZoneInfo]::FindSystemTimeZoneById($timeZoneId)
            return [TimeZoneInfo]::ConvertTime($utcNow, $timeZone)
        }
        catch {
            # Try the platform-specific identifier used by the next runtime.
        }
    }
    return $utcNow.ToOffset([TimeSpan]::FromHours(9))
}

function Get-AuditEvents {
    param([Parameter(Mandatory = $true)][object]$State)

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

$capturedAt = Get-JstNow

if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
}
else {
    $state = [pscustomobject]@{ version = 3; seen = @(); battles = @(); events = @(); scenes = @(); currentScene = $null; nextSceneAt = 0 }
}

$battles = @($state.battles)
$auditEvents = @(Get-AuditEvents $state)
$statusCounts = @(
    $battles |
        Group-Object status |
        ForEach-Object { [pscustomobject]@{ status = $_.Name; count = $_.Count } }
)
$report = [pscustomobject]@{
    capturedAt = $capturedAt.ToString("yyyy-MM-dd HH:mm:ss zzz")
    timezone = "Asia/Tokyo"
    statePath = $statePath
    seenNotes = @($state.seen).Count
    battles = $battles.Count
    statusCounts = $statusCounts
    currentScene = $state.currentScene
    nextSceneAt = $state.nextSceneAt
    sceneCount = @($state.scenes).Count
    survival = $state.survival
    activeBattles = @($battles | Where-Object status -in @("challenge", "engaged", "awaiting_result"))
    ctf = $state.ctf
    dctf = $state.dctf
    dctfArchive = @(
        $state.dctfArchive |
            ForEach-Object {
                [pscustomobject]@{
                    seasonId = $_.seasonId
                    status = $_.status
                    problems = @($_.problems).Count
                    submissions = @($_.submissions).Count
                    events = @($_.events).Count
                    score = $_.score
                }
            }
    )
    recentEvents = @($state.events | Select-Object -Last 20)
    auditEventCount = $auditEvents.Count
    recentAuditEvents = @(
        $auditEvents |
            Sort-Object { [string]$_.at } |
            Select-Object -Last 20
    )
}

if ($AsJson) {
    $report | ConvertTo-Json -Depth 8
    exit 0
}

Write-Host "GM state: $($report.capturedAt)"
Write-Host "Seen notes: $($report.seenNotes); battles: $($report.battles)"
if ($null -ne $report.currentScene) {
    $scene = $report.currentScene
    Write-Host "Current scene: $($scene.id) / $($scene.phase) / $($scene.location) / round $($scene.round)"
    Write-Host "Actions: black=$(@($scene.actions.black).Count), white=$(@($scene.actions.white).Count); deadline=$($scene.actionDeadline)"
}
else {
    Write-Host "Current scene: none"
}
if ($null -ne $report.survival) {
    Write-Host "Survival basis: mode=$($report.survival.clockMode); environment=$($report.survival.environmentSignal); risk=$($report.survival.status)"
    @($report.survival.systems.PSObject.Properties) |
        ForEach-Object {
            $system = $_.Value
            [pscustomobject]@{ system = $system.label; status = $system.status; evidence = (@($system.evidence) -join "; ") }
        } |
        Format-Table -AutoSize
}
if ($statusCounts.Count -gt 0) {
    $statusCounts | Format-Table -AutoSize
}
if ($report.activeBattles.Count -eq 0) {
    Write-Host "No active battles."
}
else {
    $report.activeBattles |
        Select-Object id, status, location, @{Name="challenger"; Expression={ $_.challenger.instance }}, @{Name="responder"; Expression={ $_.responder.instance }} |
        Format-Table -AutoSize
}
if ($null -ne $report.ctf) {
    $ctf = $report.ctf
    Write-Host "CTF flag-board: $($ctf.seasonId) / $($ctf.status) / black=$($ctf.score.black) white=$($ctf.score.white) / target=$($ctf.victoryScore)"
    @($ctf.flags.PSObject.Properties) |
        ForEach-Object {
            $flag = $_.Value
            [pscustomobject]@{ id = $flag.id; location = $flag.location; status = $flag.status; holder = $flag.holder }
        } |
        Format-Table -AutoSize
}
if ($null -ne $report.dctf) {
    $dctf = $report.dctf
    Write-Host "CTFd security competition: $($dctf.name) / $($dctf.status) / black=$($dctf.score.black) white=$($dctf.score.white) / target=$($dctf.victoryScore) / problems=$(@($dctf.problems).Count)"
    @($dctf.problems) |
        Select-Object id, bank, authorFaction, targetFaction, status, points, solvedBy |
        Format-Table -AutoSize
}
