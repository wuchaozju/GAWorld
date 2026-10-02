"""Tests for 政策仿真与优化 (gaworld.research.policy_sim + gaworld.apps.policy_sim_api).

What we defend:

* residents' answers are clamped onto the fixed scales, and an unreadable
  answer is counted as invalid rather than as a neutral vote;
* aggregation is by code: rates, means, the composite score, the per-group
  breakdown and the widest gap between groups;
* every version is simulated on the same seeded sample of residents;
* the optimiser's revision is simulated again, and the recommendation is
  whichever version scores highest — a revision that scores worse loses;
* the HTTP routes behind ``/api/research/policy`` run a job, store the run,
  export Markdown and delete it, through ``research_api``.

No LLM is reached and no city bundle is read.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from gaworld.apps import policy_sim_api, research_api
from gaworld.research import policy_sim as ps

PEOPLE = [
    {"id": i, "name": f"居民{i}", "age": age, "gender": g, "hukou": h, "job": "职员"}
    for i, (age, g, h) in enumerate(
        [
            (25, "男", "本地"),
            (30, "女", "外地"),
            (45, "男", "本地"),
            (50, "女", "外地"),
            (70, "男", "本地"),
            (68, "女", "本地"),
            (12, "女", "本地"),
            (38, "男", "外地"),
        ],
        start=1,
    )
]


def persona(city: str, agent_id: int) -> dict:
    person = next(p for p in PEOPLE if p["id"] == agent_id)
    return {
        "agent_id": agent_id,
        "name": person["name"],
        "age": person["age"],
        "gender": person["gender"],
        "job": person["job"],
        "profile_md": "",
    }


def scripted_react(prompt: str) -> str:
    """Old people dislike the fine; everybody likes the revision."""
    if "修订" in prompt:
        return json.dumps(
            {
                "support": 2,
                "wellbeing": 3,
                "finance": 1,
                "compliance": 90,
                "behavior": "照做",
                "concern": "无",
                "suggestion": "保持",
            }
        )
    old = any(f"{age}岁" in prompt for age in (70, 68))
    if old:
        return json.dumps(
            {
                "support": -2,
                "wellbeing": -4,
                "finance": -3,
                "compliance": 30,
                "behavior": "不分",
                "concern": "罚款太重",
                "suggestion": "老人免罚",
            }
        )
    return json.dumps(
        {
            "support": 1,
            "wellbeing": 1,
            "finance": 0,
            "compliance": 80,
            "behavior": "分类",
            "concern": "麻烦",
            "suggestion": "多设桶",
        }
    )


def scripted_optimise(revised: str = "修订：老人免罚，多设分类桶"):
    def call(prompt: str) -> str:
        return json.dumps(
            {
                "assessment": "多数人支持，但老人受损。",
                "effects": ["中青年愿意分类"],
                "risks": ["老人负担重"],
                "comparison": "",
                "modifications": [
                    {"change": "老人免罚", "reason": "老年组生活 -4", "addresses": "老人"},
                    "多设桶",
                ],
                "revised_policy": revised,
                "expected": "老人支持度上升",
            }
        )

    return call


class ParsingTest(unittest.TestCase):
    def test_reaction_is_clamped(self) -> None:
        r = ps.parse_reaction('好的 {"support": 9, "wellbeing": -12, "finance": "2", "compliance": 150} 完')
        self.assertTrue(r["ok"])
        self.assertEqual((r["support"], r["wellbeing"], r["finance"], r["compliance"]), (2, -5, 2, 100))

    def test_unreadable_reaction_is_invalid_not_neutral(self) -> None:
        r = ps.parse_reaction("我不知道")
        self.assertFalse(r["ok"])
        m = ps.metrics(
            [r, {**ps.parse_reaction('{"support": 2, "wellbeing": 5, "finance": 5, "compliance": 100}')}]
        )
        self.assertEqual((m["n"], m["failed"]), (1, 1))
        self.assertEqual(m["score"], 100.0)

    def test_recommendation_accepts_string_modifications(self) -> None:
        rec = ps.parse_recommendation(scripted_optimise()(""))
        self.assertEqual([m["change"] for m in rec["modifications"]], ["老人免罚", "多设桶"])
        self.assertEqual(ps.parse_recommendation("没有 JSON")["modifications"], [])

    def test_score_bounds(self) -> None:
        self.assertEqual(ps.composite_score(-2, -5, -5, 0), 0.0)
        self.assertEqual(ps.composite_score(2, 5, 5, 100), 100.0)


class AggregationTest(unittest.TestCase):
    def test_breakdown_finds_the_widest_gap(self) -> None:
        people = {p["id"]: p for p in PEOPLE}
        reactions = [
            {"agent_id": 1, "ok": True, "support": 1, "wellbeing": 2},
            {"agent_id": 2, "ok": True, "support": 1, "wellbeing": 2},
            {"agent_id": 5, "ok": True, "support": -2, "wellbeing": -4},
            {"agent_id": 6, "ok": True, "support": -2, "wellbeing": -4},
        ]
        groups = ps.breakdown(reactions, people)
        self.assertEqual(groups["age_band"]["65+"]["mean_wellbeing"], -4)
        self.assertEqual(groups["widest_gap"]["low"], "65+")
        self.assertEqual(groups["widest_gap"]["gap"], 6.0)

    def test_sample_skips_children_and_is_seeded(self) -> None:
        a = ps.sample_residents(PEOPLE, 5, seed=7)
        self.assertEqual(a, ps.sample_residents(PEOPLE, 5, seed=7))
        self.assertNotIn(7, [p["id"] for p in a])
        self.assertEqual(len(ps.sample_residents(PEOPLE, 50, seed=1)), 7)


class RunTest(unittest.TestCase):
    def _run(self, **kw):
        defaults = {
            "policy": "混投罚款 300 元",
            "city": "",
            "sample_size": 7,
            "seed": 3,
            "react": scripted_react,
            "optimise": scripted_optimise(),
            "population": PEOPLE,
            "persona_fn": persona,
        }
        defaults.update(kw)
        return ps.run_policy_sim(**defaults)

    def test_revision_is_verified_and_wins(self) -> None:
        run = self._run(candidate="按户收费")
        self.assertEqual([p["key"] for p in run["policies"]], ["A", "B", "R"])
        ids = [[r["agent_id"] for r in run["reactions"][k]] for k in "ABR"]
        self.assertTrue(ids[0] == ids[1] == ids[2])
        self.assertEqual(run["best"], "R")
        self.assertGreater(run["metrics"]["R"]["score"], run["metrics"]["A"]["score"])
        self.assertIn("老人免罚", ps.export_markdown(run))

    def test_a_worse_revision_does_not_win(self) -> None:
        def react(prompt: str) -> str:
            score = -2 if "修订" in prompt else 1
            return json.dumps({"support": score, "wellbeing": score, "finance": 0, "compliance": 50})

        run = self._run(react=react)
        self.assertEqual(run["best"], "A")

    def test_without_verification_only_original_is_simulated(self) -> None:
        run = self._run(verify=False)
        self.assertEqual([p["key"] for p in run["policies"]], ["A"])
        self.assertTrue(run["recommendation"]["revised_policy"])

    def test_optimiser_sees_numbers_and_worries(self) -> None:
        seen = []
        self._run(optimise=lambda p: seen.append(p) or "{}")
        self.assertIn("综合分", seen[0])
        self.assertIn("罚款太重", seen[0])

    def test_empty_policy_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._run(policy="  ")


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(ps, "policy_root", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        policy_sim_api.reset()

        def llm(prompt: str, task: str, provider: str) -> str:
            return scripted_optimise()(prompt) if task == "optimise" else scripted_react(prompt)

        for target in (
            mock.patch.object(policy_sim_api, "_LLM_OVERRIDE", llm),
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.apps.games_api.load_persona", side_effect=persona),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _wait(self, job_id: str) -> dict:
        for _ in range(200):
            record, status = research_api.handle_get(f"/api/research/policy/jobs/{job_id}")
            self.assertEqual(status, 200)
            if record["status"] != "running":
                return record
            time.sleep(0.02)
        self.fail("job did not finish")

    def test_run_view_export_delete(self) -> None:
        body, status = research_api.handle_post("/api/research/policy/run", {"policy": ""})
        self.assertEqual(status, 400)

        body, status = research_api.handle_post(
            "/api/research/policy/run",
            {"policy": "混投罚款", "sample_size": 6, "seed": 1, "city_name": "测试城"},
        )
        self.assertEqual(status, 202)
        job = self._wait(body["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        run_id = job["result"]["run_id"]

        listing, _ = research_api.handle_get("/api/research/policy")
        self.assertEqual(listing["runs"][0]["id"], run_id)
        self.assertEqual(listing["runs"][0]["best"], "R")

        run, status = research_api.handle_get(f"/api/research/policy/{run_id}")
        self.assertEqual((status, run["city_name"], len(run["residents"])), (200, "测试城", 6))
        export, _ = research_api.handle_get(f"/api/research/policy/{run_id}/export")
        self.assertTrue(export["markdown"].startswith("# 政策仿真与优化"))

        deleted, _ = research_api.handle_post(f"/api/research/policy/{run_id}/delete", {})
        self.assertTrue(deleted["deleted"])
        self.assertEqual(research_api.handle_get(f"/api/research/policy/{run_id}")[1], 404)
        self.assertEqual(research_api.handle_get("/api/research/policy/../etc")[1], 404)


if __name__ == "__main__":
    unittest.main()
