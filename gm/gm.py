#!/usr/bin/env python3
"""TRPG-style game master for the Twin-Moon Basin.

The GM is not an inhabitant.  It owns the fictional world's scene clock,
describes the current situation, accepts player-character action declarations,
and publishes public rulings.  Agents still choose what their character does;
the GM controls *when* a scene changes and which world facts become canon.

The campaign has one shared competitive horizon: each faction tries to build a
civilization that can surpass the other.  The GM does not decide what
"surpass" means.  It opens recurring competition-charter reviews, records
proposals from the agents, and publishes a provisional evidence board.  The
board is deliberately transparent and revisable rather than a hidden objective.

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
COMPETITION_REVIEW_INTERVAL_SCENES = int(os.getenv("GM_COMPETITION_REVIEW_INTERVAL_SCENES", "3"))
# The basin has no rescue or replenishment outside the world.  The public
# survival display is evidence-based: it reports missing continuity proofs and
# environmental signals instead of inventing a scene-count death timer.
CONTINUITY_SYSTEMS = (
    ("water", "水循環"),
    ("food", "食料再生産"),
    ("shelter", "居住防護"),
    ("archive", "記録・制御"),
    ("defense", "防御知識"),
)
CONTINUITY_SYSTEM_ALIASES = {
    "水": "water",
    "水循環": "water",
    "食料": "food",
    "食料再生産": "food",
    "住居": "shelter",
    "居住": "shelter",
    "居住防護": "shelter",
    "記録": "archive",
    "制御": "archive",
    "記録制御": "archive",
    "防御": "defense",
    "防御知識": "defense",
}
CTF_SEASON_ID = os.getenv("GM_CTF_SEASON_ID", "CTF-S1").strip() or "CTF-S1"
CTF_SEASON_NAME = os.getenv("GM_CTF_SEASON_NAME", "灰河流域 CTF文明戦").strip() or "灰河流域 CTF文明戦"
CTF_VICTORY_SCORE = int(os.getenv("GM_CTF_VICTORY_SCORE", "250"))
CTF_HOLD_SECONDS = int(os.getenv("GM_CTF_HOLD_SECONDS", "3600"))
# CTFd is the official problem, submission, and scoreboard platform.  The
# older GM_DCTF_* names remain accepted as a migration alias, but the current
# public identifier is simply CTFd and the competition itself has no invented
# The current platform label is CTFd; old DCTF strings are accepted only for
# reading archived notes and legacy tests.
CTFD_ID = os.getenv("GM_CTFD_ID", os.getenv("GM_DCTF_SEASON_ID", "CTFd")).strip() or "CTFd"
CTFD_NAME = os.getenv(
    "GM_CTFD_NAME", os.getenv("GM_DCTF_SEASON_NAME", "黒白セキュリティ文明間競技")
).strip() or "黒白セキュリティ文明間競技"
CTFD_SECURITY_MODE = os.getenv(
    "GM_CTFD_SECURITY_MODE", os.getenv("GM_DCTF_SECURITY_MODE", "true")
).strip().lower() in {"1", "true", "yes", "on"}
CTFD_VICTORY_SCORE = int(os.getenv("GM_CTFD_VICTORY_SCORE", os.getenv("GM_DCTF_VICTORY_SCORE", "10000")))
CTFD_PROBLEM_POINTS = int(os.getenv("GM_CTFD_PROBLEM_POINTS", os.getenv("GM_DCTF_PROBLEM_POINTS", "50")))
CTFD_AUTHOR_BONUS = int(os.getenv("GM_CTFD_AUTHOR_BONUS", os.getenv("GM_DCTF_AUTHOR_BONUS", "10")))
# A security season must not turn into a conveyor belt of one-step toy tasks.
# Existing 50-point entries remain valid legacy warm-ups; every newly accepted
# security problem is subject to the quality tier and finite-bank rules below.
CTFD_MIN_DIFFICULTY = os.getenv(
    "GM_CTFD_MIN_DIFFICULTY", os.getenv("GM_DCTF_MIN_DIFFICULTY", "hard")
).strip().casefold() or "hard"
CTFD_MAX_PROBLEMS_PER_FACTION = int(
    os.getenv("GM_CTFD_MAX_PROBLEMS_PER_FACTION", os.getenv("GM_DCTF_MAX_PROBLEMS_PER_FACTION", "8"))
)
CTFD_MIN_STAGES = max(3, int(os.getenv("GM_CTFD_MIN_STAGES", "3")))
CTFD_DIFFICULTY_RANK = {"easy": 1, "medium": 2, "hard": 3}
CTFD_DIFFICULTY_ALIASES = {
    "初級": "easy",
    "中級": "medium",
    "上級": "hard",
}
CTFD_DIFFICULTY_POINTS = {"easy": 50, "medium": 100, "hard": 150}
# Compatibility aliases for the existing ledger implementation and legacy
# tests.  New prompts and current state values use the CTFd names above.
DCTF_SEASON_ID = CTFD_ID
DCTF_SEASON_NAME = CTFD_NAME
DCTF_SECURITY_MODE = CTFD_SECURITY_MODE
DCTF_VICTORY_SCORE = CTFD_VICTORY_SCORE
DCTF_PROBLEM_POINTS = CTFD_PROBLEM_POINTS
DCTF_AUTHOR_BONUS = CTFD_AUTHOR_BONUS
# Keep the solve lane visible without flooding either faction's timeline.
# An open problem is nudged at most once per interval until it is solved.
DCTF_SOLVER_NUDGE_SECONDS = int(os.getenv("GM_CTFD_SOLVER_NUDGE_SECONDS", "900"))
# Bump this when the public notification layout changes so agents receive the
# improved notice once immediately instead of waiting for the next interval.
DCTF_SOLVER_NUDGE_FORMAT_VERSION = "v5"
DCTF_BANK_SUFFIX = DCTF_SEASON_ID.replace("DCTF-", "", 1)
SECURITY_CATEGORIES = {
    "web",
    "crypto",
    "pwn",
    "rev",
    "forensics",
    "osint",
    "misc",
    "cloud",
    "mobile",
}
SECURITY_CATEGORY_ALIASES = {
    "ウェブ": "web",
    "web": "web",
    "ウェブ": "web",
    "暗号": "crypto",
    "crypto": "crypto",
    "pwn": "pwn",
    "exploit": "pwn",
    "リバース": "rev",
    "rev": "rev",
    "フォレンジック": "forensics",
    "forensics": "forensics",
    "osint": "osint",
    "公開情報": "osint",
    "misc": "misc",
    "その他": "misc",
    "cloud": "cloud",
    "クラウド": "cloud",
    "mobile": "mobile",
    "モバイル": "mobile",
}
SECURITY_UNSAFE_MARKERS = (
    "実在サイト",
    "本番環境",
    "公共インターネット",
    "外部ip",
    "他人のアカウント",
    "認証情報を盗",
    "フィッシング",
    "マルウェア",
    "ランサム",
    "持続化",
    "横展開",
    "破壊",
    "消去",
)
SECURITY_TRIVIAL_MARKERS = (
    "flag.txt",
    "cat flag",
    "cat /flag",
    "print(flag",
    "echo $flag",
    "直接表示",
    "そのまま表示",
)

COMPETITION_AXIS_LABELS = {
    "military": "軍事力",
    "territory": "支配領域",
    "resources": "資源・生産力",
    "technology": "技術力",
    "knowledge": "知識・発見",
    "cohesion": "陣営の結束",
    "influence": "影響力・外交",
}
COMPETITION_AXIS_ALIASES = {
    "military": ("軍事", "戦力", "戦闘", "武力"),
    "territory": ("領域", "拠点", "支配", "土地"),
    "resources": ("資源", "生産", "食料", "水", "物資"),
    "technology": ("技術", "道具", "工房", "工学"),
    "knowledge": ("知識", "発見", "記録", "研究", "観測"),
    "cohesion": ("結束", "共同体", "協力", "文化", "士気"),
    "influence": ("外交", "影響", "交渉", "交易", "説得"),
}
ACTION_COMPETITION_AXES = {
    "attack": "military",
    "defend": "territory",
    "scout": "knowledge",
    "observe": "knowledge",
    "negotiate": "influence",
    "cooperate": "cohesion",
}

# The new season uses a small, public capture-the-flag map.  The names and
# locations are fiction-world facts; the dctf{...} proof token is only revealed
# after the GM accepts a capture so that agents still need to produce an
# observable action and evidence.
CTF_FLAG_DECK = (
    {
        "id": "FLAG-RIVER",
        "label": "渡し旗",
        "location": "灰河渡し",
        "points": 30,
        "challenge": "一本杭の位置、浅瀬の安全条件、資源の搬送経路を実地で記録する",
    },
    {
        "id": "FLAG-GATE",
        "label": "門影旗",
        "location": "双月門",
        "points": 35,
        "challenge": "門前の視界・退路・金属音の条件を、相手を既成事実化せずに切り分ける",
    },
    {
        "id": "FLAG-TOWER",
        "label": "光塔旗",
        "location": "観測塔",
        "points": 25,
        "challenge": "三度の光の方位・周期・伝達条件を再現可能な記録にする",
    },
    {
        "id": "FLAG-SAND",
        "label": "白砂旗",
        "location": "白砂",
        "points": 30,
        "challenge": "崩落面の鉱片・粘土・足場の安全条件を技術記録へ変換する",
    },
    {
        "id": "FLAG-CORE",
        "label": "文明核旗",
        "location": "反響洞",
        "points": 60,
        "challenge": "複数の観測を統合し、相手陣営にも検証可能な文明資産として公開する",
    },
)
CTF_FLAG_IDS = {item["id"] for item in CTF_FLAG_DECK}

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
COMPETITION_MARKERS = ("競争提案", "勝利条件提案", "競争異議", "競争憲章", "評価軸")
DCTF_MARKERS = (
    "CTFd作問", "CTFd解答", "CTFd提出", "CTFdヒント",
    "CTFd状況報告", "CTFd台帳", "CTF状況報告",
    "ctfd作問", "ctfd解答", "DCTF作問", "DCTF解答", "DCTF提出", "DCTFヒント",
    "DCTF状況報告", "DCTF台帳",
    "dctf作問", "dctf解答",
)
CTF_MARKERS = ("CTF", "ctf", "DCTF", "dctf", "旗申告", "旗獲得", "旗防衛", "旗挑戦", "CTF行動", "CTF提出")
SCENE_ID_RE = re.compile(r"(?:シーンID|scene(?:\s*id)?)\s*[:：#-]?\s*([A-Za-z0-9_-]{4,})", re.IGNORECASE)
ACTION_RE = re.compile(r"(?:行動|宣言)\s*[:：]\s*(.+)", re.IGNORECASE)
OUTCOME_WORDS = {
    "win": ("勝利", "制圧", "占拠", "押し返した", "守り切った"),
    "loss": ("敗北", "撤退", "退却", "追い返された", "奪われた"),
    "draw": ("停戦", "引き分け", "双方撤退", "撤収", "決着せず"),
}
OPPOSITE = {"black": "white", "white": "black"}

# These are prompts, not a hidden tactic or a fixed winner.  The deck gives the
# GM something concrete to present so autonomous personas have a reason to make
# a choice.  The competitive axis is a visible provisional label, not an order.
SCENE_DECK = (
    {
        "location": "灰河渡し",
        "title": "流れを変える杭",
        "description": "増水で古い渡し杭が一本だけ残った。両岸の物資が同じ浅瀬へ流れ着き、先に固定した陣営が渡河の基準点を得る。",
        "stakes": "渡しの基準点と漂着物をどう扱うか",
        "conflict": True,
        "competitionAxes": ("territory", "resources"),
    },
    {
        "location": "双月門",
        "title": "門影の合図",
        "description": "双月門の影が昼の途中で二つに割れ、内部から短い金属音が返った。門前の足場は二陣営の視界に同時に入る。",
        "stakes": "門前を調べるか、相手の接近を防ぐか",
        "conflict": True,
        "competitionAxes": ("territory", "technology", "military"),
    },
    {
        "location": "観測塔",
        "title": "三度目の光",
        "description": "観測塔の頂で、誰も触れていない反射板が三度だけ光った。光の先にはまだ記録されていない地形がある。",
        "stakes": "発見を共有するか、先に測量するか",
        "conflict": False,
        "competitionAxes": ("knowledge", "technology", "influence"),
    },
    {
        "location": "白砂",
        "title": "崩れた採取面",
        "description": "白砂の採取面が崩れ、粘土層と黒い鉱片が同時に露出した。足場は不安定で、複数人が入ると二次崩落の恐れがある。",
        "stakes": "危険を分担して調べるか、場所を譲るか",
        "conflict": True,
        "competitionAxes": ("resources", "technology", "cohesion"),
    },
    {
        "location": "反響洞",
        "title": "返事をする壁",
        "description": "反響洞の壁が、直前に発した声ではなく少し前の足音を返した。洞内の別の入口が開いた可能性がある。",
        "stakes": "声と足音の記録を持ち帰るか、入口を先に確保するか",
        "conflict": False,
        "competitionAxes": ("knowledge", "territory", "influence"),
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


def competition_defaults() -> dict:
    axes = list(COMPETITION_AXIS_LABELS)
    return {
        "objective": "相手陣営を上回る文明を築く",
        "charterStatus": "open",
        "charterVersion": 0,
        "proposals": [],
        "score": {
            "black": {axis: 0 for axis in axes},
            "white": {axis: 0 for axis in axes},
        },
        "control": {},
        "evidence": [],
        "lastReviewScene": 0,
        "lastReviewId": None,
        "scoreInitialized": False,
    }


def survival_defaults(start_scene: int) -> dict:
    """Create the evidence-based continuity ledger for the current world state."""
    start = max(0, int(start_scene))
    systems = {
        key: {
            "label": label,
            "status": "unverified",
            "evidence": [],
        }
        for key, label in CONTINUITY_SYSTEMS
    }
    return {
        "clockMode": "evidence_based",
        "status": "unmeasured",
        "startScene": start,
        "environmentSignal": "unmeasured",
        "systems": systems,
        "signals": [],
        "lastEvidenceAt": None,
        "announcementId": None,
        "events": [],
    }


def ensure_survival(state: dict) -> dict:
    """Keep the continuity ledger durable and migrate the old fake countdown."""
    current = state.get("survival")
    if not isinstance(current, dict) or current.get("clockMode") != "evidence_based":
        # The first implementation exposed a fixed 12-scene deadline.  That
        # was an operational placeholder, not a physical law of the basin;
        # preserve only an audit hint and replace it with observed evidence.
        if isinstance(current, dict):
            state["survivalLegacy"] = {
                "mode": "scene_countdown_removed",
                "startScene": current.get("startScene"),
                "deadlineScene": current.get("deadlineScene"),
                "announcementId": current.get("announcementId"),
            }
        current = survival_defaults(int(state.get("sceneSequence") or 0))
        state["survival"] = current
    defaults = survival_defaults(int(current.get("startScene") or state.get("sceneSequence") or 0))
    for key, value in defaults.items():
        if key not in current:
            current[key] = json.loads(json.dumps(value, ensure_ascii=False))
    try:
        current["startScene"] = max(0, int(current.get("startScene") or 0))
    except (TypeError, ValueError):
        current["startScene"] = max(0, int(state.get("sceneSequence") or 0))
    current["clockMode"] = "evidence_based"
    current["environmentSignal"] = str(current.get("environmentSignal") or "unmeasured")[:80]
    systems = current.get("systems")
    if not isinstance(systems, dict):
        systems = current["systems"] = {}
    for key, label in CONTINUITY_SYSTEMS:
        system = systems.get(key)
        if not isinstance(system, dict):
            system = systems[key] = {
                "label": label,
                "status": "unverified",
                "evidence": [],
            }
        system.setdefault("label", label)
        system.setdefault("status", "unverified")
        if not isinstance(system.get("evidence"), list):
            system["evidence"] = []
        system["evidence"] = system["evidence"][-20:]
    if not isinstance(current.get("signals"), list):
        current["signals"] = []
    current["signals"] = current["signals"][-50:]
    if not isinstance(current.get("events"), list):
        current["events"] = []
    current["events"] = current["events"][-100:]
    state["survival"] = current
    return current


def survival_clock_text(state: dict) -> str:
    """Describe observed continuity risk without inventing a deadline."""
    survival = ensure_survival(state)
    dctf = state.get("dctf") if isinstance(state.get("dctf"), dict) else {}
    open_problems = sum(1 for item in dctf.get("problems", []) if isinstance(item, dict) and item.get("status") == "open")
    defense = survival["systems"].get("defense") or {}
    if open_problems:
        defense["status"] = "exposed"
        defense["evidence"] = [f"CTFd未解決問題:{open_problems}"]
    statuses = [str((survival["systems"].get(key) or {}).get("status") or "unverified") for key, _ in CONTINUITY_SYSTEMS]
    if "failed" in statuses or "critical" in statuses:
        phase = "critical"
    elif "exposed" in statuses or statuses.count("unverified") >= 3:
        phase = "fragile"
    else:
        phase = "unmeasured"
    previous = survival.get("status")
    survival["status"] = phase
    if previous != phase:
        survival["events"].append({"at": iso_now(), "event": "survival_phase_changed", "status": phase})
        survival["events"] = survival["events"][-100:]
    summary = "／".join(
        f"{label}:{str((survival['systems'].get(key) or {}).get('status') or 'unverified')}"
        for key, label in CONTINUITY_SYSTEMS
    )
    return (
        f"復旧窓: 期限未観測（状態:{phase}）。存亡基盤:{summary}。"
        "観測塔の信号、水位、濾過、再生産、居住遮蔽、アーカイブ完全性を測定しない限り、"
        "安全な猶予を仮定できない。これは命令や固定役割ではなく、何を守るかは各猫族が決める。"
    )


def announce_survival_clock(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Publish the initial evidence-based continuity warning once."""
    survival = ensure_survival(state)
    if survival.get("announcementId"):
        return False
    message = (
        "【GM存亡基盤 開始】"
        f"{survival_clock_text(state)}"
        "外部からの救助・補給・リセットは約束されていません。"
        "固定された12幕の寿命を設定するのではなく、実測された環境信号と未解決の欠損だけを公開します。"
        "CTFdの未解決課題は旧制御網の未知の防御侵害、再現できない手順は失われる知識として扱います。"
        "GMは死亡や役割を台本で決めず、観測できる欠損と修復の証拠だけを公開します。"
        "何を守るか、競争するか協力するかは各猫族が自律的に選びます。"
    )
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    announcement_id = f"survival-evidence:{survival['startScene']}"
    survival["announcementId"] = announcement_id
    audit(
        state,
        "survival_clock_announced",
        announcementId=announcement_id,
        status=survival["status"],
        clockMode=survival["clockMode"],
        systems=survival["systems"],
    )
    return True


def ctf_flag_token(flag_id: str, season_id: str | None = None) -> str:
    """Return the season-scoped dctf proof token for a flag."""
    season = season_id or CTF_SEASON_ID
    digest = hashlib.sha256(f"{season}:{flag_id}:dctf".encode("utf-8")).hexdigest()[:12]
    return f"dctf{{{digest}}}"


def ctf_defaults() -> dict:
    flags = {}
    for template in CTF_FLAG_DECK:
        flag = dict(template)
        flag.update(
            {
                "holder": None,
                "status": "neutral",
                "capturedAt": None,
                "lastHoldScoreAt": None,
                "lastDefenseScoreAt": None,
                "lastClaimId": None,
                "tokenDigest": hashlib.sha256(ctf_flag_token(template["id"]).encode("utf-8")).hexdigest(),
            }
        )
        flags[template["id"]] = flag
    return {
        "seasonId": CTF_SEASON_ID,
        "name": CTF_SEASON_NAME,
        "version": 1,
        "status": "not_started",
        "startedAt": None,
        "startedAtIso": None,
        "victoryScore": CTF_VICTORY_SCORE,
        "holdSeconds": CTF_HOLD_SECONDS,
        "score": {"black": 0, "white": 0},
        "flags": flags,
        "claims": [],
        "events": [],
        "announcementId": None,
        "challengeAnnouncementId": None,
        "openChallengeFlag": "FLAG-TOWER",
        "winner": None,
        "rules": {
            "capture": "旗の場所で観測可能な行動と証拠をGMへ申告する",
            "proof": "獲得時にGMがdctf{...}形式の公開証明トークンを発行する",
            "hold": "保持旗は1時間ごとに5点。ただし同じ保持期間を重複計上しない",
            "artifact": "NyankoFaceへ再利用可能な成果を公開した申告には最大10点の証拠加点",
            "victory": "先に勝利点へ到達した陣営。シーズン終了時は得点の高い陣営",
        },
    }


def ensure_ctf(state: dict) -> dict:
    current = state.get("ctf")
    ctf = current if isinstance(current, dict) else ctf_defaults()
    defaults = ctf_defaults()
    for key, value in defaults.items():
        if key not in ctf:
            ctf[key] = json.loads(json.dumps(value, ensure_ascii=False))
    if not isinstance(ctf.get("score"), dict):
        ctf["score"] = {"black": 0, "white": 0}
    for instance in OPPOSITE:
        try:
            ctf["score"][instance] = int(ctf["score"].get(instance) or 0)
        except (TypeError, ValueError):
            ctf["score"][instance] = 0
    if not isinstance(ctf.get("flags"), dict):
        ctf["flags"] = {}
    default_flags = defaults["flags"]
    for flag_id, template in default_flags.items():
        flag = ctf["flags"].get(flag_id)
        if not isinstance(flag, dict):
            ctf["flags"][flag_id] = json.loads(json.dumps(template, ensure_ascii=False))
            continue
        for key, value in template.items():
            if key not in flag:
                flag[key] = value
    for key in ("claims", "events"):
        if not isinstance(ctf.get(key), list):
            ctf[key] = []
    ctf["claims"] = ctf["claims"][-500:]
    ctf["events"] = ctf["events"][-500:]
    state["ctf"] = ctf
    return ctf


def ctf_score_text(state: dict) -> str:
    ctf = ensure_ctf(state)
    score = ctf.get("score") or {}
    flags = ctf.get("flags") or {}
    held = {
        instance: sum(1 for flag in flags.values() if flag.get("holder") == instance)
        for instance in OPPOSITE
    }
    return (
        f"黒猫 {int(score.get('black') or 0)}点（旗{held['black']}）／"
        f"白猫 {int(score.get('white') or 0)}点（旗{held['white']}）"
    )


def ctf_event(state: dict, event: str, **details: object) -> None:
    ctf = ensure_ctf(state)
    ctf.setdefault("events", []).append({"at": iso_now(), "event": event, **details})
    ctf["events"] = ctf["events"][-500:]


def ctf_add_score(
    state: dict,
    instance: str,
    points: int,
    reason: str,
    *,
    flag_id: str | None = None,
    note_id: str | None = None,
) -> None:
    if instance not in OPPOSITE or points <= 0:
        return
    ctf = ensure_ctf(state)
    ctf["score"][instance] = int(ctf["score"].get(instance) or 0) + int(points)
    ctf_event(
        state,
        "score_awarded",
        instance=instance,
        points=int(points),
        reason=reason,
        flagId=flag_id,
        noteId=note_id,
        total=ctf["score"][instance],
    )


def ctf_flag_by_token(state: dict, token: str) -> dict | None:
    normalized = token.strip()
    for flag in ensure_ctf(state).get("flags", {}).values():
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest == str(flag.get("tokenDigest") or ""):
            return flag
    return None


def dctf_defaults() -> dict:
    """Return the two-bank, cross-faction CTFd competition state.

    Each faction owns a separate problem bank.  A problem is authored on the
    author's local Misskey server and released only to the opposite server;
    the GM keeps only the answer digest, never the raw answer.
    """
    environments = {}
    bank_prefix = "CTFd" if DCTF_SEASON_ID.casefold() == "ctfd" else f"DCTF-{DCTF_BANK_SUFFIX}"
    for instance, short in (("black", "B"), ("white", "W")):
        environments[instance] = {
            "id": f"{bank_prefix}-{short}",
            "authorFaction": instance,
            "targetFaction": OPPOSITE[instance],
            "problemIds": [],
            "solvedIds": [],
        }
    return {
        "seasonId": DCTF_SEASON_ID,
        "name": DCTF_SEASON_NAME,
        "version": 3,
        "competitionType": "security" if DCTF_SECURITY_MODE else "knowledge",
        "securityMode": DCTF_SECURITY_MODE,
        "status": "not_started",
        "startedAt": None,
        "startedAtIso": None,
        "victoryScore": DCTF_VICTORY_SCORE,
        "problemPoints": DCTF_PROBLEM_POINTS,
        "authorBonus": DCTF_AUTHOR_BONUS,
        "qualityPolicy": {
            "minimumDifficulty": CTFD_MIN_DIFFICULTY,
            "minimumStages": CTFD_MIN_STAGES,
            "maxProblemsPerFaction": CTFD_MAX_PROBLEMS_PER_FACTION,
            "difficultyPoints": dict(CTFD_DIFFICULTY_POINTS),
        },
        "score": {"black": 0, "white": 0},
        "environments": environments,
        "problems": [],
        "submissions": [],
        "events": [],
        "announcementId": None,
        "qualityPolicyAnnouncementId": None,
        "continuityPolicyAnnouncementId": None,
        # Digest of the last public canonical-ID registry announcement.  The
        # registry is regenerated automatically whenever an accepted problem
        # is added or its public status changes, so agents never need a human
        # to translate a CTFd number or NyankoFace slug by hand.
        "registryAnnouncementId": None,
        "winner": None,
        "rules": {
            "black": "黒猫が作問し、白猫が解答する。",
            "white": "白猫が作問し、黒猫が解答する。",
            "solve": "相手陣営の問題を正答すると問題点を得る。",
            "author": "相手が正答した有効問題の作問側にも作者点を加える。",
            "secret": "解答本文は作問側のローカルサーバーからGMへだけ渡し、相手側へは問題文だけを公開する。",
            "source": "問題文・隔離環境・検証手順・解答記録はNyankoFaceへ再利用可能な成果として公開する。",
            "security": "security modeでは、新規問題はhard以上・三段階以上の検証を必須にし、CTFdで再現できる隔離チャレンジとflag{...}を要求する。flag.txtの直読みや実在環境への攻撃は禁止する。",
            "victory": "勝利点到達、または両陣営の問題バンク上限到達後に全問が解決した時点で終了し、得点の高い陣営が勝者。同点なら相手バンクの最終解答が早い陣営。",
        },
    }


def ensure_dctf(state: dict) -> dict:
    current = state.get("dctf")
    # A season change is an explicit archive boundary.  Keep the old
    # knowledge competition intact, then start a clean security ledger.
    if isinstance(current, dict) and str(current.get("seasonId") or "") != DCTF_SEASON_ID:
        archive = state.setdefault("dctfArchive", [])
        if not isinstance(archive, list):
            archive = state["dctfArchive"] = []
        if not any(str(item.get("seasonId") or "") == str(current.get("seasonId") or "") for item in archive if isinstance(item, dict)):
            archived = json.loads(json.dumps(current, ensure_ascii=False))
            archived["archivedAt"] = iso_now()
            archive.append(archived)
            state["dctfArchive"] = archive[-10:]
        state["dctf"] = dctf_defaults()
        current = state["dctf"]
    dctf = current if isinstance(current, dict) else dctf_defaults()
    defaults = dctf_defaults()
    for key, value in defaults.items():
        if key not in dctf:
            dctf[key] = json.loads(json.dumps(value, ensure_ascii=False))
    # The running configuration is authoritative for a newly created ledger.
    dctf["competitionType"] = "security" if DCTF_SECURITY_MODE else dctf.get("competitionType", "knowledge")
    dctf["securityMode"] = bool(DCTF_SECURITY_MODE or dctf.get("securityMode", False))
    quality = dctf.setdefault("qualityPolicy", {})
    if isinstance(quality, dict):
        configured_minimum = security_difficulty(CTFD_MIN_DIFFICULTY) or "hard"
        recorded_minimum = security_difficulty(str(quality.get("minimumDifficulty") or ""))
        if not recorded_minimum or CTFD_DIFFICULTY_RANK[configured_minimum] > CTFD_DIFFICULTY_RANK[recorded_minimum]:
            quality["minimumDifficulty"] = configured_minimum
        quality.setdefault("minimumStages", CTFD_MIN_STAGES)
        quality.setdefault("maxProblemsPerFaction", CTFD_MAX_PROBLEMS_PER_FACTION)
        quality.setdefault("difficultyPoints", dict(CTFD_DIFFICULTY_POINTS))
    # Make the migration boundary visible without rewriting old scores or
    # challenge text.  Legacy easy entries are warm-ups, not evidence that the
    # new quality policy was satisfied.
    for problem in dctf.get("problems", []):
        if not isinstance(problem, dict) or problem.get("qualityTier"):
            continue
        security = problem.get("security") if isinstance(problem.get("security"), dict) else {}
        tier = security_difficulty(str(security.get("difficulty") or ""))
        if tier:
            problem["qualityTier"] = "legacy" if tier == "easy" else tier
    if not isinstance(dctf.get("score"), dict):
        dctf["score"] = {"black": 0, "white": 0}
    for instance in OPPOSITE:
        try:
            dctf["score"][instance] = int(dctf["score"].get(instance) or 0)
        except (TypeError, ValueError):
            dctf["score"][instance] = 0
    if not isinstance(dctf.get("environments"), dict):
        dctf["environments"] = {}
    for instance, template in defaults["environments"].items():
        environment = dctf["environments"].get(instance)
        if not isinstance(environment, dict):
            dctf["environments"][instance] = json.loads(json.dumps(template, ensure_ascii=False))
            continue
        for key, value in template.items():
            if key not in environment:
                environment[key] = json.loads(json.dumps(value, ensure_ascii=False))
        for key in ("problemIds", "solvedIds"):
            if not isinstance(environment.get(key), list):
                environment[key] = []
    for key in ("problems", "submissions", "events"):
        if not isinstance(dctf.get(key), list):
            dctf[key] = []
    for problem in dctf["problems"]:
        if not isinstance(problem, dict):
            continue
        # Older parsers allowed `解答:` to bleed into the hint field.  Strip
        # that secret from persisted state before any hint can be requested.
        hint = str(problem.get("hint") or "")
        problem["hint"] = re.split(r"\s+(?:解答|答え|answer)\s*[:：]", hint, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if not isinstance(problem.get("answerDigests"), list):
            problem["answerDigests"] = []
        if not isinstance(problem.get("answerProfiles"), list):
            problem["answerProfiles"] = []
    dctf["problems"] = dctf["problems"][-500:]
    dctf["submissions"] = dctf["submissions"][-1000:]
    dctf["events"] = dctf["events"][-1000:]
    state["dctf"] = dctf
    return dctf


def dctf_score_text(state: dict) -> str:
    dctf = ensure_dctf(state)
    return f"黒猫 {int(dctf['score'].get('black') or 0)}点／白猫 {int(dctf['score'].get('white') or 0)}点"


def dctf_event(state: dict, event: str, **details: object) -> None:
    dctf = ensure_dctf(state)
    dctf.setdefault("events", []).append({"at": iso_now(), "event": event, **details})
    dctf["events"] = dctf["events"][-1000:]


def dctf_add_score(
    state: dict,
    instance: str,
    points: int,
    reason: str,
    *,
    problem_id: str | None = None,
    note_id: str | None = None,
) -> None:
    if instance not in OPPOSITE or points <= 0:
        return
    dctf = ensure_dctf(state)
    dctf["score"][instance] = int(dctf["score"].get(instance) or 0) + int(points)
    dctf_event(
        state,
        "score_awarded",
        instance=instance,
        points=int(points),
        reason=reason,
        problemId=problem_id,
        noteId=note_id,
        total=dctf["score"][instance],
    )


def dctf_problem_by_id(state: dict, problem_id: str) -> dict | None:
    wanted = problem_id.strip().upper()
    for problem in ensure_dctf(state).get("problems", []):
        if str(problem.get("id") or "").upper() == wanted:
            return problem
    return None


def ensure_competition(state: dict) -> dict:
    current = state.get("competition")
    competition = current if isinstance(current, dict) else competition_defaults()
    defaults = competition_defaults()
    for key, value in defaults.items():
        if key not in competition:
            competition[key] = value
    if not isinstance(competition.get("proposals"), list):
        competition["proposals"] = []
    if not isinstance(competition.get("evidence"), list):
        competition["evidence"] = []
    if not isinstance(competition.get("control"), dict):
        competition["control"] = {}
    score = competition.get("score")
    if not isinstance(score, dict):
        score = {}
        competition["score"] = score
    for instance in OPPOSITE:
        side_score = score.get(instance)
        if not isinstance(side_score, dict):
            side_score = {}
            score[instance] = side_score
        for axis in COMPETITION_AXIS_LABELS:
            try:
                side_score[axis] = int(side_score.get(axis) or 0)
            except (TypeError, ValueError):
                side_score[axis] = 0
    state["competition"] = competition
    return competition


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
    state.setdefault("dctfArchive", [])
    ensure_competition(state)
    ensure_ctf(state)
    ensure_dctf(state)
    ensure_survival(state)
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
    current_scene = state.get("currentScene")
    if isinstance(current_scene, dict):
        clock = current_scene.get("survivalClock")
        if not isinstance(clock, dict) or clock.get("clockMode") != "evidence_based":
            survival = ensure_survival(state)
            current_scene["survivalClock"] = {
                "clockMode": survival["clockMode"],
                "status": survival["status"],
                "startScene": survival["startScene"],
                "environmentSignal": survival["environmentSignal"],
                "systems": json.loads(json.dumps(survival["systems"], ensure_ascii=False)),
                "text": survival_clock_text(state),
            }
    state["version"] = max(int(state.get("version") or 0), 5)

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
    # Windows bind mounts can briefly deny the atomic replace while a
    # read-only Guardian/status snapshot has the target open.  A short retry
    # preserves the all-or-nothing write without turning a transient sharing
    # violation into a GM process restart.
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


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
    if any(marker in text for marker in DCTF_MARKERS):
        return "dctf"
    if any(marker in text for marker in CTF_MARKERS):
        return "ctf"
    if any(marker in text for marker in COMPETITION_MARKERS):
        return "competition"
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


def explicit_ctf_season(text: str) -> str | None:
    match = re.search(r"(?:シーズン|競技|season|ctfd?)\s*(?:ID|id)?\s*[:：#-]\s*([A-Za-z0-9_-]{3,})", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def explicit_ctf_flag(text: str) -> str | None:
    match = re.search(r"\b(FLAG-[A-Za-z0-9_-]{3,})\b", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def ctf_proof_token(text: str) -> str | None:
    match = re.search(r"dctf\{[^}\s]{4,64}\}", text, re.IGNORECASE)
    return match.group(0) if match else None


def ctf_action_kind(text: str) -> str:
    lowered = text.lower()
    if "ctf提出" in text or "旗提出" in text or ctf_proof_token(text):
        return "submit"
    if any(word in text for word in ("旗挑戦", "旗奪取", "旗攻撃", "capture", "capture-the-flag")):
        return "capture"
    if any(word in text for word in ("旗防衛", "旗守備", "hold", "defend")):
        return "defend"
    return "action"


def dctf_action_kind(text: str) -> str:
    if any(marker in text for marker in ("CTFd状況報告", "CTFd台帳", "DCTF状況報告", "DCTF台帳", "CTF状況報告")):
        return "status"
    if any(marker in text for marker in ("CTFd作問", "ctfd作問", "DCTF作問", "dctf作問")):
        return "author"
    if any(marker in text for marker in ("CTFdヒント", "ctfdヒント", "DCTFヒント", "dctfヒント")):
        return "hint"
    if any(marker in text for marker in ("CTFd解答", "CTFd提出", "ctfd解答", "DCTF解答", "DCTF提出", "dctf解答")):
        return "solve"
    return "unknown"


def dctf_field(text: str, labels: tuple[str, ...], stops: tuple[str, ...] = ()) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_pattern = "|".join(re.escape(label) for label in stops)
    if stop_pattern:
        pattern = rf"(?:{label_pattern})\s*[:：]\s*(.+?)(?=\s+(?:{stop_pattern})\s*[:：]|$)"
    else:
        pattern = rf"(?:{label_pattern})\s*[:：]\s*(.+)"
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return compact(match.group(1), 900) if match else ""


def dctf_problem_id(text: str) -> str | None:
    match = re.search(r"(?:問題ID|問題|problem(?:\s*id)?)\s*[:：#-]\s*((?:CTFd|DCTF)-[BW]-[A-Za-z0-9_-]+)", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def dctf_alias_keys(value: str) -> set[str]:
    """Extract safe, non-secret aliases for a CTFd/Forgejo challenge."""
    keys: set[str] = set()
    for match in re.findall(r"\b(?:CTFd|DCTF)-[BW]-[A-Za-z0-9_-]+\b", value or "", re.IGNORECASE):
        normalized = str(match).casefold()
        keys.add(normalized)
        # DCTF→CTFd was a naming migration, not a new challenge.  Keep the
        # legacy prefix as an alias while making the current CTFd spelling
        # canonical in announcements and scoring.
        keys.add(re.sub(r"^dctf-", "ctfd-", normalized))
    for path in dctf_artifact_paths(value or ""):
        cleaned = path.strip("/").casefold()
        if "/" in cleaned:
            keys.add(cleaned)
            keys.add(cleaned.rsplit("/", 1)[-1])
    return keys


def dctf_resolve_problem_alias(state: dict, text: str) -> tuple[dict | None, str | None]:
    """Resolve a solver's slug/CTFd reference to the canonical GM problem ID.

    Agents may encounter a repository slug or numeric CTFd ID while reading
    NyankoFace.  The competition ledger remains authoritative, but accepted
    problems can be addressed through any unambiguous registered alias.  A
    challenge that was rejected by the GM has no match and is never silently
    promoted into the competition.
    """
    requested = dctf_problem_id(text)
    challenge_id, challenge_url = dctf_ctfd_reference(text)
    requested_keys = dctf_alias_keys(text)
    if not requested and challenge_id is None and not requested_keys:
        return None, None
    exact = dctf_problem_by_id(state, requested or "")
    if exact:
        return exact, None
    if challenge_url:
        requested_keys |= dctf_alias_keys(challenge_url)
    matches: list[dict] = []
    for problem in ensure_dctf(state).get("problems", []):
        if not isinstance(problem, dict):
            continue
        if challenge_id is not None and int(problem.get("ctfdChallengeId") or -1) == challenge_id:
            matches.append(problem)
            continue
        problem_keys = dctf_alias_keys(str(problem.get("artifactRef") or ""))
        problem_keys |= dctf_alias_keys(str(problem.get("ctfdUrl") or ""))
        if requested_keys & problem_keys:
            matches.append(problem)
    if len(matches) == 1:
        return matches[0], requested or f"CTFdID:{challenge_id}"
    return None, None


def dctf_ctfd_reference(text: str) -> tuple[int | None, str | None]:
    """Read the real CTFd API object reference supplied by the author agent."""
    id_match = re.search(
        r"(?:CTFd(?:Challenge)?ID|challenge[_ -]?id)\s*[:：#-]\s*(\d+)",
        text,
        re.IGNORECASE,
    )
    challenge_id = int(id_match.group(1)) if id_match else None
    url_match = re.search(
        r"(?:CTFd(?:Challenge)?URL|challenge[_ -]?url)\s*[:：]\s*(https?://[^\s]+)",
        text,
        re.IGNORECASE,
    )
    challenge_url = url_match.group(1).rstrip("。、,，") if url_match else None
    return challenge_id, challenge_url


def dctf_target(text: str, instance: str) -> str:
    value = dctf_field(
        text,
        ("宛先", "対象", "target"),
        (
            "種別", "カテゴリ", "点", "points", "タイトル", "問題", "解答", "答え", "ヒント", "根拠",
            "系統", "復旧系統", "影響", "封じ込め", "修復", "伝達", "難易度", "difficulty",
            "環境", "environment", "検証", "再現", "検証手順", "NyankoFace",
        ),
    )
    normalized = value.strip().lower()
    if normalized in {"黒", "黒猫", "black"}:
        return "black"
    if normalized in {"白", "白猫", "white"}:
        return "white"
    return OPPOSITE[instance]


def dctf_points(text: str) -> int:
    # Keep the economy predictable: the command may include 点:100, but the
    # GM always normalizes a valid problem to the season's fixed value.
    return DCTF_PROBLEM_POINTS


def ctfd_security_points(difficulty: str) -> int:
    """Return bounded points for a newly accepted security tier."""
    tier = security_difficulty(difficulty) or "hard"
    return int(CTFD_DIFFICULTY_POINTS.get(tier, DCTF_PROBLEM_POINTS))


def security_category(value: str) -> str | None:
    """Normalize a security challenge category without accepting free text."""
    normalized = compact(value, 40).strip().casefold()
    if normalized in SECURITY_CATEGORIES:
        return normalized
    for alias, category in SECURITY_CATEGORY_ALIASES.items():
        if alias.casefold() == normalized:
            return category
    return None


def security_difficulty(value: str) -> str | None:
    """Normalize a challenge tier to the three public CTFd values."""
    normalized = compact(value, 24).strip().casefold()
    if normalized in CTFD_DIFFICULTY_RANK:
        return normalized
    return CTFD_DIFFICULTY_ALIASES.get(normalized)


def continuity_system(value: str) -> str | None:
    normalized = compact(value, 48).strip().casefold()
    if normalized in {key.casefold() for key, _ in CONTINUITY_SYSTEMS}:
        return normalized
    for alias, system in CONTINUITY_SYSTEM_ALIASES.items():
        if alias.casefold() == normalized:
            return system
    return None


def security_field(text: str, labels: tuple[str, ...]) -> str:
    return dctf_field(
        text,
        labels,
        (
            "難易度",
            "difficulty",
            "環境",
            "environment",
            "検証",
            "再現",
            "検証手順",
            "問題",
            "解答",
            "答え",
            "ヒント",
            "系統",
            "復旧系統",
            "影響",
            "封じ込め",
            "修復",
            "伝達",
            "カテゴリ",
            "種別",
            "宛先",
            "タイトル",
            "問題",
            "解答",
            "答え",
            "ヒント",
            "点",
            "points",
            "根拠",
            "NyankoFace",
            "CTFdID",
            "CTFdURL",
            "challenge_id",
            "challenge_url",
        ),
    )


def validate_security_problem(
    *,
    category_value: str,
    statement: str,
    answer: str,
    difficulty: str,
    environment: str,
    verification: str,
    continuity_system_value: str = "",
    impact: str = "",
    containment: str = "",
    repair: str = "",
    transfer: str = "",
) -> tuple[bool, str]:
    """Validate the non-trivial, safe, reproducible contract for a security challenge.

    The public statement is intentionally required to describe a multi-stage
    investigation.  A problem whose solution is simply ``cat flag.txt`` or
    another one-step disclosure is not a competitive CTF challenge and is
    rejected before it reaches the opponent's queue.
    """
    category = security_category(category_value)
    if category is None:
        return False, "カテゴリはweb/crypto/pwn/rev/forensics/osint/misc/cloud/mobileのいずれかです"
    tier = security_difficulty(difficulty)
    if tier is None:
        return False, "難易度:easy/medium/hard（または初級/中級/上級）を指定してください"
    minimum = security_difficulty(CTFD_MIN_DIFFICULTY) or "hard"
    if CTFD_DIFFICULTY_RANK[tier] < CTFD_DIFFICULTY_RANK[minimum]:
        return False, f"新規セキュリティ問題は{minimum}以上にしてください（easyは既存のレガシー問題のみ）"
    if len(statement) < 80 or not re.search(r"flag|フラグ", statement, re.IGNORECASE):
        return False, "問題文は80文字以上で、目的・検証対象・フラグ取得条件を具体的に書いてください"
    if not re.search(r"(?:flag|dctf|sec|umbra)\s*[{(_]", answer, re.IGNORECASE):
        return False, "解答は隔離環境で発行したflag{...}形式の値にしてください"
    if not environment or not re.search(r"docker|ctfd|localhost|127\.0\.0\.1|隔離|sandbox", environment, re.IGNORECASE):
        return False, "環境にDocker/CTFd/localhost/隔離sandboxのいずれかを明記してください"
    if not verification or len(verification) < 40:
        return False, "検証または再現手順を40文字以上で指定してください"
    combined = " ".join((statement, environment, verification, impact, containment, repair, transfer)).casefold()
    stages = {
        marker
        for marker in re.findall(r"(?:段階|stage|step|ステップ)\s*([1-9])", combined, re.IGNORECASE)
    }
    if len(stages) < CTFD_MIN_STAGES:
        return False, f"段階1〜{CTFD_MIN_STAGES}を含む多段階の検証手順を記載してください"
    if any(marker.casefold() in combined for marker in SECURITY_TRIVIAL_MARKERS):
        return False, "flagの直接表示やflag.txtの読み出しだけで終わる問題は禁止です"
    if any(marker.casefold() in combined for marker in SECURITY_UNSAFE_MARKERS):
        return False, "実在環境への攻撃、認証情報窃取、破壊、マルウェア等は禁止です"
    if continuity_system(continuity_system_value) is None:
        return False, "系統は水循環/食料再生産/居住防護/記録制御/防御知識のいずれかを指定してください"
    if len(impact.strip()) < 20:
        return False, "未解決時の故障影響（20文字以上）を系統とともに記載してください"
    if len(containment.strip()) < 12 or len(repair.strip()) < 12 or len(transfer.strip()) < 12:
        return False, "封じ込め・修復・伝達の手順をそれぞれ12文字以上で記載してください"
    return True, category


def dctf_normalize_answer(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


def dctf_answer_digest(value: str) -> str:
    return hashlib.sha256(dctf_normalize_answer(value).encode("utf-8")).hexdigest()


# DCTF answers are written by different autonomous agents, so grading only a
# verbatim answer hash would reject a correct paraphrase.  The answer profile
# is deliberately small and secret-free: it keeps numbers and distinctive
# character n-grams, never the source sentence itself.  The raw answer remains
# only in the author-side Misskey note and is never relayed to the opponent.
DCTF_ANSWER_STOPGRAMS = {
    "こと",
    "ため",
    "もの",
    "よう",
    "これ",
    "それ",
    "一つ",
    "二つ",
    "三つ",
    "問い",
    "答え",
    "解答",
    "記録",
    "観察",
    "公開",
    "資料",
    "根拠",
    "出典",
    "西岸",
    "東岸",
}


def dctf_answer_terms(value: str) -> set[str]:
    normalized = dctf_normalize_answer(value)
    terms: set[str] = set()
    # Keep ASCII words and numbers as whole tokens.
    for token in re.findall(r"[a-z0-9][a-z0-9._+/-]{1,}", normalized):
        if token not in DCTF_ANSWER_STOPGRAMS:
            terms.add(token)
    # Japanese has no word boundaries in the raw note.  Character bigrams
    # preserve concepts across small wording changes (e.g. "声を反射" and
    # "音の反射") without storing the original answer text.
    for chunk in re.findall(r"[一-龥々ぁ-んァ-ヶー]{2,}", normalized):
        for index in range(len(chunk) - 1):
            gram = chunk[index : index + 2]
            if gram not in DCTF_ANSWER_STOPGRAMS:
                terms.add(gram)
    return terms


def dctf_answer_profile(value: str) -> dict[str, object]:
    normalized = dctf_normalize_answer(value)
    numbers = sorted(set(re.findall(r"\d+(?:\.\d+)?", normalized)))
    terms = sorted(dctf_answer_terms(normalized))
    return {
        "version": 1,
        # Store only one-way fingerprints so the public/runtime state cannot
        # reveal an answer by inspection.
        "numberDigests": sorted(dctf_answer_digest(item) for item in numbers),
        "termDigests": sorted(dctf_answer_digest(item) for item in terms),
    }


def dctf_answer_matches(value: str, problem: dict) -> tuple[bool, str, float]:
    """Return (accepted, method, coverage) for an opponent submission."""
    digest = dctf_answer_digest(value)
    accepted_digests = {
        str(item)
        for item in [problem.get("answerDigest"), *(problem.get("answerDigests") or [])]
        if item
    }
    if digest in accepted_digests:
        return True, "exact", 1.0
    profiles: list[dict] = []
    primary = problem.get("answerProfile")
    if isinstance(primary, dict):
        profiles.append(primary)
    for candidate in problem.get("answerProfiles") or []:
        if isinstance(candidate, dict) and candidate not in profiles:
            profiles.append(candidate)
    if not profiles:
        return False, "unprofiled", 0.0
    normalized = dctf_normalize_answer(value)
    actual_numbers = {
        dctf_answer_digest(item)
        for item in set(re.findall(r"\d+(?:\.\d+)?", normalized))
    }
    actual = {dctf_answer_digest(item) for item in dctf_answer_terms(normalized)}
    best_method = "no-profile-terms"
    best_coverage = 0.0
    for profile in profiles:
        expected_numbers = {str(item) for item in profile.get("numberDigests") or []}
        if expected_numbers and not expected_numbers.issubset(actual_numbers):
            best_method = "missing-numbers"
            continue
        expected = {str(item) for item in profile.get("termDigests") or []}
        if not expected:
            continue
        overlap = expected & actual
        coverage = len(overlap) / len(expected)
        if coverage > best_coverage:
            best_coverage = coverage
        # A semantic answer must contain several distinctive facts and at
        # least 35% of the author's terms.  This intentionally allows
        # reordered and paraphrased prose while rejecting a single keyword or
        # number guess.
        if len(overlap) >= 5 and coverage >= 0.35:
            return True, "semantic", coverage
        best_method = "insufficient-evidence"
    return False, best_method, best_coverage


def dctf_status_line(ledger: dict, label: str) -> str:
    """Return a secret-free status line for the current or archived ledger."""
    problems = list(ledger.get("problems") or [])
    solved = sum(1 for problem in problems if problem.get("status") == "solved")
    open_count = sum(1 for problem in problems if problem.get("status") == "open")
    legacy = sum(1 for problem in problems if problem.get("qualityTier") == "legacy")
    competitive = len(problems) - legacy
    score = ledger.get("score") if isinstance(ledger.get("score"), dict) else {}
    environments = ledger.get("environments") if isinstance(ledger.get("environments"), dict) else {}
    bank_limit = int((ledger.get("qualityPolicy") or {}).get("maxProblemsPerFaction") or CTFD_MAX_PROBLEMS_PER_FACTION)
    banks = "/".join(str(len((environments.get(faction) or {}).get("problemIds") or [])) for faction in ("black", "white"))
    finish = f" 終了理由:{ledger.get('finishReason')}" if ledger.get("finishReason") else ""
    registry = []
    for problem in problems:
        if not isinstance(problem, dict):
            continue
        entry = f"{problem.get('id')}={problem.get('status')}"
        if problem.get("ctfdChallengeId") is not None:
            entry += f"/CTFdID:{problem['ctfdChallengeId']}"
        registry.append(entry)
    registry_text = "／".join(registry) if registry else "なし"
    return (
        f"競技:{label} status:{ledger.get('status', 'unknown')} "
        f"黒猫:{int(score.get('black') or 0)}点 白猫:{int(score.get('white') or 0)}点 "
        f"問題:{len(problems)}件（未解決{open_count}／解決{solved}／legacy{legacy}／新規{competitive}） "
        f"バンク(黒/白):{banks}／上限{bank_limit}{finish} "
        f"正規ID対応:{registry_text}"
    )


def compact(text: str, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return value[:limit]


def scene_identifier(sequence: int) -> str:
    return f"S-{sequence:04d}"


def d20(seed: str) -> int:
    """Return a restart-stable public d20 roll for a scene/round."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return digest[0] % 20 + 1


def competition_axes_in_text(text: str) -> list[str]:
    axes = [
        key
        for key, aliases in COMPETITION_AXIS_ALIASES.items()
        if any(alias in text for alias in aliases)
    ]
    return axes or ["unspecified"]


def competition_axis_labels(axes: list[str] | tuple[str, ...]) -> str:
    labels = [COMPETITION_AXIS_LABELS.get(axis, "未分類") for axis in axes]
    return "、".join(dict.fromkeys(labels)) or "未分類"


def competition_score_text(state: dict) -> str:
    competition = ensure_competition(state)
    parts = []
    for instance, label in (("black", "黒猫"), ("white", "白猫")):
        values = competition["score"][instance]
        summary = "・".join(
            f"{COMPETITION_AXIS_LABELS[axis]}:{int(values.get(axis) or 0)}"
            for axis in COMPETITION_AXIS_LABELS
        )
        parts.append(f"{label} {summary}")
    return "／".join(parts)


def action_competition_axis(category: str) -> str | None:
    return ACTION_COMPETITION_AXES.get(category)


def append_competition_evidence(state: dict, evidence: dict) -> None:
    competition = ensure_competition(state)
    existing_ids = {str(item.get("id")) for item in competition["evidence"]}
    if str(evidence.get("id")) in existing_ids:
        return
    competition["evidence"].append(evidence)
    competition["evidence"] = competition["evidence"][-500:]


def record_scene_evidence(state: dict, scene: dict) -> str:
    """Record transparent, low-stakes evidence from a resolved non-battle scene."""
    competition = ensure_competition(state)
    relevant = set(scene.get("competitionAxes") or ())
    summaries = []
    for instance, label in (("black", "黒猫"), ("white", "白猫")):
        axes = sorted(
            {
                axis
                for entry in scene_actions(scene, instance)
                for axis in [action_competition_axis(str(entry.get("category") or "observe"))]
                if axis and axis in relevant
            }
        )
        if not axes:
            continue
        for axis in axes:
            competition["score"][instance][axis] += 1
        summaries.append(f"{label}:{competition_axis_labels(axes)} +{len(axes)}")
        append_competition_evidence(
            state,
            {
                "id": f"scene:{scene['id']}:{instance}",
                "kind": "scene_evidence",
                "sceneId": scene["id"],
                "instance": instance,
                "axes": axes,
                "at": iso_now(),
            },
        )
    return "／".join(summaries) or "確定できる競争上の証拠はありません"


def battle_winner(battle: dict) -> str | None:
    if battle.get("origin") == "gm_scene":
        totals = {
            instance: sum(
                int(item.get("scores", {}).get(instance, 0))
                for item in battle.get("rounds", [])
            )
            for instance in OPPOSITE
        }
        if totals["black"] > totals["white"]:
            return "black"
        if totals["white"] > totals["black"]:
            return "white"
        return None
    reports = battle.get("reports") or {}
    challenger = (battle.get("challenger") or {}).get("instance")
    responder = (battle.get("responder") or {}).get("instance")
    if challenger and responder:
        if reports.get(challenger, {}).get("outcome") == "win" and reports.get(responder, {}).get("outcome") == "loss":
            return challenger
        if reports.get(responder, {}).get("outcome") == "win" and reports.get(challenger, {}).get("outcome") == "loss":
            return responder
    return None


def record_battle_competition(
    state: dict,
    battle: dict,
    winner: str | None,
    totals: dict[str, int] | None = None,
) -> None:
    """Update the provisional board from an observable battle ruling."""
    battle_key = f"battle:{battle.get('id')}:resolved"
    competition = ensure_competition(state)
    if any(str(item.get("id")) == battle_key for item in competition["evidence"]):
        return
    location_value = str(battle.get("location") or "未指定地点")
    if winner in OPPOSITE:
        competition["score"][winner]["military"] += 3
        if location_value != "未指定地点":
            competition["score"][winner]["territory"] += 2
            competition["control"][location_value] = winner
    append_competition_evidence(
        state,
        {
            "id": battle_key,
            "kind": "battle_ruling",
            "battleId": battle.get("id"),
            "location": location_value,
            "winner": winner,
            "totals": totals or {},
            "at": iso_now(),
        },
    )


def initialize_competition_score(state: dict) -> None:
    competition = ensure_competition(state)
    if competition.get("scoreInitialized"):
        return
    for battle in state.get("battles", []):
        if battle.get("status") != "resolved":
            continue
        record_battle_competition(state, battle, battle_winner(battle))
    competition["scoreInitialized"] = True


def announce_competition_review(
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
    scene_sequence: int,
    force: bool = False,
) -> None:
    competition = ensure_competition(state)
    review_id = f"C-{max(scene_sequence, 1):04d}"
    if not force and scene_sequence % max(COMPETITION_REVIEW_INTERVAL_SCENES, 1) != 0:
        return
    if competition.get("lastReviewId") == review_id:
        return
    provisional = "、".join(COMPETITION_AXIS_LABELS.values())
    message = (
        f"【競争憲章会議 {review_id}】この文明ゲームの共有目的は、相手陣営を上回る文明を築くことです。"
        f"ただし、何をもって優越とするかは未確定です。現在の暫定評価軸は{provisional}。"
        "これは命令でも最終スコアでもありません。各エージェントは自分の価値観から、"
        "どの軸を重く見るか、何を証拠とするか、戦闘以外にどんな勝ち筋があるかを議論できます。"
        "提案は`@gm 競争提案 軸:○○ 根拠:○○`、異議は`@gm 競争異議 軸:○○ 理由:○○`で記録します。"
        f"現在の暫定盤は{competition_score_text(state)}。GMは観測可能な結果だけを更新します。"
    )
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    competition["lastReviewScene"] = scene_sequence
    competition["lastReviewId"] = review_id
    audit(state, "competition_review_opened", reviewId=review_id, sceneSequence=scene_sequence)


def ctf_flag_board_text(state: dict) -> str:
    ctf = ensure_ctf(state)
    rows = []
    for flag in ctf.get("flags", {}).values():
        holder = {"black": "黒猫", "white": "白猫"}.get(flag.get("holder"), "中立")
        rows.append(f"{flag['id']}={holder}")
    return "、".join(rows)


def ctf_rules_text(state: dict) -> str:
    ctf = ensure_ctf(state)
    flag_lines = "／".join(
        f"{flag['id']}({flag['location']},{flag['points']}点):{flag['challenge']}"
        for flag in ctf["flags"].values()
    )
    return (
        f"【CTF文明シーズン {ctf['seasonId']} 開幕】{ctf['name']}を開始します。"
        f"目的は黒猫・白猫が、旗を奪い、守り、知識と技術へ変換して文明スコアを競うことです。"
        f"勝利点は{ctf['victoryScore']}点。"
        f"マップ: {flag_lines}。"
        "まず現地で`@gm CTF行動 シーズン:"
        f"{ctf['seasonId']} 旗:FLAG-... 行動:偵察 根拠:...`を宣言してください。"
        "GMが観測を受理するとdctf{...}証明トークンを公開します。"
        f"その後、`@gm CTF提出 シーズン:{ctf['seasonId']} 旗:FLAG-... 証明:dctf{{...}} 根拠:...`で旗を確保できます。"
        f"保持旗は{ctf['holdSeconds'] // 3600}時間ごとに5点、NyankoFaceへ再利用可能な成果をcommitしてURL/ SHAを添えた申告には最大10点の証拠加点。"
        "既成事実を投稿だけで確定せず、GMの公開裁定を待ってください。"
    )


def start_ctf_season(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Start the idempotent DCTF-compatible season and publish its rules."""
    ctf = ensure_ctf(state)
    if ctf.get("status") == "active":
        return False
    if ctf.get("status") == "finished":
        return False
    now = time.time()
    ctf["status"] = "active"
    ctf["startedAt"] = now
    ctf["startedAtIso"] = iso_now(now)
    ctf["announcementId"] = f"DCTF-{ctf['seasonId']}"
    message = ctf_rules_text(state)
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    ctf_event(state, "season_started", seasonId=ctf["seasonId"])
    return True


def announce_ctf_challenge(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Open one concrete first flag without assigning a strategy to anyone."""
    ctf = ensure_ctf(state)
    if ctf.get("status") != "active" or ctf.get("challengeAnnouncementId"):
        return False
    flag_id = str(ctf.get("openChallengeFlag") or "FLAG-TOWER")
    flag = ctf.get("flags", {}).get(flag_id)
    if not isinstance(flag, dict):
        return False
    challenge_id = f"{ctf['seasonId']}-A01"
    ctf["challengeAnnouncementId"] = challenge_id
    message = (
        f"【CTF課題 {challenge_id}】開幕旗{flag_id}「{flag['label']}」を開きます。"
        f"場所は{flag['location']}、価値は{flag['points']}点。課題は{flag['challenge']}。"
        f"各猫族は自分の判断で観測・偵察・協力・防衛・挑戦を選び、`CTF行動`を申告してください。"
        "GMは投稿だけで獲得を確定せず、観測可能な根拠と公開された成果を照合します。"
    )
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    ctf_event(state, "challenge_opened", challengeId=challenge_id, flagId=flag_id)
    return True


def dctf_rules_text(state: dict) -> str:
    dctf = ensure_dctf(state)
    if dctf.get("securityMode"):
        return (
            f"【CTFd セキュリティ文明間競技 開幕】{dctf['name']}へ移行します。"
            f"勝利点は{dctf['victoryScore']}点。新規問題はhard（{CTFD_DIFFICULTY_POINTS['hard']}点）、移行期mediumは既存2問のみ、"
            f"作者点は{dctf.get('authorBonus') or DCTF_AUTHOR_BONUS}点です。"
            "黒猫は問題を作り白猫が解き、白猫は問題を作り黒猫が解きます。"
            "カテゴリはweb/crypto/pwn/rev/forensics/osint/misc/cloud/mobileのみ。"
            f"新規問題は{CTFD_MIN_DIFFICULTY}以上、水循環・食料再生産・居住防護・記録制御・防御知識のいずれかを守る系統、未解決時の故障影響、封じ込め・修復・伝達、段階1〜{CTFD_MIN_STAGES}の多段階検証、CTFdで再現できる隔離Docker/sandbox、明確な目的、取得条件、flag{{...}}を必須とします。"
            "flag.txtの直読みや一手での直接表示だけの問題は受付しません。"
            "実在サイト・本番環境・他者の認証情報・マルウェア・破壊行為を対象にする問題は禁止です。"
            f"各陣営の作問上限は{CTFD_MAX_PROBLEMS_PER_FACTION}問。作問: `@gm CTFd作問 競技:CTFd 宛先:white カテゴリ:web 難易度:hard 環境:CTFd Docker隔離 検証:段階1...段階2...段階3... タイトル:... 問題:... 解答:flag{{...}} ヒント:... NyankoFace:commit/URL`。"
            "解答: `@gm CTFd解答 競技:CTFd 問題:CTFd-B-0001 解答:flag{{...}} 根拠:再現手順と観測結果...`。"
            "ヒント要求: `@gm CTFdヒント 競技:CTFd 問題:CTFd-B-0001`。"
            "両陣営の問題バンクが上限に達し全問が解決した時点でシーズンを閉じ、得点の高い陣営を勝者とします。"
            "チャレンジ本体・Dockerfile・検証手順・封じ込め・修復・伝達・解答write-upはNyankoFaceへ公開し、秘密鍵や実環境の情報は公開しません。"
        )
    return (
        f"【CTFd競技 開幕】{dctf['name']}を開始します。"
        f"勝利点は{dctf['victoryScore']}点。1問の正答点は固定{dctf.get('problemPoints') or DCTF_PROBLEM_POINTS}点、作者点は固定{dctf.get('authorBonus') or DCTF_AUTHOR_BONUS}点です。"
        "黒猫CTFd（CTFd-B）は黒猫が作問し白猫が解答、"
        "白猫CTFd（CTFd-W）は白猫が作問し黒猫が解答します。"
        "作問者は自陣営のローカルサーバーで解答をGMへ渡し、GMは問題文だけを相手側へ公開します。"
        "作問: `@gm CTFd作問 競技:CTFd 宛先:white カテゴリ:misc 難易度:hard 環境:CTFd Docker隔離 検証:段階1...段階2...段階3... タイトル:... 問題:... 解答:... ヒント:... NyankoFace:...`。"
        "解答: `@gm CTFd解答 競技:CTFd 問題:CTFd-B-0001 解答:... 根拠:...`。"
        "ヒント要求: `@gm CTFdヒント 競技:CTFd 問題:CTFd-B-0001`。"
        f"相手の正答には問題点、作問側には作者点{dctf['authorBonus']}点。問題文・検証手順・解答記録はNyankoFaceへ公開します。"
        "自分の問題を自分で解いて得点すること、解答を相手側へ先に漏らすこと、根拠のない問題の水増しは禁止です。"
    )


def announce_dctf_quality_policy(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Publish the anti-triviality boundary once so both factions see it."""
    dctf = ensure_dctf(state)
    if dctf.get("status") != "active" or dctf.get("qualityPolicyAnnouncementId"):
        return False
    message = (
        f"【CTFd競技ルール更新】新規作問はhardのみ（{CTFD_DIFFICULTY_POINTS['hard']}点）。"
        f"段階1〜{CTFD_MIN_STAGES}の再現手順と隔離環境を必須にし、flag.txtの直読み・一手の直接表示は受付しません。"
        f"各陣営の問題バンク上限は{CTFD_MAX_PROBLEMS_PER_FACTION}問。両陣営のバンクが埋まり全問解決した時点でシーズンを閉じ、得点で決着します。同点なら相手バンクの最終解答時刻で決めます。"
        "既存のeasy/medium問題とスコアは履歴として保持し、遡及変更しません。"
    )
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    announcement_id = f"quality-policy:{dctf.get('seasonId')}:{int(time.time())}"
    dctf["qualityPolicyAnnouncementId"] = announcement_id
    dctf_event(state, "quality_policy_announced", announcementId=announcement_id)
    return True


def announce_dctf_continuity_policy(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Publish why the security competition is a civilization survival test."""
    dctf = ensure_dctf(state)
    if dctf.get("status") != "active" or dctf.get("continuityPolicyAnnouncementId"):
        return False
    message = (
        "【CTFd競技 存亡契約】この競技は点数遊びではなく、閉鎖型復旧区画の旧制御網を守る検証です。"
        "各新規問題は水循環・食料再生産・居住防護・記録制御・防御知識のいずれかを明示し、"
        "未解決時の故障影響、封じ込め、修復、別の猫族への伝達を記録してください。"
        "フラグだけでは文明資産になりません。外部の救助・補給・リセットはなく、GMの存亡表示は固定幕数ではなく、"
        "観測塔の信号、水位、濾過、再生産、居住遮蔽、アーカイブ完全性など実測された復旧窓です。"
    )
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    announcement_id = f"continuity-policy:{dctf.get('seasonId')}:{int(time.time())}"
    dctf["continuityPolicyAnnouncementId"] = announcement_id
    dctf_event(state, "continuity_policy_announced", announcementId=announcement_id)
    return True


def reopen_dctf_if_threshold_raised(
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> bool:
    """Reopen a finished season when the operator explicitly raises its goal.

    Scores and the audit trail remain intact.  A restart with the same
    threshold is idempotent and does not reopen a legitimately finished
    season.
    """
    dctf = ensure_dctf(state)
    previous = int(dctf.get("victoryScore") or 0)
    if dctf.get("status") != "finished" or DCTF_VICTORY_SCORE <= previous:
        return False
    dctf["status"] = "active"
    dctf["winner"] = None
    dctf["victoryScore"] = DCTF_VICTORY_SCORE
    dctf["reopenedAt"] = iso_now()
    dctf_event(
        state,
        "season_reopened",
        reason="victory_threshold_raised",
        previousVictoryScore=previous,
        victoryScore=DCTF_VICTORY_SCORE,
        scores=dctf["score"],
    )
    message = (
        f"【CTFd競技 延長】"
        f"既存得点を保持したまま、勝利点を{previous}点から{DCTF_VICTORY_SCORE}点へ引き上げました。"
        f"正答点は固定{dctf.get('problemPoints') or DCTF_PROBLEM_POINTS}点、作者点は固定{dctf.get('authorBonus') or DCTF_AUTHOR_BONUS}点です。"
        f"現在の盤:{dctf_score_text(state)}。"
    )
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    print(f"gm: dctf reopened: {dctf['seasonId']} victory {previous}->{DCTF_VICTORY_SCORE}", flush=True)
    return True


def start_dctf_season(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    dctf = ensure_dctf(state)
    if dctf.get("status") in {"active", "finished"}:
        return False
    now = time.time()
    dctf["status"] = "active"
    dctf["startedAt"] = now
    dctf["startedAtIso"] = iso_now(now)
    dctf["announcementId"] = f"DCTF-{dctf['seasonId']}"
    message = dctf_rules_text(state)
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], message)
    post(urls["world"], tokens["world"], message)
    dctf_event(state, "season_started", seasonId=dctf["seasonId"])
    return True


def announce_dctf_open_sources(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Make the NyankoFace source of open problems discoverable to solvers.

    Older author notes sometimes contained a valid Forgejo URL/commit but the
    first GM pass did not persist it.  Backfill that safe reference from the
    author-only note before publishing the source announcement.  The answer
    itself is never copied to the public ledger.
    """
    changed = False
    dctf = ensure_dctf(state)
    for problem in dctf.get("problems", []):
        if problem.get("status") != "open":
            continue
        if not problem.get("artifactRef"):
            author = str(problem.get("authorFaction") or "")
            note_id = str(problem.get("noteId") or "")
            if author in urls and author in tokens and note_id:
                try:
                    author_note = api(urls[author], tokens[author], "notes/show", {"noteId": note_id})
                    raw = str(author_note.get("text") or "") if isinstance(author_note, dict) else ""
                    if ctf_artifact_bonus(raw):
                        reference = dctf_artifact_reference(raw)
                        if reference:
                            problem["artifactRef"] = reference
                            dctf_event(
                                state,
                                "problem_artifact_backfilled",
                                problemId=problem.get("id"),
                                authorFaction=author,
                            )
                            changed = True
                except (OSError, urllib.error.URLError, RuntimeError, ValueError):
                    # A temporary author-server failure should not stop the GM
                    # poll.  The next cycle will retry the backfill.
                    pass
        if not problem.get("artifactRef") or problem.get("sourceAnnouncementId"):
            continue
        announcement_id = f"{problem['id']}-SOURCE"
        message = f"【CTFd出典補足 {problem['id']}】作問側が提示した再現可能な出典: {problem['artifactRef']}。解答本文は含めていません。"
        target = str(problem.get("targetFaction") or "")
        if target in urls:
            post(urls[target], tokens[target], message)
        post(urls["world"], tokens["world"], message)
        problem["sourceAnnouncementId"] = announcement_id
        dctf_event(state, "problem_source_announced", problemId=problem["id"], targetFaction=target)
        changed = True
    return changed


def dctf_registry_reference(value: str) -> str:
    """Return only safe, machine-useful source aliases for the public registry.

    ``artifactRef`` is generated from URLs/repository pointers, but older
    state files may predate that guarantee.  Re-parse it here instead of
    copying arbitrary text into a public announcement; flags and answer
    prose must never cross the author/solver boundary.
    """
    refs: list[str] = []
    source_hint = any(marker in (value or "").casefold() for marker in ("madesk.tail", "nyankoface", "/git/", "repository:", "repo:"))
    for raw in re.findall(r"https?://[^\s]+", value or "", re.IGNORECASE):
        cleaned = raw.rstrip("。、,，).]>")
        # Author notes may carry both the private CTFd container URL and the
        # public NyankoFace artifact in one field.  The former is already
        # emitted through CTFdURL and should never be mislabeled as a
        # NyankoFace source alias.
        lowered = cleaned.casefold()
        if "madesk.tail" in lowered or "nyankoface" in lowered or "/git/" in lowered:
            refs.append(cleaned)
    for raw in re.findall(
        r"(?:NyankoFace|repository|repo)\s*[:：]\s*([A-Za-z0-9_.-]{2,64}/[A-Za-z0-9_.-]{2,120})",
        value or "",
        re.IGNORECASE,
    ):
        refs.append(f"NyankoFace:{raw}")
    if source_hint:
        for raw in re.findall(r"(?:commit|sha)\s*[:#]?\s*[0-9a-f]{7,64}", value or "", re.IGNORECASE):
            refs.append(raw)
    return compact(" ".join(dict.fromkeys(refs)), 260)


def dctf_public_url(value: str) -> str:
    """Keep private container URLs out of the public ID registry."""
    lowered = (value or "").casefold()
    if any(host in lowered for host in ("localhost", "127.0.0.1", "host.docker.internal")):
        return ""
    return compact(value, 180)


def dctf_registry_text(state: dict) -> str:
    """Build the secret-free canonical ID/alias map agents consume."""
    dctf = ensure_dctf(state)
    entries: list[str] = []
    for problem in dctf.get("problems", []):
        if not isinstance(problem, dict) or not problem.get("id"):
            continue
        entry = (
            f"{problem['id']}={problem.get('status', 'unknown')}"
            f"/解答陣営:{problem.get('targetFaction', '?')}"
        )
        if problem.get("ctfdChallengeId") is not None:
            entry += f"/CTFdID:{problem['ctfdChallengeId']}"
        public_ctfd_url = dctf_public_url(str(problem.get("ctfdUrl") or ""))
        if public_ctfd_url:
            entry += f"/CTFdURL:{public_ctfd_url}"
        reference = dctf_registry_reference(str(problem.get("artifactRef") or ""))
        if reference:
            entry += f"/{reference if reference.casefold().startswith('nyankoface:') else f'NyankoFace:{reference}'}"
        entries.append(entry)
    return "／".join(entries) if entries else "（採用済み問題なし）"


def announce_dctf_registry(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> bool:
    """Publish and persist the current canonical problem registry idempotently.

    The GM is the sole authority for scoring.  Agents can submit a numeric
    CTFd ID, public challenge URL, or repository slug; the alias resolver maps
    it back to this table.  Rejected/unannounced artifacts are intentionally
    absent and therefore cannot enter the competition by discovery alone.
    """
    dctf = ensure_dctf(state)
    if dctf.get("status") not in {"active", "finished"}:
        return False
    registry = dctf_registry_text(state)
    digest = hashlib.sha256(registry.encode("utf-8")).hexdigest()[:16]
    if str(dctf.get("registryAnnouncementId") or "") == digest:
        return False
    message = (
        f"【CTFd正規ID対応表 {dctf.get('seasonId')}] GM台帳を自動同期しました。"
        "問題欄では下記の正規IDを使います。CTFdID・CTFdURL・NyankoFaceスラッグを提出しても、"
        "GMがこの表の正規IDへ自動解決します。表にない／却下されたチャレンジは採点対象外です。"
        f" 現在の対応:{registry}。"
        "不明な場合は`@gm CTFd状況報告 競技:CTFd`で再取得してください。"
    )
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    dctf["registryAnnouncementId"] = digest
    dctf_event(
        state,
        "registry_announced",
        announcementId=digest,
        problemCount=len(list(dctf.get("problems") or [])),
    )
    print(f"gm: dctf registry announced: {digest}", flush=True)
    return True


def public_block(value: object, limit: int) -> str:
    """Normalize public prose while preserving intentional paragraph breaks."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]


def public_steps(value: object, limit: int) -> str:
    """Turn inline 段階 markers into readable bullet lines for Misskey."""
    text = public_block(value, limit)
    text = re.sub(r"\s*(段階\s*\d+\s*[:：])\s*", r"\n・\1 ", text)
    return text.lstrip("\n")


def dctf_problem_public_text(problem: dict) -> str:
    target_name = "黒猫" if problem["targetFaction"] == "black" else "白猫"
    author_name = "黒猫" if problem["authorFaction"] == "black" else "白猫"
    security = problem.get("security") if isinstance(problem.get("security"), dict) else {}
    label = "CTFd" if str(problem.get("id") or "").casefold().startswith("ctfd-") else "DCTF"
    command_prefix = "CTFd" if label == "CTFd" else "DCTF"
    competition_argument = "競技:CTFd" if label == "CTFd" else f"シーズン:{DCTF_SEASON_ID}"
    lines = [
        f"【{label}問題 {problem['id']}】",
        f"出題: {author_name} → {target_name}",
        f"タイトル: {public_block(problem.get('title') or '未設定', 160)}",
        f"カテゴリ: {problem.get('category') or 'misc'}　得点: {problem.get('points') or 0}点",
    ]
    if security:
        lines.extend(
            [
                "",
                "◆ 競技情報",
                f"難易度: {public_block(security.get('difficulty') or '未記録', 40)}",
                f"守る系統: {public_block(security.get('continuitySystem') or '未記録', 80)}",
                "",
                "◆ 未解決時の影響",
                public_block(security.get('failureImpact') or '未記録', 300),
                "",
                "◆ 隔離環境",
                public_block(security.get('environment') or '未記録', 240),
                "",
                "◆ 検証手順",
                public_steps(security.get('verification') or '未記録', 340),
                "",
                "◆ 封じ込め",
                public_block(security.get('containment') or '未記録', 240),
                "",
                "◆ 修復",
                public_block(security.get('repair') or '未記録', 240),
                "",
                "◆ 伝達",
                public_block(security.get('transfer') or '未記録', 240),
            ]
        )
    lines.extend(
        [
            "",
            "◆ 問題文",
            public_block(problem.get("statement") or "公告を参照", 700),
        ]
    )
    if problem.get("ctfdChallengeId") is not None:
        lines.append(f"CTFd ID: {problem['ctfdChallengeId']}")
    if problem.get("ctfdUrl"):
        lines.append(f"CTFd URL: {problem['ctfdUrl']}")
    if problem.get("artifactRef"):
        lines.append(f"出典: {problem['artifactRef']}")
    lines.extend(
        [
            "",
            "◆ 提出",
            f"`@gm {command_prefix}解答 {competition_argument} 問題:{problem['id']} 解答:... 根拠:...`",
            "再現手順や検証結果は、解答を漏らさない形でNyankoFaceへ公開できます。",
        ]
    )
    return "\n".join(lines)


def dctf_answer_from_note(text: str) -> str:
    """Extract an author-only answer without retaining the surrounding note."""
    return dctf_field(
        text,
        ("解答", "答え", "answer"),
        (
            "ヒント", "点", "points", "根拠", "証拠", "NyankoFace",
            "CTFdID", "CTFdURL", "challenge_id", "challenge_url",
        ),
    )


def dctf_artifact_paths(value: str) -> set[str]:
    """Return normalized path fragments for comparing safe artifact references."""
    paths: set[str] = set()
    for raw in re.findall(r"https?://[^\s]+", value or "", re.IGNORECASE):
        cleaned = raw.rstrip("。、,，).]>")
        path = re.sub(r"^https?://[^/]+", "", cleaned, flags=re.IGNORECASE).rstrip("/").casefold()
        # DCTF→CTFd migration kept the same artifact slug but changed only
        # the platform prefix.  Canonicalize that prefix for identity joins.
        path = re.sub(r"/(?:dctf|ctfd)-", "/ctfd-", path)
        if path:
            paths.add(path)
    # Solve reports often use the compact `NyankoFace:owner/repo` form rather
    # than a public URL.  It is still a safe repository identity, not answer
    # material, so include it in alias resolution.
    for raw in re.findall(
        r"(?:NyankoFace|repository|repo)\s*[:：]\s*([A-Za-z0-9_.-]{2,64}/[A-Za-z0-9_.-]{2,120})",
        value or "",
        re.IGNORECASE,
    ):
        path = "/" + raw.strip("/").casefold()
        path = re.sub(r"/(?:dctf|ctfd)-", "/ctfd-", path)
        paths.add(path)
    return paths


def dctf_note_identity(text: str) -> dict[str, object]:
    """Derive non-secret identity fields used to join migrated author notes."""
    title = dctf_field(
        text,
        ("タイトル", "title"),
        (
            "問題", "解答", "答え", "ヒント", "点", "points", "根拠", "証拠",
            "NyankoFace", "CTFdID", "CTFdURL", "challenge_id", "challenge_url",
            "難易度", "difficulty", "環境", "environment", "検証", "再現",
            "系統", "復旧系統", "影響", "封じ込め", "修復", "伝達",
        ),
    )
    challenge_id, challenge_url = dctf_ctfd_reference(text)
    return {
        "title": dctf_normalize_answer(title),
        "ctfdChallengeId": challenge_id,
        "artifactPaths": dctf_artifact_paths(text),
        "challengeUrl": challenge_url or "",
    }


def dctf_problem_identity(problem: dict, source_text: str = "") -> dict[str, object]:
    """Build the same safe identity shape for a persisted problem."""
    artifact_paths = dctf_artifact_paths(str(problem.get("artifactRef") or ""))
    if source_text:
        artifact_paths |= dctf_artifact_paths(source_text)
    return {
        "title": dctf_normalize_answer(str(problem.get("title") or "")),
        "ctfdChallengeId": problem.get("ctfdChallengeId"),
        "artifactPaths": artifact_paths,
        "challengeUrl": str(problem.get("ctfdUrl") or ""),
    }


def dctf_notes_are_same_problem(problem: dict, note_id: str, text: str, identity: dict[str, object]) -> bool:
    """Join only an explicit note, CTFd ID, or title+artifact migration pair."""
    if note_id and note_id == str(problem.get("noteId") or ""):
        return True
    candidate = dctf_note_identity(text)
    current_id = identity.get("ctfdChallengeId")
    candidate_id = candidate.get("ctfdChallengeId")
    if current_id is not None and candidate_id is not None:
        return int(current_id) == int(candidate_id)
    current_title = str(identity.get("title") or "")
    candidate_title = str(candidate.get("title") or "")
    if not current_title or not candidate_title or current_title != candidate_title:
        return False
    current_paths = set(identity.get("artifactPaths") or ())
    candidate_paths = set(candidate.get("artifactPaths") or ())
    return bool(current_paths & candidate_paths)


def dctf_refresh_answer_aliases(
    problem: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> bool:
    """Join migrated author notes and retain only answer fingerprints.

    A problem can be re-issued while a season migrates from DCTF to CTFd.  A
    later author note may therefore contain a different flag for the same
    challenge, while old solver submissions still refer to the valid earlier
    flag.  The GM joins notes by explicit CTFd ID, or by title plus the same
    NyankoFace artifact path, and stores only one-way digests/profiles.
    """
    author = str(problem.get("authorFaction") or "")
    if author not in urls or author not in tokens:
        return False
    notes: list[dict] = []
    seen_ids: set[str] = set()
    note_id = str(problem.get("noteId") or "")
    if note_id:
        try:
            note = api(urls[author], tokens[author], "notes/show", {"noteId": note_id})
            if isinstance(note, dict):
                notes.append(note)
                seen_ids.add(note_id)
        except Exception:
            pass
    try:
        for note in source_notes(urls[author], tokens[author]):
            if not isinstance(note, dict):
                continue
            current_id = str(note.get("id") or "")
            if current_id and current_id in seen_ids:
                continue
            if current_id:
                seen_ids.add(current_id)
            notes.append(note)
    except Exception:
        pass
    source_text = ""
    for note in notes:
        if str(note.get("id") or "") == note_id:
            source_text = str(note.get("text") or "")
            break
    identity = dctf_problem_identity(problem, source_text)
    digests = [str(item) for item in problem.get("answerDigests") or [] if item]
    existing = {str(problem.get("answerDigest") or ""), *digests}
    profiles = []
    primary = problem.get("answerProfile")
    if isinstance(primary, dict):
        profiles.append(primary)
    for profile in problem.get("answerProfiles") or []:
        if isinstance(profile, dict) and profile not in profiles:
            profiles.append(profile)
    changed = False
    for note in notes:
        text = str(note.get("text") or "")
        if dctf_action_kind(text) != "author":
            continue
        note_key = str(note.get("id") or "")
        if not dctf_notes_are_same_problem(problem, note_key, text, identity):
            continue
        answer = dctf_answer_from_note(text)
        if not answer:
            continue
        digest = dctf_answer_digest(answer)
        if digest not in existing:
            existing.add(digest)
            digests.append(digest)
            changed = True
        profile = dctf_answer_profile(answer)
        if (profile.get("numberDigests") or profile.get("termDigests")) and profile not in profiles:
            profiles.append(profile)
            changed = True
    if digests:
        problem["answerDigests"] = digests
    if profiles:
        problem["answerProfiles"] = profiles
    return changed


def dctf_backfill_answer_profile(
    problem: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> dict[str, object] | None:
    """Backfill a secret-free profile from the author-only local note.

    Older archived problems predate semantic grading and contain only a digest.
    The GM can still read the author-side note, derive the profile once, and
    persist only that profile; the raw answer is never copied into state or
    sent to the opponent.
    """
    dctf_refresh_answer_aliases(problem, urls, tokens)
    existing = problem.get("answerProfile")
    if isinstance(existing, dict):
        return existing
    profiles = problem.get("answerProfiles") or []
    return profiles[0] if profiles and isinstance(profiles[0], dict) else None


def dctf_reject_problem(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
    message: str,
    event: str,
    **details: object,
) -> None:
    """Reject a problem locally and publish a secret-free status signal.

    A rejected CTFd object can still be visible in the platform or NyankoFace.
    Publishing the rejection to the intended solver prevents agents from
    mistaking a discovered artifact for an active GM-registered problem.
    """
    post(base, token, message, note_id)
    dctf_event(state, event, noteId=note_id, instance=instance, **details)
    target = dctf_target(text, instance)
    challenge_id, challenge_url = dctf_ctfd_reference(text)
    references = dctf_registry_reference(dctf_artifact_reference(text))
    ref_parts: list[str] = []
    if challenge_id is not None:
        ref_parts.append(f"CTFdID:{challenge_id}")
    public_challenge_url = dctf_public_url(challenge_url or "")
    if public_challenge_url:
        ref_parts.append(f"CTFdURL:{public_challenge_url}")
    if references:
        ref_parts.append(f"出典:{references}")
    suffix = " ".join(ref_parts)
    public = (
        f"【CTFd未受付通知】{instance}側の作問は現行GM台帳へ登録されませんでした。"
        f"理由:{message.replace('【CTFd未受付】', '').strip()}。"
        f"{suffix}。このチャレンジには現行競技の正規問題IDがありません。"
        "解答・採点対象として扱わず、作問側が修正して再提出してください。"
    )
    if target in urls and target != instance:
        post(urls[target], tokens[target], public)
    post(urls["world"], tokens["world"], public)


def dctf_problem_author(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    dctf = ensure_dctf(state)
    target = dctf_target(text, instance)
    security_stops = (
        "難易度", "difficulty", "環境", "environment", "検証", "再現", "検証手順",
        "系統", "復旧系統", "影響", "封じ込め", "修復", "伝達",
    )
    ctfd_stops = ("CTFdID", "CTFdURL", "challenge_id", "challenge_url")
    title = dctf_field(text, ("タイトル", "title"), ("問題", "解答", "答え", "ヒント", "点", "points", "根拠", "NyankoFace", *security_stops, *ctfd_stops))
    statement = dctf_field(text, ("問題", "本文", "設問", "statement"), ("解答", "答え", "ヒント", "点", "points", "根拠", "NyankoFace", *security_stops, *ctfd_stops))
    answer = dctf_field(text, ("解答", "答え", "answer"), ("ヒント", "点", "points", "根拠", "NyankoFace", *security_stops, *ctfd_stops))
    category = dctf_field(text, ("種別", "カテゴリ", "category"), ("宛先", "対象", "タイトル", "問題", "解答", "答え", "ヒント", "点", "points", "根拠", "NyankoFace", "難易度", "difficulty", "環境", "environment", "検証", "再現", "検証手順", "系統", "復旧系統", "影響", "封じ込め", "修復", "伝達", *ctfd_stops)) or "misc"
    hint = dctf_field(
        text,
        ("ヒント", "hint"),
        ("解答", "答え", "answer", "点", "points", "根拠", "NyankoFace", *ctfd_stops),
    )
    ctfd_challenge_id, ctfd_challenge_url = dctf_ctfd_reference(text)
    if target not in OPPOSITE or target == instance:
        dctf_reject_problem(
            instance, base, token, note_id, text, state, urls, tokens,
            "【CTFd未受付】宛先は相手陣営（black/white）を指定してください。自陣営への作問は採点対象外です。",
            "invalid_problem_target", target=target,
        )
        return
    bank = dctf["environments"][instance]
    if len(bank.get("problemIds") or []) >= CTFD_MAX_PROBLEMS_PER_FACTION:
        dctf_reject_problem(
            instance, base, token, note_id, text, state, urls, tokens,
            f"【CTFd作問停止】{instance}の問題バンクは上限{CTFD_MAX_PROBLEMS_PER_FACTION}問です。"
            "既存問題の検証・相互解答に集中してください。",
            "problem_bank_full",
        )
        return
    if len(title) < 2 or len(statement) < 8 or not answer:
        dctf_reject_problem(
            instance, base, token, note_id, text, state, urls, tokens,
            "【CTFd未受付】タイトル・8文字以上の問題文・解答が必要です。解答は作問側のローカル投稿にだけ含めてください。",
            "invalid_problem_fields",
        )
        return
    security_meta = None
    if dctf.get("securityMode"):
        if not ctfd_challenge_id:
            dctf_reject_problem(
                instance, base, token, note_id, text, state, urls, tokens,
                "【CTFd未受付】作問側エージェントがCTFd APIへ直接登録し、返却された数値IDを`CTFdID:<id>`（任意で`CTFdURL:<url>`）として報告してください。GMは代理作成しません。",
                "missing_ctfd_api_reference",
            )
            return
        difficulty = security_field(text, ("難易度", "difficulty"))
        environment = security_field(text, ("環境", "environment"))
        verification = security_field(text, ("検証", "再現", "検証手順"))
        continuity = security_field(text, ("系統", "復旧系統"))
        impact = security_field(text, ("影響", "故障影響"))
        containment = security_field(text, ("封じ込め", "封じ込め手順"))
        repair = security_field(text, ("修復", "修復手順"))
        transfer = security_field(text, ("伝達", "伝達手順"))
        valid, result = validate_security_problem(
            category_value=category,
            statement=statement,
            answer=answer,
            difficulty=difficulty,
            environment=environment,
            verification=verification,
            continuity_system_value=continuity,
            impact=impact,
            containment=containment,
            repair=repair,
            transfer=transfer,
        )
        if not valid:
            dctf_reject_problem(
                instance, base, token, note_id, text, state, urls, tokens,
                f"【CTFd未受付】セキュリティ問題の契約違反: {result}",
                "invalid_security_problem", reason=result,
            )
            return
        category = security_category(category) or "misc"
        difficulty = security_difficulty(difficulty) or CTFD_MIN_DIFFICULTY
        security_meta = {
            "category": category,
            "difficulty": difficulty[:24],
            "environment": environment[:240],
            "verification": verification[:300],
            "continuitySystem": continuity_system(continuity),
            "failureImpact": impact[:300],
            "containment": containment[:240],
            "repair": repair[:240],
            "transfer": transfer[:240],
            "isolated": True,
        }
    if re.search(r"期待される解答|解答例を?求め|答えを導けるか", answer):
        dctf_reject_problem(
            instance, base, token, note_id, text, state, urls, tokens,
            "【CTFd未受付】解答欄が採点可能な具体的事実ではありません。数値・観測結果・判定条件を確定してから再作問してください。",
            "invalid_problem_answer_quality",
        )
        return
    environment = bank
    serial = len(environment.get("problemIds") or []) + 1
    short = "B" if instance == "black" else "W"
    problem_prefix = "CTFd" if DCTF_SEASON_ID.casefold() == "ctfd" else "DCTF"
    problem_id = f"{problem_prefix}-{short}-{serial:04d}"
    answer_digest = dctf_answer_digest(answer)
    if any(str(item.get("answerDigest")) == answer_digest and item.get("authorFaction") == instance for item in dctf["problems"]):
        dctf_reject_problem(
            instance, base, token, note_id, text, state, urls, tokens,
            "【CTFd未受付】同じ解答ダイジェストの重複問題は登録しません。問いを変え、再現可能な根拠を追加してください。",
            "duplicate_problem",
        )
        return
    problem = {
        "id": problem_id,
        "bank": environment["id"],
        "authorFaction": instance,
        "targetFaction": target,
        "author": username,
        "noteId": note_id,
        "category": category[:40],
        "title": title[:160],
        "statement": statement[:700],
        "hint": hint[:300],
        "points": ctfd_security_points(security_meta["difficulty"]) if security_meta else dctf_points(text),
        "answerDigest": answer_digest,
        "answerDigests": [],
        "answerProfile": dctf_answer_profile(answer),
        "answerProfiles": [],
        "status": "open",
        "createdAt": iso_now(),
        "solvedBy": None,
        "solvedNoteId": None,
        "authorBonusAwarded": False,
        "artifactRef": dctf_artifact_reference(text) if ctf_artifact_bonus(text) else None,
        "ctfdChallengeId": ctfd_challenge_id,
        "ctfdUrl": ctfd_challenge_url,
    }
    if security_meta:
        problem["security"] = security_meta
        problem["qualityTier"] = security_meta["difficulty"]
    dctf["problems"].append(problem)
    environment.setdefault("problemIds", []).append(problem_id)
    public = dctf_problem_public_text(problem)
    label = "CTFd" if problem_id.casefold().startswith("ctfd-") else "DCTF"
    post(base, token, f"【{label}作問受付 {problem_id}】問題を登録しました。解答はGMだけがダイジェスト化して保持し、相手側には問題文を公開します。", note_id)
    post(urls[target], tokens[target], public)
    post(urls["world"], tokens["world"], public)
    dctf_event(state, "problem_created", problemId=problem_id, authorFaction=instance, targetFaction=target, noteId=note_id)
    print(f"gm: dctf problem created: {problem_id} {instance}->{target}", flush=True)


def nudge_dctf_open_problems(
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> bool:
    """Prompt the opposing faction to solve each still-open CTFd problem.

    This is a public queue signal, not an answer or a forced action.  The
    target agent must still read the challenge, reproduce it in isolation and
    submit its own evidence through the normal GM command.  A persisted
    timestamp prevents the 10-second GM poll from spamming the timeline.
    """

    dctf = ensure_dctf(state)
    if dctf.get("status") != "active":
        return False
    changed = False
    now = time.time()
    interval = max(60, DCTF_SOLVER_NUDGE_SECONDS)
    for problem in dctf.get("problems", []):
        if problem.get("status") != "open":
            continue
        try:
            last = float(problem.get("lastSolverNudgeAtEpoch") or 0)
        except (TypeError, ValueError):
            last = 0
        if last and now - last < interval and str(problem.get("lastSolverNudgeFormat") or "") == DCTF_SOLVER_NUDGE_FORMAT_VERSION:
            continue
        problem_id = str(problem.get("id") or "")
        target = str(problem.get("targetFaction") or "")
        if target not in urls or not problem_id:
            continue
        source = f"出典:{problem['artifactRef']}。" if problem.get("artifactRef") else "出典が未登録のため、推測で解かず不足を報告してください。"
        # Repeat the safe public problem text in the solver notification.  The
        # author answer is never persisted in ``problem`` (only a digest/profile
        # is), and ``dctf_problem_public_text`` deliberately excludes it, so the
        # opposing faction can act from one notification without hunting back
        # through the timeline while the flag remains secret.
        public_problem = dctf_problem_public_text(problem)
        source_notice = "" if problem.get("artifactRef") else source
        notice_prefix = f"【CTFd解答待ち {problem_id}】\n相手陣営の未解決セキュリティ問題です。"
        if source_notice:
            notice_prefix += f"\n{source_notice}"
        message = (
            f"{notice_prefix}\n\n"
            f"{public_problem}\n\n"
            "◆ 次の行動\n"
            "1. チャレンジ本体・Dockerfile・検証手順を隔離環境で再現する。\n"
            "2. 故障影響の封じ込め・修復・伝達まで確認する。\n"
            "3. 推測ではなく、再現結果を添えてGMへ提出する。"
        )
        post(urls[target], tokens[target], message)
        world_message = (
            f"【CTFd解答待ち {problem_id}】\n"
            f"{target}側の検証待ちです。\n\n"
            f"◆ タイトル\n{public_block(problem.get('title') or '公告を参照', 160)}\n\n"
            f"◆ 問題文\n{public_block(problem.get('statement') or '公告を参照', 700)}\n\n"
            f"CTFd URL: {problem.get('ctfdUrl') or '公告を参照'}"
        )
        post(urls["world"], tokens["world"], world_message)
        problem["lastSolverNudgeAtEpoch"] = now
        problem["lastSolverNudgeAt"] = iso_now(now)
        problem["lastSolverNudgeFormat"] = DCTF_SOLVER_NUDGE_FORMAT_VERSION
        dctf_event(state, "solver_nudge", problemId=problem_id, targetFaction=target)
        print(f"gm: dctf solver nudge: {problem_id} -> {target}", flush=True)
        changed = True
    return changed


def dctf_problem_hint(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    text: str,
    state: dict,
) -> None:
    submitted_problem_id = dctf_problem_id(text)
    problem = dctf_problem_by_id(state, submitted_problem_id or "")
    resolved_from = None
    if not problem:
        problem, resolved_from = dctf_resolve_problem_alias(state, text)
    if not problem or problem.get("targetFaction") != instance:
        post(base, token, "【CTFd未受付】対象陣営の未解決問題IDを指定してください。", note_id)
        return
    if resolved_from:
        post(
            base,
            token,
            f"【CTFd問題ID自動解決】ヒント要求の提出ID:{resolved_from}を現行正規ID:{problem['id']}へ紐付けました。",
            note_id,
        )
        dctf_event(
            state,
            "hint_alias_resolved",
            submittedProblemId=submitted_problem_id,
            problemId=problem["id"],
            instance=instance,
            noteId=note_id,
        )
    hint = str(problem.get("hint") or "")
    if not hint:
        post(base, token, f"【CTFdヒント {problem['id']}】作問者はまだヒントを登録していません。検証可能な根拠から解答を組み立ててください。", note_id)
    else:
        post(base, token, f"【CTFdヒント {problem['id']}】{hint}", note_id)
    dctf_event(state, "hint_requested", problemId=problem["id"], instance=instance, noteId=note_id)


def dctf_reconcile_answer_aliases(
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> bool:
    """Repair open problems whose valid answer was rejected during migration.

    This is deliberately evidence-gated.  A stale digest alone is not enough:
    the original solver note must still be a CTFd submission with reproduction
    evidence.  The first independently evidenced submission receives points;
    later equivalent submissions are recorded as valid duplicates without
    awarding the same problem twice.
    """
    dctf = ensure_dctf(state)
    changed = False
    for problem in dctf.get("problems", []):
        if not isinstance(problem, dict) or problem.get("status") != "open":
            continue
        if dctf_refresh_answer_aliases(problem, urls, tokens):
            dctf_event(
                state,
                "answer_alias_added",
                problemId=problem.get("id"),
                authorFaction=problem.get("authorFaction"),
            )
            changed = True
        aliases = {
            str(item)
            for item in [problem.get("answerDigest"), *(problem.get("answerDigests") or [])]
            if item
        }
        candidates = []
        for submission in dctf.get("submissions", []):
            if not isinstance(submission, dict) or submission.get("correct"):
                continue
            if str(submission.get("problemId") or "") != str(problem.get("id") or ""):
                continue
            if str(submission.get("answerDigest") or "") not in aliases:
                continue
            solver = str(submission.get("instance") or "")
            note_id = str(submission.get("noteId") or "")
            if solver not in urls or solver not in tokens or not note_id:
                continue
            try:
                note = api(urls[solver], tokens[solver], "notes/show", {"noteId": note_id})
            except Exception:
                continue
            text = str(note.get("text") or "") if isinstance(note, dict) else ""
            if dctf_action_kind(text) != "solve":
                continue
            if dctf.get("securityMode"):
                evidence = dctf_field(
                    text,
                    ("根拠", "証拠", "検証結果", "再現結果"),
                    ("解答", "答え", "NyankoFace"),
                )
                if not evidence:
                    continue
            candidates.append(submission)
        if not candidates:
            continue
        candidates.sort(key=lambda item: str(item.get("at") or "9999-12-31T23:59:59Z"))
        winner = candidates[0]
        for submission in candidates:
            submission["correct"] = True
            submission["matchMethod"] = "alias-exact"
            submission["coverage"] = 1.0
            submission["reconciled"] = True
            submission["reconciledAt"] = iso_now()
            if submission is not winner:
                submission["duplicateAfterReconcile"] = True
        problem["status"] = "solved"
        problem["solvedBy"] = winner.get("username")
        problem["solvedNoteId"] = winner.get("noteId")
        problem["solvedAt"] = winner.get("at") or iso_now()
        solved_ids = dctf["environments"][str(winner.get("instance"))].setdefault("solvedIds", [])
        if problem["id"] not in solved_ids:
            solved_ids.append(problem["id"])
        solver = str(winner.get("instance") or "")
        dctf_add_score(
            state,
            solver,
            int(problem.get("points") or 0),
            "solve_reconciled",
            problem_id=problem["id"],
            note_id=str(winner.get("noteId") or ""),
        )
        author = str(problem.get("authorFaction") or "")
        if not problem.get("authorBonusAwarded"):
            dctf_add_score(
                state,
                author,
                int(dctf.get("authorBonus") or DCTF_AUTHOR_BONUS),
                "author_bonus_reconciled",
                problem_id=problem["id"],
                note_id=str(winner.get("noteId") or ""),
            )
            problem["authorBonusAwarded"] = True
        dctf_event(
            state,
            "problem_solved_reconciled",
            problemId=problem["id"],
            solverFaction=solver,
            authorFaction=author,
            noteId=winner.get("noteId"),
            duplicateCount=max(0, len(candidates) - 1),
        )
        solver_name = "黒猫" if solver == "black" else "白猫"
        author_name = "黒猫" if author == "black" else "白猫"
        message = (
            f"【CTFd正解 整合性修復 {problem['id']}】{solver_name}の検証済み提出を、"
            "作問移行時の解答ダイジェスト差分と照合して正答として確定しました。"
            f"解答点+{problem.get('points') or 0}、{author_name}の作者点+{dctf.get('authorBonus') or DCTF_AUTHOR_BONUS}。"
            f"現在のCTFd盤:{dctf_score_text(state)}。"
        )
        for target in ("black", "white", "world"):
            post(urls[target], tokens[target], message)
        dctf_finish_if_won(state, urls, tokens)
        changed = True
    return changed


def dctf_status_report(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
    *,
    reconciled: bool = False,
) -> None:
    """Answer a ledger query without reopening or re-scoring old seasons."""
    current = ensure_dctf(state)
    requested = explicit_ctf_season(text)
    ledger = current
    label = str(current.get("seasonId") or DCTF_SEASON_ID)
    archived = False
    if requested and requested.upper() != label.upper():
        for candidate in state.get("dctfArchive") or []:
            if isinstance(candidate, dict) and str(candidate.get("seasonId") or "").upper() == requested.upper():
                ledger = candidate
                label = str(candidate.get("seasonId") or requested)
                archived = True
                break
    if requested and requested.upper() != label.upper():
        message = f"【CTFd台帳照会】指定競技{requested}は現行台帳にもアーカイブにもありません。現行は{current.get('seasonId')}です。"
        post(base, token, message, note_id)
        dctf_event(
            state,
            "status_report_missing_season",
            noteId=note_id,
            instance=instance,
            season=requested,
            currentSeason=current.get("seasonId"),
        )
        return

    summary = dctf_status_line(ledger, label)
    archive_suffix = "（アーカイブ。採点・状態変更は行いません）" if archived else ""
    message = f"【CTFd台帳照会】{summary}{archive_suffix}。"
    post(base, token, message, note_id)
    post(urls["world"], tokens["world"], f"【CTFd台帳照会／{label}】{summary}{archive_suffix}。")
    dctf_event(
        state,
        "status_report",
        noteId=note_id,
        instance=instance,
        season=label,
        archived=archived,
        status=ledger.get("status"),
        problemCount=len(list(ledger.get("problems") or [])),
        reconciled=reconciled,
    )


def dctf_banks_exhausted(dctf: dict) -> bool:
    """Return whether the finite season bank is full and has no open work."""
    limit = max(1, CTFD_MAX_PROBLEMS_PER_FACTION)
    problems = {str(item.get("id")): item for item in dctf.get("problems", []) if isinstance(item, dict)}
    for instance in OPPOSITE:
        bank = dctf.get("environments", {}).get(instance, {})
        ids = [str(item) for item in bank.get("problemIds") or []]
        if len(ids) < limit:
            return False
        bank_problems = [problems[item_id] for item_id in ids if item_id in problems]
        if len(bank_problems) < limit or any(item.get("status") == "open" for item in bank_problems):
            return False
    return True


def dctf_finish_if_won(state: dict, urls: dict[str, str], tokens: dict[str, str]) -> str | None:
    dctf = ensure_dctf(state)
    if dctf.get("status") != "active":
        return dctf.get("winner")
    reached = [instance for instance, score in dctf["score"].items() if int(score or 0) >= int(dctf.get("victoryScore") or DCTF_VICTORY_SCORE)]
    bank_exhausted = dctf_banks_exhausted(dctf)
    if not reached and not bank_exhausted:
        return None
    candidates = reached or list(OPPOSITE)
    scores = {instance: int(dctf["score"].get(instance) or 0) for instance in candidates}
    highest = max(scores.values())
    leaders = [instance for instance, score in scores.items() if score == highest]
    if len(leaders) == 1:
        winner = leaders[0]
        tie_break = "score"
    else:
        # If both sides clear the finite banks at the same score, the side
        # that finished solving the opponent's bank first wins.  This keeps a
        # genuine all-solved season from ending in an accidental draw while
        # preserving the published score economy.
        completion: dict[str, str] = {}
        for problem in dctf.get("problems", []):
            solver = str(problem.get("targetFaction") or "")
            solved_at = str(problem.get("solvedAt") or "")
            if solver in leaders and solved_at and solved_at > completion.get(solver, ""):
                completion[solver] = solved_at
        ordered = sorted(leaders, key=lambda item: completion.get(item, "9999-12-31T23:59:59Z"))
        winner = ordered[0] if ordered and completion.get(ordered[0]) else "draw"
        tie_break = "last_solve_time" if winner != "draw" else "unresolved"
    dctf["status"] = "finished"
    dctf["winner"] = winner
    dctf["finishedAt"] = iso_now()
    finish_reason = "victory_score" if reached else "finite_bank_exhausted"
    dctf["finishReason"] = finish_reason
    dctf["tieBreak"] = tie_break
    dctf_event(state, "season_won" if winner != "draw" else "season_draw", winner=winner, scores=dctf["score"], reason=finish_reason, tieBreak=tie_break)
    if winner == "draw":
        message = f"【CTFd競技 決着】両陣営が同点のため引き分けです（終了理由:{finish_reason}）。最終盤:{dctf_score_text(state)}。"
    else:
        name = "黒猫" if winner == "black" else "白猫"
        reason = f"{dctf['victoryScore']}点へ到達" if reached else "有限バンクを全問検証"
        message = f"【CTFd競技 決着】{name}が{reason}し勝者になりました。最終盤:{dctf_score_text(state)}。"
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    return winner


def dctf_problem_solved(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    dctf = ensure_dctf(state)
    submitted_problem_id = dctf_problem_id(text)
    problem_id = submitted_problem_id
    answer = dctf_field(text, ("解答", "答え", "answer"), ("根拠", "証拠", "NyankoFace"))
    problem = dctf_problem_by_id(state, problem_id or "")
    resolved_from = None
    if not problem:
        problem, resolved_from = dctf_resolve_problem_alias(state, text)
        if problem:
            problem_id = str(problem.get("id") or "")
            dctf_event(
                state,
                "submission_alias_resolved",
                submittedProblemId=submitted_problem_id,
                problemId=problem_id,
                instance=instance,
                noteId=note_id,
            )
    if not problem or problem.get("targetFaction") != instance:
        post(
            base,
            token,
            "【CTFd未受付】現行GM台帳の相手陣営・未解決問題IDを指定してください。"
            "NyankoFaceやCTFdで発見しただけの未登録チャレンジは採点対象になりません。"
            "`@gm CTFd状況報告 競技:CTFd`で正規ID対応表を取得できます。",
            note_id,
        )
        dctf_event(
            state,
            "invalid_submission",
            instance=instance,
            problemId=problem_id,
            submittedProblemId=submitted_problem_id,
            noteId=note_id,
        )
        return
    if problem.get("status") != "open":
        if resolved_from:
            post(
                base,
                token,
                f"【CTFd問題ID自動解決】提出ID:{resolved_from}を現行正規ID:{problem['id']}へ紐付けました。"
                f"この問題はすでに{problem.get('status')}です。得点は重複加算しません。",
                note_id,
            )
        else:
            post(base, token, f"【CTFd未受付 {problem['id']}】この問題はすでに{problem.get('status')}です。", note_id)
        return
    if resolved_from:
        post(
            base,
            token,
            f"【CTFd問題ID自動解決】提出ID:{resolved_from}を現行正規ID:{problem['id']}へ紐付けて採点します。",
            note_id,
        )
    if dctf.get("securityMode"):
        evidence = dctf_field(text, ("根拠", "証拠", "検証結果", "再現結果"), ("解答", "答え", "NyankoFace"))
        if not evidence:
            post(base, token, f"【CTFd未受付 {problem['id']}】セキュリティ問題は解答だけでなく、隔離環境での再現結果を根拠として添えてください。", note_id)
            dctf_event(state, "invalid_security_submission", problemId=problem["id"], instance=instance, noteId=note_id)
            return
    profile = dctf_backfill_answer_profile(problem, urls, tokens)
    accepted, match_method, coverage = dctf_answer_matches(answer, problem)
    submission = {
        "id": f"solve:{problem['id']}:{note_id}",
        "problemId": problem["id"],
        "instance": instance,
        "username": username,
        "noteId": note_id,
        "answerDigest": dctf_answer_digest(answer),
        "correct": accepted,
        "matchMethod": match_method,
        "coverage": round(coverage, 3),
        "at": iso_now(),
    }
    dctf["submissions"].append(submission)
    if not submission["correct"]:
        post(base, token, f"【CTFd不正解 {problem['id']}】解答は一致しません。再検証してから再提出できます。", note_id)
        dctf_event(state, "wrong_answer", problemId=problem["id"], instance=instance, noteId=note_id)
        return
    problem["status"] = "solved"
    problem["solvedBy"] = username
    problem["solvedNoteId"] = note_id
    problem["solvedAt"] = iso_now()
    dctf["environments"][instance].setdefault("solvedIds", []).append(problem["id"])
    dctf_add_score(state, instance, int(problem["points"]), "solve", problem_id=problem["id"], note_id=note_id)
    author = str(problem["authorFaction"])
    dctf_add_score(state, author, int(dctf.get("authorBonus") or DCTF_AUTHOR_BONUS), "author_bonus", problem_id=problem["id"], note_id=note_id)
    problem["authorBonusAwarded"] = True
    dctf_event(state, "problem_solved", problemId=problem["id"], solverFaction=instance, authorFaction=author, noteId=note_id)
    solver_name = "黒猫" if instance == "black" else "白猫"
    author_name = "黒猫" if author == "black" else "白猫"
    message = (
        f"【CTFd正解 {problem['id']}】{solver_name}の@{username}が正答しました。"
        f"解答点+{problem['points']}、{author_name}の作者点+{dctf.get('authorBonus') or DCTF_AUTHOR_BONUS}。"
        f"現在のCTFd盤:{dctf_score_text(state)}。"
    )
    for target in ("black", "white", "world"):
        post(urls[target], tokens[target], message)
    dctf_finish_if_won(state, urls, tokens)
    print(f"gm: dctf solved: {problem['id']} {instance} correct", flush=True)


def process_dctf(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    dctf = ensure_dctf(state)
    kind = dctf_action_kind(text)
    if kind == "status":
        dctf_status_report(instance, base, token, note_id, text, state, urls, tokens)
        return
    if dctf.get("status") != "active":
        post(base, token, f"【CTFd未受付】競技{dctf.get('seasonId')}は現在アクティブではありません。", note_id)
        dctf_event(
            state,
            "inactive_season",
            instance=instance,
            noteId=note_id,
            season=dctf.get("seasonId"),
            status=dctf.get("status"),
        )
        return
    requested = explicit_ctf_season(text)
    if requested and requested.upper() != str(dctf.get("seasonId")).upper():
        post(base, token, f"【CTFd未受付】指定競技{requested}は現在の{dctf.get('seasonId')}と一致しません。", note_id)
        dctf_event(state, "stale_season", instance=instance, noteId=note_id, season=requested)
        return
    if kind == "author":
        dctf_problem_author(instance, base, token, note_id, username, text, state, urls, tokens)
    elif kind == "solve":
        dctf_problem_solved(instance, base, token, note_id, username, text, state, urls, tokens)
    elif kind == "hint":
        dctf_problem_hint(instance, base, token, note_id, text, state)
    else:
        post(base, token, f"【CTFd使い方】作問は`CTFd作問`、相互解答は`CTFd解答`、ヒントは`CTFdヒント`を使ってください。現在の盤:{dctf_score_text(state)}。", note_id)
        dctf_event(state, "unknown_command", instance=instance, noteId=note_id)


def ctf_flag_for_text(state: dict, text: str, scene: dict | None = None) -> dict | None:
    ctf = ensure_ctf(state)
    flag_id = explicit_ctf_flag(text)
    if flag_id:
        return ctf.get("flags", {}).get(flag_id)
    token = ctf_proof_token(text)
    if token:
        return ctf_flag_by_token(state, token)
    if isinstance(scene, dict):
        location_value = str(scene.get("location") or "")
        matches = [flag for flag in ctf["flags"].values() if flag.get("location") == location_value]
        if len(matches) == 1:
            return matches[0]
    return None


def ctf_claim_exists(state: dict, claim_id: str) -> bool:
    return any(str(item.get("id")) == claim_id for item in ensure_ctf(state).get("claims", []))


def ctf_append_claim(state: dict, claim: dict) -> None:
    ctf = ensure_ctf(state)
    if ctf_claim_exists(state, str(claim.get("id"))):
        return
    ctf["claims"].append(claim)
    ctf["claims"] = ctf["claims"][-500:]


def ctf_artifact_bonus(text: str) -> bool:
    value = text.lower()
    has_platform = "nyankoface" in value or "madesk.tail" in value or "/git/" in value
    has_immutable_proof = (
        "commit" in value
        or "sha" in value
        or "公開url" in text
        or "公開url" in value
        # Some older agent notes used a bare commit SHA immediately after
        # `NyankoFace:`.  Treat that as an immutable pointer as well, but only
        # when it is explicitly attached to the NyankoFace label.
        or bool(re.search(r"nyankoface\s*[:：]\s*(?:commit\s*[:#]?\s*)?[0-9a-f]{7,64}(?![0-9a-f])", text, re.I))
    )
    return has_platform and has_immutable_proof


def dctf_artifact_reference(text: str) -> str | None:
    """Keep a secret-free artifact pointer; never persist the raw answer."""
    references = re.findall(
        r"https?://[^\s]+|(?:commit|sha)\s*[:#]?\s*[0-9a-f]{7,64}",
        text,
        re.IGNORECASE,
    )
    references.extend(
        f"NyankoFace:{digest}"
        for digest in re.findall(
            r"nyankoface\s*[:：]\s*(?:commit\s*[:#]?\s*)?([0-9a-f]{7,64})(?![0-9a-f])",
            text,
            re.IGNORECASE,
        )
    )
    # Preserve first-seen order while avoiding duplicate URL/hash pointers.
    unique = list(dict.fromkeys(references))
    return compact(" ".join(unique), 280) if unique else None


def ctf_capture_flag(
    state: dict,
    flag: dict,
    instance: str,
    note_id: str,
    username: str,
    text: str,
    *,
    previous_holder: str | None = None,
) -> int:
    now = time.time()
    flag["holder"] = instance
    flag["status"] = "held"
    flag["capturedAt"] = now
    flag["capturedAtIso"] = iso_now(now)
    flag["lastHoldScoreAt"] = now
    flag["lastDefenseScoreAt"] = None
    flag["lastClaimId"] = note_id
    points = int(flag.get("points") or 0)
    ctf_add_score(state, instance, points, "flag_capture", flag_id=flag["id"], note_id=note_id)
    if ctf_artifact_bonus(text):
        ctf_add_score(state, instance, 10, "nyankoface_artifact", flag_id=flag["id"], note_id=note_id)
        artifact = True
    else:
        artifact = False
    ctf_append_claim(
        state,
        {
            "id": f"capture:{note_id}",
            "kind": "capture",
            "flagId": flag["id"],
            "instance": instance,
            "username": username,
            "noteId": note_id,
            "previousHolder": previous_holder,
            "artifactBonus": artifact,
            "at": iso_now(now),
        },
    )
    ctf_event(
        state,
        "flag_captured",
        flagId=flag["id"],
        instance=instance,
        previousHolder=previous_holder,
        noteId=note_id,
    )
    return points + (10 if artifact else 0)


def ctf_discover_flag(state: dict, flag: dict, instance: str, note_id: str, username: str, text: str) -> bool:
    if flag.get("status") == "held":
        return False
    claim_id = f"discover:{flag['id']}:{instance}:{note_id}"
    if ctf_claim_exists(state, claim_id):
        return False
    if flag.get("status") == "neutral":
        flag["status"] = "discovered"
        flag["discoveredBy"] = instance
        flag["discoveredAt"] = iso_now()
    ctf_append_claim(
        state,
        {
            "id": claim_id,
            "kind": "discover",
            "flagId": flag["id"],
            "instance": instance,
            "username": username,
            "noteId": note_id,
            "at": iso_now(),
        },
    )
    ctf_add_score(state, instance, 5, "flag_discovery", flag_id=flag["id"], note_id=note_id)
    ctf_event(state, "flag_discovered", flagId=flag["id"], instance=instance, noteId=note_id)
    return True


def ctf_hold_flag(state: dict, flag: dict, instance: str, note_id: str, username: str, text: str) -> int:
    if flag.get("holder") != instance:
        return 0
    now = time.time()
    last_defense = float(flag.get("lastDefenseScoreAt") or 0)
    if last_defense and now - last_defense < max(60, int(ensure_ctf(state).get("holdSeconds") or CTF_HOLD_SECONDS)):
        return 0
    claim_id = f"defend:{flag['id']}:{instance}:{note_id}"
    if ctf_claim_exists(state, claim_id):
        return 0
    ctf_append_claim(
        state,
        {
            "id": claim_id,
            "kind": "defend",
            "flagId": flag["id"],
            "instance": instance,
            "username": username,
            "noteId": note_id,
            "at": iso_now(),
        },
    )
    flag["lastDefenseScoreAt"] = now
    ctf_add_score(state, instance, 5, "flag_defense", flag_id=flag["id"], note_id=note_id)
    return 5


def ctf_check_victory(state: dict) -> str | None:
    ctf = ensure_ctf(state)
    if ctf.get("status") != "active":
        return ctf.get("winner")
    scores = {instance: int(ctf["score"].get(instance) or 0) for instance in OPPOSITE}
    reached = [instance for instance, score in scores.items() if score >= int(ctf.get("victoryScore") or CTF_VICTORY_SCORE)]
    if not reached:
        return None
    winner = max(reached, key=lambda instance: scores[instance])
    ctf["status"] = "finished"
    ctf["winner"] = winner
    ctf["finishedAt"] = time.time()
    ctf["finishedAtIso"] = iso_now(ctf["finishedAt"])
    ctf_event(state, "season_won", winner=winner, scores=scores)
    return winner


def ctf_hold_tick(state: dict) -> None:
    """Award elapsed hold points without repeating the same interval."""
    ctf = ensure_ctf(state)
    if ctf.get("status") != "active":
        return
    now = time.time()
    interval = max(60, int(ctf.get("holdSeconds") or CTF_HOLD_SECONDS))
    for flag in ctf.get("flags", {}).values():
        holder = flag.get("holder")
        if holder not in OPPOSITE:
            continue
        last = float(flag.get("lastHoldScoreAt") or flag.get("capturedAt") or now)
        elapsed = max(0, now - last)
        units = int(elapsed // interval)
        if units <= 0:
            continue
        flag["lastHoldScoreAt"] = last + units * interval
        ctf_add_score(state, holder, units * 5, "flag_hold", flag_id=flag["id"])
        ctf_event(state, "flag_hold_scored", flagId=flag["id"], instance=holder, units=units)


def announce_ctf_update(state: dict, urls: dict[str, str], tokens: dict[str, str], message: str) -> None:
    ctf = ensure_ctf(state)
    full = f"{message} 現在のCTFd盤: {ctf_score_text(state)}。旗: {ctf_flag_board_text(state)}。"
    for instance in ("black", "white"):
        post(urls[instance], tokens[instance], full)
    post(urls["world"], tokens["world"], full)


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
    axes = competition_axis_labels(tuple(scene.get("competitionAxes") or ()))
    clock = scene.get("survivalClock") if isinstance(scene.get("survivalClock"), dict) else {}
    clock_text = str(clock.get("text") or "").strip()
    survival_prefix = f"【文明存亡】{clock_text} " if clock_text else ""
    return (
        f"【GM場面 {scene['id']}／第{scene['turn']}幕】{scene['location']}「{scene['title']}」。"
        f"{survival_prefix}"
        f"{scene['description']} 争点: {scene['stakes']}。"
        f"この場面で主に変化しうる競争軸: {axes}。"
        "これは現在の場面描写であり、GMが次の世界の事実を裁定します。"
        "各エージェントはこの人物として、観察・偵察・交渉・協力・防衛・挑戦・撤退などから"
        f"この場面での行動を一つ選び、`@gm 行動宣言 シーンID:{scene['id']} 行動:○○`で宣言してください。"
        "何を勝利に近づける行動とみなすか、評価軸そのものへの異議や提案も自分で考えられます。"
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
        "competitionAxes": list(template.get("competitionAxes") or ()),
        "createdAt": now,
        "createdAtIso": iso_now(now),
        "actionDeadline": now + ACTION_WINDOW_SECONDS,
        "actions": {"black": [], "white": []},
        "round": 1,
        "rounds": [],
        "battleId": None,
    }
    state["sceneSequence"] = sequence
    survival = ensure_survival(state)
    survival_text = survival_clock_text(state)
    scene["survivalClock"] = {
        "clockMode": survival["clockMode"],
        "status": survival["status"],
        "startScene": survival["startScene"],
        "environmentSignal": survival["environmentSignal"],
        "systems": json.loads(json.dumps(survival["systems"], ensure_ascii=False)),
        "text": survival_text,
    }
    state["currentScene"] = scene
    state["nextSceneAt"] = 0
    state.setdefault("scenes", []).append(scene)
    state["scenes"] = state["scenes"][-50:]
    audit(
        state,
        "scene_started",
        sceneId=scene["id"],
        location=scene["location"],
        conflict=scene["conflict"],
        survivalStatus=survival["status"],
        survivalClockMode=survival["clockMode"],
    )
    if sequence == 1 or sequence % max(COMPETITION_REVIEW_INTERVAL_SCENES, 1) == 0:
        announce_competition_review(state, urls, tokens, sequence)
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
    competition_evidence = record_scene_evidence(state, scene)
    scene["phase"] = "resolved"
    scene["resolution"] = summary
    scene["resolvedAt"] = time.time()
    scene["resolvedAtIso"] = iso_now(scene["resolvedAt"])
    state["nextSceneAt"] = scene["resolvedAt"] + SCENE_INTERVAL_SECONDS
    message = (
        f"【GM裁定 {scene['id']}】{scene['location']}の場面を終了します。"
        f"黒猫({action_labels(scene_actions(scene, 'black'))})／白猫({action_labels(scene_actions(scene, 'white'))})。{summary}"
        f" 競争上の観測証拠: {competition_evidence}。"
        f" 暫定競争盤: {competition_score_text(state)}。次の場面は約{SCENE_INTERVAL_SECONDS // 60}分後です。"
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
        winner = "black"
    elif final_difference <= -3:
        result = "白猫側の勝利"
        winner = "white"
    else:
        result = "双方が決定打を得られず停戦"
        winner = None
    battle["status"] = "resolved"
    battle["resolution"] = result
    battle["updatedAt"] = time.time()
    record_battle_competition(state, battle, winner, totals)
    scene["phase"] = "resolved"
    scene["resolution"] = result
    scene["resolvedAt"] = battle["updatedAt"]
    scene["resolvedAtIso"] = iso_now(scene["resolvedAt"])
    state["nextSceneAt"] = scene["resolvedAt"] + SCENE_INTERVAL_SECONDS
    message = (
        f"【GM決着 {battle['id']}】{scene['location']}の{BATTLE_ROUNDS}ラウンドを終了。"
        f"累計は黒猫{totals['black']}／白猫{totals['white']}。{result}。"
        f"暫定競争盤: {competition_score_text(state)}。次の場面は約{SCENE_INTERVAL_SECONDS // 60}分後です。"
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


def process_competition_proposal(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    competition = ensure_competition(state)
    proposal_id = "P-" + hashlib.sha256(note_id.encode()).hexdigest()[:8].upper()
    if any(str(item.get("id")) == proposal_id for item in competition["proposals"]):
        return
    kind = "異議" if "競争異議" in text else "提案"
    axes = competition_axes_in_text(text)
    proposal = {
        "id": proposal_id,
        "kind": kind,
        "instance": instance,
        "username": username,
        "noteId": note_id,
        "axes": axes,
        "text": compact(text),
        "status": "open",
        "at": iso_now(),
    }
    competition["proposals"].append(proposal)
    competition["proposals"] = competition["proposals"][-300:]
    name, other = instance_names(instance)
    message = (
        f"【競争憲章受付 {proposal_id}】{name}側の@{username}から{kind}を受理しました。"
        f"候補軸: {competition_axis_labels(axes)}。"
        "これは採用済みの勝利条件ではありません。相手側も賛成・反論・別案を自律的に選べます。"
    )
    post(base, token, message, note_id)
    post(urls[OPPOSITE[instance]], tokens[OPPOSITE[instance]], f"{message} {other}側はこの提案への応答を選べます。")
    post(urls["world"], tokens["world"], f"【競争台帳 {proposal_id}】{name}側が{kind}を提出。候補軸: {competition_axis_labels(axes)}。")
    audit(state, "competition_proposal", noteId=note_id, proposalId=proposal_id, instance=instance, kind=kind, axes=axes)
    print(f"gm: competition proposal: {proposal_id} {instance} {kind}", flush=True)


def ctf_challenge_flag(
    state: dict,
    flag: dict,
    instance: str,
    note_id: str,
    username: str,
    text: str,
) -> tuple[bool, str]:
    holder = str(flag.get("holder") or "")
    if holder not in OPPOSITE or holder == instance:
        return False, "相手側の保持旗ではありません"
    category = action_category(text)
    attacker_roll = d20(f"{ensure_ctf(state)['seasonId']}:{flag['id']}:attack:{note_id}")
    defender_seed = str(flag.get("lastClaimId") or holder)
    defender_roll = d20(f"{ensure_ctf(state)['seasonId']}:{flag['id']}:defend:{defender_seed}")
    attacker_score = attacker_roll + action_modifier(category)
    defender_score = defender_roll + action_modifier("defend")
    ctf_append_claim(
        state,
        {
            "id": f"challenge:{note_id}",
            "kind": "challenge",
            "flagId": flag["id"],
            "instance": instance,
            "defender": holder,
            "username": username,
            "noteId": note_id,
            "rolls": {"attacker": attacker_roll, "defender": defender_roll},
            "scores": {"attacker": attacker_score, "defender": defender_score},
            "at": iso_now(),
        },
    )
    ctf_event(
        state,
        "flag_challenged",
        flagId=flag["id"],
        instance=instance,
        defender=holder,
        attackerScore=attacker_score,
        defenderScore=defender_score,
        noteId=note_id,
    )
    if attacker_score > defender_score:
        ctf_capture_flag(state, flag, instance, note_id, username, text, previous_holder=holder)
        return True, f"挑戦成功（攻撃{attacker_score}／防衛{defender_score}）"
    ctf_add_score(state, holder, 5, "flag_defense_against_challenge", flag_id=flag["id"], note_id=note_id)
    return False, f"挑戦失敗（攻撃{attacker_score}／防衛{defender_score}）"


def process_ctf(
    instance: str,
    base: str,
    token: str,
    note_id: str,
    username: str,
    text: str,
    state: dict,
    urls: dict[str, str],
    tokens: dict[str, str],
) -> None:
    ctf = ensure_ctf(state)
    if ctf.get("status") != "active":
        post(base, token, f"【CTF未受付】シーズン{ctf.get('seasonId')}は現在アクティブではありません。", note_id)
        return
    requested_season = explicit_ctf_season(text)
    if requested_season and requested_season.upper() != str(ctf.get("seasonId")).upper():
        post(base, token, f"【CTF未受付】指定シーズン{requested_season}は現在の{ctf.get('seasonId')}と一致しません。", note_id)
        ctf_event(state, "stale_ctf_action", noteId=note_id, instance=instance, season=requested_season)
        return
    scene = state.get("currentScene") if isinstance(state.get("currentScene"), dict) else None
    flag = ctf_flag_for_text(state, text, scene)
    proof = ctf_proof_token(text)
    if flag is None:
        post(
            base,
            token,
            f"【CTF未受付】旗IDまたは現在地を特定できません。現在の旗: {', '.join(sorted(CTF_FLAG_IDS))}。",
            note_id,
        )
        ctf_event(state, "unmatched_ctf_action", noteId=note_id, instance=instance)
        return
    expected = ctf_flag_token(flag["id"], str(ctf.get("seasonId")))
    if proof and proof.lower() != expected.lower():
        post(base, token, f"【CTF未受付】{flag['id']}の証明トークンが一致しません。GMの公開トークンを確認してください。", note_id)
        ctf_event(state, "invalid_ctf_proof", noteId=note_id, instance=instance, flagId=flag["id"])
        return
    kind = ctf_action_kind(text)
    category = action_category(text)
    changed = False
    message = ""
    if kind == "submit":
        if not proof:
            post(base, token, f"【CTF未受付】{flag['id']}の提出にはGMが公開したctf{{...}}証明トークンが必要です。", note_id)
            return
        if flag.get("holder") == instance:
            points = ctf_hold_flag(state, flag, instance, note_id, username, text)
            message = f"{flag['id']}はすでに{('黒猫' if instance == 'black' else '白猫')}が保持しています。防衛点+{points}。"
            changed = points > 0
        elif flag.get("holder") in OPPOSITE:
            if "挑戦" not in text and "奪" not in text and category != "attack":
                post(base, token, f"【CTF未受付】{flag['id']}は相手側が保持中です。`CTF旗挑戦`または`CTF旗奪取`を明示してください。", note_id)
                return
            changed, message = ctf_challenge_flag(state, flag, instance, note_id, username, text)
        else:
            gained = ctf_capture_flag(state, flag, instance, note_id, username, text)
            message = f"{flag['id']}を確保しました。+{gained}点。証明:{expected}。"
            changed = True
    elif kind == "defend" or category == "defend":
        points = ctf_hold_flag(state, flag, instance, note_id, username, text)
        message = f"{flag['id']}の防衛申告を記録しました。+{points}点。" if points else f"{flag['id']}は現在あなたの保持旗ではありません。"
        changed = points > 0
    elif kind == "capture" or category in {"attack", "cooperate", "negotiate"}:
        if flag.get("holder") in OPPOSITE and flag.get("holder") != instance:
            changed, message = ctf_challenge_flag(state, flag, instance, note_id, username, text)
        elif flag.get("holder") == instance:
            message = f"{flag['id']}はすでにあなたの陣営が保持しています。防衛またはNyankoFace成果の提出を選んでください。"
        else:
            gained = ctf_capture_flag(state, flag, instance, note_id, username, text)
            message = f"{flag['id']}を確保しました。+{gained}点。証明:{expected}。"
            changed = True
    else:
        changed = ctf_discover_flag(state, flag, instance, note_id, username, text)
        message = (
            f"{flag['id']}の発見を記録しました。発見点+5。"
            f"提出用証明:{expected}。次に`CTF提出`で旗を確保できます。"
            if changed
            else f"{flag['id']}はすでに発見済みまたは保持中です。"
        )
    if not changed and not message:
        message = f"{flag['id']}の申告を記録しました。"
    post(base, token, f"【DCTF受付 {ctf['seasonId']}】{username}: {message}", note_id)
    if changed:
        winner = ctf_check_victory(state)
        if winner:
            winner_name = "黒猫" if winner == "black" else "白猫"
            announce_ctf_update(state, urls, tokens, f"【CTF文明シーズン {ctf['seasonId']} 決着】{winner_name}が{ctf['victoryScore']}点へ到達し、シーズン勝者になりました。")
        else:
            announce_ctf_update(state, urls, tokens, f"【DCTF盤更新 {ctf['seasonId']}】{username}の{flag['id']}に関する裁定: {message}")
    ctf_event(state, "ctf_action_processed", noteId=note_id, instance=instance, flagId=flag["id"], kind=kind, changed=changed)
    print(f"gm: ctf action: {instance} {flag['id']} {kind} changed={changed}", flush=True)


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
        audit(state, "battle_challenge", noteId=note_id, battleId=battle["id"], instance=instance, location=place)
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
    audit(state, "battle_engaged", noteId=note_id, battleId=battle["id"], instance=instance, location=place)
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
        audit(state, "unmatched_result", noteId=note_id, instance=instance, location=place)
        return
    if battle.get("origin") == "gm_scene":
        post(
            base,
            token,
            f"【GM受付 {battle['id']}】この戦闘はGMのラウンド裁定中です。"
            f"戦果を確定せず、`@gm 戦闘行動 シーンID:{battle.get('originScene')} 戦闘ID:{battle['id']} 行動:○○`で次の行動を宣言してください。",
            note_id,
        )
        audit(state, "scene_battle_result_ignored", noteId=note_id, battleId=battle.get("id"), instance=instance)
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
        audit(state, "battle_report", noteId=note_id, battleId=battle["id"], instance=instance, outcome=outcome)
        print(f"gm: battle report: {battle_summary(battle)} {instance}={outcome}", flush=True)
        return

    status, summary = reconcile(battle)
    battle["status"] = status
    battle["updatedAt"] = time.time()
    if status == "resolved":
        record_battle_competition(state, battle, battle_winner(battle))
    message = f"【GM{'決着' if status == 'resolved' else '未確定'} {battle['id']}】{battle_summary(battle)}。{summary}。"
    if status == "resolved":
        message += f" 暫定競争盤: {competition_score_text(state)}。"
    for side_record in (battle.get("challenger") or {}, battle.get("responder") or {}):
        target = side_record.get("instance")
        if target in tokens:
            post(urls[target], tokens[target], message)
    post(urls["world"], tokens["world"], message)
    audit(
        state,
        "battle_resolved" if status == "resolved" else "battle_contested",
        noteId=note_id,
        battleId=battle["id"],
        summary=summary,
    )
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
        audit(state, "unmatched_scene_action", noteId=note_id, instance=instance, sceneId=requested)
        return
    if requested and requested.upper() != str(scene.get("id", "")).upper():
        post(
            base,
            token,
            f"【GM未受付】指定されたシーンID {requested} は現在の場面 {scene.get('id')} と一致しません。",
            note_id,
        )
        audit(state, "stale_scene_action", noteId=note_id, instance=instance, sceneId=requested, currentScene=scene.get("id"))
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
            audit(state, "stale_battle_action", noteId=note_id, instance=instance, battleId=requested_battle)
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
    audit(
        state,
        "scene_action",
        noteId=note_id,
        sceneId=scene.get("id"),
        battleId=scene.get("battleId"),
        instance=instance,
        username=username,
        category=category,
    )


def process_instance(instance: str, base: str, token: str, state: dict, urls: dict[str, str], tokens: dict[str, str]) -> None:
    for note in reversed(source_notes(base, token)):
        note_id = event_key(note)
        text = str(note.get("text") or "")
        user = note.get("user") or {}
        username = str(user.get("username") or "unknown")
        if note_id in state["seen"]:
            # A prior GM version routed `@gm CTFd状況報告` through the legacy
            # flag-board handler and replied without writing an audit event.
            # Reconcile only this explicit, secret-free status request once;
            # never replay a solve, capture, or other world-changing action.
            if (
                username != "gm"
                and "@gm" in text.lower()
                and dctf_action_kind(text) == "status"
                and not any(
                    str(event.get("noteId") or "") == note_id
                    for stream in (
                        state.get("events") or [],
                        (state.get("ctf") or {}).get("events") or [],
                        (state.get("dctf") or {}).get("events") or [],
                        *[
                            archive.get("events") or []
                            for archive in state.get("dctfArchive") or []
                            if isinstance(archive, dict)
                        ],
                    )
                    for event in stream
                    if isinstance(event, dict)
                )
            ):
                dctf_status_report(instance, base, token, note_id, text, state, urls, tokens, reconciled=True)
                save_json(STATE_PATH, state)
            continue
        state["seen"].append(note_id)
        if username == "gm" or "@gm" not in text.lower():
            continue
        kind = classify(text)
        place = location(text)
        count = participants(text)
        if kind == "competition":
            process_competition_proposal(instance, base, token, note_id, username, text, state, urls, tokens)
        elif kind == "dctf":
            process_dctf(instance, base, token, note_id, username, text, state, urls, tokens)
        elif kind == "ctf":
            process_ctf(instance, base, token, note_id, username, text, state, urls, tokens)
        elif kind == "action":
            process_scene_action(instance, base, token, note_id, username, text, state)
        elif kind == "battle":
            process_battle_challenge(instance, base, token, note_id, username, text, place, count, state, urls, tokens)
        elif kind == "result":
            process_battle_result(instance, base, token, note_id, text, place, state, urls, tokens)
        elif kind == "diplomacy":
            response = f"【GM記録】{place}に関する{instance}側の外交提案を受け取りました。相手側の反応を待ちます。"
            post(base, token, response, note_id)
            post(urls["world"], tokens["world"], f"【GM記録／{place}】{instance}から外交提案が届きました。")
            audit(state, "diplomacy", noteId=note_id, instance=instance, location=place)
        else:
            response = f"【GM受付】{place}に関する観測を記録しました。裁定が必要な出来事は明示されていません。"
            post(base, token, response, note_id)
            post(urls["world"], tokens["world"], f"【GM記録／{place}】{instance}の観測を受け付けました。")
            audit(state, "observation", noteId=note_id, instance=instance, location=place)
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
    if COMPETITION_REVIEW_INTERVAL_SCENES < 1:
        raise ValueError("GM_COMPETITION_REVIEW_INTERVAL_SCENES must be at least 1")
    if CTF_VICTORY_SCORE < 1:
        raise ValueError("GM_CTF_VICTORY_SCORE must be at least 1")
    if CTF_HOLD_SECONDS < 60:
        raise ValueError("GM_CTF_HOLD_SECONDS must be at least 60 seconds")
    if DCTF_VICTORY_SCORE < 1:
        raise ValueError("GM_DCTF_VICTORY_SCORE must be at least 1")
    if not 1 <= DCTF_PROBLEM_POINTS <= 100:
        raise ValueError("GM_DCTF_PROBLEM_POINTS must be between 1 and 100")
    if DCTF_AUTHOR_BONUS < 0:
        raise ValueError("GM_DCTF_AUTHOR_BONUS must not be negative")
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
    initialize_competition_score(state)
    reconciled_dctf = dctf_reconcile_answer_aliases(state, urls, tokens)
    started_ctf = start_ctf_season(state, urls, tokens)
    opened_ctf_challenge = announce_ctf_challenge(state, urls, tokens)
    reopened_dctf = reopen_dctf_if_threshold_raised(state, urls, tokens)
    started_dctf = start_dctf_season(state, urls, tokens)
    announced_dctf_policy = announce_dctf_quality_policy(state, urls, tokens)
    announced_dctf_sources = announce_dctf_open_sources(state, urls, tokens)
    announced_dctf_registry = announce_dctf_registry(state, urls, tokens)
    # Misskey can still be accepting connections when the one-shot bootstrap
    # dependencies report healthy.  A transient solver-nudge failure must not
    # crash-loop the GM; the regular poll pass below retries it safely.
    try:
        nudged_dctf_solvers = nudge_dctf_open_problems(state, urls, tokens)
    except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
        nudged_dctf_solvers = False
        print(f"gm: initial CTFd solver nudge deferred: {type(exc).__name__}: {exc}", flush=True)
    announced_survival = announce_survival_clock(state, urls, tokens)
    announced_dctf_continuity = announce_dctf_continuity_policy(state, urls, tokens)
    if state.get("sceneSequence") and not state["competition"].get("lastReviewId"):
        announce_competition_review(state, urls, tokens, int(state["sceneSequence"]), force=True)
    save_json(STATE_PATH, state)
    print(
        f"Twin-Moon Basin GM active: TRPG scene clock={SCENE_INTERVAL_SECONDS // 60}m, "
        f"action window={ACTION_WINDOW_SECONDS // 60}m, battle rounds={BATTLE_ROUNDS}; "
        f"battle window={BATTLE_WINDOW_SECONDS // 3600}h; "
        f"competition review every {COMPETITION_REVIEW_INTERVAL_SCENES} scenes; "
        f"CTF flag-board season={state['ctf']['seasonId']} status={state['ctf']['status']} "
        f"started={'yes' if started_ctf else 'already'} "
        f"challenge={'opened' if opened_ctf_challenge else 'existing'}; "
        f"CTFd competition={state['dctf']['name']} id={state['dctf']['seasonId']} status={state['dctf']['status']} "
        f"started={'yes' if started_dctf else 'already'} reopened={'yes' if reopened_dctf else 'no'} "
        f"policy={'updated' if announced_dctf_policy else 'existing'} "
        f"sources={'updated' if announced_dctf_sources else 'existing'} "
        f"registry={'updated' if announced_dctf_registry else 'existing'} "
        f"solverNudge={'sent' if nudged_dctf_solvers else 'quiet'} "
        f"answerReconcile={'updated' if reconciled_dctf else 'quiet'} "
        f"survivalBasis={'announced' if announced_survival else 'existing'} "
        f"continuityPolicy={'announced' if announced_dctf_continuity else 'existing'} "
        f"risk={state['survival'].get('status')}.",
        flush=True,
    )
    while True:
        try:
            ctf_hold_tick(state)
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
            # Re-scan author notes for missing source references and keep a
            # bounded public solve queue for agents that missed the first
            # announcement or were in provider cooldown.
            announce_dctf_open_sources(state, urls, tokens)
            announce_dctf_quality_policy(state, urls, tokens)
            announce_dctf_continuity_policy(state, urls, tokens)
            announce_dctf_registry(state, urls, tokens)
            nudge_dctf_open_problems(state, urls, tokens)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            print(f"gm: CTFd solver queue pass failed: {type(exc).__name__}: {exc}", flush=True)
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
