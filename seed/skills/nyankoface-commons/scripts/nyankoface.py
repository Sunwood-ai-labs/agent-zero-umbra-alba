#!/usr/bin/env python3
"""NyankoFace catalog reader and Forgejo content client.

NyankoFace is a repository-backed commons.  The ``of_agent_*`` credential is
only for attributed view/like metrics; durable content uses a separate,
least-privilege Forgejo token.  The client never prints either credential.
"""

from __future__ import annotations

import argparse
import base64
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
FORGEJO_URL = os.environ.get("NYANKOFACE_FORGEJO_URL", f"{BASE_URL}/git").rstrip("/")
FORGEJO_TOKEN_FILE = os.environ.get(
    "NYANKOFACE_FORGEJO_TOKEN_FILE", "/opt/data/nyankoface-forgejo-token"
)
FORGEJO_TOKEN = os.environ.get("NYANKOFACE_FORGEJO_TOKEN", "").strip()
FORGEJO_USER = os.environ.get("NYANKOFACE_FORGEJO_USER", "").strip()
MCP_URL = os.environ.get("NYANKOFACE_MCP_URL", f"{BASE_URL}/mcp").rstrip("/")
MCP_PROTOCOL_VERSION = "2025-06-18"
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
AGENT_KEY = os.environ.get("NYANKOFACE_AGENT_API_KEY", "").strip()
AGENT_SLUG = os.environ.get("NYANKOFACE_AGENT_SLUG", "character")
OUTBOX_DIR = Path(
    os.environ.get("NYANKOFACE_OUTBOX_DIR", "/opt/data/nyankoface-outbox")
)
ARTIFACT_KINDS = (
    "knowledge",
    "skill",
    "prompt",
    "space",
    "mcp",
    "automation",
    "model",
    "dataset",
    "character",
    "benchmark",
    "pages",
)
REPORT_KINDS = ("bug", "enhancement")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SECRET_SHAPES = re.compile(
    r"(?ix)"
    r"(?:\b(?:api[_-]?key|password|access[_-]?token)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{16,})"
    r"|(?:\bbearer\s+[A-Za-z0-9._-]{20,})"
    r"|(?:-----BEGIN\s+[A-Z ]*PRIVATE KEY-----)"
    r"|(?:\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[A-Za-z0-9_./-]{16,})"
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


def _endpoint_errors(name: str, value: str, expected_path: str) -> list[str]:
    """Return safe, actionable configuration errors for a public endpoint.

    The agents previously turned a valid Forgejo base URL into paths such as
    ``/git/api/swagger/api/v1/...`` by copying a documentation URL into the
    environment.  Validate the *base* path before making a request so a bad
    URL fails locally with a repair hint instead of a misleading remote 404.
    """
    errors: list[str] = []
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors.append(f"{name} must be an absolute http(s) URL")
        return errors
    path = parsed.path.rstrip("/")
    if path != expected_path:
        suffix = f"{expected_path or '/'} (do not append /api/v1, /api/swagger, or a repository path)"
        errors.append(f"{name} must use the public base path {suffix}")
    if parsed.query or parsed.fragment:
        errors.append(f"{name} must not contain a query string or fragment")
    return errors


def _secret_file_configured(path: str) -> bool:
    try:
        return bool(Path(path).read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _runtime_preflight(mode: str) -> dict[str, object]:
    """Check local NyankoFace prerequisites without contacting the network."""
    errors: list[str] = []
    checks: dict[str, object] = {
        "client_path": str(Path(__file__).resolve()),
        "public_url": BASE_URL,
        "forgejo_url": FORGEJO_URL,
        "mcp_url": MCP_URL,
        "forgejo_token_file": FORGEJO_TOKEN_FILE,
        "agent_key_file": AGENT_KEY_FILE,
        "agent_slug": AGENT_SLUG,
        "forgejo_user": FORGEJO_USER or None,
    }
    for name, value, expected_path in (
        ("NYANKOFACE_PUBLIC_URL", BASE_URL, ""),
        ("NYANKOFACE_FORGEJO_URL", FORGEJO_URL, "/git"),
        ("NYANKOFACE_MCP_URL", MCP_URL, "/mcp"),
    ):
        errors.extend(_endpoint_errors(name, value, expected_path))
    if not SAFE_SLUG.fullmatch(AGENT_SLUG):
        errors.append("NYANKOFACE_AGENT_SLUG must be a lowercase hyphenated slug")
    if mode not in {"read", "write", "metrics"}:
        errors.append("preflight mode must be read, write, or metrics")
    if mode == "write":
        if not FORGEJO_USER:
            errors.append("NYANKOFACE_FORGEJO_USER is required for repository writes")
        if not (FORGEJO_TOKEN or _secret_file_configured(FORGEJO_TOKEN_FILE)):
            errors.append("Forgejo content token is missing; writes are blocked")
    if mode == "metrics" and not (AGENT_KEY or _secret_file_configured(AGENT_KEY_FILE)):
        errors.append("per-character NyankoFace agent key is missing; metrics are blocked")
    checks.update(
        {
            "forgejo_token_configured": bool(FORGEJO_TOKEN) or _secret_file_configured(FORGEJO_TOKEN_FILE),
            "agent_key_configured": bool(AGENT_KEY) or _secret_file_configured(AGENT_KEY_FILE),
            "mode": mode,
        }
    )
    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "canonical_commands": {
            "client": "/opt/data/skills/nyankoface-commons/scripts/nyankoface.py",
            "read": "python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py catalog --limit 8",
            "repo": "python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py repo --owner OWNER --repo REPO",
            "file": "python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py file --owner OWNER --repo REPO --path PATH --raw",
            "write": "python /opt/data/skills/nyankoface-commons/scripts/nyankoface.py publish-file --owner OWNER --repo REPO --path PATH --body-file BODY_FILE --message MESSAGE",
        },
    }


def preflight(args: argparse.Namespace) -> None:
    summary = _runtime_preflight(args.mode)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        raise SystemExit(2)


def request_json(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: object | None = None,
    base_url: str = BASE_URL,
) -> object:
    body = None
    request_headers = {"Accept": "application/json", "User-Agent": "agent-zero-nyankoface/1", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        f"{base_url}/{path.lstrip('/')}",
        data=body,
        headers=request_headers,
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


def read_forgejo_token() -> str:
    if FORGEJO_TOKEN:
        return FORGEJO_TOKEN
    try:
        token = Path(FORGEJO_TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not token:
        raise RuntimeError(
            "No Forgejo content token is provisioned; public NyankoFace reads remain available."
        )
    return token


def forgejo_token_available() -> bool:
    if FORGEJO_TOKEN:
        return True
    try:
        return bool(Path(FORGEJO_TOKEN_FILE).read_text(encoding="utf-8").strip())
    except OSError:
        return False


def read_mcp_token() -> str:
    """Use the agent's Forgejo token as the MCP bearer without printing it."""
    return read_forgejo_token()


def mcp_token_available() -> bool:
    return forgejo_token_available()


def _decode_mcp_payload(body: bytes, content_type: str) -> dict[str, object]:
    if not body:
        return {}
    text = body.decode("utf-8", errors="replace")
    if "application/json" in content_type:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise RuntimeError("NyankoFace MCP returned a non-object response")
        return payload
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line.split(":", 1)[1].strip()
        if not data or data == "[DONE]":
            continue
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise RuntimeError("NyankoFace MCP returned a non-object response")
        return payload
    raise RuntimeError("NyankoFace MCP returned no JSON-RPC response")


def mcp_request(
    token: str,
    method: str,
    *,
    request_id: int | None = None,
    params: dict[str, object] | None = None,
) -> tuple[int, str, dict[str, object]]:
    endpoint_errors = _endpoint_errors("NYANKOFACE_MCP_URL", MCP_URL, "/mcp")
    if endpoint_errors:
        raise RuntimeError("; ".join(endpoint_errors) + "; run `nyankoface.py preflight --mode read`")
    message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    request = urllib.request.Request(
        MCP_URL,
        data=json.dumps(message, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "agent-zero-nyankoface-mcp-check/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, _decode_mcp_payload(body, content_type)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"NyankoFace MCP HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"NyankoFace MCP unavailable: {exc.reason}") from exc


def mcp_check(_: argparse.Namespace) -> None:
    summary: dict[str, object] = {
        "mcp_url": MCP_URL,
        "forgejo_token_file": FORGEJO_TOKEN_FILE,
        "mcp_credential_source": "NYANKOFACE_FORGEJO_TOKEN_FILE",
        "forgejo_token_configured": forgejo_token_available(),
        "secret_exposed": False,
    }
    if not summary["forgejo_token_configured"]:
        summary.update(
            {
                "ok": False,
                "error": "Forgejo token is missing; public fallback remains available",
            }
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(2)

    token = read_mcp_token()
    try:
        initialize_status, initialize_type, initialize = mcp_request(
            token,
            "initialize",
            request_id=1,
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agent-zero-mcp-check", "version": "1"},
            },
        )
        initialized_status, _, _ = mcp_request(token, "notifications/initialized")
        tools_status, _, tools = mcp_request(token, "tools/list", request_id=2, params={})
        resources_status, _, resources = mcp_request(token, "resources/list", request_id=3, params={})
    except RuntimeError as exc:
        summary.update({"ok": False, "error": str(exc)})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc

    initialize_result = initialize.get("result") if isinstance(initialize, dict) else {}
    tools_result = tools.get("result") if isinstance(tools, dict) else {}
    resources_result = resources.get("result") if isinstance(resources, dict) else {}
    initialize_protocol = (
        initialize_result.get("protocolVersion")
        if isinstance(initialize_result, dict)
        else None
    )
    initialize_ok = (
        initialize_status == 200
        and isinstance(initialize_result, dict)
        and not initialize.get("error")
        and initialize_protocol == MCP_PROTOCOL_VERSION
    )
    tools_ok = (
        tools_status == 200
        and isinstance(tools_result, dict)
        and not tools.get("error")
        and isinstance(tools_result.get("tools"), list)
    )
    resources_ok = (
        resources_status == 200
        and isinstance(resources_result, dict)
        and not resources.get("error")
        and isinstance(resources_result.get("resources"), list)
    )
    summary.update(
        {
            "ok": initialize_ok
            and initialized_status in {200, 202}
            and tools_ok
            and resources_ok,
            "initialize": {
                "status": initialize_status,
                "content_type": initialize_type,
                "protocol": initialize_protocol,
            },
            "initialized_notification": {"status": initialized_status},
            "tools_list": {
                "status": tools_status,
                "count": len(tools_result.get("tools", []))
                if isinstance(tools_result, dict) and isinstance(tools_result.get("tools"), list)
                else 0,
            },
            "resources_list": {
                "status": resources_status,
                "count": len(resources_result.get("resources", []))
                if isinstance(resources_result, dict) and isinstance(resources_result.get("resources"), list)
                else 0,
            },
        }
    )
    if not summary["ok"]:
        summary["error"] = "NyankoFace MCP protocol check did not satisfy the expected response contract"
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        raise SystemExit(2)


def forgejo_request(
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
    authenticated: bool = False,
) -> object:
    endpoint_errors = _endpoint_errors("NYANKOFACE_FORGEJO_URL", FORGEJO_URL, "/git")
    if endpoint_errors:
        raise RuntimeError("; ".join(endpoint_errors) + "; run `nyankoface.py preflight --mode write`")
    headers: dict[str, str] = {}
    if authenticated:
        headers["Authorization"] = f"token {read_forgejo_token()}"
    try:
        return request_json(path, method=method, headers=headers, payload=payload, base_url=FORGEJO_URL)
    except RuntimeError as exc:
        raise RuntimeError(f"Forgejo content operation failed: {exc}") from exc


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
    if AGENT_KEY:
        return AGENT_KEY
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
    if AGENT_KEY:
        return True
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
                "forgejo_url": FORGEJO_URL,
                "mcp_url": MCP_URL,
                "forgejo_token_file": FORGEJO_TOKEN_FILE,
                "mcp_credential_source": "NYANKOFACE_FORGEJO_TOKEN_FILE",
                "forgejo_token_configured": forgejo_token_available(),
                "github_repository": GITHUB_REPO,
                "github_url": GITHUB_URL,
                "github_issues_url": GITHUB_ISSUES_URL,
                "operator_local_checkout_configured": bool(LOCAL_PATH),
                "operator_ssh_mirror_configured": bool(SSH_TARGET),
                "character_agent_key_configured": agent_key_configured(),
                "forgejo_user_configured": bool(FORGEJO_USER),
                "forgejo_content_token_configured": bool(FORGEJO_TOKEN) or Path(FORGEJO_TOKEN_FILE).is_file(),
                "canonical_data_plane": "NyankoFace catalog backed by Forgejo repositories",
                "publish_mode": "native Forgejo Git/API using the agent's own least-privilege identity",
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
                "surfaces": list(ARTIFACT_KINDS),
                "canonical_unit": "Forgejo repository with real files, topics, history, and permissions",
                "repository_contract": {
                    "knowledge": "articles/*.md with frontmatter and doc topic",
                    "skill": "root SKILL.md with name and description frontmatter",
                    "space": "Dockerfile listening on 0.0.0.0:7860 or README external_url",
                    "mcp": "README, dependency manifest, and runnable server entrypoint",
                    "prompt": "root PROMPT.md plus immutable version tag",
                    "automation": "runnable automation files and declared dependencies",
                    "model": "model files or a documented external artifact with provenance",
                    "dataset": "dataset files or a documented source and schema",
                    "character": "character definition and at least one runtime-readable format",
                    "benchmark": "benchmark definition, runner, and reproducible result evidence",
                    "pages": "publishable site root; Pages is an additional surface, not a repository topic",
                },
                "publish_boundary": "durable artifacts are committed to Forgejo; local drafts are only a recovery buffer",
                "secret_policy": "keys, passwords, tokens, and private keys are rejected",
                "issue_reporting": {
                    "kinds": list(REPORT_KINDS),
                    "command": "nyankoface.py report",
                    "destination": GITHUB_ISSUES_URL,
                    "publication": "github-issues.py publishes directly when the separate Issue secret is available",
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
        "publication": "recovery-only-not-published",
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


def forgejo_repository(args: argparse.Namespace) -> None:
    owner = urllib.parse.quote(args.owner, safe="")
    repo = urllib.parse.quote(args.repo, safe="")
    result = forgejo_request(f"api/v1/repos/{owner}/{repo}", authenticated=forgejo_token_available())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def forgejo_file(args: argparse.Namespace) -> None:
    owner = urllib.parse.quote(args.owner, safe="")
    repo = urllib.parse.quote(args.repo, safe="")
    encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in args.path.split("/"))
    query = f"?ref={urllib.parse.quote(args.ref, safe='')}" if args.ref else ""
    result = forgejo_request(
        f"api/v1/repos/{owner}/{repo}/contents/{encoded_path}{query}",
        authenticated=forgejo_token_available(),
    )
    if isinstance(result, dict) and result.get("type") == "file" and args.raw:
        if result.get("encoding") != "base64" or not isinstance(result.get("content"), str):
            raise RuntimeError("Forgejo returned an unsupported file encoding")
        try:
            content = base64.b64decode(result["content"], validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("Forgejo file is not valid UTF-8 text") from exc
        if len(content.encode("utf-8")) > 1024 * 1024:
            raise RuntimeError("Forgejo file exceeds the 1 MiB read limit")
        print(content, end="")
        return
    if isinstance(result, list):
        result = [
            {"name": item.get("name"), "type": item.get("type"), "path": item.get("path"), "size": item.get("size")}
            for item in result
            if isinstance(item, dict)
        ]
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def forgejo_create_repository(args: argparse.Namespace) -> None:
    if not SAFE_SLUG.fullmatch(args.name):
        raise RuntimeError("repository name must contain lowercase letters, numbers, and hyphens")
    payload = {
        "name": args.name,
        "description": args.description.strip(),
        "private": bool(args.private),
        "auto_init": True,
        "default_branch": args.branch,
    }
    result = forgejo_request("api/v1/user/repos", method="POST", payload=payload, authenticated=True)
    print(json.dumps({"created": True, "repository": result.get("full_name") if isinstance(result, dict) else None}, ensure_ascii=False, indent=2))


def forgejo_set_topics(args: argparse.Namespace) -> None:
    if not SAFE_SLUG.fullmatch(args.owner) or not SAFE_SLUG.fullmatch(args.repo):
        raise RuntimeError("owner and repo must be lowercase hyphenated slugs")
    topics = []
    for topic in args.topics:
        if not SAFE_SLUG.fullmatch(topic):
            raise RuntimeError(f"topic must be a lowercase hyphenated slug: {topic}")
        if topic not in topics:
            topics.append(topic)
    result = forgejo_request(
        f"api/v1/repos/{urllib.parse.quote(args.owner, safe='')}/{urllib.parse.quote(args.repo, safe='')}/topics",
        method="PUT",
        payload={"topics": topics},
        authenticated=True,
    )
    returned = result.get("topics", topics) if isinstance(result, dict) else topics
    print(json.dumps({"updated": True, "repository": f"{args.owner}/{args.repo}", "topics": returned}, ensure_ascii=False, indent=2))


def forgejo_publish_file(args: argparse.Namespace) -> None:
    if not SAFE_SLUG.fullmatch(args.owner) or not SAFE_SLUG.fullmatch(args.repo):
        raise RuntimeError("owner and repo must be lowercase hyphenated slugs")
    if not args.path or args.path.startswith("/") or ".." in Path(args.path).parts:
        raise RuntimeError("repository path must be relative and must not traverse parent directories")
    try:
        content = Path(args.body_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"content file could not be read: {args.body_file}") from exc
    if not content.strip():
        raise RuntimeError("content must not be empty")
    if len(content.encode("utf-8")) > 1024 * 1024:
        raise RuntimeError("content exceeds the 1 MiB write limit")
    if SECRET_SHAPES.search(content):
        raise RuntimeError("content resembles a credential; remove secrets before publishing")

    owner_q = urllib.parse.quote(args.owner, safe="")
    repo_q = urllib.parse.quote(args.repo, safe="")
    path_q = "/".join(urllib.parse.quote(part, safe="") for part in args.path.split("/"))
    current: object | None = None
    try:
        current = forgejo_request(
            f"api/v1/repos/{owner_q}/{repo_q}/contents/{path_q}?ref={urllib.parse.quote(args.branch, safe='')}"
        )
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
    if isinstance(current, dict) and current.get("type") == "file":
        existing_content = ""
        if current.get("encoding") == "base64" and isinstance(current.get("content"), str):
            try:
                existing_content = base64.b64decode(current["content"], validate=False).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                existing_content = ""
        if existing_content == content:
            print(json.dumps({"published": False, "unchanged": True, "repository": f"{args.owner}/{args.repo}", "path": args.path}, ensure_ascii=False))
            return

    payload: dict[str, object] = {
        "message": args.message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": args.branch,
    }
    method = "POST"
    if isinstance(current, dict) and current.get("sha"):
        payload["sha"] = current["sha"]
        method = "PUT"
    result = forgejo_request(
        f"api/v1/repos/{owner_q}/{repo_q}/contents/{path_q}",
        method=method,
        payload=payload,
        authenticated=True,
    )
    commit = result.get("commit") if isinstance(result, dict) else {}
    print(json.dumps({"published": True, "repository": f"{args.owner}/{args.repo}", "path": args.path, "commit": commit.get("sha") if isinstance(commit, dict) else None, "public_url": f"{BASE_URL}/{args.owner}/{args.repo}"}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    source_parser = sub.add_parser("source")
    source_parser.set_defaults(handler=source)

    preflight_parser = sub.add_parser(
        "preflight",
        help="validate endpoint paths and local credentials before using the client",
    )
    preflight_parser.add_argument("--mode", choices=("read", "write", "metrics"), default="write")
    preflight_parser.set_defaults(handler=preflight)

    mcp = sub.add_parser("mcp-check")
    mcp.set_defaults(handler=mcp_check)

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

    repo = sub.add_parser("repo")
    repo.add_argument("--owner", required=True)
    repo.add_argument("--repo", required=True)
    repo.set_defaults(handler=forgejo_repository)

    file_parser = sub.add_parser("file")
    file_parser.add_argument("--owner", required=True)
    file_parser.add_argument("--repo", required=True)
    file_parser.add_argument("--path", required=True)
    file_parser.add_argument("--ref")
    file_parser.add_argument("--raw", action="store_true")
    file_parser.set_defaults(handler=forgejo_file)

    create_repo = sub.add_parser("create-repo")
    create_repo.add_argument("--name", required=True)
    create_repo.add_argument("--description", default="")
    create_repo.add_argument("--branch", default="main")
    create_repo.add_argument("--private", action="store_true")
    create_repo.set_defaults(handler=forgejo_create_repository)

    topics = sub.add_parser("set-topics")
    topics.add_argument("--owner", required=True)
    topics.add_argument("--repo", required=True)
    topics.add_argument("--topics", nargs="+", required=True)
    topics.set_defaults(handler=forgejo_set_topics)

    publish_file = sub.add_parser("publish-file")
    publish_file.add_argument("--owner", required=True)
    publish_file.add_argument("--repo", required=True)
    publish_file.add_argument("--path", required=True)
    publish_file.add_argument("--body-file", required=True)
    publish_file.add_argument("--message", default="Publish reusable NyankoFace artifact")
    publish_file.add_argument("--branch", default="main")
    publish_file.set_defaults(handler=forgejo_publish_file)

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
