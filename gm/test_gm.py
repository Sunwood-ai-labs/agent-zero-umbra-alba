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
