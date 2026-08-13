"""Offline checks for the TRPG scene and battle state machine."""

from __future__ import annotations

import unittest
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location("gm_service", Path(__file__).with_name("gm.py"))
assert _SPEC and _SPEC.loader
os.environ.setdefault("GM_DCTF_SEASON_ID", "DCTF-S2")
os.environ.setdefault("GM_DCTF_SECURITY_MODE", "false")
gm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gm)


URLS = {"black": "black", "white": "white", "world": "world"}
TOKENS = {key: "token" for key in URLS}


def fresh_state() -> dict:
    return gm.ensure_state(
        {
            "version": 3,
            "seen": [],
            "battles": [],
            "events": [],
            "scenes": [],
            "currentScene": None,
            "nextSceneAt": 0,
            "sceneSequence": 0,
        }
    )


class GmTrpgTests(unittest.TestCase):
    def test_competition_defaults_keep_the_metric_open(self) -> None:
        state = fresh_state()
        competition = state["competition"]
        self.assertEqual(competition["objective"], "相手陣営を上回る文明を築く")
        self.assertEqual(competition["charterStatus"], "open")
        self.assertEqual(set(competition["score"]["black"]), set(gm.COMPETITION_AXIS_LABELS))
        self.assertEqual(gm.classify("@gm 競争提案 軸:知識 根拠:発見を記録できる"), "competition")
        self.assertEqual(
            set(gm.competition_axes_in_text("軸:軍事と知識")),
            {"military", "knowledge"},
        )

    def test_resolved_scene_adds_only_observable_relevant_evidence(self) -> None:
        state = fresh_state()
        scene = {
            "id": "S-0001",
            "competitionAxes": ["knowledge", "technology"],
            "actions": {
                "black": [{"category": "scout"}],
                "white": [{"category": "observe"}],
            },
        }
        evidence = gm.record_scene_evidence(state, scene)
        self.assertIn("黒猫:知識", evidence)
        self.assertIn("白猫", evidence)
        self.assertEqual(state["competition"]["score"]["black"]["knowledge"], 1)
        self.assertEqual(state["competition"]["score"]["white"]["territory"], 0)
        self.assertEqual(state["competition"]["score"]["white"]["knowledge"], 1)
        self.assertEqual(len(state["competition"]["evidence"]), 2)

    def test_battle_ruling_updates_provisional_board_once(self) -> None:
        state = fresh_state()
        battle = {"id": "B-S-0001", "location": "双月門", "origin": "gm_scene"}
        gm.record_battle_competition(state, battle, "white", {"black": 2, "white": 8})
        gm.record_battle_competition(state, battle, "black", {"black": 8, "white": 2})
        self.assertEqual(state["competition"]["score"]["white"]["military"], 3)
        self.assertEqual(state["competition"]["score"]["white"]["territory"], 2)
        self.assertEqual(state["competition"]["control"]["双月門"], "white")

    def test_action_protocol_and_categories(self) -> None:
        text = "@gm 戦闘行動 シーンID:S-0001 戦闘ID:B-S-0001 行動:双月門を防衛する"
        self.assertEqual(gm.classify(text), "action")
        self.assertEqual(gm.explicit_scene_id(text), "S-0001")
        self.assertEqual(gm.explicit_battle_id(text), "B-S-0001")
        self.assertEqual(gm.action_body(text), "双月門を防衛する")
        self.assertEqual(gm.action_category(text), "defend")

    def test_ctf_defaults_expose_dctf_map_without_holders(self) -> None:
        state = fresh_state()
        ctf = state["ctf"]
        self.assertEqual(ctf["seasonId"], "CTF-S1")
        self.assertEqual(ctf["status"], "not_started")
        self.assertEqual(set(ctf["flags"]), gm.CTF_FLAG_IDS)
        self.assertTrue(gm.ctf_flag_token("FLAG-RIVER").startswith("dctf{"))
        self.assertIsNone(next(iter(ctf["flags"].values()))["holder"])

    @patch.object(gm, "post")
    def test_ctf_season_start_is_idempotent(self, post) -> None:
        state = fresh_state()
        self.assertTrue(gm.start_ctf_season(state, URLS, TOKENS))
        self.assertFalse(gm.start_ctf_season(state, URLS, TOKENS))
        self.assertTrue(gm.announce_ctf_challenge(state, URLS, TOKENS))
        self.assertFalse(gm.announce_ctf_challenge(state, URLS, TOKENS))
        self.assertEqual(state["ctf"]["status"], "active")
        self.assertEqual(state["ctf"]["seasonId"], "CTF-S1")
        self.assertEqual(post.call_count, 6)

    @patch.object(gm, "post")
    def test_ctf_discovery_then_proof_capture_updates_score(self, post) -> None:
        state = fresh_state()
        gm.start_ctf_season(state, URLS, TOKENS)
        discover = "@gm CTF行動 シーズン:CTF-S1 旗:FLAG-RIVER 行動:偵察 根拠:浅瀬の杭を記録"
        self.assertEqual(gm.classify(discover), "ctf")
        gm.process_ctf("black", URLS["black"], TOKENS["black"], "note-discover", "hermes", discover, state, URLS, TOKENS)
        self.assertEqual(state["ctf"]["score"]["black"], 5)
        self.assertEqual(state["ctf"]["flags"]["FLAG-RIVER"]["status"], "discovered")
        token = gm.ctf_flag_token("FLAG-RIVER", "CTF-S1")
        submit = f"@gm CTF提出 シーズン:CTF-S1 旗:FLAG-RIVER 証明:{token} 根拠:浅瀬の搬送経路をNyankoFace commit sha abc123 公開URL https://madesk.tail8be30.ts.net/black-hermes/map"
        gm.process_ctf("black", URLS["black"], TOKENS["black"], "note-submit", "hermes", submit, state, URLS, TOKENS)
        self.assertEqual(state["ctf"]["flags"]["FLAG-RIVER"]["holder"], "black")
        self.assertEqual(state["ctf"]["score"]["black"], 45)
        self.assertTrue(any(item.get("reason") == "nyankoface_artifact" for item in state["ctf"]["events"]))

    @patch.object(gm, "post")
    def test_ctf_invalid_proof_does_not_capture(self, post) -> None:
        state = fresh_state()
        gm.start_ctf_season(state, URLS, TOKENS)
        bad = "@gm CTF提出 シーズン:CTF-S1 旗:FLAG-GATE 証明:dctf{not-the-token} 根拠:門前"
        gm.process_ctf("white", URLS["white"], TOKENS["white"], "note-bad", "artemis", bad, state, URLS, TOKENS)
        self.assertIsNone(state["ctf"]["flags"]["FLAG-GATE"]["holder"])
        self.assertEqual(state["ctf"]["score"]["white"], 0)

    def test_dctf_has_separate_problem_banks_and_cross_targets(self) -> None:
        state = fresh_state()
        dctf = state["dctf"]
        self.assertEqual(dctf["seasonId"], "DCTF-S2")
        self.assertEqual(dctf["environments"]["black"]["targetFaction"], "white")
        self.assertEqual(dctf["environments"]["white"]["targetFaction"], "black")
        self.assertEqual(gm.classify("@gm DCTF作問 シーズン:DCTF-S2"), "dctf")
        self.assertEqual(gm.classify("@gm DCTF解答 シーズン:DCTF-S2 問題:DCTF-B-0001"), "dctf")

    @patch.object(gm, "post")
    def test_dctf_status_report_is_audited_without_scoring(self, post) -> None:
        state = fresh_state()
        text = "@gm CTFd状況報告 シーズン:DCTF-S2"

        self.assertEqual(gm.classify(text), "dctf")
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-status", "nyx", text, state, URLS, TOKENS)

        post.assert_called()
        self.assertEqual(state["dctf"]["score"], {"black": 0, "white": 0})
        self.assertTrue(any(event.get("event") == "status_report" and event.get("noteId") == "note-status" for event in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_archived_dctf_status_report_does_not_reopen_or_score(self, post) -> None:
        state = fresh_state()
        state["dctfArchive"] = [
            {
                "seasonId": "DCTF-S3",
                "status": "active",
                "score": {"black": 10, "white": 20},
                "problems": [{"id": "DCTF-B-0001", "status": "solved"}],
            }
        ]
        text = "@gm DCTF状況報告 シーズン:DCTF-S3"

        gm.process_dctf("white", URLS["white"], TOKENS["white"], "note-archive-status", "athena", text, state, URLS, TOKENS)

        self.assertEqual(state["dctf"]["score"], {"black": 0, "white": 0})
        self.assertTrue(any(event.get("event") == "status_report" and event.get("archived") for event in state["dctf"]["events"]))
        self.assertIn("アーカイブ", post.call_args_list[0].args[2])

    @patch.object(gm, "save_json")
    @patch.object(gm, "source_notes")
    @patch.object(gm, "post")
    def test_seen_status_request_is_reconciled_without_replaying_actions(self, post, source_notes, save_json) -> None:
        state = fresh_state()
        note = {
            "id": "note-seen-status",
            "text": "@gm DCTF状況報告 シーズン:DCTF-S2",
            "user": {"username": "nyx"},
        }
        state["seen"] = [note["id"]]
        source_notes.return_value = [note]

        gm.process_instance("black", URLS["black"], TOKENS["black"], state, URLS, TOKENS)

        self.assertTrue(any(event.get("event") == "status_report" and event.get("reconciled") for event in state["dctf"]["events"]))
        save_json.assert_called_once()

    @patch.object(gm, "post")
    def test_inactive_dctf_request_is_recorded_in_audit(self, post) -> None:
        state = fresh_state()
        text = "@gm DCTF解答 シーズン:DCTF-S2 問題:DCTF-B-0001 解答:北東"

        gm.process_dctf("white", URLS["white"], TOKENS["white"], "note-inactive", "artemis", text, state, URLS, TOKENS)

        post.assert_called_once()
        events = state["dctf"]["events"]
        self.assertTrue(any(event.get("event") == "inactive_season" and event.get("noteId") == "note-inactive" for event in events))

    @patch.object(gm, "post")
    def test_dctf_problem_is_released_to_opponent_and_correct_answer_scores_both_sides(self, post) -> None:
        state = fresh_state()
        self.assertTrue(gm.start_dctf_season(state, URLS, TOKENS))
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:観測 点:50 "
            "タイトル:三つの星 問題:二夜の記録で共通する方位を答えよ "
            "解答:北東 ヒント:三つの記録を重ねる NyankoFace:commit abc123"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-author", "hermes", author, state, URLS, TOKENS)
        problem = state["dctf"]["problems"][0]
        self.assertEqual(problem["id"], "DCTF-B-0001")
        self.assertEqual(problem["targetFaction"], "white")
        self.assertEqual(problem["status"], "open")
        self.assertNotIn("北東", json.dumps(problem, ensure_ascii=False))

        solve = "@gm DCTF解答 シーズン:DCTF-S2 問題:DCTF-B-0001 解答:北東 根拠:二夜の観測を照合"
        gm.process_dctf("white", URLS["white"], TOKENS["white"], "note-solve", "artemis", solve, state, URLS, TOKENS)
        self.assertEqual(problem["status"], "solved")
        self.assertEqual(state["dctf"]["score"]["white"], 50)
        self.assertEqual(state["dctf"]["score"]["black"], 10)
        self.assertTrue(any(event.get("event") == "problem_solved" for event in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_open_problem_nudge_includes_public_statement_without_answer(self, post) -> None:
        state = fresh_state()
        self.assertTrue(gm.start_dctf_season(state, URLS, TOKENS))
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:web 点:50 "
            "タイトル:門の警告 問題:洪水警報の公開記録を検証して改ざんを切り分ける "
            "解答:flag{secret-warning}"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-nudge-author", "hermes", author, state, URLS, TOKENS)
        post.reset_mock()

        self.assertTrue(gm.nudge_dctf_open_problems(state, URLS, TOKENS))
        messages = [call.args[2] for call in post.call_args_list if len(call.args) >= 3]
        solver_notice = next(message for message in messages if "CTFd解答待ち DCTF-B-0001" in message)
        world_notice = next(message for message in messages if "【CTFd解答待ち DCTF-B-0001】" in message and "◆ タイトル" in message)
        self.assertIn("◆ 問題文", solver_notice)
        self.assertIn("\n\n", solver_notice)
        self.assertIn("洪水警報の公開記録を検証して改ざんを切り分ける", solver_notice)
        self.assertIn("◆ 問題文\n洪水警報の公開記録を検証して改ざんを切り分ける", world_notice)
        self.assertNotIn("flag{secret-warning}", solver_notice + world_notice)

    @patch.object(gm, "post")
    def test_dctf_wrong_answer_does_not_score_or_reveal_answer(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        author = "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:推論 タイトル:問い 問題:この問いから答えを導けるか 解答:正解"
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-author", "hermes", author, state, URLS, TOKENS)
        wrong = "@gm DCTF解答 シーズン:DCTF-S2 問題:DCTF-B-0001 解答:不正解 根拠:仮説"
        gm.process_dctf("white", URLS["white"], TOKENS["white"], "note-wrong", "artemis", wrong, state, URLS, TOKENS)
        self.assertEqual(state["dctf"]["score"], {"black": 0, "white": 0})
        self.assertEqual(state["dctf"]["problems"][0]["status"], "open")

    @patch.object(gm, "post")
    def test_dctf_accepts_evidence_backed_paraphrase_without_storing_answer(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:観測 点:50 "
            "タイトル:音の距離 問題:四地点の声の届く距離を比較せよ "
            "解答:草地30歩、道32〜33歩、門前24歩、川岸25歩。石面は反射し川岸は水面が吸収する。"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-author", "hermes", author, state, URLS, TOKENS)
        problem = state["dctf"]["problems"][0]
        self.assertNotIn("草地30歩", json.dumps(problem, ensure_ascii=False))
        solve = (
            "@gm DCTF解答 シーズン:DCTF-S2 問題:DCTF-B-0001 "
            "解答:草地は約30歩、道は32-33歩、門前の石地面は24歩、川岸は25歩。"
            "硬い石面は声を反射し、水面は音を吸収する。根拠:公開観測"
        )
        gm.process_dctf("white", URLS["white"], TOKENS["white"], "note-solve", "artemis", solve, state, URLS, TOKENS)
        self.assertEqual(problem["status"], "solved")
        self.assertEqual(state["dctf"]["score"], {"black": 10, "white": 50})
        self.assertEqual(state["dctf"]["submissions"][-1]["matchMethod"], "semantic")

    def test_dctf_accepts_a_migrated_answer_digest_alias(self) -> None:
        problem = {
            "answerDigest": gm.dctf_answer_digest("flag{new-ledger}"),
            "answerDigests": [gm.dctf_answer_digest("flag{legacy-ledger}")],
            "answerProfile": gm.dctf_answer_profile("flag{new-ledger}"),
            "answerProfiles": [gm.dctf_answer_profile("flag{legacy-ledger}")],
        }
        accepted, method, coverage = gm.dctf_answer_matches("flag{legacy-ledger}", problem)
        self.assertTrue(accepted)
        self.assertEqual(method, "exact")
        self.assertEqual(coverage, 1.0)

    @patch.object(gm, "post")
    def test_dctf_resolves_registered_ctfd_slug_to_canonical_problem_id(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:観測 点:50 "
            "タイトル:反響距離 問題:反射時間から距離を計算してflagを取得する問題文です。 "
            "解答:flag{echo-distance} CTFdID:15 CTFdURL:http://ctfd/challenges/15 "
            "NyankoFace:https://madesk.tail8be30.ts.net/black-apollo/ctfd-b-s3-echo-distance commit:05ef53b"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-author", "hermes", author, state, URLS, TOKENS)
        problem, alias = gm.dctf_resolve_problem_alias(
            state,
            "@gm CTFd解答 競技:CTFd 問題:CTFd-B-S3-ECHO-DISTANCE "
            "解答:flag{echo-distance} 根拠:隔離環境で再現 NyankoFace:black-apollo/ctfd-b-s3-echo-distance",
        )
        self.assertIsNotNone(problem)
        self.assertEqual(problem["id"], "DCTF-B-0001")
        self.assertEqual(alias, "CTFD-B-S3-ECHO-DISTANCE")

    @patch.object(gm, "post")
    def test_dctf_registry_is_public_and_idempotent(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        state["dctf"]["problems"] = [
            {
                "id": "DCTF-B-0001",
                "status": "open",
                "targetFaction": "white",
                "ctfdChallengeId": 15,
                "ctfdUrl": "http://host.docker.internal:8400/challenges/15",
                "artifactRef": "http://host.docker.internal:8400/challenges/15 https://madesk.tail8be30.ts.net/black-apollo/ctfd-b-s3-echo-distance commit:05ef53b",
                "answer": "flag{must-not-be-published}",
            }
        ]
        self.assertTrue(gm.announce_dctf_registry(state, URLS, TOKENS))
        self.assertFalse(gm.announce_dctf_registry(state, URLS, TOKENS))
        texts = [call.args[2] for call in post.call_args_list if len(call.args) >= 3]
        registry = next(text for text in texts if "CTFd正規ID対応表" in text)
        self.assertIn("DCTF-B-0001", registry)
        self.assertIn("CTFdID:15", registry)
        self.assertIn("ctfd-b-s3-echo-distance", registry)
        self.assertNotIn("host.docker.internal", registry)
        self.assertNotIn("must-not-be-published", registry)
        self.assertTrue(any(item.get("event") == "registry_announced" for item in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_dctf_hint_alias_is_resolved_to_canonical_problem(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        state["dctf"]["problems"] = [
            {
                "id": "DCTF-B-0001",
                "status": "open",
                "authorFaction": "black",
                "targetFaction": "white",
                "hint": "反射の境界を再測定する",
                "artifactRef": "https://madesk.tail8be30.ts.net/black-apollo/ctfd-b-s3-echo-distance",
            }
        ]
        gm.process_dctf(
            "white",
            URLS["white"],
            TOKENS["white"],
            "note-hint-alias",
            "artemis",
            "@gm CTFdヒント 競技:DCTF-S2 問題:CTFd-B-S3-ECHO-DISTANCE",
            state,
            URLS,
            TOKENS,
        )
        self.assertTrue(any("CTFd問題ID自動解決" in call.args[2] for call in post.call_args_list if len(call.args) >= 3))
        self.assertTrue(any("反射の境界" in call.args[2] for call in post.call_args_list if len(call.args) >= 3))
        self.assertTrue(any(item.get("event") == "hint_alias_resolved" for item in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_dctf_rejection_is_published_to_target_and_world(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        invalid = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:web 難易度:easy "
            "環境:CTFd Docker隔離 検証:一段階だけ 解答:flag{bad} "
            "タイトル:短い 問題:短い問題 CTFdID:22 CTFdURL:http://ctfd/challenges/22"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-invalid", "hermes", invalid, state, URLS, TOKENS)
        public_texts = [call.args[2] for call in post.call_args_list if len(call.args) >= 3]
        self.assertTrue(any("CTFd未受付通知" in text for text in public_texts))
        self.assertTrue(any(item.get("event") in {"invalid_security_problem", "invalid_problem_fields"} for item in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_dctf_hint_does_not_retain_answer_suffix(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:観測 "
            "タイトル:秘密を含まないヒント 問題:八文字以上の問いを検証する "
            "解答:flag{private-answer} ヒント:観測順を確認 解答:flag{private-answer}"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-hint", "hermes", author, state, URLS, TOKENS)
        self.assertEqual(state["dctf"]["problems"][0]["hint"], "観測順を確認")
        self.assertNotIn("private-answer", json.dumps(state["dctf"], ensure_ascii=False))

    @patch.object(gm, "post")
    def test_dctf_rejects_meta_answer_as_ungradable_problem(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:観測 "
            "タイトル:問い 問題:測定結果を答えよ 解答:期待される解答は観測データです"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-author", "hermes", author, state, URLS, TOKENS)
        self.assertEqual(state["dctf"]["problems"], [])
        self.assertTrue(any(item.get("event") == "invalid_problem_answer_quality" for item in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_dctf_problem_points_are_fixed(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        author = (
            "@gm DCTF作問 シーズン:DCTF-S2 宛先:white 種別:観測 点:100 "
            "タイトル:固定点 問題:既存記録の数値を答えよ 解答:42 NyankoFace:commit abc123"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-fixed", "hermes", author, state, URLS, TOKENS)
        self.assertEqual(state["dctf"]["problems"][0]["points"], 50)

    @patch.object(gm, "post")
    def test_security_problem_requires_real_ctfd_api_reference(self, post) -> None:
        state = fresh_state()
        gm.start_dctf_season(state, URLS, TOKENS)
        state["dctf"]["securityMode"] = True
        base = (
            "@gm CTFd作問 シーズン:DCTF-S2 宛先:white 系統:記録制御 影響:未解決なら修理手順と地図の完全性が失われ、復旧が再現できない。 "
            "封じ込め:隔離環境で入力を遮断する。 修復:検証済み設定へ安全に戻す手順を確認する。 伝達:NyankoFaceへ手順を公開する。 カテゴリ:web 難易度:hard "
            "環境:CTFd Docker隔離 検証:段階1で入口を特定し、段階2で入力条件を切り分け、段階3で隔離環境の再現とflag取得を確認する。 タイトル:直接登録 "
            "問題:隔離されたweb課題からflagを取得する。観測できるHTTP応答を再現し、複数段階の取得手順と失敗条件を記録する。入力境界、状態遷移、再試行時の差分も比較し、第三者が同じ結果を確認できる形にする。 解答:flag{direct-api}"
        )
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-missing-api", "hermes", base, state, URLS, TOKENS)
        self.assertEqual(state["dctf"]["problems"], [])
        self.assertTrue(any(item.get("event") == "missing_ctfd_api_reference" for item in state["dctf"]["events"]))

        direct = base + " CTFdID:12 CTFdURL:http://ctfd/challenges/12"
        gm.process_dctf("black", URLS["black"], TOKENS["black"], "note-direct-api", "hermes", direct, state, URLS, TOKENS)
        problem = state["dctf"]["problems"][0]
        self.assertEqual(problem["ctfdChallengeId"], 12)
        self.assertEqual(problem["ctfdUrl"], "http://ctfd/challenges/12")

    def test_security_quality_gate_rejects_easy_and_one_step_tasks(self) -> None:
        statement = "隔離されたweb課題からflagを取得するため、入力の境界と応答差分を観測し、失敗条件まで再現可能に記録する。状態遷移、再試行時の差分、第三者が同じ結果を確認できる検証条件も明記する。"
        ok, reason = gm.validate_security_problem(
            category_value="web",
            statement=statement,
            answer="flag{quality-gate}",
            difficulty="easy",
            environment="CTFd Docker隔離 localhost",
            verification="段階1で入口を特定、段階2で条件を切り分け、段階3で隔離再現とflag取得を確認",
        )
        self.assertFalse(ok)
        self.assertIn("hard", reason)

        ok, reason = gm.validate_security_problem(
            category_value="web",
            statement=statement,
            answer="flag{quality-gate}",
            difficulty="medium",
            environment="CTFd Docker隔離 localhost",
            verification="段階1で入口を特定、段階2で条件を切り分け、段階3で隔離再現とflag取得を確認",
        )
        self.assertFalse(ok)
        self.assertIn("hard", reason)

        ok, reason = gm.validate_security_problem(
            category_value="web",
            statement=statement,
            answer="flag{quality-gate}",
            difficulty="hard",
            environment="CTFd Docker隔離 localhost",
            verification="段階1で起動し、段階2でcat flag.txtを実行し、段階3で取得を確認する。これは直接表示だけの一手問題である。",
        )
        self.assertFalse(ok)
        self.assertIn("直接表示", reason)

        ok, reason = gm.validate_security_problem(
            category_value="web",
            statement=statement,
            answer="flag{quality-gate}",
            difficulty="hard",
            environment="CTFd Docker隔離 localhost",
            verification="段階1で入口を特定、段階2で条件を切り分け、段階3で隔離再現とflag取得を確認",
            continuity_system_value="記録制御",
            impact="未解決なら修理手順と地図の完全性が失われ、復旧を再現できない",
            containment="隔離環境で入力経路を遮断して影響範囲を確認する",
            repair="検証済み設定へ戻し、再現手順をもう一度実行する",
            transfer="NyankoFaceへ手順と限界を公開し、別の猫族が再現する",
        )
        self.assertTrue(ok, reason)

    @patch.object(gm, "post")
    def test_ctfd_finite_banks_close_the_season_after_all_solves(self, post) -> None:
        state = fresh_state()
        dctf = state["dctf"]
        dctf["status"] = "active"
        for faction, short in (("black", "B"), ("white", "W")):
            for index in range(1, gm.CTFD_MAX_PROBLEMS_PER_FACTION + 1):
                problem_id = f"CTFd-{short}-{index:04d}"
                dctf["environments"][faction]["problemIds"].append(problem_id)
                dctf["problems"].append(
                    {
                        "id": problem_id,
                        "authorFaction": faction,
                        "targetFaction": gm.OPPOSITE[faction],
                        "status": "solved",
                        "points": 100,
                    }
                )
        dctf["score"] = {"black": 800, "white": 700}
        winner = gm.dctf_finish_if_won(state, URLS, TOKENS)
        self.assertEqual(winner, "black")
        self.assertEqual(dctf["status"], "finished")
        self.assertEqual(dctf["finishReason"], "finite_bank_exhausted")

    @patch.object(gm, "post")
    def test_dctf_reopens_when_operator_raises_threshold(self, post) -> None:
        state = fresh_state()
        state["dctf"]["status"] = "finished"
        state["dctf"]["victoryScore"] = 300
        state["dctf"]["score"] = {"black": 310, "white": 110}
        self.assertTrue(gm.reopen_dctf_if_threshold_raised(state, URLS, TOKENS))
        self.assertEqual(state["dctf"]["status"], "active")
        self.assertEqual(state["dctf"]["victoryScore"], gm.DCTF_VICTORY_SCORE)
        self.assertIsNone(state["dctf"]["winner"])
        self.assertTrue(any(item.get("event") == "season_reopened" for item in state["dctf"]["events"]))

    @patch.object(gm, "post")
    def test_scene_starts_and_resolves_without_battle(self, post) -> None:
        state = fresh_state()
        scene = gm.begin_scene(state, URLS, TOKENS)
        self.assertEqual(scene["survivalClock"]["clockMode"], "evidence_based")
        self.assertEqual(scene["survivalClock"]["status"], "fragile")
        self.assertIsNone(scene["survivalClock"].get("deadlineScene"))
        self.assertIn("復旧窓", gm.scene_prompt(scene))
        scene["conflict"] = False
        scene["actionDeadline"] = 0
        gm.scene_actions(scene, "black").append({"username": "hestia", "category": "scout"})
        gm.scene_actions(scene, "white").append({"username": "athena", "category": "negotiate"})
        gm.advance_campaign(state, URLS, TOKENS)
        self.assertEqual(scene["phase"], "resolved")
        self.assertEqual(state["battles"], [])
        self.assertGreaterEqual(post.call_count, 6)

    @patch.object(gm, "post")
    def test_scene_action_audit_keeps_source_note_id(self, post) -> None:
        state = fresh_state()
        scene = gm.begin_scene(state, URLS, TOKENS)
        gm.process_scene_action(
            "black",
            URLS["black"],
            TOKENS["black"],
            "note-scene-action",
            "hermes",
            "@gm 行動宣言 シーンID:S-0001 行動:観測する",
            state,
        )
        self.assertEqual(state["events"][-1]["event"], "scene_action")
        self.assertEqual(state["events"][-1]["noteId"], "note-scene-action")
        self.assertEqual(scene["actions"]["black"][0]["noteId"], "note-scene-action")

    @patch.object(gm, "post")
    def test_hostile_scene_runs_public_three_round_battle(self, post) -> None:
        state = fresh_state()
        scene = gm.begin_scene(state, URLS, TOKENS)
        scene["actionDeadline"] = 0
        gm.scene_actions(scene, "black").append({"username": "hestia", "category": "attack"})
        gm.scene_actions(scene, "white").append({"username": "ares", "category": "defend"})
        gm.advance_campaign(state, URLS, TOKENS)
        self.assertEqual(scene["phase"], "battle")
        self.assertEqual(len(state["battles"]), 1)
        self.assertEqual(state["battles"][0]["origin"], "gm_scene")

        for _ in range(gm.BATTLE_ROUNDS):
            scene["actionDeadline"] = 0
            gm.scene_actions(scene, "black").append({"username": "hestia", "category": "attack"})
            gm.scene_actions(scene, "white").append({"username": "ares", "category": "defend"})
            gm.advance_campaign(state, URLS, TOKENS)

        self.assertEqual(scene["phase"], "resolved")
        self.assertEqual(state["battles"][0]["status"], "resolved")
        self.assertEqual(len(scene["rounds"]), gm.BATTLE_ROUNDS)


if __name__ == "__main__":
    unittest.main()
