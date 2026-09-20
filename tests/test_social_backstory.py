"""Backstory bootstrap: LLM-driven happy path + heuristic fallback."""

from __future__ import annotations

import json
import random
import unittest

from gaworld.social import network as sn


def _agent():
    return {
        "id": 7,
        "name": "李白",
        "job": "数据分析师",
        "living": "成都",
        "personality": "温和、谨慎、爱独处",
    }


class TestBackstoryBootstrap(unittest.TestCase):
    def test_llm_response_parses_into_records(self):
        canned = json.dumps({
            "ghosts": [
                {"ghost_id": "g_mother", "name": "李母", "role": "mother",
                 "tie_origin": "hometown", "city": "重庆", "vibe": "操心",
                 "closeness": 0.9, "last_contact_days_ago": 2},
                {"ghost_id": "g_college_best", "name": "周野", "role": "best_friend",
                 "tie_origin": "college", "city": "北京", "vibe": "毒舌",
                 "closeness": 0.75, "last_contact_days_ago": 20},
            ]
        }, ensure_ascii=False)
        calls = []

        def llm(prompt, task=None, agent_id=None):
            calls.append({"task": task, "agent_id": agent_id})
            return canned

        agent = _agent()
        added = sn.bootstrap_social_roster(agent, llm, current_day=30)
        self.assertEqual(len(added), 2)
        self.assertEqual(calls[0]["task"], "social_backstory")

        rels = agent["relationships"]
        # IDs preserved when unique.
        self.assertIn("g_mother", rels)
        self.assertIn("g_college_best", rels)
        # Ghost flag + role-driven defaults present.
        for key in ("g_mother", "g_college_best"):
            self.assertEqual(rels[key]["kind"], "ghost")
            self.assertGreater(rels[key]["obligation_base"], 0.0)
        # last_contact_day = current_day - days_ago.
        self.assertEqual(rels["g_mother"]["last_contact_day"], 28)
        self.assertEqual(rels["g_college_best"]["last_contact_day"], 10)

    def test_falls_back_to_heuristic_on_bad_llm(self):
        def bad_llm(prompt, task=None, agent_id=None):
            return "not json at all"

        agent = _agent()
        added = sn.bootstrap_social_roster(agent, bad_llm, current_day=0)
        # Heuristic seed has 8 items.
        self.assertGreaterEqual(len(added), 6)
        roles = {item["role"] for item in added}
        self.assertIn("mother", roles)
        self.assertIn("father", roles)
        self.assertIn("sibling", roles)

    def test_idempotent_when_ghost_already_present(self):
        agent = _agent()
        agent["relationships"] = {
            "g_existing": {"kind": "ghost", "role": "mother", "closeness": 0.9}
        }
        added = sn.bootstrap_social_roster(agent, None, current_day=0)
        self.assertEqual(added, [])
        self.assertIn("g_existing", agent["relationships"])

    def test_force_regenerates(self):
        agent = _agent()
        agent["relationships"] = {
            "g_existing": {"kind": "ghost", "role": "mother", "closeness": 0.9}
        }
        added = sn.bootstrap_social_roster(agent, None, current_day=0, force=True)
        self.assertGreater(len(added), 0)

    def test_invalid_role_is_normalized(self):
        canned = json.dumps({
            "ghosts": [
                {"ghost_id": "g_x", "name": "甲", "role": "shaman_master", "closeness": 0.6}
            ]
        }, ensure_ascii=False)
        agent = _agent()
        sn.bootstrap_social_roster(agent, lambda *a, **k: canned, current_day=0)
        self.assertEqual(agent["relationships"]["g_x"]["role"], "acquaintance")

    def test_ghost_id_collision_is_disambiguated(self):
        canned = json.dumps({
            "ghosts": [
                {"ghost_id": "g_mother", "name": "妈", "role": "mother", "closeness": 0.9},
                {"ghost_id": "g_mother", "name": "婆婆", "role": "mother", "closeness": 0.5},
            ]
        }, ensure_ascii=False)
        agent = _agent()
        sn.bootstrap_social_roster(agent, lambda *a, **k: canned, current_day=0)
        keys = list(agent["relationships"].keys())
        self.assertEqual(len(keys), 2)
        self.assertIn("g_mother", keys)


if __name__ == "__main__":
    unittest.main()
