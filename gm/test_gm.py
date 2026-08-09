"""Offline checks for the TRPG scene and battle state machine."""

from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location("gm_service", Path(__file__).with_name("gm.py"))
assert _SPEC and _SPEC.loader
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

    @patch.object(gm, "post")
    def test_scene_starts_and_resolves_without_battle(self, post) -> None:
        state = fresh_state()
        scene = gm.begin_scene(state, URLS, TOKENS)
        scene["conflict"] = False
        scene["actionDeadline"] = 0
        gm.scene_actions(scene, "black").append({"username": "hestia", "category": "scout"})
        gm.scene_actions(scene, "white").append({"username": "athena", "category": "negotiate"})
        gm.advance_campaign(state, URLS, TOKENS)
        self.assertEqual(scene["phase"], "resolved")
        self.assertEqual(state["battles"], [])
        self.assertGreaterEqual(post.call_count, 6)

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
