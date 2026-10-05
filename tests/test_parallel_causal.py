"""Counterfactual inference over parallel worlds (``gaworld.parallel.causal``).

Every fixture is built so the right answer is known by construction — a
resident's treated history is their control history plus a chosen offset —
because the failure this module can produce is not a crash but a confident
interval around the wrong number. What is pinned:

* the ATE is the mean of the paired individual effects over the post-event
  window, and its interval/p-value call a real effect and do not call a null;
* a placebo world raises the bar an effect must clear;
* a pre-event gap is caught, and DiD removes it;
* BH q-values, the exact sign-flip test and the event step are checked
  against values worked out by hand;
* heterogeneity finds the subgroup an effect actually landed on;
* seed replicates pool on seed-level effects, and disagreeing seeds are
  called mixed rather than averaged into a clean-looking mean.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from gaworld.apps import parallel_worlds_api as api
from gaworld.apps import world_paths
from gaworld.parallel import analysis, causal, runner
from gaworld.parallel import spec as spec_mod

AGENTS = 20
STEPS = 10
SIM_DAYS = 2  # 5 steps per day; an event at Day 2 00:00 lands on step 5


def _women(agent: int) -> bool:
    return agent % 2 == 0


def _base_value(agent: int, step: int) -> float:
    # Residents differ from each other and drift a little, so nothing is flat.
    return 0.4 + 0.01 * (agent % 7) + 0.002 * step


def _write(path: str, offset) -> None:
    """A state history where ``offset(agent, step)`` is added to the base."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["agent_id", "step", "metric", "value"])
        for agent in range(1, AGENTS + 1):
            for step in range(STEPS):
                base = _base_value(agent, step)
                writer.writerow([agent, step, "emotion", base + offset(agent, step)])
                writer.writerow([agent, step, "stress", 0.5 + 0.005 * (agent % 5)])


def _panel(tmp: str, name: str, offset) -> dict:
    path = os.path.join(tmp, f"{name}.csv")
    _write(path, offset)
    return analysis.read_state_series(path, panel=True)["panel"]


EVENT = [{"day": 2, "time": "00:00", "name": "e"}]


def _spec(*worlds) -> dict:
    return {"sim_days": SIM_DAYS, "baseline_id": "base", "worlds": [{"id": "base", "events": []}, *worlds]}


def _rows(result: dict, world: str) -> dict:
    return {row["metric"]: row for row in result["estimates"] if row["world_id"] == world}


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = _panel(self.tmp.name, "base", lambda a, s: 0.0)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, spec: dict, panels: dict) -> dict:
        return causal.estimate_effects(
            spec,
            {"base": self.base, **panels},
            baseline_id="base",
            steps=STEPS,
            steps_per_day=STEPS / SIM_DAYS,
        )

    def test_a_real_effect_is_estimated_and_called(self):
        # Women lose 0.10 after the event, men 0.02: ATE = -0.06 exactly.
        shock = _panel(
            self.tmp.name, "shock", lambda a, s: (-0.10 if _women(a) else -0.02) if s >= 5 else 0.0
        )
        result = self._run(_spec({"id": "shock", "events": EVENT}), {"shock": shock})
        row = _rows(result, "shock")["emotion"]
        self.assertEqual(row["n"], AGENTS)
        self.assertEqual(row["event_step"], 5)
        self.assertAlmostEqual(row["ate"], -0.06, places=9)
        self.assertLess(row["ci_low"], row["ate"])
        self.assertLess(row["ci_high"], 0)  # excludes zero
        self.assertLess(row["p_value"], 0.01)
        self.assertLess(row["d_z"], 0)
        self.assertAlmostEqual(row["pre_gap"], 0.0, places=9)
        self.assertTrue(row["balanced"])
        self.assertAlmostEqual(row["did"], -0.06, places=9)
        self.assertEqual(row["share_down"], 1.0)
        self.assertEqual(row["verdict"], "robust")
        # The metric nobody touched is a null, not a false positive.
        stress = _rows(result, "shock")["stress"]
        self.assertEqual(stress["ate"], 0.0)
        self.assertEqual(stress["p_value"], 1.0)
        self.assertEqual(stress["verdict"], "null")

    def test_estimates_are_reproducible(self):
        shock = _panel(self.tmp.name, "shock", lambda a, s: -0.05 * (a % 3) if s >= 5 else 0.0)
        spec = _spec({"id": "shock", "events": EVENT})
        first = _rows(self._run(spec, {"shock": shock}), "shock")["emotion"]
        second = _rows(self._run(spec, {"shock": shock}), "shock")["emotion"]
        self.assertEqual(
            (first["ci_low"], first["ci_high"], first["p_value"]),
            (second["ci_low"], second["ci_high"], second["p_value"]),
        )

    def test_a_placebo_world_sets_the_noise_floor(self):
        placebo = _panel(self.tmp.name, "placebo", lambda a, s: 0.05 + 0.001 * (a % 3) if s >= 5 else 0.0)
        weak = _panel(self.tmp.name, "weak", lambda a, s: -0.04 - 0.001 * (a % 3) if s >= 5 else 0.0)
        result = self._run(
            _spec({"id": "placebo", "role": "placebo", "events": EVENT}, {"id": "weak", "events": EVENT}),
            {"placebo": placebo, "weak": weak},
        )
        self.assertEqual(result["placebo_ids"], ["placebo"])
        self.assertGreaterEqual(result["noise"]["emotion"], 0.05)
        row = _rows(result, "weak")["emotion"]
        self.assertEqual(row["verdict"], "below_noise")
        # A placebo that moved is itself something the reader must be told.
        self.assertIn("placebo_moved", {warning["kind"] for warning in result["warnings"]})

    def test_comparing_two_treatments_keeps_the_noise_floor_on_the_reference(self):
        """Read against "mild", the placebo row is "placebo − mild" — a real
        contrast. Using it as the floor would swallow every effect."""
        mild = _panel(self.tmp.name, "mild", lambda a, s: -0.05 if s >= 5 else 0.0)
        harsh = _panel(self.tmp.name, "harsh", lambda a, s: -0.10 - 0.001 * (a % 3) if s >= 5 else 0.0)
        placebo = _panel(self.tmp.name, "placebo", lambda a, s: 0.002 * (a % 3) if s >= 5 else 0.0)
        spec = _spec(
            {"id": "mild", "events": EVENT},
            {"id": "harsh", "events": EVENT},
            {"id": "placebo", "role": "placebo", "events": EVENT},
        )
        result = causal.estimate_effects(
            spec,
            {"base": self.base, "mild": mild, "harsh": harsh, "placebo": placebo},
            baseline_id="mild",
            steps=STEPS,
            steps_per_day=STEPS / SIM_DAYS,
            noise_reference_id="base",
        )
        self.assertEqual(result["noise_reference_id"], "base")
        self.assertLess(result["noise"]["emotion"], 0.01)
        self.assertNotIn("placebo_moved", {warning["kind"] for warning in result["warnings"]})
        harsh_row = _rows(result, "harsh")["emotion"]
        self.assertAlmostEqual(harsh_row["ate"], -0.05105, places=9)  # mean of a % 3 over 1..20 is 1.05
        self.assertEqual(harsh_row["verdict"], "robust")
        # The placebo's own row is an ordinary contrast now, judged against the floor.
        self.assertIsNotNone(_rows(result, "placebo")["emotion"]["noise"])

    def test_a_pre_event_gap_is_flagged_and_did_removes_it(self):
        drifted = _panel(self.tmp.name, "drifted", lambda a, s: 0.05 + (0.10 if s >= 5 else 0.0))
        row = _rows(self._run(_spec({"id": "drifted", "events": EVENT}), {"drifted": drifted}), "drifted")[
            "emotion"
        ]
        self.assertAlmostEqual(row["ate"], 0.15, places=9)
        self.assertAlmostEqual(row["pre_gap"], 0.05, places=9)
        self.assertAlmostEqual(row["did"], 0.10, places=9)
        self.assertFalse(row["balanced"])
        self.assertEqual(row["verdict"], "unbalanced")

    def test_a_config_world_without_events_uses_the_whole_horizon(self):
        policy = _panel(self.tmp.name, "policy", lambda a, s: 0.03)
        row = _rows(self._run(_spec({"id": "policy", "events": []}), {"policy": policy}), "policy")["emotion"]
        self.assertIsNone(row["event_step"])
        self.assertIsNone(row["pre_gap"])
        self.assertIsNone(row["balanced"])
        self.assertAlmostEqual(row["ate"], 0.03, places=9)

    def test_dynamics_find_onset_peak_and_decay(self):
        def pulse(agent: int, step: int) -> float:
            return {5: 0.10, 6: 0.08, 7: 0.06, 8: 0.04, 9: 0.03}.get(step, 0.0)

        result = self._run(
            _spec({"id": "pulse", "events": EVENT}), {"pulse": _panel(self.tmp.name, "p", pulse)}
        )
        emotion = result["dynamics"]["pulse"]["metrics"]["emotion"]
        self.assertEqual(emotion["onset_step"], 5)
        self.assertEqual(emotion["peak_step"], 5)
        self.assertAlmostEqual(emotion["peak"], 0.10, places=6)
        self.assertEqual(emotion["half_life"], 3)  # 0.04 < 0.05 at step 8
        self.assertAlmostEqual(emotion["persistence"], 0.3, places=6)
        self.assertEqual(result["dynamics"]["pulse"]["order"], ["emotion"])
        band = result["effect_curves"]["pulse"]["emotion"]
        self.assertEqual(len(band["mean"]), STEPS)
        self.assertLessEqual(band["lo"][5], band["mean"][5])

    def test_dose_response_slope(self):
        mild = _panel(self.tmp.name, "mild", lambda a, s: -0.05 if s >= 5 else 0.0)
        harsh = _panel(self.tmp.name, "harsh", lambda a, s: -0.10 if s >= 5 else 0.0)
        result = self._run(
            _spec({"id": "mild", "dose": 1, "events": EVENT}, {"id": "harsh", "dose": 2, "events": EVENT}),
            {"mild": mild, "harsh": harsh},
        )
        emotion = next(row for row in result["dose_response"] if row["metric"] == "emotion")
        self.assertAlmostEqual(emotion["slope"], -0.05, places=9)
        self.assertTrue(emotion["monotonic"])
        self.assertAlmostEqual(emotion["r2"], 1.0, places=9)

    def test_no_dose_response_without_two_dosed_worlds(self):
        mild = _panel(self.tmp.name, "mild", lambda a, s: -0.05 if s >= 5 else 0.0)
        result = self._run(_spec({"id": "mild", "dose": 1, "events": EVENT}), {"mild": mild})
        self.assertEqual(result["dose_response"], [])


class NumericsTests(unittest.TestCase):
    def test_bh_qvalues_by_hand(self):
        q = causal.bh_qvalues([0.01, 0.04, 0.03, 0.5])
        for got, want in zip(q, [0.04, 0.16 / 3, 0.16 / 3, 0.5], strict=True):
            self.assertAlmostEqual(got, want, places=9)

    def test_exact_sign_flip(self):
        # Three positive effects: only all-plus and all-minus reach |mean|.
        self.assertAlmostEqual(causal.sign_flip_p(np.array([1.0, 1.0, 1.0]), np.random.default_rng(0)), 0.25)
        self.assertEqual(causal.sign_flip_p(np.zeros(5), np.random.default_rng(0)), 1.0)

    def test_event_step(self):
        world = {"events": [{"day": 2, "time": "07:00", "name": "x"}]}
        self.assertEqual(causal.event_step(world, 5.0, 10), 6)  # 5 + 7/24·5 = 6.46
        self.assertIsNone(causal.event_step({"events": []}, 5.0, 10))
        self.assertIsNone(causal.event_step(world, None, 10))


class HeterogeneityTests(unittest.TestCase):
    def test_the_subgroup_the_effect_landed_on_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _panel(tmp, "base", lambda a, s: 0.0)
            shock = _panel(tmp, "shock", lambda a, s: (-0.10 if _women(a) else -0.02) if s >= 5 else 0.0)
        attributes = causal.resident_attributes(
            [
                {
                    "id": str(agent),
                    "name": f"居民{agent}",
                    "gender": "女" if _women(agent) else "男",
                    "age": str(20 + agent * 3),
                    "residence": f"街道{agent}",
                    "emotion": "0.5",
                }
                for agent in range(1, AGENTS + 1)
            ]
        )
        self.assertEqual(set(attributes["1"]), {"gender", "age"})  # name/residence/state skipped
        self.assertEqual(attributes["1"]["age"], "<30")
        self.assertEqual(attributes["20"]["age"], "60+")

        result = causal.heterogeneity(shock, base, "emotion", 5, attributes)
        self.assertAlmostEqual(result["ate"], -0.06, places=9)
        by_id = {item["id"]: item for item in result["attributes"]}
        gender = {group["group"]: group for group in by_id["gender"]["groups"]}
        self.assertAlmostEqual(gender["女"]["cate"], -0.10, places=9)
        self.assertAlmostEqual(gender["男"]["cate"], -0.02, places=9)
        self.assertAlmostEqual(by_id["gender"]["spread"], 0.08, places=9)
        self.assertLess(by_id["gender"]["p_value"], 0.01)
        self.assertEqual(result["attributes"][0]["id"], "gender")  # most significant first
        self.assertIn("initial", by_id)


class ReplicationTests(unittest.TestCase):
    @staticmethod
    def _run(seed: int, ate: float) -> dict:
        return {
            "seed": seed,
            "root": f"r{seed}",
            "causal": {
                "estimates": [
                    {
                        "world_id": "t",
                        "metric": "emotion",
                        "ate": ate,
                        "ci_low": ate - 0.01,
                        "ci_high": ate + 0.01,
                        "verdict": "robust",
                    },
                ]
            },
        }

    def test_seeds_that_agree_replicate(self):
        pooled = causal.pool_replicates([self._run(1, -0.05), self._run(2, -0.06), self._run(3, -0.055)])
        row = pooled["rows"][0]
        self.assertEqual(row["seeds"], 3)
        self.assertAlmostEqual(row["mean"], -0.055, places=9)
        self.assertEqual(row["agree"], 3)
        self.assertLess(row["ci_high"], 0)
        self.assertEqual(row["verdict"], "replicated")

    def test_seeds_that_disagree_are_mixed_not_averaged_away(self):
        pooled = causal.pool_replicates([self._run(1, -0.05), self._run(2, 0.04), self._run(3, -0.06)])
        self.assertEqual(pooled["rows"][0]["verdict"], "mixed")
        self.assertEqual(pooled["summary"]["mixed"], 1)


class SpecTests(unittest.TestCase):
    def test_roles_and_doses_are_validated(self):
        experiment = spec_mod.normalize_experiment(
            {
                "worlds": [
                    {"label": "a"},
                    {"label": "b", "role": "placebo", "dose": "1.5", "events": EVENT},
                ]
            }
        )
        self.assertEqual(experiment.worlds[1].role, "placebo")
        self.assertEqual(experiment.worlds[1].dose, 1.5)
        self.assertEqual(experiment.to_dict()["worlds"][1]["role"], "placebo")
        with self.assertRaises(ValueError):
            spec_mod.normalize_experiment({"worlds": [{"label": "a"}, {"label": "b", "role": "boss"}]})
        with self.assertRaises(ValueError):
            spec_mod.normalize_experiment({"worlds": [{"label": "a"}, {"label": "b", "dose": "nan"}]})

    def test_a_declared_baseline_is_the_baseline(self):
        experiment = spec_mod.normalize_experiment(
            {
                "worlds": [
                    {"id": "t", "label": "t", "events": EVENT},
                    {"id": "c", "label": "c", "role": "baseline", "events": EVENT},
                ]
            }
        )
        self.assertEqual(experiment.baseline_id, "c")


# ---------------------------------------------------------------------------
# Through the dashboard delegate
# ---------------------------------------------------------------------------


class _TempRepo:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._saved = (world_paths.REPO_ROOT, world_paths.DASHBOARD_CONFIG_PATH)

    def __enter__(self):
        world_paths.REPO_ROOT = self.root
        world_paths.DASHBOARD_CONFIG_PATH = os.path.join(self.root, "dashboard_config.json")
        api._reset_for_tests()
        return self

    def __exit__(self, *exc):
        world_paths.REPO_ROOT, world_paths.DASHBOARD_CONFIG_PATH = self._saved
        api._reset_for_tests()
        self.tmp.cleanup()
        return False


PAYLOAD = {
    "name": "裁员",
    "sim_days": SIM_DAYS,
    "worlds": [
        {"id": "base", "label": "基准"},
        {"id": "shock", "label": "裁员", "role": "treatment", "events": EVENT},
        {"id": "placebo", "label": "安慰剂", "role": "placebo", "events": EVENT},
    ],
}

OFFSETS = {
    "base": lambda a, s: 0.0,
    "shock": lambda a, s: (-0.10 if _women(a) else -0.02) if s >= 5 else 0.0,
    "placebo": lambda a, s: 0.001 * (a % 3) if s >= 5 else 0.0,
}


def _experiment(root: str, seed: int, *, group: str | None = None, experiment_id: str | None = None) -> dict:
    experiment = spec_mod.normalize_experiment({**PAYLOAD, "seed": seed})
    manifest = runner.prepare_experiment(experiment, root, experiment_id=experiment_id, group=group)
    for world_id, entry in manifest["worlds"].items():
        _write(os.path.join(root, entry["state_csv"]), OFFSETS[world_id])
    return manifest


class ApiTests(unittest.TestCase):
    def test_the_report_carries_the_estimates(self):
        with _TempRepo() as repo:
            manifest = _experiment(repo.root, 42)
            report = api.experiment_report(manifest["root"])
            self.assertIsNone(report["replication"])
            causal_part = report["causal"]
            self.assertEqual(causal_part["baseline_id"], "base")
            self.assertEqual(causal_part["placebo_ids"], ["placebo"])
            shock = _rows(causal_part, "shock")["emotion"]
            self.assertEqual(shock["verdict"], "robust")
            self.assertEqual(shock["role"], "treatment")
            json.dumps(api._wire_safe(report))  # the browser can parse it

    def test_another_world_can_be_the_comparison(self):
        with _TempRepo() as repo:
            manifest = _experiment(repo.root, 42)
            report = api.experiment_report(manifest["root"], baseline="placebo")
            self.assertEqual(report["baseline_id"], "placebo")
            self.assertEqual(report["causal"]["baseline_id"], "placebo")
            self.assertEqual(report["causal"]["noise_reference_id"], "base")
            payload, status = api.handle_get(
                "/api/parallel-worlds/experiment", {"root": [manifest["root"]], "baseline": ["nope"]}
            )
            self.assertEqual(status, 404)
            self.assertIn("对照世界", payload["error"])

    def test_seed_replicates_are_pooled(self):
        with _TempRepo() as repo:
            first = _experiment(repo.root, 1, group="g1", experiment_id="g1_s1")
            _experiment(repo.root, 2, group="g1", experiment_id="g1_s2")
            _experiment(repo.root, 3, experiment_id="loner")  # not in the group
            report = api.experiment_report(first["root"])
            pooled = report["replication"]
            self.assertEqual(pooled["seeds"], [1, 2])
            row = next(r for r in pooled["rows"] if r["world_id"] == "shock" and r["metric"] == "emotion")
            self.assertEqual(row["seeds"], 2)
            self.assertAlmostEqual(row["mean"], -0.06, places=9)
            items = {item["id"]: item for item in api.list_experiments()}
            self.assertEqual(items["g1_s1"]["group"], "g1")
            self.assertIsNone(items["loner"]["group"])

    def test_seeds_from_another_code_epoch_are_not_pooled(self):
        def stamp(manifest, epoch):
            manifest["comparability_epoch"] = epoch
            runner.write_manifest(repo.root, manifest)

        with _TempRepo() as repo:
            first = _experiment(repo.root, 1, group="g1", experiment_id="g1_s1")
            stamp(first, 5)
            stamp(_experiment(repo.root, 2, group="g1", experiment_id="g1_s2"), 5)
            stamp(_experiment(repo.root, 3, group="g1", experiment_id="g1_s3"), 4)
            pooled = api.experiment_report(first["root"])["replication"]
            self.assertEqual(pooled["seeds"], [1, 2])
            self.assertEqual([item["seed"] for item in pooled["excluded"]], [3])

            # Nothing left to pool: say why instead of looking like one seed.
            lone = _experiment(repo.root, 4, group="g2", experiment_id="g2_s4")
            stamp(lone, 5)
            stamp(_experiment(repo.root, 5, group="g2", experiment_id="g2_s5"), None)
            refused = api.experiment_report(lone["root"])["replication"]
            self.assertEqual((refused["rows"], [i["seed"] for i in refused["excluded"]]), ([], [5]))

    def test_a_finished_experiment_records_its_code_epoch(self):
        from gaworld.core.comparability import CURRENT_EPOCH

        with _TempRepo() as repo:
            manifest = _experiment(repo.root, 1)
            report = runner.ExperimentRunner(manifest, repo.root).finish()
            self.assertEqual(report["comparability_epoch"], CURRENT_EPOCH)
            saved = runner.load_manifest(repo.root, manifest["root"])
            self.assertEqual(saved["comparability_epoch"], CURRENT_EPOCH)

    def test_study_runs_are_grouped_by_their_id(self):
        self.assertEqual(api.group_of({"id": "study_S1-ab_s42"}), "study_S1-ab")
        self.assertIsNone(api.group_of({"id": "20260101_000000_x_s42"}))

    def test_heterogeneity_endpoint_uses_the_seed_csv(self):
        with _TempRepo() as repo:
            manifest = _experiment(repo.root, 42)
            seed_csv = os.path.join(repo.root, "seed.csv")
            with open(seed_csv, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["id", "name", "gender", "age"])
                for agent in range(1, AGENTS + 1):
                    writer.writerow([agent, f"居民{agent}", "女" if _women(agent) else "男", 20 + agent])
            with mock.patch.object(world_paths, "state_csv_path", return_value=seed_csv):
                payload, status = api.handle_get(
                    "/api/parallel-worlds/heterogeneity",
                    {
                        "root": [manifest["root"]],
                        "world": ["shock"],
                        "metric": ["emotion"],
                    },
                )
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["event_step"], 5)
            self.assertEqual(payload["attributes"][0]["id"], "gender")
            _, status = api.handle_get(
                "/api/parallel-worlds/heterogeneity",
                {
                    "root": [manifest["root"]],
                    "world": ["base"],
                    "metric": ["emotion"],
                },
            )
            self.assertEqual(status, 404)
            self.assertEqual(api.handle_get("/api/parallel-worlds/heterogeneity", {})[1], 400)

    def test_replicate_seeds_are_validated(self):
        self.assertEqual(api.replicate_seeds({}, 7), [7])
        self.assertEqual(api.replicate_seeds({"seeds": [3, "4", 3]}, 7), [3, 4])
        with self.assertRaises(ValueError):
            api.replicate_seeds({"seeds": list(range(api.MAX_SEEDS + 1))}, 7)
        with self.assertRaises(ValueError):
            api.replicate_seeds({"seeds": ["x"]}, 7)

    def test_a_multi_seed_run_forks_one_grouped_experiment_per_seed(self):
        started: list[dict] = []

        class FakeRunner:
            def __init__(self, manifest, repo_root, **_kwargs):
                self.manifest = manifest
                started.append(manifest)

            def run(self, on_progress=None):
                if on_progress:
                    on_progress(1.0, "done")
                return {"worlds": []}

            def snapshot(self):
                return {"worlds": [], "progress": 1.0, "running": False, "paused": False, "sim_days": 1}

            def stop(self):
                pass

        with _TempRepo(), mock.patch.object(runner, "ExperimentRunner", FakeRunner):
            result = api.start({**PAYLOAD, "seeds": [11, 12, 13]})
            deadline = 50
            while deadline and (api.job_status(result["job_id"]) or {}).get("status") == "running":
                import time

                time.sleep(0.05)
                deadline -= 1
            job = api.job_status(result["job_id"])
        self.assertEqual(job["status"], "done")
        self.assertEqual([m["spec"]["seed"] for m in started], [11, 12, 13])
        groups = {m.get("group") for m in started}
        self.assertEqual(len(groups), 1)
        self.assertTrue(next(iter(groups)))
        self.assertEqual(len(job["experiments"]), 3)
        self.assertTrue(all(m["id"].endswith(f"_s{m['spec']['seed']}") for m in started))


if __name__ == "__main__":
    unittest.main()


ANSWER = {
    "summary": "裁员显著压低了情绪。",
    "findings": [
        {"world": "shock", "metric": "emotion", "claim": "裁员压低情绪", "evidence": "ATE -0.06"},
        {"world": "裁员", "metric": "压力", "claim": "压力也上升了", "evidence": "?"},
        {"world": "nope", "metric": "emotion", "claim": "凭空的世界", "evidence": ""},
    ],
    "limitations": ["只有一个种子"],
    "next_experiments": [{"title": "加种子", "rationale": "看能否复现", "design": "重复种子数设为 3"}],
}


class InterpretTests(unittest.TestCase):
    """The model reads the table; it does not get to add to it."""

    def test_findings_are_tied_to_rows_and_cached(self):
        prompts: list[str] = []

        def llm(prompt: str) -> str:
            prompts.append(prompt)
            return "```json\n" + json.dumps(ANSWER, ensure_ascii=False) + "\n```"

        with _TempRepo() as repo:
            manifest = _experiment(repo.root, 42)
            result = api.interpret_experiment({"root": manifest["root"]}, llm_fn=llm)
            self.assertIn("| shock | emotion |", prompts[0])
            self.assertIn("robust", prompts[0])
            findings = result["findings"]
            self.assertTrue(findings[0]["grounded"])
            self.assertEqual(findings[0]["verdict"], "robust")
            # Labels are mapped back to ids, and a null effect is shown as one.
            self.assertEqual((findings[1]["world"], findings[1]["metric"]), ("shock", "stress"))
            self.assertTrue(findings[1]["grounded"])
            self.assertEqual(findings[1]["verdict"], "null")
            self.assertFalse(findings[2]["grounded"])
            self.assertEqual(result["baseline_id"], "base")

            payload, status = api.handle_get(
                "/api/parallel-worlds/interpretation", {"root": [manifest["root"]]}
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["interpretation"]["summary"], "裁员显著压低了情绪。")
            # Another comparison world is another table, so nothing is cached for it yet.
            payload, _ = api.handle_get(
                "/api/parallel-worlds/interpretation", {"root": [manifest["root"]], "baseline": ["placebo"]}
            )
            self.assertIsNone(payload["interpretation"])

    def test_an_unusable_answer_is_a_400_not_a_crash(self):
        with _TempRepo() as repo:
            manifest = _experiment(repo.root, 42)
            with self.assertRaises(ValueError):
                api.interpret_experiment({"root": manifest["root"]}, llm_fn=lambda prompt: "不是 JSON")
            with mock.patch.object(
                api, "interpret_experiment", side_effect=ValueError("模型没有返回可解析的 JSON 解读")
            ):
                payload, status = api.handle_post(
                    "/api/parallel-worlds/interpret", {"root": manifest["root"]}
                )
            self.assertEqual(status, 400)
            self.assertIn("JSON", payload["error"])
