from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMONS_SCRIPTS = PROJECT_ROOT / "seed" / "skills" / "nyankoface-commons" / "scripts"
HELPER = COMMONS_SCRIPTS / "github-issues.py"


def load_helper():
    sys.path.insert(0, str(COMMONS_SCRIPTS))
    spec = importlib.util.spec_from_file_location("nyankoface_issue_publisher_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_verifies_created_issue_before_marking_published(tmp_path: Path, monkeypatch) -> None:
    helper = load_helper()
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    title = "[NyankoFace] Verify published issue"
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "kind": "enhancement",
                "title": title,
                "repository": "Sunwood-ai-labs/NyankoFace",
                "status": "pending",
                "agent": "gm-luna-max",
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "issue.md").write_text("## Summary\nA reproducible improvement.\n", encoding="utf-8")

    issue_url = "https://github.com/Sunwood-ai-labs/NyankoFace/issues/42"
    calls: list[tuple[str, str]] = []

    def fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method))
        if path.startswith("search/issues?"):
            return {"items": []}
        if path == "repos/Sunwood-ai-labs/NyankoFace/issues" and method == "POST":
            return {"number": 42, "html_url": issue_url, "title": title}
        if path == "repos/Sunwood-ai-labs/NyankoFace/issues/42" and method == "GET":
            return {"number": 42, "html_url": issue_url, "title": title, "state": "open"}
        raise AssertionError((path, method))

    monkeypatch.setattr(helper, "request_json", fake_request)
    helper.publish_report(Namespace(report_dir=str(report_dir)))

    metadata = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "published"
    assert metadata["issue_state"] == "open"
    assert metadata["verified_at"]
    assert calls[-1] == ("repos/Sunwood-ai-labs/NyankoFace/issues/42", "GET")


def test_publish_rechecks_existing_issue_status(tmp_path: Path, monkeypatch) -> None:
    helper = load_helper()
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    title = "[NyankoFace] Recheck existing issue"
    issue_url = "https://github.com/Sunwood-ai-labs/NyankoFace/issues/8"
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "kind": "bug",
                "title": title,
                "repository": "Sunwood-ai-labs/NyankoFace",
                "status": "published",
                "agent": "gm-luna-max",
                "issue_number": 8,
                "issue_url": issue_url,
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "issue.md").write_text("## Summary\nA previously published issue.\n", encoding="utf-8")

    calls: list[tuple[str, str]] = []

    def fake_request(path: str, *, method: str = "GET", payload=None):
        calls.append((path, method))
        assert path == "repos/Sunwood-ai-labs/NyankoFace/issues/8"
        assert method == "GET"
        return {"number": 8, "html_url": issue_url, "title": title, "state": "closed"}

    monkeypatch.setattr(helper, "request_json", fake_request)
    helper.publish_report(Namespace(report_dir=str(report_dir)))

    metadata = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "published"
    assert metadata["issue_state"] == "closed"
    assert metadata["verified_at"]
    assert calls == [("repos/Sunwood-ai-labs/NyankoFace/issues/8", "GET")]


def test_pending_publication_failure_is_recorded_without_the_secret(tmp_path: Path) -> None:
    helper = load_helper()
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "report.json").write_text(
        json.dumps({"status": "pending", "title": "[NyankoFace] Pending report"}),
        encoding="utf-8",
    )

    helper.mark_publication_pending(str(report_dir), RuntimeError("GitHub unavailable; token=secret-value"))

    metadata = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert metadata["publication_error"].startswith("GitHub unavailable;")
    assert "[redacted]" in metadata["publication_error"]
    assert "secret-value" not in json.dumps(metadata)
    assert metadata["publication_checked_at"]


def test_publish_rejects_issue_url_for_another_repository(tmp_path: Path, monkeypatch) -> None:
    helper = load_helper()
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    title = "[NyankoFace] Reject foreign issue URL"
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "kind": "bug",
                "title": title,
                "repository": "Sunwood-ai-labs/NyankoFace",
                "status": "pending",
                "agent": "gm-luna-max",
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "issue.md").write_text("## Summary\nA reproducible bug.\n", encoding="utf-8")

    monkeypatch.setattr(
        helper,
        "request_json",
        lambda path, *, method="GET", payload=None: (
            {"items": []}
            if path.startswith("search/issues?")
            else {"number": 12, "html_url": "https://github.com/other/repo/issues/12", "title": title}
        ),
    )

    try:
        helper.publish_report(Namespace(report_dir=str(report_dir)))
    except RuntimeError as error:
        assert "unexpected Issue URL" in str(error)
        helper.mark_publication_pending(str(report_dir), error)
    else:
        raise AssertionError("foreign Issue URL was accepted")

    metadata = json.loads((report_dir / "report.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "pending"
    assert "unexpected Issue URL" in metadata["publication_error"]
