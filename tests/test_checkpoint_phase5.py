"""Phase 5 STAGE A — checkpoint state, RNG and restore invariants (RED).

Specifies the GAWorld-owned durable checkpoint feature at completed-day
boundaries (see task 2555 / PHASE5-BRIEF.md §14).  These tests are written
before any implementation exists: they should fail on the missing
``gaworld.checkpoints`` module, not on syntax errors.

Scope guards honoured: SAVE / RESTORE / CONTINUE only.  CSV / timeline /
reports are outputs, never checkpoint state.  No secrets in checkpoints.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys

import numpy as np
import pytest

try:  # deferred import: the feature is missing, tests must fail individually
    from gaworld.checkpoints import (
        CheckpointCorrupted,
        CheckpointManager,
        CheckpointVersionUnsupported,
    )

    _FEATURE_PRESENT = True
except ModuleNotFoundError as _exc:  # pragma: no cover - RED phase
    if _exc.name != "gaworld.checkpoints":
        raise
    _FEATURE_PRESENT = False


@pytest.fixture(autouse=True)
def _require_feature():
    if not _FEATURE_PRESENT:
        pytest.fail("gaworld.checkpoints not implemented (Phase 5 RED)")


# ---------------------------------------------------------------------------
# Helpers — a tiny deterministic "runtime" standing in for the real one
# ---------------------------------------------------------------------------


class MiniRuntime:
    """Minimal mutable runtime state with the same shape of concerns as the
    GAWorld day loop: clock/day cursor, per-agent mutable dicts, an RNG, a
    routing-provenance block and runtime config."""

    def __init__(self, seed: int = 7):
        self.completed_day = 0
        self.config = {"sim_days": 3, "city": "测试市"}
        self.agent_ids = [2, 7, 11]
        self.agents = {aid: {"id": aid, "mood": 0.5, "money": 100.0, "steps": []} for aid in self.agent_ids}
        self.rng_python = random.Random(seed)
        self.rng_numpy = np.random.default_rng(seed)
        self.routing = {
            "default_provider": "mock",
            "per_agent": {"7": "mock-b"},
            "policy": "ordered_fallback",
        }

    def run_day(self, llm) -> int:
        """Advance one day deterministically given a deterministic llm."""
        self.completed_day += 1
        day = self.completed_day
        for aid in self.agent_ids:
            a = self.agents[aid]
            a["steps"].append(llm(aid, day))
            a["mood"] = round(a["mood"] + self.rng_python.random() * 0.01, 6)
            a["money"] = round(a["money"] + float(self.rng_numpy.random()), 6)
        return day


def deterministic_llm(aid, day):
    return f"agent{aid}-day{day}"


def capture_state(rt: MiniRuntime) -> dict:
    """Everything a restored run must reproduce (no wall-clock, no paths)."""
    return {
        "completed_day": rt.completed_day,
        "agent_ids": list(rt.agent_ids),
        "agents": json.loads(json.dumps(rt.agents)),
        "routing": json.loads(json.dumps(rt.routing)),
    }


# ---------------------------------------------------------------------------
# Manifest / discovery
# ---------------------------------------------------------------------------


class TestManifestAndDiscovery:
    def test_save_day0000_before_day1(self, tmp_path):
        """Requirement 6: day_0000 checkpoint after population load, before
        day 1 mutates anything."""
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        ref = mgr.save_checkpoint(rt, completed_day=0)
        assert ref.completed_day == 0
        assert (tmp_path / "checkpoints" / "day_0000" / "manifest.json").is_file()

    def test_manifest_core_fields(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        manifest = json.loads((tmp_path / "checkpoints" / "day_0001" / "manifest.json").read_text("utf-8"))
        for key in (
            "checkpoint_version",
            "run_id",
            "completed_day",
            "city",
            "agent_ids",
            "created_at",
            "state_files",
        ):
            assert key in manifest, f"manifest missing {key}"
        assert manifest["run_id"] == "run-a"
        assert manifest["completed_day"] == 1
        assert manifest["agent_ids"] == [2, 7, 11]

    def test_list_and_latest_exclude_partial(self, tmp_path):
        """Requirement 7: temp/partial writes are never listed or returned."""
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        # simulate a crashed writer: stray temp directory
        partial = tmp_path / "checkpoints" / ".tmp-day_0002"
        partial.mkdir(parents=True)
        (partial / "manifest.json").write_text('{"completed_day": 2}', "utf-8")
        days = [c.completed_day for c in mgr.list_checkpoints()]
        assert days == [1]
        assert mgr.latest_checkpoint().completed_day == 1


# ---------------------------------------------------------------------------
# State equivalence / restore
# ---------------------------------------------------------------------------


class TestStateEquivalence:
    def test_all_components_roundtrip(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        rt.run_day(deterministic_llm)
        rt.run_day(deterministic_llm)
        mgr.save_checkpoint(rt, completed_day=rt.completed_day)
        before = capture_state(rt)

        fresh = MiniRuntime()  # destroyed / fresh runtime, day 0
        mgr.restore_checkpoint(fresh, ref=None)  # ref None → latest
        assert capture_state(fresh) == before, "every checkpointed component must survive restore identically"

    def test_resume_never_reruns_completed_day(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        rt.run_day(deterministic_llm)
        mgr.save_checkpoint(rt, completed_day=rt.completed_day)
        fresh = MiniRuntime()
        mgr.restore_checkpoint(fresh, ref=None)
        assert fresh.completed_day == 1
        fresh.run_day(deterministic_llm)
        assert fresh.completed_day == 2, "next simulated day is N+1, not N"

    def test_agent_identity_preserved(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=0)
        fresh = MiniRuntime()
        fresh.agent_ids = [999]
        mgr.restore_checkpoint(fresh, ref=None)
        assert fresh.agent_ids == [2, 7, 11], (
            "routing/identity must resolve by the same agent IDs post-restore"
        )
        assert set(fresh.agents) == {2, 7, 11}

    def test_routing_provenance_survives(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=0)
        fresh = MiniRuntime()
        mgr.restore_checkpoint(fresh, ref=None)
        assert fresh.routing == rt.routing


class TestContinuousVsResumed:
    def test_three_day_equivalence(self, tmp_path):
        """Run A: days 1..3 continuous.  Run B: day 1, checkpoint, destroy,
        restore into a fresh runtime, days 2..3.  Final state identical."""
        # continuous
        run_a = MiniRuntime()
        for _ in range(3):
            run_a.run_day(deterministic_llm)

        # resumed
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-b")
        run_b = MiniRuntime()
        run_b.run_day(deterministic_llm)
        mgr.save_checkpoint(run_b, completed_day=run_b.completed_day)
        run_b = None  # destroy

        resumed = MiniRuntime()
        mgr.restore_checkpoint(resumed, ref=None)
        resumed.run_day(deterministic_llm)
        resumed.run_day(deterministic_llm)

        assert capture_state(resumed) == capture_state(run_a), (
            "resumed run must match continuous run in every stateful component"
        )


class TestRNGContinuation:
    def test_python_and_numpy_rng_continue_sequence(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        rt.run_day(deterministic_llm)
        mgr.save_checkpoint(rt, completed_day=rt.completed_day)

        # draw after checkpoint in the continuous run
        cont_py = [rt.rng_python.random() for _ in range(3)]
        cont_np = [float(rt.rng_numpy.random()) for _ in range(3)]

        fresh = MiniRuntime()
        mgr.restore_checkpoint(fresh, ref=None)
        res_py = [fresh.rng_python.random() for _ in range(3)]
        res_np = [float(fresh.rng_numpy.random()) for _ in range(3)]

        assert res_py == cont_py, "python random must continue, not restart"
        assert res_np == cont_np, "numpy generator must continue, not restart"


# ---------------------------------------------------------------------------
# Failure / atomicity / validation
# ---------------------------------------------------------------------------


class TestFailedDayInvariant:
    def test_failed_day_leaves_no_checkpoint(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        rt.run_day(deterministic_llm)
        mgr.save_checkpoint(rt, completed_day=1)

        # day 2 fails midway: caller must NOT save; latest stays day 1
        rt.completed_day = 2  # partial mutation, then failure
        assert mgr.latest_checkpoint().completed_day == 1
        days = [c.completed_day for c in mgr.list_checkpoints()]
        assert days == [1]

    def test_never_silently_overwrites_valid_checkpoint(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        with pytest.raises(Exception):
            mgr.save_checkpoint(rt, completed_day=1, overwrite=False)


class TestValidationOnLoad:
    def test_version_rejected_with_precise_error(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        mpath = tmp_path / "checkpoints" / "day_0001" / "manifest.json"
        manifest = json.loads(mpath.read_text("utf-8"))
        manifest["checkpoint_version"] = -1
        mpath.write_text(json.dumps(manifest), "utf-8")
        fresh = MiniRuntime()
        with pytest.raises(CheckpointVersionUnsupported) as exc:
            mgr.restore_checkpoint(fresh, completed_day=1)
        assert "checkpoint_version" in str(exc.value) or "-1" in str(exc.value)

    def test_corrupted_state_rejected_no_partial_restore(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        day_dir = tmp_path / "checkpoints" / "day_0001"
        for path in manifest_state_files(day_dir):
            path.write_text("{not json", "utf-8")
        fresh = MiniRuntime()
        with pytest.raises(CheckpointCorrupted):
            mgr.restore_checkpoint(fresh, completed_day=1)
        assert fresh.completed_day == 0, "no partial continuation allowed"


def manifest_state_files(day_dir):
    """Yield (path, name) for every state file named in the manifest."""
    manifest = json.loads((day_dir / "manifest.json").read_text("utf-8"))
    out = []
    for rel in manifest.get("state_files", []):
        if isinstance(rel, str):
            out.append(day_dir / rel)
        elif isinstance(rel, dict) and "path" in rel:
            out.append(day_dir / rel["path"])
    return out


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class TestSecretsNeverCheckpointed:
    def test_no_api_keys_in_checkpoint_payload(self, tmp_path):
        rt = MiniRuntime()
        rt.config["llm_api_key"] = "sk-supersecret-123"
        rt.config["jwt_token"] = "eyJhbGciOi.token"
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        blob = ""
        for path in (tmp_path / "checkpoints" / "day_0001").rglob("*"):
            if path.is_file():
                blob += path.read_text("utf-8", errors="ignore")
        assert "sk-supersecret-123" not in blob
        assert "eyJhbGciOi.token" not in blob
        # provider/model identifiers are fine and expected
        assert "mock" in blob


# ---------------------------------------------------------------------------
# Fresh-process restore
# ---------------------------------------------------------------------------

SUBPROCESS_RESTORE = """
import json, sys, tempfile, pathlib
sys.path.insert(0, {repo!r})
from gaworld.checkpoints import CheckpointManager
sys.path.insert(0, {tests!r})
from test_checkpoint_phase5 import MiniRuntime, deterministic_llm, capture_state

run_dir = pathlib.Path({run_dir!r})
mgr = CheckpointManager(run_dir=run_dir, run_id="run-a")
rt = MiniRuntime()
mgr.restore_checkpoint(rt, ref=None)
print(json.dumps(capture_state(rt)))
"""


class TestFreshProcessRestore:
    def test_restore_in_fresh_subprocess(self, tmp_path):
        """Checkpoints must survive process death — restore in a brand new
        interpreter."""
        rt = MiniRuntime()
        rt.run_day(deterministic_llm)
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=rt.completed_day)
        expected = capture_state(rt)

        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        code = SUBPROCESS_RESTORE.format(repo=repo, tests=tests_dir, run_dir=str(tmp_path))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout.strip().splitlines()[-1]) == expected


# ---------------------------------------------------------------------------
# Resume interface
# ---------------------------------------------------------------------------


class TestResumeInterface:
    def test_resume_from_checkpoint_ref_resolves(self, tmp_path):
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        ref = mgr.save_checkpoint(rt, completed_day=1)
        # the launcher-facing interface: resume_from_checkpoint=<ref>
        assert mgr.resolve_ref(f"{ref.run_id}:day_{ref.completed_day:04d}").completed_day == 1

    def test_runtime_config_override_distinguishable_from_state(self, tmp_path):
        """Restored simulation state and runtime configuration stay separate:
        an override after restore wins without mutating state fields."""
        rt = MiniRuntime()
        mgr = CheckpointManager(run_dir=tmp_path, run_id="run-a")
        mgr.save_checkpoint(rt, completed_day=1)
        fresh = MiniRuntime()
        mgr.restore_checkpoint(fresh, ref=None, config_overrides={"sim_days": 99})
        assert fresh.config["sim_days"] == 99, "override must apply"
        assert fresh.completed_day == 1, "state must not be affected by overrides"
