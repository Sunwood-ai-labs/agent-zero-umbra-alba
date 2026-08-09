#!/usr/bin/env python3
"""Small, safe NyankoFace public-reader and optional agent-metrics client."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
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
LOCAL_PATH = os.environ.get("NYANKOFACE_LOCAL_PATH", "")
SSH_TARGET = os.environ.get("NYANKOFACE_SSH_TARGET", "")
AGENT_KEY_FILE = os.environ.get(
    "NYANKOFACE_AGENT_API_KEY_FILE", "/opt/data/nyankoface-agent-api-key"
)
AGENT_SLUG = os.environ.get("NYANKOFACE_AGENT_SLUG", "character")


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
                "operator_local_checkout_configured": bool(LOCAL_PATH),
                "operator_ssh_mirror_configured": bool(SSH_TARGET),
                "character_agent_key_configured": agent_key_configured(),
            },
            ensure_ascii=False,
            indent=2,
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
