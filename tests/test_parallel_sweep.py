"""Parameter sweep: one numeric setting, several values, one world each.

See ``gaworld/parallel/sweep.py``. A sweep is an ordinary parallel-worlds
experiment; what is tested here is the expansion and its guard rails, that
the patch reaches a world's config without clobbering its siblings, and that
the report's dose–response reads the sweep as effect against value.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from gaworld.apps import parallel_worlds_api as api
from gaworld.parallel import causal
from gaworld.parallel import sweep as psweep
from gaworld.parallel.spec import normalize_experiment, world_overrides

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG = {
    "random_seed": 42,
    "sim_days": 7,
    "economy": {"shocks": {"enabled": True, "layoff_base_prob": 0.001, "raise_base_prob": 0.008,
                           "medical_cost_range": (2000.0, 50000.0)}},
    "traffic": {"enabled": False, "agents_represent": 25},
    "city": "default",
}

PATH = "economy.shocks.layoff_base_prob"


class TestExpansion:
    def test_tunables_are_the_numeric_settings_outside_the_experiment_keys(self):
        paths = {item["path"]: item["value"] for item in psweep.tunables(CONFIG)}
        assert paths == {PATH: 0.001, "economy.shocks.raise_base_prob": 0.008, "traffic.agents_represent": 25}

    def test_a_sweep_is_a_baseline_at_the_current_value_plus_one_world_per_value(self):
        out = psweep.sweep_worlds(CONFIG, PATH, "0.004, 0.002")
        base, *swept = out["worlds"]
        assert (base["id"], base["role"], base["dose"], base["config"]) == ("baseline", "baseline", 0.001, {})
        assert [w["dose"] for w in swept] == [0.002, 0.004]
        assert swept[0]["config"] == {"economy": {"shocks": {"layoff_base_prob": 0.002}}}
        assert all(w["role"] == "treatment" for w in swept)
        assert out["current"] == 0.001 and out["dropped"] == []

    def test_the_current_value_and_repeats_are_dropped_not_run_twice(self):
        out = psweep.sweep_worlds(CONFIG, PATH, [0.001, 0.002, 0.002, 0.003])
        assert out["values"] == [0.002, 0.003]
        assert [d["reason"] for d in out["dropped"]] == ["与当前值相同，就是基准世界", "重复"]

    def test_an_integer_setting_takes_integers_only(self):
        out = psweep.sweep_worlds(CONFIG, "traffic.agents_represent", "50, 100.0")
        assert out["values"] == [50, 100] and all(isinstance(v, int) for v in out["values"])
        with pytest.raises(ValueError, match="不是整数"):
            psweep.sweep_worlds(CONFIG, "traffic.agents_represent", "50, 62.5")

    @pytest.mark.parametrize(("path", "message"), [
        ("economy.shocks.layof_base_prob", "找不到 layof_base_prob"),
        ("economy.shocks.enabled", "不是数值"),
        ("economy.shocks.medical_cost_range", "不是数值"),
        ("random_seed", "实验级设置"),
        ("sim_days", "实验级设置"),
        ("", "缺少"),
    ])
    def test_paths_that_cannot_be_swept_are_refused(self, path, message):
        with pytest.raises(ValueError, match=message):
            psweep.sweep_worlds(CONFIG, path, "1, 2")

    def test_value_count_limits(self):
        with pytest.raises(ValueError, match="至少要两个"):
            psweep.sweep_worlds(CONFIG, PATH, "0.001, 0.002")
        seven = ",".join(str(0.01 * i) for i in range(1, 8))
        assert len(psweep.sweep_worlds(CONFIG, PATH, seven)["worlds"]) == 8
        with pytest.raises(ValueError, match="最多 6 个取值"):
            psweep.sweep_worlds(CONFIG, PATH, seven, placebo=True)
        with pytest.raises(ValueError, match="不是数字"):
            psweep.sweep_worlds(CONFIG, PATH, "0.01, lots")

    def test_the_placebo_is_an_exact_copy_of_the_baseline_and_events_are_shared(self):
        shock = {"day": 3, "time": "09:00", "name": "经济下行", "description": "d"}
        out = psweep.sweep_worlds(CONFIG, PATH, "0.002, 0.004", placebo=True, events=[shock])
        placebo = out["worlds"][-1]
        assert (placebo["role"], placebo["dose"], placebo["config"]) == ("placebo", 0.001, {})
        assert all(w["events"] == [shock] for w in out["worlds"])

    def test_cli_argument(self):
        assert psweep.parse_sweep_arg(f"{PATH}=0.002,0.004") == (PATH, [0.002, 0.004])
        with pytest.raises(ValueError, match="格式"):
            psweep.parse_sweep_arg("0.002,0.004")


class TestDownstream:
    def _spec(self, **kw):
        out = psweep.sweep_worlds(CONFIG, PATH, "0.002, 0.004", **kw)
        return normalize_experiment({"name": "sweep", "worlds": out["worlds"], "baseline_id": out["baseline_id"]})

    def test_the_sweep_is_a_valid_experiment(self):
        spec = self._spec(placebo=True)
        assert spec.baseline_id == "baseline"
        assert [w.dose for w in spec.worlds] == [0.001, 0.002, 0.004, 0.001]

    def test_the_patch_reaches_the_child_and_leaves_the_siblings_alone(self, tmp_path):
        spec = self._spec()
        overrides = world_overrides(spec, spec.worlds[1], str(tmp_path / "w"), base_config=CONFIG)
        # One key under economy.shocks; the world's own economy output dir is pinned beside it.
        assert overrides["economy"]["shocks"] == {"layoff_base_prob": 0.002}
        env = {**os.environ, "GAWORLD_CONFIG_OVERRIDES": json.dumps({"economy": overrides["economy"]}),
               "GAWORLD_IGNORE_LOCAL_CONFIG": "1"}
        proc = subprocess.run(
            [sys.executable, "-c", "import json; from gaworld.settings import CONFIG; "
             "print(json.dumps(CONFIG['economy']['shocks'], default=list))"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=True,
        )
        shocks = json.loads(proc.stdout.strip().splitlines()[-1])
        assert shocks["layoff_base_prob"] == 0.002
        assert shocks["raise_base_prob"] == 0.008 and shocks["enabled"] is True

    def test_dose_response_reads_the_sweep_from_the_current_value(self):
        spec = self._spec(placebo=True)
        worlds = [w.to_dict() for w in spec.worlds]
        estimates = [
            {"world_id": "v1", "metric": "stress", "ate": 0.01},
            {"world_id": "v2", "metric": "stress", "ate": 0.03},
            {"world_id": "placebo", "metric": "stress", "ate": 0.5},
        ]
        (row,) = causal.dose_response(estimates, worlds, "baseline")
        assert [(p["world_id"], p["dose"]) for p in row["points"]] == [
            ("baseline", 0.001), ("v1", 0.002), ("v2", 0.004)]
        assert row["monotonic"] and row["slope"] > 0


class TestApi:
    def test_the_endpoint_expands_against_the_effective_config(self, monkeypatch):
        monkeypatch.setattr(api, "_config", lambda: CONFIG)
        body, status = api.handle_post("/api/parallel-worlds/sweep",
                                       {"path": PATH, "values": [0.002, 0.004], "placebo": True})
        assert status == 200 and len(body["worlds"]) == 4 and body["current"] == 0.001
        body, status = api.handle_post("/api/parallel-worlds/sweep", {"path": "sim_days", "values": [3, 5]})
        assert status == 400 and "实验级设置" in body["error"]

    def test_the_plan_names_the_changed_setting(self):
        spec = self._spec()
        plan = api._plan(spec)
        assert plan[1]["summary"] == f"配置 {PATH} = 0.002"
        assert plan[0]["summary"] == "无干预（基准）"

    def _spec(self):
        out = psweep.sweep_worlds(CONFIG, PATH, "0.002, 0.004")
        return normalize_experiment({"name": "sweep", "worlds": out["worlds"], "baseline_id": "baseline"})


def test_cli_sweep_builds_the_worlds_and_takes_events_from_the_spec_baseline(tmp_path, monkeypatch, capsys):
    import gaworld.parallel as parallel
    import generative_city_sim as sim
    from gaworld.parallel import analysis

    captured = {}

    def fake_prepare(spec, repo_root, **kw):
        captured["spec"] = spec
        return {"root": "output/parallel_worlds/x"}

    class FakeRunner:
        def __init__(self, *a, **kw):
            pass

        def run(self, on_progress=None):
            return {}

    monkeypatch.setattr(parallel, "prepare_experiment", fake_prepare)
    monkeypatch.setattr(parallel, "ExperimentRunner", FakeRunner)
    monkeypatch.setattr(analysis, "summarize_report", lambda report: [])
    monkeypatch.setattr(sim, "CONFIG", CONFIG)
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps({"name": "下行期扫描", "agent_ids": [1, 2], "worlds": [
        {"label": "基准", "events": [{"day": 2, "time": "09:00", "name": "经济下行", "description": "d"}]}]},
        ensure_ascii=False), encoding="utf-8")
    args = sim._build_arg_parser().parse_args(
        ["parallel-worlds", "--spec", str(spec_file), "--sweep", f"{PATH}=0.002,0.004,0.001", "--placebo"])
    sim._cli_parallel_worlds(args)
    spec = captured["spec"]
    assert spec.name == "下行期扫描" and spec.agent_ids == [1, 2]
    assert [w.dose for w in spec.worlds] == [0.001, 0.002, 0.004, 0.001]
    assert all(w.events and w.events[0]["name"] == "经济下行" for w in spec.worlds)
    out = capsys.readouterr().out
    assert "跳过取值 0.001" in out and f"{PATH} = 0.004" in out

    with pytest.raises(SystemExit, match="--spec 或 --sweep"):
        sim._cli_parallel_worlds(sim._build_arg_parser().parse_args(["parallel-worlds"]))
    with pytest.raises(SystemExit, match="参数扫描"):
        sim._cli_parallel_worlds(sim._build_arg_parser().parse_args(["parallel-worlds", "--sweep", "sim_days=3,5"]))
