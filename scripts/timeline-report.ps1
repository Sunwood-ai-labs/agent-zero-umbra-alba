[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:3310",

    [ValidateRange(1, 100)]
    [int]$Limit = 100,

    [switch]$AsJson
)

$ErrorActionPreference = "Stop"

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

$capturedAt = Get-JstNow
$payload = @{ limit = $Limit } | ConvertTo-Json
$notes = Invoke-RestMethod -Uri "$($BaseUrl.TrimEnd('/'))/api/notes/global-timeline" `
    -Method Post -ContentType "application/json" -Body $payload -TimeoutSec 30

$reactionRows = foreach ($note in $notes) {
    $properties = @(
        $note.reactions.PSObject.Properties |
            Where-Object MemberType -eq NoteProperty
    )
    foreach ($property in $properties) {
        [pscustomobject]@{
            emoji = $property.Name
            count = [int]$property.Value
        }
    }
}

$topEmoji = @(
    $reactionRows |
        Group-Object emoji |
        ForEach-Object {
            [pscustomobject]@{
                emoji = $_.Name
                count = ($_.Group.count | Measure-Object -Sum).Sum
            }
        } |
        Sort-Object count -Descending |
        Select-Object -First 10
)

$report = [pscustomobject]@{
    capturedAt = $capturedAt.ToString("yyyy-MM-dd HH:mm:ss zzz")
    timezone = "Asia/Tokyo"
    sample = $notes.Count
    originalNotes = @(
        $notes | Where-Object { $_.text -and -not $_.replyId -and -not $_.renoteId }
    ).Count
    replies = @($notes | Where-Object replyId).Count
    renotes = @($notes | Where-Object { $_.renoteId -and -not $_.text }).Count
    quotes = @($notes | Where-Object { $_.renoteId -and $_.text }).Count
    reactedNotes = @(
        $notes | Where-Object {
            @(
                $_.reactions.PSObject.Properties |
                    Where-Object MemberType -eq NoteProperty
            ).Count -gt 0
        }
    ).Count
    totalReactions = ($reactionRows.count | Measure-Object -Sum).Sum
    uniqueEmoji = @($reactionRows | Group-Object emoji).Count
    authors = @(
        $notes |
            Group-Object { $_.user.username } |
            Sort-Object Count -Descending |
            Select-Object @{ Name = "username"; Expression = { $_.Name } }, Count
    )
    topEmoji = $topEmoji
}

if ($AsJson) {
    $report | ConvertTo-Json -Depth 6
}
else {
    $report
}
