from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLIENT = PROJECT_ROOT / "seed" / "skills" / "nyankoface-commons" / "scripts" / "nyankoface.py"


def run_report(outbox: Path, repro: Path, *, summary: str = "A reproducible observation.") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "NYANKOFACE_OUTBOX_DIR": str(outbox),
            "NYANKOFACE_AGENT_SLUG": "black-agent01",
            "NYANKOFACE_PUBLIC_URL": "https://madesk.tail8be30.ts.net",
        }
    )
    return subprocess.run(
        [
            sys.executable,
            str(CLIENT),
            "report",
            "--kind",
            "bug",
            "--slug",
            "timeline-rendering-newline",
            "--title",
            "Timeline renders escaped newlines",
            "--summary",
            summary,
            "--environment",
            "Public deployment; mobile Safari",
            "--reproduction-file",
            str(repro),
            "--expected",
            "Line breaks render as separate lines.",
            "--actual",
            r"The literal escape sequence \n is displayed.",
            "--impact",
            "Long posts are difficult to read.",
            "--suggested-fix",
            "Normalize escaped line breaks before rendering.",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_report_stages_secret_free_issue(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    repro = tmp_path / "reproduction.txt"
    repro.write_text("1. Open the public timeline.\n2. Inspect the rendered post.\n", encoding="utf-8")

    result = run_report(outbox, repro)

    assert result.returncode == 0, result.stderr
    target = outbox / "reports" / "black-agent01" / "bug-timeline-rendering-newline"
    metadata = json.loads((target / "report.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "pending"
    assert metadata["publication"] == "pending-github-issue"
    assert metadata["title"] == "[NyankoFace] Timeline renders escaped newlines"
    issue_body = (target / "issue.md").read_text(encoding="utf-8")
    assert "## Reproduction steps" in issue_body
    assert "api_key" not in issue_body.lower()


def test_report_rejects_credential_shaped_values(tmp_path: Path) -> None:
    repro = tmp_path / "reproduction.txt"
    repro.write_text("1. Observe the public page.\n", encoding="utf-8")

    result = run_report(tmp_path / "outbox", repro, summary="api_key: should never be included")

    assert result.returncode == 2
    assert "resembles a credential" in result.stderr
    assert not (tmp_path / "outbox" / "reports").exists()


def test_report_requires_explicit_force_for_replacement(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    repro = tmp_path / "reproduction.txt"
    repro.write_text("1. Observe the public page.\n", encoding="utf-8")

    first = run_report(outbox, repro)
    second = run_report(outbox, repro)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 2
    assert "report already exists" in second.stderr
