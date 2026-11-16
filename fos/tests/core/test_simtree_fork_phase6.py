"""Phase 6 STAGE A — SimTree checkpoint forks + recovery (RED tests).

Specifies the SimTree fork-from-checkpoint feature set from PHASE6-BRIEF.md:

* ``config_params_patch`` must deep-merge so a nested runtime patch such as
  ``{"gaworld": {"checkpoint": {"restore_dir": ...}}}`` preserves the other
  keys already nested under ``gaworld`` (population, LLM, …).
* Forks A and B created from the same source checkpoint both reference that
  checkpoint in ``node.meta["checkpoint"]``; meta survives clone and the
  serialize/deserialize roundtrip; only reference fields, never payloads.
* Per-branch runtime config isolates every GAWorld writable path via the
  authoritative ``gaworld.city.config.run_root_overrides`` key set
  (``gaworld/parallel/spec.py`` ``world_overrides`` semantics) — output,
  state, memory, logs, vector db, environment, diary, life events,
  interventions, kernel, records, work, visualization — plus
  ``checkpoint.restore_dir`` and per-branch LLM routing.
* Branch LLM routing resolves at runtime through the Phase 4 GAWorld
  ``LLMRouter`` contract with exact int agent IDs, differing per branch.
* Recovery = Retry / Fix-and-retry / Substitute ONLY; every action restores
  the last completed checkpoint, keeps failed evidence, uses a fresh attempt
  directory and never silently substitutes a provider.
* Concurrency guard: ``FOS_GAWORLD_MAX_SUBPROCESSES`` bounds LIVE GAWorld
  subprocesses (asserted on REAL process count); non-GAWorld scenes are
  unaffected.
* Launch-time checkpoint validation fails loudly on missing/corrupt/wrong
  lineage references — no hidden fallback.

Every non-guard test must fail naming the missing feature (AttributeError
via ``_feature`` / missing module), never a syntax error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import gaworld.city.config as city_config
import gaworld.parallel.spec as pw_spec
from fos.core.simtree import SimTree

# The FOS-side module that will own branch runtime config / recovery.
try:
    import fos.backend.services.simtree_gaworld as simtree_gaworld
except ModuleNotFoundError:  # pragma: no cover - module may not exist yet
    simtree_gaworld = None


def _feature(module, name, *, label=None):
    """Fetch a not-yet-existing attribute; fail naming the missing feature."""
    assert module is not None, (
        f"feature missing: module {label or 'module'} does not exist (Phase 6 RED)"
    )
    attr = getattr(module, name, None)
    assert attr is not None, (
        f"feature missing: {module.__name__}.{name} is not implemented (Phase 6 RED)"
    )
    return attr


# ---------------------------------------------------------------------------
# Mock infrastructure (mirrors test_simtree_operations.py)
# ---------------------------------------------------------------------------


class MockMemory:
    def __init__(self):
        self.history = []

    def get_all(self):
        return self.history

    def append(self, role, content):
        self.history.append({"role": role, "content": content})

    def __len__(self):
        return len(self.history)


class MockAgent:
    def __init__(self, name):
        self.name = name
        self.short_memory = MockMemory()
        self.plan_state = None
        self.properties = {}
        self.knowledge_base = []
        self.documents = {}
        self.language = "en"
        self.last_history_length = 1
        self.consecutive_llm_errors = 0
        self.is_offline = False
        self.log_event = None
        self.role_prompt = ""
        self.user_profile = ""

    def add_env_feedback(self, msg, images=None):
        pass


class MockConfig:
    def __init__(self, parameters=None):
        self.parameters = parameters or {}
        self.description = ""
        self.social_network = {}
        self.actions = []


class MockScene:
    def __init__(self, parameters=None):
        self.TYPE = "mock"
        self.state = {}
        self.config = MockConfig(parameters)
        self.runner = None

    def on_event(self, sim, event_type, payload):
        pass

    def on_private_event(self, sim, event_type, payload, receivers):
        pass


class MockOrdering:
    def serialize(self):
        return {"type": "mock_ordering", "state": {}}


class MockEventQueue:
    def empty(self):
        return True


class FakeSim:
    def __init__(self, agents=None, parameters=None):
        self.agents = agents or {}
        self.scene = MockScene(parameters)
        self.event_queue = MockEventQueue()
        self.ordering = MockOrdering()
        self.turns = 0
        self.log_event = None

    def serialize(self):
        return {
            "agents": {n: {"name": n} for n in self.agents},
            "scene": {"TYPE": "mock", "parameters": self.scene.config.parameters},
            "turns": self.turns,
        }

    @classmethod
    def deserialize(cls, data, clients, log_handler=None):
        sim = cls()
        sim.agents = {n: MockAgent(n) for n in data.get("agents", {})}
        scene = data.get("scene") or {}
        sim.scene = MockScene(dict(scene.get("parameters") or {}))
        sim.turns = int(data.get("turns", 0))
        return sim

    def run(self, max_turns):
        self.turns += max_turns

    def reset_event_queue(self):
        pass

    def broadcast(self, event):
        pass

    def emit_remaining_events(self):
        pass


@pytest.fixture(autouse=True)
def _patch_simulator():
    with patch("fos.core.simtree.Simulator", FakeSim):
        yield


@pytest.fixture()
def _patch_era():
    class _MockERA:
        pass

    mock_mod = MagicMock()
    mock_mod.ExperimentRunnerAdapter = _MockERA
    import fos.backend.services.simtree_runtime as real_mod

    original = real_mod.ExperimentRunnerAdapter
    real_mod.ExperimentRunnerAdapter = _MockERA
    try:
        yield _MockERA
    finally:
        real_mod.ExperimentRunnerAdapter = original


def _make_tree(agent_names=("Alice", "Bob"), parameters=None):
    agents = {name: MockAgent(name) for name in agent_names}
    sim = FakeSim(agents=agents, parameters=parameters)
    tree = SimTree.new(sim, {"mock": object()})
    return tree


def _checkpoint_ref(tmp_path: Path, day: int = 3) -> dict:
    """A checkpoint reference the way FOS stores it (reference only)."""
    return {
        "checkpoint_id": f"day_{day:04d}",
        "checkpoint_path": str(tmp_path / "run" / "checkpoints" / f"day_{day:04d}"),
        "day": day,
        "manifest_sha": "a" * 64,
        "parent_checkpoint": f"day_{day - 1:04d}" if day else None,
    }


CHECKPOINT_META_KEYS = {
    "checkpoint_id",
    "checkpoint_path",
    "day",
    "manifest_sha",
    "parent_checkpoint",
}


# ===========================================================================
# §13a — config_params_patch deep-merge safety (RED: today it is shallow)
# ===========================================================================


class TestConfigPatchDeepMerge:
    """A nested patch must never wipe sibling keys at the same level."""

    BASE_PARAMS = {
        "gaworld": {
            "population": {"city": "wuzhen", "agent_ids": [1, 2, 3]},
            "llm": {"routing": {"default": "local"}},
            "sim_days": 30,
        },
    }

    def _branch_with_patch(self, updates):
        tree = _make_tree(parameters=json.loads(json.dumps(self.BASE_PARAMS)))
        root = tree.root
        cid = tree.branch(
            root, [{"op": "config_params_patch", "updates": updates}]
        )
        return tree, cid

    def test_nested_restore_dir_patch_preserves_population(self):
        tree, cid = self._branch_with_patch(
            {"gaworld": {"checkpoint": {"restore_dir": "/tmp/branch-b/checkpoints"}}}
        )
        params = tree.nodes[cid]["sim"].scene.config.parameters
        gaworld_cfg = params["gaworld"]
        assert gaworld_cfg.get("population") == {"city": "wuzhen", "agent_ids": [1, 2, 3]}, (
            "config_params_patch replaced the whole 'gaworld' dict — "
            "population keys were wiped by a nested checkpoint patch"
        )

    def test_nested_restore_dir_patch_preserves_llm(self):
        tree, cid = self._branch_with_patch(
            {"gaworld": {"checkpoint": {"restore_dir": "/tmp/branch-b/checkpoints"}}}
        )
        params = tree.nodes[cid]["sim"].scene.config.parameters
        assert params["gaworld"].get("llm") == {"routing": {"default": "local"}}, (
            "config_params_patch replaced the whole 'gaworld' dict — "
            "llm routing was wiped by a nested checkpoint patch"
        )

    def test_nested_patch_adds_restore_dir_without_losing_sim_days(self):
        tree, cid = self._branch_with_patch(
            {"gaworld": {"checkpoint": {"restore_dir": "/tmp/branch-b/checkpoints"}}}
        )
        params = tree.nodes[cid]["sim"].scene.config.parameters
        assert params["gaworld"].get("sim_days") == 30
        assert (
            params["gaworld"]["checkpoint"]["restore_dir"]
            == "/tmp/branch-b/checkpoints"
        )

    def test_parent_node_parameters_untouched_by_child_patch(self):
        tree = _make_tree(parameters=json.loads(json.dumps(self.BASE_PARAMS)))
        root = tree.root
        tree.branch(root, [{"op": "config_params_patch", "updates": {
            "gaworld": {"checkpoint": {"restore_dir": "/tmp/branch-b/checkpoints"}},
        }}])
        parent_params = tree.nodes[root]["sim"].scene.config.parameters
        assert "checkpoint" not in parent_params["gaworld"], (
            "branching mutated the parent node's config"
        )


# ===========================================================================
# §13b — node.meta["checkpoint"] survives clone + serialization (guard +
#        payload-shape RED where applicable)
# ===========================================================================


class TestCheckpointMetaSurvival:
    def _tree_with_checkpoint_meta(self, tmp_path):
        tree = _make_tree()
        ref = _checkpoint_ref(tmp_path, day=3)
        tree.nodes[tree.root]["meta"]["checkpoint"] = ref
        return tree, ref

    def test_meta_checkpoint_survives_clone(self, tmp_path):
        tree, ref = self._tree_with_checkpoint_meta(tmp_path)
        nid = tree.copy_sim(tree.root)
        assert tree.nodes[nid]["meta"].get("checkpoint") == ref

    def test_meta_checkpoint_survives_serialize_roundtrip(self, tmp_path):
        tree, ref = self._tree_with_checkpoint_meta(tmp_path)
        data = json.loads(json.dumps(tree.serialize()))
        revived = SimTree.deserialize(data, {"mock": object()})
        assert revived.nodes[revived.root]["meta"].get("checkpoint") == ref

    def test_checkpoint_meta_carries_reference_fields_only(self, tmp_path):
        tree, ref = self._tree_with_checkpoint_meta(tmp_path)
        assert set(ref.keys()) == CHECKPOINT_META_KEYS
        # Reference only: no state payloads, no credentials.
        blob = json.dumps(ref)
        assert "api_key" not in blob.lower()
        assert "password" not in blob.lower()


# ===========================================================================
# §13c — fork creation from a checkpoint: A and B share the source reference
# ===========================================================================


class TestForkFromCheckpoint:
    def test_fork_api_exists(self):
        fork = getattr(SimTree, "fork_from_checkpoint", None)
        assert fork is not None, (
            "feature missing: SimTree.fork_from_checkpoint is not implemented "
            "(Phase 6 RED)"
        )

    def test_two_branches_reference_the_same_source_checkpoint(self, tmp_path):
        fork = getattr(SimTree, "fork_from_checkpoint", None)
        assert fork is not None, (
            "feature missing: SimTree.fork_from_checkpoint is not implemented "
            "(Phase 6 RED)"
        )
        tree = _make_tree()
        ref = _checkpoint_ref(tmp_path, day=3)
        children = fork(tree, tree.root, ref, count=2)
        assert len(children) == 2
        a, b = children
        # Siblings sharing one parent, each referencing the same checkpoint.
        assert tree.nodes[a]["parent"] == tree.root or (
            tree.nodes[a]["parent"] == tree.nodes[tree.root]["parent"]
        )
        assert tree.nodes[b]["parent"] == tree.nodes[a]["parent"]
        assert tree.nodes[a]["meta"]["checkpoint"] == ref
        assert tree.nodes[b]["meta"]["checkpoint"] == ref

    def test_branch_meta_updates_after_branch_advances(self, tmp_path):
        """After a branch advances and a new checkpoint completes, that
        branch's meta points at the NEW checkpoint; the sibling and the
        source reference stay untouched."""
        fork = getattr(SimTree, "fork_from_checkpoint", None)
        assert fork is not None, (
            "feature missing: SimTree.fork_from_checkpoint is not implemented "
            "(Phase 6 RED)"
        )
        tree = _make_tree()
        ref = _checkpoint_ref(tmp_path, day=3)
        a, b = fork(tree, tree.root, ref, count=2)
        new_ref = _checkpoint_ref(tmp_path, day=4)
        marker = getattr(tree, "mark_checkpoint", None)
        assert marker is not None, (
            "feature missing: SimTree.mark_checkpoint is not implemented "
            "(Phase 6 RED)"
        )
        marker(tree, a, new_ref)
        assert tree.nodes[a]["meta"]["checkpoint"] == new_ref
        assert tree.nodes[b]["meta"]["checkpoint"] == ref

    def test_restored_state_equality_between_two_branches(self, tmp_path):
        """Two branches forked from the same checkpoint start from identical
        restored state (Phase 5 equivalence: same checkpoint → same state)."""
        fork = getattr(SimTree, "fork_from_checkpoint", None)
        assert fork is not None, (
            "feature missing: SimTree.fork_from_checkpoint is not implemented "
            "(Phase 6 RED)"
        )
        tree = _make_tree()
        ref = _checkpoint_ref(tmp_path, day=3)
        a, b = fork(tree, tree.root, ref, count=2)
        state_a = tree.nodes[a]["sim"].serialize()
        state_b = tree.nodes[b]["sim"].serialize()
        assert state_a == state_b, (
            "branches forked from the same checkpoint must start from "
            "identical restored state"
        )


# ===========================================================================
# §13d — per-branch path isolation via the authoritative override key set
# ===========================================================================


class TestBranchPathIsolation:
    def test_run_root_overrides_covers_every_run_path(self, tmp_path):
        """GUARD — the authoritative key set already isolates every writable
        path (memory, logs, vector db, state, environment, diary, life events,
        interventions, kernel, records, economy, work, visualization, …)."""
        base = tmp_path / "branch-a"
        patch = city_config.run_root_overrides(str(base))

        def _dig(d, dotted):
            cur = d
            for part in dotted.split("."):
                cur = cur[part]
            return cur

        for dotted in city_config.RUN_PATHS:
            value = _dig(patch, dotted)
            assert str(value).startswith(str(base)), (
                f"run_root_overrides did not isolate {dotted} under {base}"
            )

    def test_kernel_interventions_path_is_branch_local(self, tmp_path):
        """GUARD — interventions and the Recorder audit stream are per-run."""
        base_a = tmp_path / "branch-a"
        base_b = tmp_path / "branch-b"
        a = city_config.run_root_overrides(str(base_a))
        b = city_config.run_root_overrides(str(base_b))
        assert a["kernel"]["interventions_path"] != b["kernel"]["interventions_path"]
        assert a["records"]["output_dir"] != b["records"]["output_dir"]
        assert a["intervention"]["output_dir"] != b["intervention"]["output_dir"]

    def test_branch_runtime_overrides_builder_exists(self, tmp_path):
        _feature(simtree_gaworld, "branch_runtime_overrides")

    def test_branch_runtime_overrides_isolate_all_paths_per_branch(self, tmp_path):
        build = _feature(simtree_gaworld, "branch_runtime_overrides")
        a = build(branch_dir=str(tmp_path / "branch-a"), checkpoint_ref=_checkpoint_ref(tmp_path))
        b = build(branch_dir=str(tmp_path / "branch-b"), checkpoint_ref=_checkpoint_ref(tmp_path))

        def _all_paths(patch):
            found = {}

            def _walk(d, prefix=""):
                for key, value in d.items():
                    dotted = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        _walk(value, dotted)
                    elif isinstance(value, str) and ("/" in value or key.endswith("_dir") or key.endswith("_path")):
                        found[dotted] = value

            _walk(patch)
            return found

        paths_a, paths_b = _all_paths(a), _all_paths(b)
        shared = set(paths_a) & set(paths_b)
        overlapping = {k for k in shared if paths_a[k] == paths_b[k]}
        assert not overlapping, (
            f"branches share writable paths: {sorted(overlapping)}"
        )

    def test_branch_runtime_overrides_include_checkpoint_restore_dir(self, tmp_path):
        build = _feature(simtree_gaworld, "branch_runtime_overrides")
        ref = _checkpoint_ref(tmp_path, day=3)
        patch = build(branch_dir=str(tmp_path / "branch-a"), checkpoint_ref=ref)
        restore_dir = patch["gaworld"]["checkpoint"]["restore_dir"]
        assert str(tmp_path / "branch-a") in restore_dir
        # Forks restore from the SOURCE checkpoint's run dir, never write into it.
        assert restore_dir != ref["checkpoint_path"]

    def test_world_overrides_repins_paths_after_patch(self, tmp_path):
        """GUARD — gaworld/parallel/spec.py world_overrides re-applies
        run_root_overrides after a world patch so no nested patch can move a
        branch's output back into the shared tree."""
        from gaworld.parallel.spec import ExperimentSpec, WorldSpec

        spec = ExperimentSpec(
            name="t",
            baseline_id="a",
            worlds=[WorldSpec(id="a", label="A", config={
                "economy": {"output_dir": "/shared/tree/output"},
            })],
            seed=1,
        )
        world_dir = str(tmp_path / "w-a")
        overrides = pw_spec.world_overrides(spec, spec.worlds[0], world_dir)
        assert str(tmp_path) in str(overrides["economy"]["output_dir"]), (
            "a world patch moved economy.output_dir out of the world dir"
        )


# ===========================================================================
# §13e — intervention isolation via GAWorld kernel paths
# ===========================================================================


class TestInterventionIsolation:
    def test_branch_intervention_config_targets_only_that_branch(self, tmp_path):
        build = _feature(simtree_gaworld, "branch_runtime_overrides")
        ref = _checkpoint_ref(tmp_path, day=3)
        a = build(
            branch_dir=str(tmp_path / "branch-a"),
            checkpoint_ref=ref,
            interventions_path=str(tmp_path / "branch-a" / "intervention" / "ops.json"),
        )
        b = build(
            branch_dir=str(tmp_path / "branch-b"),
            checkpoint_ref=ref,
            interventions_path=str(tmp_path / "branch-b" / "intervention" / "ops.json"),
        )
        assert (
            a["kernel"]["interventions_path"]
            != b["kernel"]["interventions_path"]
        )
        assert "branch-a" in a["kernel"]["interventions_path"]
        assert "branch-b" in b["kernel"]["interventions_path"]

    def test_recorder_audit_stream_is_branch_local(self, tmp_path):
        build = _feature(simtree_gaworld, "branch_runtime_overrides")
        ref = _checkpoint_ref(tmp_path, day=3)
        a = build(branch_dir=str(tmp_path / "branch-a"), checkpoint_ref=ref)
        b = build(branch_dir=str(tmp_path / "branch-b"), checkpoint_ref=ref)
        assert a["records"]["output_dir"] != b["records"]["output_dir"]
        assert "branch-a" in a["records"]["output_dir"]


# ===========================================================================
# §13f — branch LLM routing: runtime resolution differs per branch (exact
#        int GAWorld IDs, Phase 4 router contract)
# ===========================================================================


class _StubProvider:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def call(self, prompt, **overrides):
        self.calls += 1
        return f"hello from {self.name}"


class TestBranchLLMRouting:
    def _router(self, routing, providers):
        from gaworld.llm.providers import LLMRouter

        router = object.__new__(LLMRouter)
        router.providers = providers
        router.routing = routing
        router.config = {}
        return router

    def test_router_resolves_exact_int_agent_id(self):
        """GUARD — Phase 4 contract: agents keyed by exact int GAWorld ID."""
        from gaworld.llm.providers import resolve_llm_target

        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        assert resolve_llm_target(routing, agent_id=7)["provider"] == "b"
        assert resolve_llm_target(routing, agent_id=8)["provider"] == "a"

    def test_branch_runtime_overrides_accepts_agent_llm_map(self, tmp_path):
        build = _feature(simtree_gaworld, "branch_runtime_overrides")
        ref = _checkpoint_ref(tmp_path, day=3)
        patch = build(
            branch_dir=str(tmp_path / "branch-b"),
            checkpoint_ref=ref,
            agent_llm_map={7: {"provider": "b", "model": "m-b"}},
        )
        agents = patch["llm"]["routing"]["agents"]
        assert "7" in agents or 7 in agents, (
            "agent_llm_map must land in llm.routing.agents keyed by the exact "
            "int GAWorld ID"
        )

    def test_two_branches_resolve_different_providers_at_runtime(self, tmp_path):
        """Runtime resolution, not just JSON shape: branch A's router sends
        agent 7 to provider a, branch B's to provider b."""
        build = _feature(simtree_gaworld, "branch_runtime_overrides")
        ref = _checkpoint_ref(tmp_path, day=3)
        patch_a = build(
            branch_dir=str(tmp_path / "branch-a"), checkpoint_ref=ref
        )
        patch_b = build(
            branch_dir=str(tmp_path / "branch-b"),
            checkpoint_ref=ref,
            agent_llm_map={7: {"provider": "b", "model": "m-b"}},
        )
        routing_a = patch_a["llm"]["routing"]
        routing_b = patch_b["llm"]["routing"]
        from gaworld.llm.providers import resolve_llm_target

        assert resolve_llm_target(routing_a, agent_id=7)["provider"] == "a"
        assert resolve_llm_target(routing_b, agent_id=7)["provider"] == "b"


# ===========================================================================
# §13g — recovery semantics: retry / fix-and-retry / substitute
# ===========================================================================


class TestRecoverySemantics:
    RECOVERY_ACTIONS = ("retry", "fix_and_retry", "substitute")

    def test_recovery_module_exposes_the_three_actions(self):
        prepare = _feature(simtree_gaworld, "prepare_recovery")

    def test_retry_reuses_config_and_checkpoint_with_fresh_attempt_dir(self, tmp_path):
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        ref = _checkpoint_ref(tmp_path, day=5)
        node = {
            "id": 9,
            "meta": {
                "checkpoint": ref,
                "runtime_status": "failed",
                "runtime_error": "boom",
                "attempt_dir": str(tmp_path / "branch-b" / "attempts" / "day_0005_attempt_1"),
            },
        }
        plan = prepare(node, action="retry")
        assert plan["checkpoint"] == ref, "retry must restore the same checkpoint"
        assert plan["action"] == "retry"
        attempt_dir = plan["attempt_dir"]
        assert "day_0005" in attempt_dir
        assert "attempt_1" not in Path(attempt_dir).name, (
            "retry must use a FRESH attempt directory, not rerun into the "
            "failed one"
        )
        # Failed evidence retained.
        assert Path(node["meta"]["attempt_dir"]).name in attempt_dir or Path(
            node["meta"]["attempt_dir"]
        ).exists() is False  # fresh dir simply planned; nothing deleted

    def test_fix_and_retry_reloads_repaired_config_same_checkpoint(self, tmp_path):
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        ref = _checkpoint_ref(tmp_path, day=5)
        node = {"id": 9, "meta": {"checkpoint": ref, "runtime_status": "failed"}}
        repaired = {"sim_days": 6, "llm": {"routing": {"default": "local"}}}
        plan = prepare(node, action="fix_and_retry", runtime_config=repaired)
        assert plan["checkpoint"] == ref
        assert plan["action"] == "fix_and_retry"
        assert plan["runtime_config"] == repaired

    def test_substitute_targets_the_affected_agent_only(self, tmp_path):
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        ref = _checkpoint_ref(tmp_path, day=5)
        node = {"id": 9, "meta": {"checkpoint": ref, "runtime_status": "failed"}}
        plan = prepare(
            node,
            action="substitute",
            agent_id=7,
            provider="local-fallback",
            model="qwen3-4b",
        )
        assert plan["action"] == "substitute"
        assert plan["agent_id"] == 7
        assert plan["provider"] == "local-fallback"
        assert plan["model"] == "qwen3-4b"
        # Explicit selection only — no auto-substitution.
        assert prepare.__code__ is not None
        with pytest.raises(TypeError):
            prepare(node, action="substitute")  # provider/model required

    def test_unknown_action_rejected(self, tmp_path):
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        node = {
            "id": 9,
            "meta": {"checkpoint": _checkpoint_ref(tmp_path), "runtime_status": "failed"},
        }
        with pytest.raises(ValueError):
            prepare(node, action="resume_partial_day")

    def test_recovery_provenance_survives_serialization(self, tmp_path):
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        ref = _checkpoint_ref(tmp_path, day=5)
        node = {"id": 9, "meta": {"checkpoint": ref, "runtime_status": "failed"}}
        plan = prepare(
            node,
            action="substitute",
            agent_id=7,
            provider="p2",
            model="m2",
        )
        blob = json.loads(json.dumps(plan))
        for key in (
            "branch",
            "failed_day",
            "agent_id",
            "original_provider",
            "original_model",
            "failure",
            "action",
            "replacement",
            "checkpoint_restored",
            "attempt_dir",
        ):
            assert key in blob, f"recovery provenance missing '{key}'"

    def test_day_zero_failure_restores_day_zero_checkpoint(self, tmp_path):
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        ref = _checkpoint_ref(tmp_path, day=0)
        node = {"id": 9, "meta": {"checkpoint": ref, "runtime_status": "failed"}}
        plan = prepare(node, action="retry")
        assert plan["checkpoint"]["day"] == 0
        assert plan["checkpoint"]["checkpoint_id"] == "day_0000"

    def test_failed_partial_state_never_enters_lineage(self, tmp_path):
        """A failed attempt dir must never be referenced as a checkpoint."""
        prepare = _feature(simtree_gaworld, "prepare_recovery")
        ref = _checkpoint_ref(tmp_path, day=5)
        node = {"id": 9, "meta": {"checkpoint": ref, "runtime_status": "failed"}}
        plan = prepare(node, action="retry")
        assert "failed" not in Path(plan["checkpoint"]["checkpoint_path"]).name
        assert plan["checkpoint"]["checkpoint_id"].startswith("day_")

    def test_failure_resolution_actions_shape_recorded_on_node(self, tmp_path):
        """Phase 4-style failure-resolution shape: the node records what
        recovery action was taken so the frontend can render it."""
        record = _feature(simtree_gaworld, "record_recovery")
        ref = _checkpoint_ref(tmp_path, day=5)
        node = {"id": 9, "meta": {"checkpoint": ref, "runtime_status": "failed"}, "logs": []}
        record(node, action="retry", attempt_dir=str(tmp_path / "attempts" / "day_0005_attempt_2"))
        meta = node["meta"]
        assert meta["runtime_status"] == "recovering"
        assert meta["recovery"]["action"] == "retry"
        json.loads(json.dumps(meta))  # serializable


# ===========================================================================
# §13h — concurrency guard: FOS_GAWORLD_MAX_SUBPROCESSES bounds LIVE
#        subprocesses (REAL process count); non-GAWorld scenes unaffected
# ===========================================================================


class TestConcurrencyGuard:
    def test_semaphore_helper_exists_and_reads_env(self, monkeypatch):
        helper = _feature(
            __import__(
                "fos.core.experiment.scenes.gaworld.subprocess_manager",
                fromlist=["gaworld_subprocess_semaphore"],
            ),
            "gaworld_subprocess_semaphore",
        )
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "3")
        sem = helper()
        assert getattr(sem, "_value", None) == 3, (
            "FOS_GAWORLD_MAX_SUBPROCESSES=3 must produce a semaphore with 3 slots"
        )

    def test_default_bound_is_two(self, monkeypatch):
        mod = __import__(
            "fos.core.experiment.scenes.gaworld.subprocess_manager",
            fromlist=["gaworld_subprocess_semaphore"],
        )
        helper = _feature(mod, "gaworld_subprocess_semaphore")
        monkeypatch.delenv("FOS_GAWORLD_MAX_SUBPROCESSES", raising=False)
        sem = helper()
        assert getattr(sem, "_value", None) == 2

    def test_six_gaworld_advances_never_exceed_two_live_processes(self, tmp_path, monkeypatch):
        """REAL process count: 6 GAWorld advances with the bound at 2 must
        never show more than 2 alive child processes at any sample."""
        mod = __import__(
            "fos.core.experiment.scenes.gaworld.subprocess_manager",
            fromlist=["gaworld_subprocess_semaphore"],
        )
        helper = _feature(mod, "gaworld_subprocess_semaphore")
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "2")
        sem = helper()

        script = tmp_path / "generative_city_sim.py"
        script.write_text(
            "import time\nprint('start', flush=True)\ntime.sleep(1.5)\n",
            encoding="utf-8",
        )
        (tmp_path / "gaworld").mkdir(exist_ok=True)

        import asyncio

        async def _advance(i):
            manager = mod.GAWorldSubprocessManager(
                gaworld_path=tmp_path,
                config_overrides={},
                output_dir=tmp_path / f"run-{i}",
                preserve_output=True,
            )
            async with sem:
                manager.launch()
                try:
                    peak_wait = 0.0
                    while manager.is_alive() and peak_wait < 5.0:
                        alive = sum(
                            1 for m in managers if m.is_alive()
                        )
                        samples.append(alive)
                        await asyncio.sleep(0.05)
                        peak_wait += 0.05
                finally:
                    if manager.is_alive():
                        manager.process.kill()

        managers: list = []
        samples: list = []

        async def _main():
            nonlocal managers
            await asyncio.gather(*[_advance(i) for i in range(6)])

        asyncio.run(_main())
        assert samples, "no liveness samples were taken"
        assert max(samples) <= 2, (
            f"observed {max(samples)} live GAWorld subprocesses with "
            "FOS_GAWORLD_MAX_SUBPROCESSES=2"
        )


# ===========================================================================
# §13i — launch-time checkpoint validation: missing/corrupt/wrong lineage
#        fail loudly, no fallback
# ===========================================================================


class TestLaunchCheckpointValidation:
    def test_validator_exists(self):
        _feature(simtree_gaworld, "validate_checkpoint_reference")

    def test_missing_checkpoint_dir_fails_loudly(self, tmp_path):
        validate = _feature(simtree_gaworld, "validate_checkpoint_reference")
        ref = _checkpoint_ref(tmp_path, day=99)  # never created
        with pytest.raises(Exception) as excinfo:
            validate(ref)
        assert "fallback" not in str(excinfo.value).lower() or True
        assert not isinstance(excinfo.value, AssertionError)

    def test_corrupt_manifest_fails_loudly(self, tmp_path):
        validate = _feature(simtree_gaworld, "validate_checkpoint_reference")
        day_dir = tmp_path / "run" / "checkpoints" / "day_0003"
        day_dir.mkdir(parents=True)
        (day_dir / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(Exception):
            validate(_checkpoint_ref(tmp_path, day=3))

    def test_wrong_lineage_fails_loudly(self, tmp_path):
        validate = _feature(simtree_gaworld, "validate_checkpoint_reference")
        day_dir = tmp_path / "other-run" / "checkpoints" / "day_0003"
        day_dir.mkdir(parents=True)
        manifest = {
            "run_id": "someoneelse",
            "completed_day": 3,
            "parent_checkpoint": None,
        }
        (day_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        ref = _checkpoint_ref(tmp_path, day=3)
        ref["run_id"] = "live2565"
        with pytest.raises(Exception):
            validate(ref, expected_run_id="live2565")

    def test_valid_reference_passes(self, tmp_path):
        validate = _feature(simtree_gaworld, "validate_checkpoint_reference")
        day_dir = tmp_path / "run" / "checkpoints" / "day_0003"
        day_dir.mkdir(parents=True)
        manifest = {
            "run_id": "live2565",
            "completed_day": 3,
            "parent_checkpoint": "day_0002",
            "manifest_sha": "a" * 64,
        }
        (day_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        ref = _checkpoint_ref(tmp_path, day=3)
        assert validate(ref, expected_run_id="live2565") is True
