"""Holiday feature tests — pure logic + integration through the plugin surface."""

from __future__ import annotations

import types

import pytest

# ---------------------------------------------------------------------------
# Pure service tests
# ---------------------------------------------------------------------------


def test_start_holiday_arms_per_agent_window():
    from gaworld.holiday import service

    agents = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    result = service.start_holiday(agents, day=5, days=7)
    assert sorted(result["armed"]) == [1, 2]
    assert result["blocked"] == []
    assert agents[0]["_holiday"]["started_day"] == 5
    assert agents[0]["_holiday"]["ends_day"] == 11
    assert agents[0]["_holiday"]["days"] == 7
    assert agents[1]["_holiday"]["ends_day"] == 11


def test_start_holiday_refuses_to_rearm_active_window():
    from gaworld.holiday import service

    agents = [{"id": 1}]
    service.start_holiday(agents, day=5, days=7)
    second = service.start_holiday(agents, day=6, days=3)
    assert second["blocked"] == [1]
    # Original window untouched.
    assert agents[0]["_holiday"]["ends_day"] == 11


def test_end_holiday_shortens_window():
    from gaworld.holiday import service

    agents = [{"id": 1}]
    service.start_holiday(agents, day=5, days=10)
    result = service.end_holiday(agents, day=8)
    assert result["ended"] == [1]
    assert agents[0]["_holiday"]["ends_day"] == 7


def test_cancel_holiday_strips_window():
    from gaworld.holiday import service

    agents = [{"id": 1}, {"id": 2}]
    service.start_holiday(agents, day=1, days=5)
    result = service.cancel_holiday(agents)
    assert sorted(result["cancelled"]) == [1, 2]
    assert all("_holiday" not in a for a in agents)


def test_holiday_status_for_agent_only_when_in_window():
    from gaworld.holiday import service

    agents = [{"id": 1}]
    service.start_holiday(agents, day=5, days=3)
    assert service.holiday_status_for_agent(agents[0], day=5)["remaining_days"] == 3
    assert service.holiday_status_for_agent(agents[0], day=7)["remaining_days"] == 1
    assert service.holiday_status_for_agent(agents[0], day=8) is None


def test_holiday_overall_status_aggregates_active_agents():
    from gaworld.holiday import service

    agents = [{"id": 1}, {"id": 2}, {"id": 3}]
    service.start_holiday(agents, day=5, days=4, plan_key="travel")
    service.start_holiday(agents[:1], day=5, days=2, plan_key="study")
    summary = service.holiday_overall_status(agents, day=6)
    assert summary["active_agents"] == 3
    assert summary["remaining_agent_days"] >= 3  # min(3) for agent 1
    assert "travel" in summary["plans"]


# ---------------------------------------------------------------------------
# Activity-replacement rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hour, minute, original, expect_replacement",
    [
        # Sleep / late-sleep bands: always pass through.
        (3, 30, "在公园散步", False),
        (23, 30, "在公园散步", False),
        # Meal bands: pass through.
        (8, 0, "在公园散步", False),
        (12, 0, "在公园散步", False),
        (18, 0, "在公园散步", False),
        # Sleep-keyword original: pass through even at 14:00.
        (14, 0, "在卧室午睡", False),
        # Waking, non-sleep original: replaced.
        (10, 0, "在公园散步", True),
        (15, 0, "整理会议纪要", True),
        (20, 30, "在客厅看电视", True),
    ],
)
def test_pick_replacement_activity_protects_sleep_and_meals(hour, minute, original, expect_replacement):
    from gaworld.holiday import service

    agent = {"_holiday": {"plan_key": "travel", "started_day": 1, "ends_day": 9}}
    time_str = f"{hour:02d}:{minute:02d}"
    replacement = service.pick_replacement_activity(agent, time_str=time_str, original_activity=original)
    if expect_replacement:
        assert replacement is not None
        assert replacement["activity"] != original
        assert replacement["reason"]
    else:
        assert replacement is None


def test_pick_replacement_skips_collision_with_original():
    """A freedom-bank label that overlaps the routine's wording is replaced
    by the next candidate, never by accident."""
    from gaworld.holiday import service

    agent = {"_holiday": {"plan_key": "exercise", "started_day": 1, "ends_day": 9}}
    # Evening: exercise is one of the bank entries that won't collide with a
    # work routine but we'd expect a travel/creative override here. We just
    # need the activity to *differ* from original.
    rep = service.pick_replacement_activity(agent, time_str="20:00", original_activity="整理会议纪要")
    assert rep is not None
    assert rep["activity"] != "整理会议纪要"


def test_format_holiday_plan_block_under_budget():
    from gaworld.holiday import service

    long = service.format_holiday_plan_block(
        {"activity": "出门短途出游", "reason": "换一种节奏过日子", "plan_key": "travel"},
        budget_chars=80,
    )
    assert long
    assert len(long) <= 80
    assert "放假模式" in long
    # Wrapper question that lets the LLM recognize holiday mode.
    assert "全新的、自由的安排" in long


def test_summarize_replacement_log_is_one_line():
    from gaworld.holiday import service

    line = service.summarize_replacement_log({"activity": "出门短途出游", "reason": "换一种节奏过日子"})
    assert line.startswith("[放假] ")
    assert line.count("\n") == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_config_rejects_bad_max_days():
    from gaworld.holiday import validate_config

    with pytest.raises(ValueError, match="max_days"):
        validate_config({"holiday": {"max_days": 0, "min_days": 1, "default_days": 3}})
    with pytest.raises(ValueError, match="min_days"):
        validate_config({"holiday": {"max_days": 5, "min_days": 9, "default_days": 3}})
    with pytest.raises(ValueError, match="plan_prompt_budget"):
        validate_config({"holiday": {"plan_prompt_budget_chars": 99999}})


def test_validate_config_accepts_well_formed_block():
    from gaworld.holiday import validate_config

    # Should not raise.
    validate_config(
        {
            "holiday": {
                "max_days": 30,
                "min_days": 1,
                "default_days": 7,
                "plan_prompt_budget_chars": 240,
            }
        }
    )


# ---------------------------------------------------------------------------
# Plugin-integration smoke: register HolidayPlugin against a tiny synthetic
# kernel and run one tick to verify the rewrite fires.
# ---------------------------------------------------------------------------


class _FakeRecorder:
    def __init__(self):
        self.rows = []

    def record(self, table, payload):
        self.rows.append((table, payload))


class _FakeBus:
    def __init__(self):
        self.handlers = []

    def on(self, event, fn, priority=0):
        self.handlers.append((event, priority, fn))

    def emit(self, event, **ctx):
        for ev, _, fn in self.handlers:
            if ev != event:
                continue
            fn(ctx)


class _FakeController:
    def __init__(self):
        self.interventions = {}

    def register_intervention(self, name, fn):
        self.interventions[name] = fn


class _FakeClock:
    def __init__(self, day):
        self.day = day


class _FakeCtx:
    def __init__(self, agents, clock_day=5):
        self.config = {}
        self.bus = _FakeBus()
        self.controller = _FakeController()
        self.agents = agents
        self.clock = _FakeClock(clock_day)
        self.recorder = _FakeRecorder()


def _run_one_tick(agent, time_str, day):
    """Emulate the kernel's per-tick flow as far as HolidayPlugin cares."""
    import os

    from gaworld.holiday import normalize_config

    # Lazy import so each test gets a fresh module-instance via importlib.
    from gaworld.holiday.plugin import HolidayPlugin

    plugin = HolidayPlugin()
    plugin._cfg = normalize_config({})
    plugin._enabled = True
    plugin._output_dir = "/tmp/_holiday_test_output"
    os.makedirs(plugin._output_dir, exist_ok=True)

    ctx = _FakeCtx([agent], clock_day=day)
    plugin.setup(ctx)

    step = {"scheduled_activity": "整理会议纪要", "activity": "整理会议纪要"}
    ctx.bus.emit(
        "on_agent_pre_step",
        agent=agent,
        step=step,
        day=day,
        time_str=time_str,
        daily_logs={},
    )
    return step, ctx


def test_plugin_rewrites_activity_when_in_window():
    agent = {"id": 7, "daily_life": "工作节奏紧张，少有整段时间"}
    from gaworld.holiday import service

    service.start_holiday([agent], day=5, days=3, plan_key="travel")
    step, _ = _run_one_tick(agent, "10:00", day=5)
    assert step["scheduled_activity"] != "整理会议纪要"
    assert step["_holiday_replacement"] is not None


def test_plugin_passes_through_sleep_hour():
    agent = {"id": 8, "daily_life": "工作节奏紧张，少有整段时间"}
    from gaworld.holiday import service

    service.start_holiday([agent], day=5, days=3, plan_key="travel")
    step, _ = _run_one_tick(agent, "03:00", day=5)
    # Sleep window: untouched.
    assert step["scheduled_activity"] == "整理会议纪要"


def test_plugin_controller_intervention_start_and_cancel():
    from gaworld.holiday.plugin import HolidayPlugin

    plugin = HolidayPlugin()
    plugin._cfg = {"enabled": True, "min_days": 1, "max_days": 30, "default_days": 7}
    plugin._enabled = True
    ctx_obj = types.SimpleNamespace(
        agents=[{"id": 1}, {"id": 2}],
        clock=types.SimpleNamespace(day=4),
        recorder=_FakeRecorder(),
    )
    started = plugin._intervene_start(ctx_obj, days=5)
    assert sorted(started["armed"]) == [1, 2]
    # The recorder audit row got written.
    assert any(row[0] == "holiday.intervention" for row in ctx_obj.recorder.rows)

    cancelled = plugin._intervene_cancel(ctx_obj)
    assert sorted(cancelled["cancelled"]) == [1, 2]
    assert all("_holiday" not in a for a in ctx_obj.agents)


def test_plugin_intervention_rejects_out_of_range_days():
    from gaworld.holiday.plugin import HolidayPlugin

    plugin = HolidayPlugin()
    plugin._cfg = {"enabled": True, "min_days": 1, "max_days": 7, "default_days": 7}
    plugin._enabled = True
    ctx_obj = types.SimpleNamespace(
        agents=[{"id": 1}],
        clock=types.SimpleNamespace(day=1),
        recorder=_FakeRecorder(),
    )
    with pytest.raises(ValueError, match="between"):
        plugin._intervene_start(ctx_obj, days=99)


def test_plugin_intervention_refuses_when_disabled():
    from gaworld.holiday.plugin import HolidayPlugin

    plugin = HolidayPlugin()
    plugin._cfg = {"enabled": True, "min_days": 1, "max_days": 7, "default_days": 7}
    plugin._enabled = False  # teacher turned the feature off mid-run
    ctx_obj = types.SimpleNamespace(
        agents=[{"id": 1}],
        clock=types.SimpleNamespace(day=1),
        recorder=_FakeRecorder(),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        plugin._intervene_start(ctx_obj, days=3)
