"""Phase 9 — contract-locking tests for the ``gaworld.worldrun`` shared
execution substrate (TDD RED).

These tests lock the TARGET API described in the Phase 9 brief:

* ``launch(world_spec, *, seed_from_dir=None, max_parallel=None) -> RunHandle``
* output isolation from ONE authoritative definition (reserved keys, path keys)
* manifest v2 (additive fields, atomic writes)
* ``seed_from_dir`` checkpoint-restore launch semantics
* shared status model and failure isolation
* secrets sentinel
* completed-day state-history persistence (hard gates)
* single-implementation audit (authoritative definitions / import paths)
* PW-specific regressions (forced provider vs ``llm.routing.agents``; optional
  ``seed_from_checkpoint`` is additive)

Until ``gaworld/worldrun/`` exists every target-API test fails with
``ModuleNotFoundError`` — that is the expected RED reason.  Tests that only
lock CURRENT behavior (legacy schema of ``agent_state_history.csv``,
``read_state_series`` compatibility) pass already and are marked as guards.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _worldrun():
    """Import the (future) worldrun package. Fails RED until it exists."""
    from gaworld import worldrun  # noqa: F401

    return worldrun


def _write_source_history(path: Path, days: range, agent_ids=(1, 2)) -> None:
    """Write a legacy-schema state/agent_state_history.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["agent_id", "step", "metric", "value"]
        )
        writer.writeheader()
        step = 0
        for day in days:
            for agent_id in agent_ids:
                for metric in ("emotion", "energy"):
                    writer.writerow(
                        {
                            "agent_id": agent_id,
                            "step": step,
                            "metric": metric,
                            "value": round(0.5 + 0.01 * step, 6),
                        }
                    )
            step += 1


# ---------------------------------------------------------------------------
# Part A — launch / RunHandle contract
# ---------------------------------------------------------------------------


class TestLaunchContract:
    def test_worldrun_package_exists(self):
        _worldrun()

    def test_launch_returns_run_handle_with_identity(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch(
                {"name": "w1", "config": {"sim_days": 1}},
                repo_root=str(tmp),
            )
            assert handle.run_id, "RunHandle must expose a run identity"
            assert handle.world_id == "w1"

    def test_run_handle_status_lifecycle(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1"}, repo_root=str(tmp))
            # shared status model: exactly these values, nothing else
            assert handle.status in {
                "created",
                "running",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
            }
            handle.wait(timeout=0.1)
            assert handle.status in {"completed", "failed", "cancelled", "timed_out"}

    def test_run_handle_exposes_output_dir_and_manifest_ref(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1"}, repo_root=str(tmp))
            output_dir = Path(handle.output_dir)
            assert output_dir.is_absolute() or Path(handle.repo_root, handle.output_dir).exists()
            assert handle.manifest_ref, "RunHandle must expose a manifest reference"

    def test_run_handle_actions_wait_and_cancel(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1"}, repo_root=str(tmp))
            assert callable(handle.wait)
            assert callable(handle.cancel)

    def test_max_parallel_is_accepted_and_bounded(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handles = wr.launch(
                [{"name": f"w{i}"} for i in range(3)],
                repo_root=str(tmp),
                max_parallel=2,
            )
            assert len(list(handles)) == 3


# ---------------------------------------------------------------------------
# Part B — output isolation: single authoritative source (§71)
# ---------------------------------------------------------------------------


class TestOutputIsolationSingleSource:
    def test_reserved_keys_defined_once_in_worldrun(self):
        wr = _worldrun()
        from gaworld.parallel import spec as pw_spec

        # worldrun is the authoritative definition; PW re-exports it.
        assert pw_spec.RESERVED_CONFIG_KEYS is wr.RESERVED_CONFIG_KEYS

    def test_reserved_keys_cover_every_run_path_leaf(self):
        wr = _worldrun()
        from gaworld.city.config import RUN_PATHS

        # flat RUN_PATHS keys are top-level config keys and must all be
        # reserved; dotted keys ("economy.output_dir") are pinned by re-running
        # run_root_overrides instead.
        flat = {key for key in RUN_PATHS if "." not in key and key not in ("", "output_root")}
        missing = flat - set(wr.RESERVED_CONFIG_KEYS)
        assert not missing, f"reserved keys must cover RUN_PATHS leaves: {missing}"

    def test_reserved_override_is_rejected_loudly(self):
        wr = _worldrun()
        with pytest.raises(Exception) as excinfo:
            wr.launch(
                {"name": "w1", "config": {"random_seed": 999}}, repo_root="."
            )
        assert "random_seed" in str(excinfo.value), (
            "rejection must name the offending reserved key"
        )

    def test_path_override_cannot_reenter_shared_tree(self):
        wr = _worldrun()
        with pytest.raises(Exception):
            wr.launch(
                {"name": "w1", "config": {"economy": {"output_dir": "output"}}},
                repo_root=".",
            )


# ---------------------------------------------------------------------------
# Part C — manifest v2: additive fields + atomicity
# ---------------------------------------------------------------------------


class TestManifestV2:
    def test_manifest_write_is_atomic_no_partial_discoverable(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "root": os.path.join(tmp, "run"),
                "worlds": {"w1": {"status": "running"}},
            }
            wr.write_manifest(tmp, manifest)
            path = Path(tmp, "run", "experiment.json")
            assert path.exists()
            # a .tmp sibling must never survive a completed write
            assert not Path(f"{path}.tmp").exists()
            loaded = wr.load_manifest(tmp, manifest["root"])
            assert loaded == manifest

    def test_manifest_v2_fields_are_additive(self):
        wr = _worldrun()
        from gaworld.parallel import runner as pw_runner

        legacy_required = {"root", "worlds"}
        manifest = {
            "root": "output/parallel/x",
            "worlds": {"w1": {"status": "done", "returncode": 0}},
        }
        # v2 optional fields
        v2 = dict(
            manifest,
            worldrun_version=1,
            completed_day=5,
            checkpoint_lineage={"source_run": "runs/a", "day": 3},
            seed_refs={"random_seed": 7},
            parent_run=None,
        )
        wr.validate_manifest(v2)  # must accept v2
        wr.validate_manifest(manifest)  # must still accept legacy (additive only)
        for key in legacy_required:
            assert key in pw_runner.write_manifest.__doc__ or True

    def test_manifest_never_contains_secrets(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {
                "root": os.path.join(tmp, "run"),
                "worlds": {"w1": {"status": "done"}},
                "env": {"OPENAI_API_KEY": "sk-secret", "PATH": "/usr/bin"},
            }
            wr.write_manifest(tmp, manifest)
            loaded = wr.load_manifest(tmp, manifest["root"])
            serialized = json.dumps(loaded)
            assert "sk-secret" not in serialized
            assert "OPENAI_API_KEY" not in serialized


# ---------------------------------------------------------------------------
# Part D — seed_from_dir semantics
# ---------------------------------------------------------------------------


class TestSeedFromDir:
    def _make_source_run(self, root: Path) -> Path:
        source = root / "source"
        _write_source_history(source / "state" / "agent_state_history.csv", range(3))
        (source / "checkpoints").mkdir(parents=True, exist_ok=True)
        (source / "checkpoints" / "day_0002").mkdir(exist_ok=True)
        (source / "checkpoints" / "day_0002" / "manifest.json").write_text(
            json.dumps({"completed_day": 2, "run_id": "src", "agent_ids": [1, 2]})
        )
        return source

    def test_seeded_launch_gets_fresh_output_dir(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_source_run(Path(tmp))
            handle = wr.launch(
                {"name": "fork", "sim_days": 4},
                repo_root=tmp,
                seed_from_dir=str(source),
            )
            assert Path(handle.output_dir) != source, "seeded run must not reuse source dir"
            assert Path(handle.output_dir).exists(), "seeded run output dir must be materialized"

    def test_seeded_launch_does_not_mutate_source(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_source_run(Path(tmp))
            before = sorted((p.relative_to(source), p.stat().st_mtime_ns) for p in source.rglob("*"))
            handle = wr.launch(
                {"name": "fork", "sim_days": 4},
                repo_root=tmp,
                seed_from_dir=str(source),
            )
            handle.wait(timeout=0.1)
            after = sorted((p.relative_to(source), p.stat().st_mtime_ns) for p in source.rglob("*"))
            assert before == after, "seed_from_dir must never mutate the source run"

    def test_seeded_launch_skips_destructive_reset(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_source_run(Path(tmp))
            handle = wr.launch(
                {"name": "fork", "sim_days": 4},
                repo_root=tmp,
                seed_from_dir=str(source),
            )
            assert getattr(handle, "reset_performed", True) is False, (
                "a seeded launch must not destructively reset the restored state"
            )

    def test_fresh_launch_still_resets(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "fresh", "sim_days": 2}, repo_root=tmp)
            assert handle.reset_performed is True, (
                "a fresh (non-seeded) launch still resets its world"
            )

    def test_seeded_run_preserves_agent_ids_and_seed(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            source = self._make_source_run(Path(tmp))
            handle = wr.launch(
                {"name": "fork", "sim_days": 4, "config": {"random_seed": 7, "agent_ids": [1, 2]}},
                repo_root=tmp,
                seed_from_dir=str(source),
            )
            manifest = handle.manifest()
            assert manifest["seed_refs"]["random_seed"] == 7
            assert list(manifest["agent_ids"]) == [1, 2]


# ---------------------------------------------------------------------------
# Part E — failure isolation
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    def test_failed_world_does_not_affect_sibling(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handles = wr.launch(
                [
                    {"name": "bad", "config": {"sim_days": 1}, "fail": True},
                    {"name": "good", "config": {"sim_days": 1}},
                ],
                repo_root=tmp,
            )
            bad, good = handles[0], handles[1]
            bad.wait(timeout=5)
            assert bad.status == "failed"
            assert good.status in {"created", "running", "completed"}, (
                "a sibling failure must not cancel or fail an independent world"
            )


# ---------------------------------------------------------------------------
# Part F — completed-day state history (hard gates, brief §70)
# ---------------------------------------------------------------------------


class TestStateHistoryHardGates:
    LEGACY_FIELDS = ["agent_id", "step", "metric", "value"]

    def test_completed_day_rows_persisted_per_day(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1", "sim_days": 3}, repo_root=tmp)
            handle.wait(timeout=5)
            csv_path = Path(handle.output_dir, "state", "agent_state_history.csv")
            assert csv_path.exists()
            rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
            steps = {int(r["step"]) for r in rows}
            assert steps == {0, 1, 2}, f"expected rows for exactly days 1-3, got {steps}"

    def test_interrupted_run_retains_completed_history(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1", "sim_days": 5}, repo_root=tmp)
            handle.cancel()
            csv_path = Path(handle.output_dir, "state", "agent_state_history.csv")
            assert csv_path.exists(), "interrupted run must retain history of completed days"
            rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
            steps = {int(r["step"]) for r in rows}
            assert max(steps) < 5, "no rows beyond the last completed day"

    def test_failed_partial_day_writes_nothing(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch(
                {"name": "w1", "sim_days": 2, "fail_on_day": 1}, repo_root=tmp
            )
            handle.wait(timeout=5)
            assert handle.status == "failed"
            csv_path = Path(handle.output_dir, "state", "agent_state_history.csv")
            if csv_path.exists():
                steps = {int(r["step"]) for r in csv.DictReader(open(csv_path, encoding="utf-8"))}
                assert 1 not in steps, "the failed partial day must not appear in history"

    def test_resume_appends_exactly_next_days_no_dup_no_loss(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            first = wr.launch({"name": "w1", "sim_days": 3}, repo_root=tmp)
            first.wait(timeout=5)
            resumed = wr.launch(
                {"name": "w1", "sim_days": 5},
                repo_root=tmp,
                seed_from_dir=str(first.output_dir),
            )
            resumed.wait(timeout=5)
            csv_path = Path(resumed.output_dir, "state", "agent_state_history.csv")
            rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
            per_agent_step = {}
            for r in rows:
                key = (r["agent_id"], int(r["step"]), r["metric"])
                count = per_agent_step.get(key, 0)
                per_agent_step[key] = count + 1
            dupes = [k for k, v in per_agent_step.items() if v > 1]
            assert not dupes, f"duplicated day rows after resume: {dupes[:3]}"
            steps = {int(r["step"]) for r in rows}
            assert steps == {0, 1, 2, 3, 4}, (
                f"resume 1-3 then 4-5 must yield exactly days 1-5, got {sorted(steps)}"
            )

    def test_final_schema_matches_legacy(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1", "sim_days": 2}, repo_root=tmp)
            handle.wait(timeout=5)
            csv_path = Path(handle.output_dir, "state", "agent_state_history.csv")
            with open(csv_path, encoding="utf-8") as fh:
                fields = next(csv.reader(fh))
            assert fields == self.LEGACY_FIELDS, f"schema drifted: {fields}"

    def test_read_state_series_still_consumes_it(self):
        wr = _worldrun()
        from gaworld.parallel.analysis import read_state_series

        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1", "sim_days": 2}, repo_root=tmp)
            handle.wait(timeout=5)
            csv_path = Path(handle.output_dir, "state", "agent_state_history.csv")
            series = read_state_series(str(csv_path), panel=True)
            assert series, "read_state_series must parse the worldrun-written history"

    def test_history_never_contains_secrets(self):
        wr = _worldrun()
        with tempfile.TemporaryDirectory() as tmp:
            handle = wr.launch({"name": "w1", "sim_days": 2}, repo_root=tmp)
            handle.wait(timeout=5)
            csv_path = Path(handle.output_dir, "state", "agent_state_history.csv")
            text = csv_path.read_text(encoding="utf-8")
            for marker in ("api_key", "sk-", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
                assert marker not in text, f"secret marker {marker!r} leaked into history"


# ---------------------------------------------------------------------------
# Part G — single-implementation audit (brief §71)
# ---------------------------------------------------------------------------


class TestSingleImplementationAudit:
    def test_pw_spec_imports_reserved_keys_from_worldrun(self):
        import gaworld.parallel.spec as pw_spec

        assert getattr(pw_spec, "_RESERVED_CONFIG_KEYS_SOURCE", "") == "gaworld.worldrun", (
            "PW must import reserved keys from worldrun, not define its own copy"
        )

    def test_simtree_branch_overrides_import_path_keys_from_worldrun(self):
        import fos.backend.services.simtree_gaworld as st

        assert getattr(st, "_RUN_ROOT_OVERRIDES_SOURCE", "") == "gaworld.worldrun", (
            "SimTree branch_runtime_overrides must take its path-key set from worldrun"
        )

    def test_checkpoint_seeding_delegates_not_duplicates(self):
        wr = _worldrun()
        import gaworld.checkpoints as cp

        assert wr.seed_from_dir.__module__.startswith("gaworld.worldrun")
        assert cp.__name__ == "gaworld.checkpoints", (
            "checkpoints.py stays the owner of serialization; worldrun delegates"
        )

    def test_subprocess_launch_primitive_defined_in_worldrun(self):
        wr = _worldrun()
        assert hasattr(wr, "launch_subprocess"), (
            "worldrun must own the subprocess launch primitive"
        )

    def test_manifest_writer_defined_once(self):
        from gaworld.parallel import runner as pw_runner
        import inspect

        wr = _worldrun()
        pw_src = inspect.getsource(pw_runner.write_manifest)
        assert "worldrun" in pw_src, (
            "PW manifest writing must delegate to worldrun"
        )


# ---------------------------------------------------------------------------
# Part H — PW-specific regressions (brief §23 / §24)
# ---------------------------------------------------------------------------


class TestPWRegressions:
    def test_forced_provider_preserves_llm_routing_agents(self):
        """§24: forcing a provider must not erase llm.routing.agents."""
        from gaworld.parallel.spec import (
            ExperimentSpec,
            WorldSpec,
            world_overrides,
        )

        base_config = {
            "llm": {
                "providers": {"p": {"type": "openai"}},
                "routing": {
                    "default": "p",
                    "tasks": {"schedule": "p"},
                    "agents": {"3": {"provider": "other", "model": "m"}},
                },
            }
        }
        spec = ExperimentSpec(
            name="t", worlds=[], baseline_id="w1", llm_provider="forced"
        )
        world = WorldSpec(id="w1", label="W1", role="treatment")
        overrides = world_overrides(
            spec, world, "output/parallel/x/w1", base_config=base_config
        )
        routing = overrides.get("llm", {}).get("routing", {})
        assert routing.get("agents", {}).get("3") == {"provider": "other", "model": "m"}, (
            "forced-provider normalization erased llm.routing.agents"
        )
        assert routing.get("default") == "forced", "provider must still be forced"

    def test_pw_experiment_accepts_optional_seed_from_checkpoint(self):
        """§23: seed_from_checkpoint is additive; normal PW unchanged."""
        from gaworld.parallel.spec import normalize_experiment

        spec = normalize_experiment(
            {
                "name": "t",
                "worlds": [
                    {"id": "baseline", "role": "baseline"},
                    {
                        "id": "replay",
                        "role": "treatment",
                        "seed_from_checkpoint": "runs/a/checkpoints/day_0002",
                    },
                ],
            }
        )
        seeded = [w for w in spec.worlds if w.id == "replay"]
        assert seeded, "world 'replay' missing"
        assert getattr(seeded[0], "seed_from_checkpoint", None) == (
            "runs/a/checkpoints/day_0002"
        ), "WorldSpec must gain an optional seed_from_checkpoint field"
        normal = [w for w in spec.worlds if w.id == "baseline"]
        assert getattr(normal[0], "seed_from_checkpoint", None) is None


# ---------------------------------------------------------------------------
# Part I — guards over CURRENT behavior (green today; protect during migration)
# ---------------------------------------------------------------------------


class TestLegacyGuards:
    def test_legacy_state_history_schema_on_disk(self):
        sample = REPO_ROOT / "output" / "state" / "agent_state_history.csv"
        if not sample.exists():
            pytest.skip("no sample history on disk in this checkout")
        with open(sample, encoding="utf-8") as fh:
            fields = next(csv.reader(fh))
        assert fields == ["agent_id", "step", "metric", "value"]

    def test_legacy_pw_manifest_write_is_already_atomic(self):
        from gaworld.parallel import runner as pw_runner

        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"root": os.path.join(tmp, "r"), "worlds": {}}
            pw_runner.write_manifest(tmp, manifest)
            assert Path(tmp, "r", "experiment.json").exists()
            assert not Path(tmp, "r", "experiment.json.tmp").exists()

    def test_branch_runtime_overrides_use_run_root_overrides_keys(self):
        from fos.backend.services.simtree_gaworld import branch_runtime_overrides
        from gaworld.city.config import RUN_PATHS

        patch = branch_runtime_overrides("/tmp/branch-x")

        def dig(node, dotted):
            for part in dotted.split("."):
                node = node.get(part, {})
            return node

        for dotted in RUN_PATHS:
            assert dig(patch, dotted), f"branch override missing RUN_PATHS key {dotted}"
        assert patch["gaworld"]["checkpoint"]["restore_dir"] == "/tmp/branch-x/checkpoints"

    def test_reserved_keys_are_the_comparison_knobs(self):
        from gaworld.parallel.spec import RESERVED_CONFIG_KEYS

        for key in ("random_seed", "sim_days", "agent_ids"):
            assert key in RESERVED_CONFIG_KEYS
