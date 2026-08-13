[CmdletBinding()]
param(
    [ValidateSet("Check", "Apply")]
    [string]$Mode = "Check",

    [switch]$Apply,

    [string]$ProjectRoot,

    [string]$Bullet,

    [string]$PreviousEvidenceReport,

    [string]$EvidenceReport,

    [string]$Reason,

    # The six-hour cooldown is part of the safety contract.  Callers may ask
    # for a longer cooldown, but must not shorten it around the guard.
    [ValidateRange(6, 168)]
    [int]$CooldownHours = 6,

    [switch]$AsJson
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { Split-Path -Parent $PSScriptRoot }
}
$projectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
if ($Apply) {
    if ($Mode -eq "Apply") {
        throw "Use either -Apply or -Mode Apply, not both."
    }
    $Mode = "Apply"
}
$runtimeRoot = Join-Path $projectRoot "runtime"
$guardianRoot = Join-Path $runtimeRoot "guardian"
$changeStatePath = Join-Path $guardianRoot "soul-changes.json"
$sectionPattern = '(?ms)^## 自律の視野\s*\r?\n.*?(?=^## |\z)'

function Get-AgentSoulFiles {
    # Only agents/*/SOUL.md are bounded inputs.  Recursing through Hermes
    # homes would accidentally inspect sessions, caches, skills, and backups.
    $files = @()
    foreach ($instance in @("black", "white")) {
        $agentRoot = Join-Path $runtimeRoot ("instances\{0}\agents" -f $instance)
        if (-not (Test-Path -LiteralPath $agentRoot -PathType Container)) {
            continue
        }
        $agentDirs = @(Get-ChildItem -LiteralPath $agentRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name)
        foreach ($agentDir in $agentDirs) {
            $candidate = Join-Path $agentDir.FullName "SOUL.md"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $files += Get-Item -LiteralPath $candidate
            }
        }
    }
    return $files
}

$files = @(Get-AgentSoulFiles)

function Write-AtomicText {
    param([string]$Path, [string]$Text)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Path.tmp.$PID"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporary, $Text, $utf8NoBom)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Get-Hash {
    param([string]$Text)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Assert-SecretFreeText {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Context
    )

    $secretPattern = '(?ix)(?:\b(?:api[_-]?key|password|access[_-]?token|token|credential|authorization|secret|private[_-]?key)\s*[:=]\s*\S+)|(?:\bbearer\s+[A-Za-z0-9._-]{20,})|(?:\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]{16,})|(?:-----BEGIN\s+[A-Z ]*PRIVATE KEY-----)|(?:https?://[^\s/@:]+:[^\s/@]+@)'
    if ($Value -match $secretPattern) {
        throw "$Context resembles a credential; remove secrets before applying a bounded Soul change."
    }
}

function Assert-ContainedReport {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Both evidence report paths are required for Apply."
    }
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $reportsRoot = [System.IO.Path]::GetFullPath((Join-Path $guardianRoot "reports")).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $prefix = $reportsRoot + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Evidence report must be inside runtime/guardian/reports: $Path"
    }
    if ([System.IO.Path]::GetExtension($fullPath) -ne ".md") {
        throw "Evidence report must be a Markdown report: $Path"
    }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Evidence report does not exist: $fullPath"
    }
    return $fullPath
}

function Get-SectionParts {
    param([string]$Text)
    $matches = [regex]::Matches($Text, $sectionPattern)
    if ($matches.Count -ne 1) {
        throw "SOUL.md must contain exactly one bounded ## 自律の視野 section."
    }
    $match = $matches[0]
    return [pscustomobject]@{
        match = $match
        prefix = $Text.Substring(0, $match.Index)
        section = $match.Value
        suffix = $Text.Substring($match.Index + $match.Length)
    }
}

function Read-ChangeState {
    if (-not (Test-Path -LiteralPath $changeStatePath -PathType Leaf)) {
        return [pscustomobject]@{ version = 1; lastAppliedAt = $null; changes = @() }
    }
    try {
        $value = Get-Content -Raw -LiteralPath $changeStatePath | ConvertFrom-Json
        if ($null -eq $value.changes) { $value | Add-Member -NotePropertyName changes -NotePropertyValue @() }
        return $value
    }
    catch {
        throw "Soul change state is not valid JSON: $changeStatePath"
    }
}

$valid = @()
$invalid = @()
foreach ($file in $files) {
    try {
        $text = Get-Content -Raw -LiteralPath $file.FullName
        $parts = Get-SectionParts $text
        $valid += [pscustomobject]@{
            path = $file.FullName
            sectionHash = Get-Hash $parts.section
            outsideHash = Get-Hash ($parts.prefix + $parts.suffix)
        }
    }
    catch {
        $invalid += [pscustomobject]@{ path = $file.FullName; error = $_.Exception.Message }
    }
}

$check = [pscustomobject]@{
    mode = $Mode
    files = $files.Count
    expectedFiles = 20
    sectionValid = ($files.Count -eq 20 -and $invalid.Count -eq 0)
    valid = $valid
    invalid = $invalid
    cooldownHours = $CooldownHours
    changeStatePath = $changeStatePath
}

if ($Mode -eq "Apply") {
    if (-not $check.sectionValid) {
        throw "Refusing Soul change because the bounded section check failed."
    }
    if ([string]::IsNullOrWhiteSpace($Bullet) -or $Bullet.Length -gt 600) {
        throw "Bullet is required and must be between 1 and 600 characters."
    }
    if ($Bullet -match "[\r\n]") {
        throw "Bullet must be a single line so it cannot inject a new section."
    }
    if ($Bullet -notmatch '^\s*-\s+') {
        throw "Bullet must be one bounded list item beginning with '- '."
    }
    if ($Bullet -match '(?i)WORLD\.md|biograph|identity|personality|role|victory|memory|来歴|価値観|人格|人物|性格|役割|職業|勝利条件|勝ち筋|モデル|メモリ|任務|命令') {
        throw "Bullet appears to target an unbounded identity, world, memory, role, or assignment field."
    }
    if ([string]::IsNullOrWhiteSpace($Reason) -or $Reason.Length -gt 1200) {
        throw "Reason is required and must be between 1 and 1200 characters."
    }
    Assert-SecretFreeText $Bullet "Bullet"
    Assert-SecretFreeText $Reason "Reason"
    $previousPath = Assert-ContainedReport $PreviousEvidenceReport
    $currentPath = Assert-ContainedReport $EvidenceReport
    if ([string]::Equals($previousPath, $currentPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The two evidence reports must be different files."
    }

    $state = Read-ChangeState
    if ($state.lastAppliedAt) {
        try {
            $lastApplied = [DateTimeOffset]::Parse([string]$state.lastAppliedAt)
            $elapsed = [DateTimeOffset]::UtcNow - $lastApplied.ToUniversalTime()
            if ($elapsed.TotalHours -lt $CooldownHours) {
                throw "Soul cooldown is active until $($lastApplied.AddHours($CooldownHours).ToString('o'))."
            }
        }
        catch [System.FormatException] {
            throw "Soul change state contains an invalid lastAppliedAt."
        }
    }

    $prepared = @()
    foreach ($file in $files) {
        $before = Get-Content -Raw -LiteralPath $file.FullName
        $parts = Get-SectionParts $before
        if ($parts.section -match [regex]::Escape($Bullet.Trim())) {
            $after = $before
        }
        else {
            $newline = if ($parts.section -match "`r`n") { "`r`n" } else { "`n" }
            $sectionBody = $parts.section.TrimEnd("`r", "`n")
            $after = $parts.prefix + $sectionBody + $newline + $Bullet.Trim() + $newline + $parts.suffix
        }
        $afterParts = Get-SectionParts $after
        if ((Get-Hash ($parts.prefix + $parts.suffix)) -ne (Get-Hash ($afterParts.prefix + $afterParts.suffix))) {
            throw "Bounded edit would change content outside ## 自律の視野: $($file.FullName)"
        }
        $prepared += [pscustomobject]@{
            path = $file.FullName
            before = $before
            after = $after
            beforeHash = Get-Hash $before
            afterHash = Get-Hash $after
            changed = ($before -ne $after)
        }
    }

    $changedFiles = @($prepared | Where-Object changed)
    if ($changedFiles.Count -eq 0) {
        $check | Add-Member -NotePropertyName status -NotePropertyValue "already-present"
    }
    else {
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssZ")
        $backupRoot = Join-Path $guardianRoot ("soul-backups\{0}" -f $stamp)
        $runtimePrefix = [System.IO.Path]::GetFullPath($runtimeRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
        foreach ($item in $changedFiles) {
            $relative = $item.path.Substring($runtimePrefix.Length)
            $backupPath = Join-Path $backupRoot $relative
            $backupParent = Split-Path -Parent $backupPath
            New-Item -ItemType Directory -Force -Path $backupParent | Out-Null
            Copy-Item -LiteralPath $item.path -Destination $backupPath -Force
        }
        $written = @()
        try {
            foreach ($item in $changedFiles) {
                Write-AtomicText $item.path $item.after
                $written += $item
            }
            $now = (Get-Date).ToUniversalTime().ToString("o")
            $change = [pscustomobject]@{
                at = $now
                reason = $Reason
                bullet = $Bullet.Trim()
                previousEvidenceReport = $previousPath
                evidenceReport = $currentPath
                backupRoot = $backupRoot
                files = @($changedFiles | ForEach-Object { $_.path })
                beforeHashes = @($changedFiles | ForEach-Object { [pscustomobject]@{ path = $_.path; sha256 = $_.beforeHash } })
                afterHashes = @($changedFiles | ForEach-Object { [pscustomobject]@{ path = $_.path; sha256 = $_.afterHash } })
            }
            $history = @($state.changes) + $change
            $newState = [pscustomobject]@{ version = 1; lastAppliedAt = $now; changes = @($history | Select-Object -Last 50) }
            Write-AtomicText $changeStatePath (($newState | ConvertTo-Json -Depth 8) + "`n")
        }
        catch {
            # A bounded change is all-or-nothing across the twenty Souls and
            # its audit state.  The backup is already inside guardian scope.
            foreach ($item in $written) {
                Write-AtomicText $item.path $item.before
            }
            throw
        }
        $check | Add-Member -NotePropertyName status -NotePropertyValue "applied"
        $check | Add-Member -NotePropertyName changedFiles -NotePropertyValue $changedFiles.Count
        $check | Add-Member -NotePropertyName backupRoot -NotePropertyValue $backupRoot
    }
}
else {
    $check | Add-Member -NotePropertyName status -NotePropertyValue "checked"
}

if ($AsJson) {
    $check | ConvertTo-Json -Depth 10
}
else {
    Write-Output "bounded Soul: $($check.status); files=$($check.files)/$($check.expectedFiles); sectionValid=$($check.sectionValid)"
    if ($check.backupRoot) { Write-Output "backup=$($check.backupRoot)" }
}
