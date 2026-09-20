import unittest
from unittest.mock import patch

import generative_city_sim as sim
from gaworld.sim import _action

# ``patch.object(sim, ...)`` only intercepts a dependency when the function
# under test also resolves that name from ``generative_city_sim``'s globals.
# The refactor moved ``choose_action`` into ``gaworld.sim._action``, which looks
# its dependencies up in its own module, so patching the re-export on ``sim``
# cannot reach it. Retargeted rather than deleted: on today's code path
# ``choose_action`` takes ``recall_context`` as an argument and never calls
# ``retrieve_relevant_memories`` at all, so the stub is inert either way -- but
# on ``_action`` it is at least in the right place if the path ever does.


class TestRelationshipWeightedSocialContext(unittest.TestCase):
    def test_high_closeness_sampled_more(self):
        agent = {
            "social_neighbors": [1, 2, 3, 4],
            "relationships": {
                "1": {"closeness": 0.95},
                "2": {"closeness": 0.05},
                "3": {"closeness": 0.05},
                "4": {"closeness": 0.05},
            },
        }
        agents_by_id = {
            1: {"name": "甲"},
            2: {"name": "乙"},
            3: {"name": "丙"},
            4: {"name": "丁"},
        }
        with patch.object(sim, "HUMAN_REALISM_ENABLED", True):
            counts = {1: 0, 2: 0, 3: 0, 4: 0}
            for _ in range(300):
                sim.get_social_context(agent, agents_by_id)
                for n in agent.get("_recent_social_partners", []):
                    counts[n] += 1
        self.assertGreater(counts[1], counts[2])
        self.assertGreater(counts[1], counts[3])
        self.assertGreater(counts[1], counts[4])

    def test_obligation_boosts_contact_and_friction_suppresses_it(self):
        action_space = {"个人时间": ["继续独处", "联系朋友确认见面"]}
        agents_by_id = {1: {"name": "甲"}}
        behavior_cfg = {
            "behavior": {
                "inertia_weight": 0.25,
                "decision_noise": 0.0,
                "avoidance_bonus_scale": 1.1,
                "need_weights": {"energy": 0.45, "hunger": 0.30, "social_need": 0.25},
                "commitment_weights": {"high": 1.2, "medium": 0.6, "low": 0.2},
            }
        }

        high_obligation_agent = {
            "id": 31,
            "social_neighbors": [1],
            "relationships": {"1": {"closeness": 0.7, "trust": 0.7, "obligation": 0.95, "friction": 0.15}},
            "_recent_social_partners": [1],
            "state": {
                "emotion": 0.5,
                "stress": 0.45,
                "econ_security": 0.5,
                "energy": 0.6,
                "hunger": 0.3,
                "social_need": 0.4,
                "fatigue_debt": 0.2,
                "self_control": 0.65,
                "time_pressure": 0.25,
            },
            "habits": {},
            "last_activity": "",
            "last_action": "",
        }
        high_friction_agent = {
            "id": 32,
            "social_neighbors": [1],
            "relationships": {"1": {"closeness": 0.4, "trust": 0.4, "obligation": 0.6, "friction": 0.9}},
            "_recent_social_partners": [1],
            "state": {
                "emotion": 0.5,
                "stress": 0.45,
                "econ_security": 0.5,
                "energy": 0.6,
                "hunger": 0.3,
                "social_need": 0.4,
                "fatigue_debt": 0.2,
                "self_control": 0.65,
                "time_pressure": 0.25,
            },
            "habits": {},
            "last_activity": "",
            "last_action": "",
        }

        with patch.object(sim, "STATEFUL", False), patch.object(
            sim, "HUMAN_REALISM_ENABLED", True
        ), patch.object(sim, "HUMAN_REALISM_CONFIG", behavior_cfg), patch.object(
            _action, "retrieve_relevant_memories", return_value=[]
        ):
            high_obligation_count = 0
            high_friction_count = 0
            for seed in range(180):
                sim.get_social_context(high_obligation_agent, agents_by_id)
                sim.get_social_context(high_friction_agent, agents_by_id)
                with patch.object(sim.random, "uniform", return_value=1.0):
                    sim.random.seed(seed)
                    if "联系" in sim.choose_action(
                        high_obligation_agent,
                        "个人时间",
                        action_space,
                        context="个人时间",
                        location_bias={},
                        location="Central Block",
                        time_str="20:00",
                    ):
                        high_obligation_count += 1
                    sim.random.seed(seed)
                    if "联系" in sim.choose_action(
                        high_friction_agent,
                        "个人时间",
                        action_space,
                        context="个人时间",
                        location_bias={},
                        location="Central Block",
                        time_str="20:00",
                    ):
                        high_friction_count += 1
        self.assertGreater(high_obligation_count, high_friction_count)


if __name__ == "__main__":
    unittest.main()
