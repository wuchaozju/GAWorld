import random
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


class TestNeedsInfluenceActionChoice(unittest.TestCase):
    def test_low_energy_prefers_rest(self):
        agent = {
            "id": 11,
            "state": {
                "emotion": 0.5,
                "stress": 0.5,
                "econ_security": 0.5,
                "energy": 0.1,
                "hunger": 0.2,
                "social_need": 0.4,
                "fatigue_debt": 0.3,
                "self_control": 0.6,
                "time_pressure": 0.2,
            },
            "habits": {},
            "last_activity": "",
            "last_action": "",
        }
        action_space = {"个人时间": ["回家休息", "继续工作"]}
        behavior_cfg = {
            "behavior": {
                "inertia_weight": 0.25,
                "decision_noise": 0.0,
                "avoidance_bonus_scale": 1.1,
                "need_weights": {"energy": 0.45, "hunger": 0.30, "social_need": 0.25},
                "commitment_weights": {"high": 1.2, "medium": 0.6, "low": 0.2},
            }
        }
        with patch.object(sim, "STATEFUL", False), patch.object(
            sim, "HUMAN_REALISM_CONFIG", behavior_cfg
        ), patch.object(
            _action, "retrieve_relevant_memories", return_value=[]
        ):
            random.seed(7)
            rest_count = 0
            for _ in range(200):
                choice = sim.choose_action(
                    agent,
                    "个人时间",
                    action_space,
                    context="个人时间",
                    location_bias={},
                    location="Central Block",
                    time_str="20:00",
                )
                if "休息" in choice:
                    rest_count += 1
            self.assertGreater(rest_count, 105)

    def test_low_self_control_and_fatigue_increase_avoidance_but_high_commitment_still_holds(self):
        agent = {
            "id": 12,
            "state": {
                "emotion": 0.35,
                "stress": 0.75,
                "econ_security": 0.5,
                "energy": 0.25,
                "hunger": 0.35,
                "social_need": 0.4,
                "fatigue_debt": 0.9,
                "self_control": 0.15,
                "time_pressure": 0.5,
            },
            "habits": {},
            "last_activity": "",
            "last_action": "",
        }
        action_space = {"上午工作": ["推进关键任务", "拖一会儿再开始，先刷手机分心"]}
        behavior_cfg = {
            "behavior": {
                "inertia_weight": 0.25,
                "decision_noise": 0.0,
                "avoidance_bonus_scale": 1.1,
                "need_weights": {"energy": 0.45, "hunger": 0.30, "social_need": 0.25},
                "commitment_weights": {"high": 1.2, "medium": 0.6, "low": 0.2},
            }
        }
        with patch.object(sim, "STATEFUL", False), patch.object(
            sim, "HUMAN_REALISM_CONFIG", behavior_cfg
        ), patch.object(_action, "retrieve_relevant_memories", return_value=[]):
            random.seed(17)
            avoidant = 0
            productive = 0
            for _ in range(240):
                choice = sim.choose_action(
                    agent,
                    "上午工作",
                    action_space,
                    context="上午工作",
                    location_bias={},
                    location="Admin Office",
                    time_str="10:00",
                )
                if "刷手机" in choice:
                    avoidant += 1
                if "推进" in choice:
                    productive += 1
            self.assertGreater(avoidant, 70)
            self.assertGreater(productive, 40)

    def test_sleep_reduces_fatigue_and_recovers_self_control(self):
        agent = {
            "state": {
                "energy": 0.25,
                "hunger": 0.4,
                "social_need": 0.5,
                "stress": 0.6,
                "fatigue_debt": 0.85,
                "self_control": 0.25,
                "time_pressure": 0.5,
            }
        }
        sim.update_needs(
            agent,
            "23:30",
            "睡觉",
            cfg=sim.HUMAN_REALISM_CONFIG,
            changed=False,
            travel={"status": "stationary"},
        )
        self.assertLess(agent["state"]["fatigue_debt"], 0.75)
        self.assertGreater(agent["state"]["self_control"], 0.28)


if __name__ == "__main__":
    unittest.main()
