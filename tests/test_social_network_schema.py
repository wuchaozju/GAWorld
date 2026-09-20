"""Schema migration + role-aware weight for the social_network module."""

from __future__ import annotations

import unittest

from gaworld.social import network as sn


class TestEnsureSchema(unittest.TestCase):
    def test_fills_defaults_on_empty(self):
        item: dict = {}
        sn.ensure_relationship_schema(item, role="mother")
        # New fields populated from role config.
        self.assertEqual(item["kind"], "agent")
        self.assertEqual(item["role"], "mother")
        self.assertAlmostEqual(item["decay_rate"], 0.001)
        self.assertAlmostEqual(item["obligation_base"], 0.80)
        self.assertEqual(item["channels"], ["call", "visit"])
        # Backwards-compat scalars also populated.
        for k in ("closeness", "trust", "obligation", "friction"):
            self.assertIn(k, item)

    def test_preserves_existing_values(self):
        item = {
            "closeness": 0.42,
            "trust": 0.31,
            "obligation": 0.77,
            "friction": 0.10,
            "role": "best_friend",
            "decay_rate": 0.99,  # caller override should win
        }
        sn.ensure_relationship_schema(item, role="mother")  # role param ignored: role already set
        self.assertEqual(item["role"], "best_friend")
        self.assertAlmostEqual(item["closeness"], 0.42)
        self.assertAlmostEqual(item["decay_rate"], 0.99)

    def test_migrate_relationships_walks_dict(self):
        agent = {
            "id": 1,
            "relationships": {
                "2": {"closeness": 0.6, "trust": 0.5, "obligation": 0.5, "friction": 0.3},
                "3": {"closeness": 0.4},
            },
        }
        sn.migrate_relationships(agent, current_day=7)
        for item in agent["relationships"].values():
            self.assertIn("kind", item)
            self.assertIn("role", item)
            self.assertIn("decay_rate", item)
            self.assertIn("last_contact_day", item)


class TestRoleAwareWeight(unittest.TestCase):
    def test_kin_outweighs_online_friend_at_same_scores(self):
        kin = {"closeness": 0.7, "trust": 0.7, "obligation": 0.7, "friction": 0.2, "role": "mother"}
        online = {"closeness": 0.7, "trust": 0.7, "obligation": 0.7, "friction": 0.2, "role": "online_friend"}
        self.assertGreater(sn.role_aware_weight(kin), sn.role_aware_weight(online))

    def test_friction_lowers_weight(self):
        a = {"closeness": 0.7, "trust": 0.7, "obligation": 0.5, "friction": 0.1, "role": "friend"}
        b = {"closeness": 0.7, "trust": 0.7, "obligation": 0.5, "friction": 0.9, "role": "friend"}
        self.assertGreater(sn.role_aware_weight(a), sn.role_aware_weight(b))


class TestBackwardsCompatibleWeight(unittest.TestCase):
    """``human_realism.relationship_weight`` should keep working on legacy records."""

    def test_legacy_record_uses_old_formula(self):
        from gaworld.cognition import realism as human_realism
        agent = {"relationships": {"5": {"closeness": 0.9, "trust": 0.9, "obligation": 0.5, "friction": 0.0}}}
        # No "role" field → falls through to legacy branch.
        w = human_realism.relationship_weight(agent, 5)
        self.assertGreater(w, 0.5)

    def test_new_record_delegates_to_role_aware(self):
        from gaworld.cognition import realism as human_realism
        agent = {"relationships": {"5": {
            "closeness": 0.7, "trust": 0.7, "obligation": 0.5, "friction": 0.0,
            "role": "mother", "kind": "ghost",
        }}}
        w = human_realism.relationship_weight(agent, 5)
        # Role-aware kin bias is 1.30; legacy formula at these inputs gives
        # 0.7*0.45 + 0.7*0.30 + 0.5*0.20 = 0.625. With bias = 0.8125.
        self.assertAlmostEqual(w, 0.625 * 1.30, places=5)


if __name__ == "__main__":
    unittest.main()
