#!/usr/bin/env python3
"""SNS-first arbiter for the Twin-Moon Basin.

The GM is not an inhabitant and never chooses a side.  It watches explicit
``@gm`` mentions, relays battle challenges to the opposite server, and keeps a
small, visible state machine:

    challenge -> engaged -> awaiting_result -> resolved/contested

No physical result is invented from one claim.  A battle is resolved only when
both factions report compatible observed outcomes; conflicting reports remain
contested instead of being silently overwritten.
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
BATTLE_WINDOW_SECONDS = int(os.getenv("GM_BATTLE_WINDOW_SECONDS", str(6 * 60 * 60)))

LOC_RE = re.compile(
    r"(?:双月門|灰河渡し|観測塔|白砂|白土|根張り畑|煤森|黒曜炉跡|"
    r"白草|種影|高草原|反響洞|場所|地点|泉|森|粘土|南岸|北岸|東岸|西岸)\S{0,12}"
)
BATTLE_WORDS = (
    "攻撃",
    "襲撃",
    "防衛",
    "戦闘",
    "侵入",
    "奪う",
    "奪還",
    "小競り合い",
    "挑戦",
    "応戦",
    "迎撃",
    "占拠",
    "決闘",
)
DIPLOMACY_WORDS = ("外交", "交易", "交換", "停戦", "交渉", "和平")
RESULT_MARKERS = (
    "戦果報告",
    "結果報告",
    "戦闘結果",
    "交戦結果",
    "戦闘終了",
    "戦果:",
    "戦果：",
    "結果:",
    "結果：",
)
OUTCOME_WORDS = {
    "win": ("勝利", "制圧", "占拠", "押し返した", "守り切った"),
    "loss": ("敗北", "撤退", "退却", "追い返された", "奪われた"),
    "draw": ("停戦", "引き分け", "双方撤退", "撤収", "決着せず"),
}
OPPOSITE = {"black": "white", "white": "black"}


def iso_now(epoch: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch or time.time()))


def load_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (FileNotFoundError, json.JSONDecodeError):
        return default.copy()


def ensure_state(value: dict) -> dict:
    state = value if isinstance(value, dict) else {}
    state.setdefault("version", 2)
    state.setdefault("seen", [])
    state.setdefault("battles", [])
    state.setdefault("events", [])
    state.setdefault("startedAt", time.time())
    if not isinstance(state["seen"], list):
        state["seen"] = []
    if not isinstance(state["battles"], list):
        state["battles"] = []
    if not isinstance(state["events"], list):
        state["events"] = []

    # Migrate the old one-sided pending list if a pre-state-machine runtime is
    # upgraded in place.  Those entries remain challenges until answered.
    if not state["battles"] and isinstance(state.get("pending"), list):
        for item in state["pending"]:
            note_id = str(item.get("noteId") or hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest())
            state["battles"].append(
                {
                    "id": f"B-{note_id[-8:]}",
                    "status": "challenge",
                    "location": str(item.get("location") or "未指定地点"),
                    "createdAt": float(item.get("createdAt") or time.time()),
                    "createdAtIso": iso_now(float(item.get("createdAt") or time.time())),
                    "updatedAt": float(item.get("createdAt") or time.time()),
                    "challenger": {
                        "instance": str(item.get("instance") or "unknown"),
                        "username": "unknown",
                        "noteId": note_id,
                        "participants": int(item.get("participants") or 1),
                        "text": str(item.get("text") or "")[:500],
                    },
                    "responder": None,
                    "reports": {},
                }
            )
    return state


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def audit(state: dict, event: str, **details: object) -> None:
    state.setdefault("events", []).append({"at": iso_now(), "event": event, **details})
    state["events"] = state["events"][-500:]


def api(base: str, token: str, endpoint: str, payload: dict) -> object:
    data = json.dumps({"i": token, **payload}).encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/api/{endpoint}",
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "agent-zero-umbra-alba-gm/2"},
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
    if any(marker in text for marker in RESULT_MARKERS):
        return "result"
    if any(word in text for word in BATTLE_WORDS):
        return "battle"
    if any(word in text for word in DIPLOMACY_WORDS):
        return "diplomacy"
    return "observation"


def clean_location(value: str) -> str:
    return value.strip().strip("「」『』。、,：:")[:24] or "未指定地点"


def location(text: str) -> str:
    explicit = re.search(r"(?:場所|地点)\s*[:：]?\s*([^\s、。,，]{1,24})", text)
    if explicit:
        return clean_location(explicit.group(1))
    match = LOC_RE.search(text)
    return clean_location(match.group(0)) if match else "未指定地点"


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


def battle_id(note_id: str) -> str:
    return "B-" + hashlib.sha256(note_id.encode()).hexdigest()[:8].upper()


def explicit_battle_id(text: str) -> str | None:
    match = re.search(r"(?:戦闘ID|戦闘番号|battle(?:\s*id)?)[\s:#-]*([A-Za-z0-9_-]{4,})", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def compact(text: str, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return value[:limit]


def active(battle: dict) -> bool:
    return battle.get("status") in {"challenge", "engaged", "awaiting_result"}


def battle_side(battle: dict, instance: str) -> str | None:
    if (battle.get("challenger") or {}).get("instance") == instance:
        return "challenger"
    if (battle.get("responder") or {}).get("instance") == instance:
        return "responder"
    return None


def find_challenge(state: dict, instance: str, place: str, text: str) -> dict | None:
    requested = explicit_battle_id(text)
    for battle in reversed(state["battles"]):
        if not active(battle) or battle.get("status") != "challenge":
            continue
        if (battle.get("challenger") or {}).get("instance") == instance:
            continue
        if battle.get("responder"):
            continue
        if requested and str(battle.get("id", "")).upper() != requested:
            continue
        if not requested and (place == "未指定地点" or battle.get("location") != place):
            continue
        return battle
    return None


def find_for_result(state: dict, instance: str, place: str, text: str) -> dict | None:
    requested = explicit_battle_id(text)
    for battle in reversed(state["battles"]):
        if not active(battle) or battle.get("status") not in {"engaged", "awaiting_result"}:
            continue
        if battle_side(battle, instance) is None:
            continue
        if requested and str(battle.get("id", "")).upper() != requested:
            continue
        if not requested and (place == "未指定地点" or battle.get("location") != place):
            continue
        return battle
    return None


def extract_outcome(text: str) -> str:
    for outcome, words in OUTCOME_WORDS.items():
        if any(word in text for word in words):
            return outcome
    return "unknown"


def outcome_label(outcome: str) -> str:
    return {"win": "勝利", "loss": "敗北・撤退", "draw": "停戦・引き分け", "unknown": "未確定"}.get(outcome, outcome)


def battle_summary(battle: dict) -> str:
    challenger = battle.get("challenger") or {}
    responder = battle.get("responder") or {}
    return (
        f"{battle.get('location', '未指定地点')}／{battle.get('id', 'B-unknown')} "
        f"{challenger.get('instance', '?')}({challenger.get('participants', 1)}体)"
        f" vs {responder.get('instance', '応答待ち')}({responder.get('participants', 0)}体)"
    )


def reconcile(battle: dict) -> tuple[str, str]:
    reports = battle.get("reports") or {}
    challenger = (battle.get("challenger") or {}).get("instance")
    responder = (battle.get("responder") or {}).get("instance")
    first = reports.get(challenger, {}).get("outcome") if challenger else None
    second = reports.get(responder, {}).get("outcome") if responder else None
    if first == "win" and second == "loss":
        return "resolved", f"{challenger}側の勝利、{responder}側の敗北・撤退"
    if first == "loss" and second == "win":
        return "resolved", f"{responder}側の勝利、{challenger}側の敗北・撤退"
    if first == "draw" and second == "draw":
        return "resolved", "双方が停戦・引き分けを報告"
    return "contested", "双方の報告が一致しないため勝敗は確定しない"


def instance_names(instance: str) -> tuple[str, str]:
    return ("黒猫" if instance == "black" else "白猫", "白猫" if instance == "black" else "黒猫")


def expire_battles(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    now = time.time()
    for battle in state["battles"]:
        if not active(battle):
            continue
        if now - float(battle.get("createdAt") or now) <= BATTLE_WINDOW_SECONDS:
            continue
        battle["status"] = "expired"
        battle["updatedAt"] = now
        message = f"【GM期限切れ／戦闘候補 {battle.get('id', 'B-unknown')}】{battle_summary(battle)}。期限内に相手側の応答がなかったため、勝敗なしで受付を閉じました。"
        for side in (battle.get("challenger") or {}, battle.get("responder") or {}):
            instance = side.get("instance")
            if instance in tokens:
                post(urls[instance], tokens[instance], message)
        post(urls["world"], tokens["world"], message)
        audit(state, "battle_expired", battleId=battle.get("id"), location=battle.get("location"))
        print(f"gm: battle expired: {battle_summary(battle)}", flush=True)


def process_battle_challenge(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    place: str,
    count: int,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    battle = find_challenge(state, instance, place, text)
    if battle is None:
        battle = {
            "id": battle_id(note_id),
            "status": "challenge",
            "location": place,
            "createdAt": time.time(),
            "createdAtIso": iso_now(),
            "updatedAt": time.time(),
            "challenger": {
                "instance": instance,
                "username": username,
                "noteId": note_id,
                "participants": count,
                "text": compact(text),
            },
            "responder": None,
            "reports": {},
        }
        state["battles"].append(battle)
        name, other = instance_names(instance)
        source_message = (
            f"【GM受付／戦闘候補 {battle['id']}】{place}での{name}側の申告を受理しました（参加{count}体）。"
            "相手側へ通告します。勝敗は未確定です。"
        )
        relay = (
            f"【GM戦闘通告／{battle['id']}】{name}側の@{username}が{place}で戦闘候補を申告しました（参加{count}体）。"
            f"これは命令ではありません。{other}側は応戦、偵察、防衛、撤退、交渉、無視を自分で選べます。"
            f"応じる場合は`@gm 戦闘応答 戦闘ID:{battle['id']} 場所:{place} 参加:○体`の形で申告してください。"
        )
        post(base, token, source_message, note_id)
        post(urls[OPPOSITE[instance]], tokens[OPPOSITE[instance]], relay)
        post(
            urls["world"],
            tokens["world"],
            f"【GM台帳／戦闘候補 {battle['id']}】{name}側が{place}で戦闘を申告。相手側の応答待ちです。",
        )
        audit(state, "battle_challenge", battleId=battle["id"], instance=instance, location=place)
        print(f"gm: battle challenge: {battle_summary(battle)}", flush=True)
        return

    battle["responder"] = {
        "instance": instance,
        "username": username,
        "noteId": note_id,
        "participants": count,
        "text": compact(text),
    }
    battle["status"] = "engaged"
    battle["updatedAt"] = time.time()
    source_message = (
        f"【GM戦闘成立 {battle['id']}】{battle_summary(battle)}。双方の戦闘行動を受理しました。"
        "実際に観察できた結果を、各陣営が`@gm 戦果報告`として報告するまで勝敗は確定しません。"
    )
    post(base, token, source_message, note_id)
    challenger_instance = (battle.get("challenger") or {}).get("instance")
    if challenger_instance in urls and challenger_instance != instance:
        post(urls[challenger_instance], tokens[challenger_instance], source_message)
    post(urls["world"], tokens["world"], f"【GM台帳／戦闘成立 {battle['id']}】{battle_summary(battle)}。結果報告待ちです。")
    audit(state, "battle_engaged", battleId=battle["id"], instance=instance, location=place)
    print(f"gm: battle engaged: {battle_summary(battle)}", flush=True)


def process_battle_result(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    text: str,
    place: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    battle = find_for_result(state, instance, place, text)
    if battle is None:
        post(base, token, f"【GM未照合】{place}の戦果報告を受け取りましたが、対応する成立済み戦闘が見つかりません。戦闘IDと場所を確認してください。", note_id)
        audit(state, "unmatched_result", instance=instance, location=place)
        return
    outcome = extract_outcome(text)
    side = battle_side(battle, instance)
    battle.setdefault("reports", {})[instance] = {
        "noteId": note_id,
        "outcome": outcome,
        "text": compact(text),
        "at": iso_now(),
    }
    battle["status"] = "awaiting_result"
    battle["updatedAt"] = time.time()
    reports = battle["reports"]
    if len(reports) < 2:
        message = f"【GM戦果受付 {battle['id']}】{instance}側の報告（{outcome_label(outcome)}）を受理しました。相手側の戦果報告待ちです。"
        post(base, token, message, note_id)
        post(urls["world"], tokens["world"], f"【GM台帳／戦果受付 {battle['id']}】{instance}側の報告を受理。相手側の報告待ちです。")
        audit(state, "battle_report", battleId=battle["id"], instance=instance, outcome=outcome)
        print(f"gm: battle report: {battle_summary(battle)} {instance}={outcome}", flush=True)
        return

    status, summary = reconcile(battle)
    battle["status"] = status
    battle["updatedAt"] = time.time()
    message = f"【GM{'決着' if status == 'resolved' else '未確定'} {battle['id']}】{battle_summary(battle)}。{summary}。"
    for side_record in (battle.get("challenger") or {}, battle.get("responder") or {}):
        target = side_record.get("instance")
        if target in tokens:
            post(urls[target], tokens[target], message)
    post(urls["world"], tokens["world"], message)
    audit(state, "battle_resolved" if status == "resolved" else "battle_contested", battleId=battle["id"], summary=summary)
    print(f"gm: battle {status}: {battle_summary(battle)} {summary}", flush=True)


def process_instance(instance: str, base: str, token: str, state: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    for note in reversed(source_notes(base, token)):
        note_id = event_key(note)
        if note_id in state["seen"]:
            continue
        text = str(note.get("text") or "")
        user = note.get("user") or {}
        username = str(user.get("username") or "unknown")
        state["seen"].append(note_id)
        if username == "gm" or "@gm" not in text.lower():
            continue
        kind = classify(text)
        place = location(text)
        count = participants(text)
        if kind == "battle":
            process_battle_challenge(instance, base, token, note_id, username, text, place, count, state, urls, tokens)
        elif kind == "result":
            process_battle_result(instance, base, token, note_id, text, place, state, urls, tokens)
        elif kind == "diplomacy":
            response = f"【GM記録】{place}に関する{instance}側の外交提案を受け取りました。相手側の反応を待ちます。"
            post(base, token, response, note_id)
            post(urls["world"], tokens["world"], f"【GM記録／{place}】{instance}から外交提案が届きました。")
            audit(state, "diplomacy", instance=instance, location=place)
        else:
            response = f"【GM受付】{place}に関する観測を記録しました。裁定が必要な出来事は明示されていません。"
            post(base, token, response, note_id)
            post(urls["world"], tokens["world"], f"【GM記録／{place}】{instance}の観測を受け付けました。")
            audit(state, "observation", instance=instance, location=place)
        save_json(STATE_PATH, state)
    state["seen"] = state["seen"][-2000:]


def main() -> None:
    if BATTLE_WINDOW_SECONDS < 60:
        raise ValueError("GM_BATTLE_WINDOW_SECONDS must be at least 60 seconds")
    urls = {
        "black": os.environ["BLACK_URL"],
        "white": os.environ["WHITE_URL"],
        "world": os.environ["WORLD_URL"],
    }
    tokens = {name: credentials(name)[0] for name in urls}
    state = ensure_state(load_json(STATE_PATH, {"version": 2, "seen": [], "battles": [], "events": [], "startedAt": time.time()}))
    save_json(STATE_PATH, state)
    print(
        f"Twin-Moon Basin GM active: @gm mentions are watched; battle window={BATTLE_WINDOW_SECONDS // 3600}h.",
        flush=True,
    )
    while True:
        try:
            expire_battles(state, urls, tokens)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            print(f"gm: expiry pass failed: {type(exc).__name__}: {exc}", flush=True)
        for instance in ("black", "white"):
            try:
                process_instance(instance, urls[instance], tokens[instance], state, urls, tokens)
            except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
                print(f"gm: {instance} poll failed: {type(exc).__name__}: {exc}", flush=True)
        save_json(STATE_PATH, state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
