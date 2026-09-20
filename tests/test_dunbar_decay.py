"""Role-aware decay + Dunbar pruning."""

from __future__ import annotations

import unittest

from gaworld.social import network as sn


class TestDecay(unittest.TestCase):
    def test_kin_decays_far_slower_than_online_friend(self):
        agent = {
            "id": 1,
            "relationships": {
                "g_mom": {
                    "kind": "ghost", "role": "mother",
                    "closeness": 0.80, "trust": 0.80, "obligation": 0.80, "friction": 0.1,
                    "decay_rate": 0.001, "obligation_base": 0.80,
                    "last_contact_day": 0, "last_interaction_day": 0,
                },
                "g_net": {
                    "kind": "ghost", "role": "online_friend",
                    "closeness": 0.80, "trust": 0.80, "obligation": 0.20, "friction": 0.1,
                    "decay_rate": 0.020, "obligation_base": 0.15,
                    "last_contact_day": 0, "last_interaction_day": 0,
                },
            },
        }
        sn.decay_relationships(agent, current_day=30)
        mom = agent["relationships"]["g_mom"]["closeness"]
        net = agent["relationships"]["g_net"]["closeness"]
        self.assertGreater(mom, net)
        # Online friend should drop noticeably (0.80 → ~0.20).
        self.assertLess(net, 0.30)

    def test_long_neglect_increases_obligation_guilt(self):
        agent = {
            "id": 1,
            "relationships": {
                "g_mom": {
                    "kind": "ghost", "role": "mother",
                    "closeness": 0.80, "trust": 0.80, "obligation": 0.50, "friction": 0.1,
                    "decay_rate": 0.001, "obligation_base": 0.80,
                    "last_contact_day": 0, "last_interaction_day": 0,
                },
            },
        }
        before = agent["relationships"]["g_mom"]["obligation"]
        sn.decay_relationships(agent, current_day=60)
        after = agent["relationships"]["g_mom"]["obligation"]
        self.assertGreater(after, before)
        # And it's capped.
        self.assertLessEqual(after, 0.80 * 1.4 + 1e-6)

    def test_closeness_floor_prevents_zero(self):
        agent = {
            "id": 1,
            "relationships": {
                "g_net": {
                    "kind": "ghost", "role": "online_friend",
                    "closeness": 0.05, "trust": 0.05, "obligation": 0.10, "friction": 0.10,
                    "decay_rate": 0.020, "obligation_base": 0.15,
                    "last_contact_day": 0, "last_interaction_day": 0,
                },
            },
        }
        sn.decay_relationships(agent, current_day=999)
        # Should clamp at the floor, not negative.
        self.assertGreaterEqual(agent["relationships"]["g_net"]["closeness"], 0.0)


class TestDunbar(unittest.TestCase):
    def _make_agent_with_n_ghosts(self, n_kin: int, n_weak: int) -> dict:
        rels: dict = {}
        for i in range(n_kin):
            rels[f"k_{i}"] = {
                "kind": "ghost", "role": "mother",
                "closeness": 0.8, "trust": 0.8, "obligation": 0.8, "friction": 0.1,
                "decay_rate": 0.001, "obligation_base": 0.80,
            }
        for i in range(n_weak):
            rels[f"w_{i}"] = {
                "kind": "ghost", "role": "online_friend",
                "closeness": 0.05 + (i * 0.001),  # tiny variance so weakest is i=0
                "trust": 0.05, "obligation": 0.10, "friction": 0.20,
                "decay_rate": 0.020, "obligation_base": 0.15,
            }
        return {"id": 1, "relationships": rels}

    def test_prunes_weakest_when_over_outer_cap(self):
        agent = self._make_agent_with_n_ghosts(n_kin=5, n_weak=200)
        result = sn.enforce_dunbar(agent)
        self.assertEqual(result["kept"], 150)
        self.assertEqual(result["pruned"], 55)
        # Weakest weak-ties pruned first; kin all survive.
        for i in range(5):
            self.assertIn(f"k_{i}", agent["relationships"])

    def test_kin_protected_even_at_low_weight(self):
        agent = self._make_agent_with_n_ghosts(n_kin=0, n_weak=160)
        # Add one kin with low closeness — should never be pruned.
        agent["relationships"]["k_low"] = {
            "kind": "ghost", "role": "mother",
            "closeness": 0.02, "trust": 0.02, "obligation": 0.80, "friction": 0.40,
            "decay_rate": 0.001, "obligation_base": 0.80,
        }
        sn.enforce_dunbar(agent)
        self.assertIn("k_low", agent["relationships"])

    def test_tiering_labels_top_records(self):
        agent = self._make_agent_with_n_ghosts(n_kin=3, n_weak=60)
        sn.enforce_dunbar(agent)
        # Kin should land in inner tier; some weak ties should land in
        # "weak" tier.
        tiers = [v["dunbar_tier"] for v in agent["relationships"].values()]
        self.assertIn("inner", tiers)
        self.assertIn("weak", tiers)


if __name__ == "__main__":
    unittest.main()
