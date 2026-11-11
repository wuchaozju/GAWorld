"""Runtime timing must observe work without changing stage results or scope."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from gaworld.core.runner import parallel_map
from gaworld.kernel import build_kernel
from gaworld.llm.stats import LLMCallStats
from gaworld.sim.pipeline import StagePipeline


def test_pipeline_records_completed_and_failed_stages_without_swallowing_errors():
    from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector

    stats = TimingCollector()
    token = ACTIVE_TIMINGS.set(stats)
    error = ValueError("original failure")

    def completed(agent, step, ctx):
        step["done"] = True

    def failed(agent, step, ctx):
        raise error

    try:
        step = {"_skip_stages": {"skip"}}
        pipeline = StagePipeline([("completed", completed), ("skip", failed), ("failed", failed)])
        with pytest.raises(ValueError) as caught:
            pipeline.run_step({"id": 1}, step, None)
        assert caught.value is error
        assert step["done"] is True
        operations = stats.snapshot()["operations"]
        assert operations["stage.completed"]["calls"] == 1
        assert operations["stage.failed"]["failures"] == 1
        assert "stage.skip" not in operations
    finally:
        ACTIVE_TIMINGS.reset(token)


def test_percentiles_are_bounded_window_stats_with_exact_lifetime_totals():
    from gaworld.core.performance import TimingCollector

    stats = TimingCollector(sample_limit=4)
    for latency in [900, 10, 20, 30, 40]:
        stats.record("test", latency, failed=latency == 900)
    report = stats.snapshot()
    row = report["operations"]["test"]
    assert row == {
        "calls": 5,
        "failures": 1,
        "total_ms": 1000,
        "max_ms": 900,
        "sample_count": 4,
        "p50_ms": 20,
        "p95_ms": 40,
    }
    assert report["percentile_scope"] == "last_samples"
    assert report["sample_limit"] == 4


def test_worker_threads_inherit_run_collector_and_preserve_results():
    from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector, measure

    stats = TimingCollector()
    token = ACTIVE_TIMINGS.set(stats)

    def work(value):
        with measure("worker"):
            return value * 2

    try:
        assert parallel_map(work, range(20), max_workers=4) == [i * 2 for i in range(20)]
        assert stats.snapshot()["operations"]["worker"]["calls"] == 20
    finally:
        ACTIVE_TIMINGS.reset(token)
    assert ACTIVE_TIMINGS.get() is None


def test_llm_metrics_keep_existing_counters_and_record_task_latency():
    from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector

    timings = TimingCollector()
    token = ACTIVE_TIMINGS.set(timings)
    stats = LLMCallStats()
    try:
        stats.record(task="planning", provider="a", latency_ms=25, ok=True)
        stats.record(task="planning", provider="a", latency_ms=75, ok=False)
        assert stats.snapshot()["by_task"]["planning"] == {
            "calls": 2,
            "failures": 1,
            "total_latency_ms": 100,
        }
        row = timings.snapshot()["operations"]["llm.planning"]
        assert row["calls"] == 2
        assert row["failures"] == 1
        assert row["total_ms"] == 100
        assert row["p95_ms"] == 75
    finally:
        ACTIVE_TIMINGS.reset(token)


def test_inactive_measurement_does_not_read_the_clock():
    from gaworld.core.performance import ACTIVE_TIMINGS, measure

    token = ACTIVE_TIMINGS.set(None)
    try:
        with patch("gaworld.core.performance.time.perf_counter", side_effect=AssertionError("clock")):
            with measure("disabled"):
                pass
    finally:
        ACTIVE_TIMINGS.reset(token)


def test_plugin_writes_run_scoped_reports_and_restores_outer_context(tmp_path, capsys):
    from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector
    from gaworld.plugins import builtin_plugins
    from gaworld.plugins.performance import PerformancePlugin

    assert "performance" in [plugin.id for plugin in builtin_plugins()]
    outer = TimingCollector()
    token = ACTIVE_TIMINGS.set(outer)
    ctx = build_kernel({"records": {"output_dir": str(tmp_path)}}, load_entry_points=False)
    plugin = PerformancePlugin()
    try:
        plugin.setup(ctx)
        assert ACTIVE_TIMINGS.get() is outer
        ctx.bus.emit("agents.built")
        stats = ACTIVE_TIMINGS.get()
        assert stats is not outer
        stats.record("stage.plan", 20)
        ctx.clock.day = 1
        assert ctx.bus.emit("on_day_end", day=1) == []
        ctx.bus.emit("on_simulation_end")
        plugin.teardown(ctx)
        assert ACTIVE_TIMINGS.get() is outer
        rows = [
            json.loads(line) for line in (tmp_path / "performance.summary.jsonl").read_text().splitlines()
        ]
        assert [row["scope"] for row in rows] == ["day_end", "simulation_end"]
        assert rows[-1]["operations"]["stage.plan"]["total_ms"] == 20
        assert "stage.plan" in capsys.readouterr().out
        assert outer.snapshot()["operations"] == {}
    finally:
        ctx.recorder.close()
        ACTIVE_TIMINGS.reset(token)


def test_disabled_plugin_does_not_install_or_write_anything(tmp_path):
    from gaworld.core.performance import ACTIVE_TIMINGS
    from gaworld.plugins.performance import PerformancePlugin

    ctx = build_kernel(
        {"performance": {"enabled": False}, "records": {"output_dir": str(tmp_path)}},
        load_entry_points=False,
    )
    before = ACTIVE_TIMINGS.get()
    plugin = PerformancePlugin()
    plugin.setup(ctx)
    ctx.bus.emit("on_day_end", day=1)
    ctx.bus.emit("on_simulation_end")
    plugin.teardown(ctx)
    ctx.recorder.close()
    assert ACTIVE_TIMINGS.get() is before
    assert list(tmp_path.iterdir()) == []


def test_failed_run_cannot_contaminate_a_subsequent_disabled_run(tmp_path):
    from gaworld.core.performance import ACTIVE_TIMINGS, isolate_timings
    from gaworld.plugins.performance import PerformancePlugin

    plugin = PerformancePlugin()
    ctx = build_kernel({"records": {"output_dir": str(tmp_path)}}, load_entry_points=False)

    @isolate_timings
    def failed_run():
        plugin.setup(ctx)
        ctx.bus.emit("agents.built")
        assert ACTIVE_TIMINGS.get() is not None
        raise ValueError("simulation failed before teardown")

    @isolate_timings
    def disabled_run():
        assert ACTIVE_TIMINGS.get() is None

    try:
        with pytest.raises(ValueError, match="before teardown"):
            failed_run()
        assert ACTIVE_TIMINGS.get() is None
        disabled_run()
        # Late cleanup of the failed plugin must not restore a stale context.
        plugin.teardown(ctx)
        assert ACTIVE_TIMINGS.get() is None
    finally:
        ctx.recorder.close()


def test_real_simulation_entrypoint_isolates_even_preflight_failures(monkeypatch):
    import generative_city_sim as sim
    from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector, measure

    outer = TimingCollector()
    token = ACTIVE_TIMINGS.set(outer)

    def fail_preflight(config):
        with measure("unrelated_run"):
            raise ValueError("preflight failure")

    monkeypatch.setattr(sim, "validate_runtime_config", fail_preflight)
    try:
        with pytest.raises(ValueError, match="preflight failure"):
            sim.run_simulation()
        assert ACTIVE_TIMINGS.get() is outer
        assert outer.snapshot()["operations"] == {}
    finally:
        ACTIVE_TIMINGS.reset(token)
