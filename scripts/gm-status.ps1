[CmdletBinding()]
param(
    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$statePath = Join-Path $projectRoot "runtime\instances\gm\events.json"

if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
}
else {
    $state = [pscustomobject]@{ version = 3; seen = @(); battles = @(); events = @(); scenes = @(); currentScene = $null; nextSceneAt = 0 }
}

$battles = @($state.battles)
$statusCounts = @(
    $battles |
        Group-Object status |
        ForEach-Object { [pscustomobject]@{ status = $_.Name; count = $_.Count } }
)
$report = [pscustomobject]@{
    capturedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss K")
    statePath = $statePath
    seenNotes = @($state.seen).Count
    battles = $battles.Count
    statusCounts = $statusCounts
    currentScene = $state.currentScene
    nextSceneAt = $state.nextSceneAt
    sceneCount = @($state.scenes).Count
    activeBattles = @($battles | Where-Object status -in @("challenge", "engaged", "awaiting_result"))
    recentEvents = @($state.events | Select-Object -Last 20)
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
