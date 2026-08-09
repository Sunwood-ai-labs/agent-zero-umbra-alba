[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$DryRun,
    [ValidateRange(1, 50)]
    [int]$MaxReportsPerRun = 10
)

$ErrorActionPreference = "Stop"
$repository = "Sunwood-ai-labs/NyankoFace"
$root = [System.IO.Path]::GetFullPath($ProjectRoot)
$outboxRoot = [System.IO.Path]::GetFullPath((Join-Path $root "runtime\nyankoface-outbox"))
$reportsRoot = Join-Path $outboxRoot "reports"

function Assert-ContainedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $prefix = $fullRoot + [System.IO.Path]::DirectorySeparatorChar
    if ($fullPath -ne $fullRoot -and -not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Report path escapes the NyankoFace outbox: $Path"
    }
    return $fullPath
}

function Set-MetadataValue {
    param(
        [Parameter(Mandatory = $true)][psobject]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Save-Metadata {
    param(
        [Parameter(Mandatory = $true)][psobject]$Metadata,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $temporaryPath = "$Path.tmp.$PID"
    $json = $Metadata | ConvertTo-Json -Depth 10
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryPath, "$json`n", $utf8NoBom)
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Assert-SecretFree {
    param(
        [Parameter(Mandatory = $true)][string[]]$Values,
        [Parameter(Mandatory = $true)][string]$Context
    )
    $secretPattern = '(?ix)(?:\b(?:api[_-]?key|password|access[_-]?token|secret|private[_-]?key)\s*[:=]\s*\S+)|(?:\bbearer\s+[A-Za-z0-9._-]{20,})|(?:\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]{16,})|(?:-----BEGIN\s+[A-Z ]*PRIVATE KEY-----)|(?:https?://[^\s/@:]+:[^\s/@]+@)'
    foreach ($value in $Values) {
        if ($value -match $secretPattern) {
            throw "$Context resembles a credential; remove secrets before publication."
        }
    }
}

if (-not (Test-Path -LiteralPath $reportsRoot -PathType Container)) {
    Write-Output "No NyankoFace reports are staged."
    exit 0
}

$null = Get-Command gh -ErrorAction Stop
$null = & gh auth status --hostname github.com 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated; no reports were published."
}

$reportFiles = @(Get-ChildItem -LiteralPath $reportsRoot -Recurse -Filter "report.json" -File)
$published = 0
$duplicates = 0
$skipped = 0
$dryRunCount = 0
$failed = 0
$deferred = 0
$pendingSeen = 0

foreach ($reportFile in $reportFiles) {
    $metadataPath = $null
    try {
        $metadataPath = Assert-ContainedPath -Path $reportFile.FullName -Root $outboxRoot
        $metadata = Get-Content -Raw -LiteralPath $metadataPath | ConvertFrom-Json
        if ($null -eq $metadata) {
            throw "report metadata is empty"
        }
        $issuePath = Assert-ContainedPath -Path (Join-Path $reportFile.DirectoryName "issue.md") -Root $outboxRoot
        if (-not (Test-Path -LiteralPath $issuePath -PathType Leaf)) {
            throw "issue.md is missing"
        }
        $status = [string]$metadata.status
        if ($status -in @("published", "duplicate")) {
            $skipped++
            continue
        }
        if ($status -ne "pending") {
            throw "unsupported report status: $status"
        }
        if ($pendingSeen -ge $MaxReportsPerRun) {
            $deferred++
            continue
        }
        $pendingSeen++
        foreach ($required in @("kind", "slug", "title", "agent", "repository", "source", "created_at")) {
            if (-not ($metadata.PSObject.Properties.Name -contains $required) -or [string]::IsNullOrWhiteSpace([string]$metadata.$required)) {
                throw "report metadata is missing $required"
            }
        }
        if ([string]$metadata.repository -ne $repository) {
            throw "report targets an unexpected repository"
        }
        if ([string]$metadata.kind -notin @("bug", "enhancement")) {
            throw "report kind must be bug or enhancement"
        }
        $issueBody = Get-Content -Raw -LiteralPath $issuePath
        Assert-SecretFree -Values @([string]$metadata.title, $issueBody) -Context "Report $($reportFile.DirectoryName)"

        $searchArgs = @(
            "issue", "list", "--repo", $repository, "--state", "all", "--limit", "50",
            "--search", "in:title $([string]$metadata.title)", "--json", "number,title,url,state"
        )
        $searchOutput = & gh @searchArgs
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub duplicate search failed"
        }
        $matches = @()
        if (-not [string]::IsNullOrWhiteSpace(($searchOutput -join ""))) {
            $matches = @($searchOutput -join "`n" | ConvertFrom-Json)
        }
        $duplicate = @($matches | Where-Object { [string]$_.title -eq [string]$metadata.title } | Select-Object -First 1)
        if ($duplicate.Count -gt 0) {
            $match = $duplicate[0]
            if (-not $DryRun) {
                Set-MetadataValue -Object $metadata -Name "status" -Value "duplicate"
                Set-MetadataValue -Object $metadata -Name "issue_number" -Value ([int]$match.number)
                Set-MetadataValue -Object $metadata -Name "issue_url" -Value ([string]$match.url)
                Set-MetadataValue -Object $metadata -Name "duplicate_checked_at" -Value ((Get-Date).ToUniversalTime().ToString("o"))
                Save-Metadata -Metadata $metadata -Path $metadataPath
            }
            $duplicates++
            Write-Output "Duplicate: issue #$($match.number) $($match.url)"
            continue
        }

        if ($DryRun) {
            $dryRunCount++
            Write-Output "Would publish: $([string]$metadata.title)"
            continue
        }

        $createArgs = @(
            "issue", "create", "--repo", $repository, "--title", [string]$metadata.title,
            "--body-file", $issuePath, "--label", [string]$metadata.kind
        )
        $createOutput = & gh @createArgs
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub issue creation failed"
        }
        $issueUrl = (($createOutput | Select-Object -Last 1).ToString()).Trim()
        if ($issueUrl -notmatch '^https://github\.com/Sunwood-ai-labs/NyankoFace/issues/\d+$') {
            throw "GitHub returned an unexpected issue URL"
        }
        $issueNumber = [int]($issueUrl -replace '^.*/', "")
        Set-MetadataValue -Object $metadata -Name "status" -Value "published"
        Set-MetadataValue -Object $metadata -Name "issue_number" -Value $issueNumber
        Set-MetadataValue -Object $metadata -Name "issue_url" -Value $issueUrl
        Set-MetadataValue -Object $metadata -Name "published_at" -Value ((Get-Date).ToUniversalTime().ToString("o"))
        Save-Metadata -Metadata $metadata -Path $metadataPath
        $published++
        Write-Output "Published: issue #$issueNumber $issueUrl"
    } catch {
        $failed++
        $displayPath = if ($metadataPath) { $metadataPath } else { $reportFile.FullName }
        Write-Error "Failed to process NyankoFace report ${displayPath}: $($_.Exception.Message)"
    }
}

Write-Output "Summary: published=$published duplicates=$duplicates skipped=$skipped deferred=$deferred dry_run=$dryRunCount failed=$failed"
if ($failed -gt 0) {
    exit 1
}
