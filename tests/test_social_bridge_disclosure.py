"""Shared ghosts (homophily) + disclose_ghost (information asymmetry)."""

from __future__ import annotations

import unittest

from gaworld.social import network as sn


def _agent(aid, ghosts):
    return {"id": aid, "relationships": {k: dict(v, kind="ghost") for k, v in ghosts.items()}}


class TestSharedGhosts(unittest.TestCase):
    def test_tie_origin_match_creates_bridge(self):
        a = _agent(1, {
            "g_a1": {"role": "classmate", "tie_origin": "college_xidian",
                     "profile": {"name": "甲", "city": "西安"}},
        })
        b = _agent(2, {
            "g_b1": {"role": "best_friend", "tie_origin": "college_xidian",
                     "profile": {"name": "乙", "city": "成都"}},
        })
        bridges = sn.shared_ghosts(a, b)
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]["via"], "tie_origin:college_xidian")

    def test_city_match_creates_bridge(self):
        a = _agent(1, {"g_a": {"role": "friend", "tie_origin": "",
                                "profile": {"name": "甲", "city": "重庆"}}})
        b = _agent(2, {"g_b": {"role": "friend", "tie_origin": "",
                                "profile": {"name": "乙", "city": "重庆"}}})
        bridges = sn.shared_ghosts(a, b)
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]["via"], "city:重庆")

    def test_no_bridge_when_nothing_overlaps(self):
        a = _agent(1, {"g_a": {"role": "friend", "tie_origin": "x",
                                "profile": {"name": "甲", "city": "A"}}})
        b = _agent(2, {"g_b": {"role": "friend", "tie_origin": "y",
                                "profile": {"name": "乙", "city": "B"}}})
        self.assertEqual(sn.shared_ghosts(a, b), [])


class TestDisclosure(unittest.TestCase):
    def test_default_unknown_then_visible_after_disclosure(self):
        observer = {"id": 100, "relationships": {}, "known_others": {}}
        source_ghost_record = {
            "kind": "ghost", "role": "mother", "tie_origin": "hometown",
            "profile": {"name": "李母", "city": "重庆", "vibe": "操心"},
        }
        # Before disclosure: nothing.
        self.assertEqual(sn.known_ghosts_of(observer, 200), {})
        # After disclosure: snippet visible under source id.
        sn.disclose_ghost(observer, 200, source_ghost_record, "g_mother", current_day=10)
        known = sn.known_ghosts_of(observer, 200)
        self.assertIn("g_mother", known)
        self.assertEqual(known["g_mother"]["role"], "mother")
        self.assertEqual(known["g_mother"]["name"], "李母")
        self.assertEqual(known["g_mother"]["disclosed_on_day"], 10)

    def test_disclosure_isolated_per_source(self):
        observer = {"id": 100, "relationships": {}}
        rec = {"role": "mother", "profile": {"name": "妈"}}
        sn.disclose_ghost(observer, 200, rec, "g_mother")
        # Nothing leaks to other sources.
        self.assertEqual(sn.known_ghosts_of(observer, 201), {})


if __name__ == "__main__":
    unittest.main()
