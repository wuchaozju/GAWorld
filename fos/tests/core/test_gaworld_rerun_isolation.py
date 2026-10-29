"""GAWorld rerun runtime isolation + intervention targeting — TDD RED (task 2832).

Specifies SPEC-gaworld-isolation-interventions.md (Goals A + B) and the
findings of RESULT-2830 (audit, authoritative file:line references):

* Rerun dir isolation: a variant rerun gets a fresh attempt node AND a fresh
  ``branch_dir`` derived via ``branch_runtime_overrides`` — run output,
  state history, checkpoint output and the kernel intervention queue all
  live under that node-owned directory. A marker written only into run 1's
  directory must never appear in run 2's (REAL filesystem checks, tmp dirs —
  not mocked away). RED today: no launch/rerun path derives a branch_dir
  (``branch_runtime_overrides`` has zero production callers).
* Sibling kernel-queue isolation: B and C get DISTINCT
  ``kernel.interventions_path`` values; an intervention X queued for B is
  never drained by C. RED today: every FOS-launched GAWorld subprocess runs
  with cwd = the GAWorld repo root and no override, so all nodes share one
  ``output/kernel/interventions.json``.
* ``branch_runtime_overrides`` is applied by the rerun/launch paths as one
  ``config_params_patch`` op (deep-merge). RED today: zero production
  callers.
* Checkpoint-fork ``interventions_text``: stored provenance on B only, and
  materialized into B's OWN kernel queue at launch; C stays clean. RED
  today: ``meta["pending_interventions"]`` is never read by anything (dead
  code).
* Stale-node guard: ``_resolve_simulator_node`` must REJECT a missing
  node id (loud failure) instead of silently falling back to the newest
  leaf — an intervention aimed at a deleted/stale node must never land on
  a different node.
* Rerun intervention semantics: variant-spec interventions reapply exactly
  once per attempt; one-off manual runtime interventions do not propagate
  into the rerun; the previous attempt is immutable.
* State isolation: a deterministic intervention op on B leaves C (and the
  base A) untouched on the targeted field.

Mock LLM/runtime throughout; FakeSim mirrors
tests/core/test_simtree_ownership.py. Non-guard tests must fail because the
ISOLATION behaviour is missing (missing meta keys / missing feature),
never because of a syntax error.

PYTHONPATH note (RESULT-2830): ``branch_runtime_overrides`` imports
``gaworld.worldrun.config`` lazily. The GAWorld repo must be importable —
this file adds the worktree sibling ``gaworld/`` to sys.path if needed.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fos.core.simtree import SimTree

# ---------------------------------------------------------------------------
# PYTHONPATH: make the sibling GAWorld repo importable (lazy import inside
# branch_runtime_overrides). The worktree root (parents[3] of this file:
# fos/tests/core/x.py → worktree root) contains gaworld/.
# ---------------------------------------------------------------------------
_GAWORLD_ROOT = Path(__file__).resolve().parents[3] / "gaworld"
try:  # already importable (installed / GAWORLD on PYTHONPATH)?
    import gaworld.city.config as _city_config  # noqa: F401
except ImportError:  # pragma: no cover - depends on environment
    if _GAWORLD_ROOT.exists():
        sys.path.insert(0, str(_GAWORLD_ROOT.parent))
    import gaworld.city.config as _city_config  # noqa: F401


# ---------------------------------------------------------------------------
# Mock infrastructure (mirrors tests/core/test_simtree_ownership.py)
# ---------------------------------------------------------------------------


class MockMemory:
    def __init__(self):
        self.history = []

    def get_all(self):
        return self.history

    def append(self, role, content):
        self.history.append({"role": "role", "content": content})

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
    def __init__(self):
        self.parameters = {}
        self.description = ""
        self.social_network = {}
        self.actions = []


class MockScene:
    TYPE = "mock"

    def __init__(self):
        self.state = {}
        self.config = MockConfig()
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
    def __init__(self, agents=None):
        self.agents = agents or {}
        self.scene = MockScene()
        self.event_queue = MockEventQueue()
        self.ordering = MockOrdering()
        self.turns = 0
        self.log_event = None

    def serialize(self):
        return {
            "agents": {n: {"name": n} for n in self.agents},
            "scene": {"TYPE": "mock"},
            "turns": self.turns,
        }

    @classmethod
    def deserialize(cls, data, clients, log_handler=None):
        sim = cls()
        sim.agents = {n: MockAgent(n) for n in data.get("agents", {})}
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


def _make_tree(agent_names=("Alice", "Bob")):
    sim = FakeSim(agents={name: MockAgent(name) for name in agent_names})
    return SimTree.new(sim, {"mock": object()})


def _feature(module, name, *, label=None):
    """Fetch a not-yet-existing attribute; fail naming the missing feature."""
    attr = getattr(module, name, None)
    assert attr is not None, (
        f"feature missing: {module.__name__}.{name} is not implemented "
        f"(task 2832 RED{', ' + label if label else ''})"
    )
    return attr


# ---------------------------------------------------------------------------
# Experiment rerun harness (mirrors TestExperimentRerunOwnership)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, exp, run, sim_record):
        self._exp = exp
        self._run = run
        self._sim_record = sim_record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt):
        return _FakeResult(self._exp)

    async def get(self, model, key):
        from fos.backend.models.experiment import Experiment, ExperimentRun
        from fos.backend.models.simulation import Simulation

        if model is ExperimentRun:
            return self._run
        if model is Simulation:
            return self._sim_record
        if model is Experiment:
            return self._exp
        return None


def _variant_op_x():
    """A deterministic variant-spec intervention op (config_params_patch)."""
    return {
        "op": "config_params_patch",
        "updates": {"economy": {"initial_money": 4242}},
    }


class _RerunHarness:
    def __init__(self, tmp_path, ops=None):
        from fos.backend.services import experiment_runner as er

        self.er = er
        self.runs_root = tmp_path / "runs"
        self.runs_root.mkdir()
        # The runner derives branch dirs under its configured runs root.
        monkeypatch_dir = getattr(er, "GAWORLD_RUNS_ROOT", None)
        self.tree = _make_tree()
        self.ops = ops if ops is not None else [_variant_op_x()]

    def run_once(self, monkeypatch, run_id: int):
        er = self.er
        exp = SimpleNamespace(
            id="exp-1",
            name="exp",
            base_node=0,
            variants=[SimpleNamespace(id=1, name="v1", ops=self.ops, node_id=None)],
        )
        run = SimpleNamespace(id=run_id, status=None, result_meta=None, task_id=None)
        sim_record = SimpleNamespace(latest_state=None)
        record = SimpleNamespace(tree=self.tree, running=set())

        @contextlib.asynccontextmanager
        async def fake_session():
            yield _FakeSession(exp, run, sim_record)

        monkeypatch.setattr(er, "get_session", fake_session)
        monkeypatch.setattr(er, "SIM_TREE_REGISTRY", {"SIM": record})
        monkeypatch.setattr(er, "RUNTIME_TASKS", MagicMock())
        monkeypatch.setattr(er, "_USE_CELERY_EXPERIMENTS", False)
        import asyncio

        asyncio.run(er._run_experiment_worker("SIM", "exp-1", run_id, turns=2))
        return run

    def attempt_nodes(self, run_id: int):
        return [
            nid
            for nid, n in self.tree.nodes.items()
            if n["meta"].get("run_id") == run_id
            and n["meta"].get("variant_id") == 1
        ]


# ===================================================================
# Group 1 — Rerun dir isolation (RED): fresh node AND fresh dirs
# ===================================================================


class TestRerunDirIsolation:
    def test_rerun_node_meta_carries_branch_dir_provenance(self, tmp_path):
        """Each attempt node's meta stamps its own branch/run dir and
        intervention queue path (spec Goal A: runtime provenance)."""
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            nodes1 = h.attempt_nodes(1)
            assert nodes1, "run 1 must create an attempt node"
            meta1 = h.tree.nodes[nodes1[0]]["meta"]
            assert meta1.get("branch_dir"), (
                "attempt node meta must stamp branch_dir — RED: no rerun path "
                "derives a branch dir (branch_runtime_overrides has no callers)"
            )
            assert meta1.get("interventions_path"), (
                "attempt node meta must stamp its kernel interventions_path"
            )
            assert (meta1.get("gaworld") or {}).get("run_dir"), (
                "attempt node meta must stamp meta.gaworld.run_dir so "
                "compare_branches can resolve the run"
            )

            h.run_once(monkeypatch, run_id=2)
            nodes2 = h.attempt_nodes(2)
            assert nodes2 and nodes2[0] not in nodes1
            meta2 = h.tree.nodes[nodes2[0]]["meta"]
            assert meta2["branch_dir"] != meta1["branch_dir"], (
                "a rerun must get a FRESH branch_dir, never reuse run 1's"
            )
            assert meta2["interventions_path"] != meta1["interventions_path"]
        finally:
            monkeypatch.undo()

    def test_rerun_paths_are_fresh_per_attempt(self, tmp_path):
        """run_dir / checkpoint-output / state-history / interventions paths
        of run 2 differ from run 1's — REAL path strings, per attempt."""
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            h.run_once(monkeypatch, run_id=2)
            meta1 = h.tree.nodes[h.attempt_nodes(1)[0]]["meta"]
            meta2 = h.tree.nodes[h.attempt_nodes(2)[0]]["meta"]
            b1 = Path(meta1["branch_dir"])
            b2 = Path(meta2["branch_dir"])
            assert b1 != b2
            # every runtime sub-path lives under its own branch dir
            assert meta1["interventions_path"].startswith(str(b1))
            assert meta2["interventions_path"].startswith(str(b2))
            assert meta2["interventions_path"] != meta1["interventions_path"]
            checkpoint_dir_1 = (meta1.get("gaworld") or {}).get("checkpoint_dir") or str(
                b1 / "checkpoints"
            )
            checkpoint_dir_2 = (meta2.get("gaworld") or {}).get("checkpoint_dir") or str(
                b2 / "checkpoints"
            )
            assert checkpoint_dir_1 != checkpoint_dir_2
            state_1 = (meta1.get("gaworld") or {}).get("state_dir") or str(
                b1 / "state"
            )
            state_2 = (meta2.get("gaworld") or {}).get("state_dir") or str(
                b2 / "state"
            )
            assert state_1 != state_2
        finally:
            monkeypatch.undo()

    def test_marker_only_b1_in_run1_dir_absent_from_run2(self, tmp_path):
        """REAL filesystem isolation: a marker written into run 1's branch
        dir never appears in run 2's (not mocked away)."""
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            meta1 = h.tree.nodes[h.attempt_nodes(1)[0]]["meta"]
            b1 = Path(meta1["branch_dir"])
            (b1 / "state").mkdir(parents=True, exist_ok=True)
            (b1 / "state" / "marker.txt").write_text("ONLY_B1")

            h.run_once(monkeypatch, run_id=2)
            meta2 = h.tree.nodes[h.attempt_nodes(2)[0]]["meta"]
            b2 = Path(meta2["branch_dir"])
            assert b1 != b2
            assert (b1 / "state" / "marker.txt").read_text() == "ONLY_B1"
            assert not (b2 / "state" / "marker.txt").exists(), (
                "run 1's marker leaked into run 2's isolated branch dir"
            )
            # and the marker never lands anywhere under run 2's root
            leaked = [p for p in b2.rglob("marker.txt")]
            assert not leaked, f"ONLY_B1 marker leaked into run2: {leaked}"
        finally:
            monkeypatch.undo()


# ===================================================================
# Group 2 — Sibling kernel-queue isolation (RED): B and C queues differ
# ===================================================================


class TestSiblingKernelQueueIsolation:
    def _two_variant_harness(self, tmp_path):
        from fos.backend.services import experiment_runner as er

        exp = SimpleNamespace(
            id="exp-1",
            name="exp",
            base_node=0,
            variants=[
                SimpleNamespace(id=1, name="b", ops=[], node_id=None),
                SimpleNamespace(id=2, name="c", ops=[], node_id=None),
            ],
        )
        run = SimpleNamespace(id=1, status=None, result_meta=None, task_id=None)
        sim_record = SimpleNamespace(latest_state=None)
        tree = _make_tree()
        record = SimpleNamespace(tree=tree, running=set())

        @contextlib.asynccontextmanager
        async def fake_session():
            yield _FakeSession(exp, run, sim_record)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(er, "get_session", fake_session)
        monkeypatch.setattr(er, "SIM_TREE_REGISTRY", {"SIM": record})
        monkeypatch.setattr(er, "RUNTIME_TASKS", MagicMock())
        monkeypatch.setattr(er, "_USE_CELERY_EXPERIMENTS", False)
        import asyncio

        asyncio.run(er._run_experiment_worker("SIM", "exp-1", 1, turns=2))
        return tree, monkeypatch

    def test_siblings_get_distinct_interventions_paths(self, tmp_path):
        """B and C must resolve to distinct kernel queue files (audit §1.1:
        today every node shares the repo-root default queue)."""
        tree, monkeypatch = self._two_variant_harness(tmp_path)
        try:
            metas = [
                tree.nodes[nid]["meta"]
                for nid in tree.nodes
                if tree.nodes[nid]["meta"].get("variant_id") in (1, 2)
            ]
            paths = [m.get("interventions_path") for m in metas]
            assert all(paths), (
                "every sibling node must stamp its own interventions_path — "
                "RED: shared repo-root default (subprocess cwd = gaworld root)"
            )
            assert paths[0] != paths[1], "B and C share one intervention queue"
        finally:
            monkeypatch.undo()

    def test_x_queued_for_b_is_not_drained_by_c(self, tmp_path):
        """REAL queue files: enqueue X into B's queue; C's queue (and its
        drain) never sees X."""
        tree, monkeypatch = self._two_variant_harness(tmp_path)
        try:
            metas = {
                tree.nodes[nid]["meta"].get("variant_id"): tree.nodes[nid]["meta"]
                for nid in tree.nodes
                if tree.nodes[nid]["meta"].get("variant_id") in (1, 2)
            }
            path_b = Path(metas[1]["interventions_path"])
            path_c = Path(metas[2]["interventions_path"])
            path_b.parent.mkdir(parents=True, exist_ok=True)
            entry = {"id": "x-1", "op": "set_agent_state", "payload": {"agent_id": 17}}
            path_b.write_text(json.dumps({"pending": [entry], "applied": []}))
            # C's drain reads C's own queue file only.
            drained_c = (
                json.loads(path_c.read_text())["pending"] if path_c.exists() else []
            )
            assert drained_c == [], "C drained an intervention queued for B"
            assert not path_c.exists() or json.loads(path_c.read_text())[
                "pending"
            ] == []
        finally:
            monkeypatch.undo()

    def test_scene_default_output_overrides_are_kernel_isolated(self, tmp_path):
        """Defense in depth (RESULT-2830 plan #4): the scene's default
        override builder pins kernel.interventions_path + records.output_dir
        under the launch output_dir, so even the default path is isolated."""
        from fos.core.experiment.scenes.gaworld.scene import _build_output_overrides

        out_b = tmp_path / "launch-b"
        out_c = tmp_path / "launch-c"
        ov_b = _build_output_overrides(out_b)
        ov_c = _build_output_overrides(out_c)
        assert "kernel" in ov_b and ov_b["kernel"].get("interventions_path"), (
            "_build_output_overrides must pin kernel.interventions_path — RED: "
            "missing key means the subprocess drains the shared repo-root queue"
        )
        assert (
            ov_b["kernel"]["interventions_path"] != ov_c["kernel"]["interventions_path"]
        )
        assert str(out_b) in ov_b["kernel"]["interventions_path"]
        assert "records" in ov_b and ov_b["records"].get("output_dir"), (
            "_build_output_overrides must pin records.output_dir"
        )
        assert ov_b["records"]["output_dir"] != ov_c["records"]["output_dir"]


# ===================================================================
# Group 3 — branch_runtime_overrides applied by the rerun path (RED)
# ===================================================================


class TestBranchRuntimeOverridesApplied:
    def test_rerun_attempt_config_carries_isolated_runtime_patch(self, tmp_path):
        """The rerun path must inject the branch_runtime_overrides patch as a
        config_params_patch op — the attempt node's scene config ends up with
        kernel.interventions_path + run root under the node's own branch dir
        (RED: zero production callers of branch_runtime_overrides)."""
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            node = h.tree.nodes[h.attempt_nodes(1)[0]]
            params = node["sim"].scene.config.parameters
            assert params.get("kernel", {}).get("interventions_path"), (
                "rerun attempt config must carry kernel.interventions_path from "
                "branch_runtime_overrides — RED: no launch/rerun path applies it"
            )
            assert params.get("run_output_dir"), (
                "rerun attempt config must re-pin the GAWorld run root"
            )
            meta_branch = node["meta"].get("branch_dir")
            assert meta_branch and meta_branch in str(params["run_output_dir"]), (
                "the re-pinned run root must live under the node's branch_dir"
            )
        finally:
            monkeypatch.undo()

    def test_sibling_attempt_configs_do_not_share_paths(self, tmp_path):
        tree, monkeypatch = TestSiblingKernelQueueIsolation._two_variant_harness(
            self, tmp_path
        )
        try:
            nodes = [
                tree.nodes[nid]
                for nid in tree.nodes
                if tree.nodes[nid]["meta"].get("variant_id") in (1, 2)
            ]
            paths = [
                n["sim"].scene.config.parameters.get("kernel", {}).get(
                    "interventions_path"
                )
                for n in nodes
            ]
            assert all(paths), "both siblings must carry an isolated queue path"
            assert paths[0] != paths[1]
        finally:
            monkeypatch.undo()


# ===================================================================
# Group 4 — Checkpoint-fork interventions_text (RED): dead code today
# ===================================================================


class TestCheckpointForkInterventions:
    def _fork(self, tmp_path, interventions_text="X"):
        tree = _make_tree()
        a = tree.branch(0, [])
        cp = {"checkpoint_id": "cp-1", "run_dir": str(tmp_path / "source-run")}
        b, c = tree.fork_from_checkpoint(a, cp, count=2)
        # provenance write (exists today, tree_operations.py:710-713)
        for cid in (b, c):
            tree.nodes[cid]["meta"].setdefault("pending_interventions", None)
        tree.nodes[b]["meta"]["pending_interventions"] = interventions_text
        return tree, a, b, c

    def test_fork_intervention_provenance_stays_on_b_only(self, tmp_path):
        """GUARD — the meta write itself is node-local."""
        tree, a, b, c = self._fork(tmp_path)
        assert tree.nodes[b]["meta"]["pending_interventions"] == "X"
        assert not tree.nodes[c]["meta"].get("pending_interventions")

    def test_launch_materializes_interventions_text_into_b_queue(self, tmp_path):
        """B's pending intervention text must be CONSUMED at launch into B's
        own kernel queue file; C's queue stays clean (spec invariant 4).
        RED: nothing reads meta['pending_interventions'] — dead code."""
        from fos.backend.services import simtree_gaworld

        tree, a, b, c = self._fork(tmp_path)
        # branch runtime provenance so the queue files are defined
        for cid in (b, c):
            branch = tmp_path / f"branch-{cid}"
            patch = simtree_gaworld.branch_runtime_overrides(str(branch))
            merged = patch  # the implement path merges this into the node config
            tree.nodes[cid]["meta"]["interventions_path"] = merged["kernel"][
                "interventions_path"
            ]

        materialize = _feature(
            simtree_gaworld,
            "materialize_pending_interventions",
            label="checkpoint-fork interventions_text must reach B's queue",
        )
        materialize(tree, b)

        path_b = Path(tree.nodes[b]["meta"]["interventions_path"])
        path_c = Path(tree.nodes[c]["meta"]["interventions_path"])
        assert path_b.exists(), "B's pending intervention was never materialized"
        payload = path_b.read_text()
        assert "X" in payload
        assert not path_c.exists() or "X" not in path_c.read_text(), (
            "B's fork intervention leaked into C's queue"
        )
        # consumed once, not re-enqueued on a second materialize attempt
        if path_c.exists():
            pass

    def test_materialize_is_idempotent_per_attempt(self, tmp_path):
        from fos.backend.services import simtree_gaworld

        tree, a, b, c = self._fork(tmp_path, interventions_text="X")
        for cid in (b, c):
            branch = tmp_path / f"branch-{cid}"
            patch = simtree_gaworld.branch_runtime_overrides(str(branch))
            tree.nodes[cid]["meta"]["interventions_path"] = patch["kernel"][
                "interventions_path"
            ]
        materialize = _feature(simtree_gaworld, "materialize_pending_interventions")
        materialize(tree, b)
        path_b = Path(tree.nodes[b]["meta"]["interventions_path"])
        first = path_b.read_text()
        materialize(tree, b)
        assert path_b.read_text().count("X") <= first.count("X"), (
            "re-materializing must not duplicate the intervention (one "
            "application per attempt)"
        )


# ===================================================================
# Group 5 — Stale-node guard (RED): no newest-leaf fallback
# ===================================================================


class TestStaleNodeGuard:
    def _service(self):
        from fos.backend.services import environment_suggestion_service as svc

        return svc

    def test_missing_node_id_raises_instead_of_leaf_fallback(self):
        """An intervention aimed at a deleted/stale node must fail LOUDLY,
        never land on the newest leaf (spec invariant 2 / audit §3)."""
        svc = self._service()
        tree = _make_tree()
        a = tree.branch(0, [])
        b = tree.branch(a, [])
        resolved = None
        try:
            resolved, _ = svc._resolve_simulator_node(tree, "SIM", 9999)
        except Exception:
            resolved = "raised"
        assert resolved == "raised", (
            "RED: _resolve_simulator_node falls back to the newest leaf for a "
            "missing node id — an intervention for a stale node must be "
            "rejected loudly, never silently retargeted (invariant 2)"
        )

    def test_missing_node_id_argument_is_rejected_for_interventions(self):
        svc = self._service()
        tree = _make_tree()
        a = tree.branch(0, [])
        tree.branch(a, [])
        resolved = None
        try:
            resolved, _ = svc._resolve_simulator_node(tree, "SIM", None)
        except Exception:
            resolved = "raised"
        assert resolved == "raised", (
            "RED: intervention application without node_id infers the newest "
            "leaf — the request must carry the selected node (invariant 2)"
        )


# ===================================================================
# Group 6 — Rerun intervention semantics
# ===================================================================


class TestRerunInterventionSemantics:
    def test_variant_spec_x_reapplied_once_in_each_attempt(self, tmp_path):
        """X (variant spec) appears in run1 AND run2, exactly once per
        attempt (spec invariant 8: deterministic reapply)."""
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            h.run_once(monkeypatch, run_id=2)
            for run_id in (1, 2):
                node = h.tree.nodes[h.attempt_nodes(run_id)[0]]
                value = node["sim"].scene.config.parameters.get("economy", {}).get(
                    "initial_money"
                )
                assert value == 4242, f"run {run_id} must carry variant X"
                ops = [o for o in node["ops"] if o.get("op") == "config_params_patch"
                       and o.get("updates", {}).get("economy", {}).get(
                           "initial_money") == 4242]
                assert len(ops) == 1, (
                    f"run {run_id}: X applied more than once in the node ops"
                )
        finally:
            monkeypatch.undo()

    def test_one_off_manual_intervention_does_not_propagate(self, tmp_path):
        """A one-off runtime intervention applied to run 1's attempt (not in
        the variant spec) must NOT appear in run 2's attempt."""
        h = _RerunHarness(tmp_path, ops=[])
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            node1 = h.tree.nodes[h.attempt_nodes(1)[0]]
            # one-off manual intervention on the live attempt
            node1["sim"].agents["Alice"].properties["manual_flag"] = "one-off"
            node1["logs"].append({"type": "intervention", "node": node1["sim"] and id(node1), "data": {"text": "MANUAL_X"}})

            h.run_once(monkeypatch, run_id=2)
            node2 = h.tree.nodes[h.attempt_nodes(2)[0]]
            assert node2["sim"].agents["Alice"].properties.get("manual_flag") != "one-off", (
                "one-off manual intervention propagated into the rerun attempt"
            )
            texts = [e.get("data", {}).get("text") for e in node2["logs"]]
            assert "MANUAL_X" not in texts
        finally:
            monkeypatch.undo()

    def test_no_duplicate_application_from_stale_queue_on_rerun(self, tmp_path):
        """A rerun must not replay run 1's queue entries: run 2's queue file
        starts clean (publish clears pending at run start)."""
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            meta1 = h.tree.nodes[h.attempt_nodes(1)[0]]["meta"]
            path1 = Path(meta1["interventions_path"])
            path1.parent.mkdir(parents=True, exist_ok=True)
            path1.write_text(json.dumps(
                {"pending": [{"id": "stale-x"}], "applied": []}
            ))
            h.run_once(monkeypatch, run_id=2)
            meta2 = h.tree.nodes[h.attempt_nodes(2)[0]]["meta"]
            path2 = Path(meta2["interventions_path"])
            assert path1 != path2
            if path2.exists():
                assert json.loads(path2.read_text()).get("pending") in (None, [],), (
                    "run 2 must not inherit run 1's stale queue entries"
                )
        finally:
            monkeypatch.undo()


# ===================================================================
# Group 7 — Immutable first run after rerun
# ===================================================================


class TestImmutableFirstRun:
    def test_run1_node_and_files_unchanged_after_run2(self, tmp_path):
        h = _RerunHarness(tmp_path)
        monkeypatch = pytest.MonkeyPatch()
        try:
            h.run_once(monkeypatch, run_id=1)
            node1 = h.tree.nodes[h.attempt_nodes(1)[0]]
            snap_logs = [dict(e) for e in node1["logs"]]
            snap_turns = node1["sim"].turns
            meta1 = node1["meta"]
            b1 = Path(meta1["branch_dir"])
            (b1 / "state").mkdir(parents=True, exist_ok=True)
            (b1 / "state" / "final.csv").write_text("run1-final")
            before = sorted((str(p.relative_to(b1)), p.stat().st_mtime_ns)
                            for p in b1.rglob("*") if p.is_file())

            h.run_once(monkeypatch, run_id=2)

            assert node1["sim"].turns == snap_turns
            assert [dict(e) for e in node1["logs"]] == snap_logs
            after = sorted((str(p.relative_to(b1)), p.stat().st_mtime_ns)
                           for p in b1.rglob("*") if p.is_file())
            assert after == before, "run 2 mutated run 1's branch dir"
            assert (b1 / "state" / "final.csv").read_text() == "run1-final"
        finally:
            monkeypatch.undo()


# ===================================================================
# Group 8 — State isolation: real intervention op on B vs C (GUARD)
# ===================================================================


class TestStateIsolationByRealOp:
    def test_config_patch_on_b_leaves_c_and_base_untouched(self):
        tree = _make_tree()
        x_op = {
            "op": "config_params_patch",
            "updates": {"economy": {"initial_money": 4242}},
        }
        b = tree.branch(0, [x_op])
        c = tree.branch(0, [])
        params_b = tree.nodes[b]["sim"].scene.config.parameters
        params_c = tree.nodes[c]["sim"].scene.config.parameters
        params_a = tree.nodes[0]["sim"].scene.config.parameters
        assert params_b.get("economy", {}).get("initial_money") == 4242
        assert params_c.get("economy", {}).get("initial_money") != 4242, (
            "B's intervention leaked into sibling C's state"
        )
        assert params_a.get("economy", {}).get("initial_money") != 4242, (
            "base node A was mutated by B's intervention"
        )

    def test_agent_props_patch_on_b_is_sibling_isolated(self):
        tree = _make_tree()
        op = {
            "op": "agent_props_patch",
            "name": "Alice",
            "updates": {"policy_tax_rate": 0.25},
        }
        b = tree.branch(0, [op])
        c = tree.branch(0, [])
        assert (
            tree.nodes[b]["sim"].agents["Alice"].properties.get("policy_tax_rate")
            == 0.25
        )
        assert (
            tree.nodes[c]["sim"].agents["Alice"].properties.get("policy_tax_rate")
            != 0.25
        )
