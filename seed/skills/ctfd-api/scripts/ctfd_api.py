#!/usr/bin/env python3
"""Small dependency-free CTFd API client used inside each Hermes agent.

The client deliberately keeps the token in a file and emits only safe API
metadata. Challenge creation and flag creation happen from the agent
container; the GM only audits the returned numeric challenge ID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


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


def load_config() -> dict[str, Any]:
    path = Path(os.environ.get("CTFD_API_CONFIG_FILE", "/opt/data/ctfd-api.json"))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"missing CTFd config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid CTFd config: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("CTFd config must be a JSON object")
    return value


CONFIG = load_config()
API_URL = (os.environ.get("CTFD_API_URL") or str(CONFIG.get("api_url") or "")).rstrip("/")
BASE_URL = (os.environ.get("CTFD_BASE_URL") or str(CONFIG.get("base_url") or "")).rstrip("/")
TOKEN_FILE = Path(
    os.environ.get("CTFD_API_TOKEN_FILE")
    or str(CONFIG.get("token_file") or "/opt/data/ctfd-api-token")
)
FACTION = str(CONFIG.get("faction") or os.environ.get("CTFD_FACTION") or "").strip()
BANK = str(CONFIG.get("bank") or "").strip()
TIMEOUT = int(CONFIG.get("timeout_seconds") or os.environ.get("CTFD_API_TIMEOUT", "20"))
MIN_DIFFICULTY = (os.environ.get("CTFD_MIN_DIFFICULTY", "hard").strip().lower() or "hard")
MIN_STAGES = max(3, int(os.environ.get("CTFD_MIN_STAGES", "3")))
DIFFICULTY_RANK = {"easy": 1, "medium": 2, "hard": 3}
DIFFICULTY_POINTS = {"easy": 50, "medium": 100, "hard": 150}
TRIVIAL_MARKERS = ("flag.txt", "cat flag", "cat /flag", "print(flag", "echo $flag", "直接表示", "そのまま表示")
CONTINUITY_SYSTEM_MARKERS = ("水循環", "食料再生産", "居住防護", "記録制御", "防御知識")
CONTINUITY_EVIDENCE_MARKERS = ("影響", "封じ込め", "修復", "伝達")


def token() -> str:
    value = os.environ.get("CTFD_API_TOKEN", "").strip()
    if not value:
        try:
            value = TOKEN_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise RuntimeError(f"missing CTFd API token file: {TOKEN_FILE}") from exc
    if not value:
        raise RuntimeError("CTFd API token is empty")
    return value


def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    if not API_URL:
        raise RuntimeError("CTFd API URL is not configured")
    url = f"{API_URL}/{path.lstrip('/')}"
    body = None
    headers = {
        "Accept": "application/json",
        # CTFd's token middleware only authenticates JSON API requests. Keep
        # this header on GETs as well as writes; otherwise an admin token is
        # ignored and the browser HTML fallback is returned.
        "Content-Type": "application/json",
        "Authorization": f"Token {token()}",
        "User-Agent": "agent-zero-umbra-alba-ctfd-agent/1",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"CTFd returned non-JSON from {path}") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"CTFd API HTTP {exc.code} at {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"CTFd API connection failed at {path}: {exc.reason}") from exc


def require_success(response: Any, operation: str) -> dict[str, Any]:
    if not isinstance(response, dict) or response.get("success") is not True:
        raise RuntimeError(f"CTFd {operation} failed: {json.dumps(response, ensure_ascii=False)[:800]}")
    data = response.get("data")
    return data if isinstance(data, dict) else {"value": data}


def preflight(_: argparse.Namespace) -> None:
    # This is an admin-only endpoint, so a 200 proves both reachability and
    # that the per-agent token has the permission required for creation.
    data = require_success(api_request("GET", "/challenges/types"), "preflight")
    print(json.dumps({
        "ok": True,
        "faction": FACTION,
        "bank": BANK,
        "api_url": API_URL,
        "base_url": BASE_URL,
        "challenge_types": sorted(data.keys()),
    }, ensure_ascii=False))


def read_text_argument(value: str | None, file_value: str | None, label: str) -> str:
    if bool(value) == bool(file_value):
        raise RuntimeError(f"provide exactly one of --{label} or --{label}-file")
    if file_value:
        return Path(file_value).read_text(encoding="utf-8").strip()
    return str(value or "").strip()


def list_challenges() -> list[dict[str, Any]]:
    response = api_request("GET", "/challenges")
    if not isinstance(response, dict) or response.get("success") is not True:
        raise RuntimeError(f"CTFd list failed: {json.dumps(response, ensure_ascii=False)[:800]}")
    data = response.get("data")
    return data if isinstance(data, list) else []


def challenge_by_name(name: str) -> dict[str, Any] | None:
    for challenge in list_challenges():
        if str(challenge.get("name") or "") == name:
            return challenge
    return None


def validate_challenge_contract(description: str, difficulty: str) -> None:
    tier = difficulty.strip().lower()
    if tier not in DIFFICULTY_RANK:
        raise RuntimeError("difficulty must be easy, medium, or hard")
    minimum = MIN_DIFFICULTY if MIN_DIFFICULTY in DIFFICULTY_RANK else "hard"
    if DIFFICULTY_RANK[tier] < DIFFICULTY_RANK[minimum]:
        raise RuntimeError(f"new security challenges require {minimum} or harder; easy is legacy-only")
    if len(description) < 80 or not re.search(r"flag|フラグ", description, re.IGNORECASE):
        raise RuntimeError("challenge description must be at least 80 characters and state the flag objective")
    stages = set(re.findall(r"(?:段階|stage|step|ステップ)\s*([1-9])", description, re.IGNORECASE))
    if len(stages) < MIN_STAGES:
        raise RuntimeError(f"challenge description must include stages 1-{MIN_STAGES}")
    if not any(marker in description for marker in CONTINUITY_SYSTEM_MARKERS):
        raise RuntimeError("challenge must name one continuity system: 水循環/食料再生産/居住防護/記録制御/防御知識")
    missing_evidence = [marker for marker in CONTINUITY_EVIDENCE_MARKERS if marker not in description]
    if missing_evidence:
        raise RuntimeError(f"challenge must document failure impact, containment, repair, and transfer; missing {','.join(missing_evidence)}")
    lowered = description.casefold()
    if any(marker.casefold() in lowered for marker in TRIVIAL_MARKERS):
        raise RuntimeError("direct flag-file disclosure is not an acceptable competitive challenge")


def create(args: argparse.Namespace) -> None:
    name = args.name.strip()
    description = read_text_argument(args.description, args.description_file, "description")
    flag = read_text_argument(args.flag, args.flag_file, "flag")
    category = args.category.strip().lower()
    if not name or len(name) > 80:
        raise RuntimeError("challenge name must be 1-80 characters")
    difficulty = args.difficulty.strip().lower()
    validate_challenge_contract(description, difficulty)
    if not flag:
        raise RuntimeError("challenge flag must not be empty")
    if re.search(r"flag\s*\{", description, re.IGNORECASE) or flag in description:
        raise RuntimeError("challenge description must not contain the flag")
    if category not in {"web", "crypto", "pwn", "rev", "forensics", "osint", "misc", "cloud", "mobile"}:
        raise RuntimeError("unsupported security category")
    description = f"{description}\n\n難易度:{difficulty}"
    value = int(args.value) if args.value is not None else DIFFICULTY_POINTS[difficulty]
    if value < DIFFICULTY_POINTS[difficulty]:
        raise RuntimeError(f"value for {difficulty} must be at least {DIFFICULTY_POINTS[difficulty]}")
    existing = challenge_by_name(name)
    created = False
    if existing:
        challenge_id = int(existing["id"])
        challenge = existing
    else:
        payload = {
            "name": name,
            "description": description,
            "category": category,
            "type": "standard",
            "state": "visible",
            "logic": "any",
            "function": "static",
            "value": value,
        }
        challenge = require_success(api_request("POST", "/challenges", payload), "challenge creation")
        try:
            challenge_id = int(challenge["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"CTFd did not return a challenge ID: {challenge}") from exc
        created = True

    flags = api_request("GET", f"/challenges/{challenge_id}/flags")
    existing_flags = flags.get("data") if isinstance(flags, dict) else []
    flag_created = False
    if not any(str(item.get("content") or "") == flag for item in (existing_flags or []) if isinstance(item, dict)):
        require_success(api_request("POST", "/flags", {
            "challenge_id": challenge_id,
            "type": "static",
            "content": flag,
            "data": "",
        }), "flag creation")
        flag_created = True
    result = {
        "ok": True,
        "created": created,
        "flag_created": flag_created,
        "faction": FACTION,
        "bank": BANK,
        "challenge_id": challenge_id,
        "challenge_url": f"{BASE_URL}/challenges/{challenge_id}" if BASE_URL else None,
        "name": name,
        "category": category,
        "value": value,
        "difficulty": difficulty,
    }
    print(json.dumps(result, ensure_ascii=False))


def list_command(_: argparse.Namespace) -> None:
    print(json.dumps({"ok": True, "faction": FACTION, "bank": BANK, "challenges": list_challenges()}, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--description-file")
    create_parser.add_argument("--category", required=True)
    create_parser.add_argument("--difficulty", choices=("easy", "medium", "hard"), default="hard")
    create_parser.add_argument("--flag")
    create_parser.add_argument("--flag-file")
    create_parser.add_argument("--value", type=int)
    sub.add_parser("list")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        {"preflight": preflight, "create": create, "list": list_command}[args.command](args)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"ctfd-api: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
