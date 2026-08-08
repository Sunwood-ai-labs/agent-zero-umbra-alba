#!/usr/bin/env python3
"""SNS-first arbiter for the black/white civilization prototype.

The arbiter never speaks as an inhabitant. It watches each faction timeline for
an explicit @gm mention, acknowledges the request on the source server, and
mirrors a compact world record to the neutral server. Battle resolution is
deliberately conservative: a single request becomes a pending event until the
opposite faction makes a matching request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


STATE_DIR = Path(os.getenv("GM_STATE_DIR", "/state/gm"))
STATE_PATH = STATE_DIR / "events.json"
POLL_SECONDS = int(os.getenv("GM_POLL_SECONDS", "10"))
LOC_RE = re.compile(r"(?:双月門|灰河渡し|観測塔|場所|地点|泉|森|粘土|白砂|白土|根張り|煤森|南岸|北岸|東岸|西岸)\S{0,12}")
BATTLE_WORDS = ("攻撃", "襲撃", "防衛", "戦闘", "侵入", "奪う", "小競り合い")
DIPLOMACY_WORDS = ("外交", "交易", "交換", "停戦", "交渉", "和平")


def load_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (FileNotFoundError, json.JSONDecodeError):
        return default.copy()


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def api(base: str, token: str, endpoint: str, payload: dict) -> object:
    data = json.dumps({"i": token, **payload}).encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/api/{endpoint}",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "agent-zero-umbra-alba-gm/1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def credentials(instance: str) -> tuple[str, str]:
    record = load_json(Path("/state") / instance / "gm-credentials.json", {})
    token = str(record.get("token") or "")
    if not token:
        raise RuntimeError(f"missing @gm credentials for {instance}")
    return token, str(record.get("username") or "gm")


def classify(text: str) -> str:
    if any(word in text for word in BATTLE_WORDS):
        return "battle"
    if any(word in text for word in DIPLOMACY_WORDS):
        return "diplomacy"
    return "observation"


def location(text: str) -> str:
    match = LOC_RE.search(text)
    return match.group(0)[:24] if match else "未指定地点"


def participants(text: str) -> int:
    match = re.search(r"(\d+)\s*(?:人|体|匹)", text)
    return max(1, min(int(match.group(1)), 20)) if match else 1


def source_notes(base: str, token: str) -> list[dict]:
    value = api(base, token, "notes/local-timeline", {"limit": 100})
    return value if isinstance(value, list) else []


def post(base: str, token: str, text: str, reply_id: str | None = None) -> None:
    payload = {"text": text, "visibility": "public"}
    if reply_id:
        payload["replyId"] = reply_id
    api(base, token, "notes/create", payload)


def event_key(note: dict) -> str:
    return str(note.get("id") or hashlib.sha256(json.dumps(note, sort_keys=True).encode()).hexdigest())


def process_instance(instance: str, base: str, token: str, state: dict, world_base: str, world_token: str) -> None:
    for note in reversed(source_notes(base, token)):
        note_id = event_key(note)
        if note_id in state["seen"]:
            continue
        state["seen"].append(note_id)
        text = str(note.get("text") or "")
        user = note.get("user") or {}
        username = str(user.get("username") or "unknown")
        if username == "gm" or "@gm" not in text.lower():
            continue
        kind = classify(text)
        place = location(text)
        count = participants(text)
        if kind == "battle":
            pending = state["pending"]
            pending.append({"instance": instance, "noteId": note_id, "location": place, "participants": count, "text": text[:500]})
            response = (
                f"【GM受付】{place}の戦闘候補を受け取りました。{instance}側の参加人数は{count}人。"
                "相手側の認識・防衛・交渉が記録されるまで、勝敗は確定しません。"
            )
            post(base, token, response, note_id)
            world_text = f"【GM受付／{place}】{instance}の@{username}が戦闘候補を申告。相手側の応答待ちです。"
        elif kind == "diplomacy":
            response = f"【GM記録】{place}に関する{instance}側の外交提案を受け取りました。相手側の反応を待ちます。"
            post(base, token, response, note_id)
            world_text = f"【GM記録／{place}】{instance}から外交提案が届きました。"
        else:
            response = f"【GM受付】{place}に関する観測を記録しました。裁定が必要な出来事は明示されていません。"
            post(base, token, response, note_id)
            world_text = f"【GM記録／{place}】{instance}の観測を受け付けました。"
        post(world_base, world_token, world_text)
        save_json(STATE_PATH, state)
    state["seen"] = state["seen"][-2000:]


def main() -> None:
    urls = {
        "black": os.environ["BLACK_URL"],
        "white": os.environ["WHITE_URL"],
        "world": os.environ["WORLD_URL"],
    }
    tokens = {name: credentials(name)[0] for name in urls}
    state = load_json(STATE_PATH, {"seen": [], "pending": [], "startedAt": time.time()})
    state.setdefault("seen", [])
    state.setdefault("pending", [])
    print("Twin-Moon Basin GM active: @gm mentions are being watched.", flush=True)
    while True:
        for instance in ("black", "white"):
            try:
                process_instance(instance, urls[instance], tokens[instance], state, urls["world"], tokens["world"])
            except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
                print(f"gm: {instance} poll failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
