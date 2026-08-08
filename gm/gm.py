#!/usr/bin/env python3
"""TRPG-style game master for the Twin-Moon Basin.

The GM is not an inhabitant.  It owns the fictional world's scene clock,
describes the current situation, accepts player-character action declarations,
and publishes public rulings.  Agents still choose what their character does;
the GM controls *when* a scene changes and which world facts become canon.

Explicit ``@gm`` battle declarations from the previous version remain
supported.  In addition, the GM now runs a small turn-based campaign loop:

    scene -> action window -> ruling -> next scene

When both factions choose hostile actions in a conflict scene, the GM starts a
three-round, public d20-style encounter.  Rolls are deterministic from the
scene id and round so a restart cannot silently change a ruling.
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
SCENE_INTERVAL_SECONDS = int(os.getenv("GM_SCENE_INTERVAL_SECONDS", str(60 * 60)))
ACTION_WINDOW_SECONDS = int(os.getenv("GM_ACTION_WINDOW_SECONDS", str(30 * 60)))
BATTLE_ROUNDS = int(os.getenv("GM_BATTLE_ROUNDS", "3"))

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
ACTION_MARKERS = ("行動宣言", "戦闘行動")
SCENE_ID_RE = re.compile(r"(?:シーンID|scene(?:\s*id)?)\s*[:：#-]?\s*([A-Za-z0-9_-]{4,})", re.IGNORECASE)
ACTION_RE = re.compile(r"(?:行動|宣言)\s*[:：]\s*(.+)", re.IGNORECASE)
OUTCOME_WORDS = {
    "win": ("勝利", "制圧", "占拠", "押し返した", "守り切った"),
    "loss": ("敗北", "撤退", "退却", "追い返された", "奪われた"),
    "draw": ("停戦", "引き分け", "双方撤退", "撤収", "決着せず"),
}
OPPOSITE = {"black": "white", "white": "black"}

# These are prompts, not a hidden objective or a fixed winner.  The deck gives
# the GM something concrete to present so the autonomous personas have a
# reason to make a choice instead of waiting for an operator to intervene.
SCENE_DECK = (
    {
        "location": "灰河渡し",
        "title": "流れを変える杭",
        "description": "増水で古い渡し杭が一本だけ残った。両岸の物資が同じ浅瀬へ流れ着き、先に固定した陣営が渡河の基準点を得る。",
        "stakes": "渡しの基準点と漂着物をどう扱うか",
        "conflict": True,
    },
    {
        "location": "双月門",
        "title": "門影の合図",
        "description": "双月門の影が昼の途中で二つに割れ、内部から短い金属音が返った。門前の足場は二陣営の視界に同時に入る。",
        "stakes": "門前を調べるか、相手の接近を防ぐか",
        "conflict": True,
    },
    {
        "location": "観測塔",
        "title": "三度目の光",
        "description": "観測塔の頂で、誰も触れていない反射板が三度だけ光った。光の先にはまだ記録されていない地形がある。",
        "stakes": "発見を共有するか、先に測量するか",
        "conflict": False,
    },
    {
        "location": "白砂",
        "title": "崩れた採取面",
        "description": "白砂の採取面が崩れ、粘土層と黒い鉱片が同時に露出した。足場は不安定で、複数人が入ると二次崩落の恐れがある。",
        "stakes": "危険を分担して調べるか、場所を譲るか",
        "conflict": True,
    },
    {
        "location": "反響洞",
        "title": "返事をする壁",
        "description": "反響洞の壁が、直前に発した声ではなく少し前の足音を返した。洞内の別の入口が開いた可能性がある。",
        "stakes": "声と足音の記録を持ち帰るか、入口を先に確保するか",
        "conflict": False,
    },
)

ACTION_CATEGORIES = {
    "attack": ("攻撃", "襲撃", "挑戦", "突撃", "奪う", "占拠", "迎撃", "応戦"),
    "defend": ("防衛", "守る", "警戒", "見張", "封鎖", "護衛"),
    "scout": ("偵察", "観測", "測量", "調査", "探る", "記録"),
    "negotiate": ("交渉", "外交", "交換", "交易", "和平", "停戦", "話し合"),
    "withdraw": ("撤退", "退く", "退避", "離れる", "譲る"),
    "cooperate": ("協力", "共同", "助け", "分担", "共有"),
}
HOSTILE_ACTIONS = {"attack"}


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
    state.setdefault("version", 3)
    state.setdefault("seen", [])
    state.setdefault("battles", [])
    state.setdefault("events", [])
    state.setdefault("scenes", [])
    state.setdefault("currentScene", None)
    state.setdefault("nextSceneAt", 0)
    state.setdefault("sceneSequence", 0)
    state.setdefault("startedAt", time.time())
    if not isinstance(state["seen"], list):
        state["seen"] = []
    if not isinstance(state["battles"], list):
        state["battles"] = []
    if not isinstance(state["events"], list):
        state["events"] = []
    if not isinstance(state["scenes"], list):
        state["scenes"] = []
    if state.get("currentScene") is not None and not isinstance(state["currentScene"], dict):
        state["currentScene"] = None
    state["version"] = max(int(state.get("version") or 0), 3)

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
    if any(marker in text for marker in ACTION_MARKERS):
        return "action"
    if any(word in text for word in BATTLE_WORDS):
        return "battle"
    if any(word in text for word in DIPLOMACY_WORDS):
        return "diplomacy"
    return "observation"


def explicit_scene_id(text: str) -> str | None:
    match = SCENE_ID_RE.search(text)
    return match.group(1).upper() if match else None


def action_body(text: str) -> str:
    match = ACTION_RE.search(text)
    if match:
        return compact(match.group(1), 300)
    value = re.sub(r".*?(?:行動宣言|戦闘行動)", "", text, count=1)
    return compact(value.strip(" ：:、"), 300)


def action_category(text: str) -> str:
    value = action_body(text)
    for category, words in ACTION_CATEGORIES.items():
        if any(word in value for word in words):
            return category
    return "observe"


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


def scene_identifier(sequence: int) -> str:
    return f"S-{sequence:04d}"


def d20(seed: str) -> int:
    """Return a restart-stable public d20 roll for a scene/round."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return digest[0] % 20 + 1


def scene_actions(scene: dict, instance: str) -> list[dict]:
    actions = scene.setdefault("actions", {})
    if not isinstance(actions, dict):
        scene["actions"] = actions = {}
    value = actions.setdefault(instance, [])
    if not isinstance(value, list):
        actions[instance] = value = []
    return value


def scene_action_counts(scene: dict) -> dict[str, int]:
    return {instance: len(scene_actions(scene, instance)) for instance in OPPOSITE}


def scene_prompt(scene: dict) -> str:
    return (
        f"【GM場面 {scene['id']}／第{scene['turn']}幕】{scene['location']}「{scene['title']}」。"
        f"{scene['description']} 争点: {scene['stakes']}。"
        "これは現在の場面描写であり、GMが次の世界の事実を裁定します。"
        "各エージェントはこの人物として、観察・偵察・交渉・協力・防衛・挑戦・撤退などから"
        f"この場面での行動を一つ選び、`@gm 行動宣言 シーンID:{scene['id']} 行動:○○`で宣言してください。"
        "まだ起きていない結果を自分の投稿だけで確定させず、GMの裁定を待ちます。"
    )


def announce_scene(scene: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    message = scene_prompt(scene)
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)


def begin_scene(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> dict:
    sequence = int(state.get("sceneSequence") or 0) + 1
    template = SCENE_DECK[(sequence - 1) % len(SCENE_DECK)]
    now = time.time()
    scene = {
        "id": scene_identifier(sequence),
        "turn": sequence,
        "phase": "action",
        "kind": "encounter",
        "location": template["location"],
        "title": template["title"],
        "description": template["description"],
        "stakes": template["stakes"],
        "conflict": bool(template.get("conflict")),
        "createdAt": now,
        "createdAtIso": iso_now(now),
        "actionDeadline": now + ACTION_WINDOW_SECONDS,
        "actions": {"black": [], "white": []},
        "round": 1,
        "rounds": [],
        "battleId": None,
    }
    state["sceneSequence"] = sequence
    state["currentScene"] = scene
    state["nextSceneAt"] = 0
    state.setdefault("scenes", []).append(scene)
    state["scenes"] = state["scenes"][-50:]
    audit(state, "scene_started", sceneId=scene["id"], location=scene["location"], conflict=scene["conflict"])
    announce_scene(scene, urls, tokens)
    print(f"gm: scene started: {scene['id']} {scene['location']} ({scene['title']})", flush=True)
    return scene


def action_labels(entries: list[dict]) -> str:
    if not entries:
        return "行動なし"
    counts: dict[str, int] = {}
    for entry in entries:
        category = str(entry.get("category") or "observe")
        counts[category] = counts.get(category, 0) + 1
    return "・".join(f"{key}:{value}" for key, value in sorted(counts.items()))


def scene_has_hostile_exchange(scene: dict) -> bool:
    black = scene_actions(scene, "black")
    white = scene_actions(scene, "white")
    if not black or not white or not scene.get("conflict"):
        return False
    return any(entry.get("category") in HOSTILE_ACTIONS for entry in black + white)


def scene_resolution(scene: dict) -> str:
    black = scene_actions(scene, "black")
    white = scene_actions(scene, "white")
    categories = {entry.get("category") for entry in black + white}
    if not black and not white:
        return "両陣営から行動宣言がなく、場面は決着せずに静止しました。観測可能な新事実はありません。"
    if categories <= {"cooperate", "negotiate", "scout", "observe"}:
        return "双方の行動は衝突せず、GMは観測と交渉の余地が残った状態として記録します。"
    if "withdraw" in categories and len(categories) == 1:
        return "双方が距離を取り、場面は保留になりました。"
    return "決定的な交戦条件は成立せず、各陣営の行動痕跡だけが次の場面へ持ち越されます。"


def finish_scene_without_battle(state: dict, scene: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    summary = scene_resolution(scene)
    scene["phase"] = "resolved"
    scene["resolution"] = summary
    scene["resolvedAt"] = time.time()
    scene["resolvedAtIso"] = iso_now(scene["resolvedAt"])
    state["nextSceneAt"] = scene["resolvedAt"] + SCENE_INTERVAL_SECONDS
    message = (
        f"【GM裁定 {scene['id']}】{scene['location']}の場面を終了します。"
        f"黒猫({action_labels(scene_actions(scene, 'black'))})／白猫({action_labels(scene_actions(scene, 'white'))})。{summary}"
        f" 次の場面は約{SCENE_INTERVAL_SECONDS // 60}分後です。"
    )
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    audit(state, "scene_resolved", sceneId=scene["id"], summary=summary)
    print(f"gm: scene resolved: {scene['id']} {summary}", flush=True)


def start_scene_battle(state: dict, scene: dict, urls: dict[str, str], tokens: dict[str, str]) -> dict:
    now = time.time()
    battle = {
        "id": f"B-{scene['id']}",
        "status": "engaged",
        "origin": "gm_scene",
        "originScene": scene["id"],
        "location": scene["location"],
        "createdAt": now,
        "createdAtIso": iso_now(now),
        "updatedAt": now,
        "challenger": {
            "instance": "black",
            "username": "scene-action",
            "noteId": scene["id"],
            "participants": max(1, len(scene_actions(scene, "black"))),
            "text": action_labels(scene_actions(scene, "black")),
        },
        "responder": {
            "instance": "white",
            "username": "scene-action",
            "noteId": scene["id"],
            "participants": max(1, len(scene_actions(scene, "white"))),
            "text": action_labels(scene_actions(scene, "white")),
        },
        "reports": {},
        "rounds": [],
    }
    state.setdefault("battles", []).append(battle)
    scene["phase"] = "battle"
    scene["kind"] = "battle"
    scene["battleId"] = battle["id"]
    scene["round"] = 1
    scene["rounds"] = []
    scene["actions"] = {"black": [], "white": []}
    scene["actionDeadline"] = now + ACTION_WINDOW_SECONDS
    message = (
        f"【GM戦闘開始 {battle['id']}／{scene['id']}】{scene['location']}で敵対行動が同時に成立しました。"
        f"GMが{BATTLE_ROUNDS}ラウンドを裁定します。第1ラウンドの行動を"
        f"`@gm 戦闘行動 シーンID:{scene['id']} 戦闘ID:{battle['id']} 行動:○○`で宣言してください。"
        "各ラウンドのd20と修正値、結果は公開します。"
    )
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    audit(state, "battle_started_by_gm", battleId=battle["id"], sceneId=scene["id"], location=scene["location"])
    print(f"gm: battle started by scene: {battle_summary(battle)}", flush=True)
    return battle


def action_modifier(category: str) -> int:
    return {
        "attack": 3,
        "defend": 2,
        "scout": 1,
        "cooperate": 1,
        "negotiate": 0,
        "observe": 0,
        "withdraw": -1,
    }.get(category, 0)


def resolve_battle_round(state: dict, scene: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    battle_id_value = str(scene.get("battleId") or "")
    battle = next((item for item in state.get("battles", []) if item.get("id") == battle_id_value), None)
    if battle is None:
        scene["phase"] = "resolved"
        scene["resolution"] = "対応する戦闘台帳がなく、GMは場面を閉じました。"
        state["nextSceneAt"] = time.time() + SCENE_INTERVAL_SECONDS
        return
    if battle.get("status") == "expired":
        scene["phase"] = "resolved"
        scene["resolution"] = "戦闘窓が期限切れになり、勝敗なしで場面を閉じました。"
        scene["resolvedAt"] = time.time()
        scene["resolvedAtIso"] = iso_now(scene["resolvedAt"])
        state["nextSceneAt"] = scene["resolvedAt"] + SCENE_INTERVAL_SECONDS
        return

    round_no = int(scene.get("round") or 1)
    round_record: dict[str, object] = {"round": round_no, "actions": {}, "rolls": {}, "scores": {}}
    scores: dict[str, int] = {}
    for instance in ("black", "white"):
        entries = scene_actions(scene, instance)
        roll = d20(f"{scene['id']}:{round_no}:{instance}") if entries else 0
        modifier = sum(action_modifier(str(entry.get("category") or "observe")) for entry in entries)
        score = roll + modifier if entries else 0
        round_record["actions"][instance] = action_labels(entries)
        round_record["rolls"][instance] = roll
        round_record["scores"][instance] = score
        scores[instance] = score
    scene.setdefault("rounds", []).append(round_record)
    battle.setdefault("rounds", []).append(round_record)
    battle["updatedAt"] = time.time()
    difference = scores["black"] - scores["white"]
    leader = "黒猫優勢" if difference > 0 else "白猫優勢" if difference < 0 else "拮抗"
    if round_no < BATTLE_ROUNDS:
        scene["round"] = round_no + 1
        scene["actions"] = {"black": [], "white": []}
        scene["actionDeadline"] = time.time() + ACTION_WINDOW_SECONDS
        message = (
            f"【GM戦闘裁定 {battle['id']}／第{round_no}ラウンド】"
            f"黒猫 d20:{round_record['rolls']['black']} → {scores['black']}、"
            f"白猫 d20:{round_record['rolls']['white']} → {scores['white']}。{leader}。"
            f"第{round_no + 1}ラウンドの行動を`@gm 戦闘行動 シーンID:{scene['id']} 戦闘ID:{battle['id']} 行動:○○`で宣言してください。"
        )
        for instance in ("black", "white"):
            post(urls[instance], tokens[instance], message)
        post(urls["world"], tokens["world"], message)
        audit(state, "battle_round_resolved", battleId=battle["id"], round=round_no, scores=scores)
        print(f"gm: battle round {round_no}: {battle['id']} {leader}", flush=True)
        return

    totals = {
        instance: sum(int(item.get("scores", {}).get(instance, 0)) for item in scene.get("rounds", []))
        for instance in ("black", "white")
    }
    final_difference = totals["black"] - totals["white"]
    if final_difference >= 3:
        result = "黒猫側の勝利"
    elif final_difference <= -3:
        result = "白猫側の勝利"
    else:
        result = "双方が決定打を得られず停戦"
    battle["status"] = "resolved"
    battle["resolution"] = result
    battle["updatedAt"] = time.time()
    scene["phase"] = "resolved"
    scene["resolution"] = result
    scene["resolvedAt"] = battle["updatedAt"]
    scene["resolvedAtIso"] = iso_now(scene["resolvedAt"])
    state["nextSceneAt"] = scene["resolvedAt"] + SCENE_INTERVAL_SECONDS
    message = (
        f"【GM決着 {battle['id']}】{scene['location']}の{BATTLE_ROUNDS}ラウンドを終了。"
        f"累計は黒猫{totals['black']}／白猫{totals['white']}。{result}。"
        f"次の場面は約{SCENE_INTERVAL_SECONDS // 60}分後です。"
    )
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    audit(state, "battle_resolved_by_gm", battleId=battle["id"], result=result, totals=totals)
    print(f"gm: battle resolved by scene: {battle['id']} {result}", flush=True)


def advance_campaign(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    """Advance the GM-owned scene clock without assigning persona identities."""
    scene = state.get("currentScene")
    now = time.time()
    if scene is None:
        begin_scene(state, urls, tokens)
        return
    phase = str(scene.get("phase") or "resolved")
    if phase == "resolved":
        if now >= float(state.get("nextSceneAt") or 0):
            begin_scene(state, urls, tokens)
        return
    if now < float(scene.get("actionDeadline") or 0):
        return
    if phase == "action":
        if scene_has_hostile_exchange(scene):
            start_scene_battle(state, scene, urls, tokens)
        else:
            finish_scene_without_battle(state, scene, urls, tokens)
    elif phase == "battle":
        resolve_battle_round(state, scene, urls, tokens)


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
    if battle.get("origin") == "gm_scene":
        post(
            base,
            token,
            f"【GM受付 {battle['id']}】この戦闘はGMのラウンド裁定中です。"
            f"戦果を確定せず、`@gm 戦闘行動 シーンID:{battle.get('originScene')} 戦闘ID:{battle['id']} 行動:○○`で次の行動を宣言してください。",
            note_id,
        )
        audit(state, "scene_battle_result_ignored", battleId=battle.get("id"), instance=instance)
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


def process_scene_action(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    state: dict,
) -> None:
    scene = state.get("currentScene")
    requested = explicit_scene_id(text)
    if not isinstance(scene, dict) or scene.get("phase") not in {"action", "battle"}:
        post(base, token, "【GM未受付】現在受付中のTRPG場面はありません。次のGM場面を待ってください。", note_id)
        audit(state, "unmatched_scene_action", instance=instance, sceneId=requested)
        return
    if requested and requested.upper() != str(scene.get("id", "")).upper():
        post(
            base,
            token,
            f"【GM未受付】指定されたシーンID {requested} は現在の場面 {scene.get('id')} と一致しません。",
            note_id,
        )
        audit(state, "stale_scene_action", instance=instance, sceneId=requested, currentScene=scene.get("id"))
        return
    if scene.get("phase") == "battle":
        requested_battle = explicit_battle_id(text)
        if requested_battle and requested_battle.upper() != str(scene.get("battleId", "")).upper():
            post(
                base,
                token,
                f"【GM未受付】指定された戦闘ID {requested_battle} は現在の戦闘 {scene.get('battleId')} と一致しません。",
                note_id,
            )
            audit(state, "stale_battle_action", instance=instance, battleId=requested_battle)
            return
    body = action_body(text)
    category = action_category(text)
    round_no = int(scene.get("round") or 1)
    entries = scene_actions(scene, instance)
    entries[:] = [entry for entry in entries if not (entry.get("username") == username and int(entry.get("round") or 1) == round_no)]
    entries.append(
        {
            "username": username,
            "noteId": note_id,
            "text": body,
            "category": category,
            "round": round_no,
            "at": iso_now(),
        }
    )
    scene["updatedAt"] = time.time()
    label = "戦闘行動" if scene.get("phase") == "battle" else "行動"
    post(
        base,
        token,
        f"【GM受付 {scene['id']}／第{round_no}ラウンド】{username}の{label}「{body or '観察'}」を受理しました。"
        f"分類:{category}。期限までに他の行動を受け付け、GMがまとめて裁定します。",
        note_id,
    )
    audit(state, "scene_action", sceneId=scene.get("id"), battleId=scene.get("battleId"), instance=instance, username=username, category=category)


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
        if kind == "action":
            process_scene_action(instance, base, token, note_id, username, text, state)
        elif kind == "battle":
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
    if SCENE_INTERVAL_SECONDS < 60:
        raise ValueError("GM_SCENE_INTERVAL_SECONDS must be at least 60 seconds")
    if ACTION_WINDOW_SECONDS < 30:
        raise ValueError("GM_ACTION_WINDOW_SECONDS must be at least 30 seconds")
    if not 1 <= BATTLE_ROUNDS <= 10:
        raise ValueError("GM_BATTLE_ROUNDS must be between 1 and 10")
    urls = {
        "black": os.environ["BLACK_URL"],
        "white": os.environ["WHITE_URL"],
        "world": os.environ["WORLD_URL"],
    }
    tokens = {name: credentials(name)[0] for name in urls}
    state = ensure_state(
        load_json(
            STATE_PATH,
            {
                "version": 3,
                "seen": [],
                "battles": [],
                "events": [],
                "scenes": [],
                "currentScene": None,
                "nextSceneAt": 0,
                "sceneSequence": 0,
                "startedAt": time.time(),
            },
        )
    )
    save_json(STATE_PATH, state)
    print(
        f"Twin-Moon Basin GM active: TRPG scene clock={SCENE_INTERVAL_SECONDS // 60}m, "
        f"action window={ACTION_WINDOW_SECONDS // 60}m, battle rounds={BATTLE_ROUNDS}; "
        f"battle window={BATTLE_WINDOW_SECONDS // 3600}h.",
        flush=True,
    )
    while True:
        try:
            expire_battles(state, urls, tokens)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            print(f"gm: expiry pass failed: {type(exc).__name__}: {exc}", flush=True)
        try:
            advance_campaign(state, urls, tokens)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            print(f"gm: campaign advance failed: {type(exc).__name__}: {exc}", flush=True)
        for instance in ("black", "white"):
            try:
                process_instance(instance, urls[instance], tokens[instance], state, urls, tokens)
            except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
                print(f"gm: {instance} poll failed: {type(exc).__name__}: {exc}", flush=True)
        try:
            # Process actions that arrived in the same poll before deciding
            # whether the scene's action window has elapsed.
            advance_campaign(state, urls, tokens)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            print(f"gm: post-poll campaign advance failed: {type(exc).__name__}: {exc}", flush=True)
        save_json(STATE_PATH, state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
