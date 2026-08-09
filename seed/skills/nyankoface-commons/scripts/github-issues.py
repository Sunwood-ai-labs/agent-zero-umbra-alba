#!/usr/bin/env python3
"""Secret-safe GitHub Issue publisher for an agent's structured reports."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nyankoface import GITHUB_REPO as NYANKOFACE_REPO, REPORT_SECRET_VALUES


GITHUB_API = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
GITHUB_REPO = os.environ.get("GITHUB_ISSUE_REPO", NYANKOFACE_REPO)
GITHUB_TOKEN_FILE = Path(
    os.environ.get("GITHUB_TOKEN_FILE", "/run/secrets/github_agent_token")
)
REPORT_KINDS = ("bug", "enhancement")
REPORT_LIMIT = 256 * 1024
ISSUE_URL = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues/\d+$")


def read_token() -> str:
    try:
        token = GITHUB_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            "GitHub agent token is not provisioned; publish remains unavailable."
        ) from exc
    if not re.fullmatch(r"(?:ghp_|github_pat_)[A-Za-z0-9_]+", token):
        raise RuntimeError("GitHub agent token format is invalid")
    return token


def request_json(path: str, *, method: str = "GET", payload: object | None = None) -> object:
    token = read_token()
    body = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "agent-zero-nyankoface-issues/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{GITHUB_API}/{path.lstrip('/')}",
        headers=headers,
        method=method,
        data=body,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API unavailable: {exc.reason}") from exc


def write_metadata(path: Path, metadata: dict[str, object]) -> None:
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_report(report_dir: Path) -> tuple[Path, dict[str, object], str]:
    report_dir = report_dir.resolve()
    metadata_path = report_dir / "report.json"
    body_path = report_dir / "issue.md"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        body = body_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"structured report could not be read: {report_dir}") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError("report metadata must be an object")
    if len(body.encode("utf-8")) > REPORT_LIMIT:
        raise RuntimeError("report body exceeds the 256 KiB limit")
    if REPORT_SECRET_VALUES.search(body) or REPORT_SECRET_VALUES.search(str(metadata.get("title", ""))):
        raise RuntimeError("report resembles a credential; remove secrets before publication")
    required = ("kind", "title", "repository", "status", "agent")
    missing = [name for name in required if not str(metadata.get(name, "")).strip()]
    if missing:
        raise RuntimeError(f"report metadata is missing {', '.join(missing)}")
    if metadata["repository"] != GITHUB_REPO:
        raise RuntimeError("report targets an unexpected repository")
    if metadata["kind"] not in REPORT_KINDS:
        raise RuntimeError("report kind must be bug or enhancement")
    if metadata["status"] not in ("pending", "published", "duplicate"):
        raise RuntimeError("unsupported report status")
    return metadata_path, metadata, body


def publish_report(args: argparse.Namespace) -> None:
    report_dir = Path(args.report_dir)
    metadata_path, metadata, body = read_report(report_dir)
    status = str(metadata["status"])
    if status in ("published", "duplicate"):
        print(json.dumps({"status": status, "issue_url": metadata.get("issue_url")}, ensure_ascii=False))
        return

    title = str(metadata["title"])
    query = urllib.parse.urlencode(
        {"q": f"repo:{GITHUB_REPO} in:title {title}", "per_page": "50"}
    )
    search = request_json(f"search/issues?{query}")
    items = search.get("items", []) if isinstance(search, dict) else []
    duplicates = [item for item in items if isinstance(item, dict) and item.get("title") == title]
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if duplicates:
        match = duplicates[0]
        metadata.update(
            {
                "status": "duplicate",
                "issue_number": match.get("number"),
                "issue_url": match.get("html_url"),
                "duplicate_checked_at": now,
            }
        )
        write_metadata(metadata_path, metadata)
        print(json.dumps({"status": "duplicate", "issue_url": match.get("html_url")}, ensure_ascii=False))
        return

    created = request_json(
        f"repos/{GITHUB_REPO}/issues",
        method="POST",
        payload={"title": title, "body": body, "labels": [str(metadata["kind"])]},
    )
    if not isinstance(created, dict) or not ISSUE_URL.fullmatch(str(created.get("html_url", ""))):
        raise RuntimeError("GitHub returned an unexpected Issue URL")
    metadata.update(
        {
            "status": "published",
            "issue_number": created.get("number"),
            "issue_url": created.get("html_url"),
            "published_at": now,
        }
    )
    write_metadata(metadata_path, metadata)
    print(json.dumps({"status": "published", "issue_url": created["html_url"]}, ensure_ascii=False))


def token_status(_: argparse.Namespace) -> None:
    token = read_token()
    print(
        json.dumps(
            {"configured": True, "path": str(GITHUB_TOKEN_FILE), "length": len(token), "value": "redacted"},
            ensure_ascii=False,
        )
    )


def repo_check(_: argparse.Namespace) -> None:
    payload = request_json(f"repos/{GITHUB_REPO}")
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub repository response was not an object")
    print(
        json.dumps(
            {
                "repository": GITHUB_REPO,
                "accessible": bool(payload.get("full_name") == GITHUB_REPO),
                "issues_enabled": bool(payload.get("has_issues")),
                "issue_create_endpoint": f"/repos/{GITHUB_REPO}/issues",
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("token-status")
    status.set_defaults(handler=token_status)

    check = sub.add_parser("repo-check")
    check.set_defaults(handler=repo_check)

    publish = sub.add_parser("publish-report")
    publish.add_argument("--report-dir", required=True)
    publish.set_defaults(handler=publish_report)

    args = parser.parse_args()
    try:
        args.handler(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
