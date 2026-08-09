#!/usr/bin/env python3
"""Small, safe NyankoFace public-reader and optional agent-metrics client."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def load_env() -> None:
    path = Path("/opt/data/.env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)


load_env()
BASE_URL = os.environ.get(
    "NYANKOFACE_PUBLIC_URL", "https://madesk.tail8be30.ts.net"
).rstrip("/")
GITHUB_REPO = os.environ.get("NYANKOFACE_GITHUB_REPO", "Sunwood-ai-labs/NyankoFace")
GITHUB_URL = os.environ.get(
    "NYANKOFACE_GITHUB_URL", f"https://github.com/{GITHUB_REPO}"
).rstrip("/")
GITHUB_ISSUES_URL = f"{GITHUB_URL}/issues"
LOCAL_PATH = os.environ.get("NYANKOFACE_LOCAL_PATH", "")
SSH_TARGET = os.environ.get("NYANKOFACE_SSH_TARGET", "")
AGENT_KEY_FILE = os.environ.get(
    "NYANKOFACE_AGENT_API_KEY_FILE", "/opt/data/nyankoface-agent-api-key"
)
AGENT_SLUG = os.environ.get("NYANKOFACE_AGENT_SLUG", "character")
OUTBOX_DIR = Path(
    os.environ.get("NYANKOFACE_OUTBOX_DIR", "/opt/data/nyankoface-outbox")
)
ARTIFACT_KINDS = ("knowledge", "skill", "prompt", "space")
REPORT_KINDS = ("bug", "enhancement")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SECRET_SHAPES = re.compile(
    r"(?i)(?:api[_-]?key|password|access[_-]?token|bearer\s+[A-Za-z0-9._-]{20,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
REPORT_SECRET_VALUES = re.compile(
    r"(?ix)"
    r"(?:\b(?:api[_-]?key|password|access[_-]?token|token|credential|authorization|secret|private[_-]?key)\s*[:=]\s*\S+)"
    r"|(?:\bbearer\s+[A-Za-z0-9._-]{20,})"
    r"|(?:\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]{16,})"
    r"|(?:-----BEGIN\s+[A-Z ]*PRIVATE KEY-----)"
    r"|(?:https?://[^\s/@:]+:[^\s/@]+@)"
)
REPORT_FIELD_LIMIT = 256 * 1024


def request_json(path: str, *, method: str = "GET", headers: dict[str, str] | None = None) -> object:
    request = urllib.request.Request(
        f"{BASE_URL}/{path.lstrip('/')}",
        headers={"Accept": "application/json", "User-Agent": "agent-zero-nyankoface/1", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
        return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"NyankoFace HTTP {exc.code}: {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"NyankoFace unavailable: {exc.reason}") from exc


def compact_repository(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        return {"value": item}
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    owner_name = str(owner.get("login") or item.get("owner_name") or "?")
    repo = str(item.get("name") or "?")
    return {
        "repository": f"{owner_name}/{repo}",
        "description": item.get("description") or "",
        "topics": item.get("topics") or [],
        "detail_url": f"{BASE_URL}/{owner_name}/{repo}",
        "updated_at": item.get("updated_at"),
        "metrics": item.get("metrics") or {},
    }


def read_agent_key() -> str:
    try:
        value = Path(AGENT_KEY_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if not value:
        raise RuntimeError(
            "No per-character NyankoFace agent key is provisioned; public reads remain available."
        )
    return value


def agent_key_configured() -> bool:
    try:
        return bool(Path(AGENT_KEY_FILE).read_text(encoding="utf-8").strip())
    except OSError:
        return False


def public_catalog(args: argparse.Namespace) -> None:
    query: dict[str, str] = {"limit": str(args.limit)}
    if args.query:
        query["q"] = args.query
    if args.topic:
        query["topic"] = args.topic
    payload = request_json("api/catalog/repositories?" + urllib.parse.urlencode(query))
    data = payload.get("data", []) if isinstance(payload, dict) else payload
    result = {
        "source": "NyankoFace public catalog",
        "public_url": BASE_URL,
        "count": len(data) if isinstance(data, list) else 0,
        "repositories": [compact_repository(item) for item in data] if isinstance(data, list) else [],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def public_agents(_: argparse.Namespace) -> None:
    payload = request_json("runner-api/agents")
    agents = payload if isinstance(payload, list) else []
    print(json.dumps({"public_url": BASE_URL, "agents": agents}, ensure_ascii=False, indent=2))


def public_metrics(args: argparse.Namespace) -> None:
    payload = request_json(
        f"runner-api/metrics/repos/{urllib.parse.quote(args.owner, safe='')}/{urllib.parse.quote(args.repo, safe='')}"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def source(_: argparse.Namespace) -> None:
    print(
        json.dumps(
            {
                "public_url": BASE_URL,
                "github_repository": GITHUB_REPO,
                "github_url": GITHUB_URL,
                "github_issues_url": GITHUB_ISSUES_URL,
                "operator_local_checkout_configured": bool(LOCAL_PATH),
                "operator_ssh_mirror_configured": bool(SSH_TARGET),
                "character_agent_key_configured": agent_key_configured(),
                "artifact_home": "NyankoFace canonical commons",
                "publish_mode": "operator-reviewed GitHub Issues/Forgejo/MCP workflow",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def artifact_contract(_: argparse.Namespace) -> None:
    print(
        json.dumps(
            {
                "canonical_home": BASE_URL,
                "kinds": list(ARTIFACT_KINDS),
                "required_files": ["artifact.json", "README.md"],
                "metadata": ["kind", "slug", "title", "agent", "source", "created_at"],
                "publish_boundary": "staged drafts require operator-reviewed authenticated publication",
                "secret_policy": "keys, passwords, tokens, and private keys are rejected",
                "issue_reporting": {
                    "kinds": list(REPORT_KINDS),
                    "command": "nyankoface.py report",
                    "destination": GITHUB_ISSUES_URL,
                    "publication": "operator duplicate-checks and creates GitHub Issues",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def draft_artifact(args: argparse.Namespace) -> None:
    if not SAFE_SLUG.fullmatch(args.slug):
        raise RuntimeError("artifact slug must contain lowercase letters, numbers, and hyphens")
    if args.kind not in ARTIFACT_KINDS:
        raise RuntimeError(f"unsupported artifact kind: {args.kind}")
    try:
        body = Path(args.body_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"artifact body could not be read: {args.body_file}") from exc
    if not body.strip():
        raise RuntimeError("artifact body must not be empty")
    if len(body.encode("utf-8")) > 1024 * 1024:
        raise RuntimeError("artifact body exceeds the 1 MiB draft limit")
    if SECRET_SHAPES.search(body):
        raise RuntimeError("artifact body resembles a credential; remove secrets before staging")

    target = OUTBOX_DIR / args.kind / args.slug
    if target.exists() and not args.force:
        raise RuntimeError(f"draft already exists; pass --force to replace it: {target}")
    target.mkdir(parents=True, exist_ok=True)
    metadata = {
        "version": 1,
        "kind": args.kind,
        "slug": args.slug,
        "title": args.title.strip(),
        "agent": AGENT_SLUG,
        "source": f"{BASE_URL}/",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "publication": "pending-operator-review",
    }
    (target / "artifact.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "README.md").write_text(body.rstrip() + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"staged": True, "kind": args.kind, "slug": args.slug, "publication": metadata["publication"]},
            ensure_ascii=False,
        )
    )


def read_report_file(path_value: str, *, label: str, required: bool = True) -> str:
    if not path_value and not required:
        return ""
    try:
        body = Path(path_value).read_text(encoding="utf-8")
    except OSError as exc:
        if not required and isinstance(exc, FileNotFoundError):
            return ""
        raise RuntimeError(f"{label} could not be read: {path_value}") from exc
    if len(body.encode("utf-8")) > REPORT_FIELD_LIMIT:
        raise RuntimeError(f"{label} exceeds the 256 KiB report limit")
    if required and not body.strip():
        raise RuntimeError(f"{label} must not be empty")
    return body.strip()


def ensure_report_secret_free(fields: dict[str, str]) -> None:
    for name, value in fields.items():
        if REPORT_SECRET_VALUES.search(value):
            raise RuntimeError(f"{name} resembles a credential; remove secrets before staging")


def report_issue(args: argparse.Namespace) -> None:
    if args.kind not in REPORT_KINDS:
        raise RuntimeError(f"unsupported report kind: {args.kind}")
    if not SAFE_SLUG.fullmatch(args.slug):
        raise RuntimeError("report slug must contain lowercase letters, numbers, and hyphens")
    if not SAFE_SLUG.fullmatch(AGENT_SLUG):
        raise RuntimeError("NYANKOFACE_AGENT_SLUG is not a safe identity slug")

    title = args.title.strip()
    summary = args.summary.strip()
    environment = args.environment.strip()
    expected = args.expected.strip()
    actual = args.actual.strip()
    impact = args.impact.strip()
    suggested_fix = args.suggested_fix.strip()
    if not title or not summary or not environment or not expected or not actual or not impact or not suggested_fix:
        raise RuntimeError("title, summary, environment, expected, actual, impact, and suggested-fix must not be empty")
    if "\n" in title or "\r" in title:
        raise RuntimeError("report title must be a single line")
    if len(title) > 180:
        raise RuntimeError("report title must be 180 characters or fewer")
    reproduction = read_report_file(args.reproduction_file, label="reproduction steps")
    evidence = read_report_file(args.evidence_file, label="evidence", required=False) or "No additional evidence was attached."
    fields = {
        "title": title,
        "summary": summary,
        "environment": environment,
        "reproduction": reproduction,
        "expected": expected,
        "actual": actual,
        "impact": impact,
        "evidence": evidence,
        "suggested_fix": suggested_fix,
    }
    ensure_report_secret_free(fields)

    issue_title = f"[NyankoFace] {title}"
    target = OUTBOX_DIR / "reports" / AGENT_SLUG / f"{args.kind}-{args.slug}"
    if target.exists() and not args.force:
        raise RuntimeError(f"report already exists; pass --force to replace it: {target}")
    target.mkdir(parents=True, exist_ok=True)
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata = {
        "version": 1,
        "kind": args.kind,
        "slug": args.slug,
        "title": issue_title,
        "agent": AGENT_SLUG,
        "repository": GITHUB_REPO,
        "issues_url": GITHUB_ISSUES_URL,
        "source": f"{BASE_URL}/",
        "created_at": created_at,
        "publication": "pending-github-issue",
        "status": "pending",
    }
    issue_body = "\n".join(
        [
            "<!-- Generated by the NyankoFace commons report contract. Do not add credentials. -->",
            f"## Summary\n{summary}",
            "## Environment\n" + environment,
            "## Reproduction steps\n" + reproduction,
            "## Expected behavior\n" + expected,
            "## Actual behavior\n" + actual,
            "## Impact\n" + impact,
            "## Evidence\n" + evidence,
            "## Suggested fix\n" + suggested_fix,
            "## Reporter\n"
            f"- Agent: `{AGENT_SLUG}`\n"
            f"- Source: {BASE_URL}/\n"
            f"- Report kind: `{args.kind}`",
        ]
    ).rstrip() + "\n"
    (target / "issue.md").write_text(issue_body, encoding="utf-8")
    (target / "report.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "staged": True,
                "kind": args.kind,
                "slug": args.slug,
                "title": issue_title,
                "publication": metadata["publication"],
                "report_path": str(target),
            },
            ensure_ascii=False,
        )
    )


def authenticated_action(args: argparse.Namespace, *, like: bool) -> None:
    key = read_agent_key()
    owner = urllib.parse.quote(args.owner, safe="")
    repo = urllib.parse.quote(args.repo, safe="")
    if like:
        path = f"runner-api/agent/v1/repos/{owner}/{repo}/like"
        method = "PUT"
        headers = {"Authorization": f"Bearer {key}"}
    else:
        path = f"runner-api/agent/v1/repos/{owner}/{repo}/views"
        method = "POST"
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        digest = hashlib.sha256(f"{AGENT_SLUG}:{args.owner}/{args.repo}:{day}".encode()).hexdigest()[:24]
        headers = {
            "Authorization": f"Bearer {key}",
            "Idempotency-Key": args.idempotency_key or f"{AGENT_SLUG}:{args.owner}/{args.repo}:{digest}",
        }
    payload = request_json(path, method=method, headers=headers)
    print(json.dumps({"action": "like" if like else "view", "repository": f"{args.owner}/{args.repo}", "result": payload}, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    source_parser = sub.add_parser("source")
    source_parser.set_defaults(handler=source)

    contract = sub.add_parser("artifact-contract")
    contract.set_defaults(handler=artifact_contract)

    draft = sub.add_parser("draft")
    draft.add_argument("--kind", required=True, choices=ARTIFACT_KINDS)
    draft.add_argument("--slug", required=True)
    draft.add_argument("--title", required=True)
    draft.add_argument("--body-file", required=True)
    draft.add_argument("--force", action="store_true")
    draft.set_defaults(handler=draft_artifact)

    report = sub.add_parser("report")
    report.add_argument("--kind", required=True, choices=REPORT_KINDS)
    report.add_argument("--slug", required=True)
    report.add_argument("--title", required=True)
    report.add_argument("--summary", required=True)
    report.add_argument("--environment", required=True)
    report.add_argument("--reproduction-file", required=True)
    report.add_argument("--expected", required=True)
    report.add_argument("--actual", required=True)
    report.add_argument("--impact", required=True)
    report.add_argument("--evidence-file")
    report.add_argument("--suggested-fix", required=True)
    report.add_argument("--force", action="store_true")
    report.set_defaults(handler=report_issue)

    catalog = sub.add_parser("catalog")
    catalog.add_argument("--limit", type=int, default=8, choices=range(1, 31))
    catalog.add_argument("--query")
    catalog.add_argument("--topic")
    catalog.set_defaults(handler=public_catalog)

    agents = sub.add_parser("agents")
    agents.set_defaults(handler=public_agents)

    metrics = sub.add_parser("metrics")
    metrics.add_argument("--owner", required=True)
    metrics.add_argument("--repo", required=True)
    metrics.set_defaults(handler=public_metrics)

    for name, is_like in (("agent-view", False), ("agent-like", True)):
        action = sub.add_parser(name)
        action.add_argument("--owner", required=True)
        action.add_argument("--repo", required=True)
        if not is_like:
            action.add_argument("--idempotency-key")
        action.set_defaults(handler=lambda parsed, like=is_like: authenticated_action(parsed, like=like))

    args = parser.parse_args()
    try:
        args.handler(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
