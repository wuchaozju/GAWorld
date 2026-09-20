import os
import tempfile
import unittest

import pandas as pd

import generative_city_sim as sim
from gaworld.policy.intervention import (
    append_intervention_metrics,
    build_intervention_feed,
    initialize_agent_intervention_state,
    update_agent_intervention_metrics,
)


class TestInterventionPolicy(unittest.TestCase):
    def _config(self):
        return {
            "recommendation": {
                "max_items": 6,
                "source_weights": {
                    "relational": 1.0,
                    "personalized": 0.9,
                    "headline": 0.8,
                },
            },
            "exposure_control": {
                "enabled": True,
                "toxicity_threshold": 0.2,
                "misinformation_threshold": 0.2,
                "suppression_factor": 0.2,
            },
            "stance": {
                "alpha": 0.5,
                "positive_keywords": ["支持", "改善"],
                "negative_keywords": ["反对", "风险"],
            },
            "toxicity_keywords": ["攻击"],
            "misinformation_keywords": ["谣言"],
        }

    def test_feed_mixes_relational_personalized_and_headline(self):
        agent = {
            "id": 1,
            "name": "甲",
            "job": "社区工作者",
            "values": "支持公共服务改善",
            "state": {},
            "social_neighbors": [2],
            "_recent_social_partners": [2],
        }
        agents_by_id = {
            2: {
                "id": 2,
                "name": "乙",
                "last_activity": "讨论交通政策",
                "last_action": "表达支持",
                "state": {"stance_score": 0.8},
            }
        }
        feed = build_intervention_feed(
            agent,
            agents_by_id=agents_by_id,
            env_events=[{"description": "公共交通服务改善"}],
            policy_event={"description": "平台工人保护政策"},
            config=self._config(),
        )
        self.assertGreaterEqual(feed["source_counts"].get("relational", 0), 1)
        self.assertGreaterEqual(feed["source_counts"].get("personalized", 0), 1)
        self.assertGreaterEqual(feed["source_counts"].get("headline", 0), 1)

    def test_exposure_control_suppresses_risky_content(self):
        agent = {
            "id": 1,
            "name": "甲",
            "values": "支持公共讨论",
            "state": {},
            "social_neighbors": [],
        }
        feed = build_intervention_feed(
            agent,
            env_events=[
                {"description": "社区服务改善"},
                {"description": "未经证实的谣言引发攻击"},
            ],
            config=self._config(),
        )
        risky = [item for item in feed["items"] if "谣言" in item["text"]][0]
        self.assertLess(risky["score"], risky["base_weight"])

    def test_stance_ema_uses_alpha(self):
        agent = {"id": 1, "state": {"stance_score": 0.0}, "social_neighbors": []}
        initialize_agent_intervention_state(agent, self._config())
        metrics = update_agent_intervention_metrics(
            agent,
            feed={"items": [{"text": "支持改善", "stance_score": 1.0}]},
            action="查看",
            reflection="支持改善",
            config=self._config(),
        )
        self.assertAlmostEqual(0.5, metrics["stance_score"], places=6)

    def test_cross_viewpoint_reward_beats_toxic_same_viewpoint(self):
        cfg = self._config()
        receiver = {"id": 1, "state": {"stance_score": -1.0}, "social_neighbors": [2]}
        initialize_agent_intervention_state(receiver, cfg)
        agents_by_id = {2: {"id": 2, "state": {"stance_score": 1.0}}}
        cross = update_agent_intervention_metrics(
            receiver,
            feed={"items": [{"text": "支持改善", "sender_id": 2, "stance_score": 1.0}]},
            action="回复讨论",
            reflection="参与讨论",
            agents_by_id=agents_by_id,
            config=cfg,
        )
        same_toxic = update_agent_intervention_metrics(
            {"id": 3, "state": {"stance_score": 1.0}, "social_neighbors": [2]},
            feed={"items": [{"text": "攻击 支持改善", "sender_id": 2, "stance_score": 1.0}]},
            action="回复讨论",
            reflection="攻击对方",
            agents_by_id=agents_by_id,
            config=cfg,
        )
        self.assertGreater(cross["intervention_reward"], same_toxic["intervention_reward"])

    def test_append_intervention_metrics_writes_expected_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = append_intervention_metrics(
                tmpdir,
                {
                    "day": 1,
                    "time": "09:00",
                    "agent_id": 1,
                    "feed_items": 2,
                    "relational_items": 1,
                    "personalized_items": 1,
                    "headline_items": 0,
                    "stance_score": 0.25,
                    "toxicity_score": 0.0,
                    "misinformation_risk": 0.0,
                    "cross_viewpoint_exposure": 0.5,
                    "intervention_reward": 0.7,
                },
            )
            df = pd.read_csv(path)
            self.assertEqual(1, len(df))
            self.assertIn("intervention_reward", df.columns)


class TestCompareEventInterventionReport(unittest.TestCase):
    def test_report_highlights_intervention_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {
                    "metric": "stance_score",
                    "baseline_final": 0.1,
                    "event_final": 0.4,
                    "delta_final": 0.3,
                    "baseline_mean": 0.1,
                    "event_mean": 0.3,
                    "delta_mean": 0.2,
                },
                {
                    "metric": "stress",
                    "baseline_final": 0.4,
                    "event_final": 0.5,
                    "delta_final": 0.1,
                    "baseline_mean": 0.4,
                    "event_mean": 0.45,
                    "delta_mean": 0.05,
                },
            ]
            report_path, _ = sim._write_comparison_report(
                tmpdir,
                {"name": "测试事件", "day": 1, "time": "09:00", "description": "测试"},
                rows,
            )
            with open(report_path, "r", encoding="utf-8") as f:
                text = f.read()
            self.assertIn("PolicySim 干预指标", text)
            self.assertIn("stance_score", text)


if __name__ == "__main__":
    unittest.main()
