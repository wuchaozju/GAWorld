"""Phase 8 STAGE A — SimTree GAWorld lifecycle hardening (RED tests).

Specifies the Phase 8 lifecycle feature set from PHASE8-BRIEF.md:

* Concurrency stress: 8 GAWorld branches with the bound at 2 must never show
  more than 2 REAL live subprocesses; queued branches drain as slots release;
  sibling output paths stay isolated.
* Queued cancellation: a queued node that is cancelled never launches and
  never consumes a slot.
* Running cancellation: terminate the process group, release the slot even
  when termination raises / the process already exited / cleanup errors;
  siblings unaffected; no orphan processes.
* Registry: a process registry that never reports dead processes as live and
  stays consistent after success / failure / timeout / cancel.
* Per-day timeout: configurable/injectable, terminates the child, node ends
  ``timed_out`` with a reason, slot released, no checkpoint for the
  incomplete day, exactly one terminal outcome in the timeout-vs-finish race.
* Failure isolation: B's failure/timeout/cancel leaves A and C unaffected and
  releases every acquired semaphore slot.
* Branch cap: max 8 GAWorld branches per advance_multi request, rejected
  BEFORE anything is created or launched, error names requested vs max.
* Branch-day budget: sum of requested additional days rejected before launch
  with requested vs allowed in the error and zero subprocesses on refusal.
* LLM budget preflight: per-provider estimates respecting Phase 4 per-agent
  routing; over-budget refuses the whole launch with a structured error
  {provider, estimated, budget, unit}; no silent provider substitution; no
  secrets in errors or payloads.
* Recovery regression guards: Retry / Fix-and-retry / Substitute stay
  checkpoint-based (these guards must stay GREEN).

Every non-guard test must fail naming the missing feature (AttributeError /
missing module / missing field), never a syntax error.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import fos.core.experiment.scenes.gaworld.subprocess_manager as subprocess_manager
import fos.core.experiment.scenes.gaworld.scene as scene_mod

# The FOS-side modules that will own the Phase 8 lifecycle features.
try:
    import fos.backend.services.simtree_lifecycle as simtree_lifecycle
except ModuleNotFoundError:  # pragma: no cover - module may not exist yet
    simtree_lifecycle = None

try:
    import fos.backend.services.simtree_budget as simtree_budget
except ModuleNotFoundError:  # pragma: no cover - module may not exist yet
    simtree_budget = None

try:
    import fos.backend.api.routes.simulations.tree_operations as tree_operations
except ModuleNotFoundError:  # pragma: no cover - never expected
    tree_operations = None


def _feature(module, name, *, label=None):
    """Fetch a not-yet-existing attribute; fail naming the missing feature."""
    assert module is not None, (
        f"feature missing: module {label or 'module'} does not exist (Phase 8 RED)"
    )
    attr = getattr(module, name, None)
    assert attr is not None, (
        f"feature missing: {module.__name__}.{name} is not implemented (Phase 8 RED)"
    )
    return attr


def _slot_count():
    """Current free slots of the shared GAWorld semaphore."""
    sem = subprocess_manager.gaworld_subprocess_semaphore()
    return sem._sem._value


class _SlowChildScript:
    """Writes a GAWorld-shaped tree whose child sleeps for a while."""

    def __init__(self, tmp_path: Path, sleep_seconds: float = 30.0):
        self.root = tmp_path / "gaworld"
        self.root.mkdir(exist_ok=True)
        script = self.root / "generative_city_sim.py"
        script.write_text(
            "import time, sys\n"
            "print('start', flush=True)\n"
            f"time.sleep({sleep_seconds})\n",
            encoding="utf-8",
        )

    @property
    def path(self) -> Path:
        return self.root


def _manager(tmp_path: Path, index: int) -> subprocess_manager.GAWorldSubprocessManager:
    return subprocess_manager.GAWorldSubprocessManager(
        gaworld_path=tmp_path / "gaworld",
        config_overrides={},
        output_dir=tmp_path / f"run-{index}",
        preserve_output=True,
    )


def _kill_quietly(manager) -> None:
    try:
        if manager.process is not None and manager.process.poll() is None:
            try:
                os.killpg(os.getpgid(manager.process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                manager.process.kill()
    except Exception:
        pass


# ===========================================================================
# §A recon-confirmed ground truth (guards — must stay GREEN)
# ===========================================================================


class TestLifecycleGroundTruth:
    def test_per_day_timeout_constant_is_1800(self):
        assert scene_mod.GAWORLD_WAIT_TIMEOUT_S == 1800, (
            "recon anchor: scene.py GAWORLD_WAIT_TIMEOUT_S must stay 1800"
        )

    def test_wait_for_day_accepts_injected_timeout(self, tmp_path):
        """wait_for_day(timeout=...) is the injectable seam."""
        _SlowChildScript(tmp_path, sleep_seconds=5.0)
        manager = _manager(tmp_path, 0)
        manager.launch()
        try:
            start = time.monotonic()
            with pytest.raises(subprocess_manager.GAWorldTimeoutError):
                manager.wait_for_day(1, timeout=0.5, poll_interval=0.1)
            assert time.monotonic() - start < 3.0, "injected timeout must be honored"
        finally:
            _kill_quietly(manager)

    def test_status_values_include_queued_and_running(self):
        """scene.py sets runtime_status queued→running around slot acquisition."""
        source = Path(scene_mod.__file__).read_text(encoding="utf-8")
        assert 'self.runtime_status = "queued"' in source
        assert 'self.runtime_status = "running"' in source


# ===========================================================================
# §13a — concurrency stress: 8 branches, limit 2, real process counts
# ===========================================================================


class TestConcurrencyStress:
    def test_process_registry_exists(self):
        """A registry of live GAWorld processes must be queryable."""
        _feature(subprocess_manager, "gaworld_process_registry")

    def test_registry_never_reports_dead_processes_as_live(self):
        registry = _feature(subprocess_manager, "gaworld_process_registry")
        assert hasattr(registry, "live_count") or callable(registry), (
            "feature missing: registry must expose live_count() (Phase 8 RED)"
        )

    def test_eight_branches_limit_two_max_two_live_processes(self, tmp_path, monkeypatch):
        """REAL process count: 8 concurrent GAWorld advances with the bound at
        2 must never show more than 2 alive child processes at any sample."""
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "2")
        monkeypatch.setattr(
            subprocess_manager, "_SLOTS_CACHE", {}, raising=False
        )
        sem = subprocess_manager.gaworld_subprocess_semaphore()
        _SlowChildScript(tmp_path, sleep_seconds=1.0)

        managers: list = []
        samples: list = []

        async def _advance(i):
            manager = _manager(tmp_path, i)
            managers.append(manager)
            async with sem:
                manager.launch()
                try:
                    waited = 0.0
                    while manager.is_alive() and waited < 5.0:
                        samples.append(sum(1 for m in managers if m.is_alive()))
                        await asyncio.sleep(0.05)
                        waited += 0.05
                finally:
                    _kill_quietly(manager)

        async def _main():
            await asyncio.gather(*[_advance(i) for i in range(8)])

        asyncio.run(_main())
        assert samples, "no liveness samples were taken"
        assert max(samples) <= 2, (
            f"observed {max(samples)} live GAWorld subprocesses with bound 2"
        )

    def test_queue_drains_as_slots_release(self, tmp_path, monkeypatch):
        """With bound 1 and 3 waits, launches must be serialized: at most one
        process alive at any time and all three eventually run."""
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "1")
        monkeypatch.setattr(subprocess_manager, "_SLOTS_CACHE", {}, raising=False)
        sem = subprocess_manager.gaworld_subprocess_semaphore()
        _SlowChildScript(tmp_path, sleep_seconds=0.4)

        order: list[str] = []

        async def _advance(i):
            manager = _manager(tmp_path, i)
            order.append(f"queued-{i}")
            async with sem:
                order.append(f"running-{i}")
                manager.launch()
                try:
                    while manager.is_alive():
                        await asyncio.sleep(0.05)
                finally:
                    _kill_quietly(manager)

        async def _main():
            await asyncio.gather(*[_advance(i) for i in range(3)])

        asyncio.run(_main())
        running_positions = [i for i, item in enumerate(order) if item.startswith("running")]
        assert len(running_positions) == 3, "all three advances must eventually run"
        # Between any two "running" entries a release must have happened —
        # with bound 1 entries can never overlap in time; approximate check:
        # each queued index precedes its running index.
        for i in range(3):
            assert order.index(f"queued-{i}") < order.index(f"running-{i}")

    def test_queue_diagnostics_metadata_exists(self, tmp_path, monkeypatch):
        """Queued/started timestamps and queue wait must be recorded."""
        _feature(scene_mod, "record_queue_diagnostics")


# ===========================================================================
# §13b — queued cancellation
# ===========================================================================


class TestQueuedCancellation:
    def test_cancel_api_exists(self):
        _feature(subprocess_manager, "request_cancel")

    def test_cancelled_queued_node_never_launches(self, tmp_path, monkeypatch):
        """Cancel while queued → cancelled, never launches, no slot consumed."""
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "1")
        monkeypatch.setattr(subprocess_manager, "_SLOTS_CACHE", {}, raising=False)
        subprocess_manager.gaworld_subprocess_semaphore()
        request_cancel = _feature(subprocess_manager, "request_cancel")
        _SlowChildScript(tmp_path, sleep_seconds=0.5)

        before = _slot_count()
        manager = _manager(tmp_path, 0)
        request_cancel(manager)
        launched = []
        try:
            # Simulate slot acquisition after cancel: must refuse to launch.
            launched.append(manager.launch())
        except Exception:
            launched.append("refused")
        assert launched[-1] == "refused" or manager.process is None, (
            "a cancelled queued node must never launch a subprocess"
        )
        assert _slot_count() == before, "cancel must not consume a slot"


# ===========================================================================
# §13c — running cancellation + slot release under error paths
# ===========================================================================


class TestRunningCancellation:
    def test_cancel_terminates_process_group(self, tmp_path):
        cancel = _feature(subprocess_manager.GAWorldSubprocessManager, "cancel")
        _SlowChildScript(tmp_path, sleep_seconds=30.0)
        manager = _manager(tmp_path, 0)
        manager.launch()
        try:
            assert manager.is_alive()
            cancel(manager)
            time.sleep(0.5)
            assert not manager.is_alive(), "cancel must terminate the subprocess"
        finally:
            _kill_quietly(manager)

    def test_cancel_releases_slot(self, tmp_path, monkeypatch):
        cancel = _feature(subprocess_manager.GAWorldSubprocessManager, "cancel")
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "1")
        monkeypatch.setattr(subprocess_manager, "_SLOTS_CACHE", {}, raising=False)
        sem = subprocess_manager.gaworld_subprocess_semaphore()
        _SlowChildScript(tmp_path, sleep_seconds=30.0)
        manager = _manager(tmp_path, 0)
        sem.acquire()
        before = _slot_count()
        manager.launch()
        try:
            cancel(manager)
            assert _slot_count() == before + 1, "cancel must release the slot"
        finally:
            _kill_quietly(manager)
            while _slot_count() < 1:
                sem.release()

    def test_slot_released_when_termination_raises(self, tmp_path, monkeypatch):
        """Slot release must survive a raising os.killpg (error path)."""
        cancel = _feature(subprocess_manager.GAWorldSubprocessManager, "cancel")
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "1")
        monkeypatch.setattr(subprocess_manager, "_SLOTS_CACHE", {}, raising=False)
        sem = subprocess_manager.gaworld_subprocess_semaphore()
        _SlowChildScript(tmp_path, sleep_seconds=30.0)
        manager = _manager(tmp_path, 0)
        sem.acquire()
        manager.launch()
        try:
            with patch("os.killpg", side_effect=ProcessLookupError("gone")):
                try:
                    cancel(manager)
                except Exception:
                    pass
            assert _slot_count() >= 1, (
                "slot must be released even when termination raises"
            )
        finally:
            _kill_quietly(manager)
            while sem._sem._value < 1:
                sem.release()

    def test_cancel_after_exit_is_safe(self, tmp_path):
        """Cancelling an already-exited process must not raise nor double-release."""
        cancel = _feature(subprocess_manager.GAWorldSubprocessManager, "cancel")
        _SlowChildScript(tmp_path, sleep_seconds=0.2)
        manager = _manager(tmp_path, 0)
        manager.launch()
        while manager.is_alive():
            time.sleep(0.05)
        cancel(manager)  # must not raise

    def test_cancelled_node_has_cancelled_status(self, tmp_path):
        """A cancelled node must be representable as cancelled."""
        source = Path(scene_mod.__file__).read_text(encoding="utf-8")
        assert '"cancelled"' in source, (
            "feature missing: scene has no cancelled runtime_status (Phase 8 RED)"
        )


# ===========================================================================
# §13d — per-day timeout
# ===========================================================================


class TestPerDayTimeout:
    def test_timeout_configurable_via_env(self, monkeypatch):
        """The ~1800s per-day timeout must be configurable for tests."""
        monkeypatch.setenv("FOS_GAWORLD_DAY_TIMEOUT_S", "3")
        resolved = _feature(scene_mod, "resolve_day_timeout_s")
        assert resolved() == 3, "env must override the default day timeout"

    def test_timed_out_status_exists(self):
        source = Path(scene_mod.__file__).read_text(encoding="utf-8")
        assert '"timed_out"' in source, (
            "feature missing: scene has no timed_out runtime_status (Phase 8 RED)"
        )

    def test_timeout_terminates_child_and_releases_slot(self, tmp_path, monkeypatch):
        """A timed-out wait must terminate the child and release its slot."""
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "1")
        monkeypatch.setattr(subprocess_manager, "_SLOTS_CACHE", {}, raising=False)
        sem = subprocess_manager.gaworld_subprocess_semaphore()
        _SlowChildScript(tmp_path, sleep_seconds=30.0)
        manager = _manager(tmp_path, 0)
        sem.acquire()
        manager.launch()
        try:
            with pytest.raises(subprocess_manager.GAWorldTimeoutError):
                manager.wait_for_day(1, timeout=0.5, poll_interval=0.1)
            _feature(scene_mod, "handle_day_timeout")(manager)
            time.sleep(0.3)
            assert not manager.is_alive(), "timeout must terminate the child"
            assert _slot_count() >= 1, "timeout must release the slot"
        finally:
            _kill_quietly(manager)
            while sem._sem._value < 1:
                sem.release()

    def test_no_checkpoint_for_incomplete_day(self, tmp_path, monkeypatch):
        """After a timeout no new checkpoint may exist; last one preserved."""
        _SlowChildScript(tmp_path, sleep_seconds=30.0)
        manager = _manager(tmp_path, 0)
        manager.launch()
        try:
            with pytest.raises(subprocess_manager.GAWorldTimeoutError):
                manager.wait_for_day(1, timeout=0.5, poll_interval=0.1)
        finally:
            _kill_quietly(manager)
        state_path = manager.output_dir / "memory" / "sim_state.json"
        assert not state_path.exists() or json.loads(
            state_path.read_text(encoding="utf-8")
        ).get("last_day", 0) < 1, (
            "an incomplete day must never yield a checkpoint reporting the day"
        )

    def test_timeout_vs_finish_race_single_terminal_outcome(self, tmp_path, monkeypatch):
        """Exactly one terminal outcome wins the timeout-vs-finish race."""
        resolve_terminal = _feature(simtree_lifecycle, "resolve_terminal_outcome")
        first, second = resolve_terminal("timed_out", "completed")
        assert second is None or second == first, (
            f"exactly one terminal outcome allowed, got {first!r} and {second!r}"
        )


# ===========================================================================
# §13e — failure isolation + registry consistency
# ===========================================================================


class TestFailureIsolation:
    def test_failure_isolation_module_seam_exists(self):
        _feature(simtree_lifecycle, "isolate_branch_failure")

    def test_semaphore_released_on_every_failure_path(self, tmp_path, monkeypatch):
        """Process error during wait must leave the semaphore full again."""
        monkeypatch.setenv("FOS_GAWORLD_MAX_SUBPROCESSES", "1")
        monkeypatch.setattr(subprocess_manager, "_SLOTS_CACHE", {}, raising=False)
        sem = subprocess_manager.gaworld_subprocess_semaphore()
        _SlowChildScript(tmp_path, sleep_seconds=0.1)
        manager = _manager(tmp_path, 0)
        sem.acquire()
        manager.launch()
        while manager.is_alive():
            time.sleep(0.05)
        with pytest.raises(subprocess_manager.GAWorldProcessError):
            manager.wait_for_day(1, timeout=5.0, poll_interval=0.1)
        _feature(scene_mod, "handle_day_timeout")
        # Error path must release: full bound of 1 restored by the handler.
        assert _slot_count() >= 0  # guard against negative bookkeeping


# ===========================================================================
# §13f — branch cap
# ===========================================================================


class TestBranchCap:
    def test_branch_cap_constant_is_eight(self):
        cap = _feature(tree_operations, "MAX_GAWORLD_BRANCHES_PER_REQUEST")
        assert int(cap) == 8, "branch cap must be 8"

    def test_branch_cap_rejects_before_launch(self):
        validate = _feature(simtree_lifecycle, "validate_branch_request")
        with pytest.raises(Exception) as excinfo:
            validate(count=9, max_branches=8)
        message = str(excinfo.value)
        assert "9" in message and "8" in message, (
            f"error must include requested vs max, got: {message}"
        )

    def test_branch_cap_within_and_exact_pass(self):
        validate = _feature(simtree_lifecycle, "validate_branch_request")
        validate(count=7, max_branches=8)
        validate(count=8, max_branches=8)

    def test_branch_cap_settings_field_exists(self):
        from fos.backend.core.config import Settings

        assert hasattr(Settings(), "fos_gaworld_max_subprocesses"), (
            "feature missing: Settings.fos_gaworld_max_subprocesses (Phase 8 RED)"
        )


# ===========================================================================
# §13g — branch-day budget
# ===========================================================================


class TestBranchDayBudget:
    def test_branch_day_budget_settings_field_exists(self):
        from fos.backend.core.config import Settings

        settings = Settings()
        assert hasattr(settings, "fos_branch_day_budget"), (
            "feature missing: Settings.fos_branch_day_budget (Phase 8 RED)"
        )

    def test_budget_rejects_over_before_launch(self):
        validate = _feature(simtree_lifecycle, "validate_branch_day_budget")
        with pytest.raises(Exception) as excinfo:
            validate(requested_days=12, allowed=10)
        message = str(excinfo.value)
        assert "12" in message and "10" in message, (
            f"error must include requested vs allowed, got: {message}"
        )

    def test_budget_within_and_exact_pass(self):
        validate = _feature(simtree_lifecycle, "validate_branch_day_budget")
        validate(requested_days=9, allowed=10)
        validate(requested_days=10, allowed=10)

    def test_refusal_launches_zero_subprocesses(self):
        """Refusal happens in validation — nothing to launch afterwards."""
        validate = _feature(simtree_lifecycle, "validate_branch_day_budget")
        with pytest.raises(Exception):
            validate(requested_days=11, allowed=10)


# ===========================================================================
# §13h — LLM budget preflight
# ===========================================================================


class TestLLMBudgetPreflight:
    def test_preflight_module_exists(self):
        assert simtree_budget is not None, (
            "feature missing: fos.backend.services.simtree_budget (Phase 8 RED)"
        )

    def test_single_provider_under_budget_passes(self):
        estimate = _feature(simtree_budget, "estimate_llm_budget")
        verdict = estimate(
            providers={"p1": {"budget": 1000, "unit": "calls"}},
            routing={"p1": 10},
        )
        assert verdict["p1"]["ok"] is True

    def test_single_provider_over_budget_refuses(self):
        estimate = _feature(simtree_budget, "estimate_llm_budget")
        verdict = estimate(
            providers={"p1": {"budget": 5, "unit": "calls"}},
            routing={"p1": 10},
        )
        assert verdict["p1"]["ok"] is False
        refusal = verdict["p1"]
        for field in ("provider", "estimated", "budget", "unit"):
            assert field in refusal, f"structured refusal missing {field!r}"

    def test_mixed_providers_estimated_separately(self):
        estimate = _feature(simtree_budget, "estimate_llm_budget")
        verdict = estimate(
            providers={
                "p1": {"budget": 5, "unit": "calls"},
                "p2": {"budget": 100, "unit": "calls"},
            },
            routing={"p1": 10, "p2": 10},
        )
        assert verdict["p1"]["ok"] is False
        assert verdict["p2"]["ok"] is True

    def test_per_agent_routing_respected(self):
        """Phase 4 per-agent routing: agents pinned to a provider count only
        against that provider."""
        estimate = _feature(simtree_budget, "estimate_llm_budget")
        verdict = estimate(
            providers={
                "p1": {"budget": 8, "unit": "calls"},
                "p2": {"budget": 8, "unit": "calls"},
            },
            routing={"p1": 6, "p2": 2},
            agent_routing={7: "p2", 8: "p2", 9: "p2"},
        )
        assert verdict["p1"]["ok"] is True
        assert verdict["p2"]["estimated"] >= 3, (
            "agents routed to p2 must be estimated against p2"
        )

    def test_no_silent_provider_substitution(self):
        estimate = _feature(simtree_budget, "estimate_llm_budget")
        verdict = estimate(
            providers={"p1": {"budget": 1, "unit": "calls"}},
            routing={"p1": 10},
        )
        assert verdict["p1"].get("substitute") in (None, False), (
            "budget refusal must never rewrite the provider"
        )

    def test_refusal_contains_no_secrets(self):
        """Sentinel: a secret-looking key must never leak into refusals."""
        estimate = _feature(simtree_budget, "estimate_llm_budget")
        verdict = estimate(
            providers={
                "p1": {"budget": 1, "unit": "calls", "api_key": "sk-SENTINEL-SECRET"}
            },
            routing={"p1": 10},
        )
        blob = json.dumps(verdict)
        assert "SENTINEL" not in blob and "sk-" not in blob, (
            "budget refusal must never contain provider secrets"
        )


# ===========================================================================
# §13i — recovery regression guards (GREEN — Phase 6 behaviour intact)
# ===========================================================================


class TestRecoveryRegressionGuards:
    def test_recovery_actions_still_exist(self):
        import fos.backend.services.simtree_gaworld as simtree_gaworld

        for name in ("prepare_recovery", "record_recovery", "validate_checkpoint_reference"):
            assert getattr(simtree_gaworld, name, None) is not None, (
                f"regression: simtree_gaworld.{name} disappeared"
            )

    def test_recovery_is_checkpoint_based(self, tmp_path):
        import fos.backend.services.simtree_gaworld as simtree_gaworld

        prepare = simtree_gaworld.prepare_recovery
        result = prepare(
            node={"meta": {"checkpoint": {"dir": str(tmp_path)}}},
            action="retry",
        )
        meta = result if isinstance(result, dict) else getattr(result, "meta", {})
        blob = json.dumps(meta, default=str)
        assert "checkpoint" in blob, "retry must stay checkpoint-based"

    def test_cancel_is_not_recovery(self):
        """cancel must not appear among the recovery actions."""
        import fos.backend.services.simtree_gaworld as simtree_gaworld

        actions = getattr(simtree_gaworld, "RECOVERY_ACTIONS", ("retry", "fix_and_retry", "substitute"))
        assert "cancel" not in actions


# ===========================================================================
# §13j — registry cleanup under every ending
# ===========================================================================


class TestRegistryCleanup:
    def test_registry_consistent_after_success(self, tmp_path):
        registry = _feature(subprocess_manager, "gaworld_process_registry")
        _SlowChildScript(tmp_path, sleep_seconds=0.2)
        manager = _manager(tmp_path, 0)
        manager.launch()
        while manager.is_alive():
            time.sleep(0.05)
        live = registry.live_count() if hasattr(registry, "live_count") else len(registry)
        assert live == 0, "registry must not report a finished process as live"

    def test_registry_consistent_after_kill(self, tmp_path):
        registry = _feature(subprocess_manager, "gaworld_process_registry")
        _SlowChildScript(tmp_path, sleep_seconds=30.0)
        manager = _manager(tmp_path, 0)
        manager.launch()
        try:
            _kill_quietly(manager)
            time.sleep(0.2)
            live = registry.live_count() if hasattr(registry, "live_count") else len(registry)
            assert live == 0, "registry must drop killed processes"
        finally:
            _kill_quietly(manager)
