# Hourly GM automation

The Windows task `Agent Zero Umbra Alba GM Hourly` runs Codex every hour with `gpt-5.6-luna` and maximum reasoning in this repository.

The run is an outside GM review, not a resident persona. It compares the black, white, and world timelines with `events.json`, checks whether explicit `@gm` requests reached the existing deterministic watcher, and takes the smallest reversible action when a confirmed infrastructure or memory-maintenance failure is found. It never hand-edits canon facts, invents outcomes, assigns roles, or impersonates an inhabitant.

After two consecutive reports show the same narrow loop or material stagnation, it may adjust only the bounded `## 自律の視野` section of runtime `SOUL.md` files. Such changes require a backup, rationale, diff, and six-hour cooldown; biographies, values, WORLD, memories, roles, and victory conditions remain untouched.

Confirmed, reproducible NyankoFace bugs and concrete improvement opportunities are staged with `nyankoface.py report` and published to `Sunwood-ai-labs/NyankoFace` through `github-issues.py`. An improvement opportunity must include an observed example or reproduction steps, expected versus actual behavior, impact, and an actionable fix idea. Local argument/configuration mistakes, speculation, one-off user input mistakes, and duplicate reports are filtered out or fixed locally first. Existing Issues are searched before publishing, and the resulting Issue URL/status is verified. If publication fails, the pending report records a secret-free reason. Tokens are read from `D:\Prj\.menv\github-agent-token` and never written to logs, commits, or timelines.

Each run writes an evidence report and a separate god-view journal under `runtime/guardian/`. The snapshot checks all 32 Compose services, both persistent scheduler state files, plus the 20 bounded `SOUL.md` and 20 non-empty `WORLD.md` files. Recent scheduler failures and an active provider cooldown remain `unhealthy` even when a scheduler container has just been recreated and its Docker log window is empty. The Docker `world-gm` process continues to handle the ten-second scene/action/battle protocol; the hourly automation provides the higher-level review and bounded intervention layer.

The Guardian report labels `world-gm` connection-refused retries during the first 120 seconds after container start as transient startup events. They remain visible in the JSON/report, while persistent endpoint failures and other errors still produce `unhealthy`.

The bounded log section includes only a few sanitized error/warning samples. It does not recurse through Hermes homes or copy complete Docker logs into the report.

The bounded, deterministic evidence pass can be run independently of Codex:

```powershell
./scripts/guardian-report.ps1
./scripts/guardian-report.ps1 -NoWrite -AsJson
./scripts/bounded-soul.ps1 -AsJson
```

`bounded-soul.ps1 -Apply` requires two different reports under `runtime/guardian/reports`, records the rationale, creates a backup, and refuses another change during the six-hour cooldown. It can only add a bullet inside `## 自律の視野`; it cannot modify identity, `WORLD.md`, memory, roles, or victory conditions.

```powershell
Get-ScheduledTask -TaskName "Agent Zero Umbra Alba GM Hourly"
Get-ScheduledTaskInfo -TaskName "Agent Zero Umbra Alba GM Hourly"
Get-Content "$env:USERPROFILE\.codex\automations\agent-zero-umbra-alba-gm-hourly\logs\latest-run.txt"
./scripts/gm-status.ps1 -AsJson
```

The runner writes `status=running` to `logs/latest-run.txt` before starting Codex and replaces it with the final result when the run ends, so an interrupted run is not mistaken for the previous successful run. It also keeps a file lock so overlapping hourly invocations exit cleanly. The scheduled task has a 45-minute execution limit; do not launch a second Codex runner or terminate it with `taskkill`. Inspect the latest log and let the task boundary release the process.
