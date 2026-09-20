"""Parallel worlds: spec validation, world isolation, divergence, the panel API.

Five failure modes drive what is covered, because each one produces a *plausible
looking* wrong answer rather than a crash:

* **Two worlds sharing an output path contaminate each other.** The whole
  method rests on each world having its own memory, state and diary tree; if
  an override is dropped the experiment still runs and still reports numbers,
  and the numbers are meaningless. Asserted per path, not by spot check.
* **A per-world config patch that silently overrides the seed or the horizon**
  destroys the comparison it was supposed to make. The reserved-key rejection
  is the guard, so it is tested as a rejection, not as a filter.
* **Divergence measured against the wrong series reads as "no effect".** The
  analysis is checked against a fixture whose split point is known by
  construction.
* **Progress parsed out of a run log is a regex over free text.** It already
  mistook an agent's goal line ("目标 Day 14") for a day banner, so the
  discriminating case is pinned.
* **Legacy ``compare-event`` trees are adapted on the fly.** If the adapter
  drifts, years of existing counterfactuals disappear from the panel — with no
  error anywhere, just a shorter list.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import parallel_worlds_api as api
from gaworld.parallel import analysis, runner, spec as spec_mod


def _write_state(path: str, *, steps: int, shift: float, agents=(1, 2)) -> None:
    """A state history whose second half is offset by ``shift``."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["agent_id", "step", "metric", "value"])
        for agent in agents:
            for step in range(steps):
                bump = shift if step >= steps // 2 else 0.0
                writer.writerow([agent, step, "emotion", 0.5 + 0.01 * step + bump])
                writer.writerow([agent, step, "stress", 0.4 - bump / 2])


BASIC_PAYLOAD = {
    "name": "限行实验",
    "sim_days": 4,
    "seed": 7,
    "worlds": [
        {"label": "基准世界", "events": []},
        {
            "label": "限行世界",
            "events": [{"day": 2, "time": "07:00", "name": "限行", "description": "单双号"}],
        },
    ],
}


class SpecTests(unittest.TestCase):
    def test_baseline_defaults_to_the_world_without_events(self):
        payload = {
            "worlds": [
                {"label": "重度", "events": [{"day": 1, "name": "A"}]},
                {"label": "对照", "events": []},
            ]
        }
        experiment = spec_mod.normalize_experiment(payload)
        self.assertEqual(experiment.world(experiment.baseline_id).label, "对照")

    def test_world_ids_are_filesystem_safe(self):
        """Ids become directory names, so a CJK label must not become one."""
        experiment = spec_mod.normalize_experiment(BASIC_PAYLOAD)
        for world in experiment.worlds:
            self.assertRegex(world.id, r"^[0-9A-Za-z_-]+$")
        self.assertEqual(len({world.id for world in experiment.worlds}), 2)

    def test_at_least_two_worlds(self):
        with self.assertRaises(ValueError):
            spec_mod.normalize_experiment({"worlds": [{"label": "只有一个"}]})

    def test_event_requires_a_day_and_a_wellformed_time(self):
        with self.assertRaises(ValueError):
            spec_mod.normalize_experiment({
                "worlds": [{"label": "a"}, {"label": "b", "events": [{"name": "x"}]}]
            })
        with self.assertRaises(ValueError):
            spec_mod.normalize_experiment({
                "worlds": [
                    {"label": "a"},
                    {"label": "b", "events": [{"name": "x", "day": 1, "time": "早上"}]},
                ]
            })

    def test_events_are_sorted_by_when_they_happen(self):
        experiment = spec_mod.normalize_experiment({
            "worlds": [
                {"label": "a"},
                {"label": "b", "events": [
                    {"name": "晚", "day": 3, "time": "08:00"},
                    {"name": "早", "day": 1, "time": "20:00"},
                    {"name": "中", "day": 1, "time": "09:00"},
                ]},
            ]
        })
        self.assertEqual(
            [event["name"] for event in experiment.worlds[1].events], ["中", "早", "晚"]
        )

    def test_a_world_patch_may_not_override_the_experiment_controls(self):
        for key in ("random_seed", "sim_days", "agent_ids", "memory_dir"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError) as caught:
                    spec_mod.normalize_experiment({
                        "worlds": [{"label": "a"}, {"label": "b", "config": {key: 1}}]
                    })
                self.assertIn(key, str(caught.exception))

    def test_every_written_path_is_isolated_per_world(self):
        experiment = spec_mod.normalize_experiment(BASIC_PAYLOAD)
        seen: dict[str, set[str]] = {}
        for world in experiment.worlds:
            overrides = spec_mod.world_overrides(experiment, world, f"root/{world.id}")
            for key in (
                "memory_dir", "log_dir", "vector_db_path", "state_output_dir",
                "network_output_dir", "environment_output_dir", "diary_output_dir",
            ):
                seen.setdefault(key, set()).add(overrides[key])
            seen.setdefault("visualization", set()).add(overrides["visualization"]["output_dir"])
            seen.setdefault("intervention", set()).add(overrides["intervention"]["output_dir"])
            seen.setdefault("life_events", set()).add(overrides["life_events"]["event_dir"])
        for key, paths in seen.items():
            # `reset` clears each of these; one shared value means one world
            # wipes another's history — or the operator's live output tree.
            self.assertEqual(len(paths), len(experiment.worlds), f"{key} is shared: {paths}")

    def test_only_the_event_world_carries_the_event(self):
        experiment = spec_mod.normalize_experiment(BASIC_PAYLOAD)
        base, event = experiment.worlds
        ambient = {"policy_events": [{"day": 1, "name": "既有事件"}]}
        base_overrides = spec_mod.world_overrides(experiment, base, "r/a", base_config=ambient)
        event_overrides = spec_mod.world_overrides(experiment, event, "r/b", base_config=ambient)
        self.assertEqual([item["name"] for item in base_overrides["policy_events"]], ["既有事件"])
        self.assertEqual(
            [item["name"] for item in event_overrides["policy_events"]], ["既有事件", "限行"]
        )
        self.assertEqual(base_overrides["random_seed"], event_overrides["random_seed"])

    def test_world_config_patch_merges_over_the_defaults(self):
        experiment = spec_mod.normalize_experiment({
            "worlds": [
                {"label": "a"},
                {"label": "b", "config": {"economy": {"tax_rate": 0.3}}},
            ]
        })
        overrides = spec_mod.world_overrides(experiment, experiment.worlds[1], "r/b")
        self.assertEqual(overrides["economy"], {"tax_rate": 0.3})


class AnalysisTests(unittest.TestCase):
    def test_series_average_over_agents_and_carry_finals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.csv")
            _write_state(path, steps=6, shift=0.0)
            series = analysis.read_state_series(path)
            self.assertEqual(series["steps"], 6)
            self.assertAlmostEqual(series["metrics"]["emotion"][0], 0.5)
            self.assertAlmostEqual(series["agents"]["1"]["emotion"], 0.55)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(analysis.read_state_series("/nope/state.csv")["steps"], 0)

    def test_divergence_finds_the_step_the_histories_split(self):
        manifest = {"spec": {
            "baseline_id": "base",
            "sim_days": 2,
            "worlds": [
                {"id": "base", "label": "基准", "events": []},
                {"id": "shock", "label": "冲击", "events": [{"day": 1, "time": "09:00", "name": "e"}]},
            ],
        }}
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "a.csv")
            shock = os.path.join(tmp, "b.csv")
            _write_state(base, steps=8, shift=0.0)
            _write_state(shock, steps=8, shift=0.2)
            report = analysis.build_report(manifest, {
                "base": analysis.read_state_series(base),
                "shock": analysis.read_state_series(shock),
            })
        worlds = {world["id"]: world for world in report["worlds"]}
        self.assertEqual(worlds["base"]["split_step"], None)
        self.assertEqual(worlds["shock"]["split_step"], 4)  # shift starts at steps//2
        self.assertAlmostEqual(worlds["shock"]["divergence_final"], 0.15)
        self.assertGreater(len(report["deltas"]), 0)
        top = report["deltas"][0]
        self.assertEqual(top["world_id"], "shock")
        self.assertAlmostEqual(top["delta_final"], 0.2)
        self.assertEqual(len(report["movers"]["shock"]), 2)

    def test_a_world_with_no_artifacts_is_reported_not_dropped(self):
        manifest = {"spec": {
            "baseline_id": "base",
            "worlds": [{"id": "base", "label": "基准"}, {"id": "dead", "label": "崩了"}],
        }}
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "a.csv")
            _write_state(base, steps=4, shift=0.0)
            report = analysis.build_report(manifest, {
                "base": analysis.read_state_series(base),
                "dead": analysis.read_state_series(os.path.join(tmp, "missing.csv")),
            })
        dead = [world for world in report["worlds"] if world["id"] == "dead"][0]
        self.assertFalse(dead["has_data"])
        self.assertIn("无状态数据", "".join(analysis.summarize_report(report)))


class RunnerTests(unittest.TestCase):
    def test_day_progress_ignores_day_numbers_in_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "- 短期[stg1]：目标 Day 14\n"
                    "================= Day 1 (2026-06-24) =================\n"
                    "[FastForward Day 2] 平稳的一天\n"
                )
            self.assertEqual(runner.latest_day(path), 2)

    def test_failure_hint_surfaces_the_exception_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "noise\nTraceback (most recent call last):\n"
                    '  File "x.py", line 1, in call\n'
                    "requests.exceptions.HTTPError: HTTP 429 quota exceeded\n"
                )
            self.assertIn("429", runner.failure_hint(path))

    def test_prepare_writes_a_manifest_that_reloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            experiment = spec_mod.normalize_experiment(BASIC_PAYLOAD)
            manifest = runner.prepare_experiment(experiment, tmp)
            reloaded = runner.load_manifest(tmp, manifest["root"])
            self.assertEqual(reloaded["spec"]["seed"], 7)
            self.assertEqual(sorted(reloaded["worlds"]), sorted(manifest["worlds"]))
            for entry in manifest["worlds"].values():
                self.assertTrue(os.path.isdir(os.path.join(tmp, entry["dir"])))

    def test_run_forks_one_process_per_world_and_writes_the_report(self):
        """End to end against a stub simulator: fork, log, analyse, persist."""
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "stub_sim.py")
            with open(stub, "w", encoding="utf-8") as handle:
                handle.write(
                    "import csv, json, os, sys\n"
                    "ov = json.loads(os.environ['GAWORLD_CONFIG_OVERRIDES'])\n"
                    "if sys.argv[1] == 'reset':\n"
                    "    sys.exit(0)\n"
                    "days = int(ov.get('sim_days', 1))\n"
                    "shift = 0.2 * len(ov.get('policy_events', []))\n"
                    "out = ov['state_output_dir']\n"
                    "os.makedirs(out, exist_ok=True)\n"
                    "for d in range(1, days + 1):\n"
                    "    print('================= Day %d (x) =====' % d, flush=True)\n"
                    "with open(os.path.join(out, 'agent_state_history.csv'), 'w', newline='') as f:\n"
                    "    w = csv.writer(f)\n"
                    "    w.writerow(['agent_id', 'step', 'metric', 'value'])\n"
                    "    for a in (1, 2):\n"
                    "        for s in range(8):\n"
                    "            w.writerow([a, s, 'emotion', 0.5 + (shift if s >= 4 else 0)])\n"
                )
            experiment = spec_mod.normalize_experiment(BASIC_PAYLOAD)
            manifest = runner.prepare_experiment(experiment, tmp)
            report = runner.ExperimentRunner(
                manifest, tmp, max_parallel=2, script_path=stub
            ).run()

            self.assertEqual(manifest["status"], "done")
            self.assertEqual(set(manifest["world_status"].values()), {"done"})
            shock = [world for world in report["worlds"] if not world["is_baseline"]][0]
            self.assertEqual(shock["status"], "done")
            self.assertEqual(shock["split_step"], 4)
            root = os.path.join(tmp, manifest["root"])
            for name in ("report.json", "divergence_metrics.csv", "divergence_summary.md"):
                self.assertTrue(os.path.exists(os.path.join(root, name)), name)
            with open(os.path.join(root, "divergence_metrics.csv"), encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertTrue(any(row["world_id"] == shock["id"] for row in rows))
            # Each world wrote into its own tree and nowhere else.
            for entry in manifest["worlds"].values():
                self.assertTrue(
                    os.path.exists(os.path.join(tmp, entry["state_csv"])), entry["state_csv"]
                )


class _TempRepo:
    """Point the dashboard's path constants at a scratch tree."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._saved = (ds.REPO_ROOT, ds.DASHBOARD_CONFIG_PATH)

    def __enter__(self):
        ds.REPO_ROOT = self.root
        ds.DASHBOARD_CONFIG_PATH = os.path.join(self.root, "dashboard_config.json")
        api._reset_for_tests()
        return self

    def __exit__(self, *exc):
        ds.REPO_ROOT, ds.DASHBOARD_CONFIG_PATH = self._saved
        api._reset_for_tests()
        self.tmp.cleanup()
        return False


class ApiTests(unittest.TestCase):
    def _legacy_tree(self, root: str, name: str, *, with_data: bool) -> str:
        directory = os.path.join(root, "output", "comparisons", name)
        for world in ("without_event", "with_event"):
            os.makedirs(os.path.join(directory, world), exist_ok=True)
            if with_data:
                _write_state(
                    os.path.join(directory, world, "state", "agent_state_history.csv"),
                    steps=6,
                    shift=0.2 if world == "with_event" else 0.0,
                )
        with open(os.path.join(directory, "run_meta.json"), "w", encoding="utf-8") as handle:
            json.dump({"event_name": "限行", "sim_days": 3, "seed": 42}, handle)
        return directory

    def test_legacy_compare_event_trees_appear_as_two_world_experiments(self):
        with _TempRepo() as repo:
            self._legacy_tree(repo.root, "20260101_000000_限行", with_data=True)
            items = api.list_experiments()
            self.assertEqual(len(items), 1)
            self.assertTrue(items[0]["legacy"])
            self.assertTrue(items[0]["has_data"])
            self.assertEqual(items[0]["worlds"], 2)

            report = api.experiment_report(items[0]["root"])
            self.assertEqual(report["baseline_id"], "without_event")
            shock = [w for w in report["worlds"] if not w["is_baseline"]][0]
            self.assertGreater(shock["divergence_final"], 0)

    def test_experiments_without_state_data_are_flagged_not_hidden(self):
        with _TempRepo() as repo:
            self._legacy_tree(repo.root, "20260101_000000_空跑", with_data=False)
            items = api.list_experiments()
            self.assertEqual(len(items), 1)
            self.assertFalse(items[0]["has_data"])

    def test_unknown_experiment_is_a_404(self):
        with _TempRepo():
            payload, status = api.handle_get(
                "/api/parallel-worlds/experiment", {"root": ["output/nope"]}
            )
            self.assertEqual(status, 404)
            self.assertIn("error", payload)

    def test_preview_validates_without_running_anything(self):
        with _TempRepo() as repo:
            payload, status = api.handle_post("/api/parallel-worlds/preview", BASIC_PAYLOAD)
            self.assertEqual(status, 200)
            self.assertEqual(len(payload["plan"]), 2)
            self.assertTrue(payload["plan"][0]["is_baseline"])
            self.assertFalse(os.path.exists(os.path.join(repo.root, "output", "parallel_worlds")))

    def test_a_bad_spec_is_a_400(self):
        with _TempRepo():
            payload, status = api.handle_post(
                "/api/parallel-worlds/preview", {"worlds": [{"label": "只有一个"}]}
            )
            self.assertEqual(status, 400)
            self.assertIn("error", payload)

    def test_a_second_experiment_is_refused_while_one_runs(self):
        with _TempRepo():
            api._JOBS["pw-x"] = {
                "id": "pw-x", "status": "running", "started_at": 0.0, "progress": 0.0,
            }
            api._ACTIVE["job_id"] = "pw-x"
            payload, status = api.handle_post("/api/parallel-worlds/start", BASIC_PAYLOAD)
            self.assertEqual(status, 409)
            self.assertIn("已有平行世界实验在运行", payload["error"])

    def test_routing_rejects_unknown_endpoints(self):
        with _TempRepo():
            self.assertEqual(api.handle_get("/api/parallel-worlds/nope", {})[1], 404)
            self.assertEqual(api.handle_post("/api/parallel-worlds/nope", {})[1], 404)

    def test_dashboard_server_forwards_the_routes(self):
        """The routing chain is 60 branches long; a missing one is silent."""
        import inspect

        source = inspect.getsource(ds.DashboardHandler)
        self.assertIn("/api/parallel-worlds", source)
        self.assertEqual(source.count('path.startswith("/api/parallel-worlds")'), 2)


if __name__ == "__main__":
    unittest.main()
