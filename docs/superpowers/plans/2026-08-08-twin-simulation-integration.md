# Twin Simulation Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reports collected by Plan 1 actually drive a simulated agent — mirroring real location and activity onto it, injecting real context into its perception, and producing a reviewable habits diff from accumulated history.

**Architecture:** Two custom pipeline stages loaded from `CONFIG["pipeline"]["agent_step"]` as `"module:function"` entries, plus one twin-owned runtime intervention registered lazily so nothing is added to the kernel. `pipeline.py`, `generative_city_sim.py`, and the kernel are not modified. Calibration is a standalone offline script that writes nothing without approval.

**Tech Stack:** Python 3 stdlib, pytest + unittest. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-08-08-mobile-digital-twin-design.md` §5

**Depends on:** Plan 1 (`docs/superpowers/plans/2026-08-08-twin-data-spine-and-server.md`), commits `c656451`…`c143e8f`. `gaworld/twin/{geo,store,binding,backend}.py` must exist.

---

## Verified Integration Contract

These were read out of the source, not assumed. Deviating from them will produce a stage that runs but silently does nothing.

**Stage signature.** `fn(agent, step, sim)` where `sim` is a `SimContext`. The builtin stages in `generative_city_sim.py` are *closures* capturing `day`, `time_str`, `city_map`, and `step_minutes` from `run_simulation`'s scope. A `"module:function"` stage has no access to those, so everything must come from `agent`, `step`, or `sim`:

| Need | Source |
|---|---|
| day / time | `sim.clock.day`, `sim.clock.time_str` |
| config | `sim.config` |
| per-agent twin state | `sim.agent_ext(agent, "twin")` |
| audited state writes | `sim.controller.intervene(...)` |

**Step keys the mirror must override.** `reflect` and `memorize` read all of these from `step`; overriding them is what makes reflection and memory record the *real* values rather than the simulated ones:

| Key | Written by | Read by |
|---|---|---|
| `_location` | `move` | `memorize` |
| `_resolved_location` | `move` | `select_action`, `reflect` |
| `_act` | `select_action` | `reflect`, `memorize` |
| `_outcome` | `select_action` | `reflect`, `memorize` |
| `_effective_activity` | `select_action` | `reflect`, `memorize` |

Plus `agent["locations"]["current"]`, which is the persistent agent-side location.

**Perception key.** `perceive` writes `step["_perception"]`; `memorize` reads it. `twin_perceive` appends to it.

**Intervention signature.** `ctx.controller.register_intervention(name, fn)` where `fn(ctx, **kwargs)`. `ctx.controller.intervene(name, ctx, **kwargs)` records every call to the `controller.intervention` table via `ctx.recorder`.

**Habit episode keys.** `update_habits_from_episode(agent, episode, cfg)` reads `time`, `location`, `final_activity`, `action`, `day` off the episode.

---

## File Structure

| File | Responsibility |
|---|---|
| `gaworld/twin/stages.py` | `twin_perceive`, `twin_mirror`, and lazy registration of `set_agent_twin_state` |
| `scripts/twin_calibrate.py` | Offline habits/profile calibration with a human-review gate |
| `tests/test_twin_stages.py` | Stage behaviour, ordering, freshness, audit |
| `tests/test_twin_calibrate.py` | Aggregation correctness and the no-write-without-approval guarantee |

No existing file is modified. That is deliberate: enabling the twin is adding two strings to a config list, and disabling it is removing them, which makes twin-on versus twin-off a clean experimental control.

---

## Task 1: Twin stages

**Files:**
- Create: `gaworld/twin/stages.py`
- Test: `tests/test_twin_stages.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_twin_stages.py`:

```python
import os
import tempfile
import unittest
from dataclasses import dataclass, field

from gaworld.twin import stages, store


class _Recorder:
    def __init__(self):
        self.records = []

    def record(self, table, payload):
        self.records.append((table, payload))


class _Controller:
    def __init__(self):
        self._interventions = {}
        self.recorder = None

    def register_intervention(self, name, fn):
        self._interventions[str(name)] = fn

    def intervention_names(self):
        return sorted(self._interventions)

    def intervene(self, name, ctx, **kwargs):
        if ctx.recorder is not None:
            ctx.recorder.record("controller.intervention", {"name": name, "kwargs": kwargs})
        return self._interventions[str(name)](ctx, **kwargs)


@dataclass
class _Clock:
    day: int = 1
    time_str: str = "09:00"
    tick_index: int = 0


@dataclass
class _Ctx:
    """Minimal SimContext stand-in exposing only what the stages may touch."""

    config: dict = field(default_factory=dict)
    clock: _Clock = field(default_factory=_Clock)
    controller: _Controller = field(default_factory=_Controller)
    recorder: _Recorder = field(default_factory=_Recorder)
    _ext: dict = field(default_factory=dict)

    def agent_ext(self, agent, plugin_id):
        return agent.setdefault("ext", {}).setdefault(str(plugin_id), {})


def _report(report_id, ts, node_id="office", tag="work", note="", out_of_map=False):
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": 30.27, "lng": 120.15, "acc_m": 10, "source": "gps"},
        "grid": {"x": 1.0, "y": 0.0},
        "node_id": node_id,
        "snap_km": 0.2,
        "out_of_map": out_of_map,
        "action_tag": tag,
        "note": note,
    }


class _TwinStageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "twin")
        self.ctx = _Ctx(
            config={
                "twin": {
                    "enabled": True,
                    "root": self.root,
                    "snapshot_ttl_minutes": 30,
                },
                "memory_dir": os.path.join(self._tmp.name, "memory"),
            }
        )
        self.agent = {"id": 7, "name": "cw", "locations": {"current": "家"}}

    def tearDown(self):
        self._tmp.cleanup()

    def _fresh_step(self):
        return {
            "_location": "家",
            "_resolved_location": "家",
            "_act": "看书",
            "_outcome": "在【休息】中执行了【看书】",
            "_effective_activity": "休息",
            "_perception": "现在是早上。",
        }


class TestTwinMirror(_TwinStageCase):
    def test_mirror_overwrites_location_and_action(self):
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)

        self.assertEqual(self.agent["locations"]["current"], "office")
        self.assertEqual(step["_location"], "office")
        self.assertEqual(step["_resolved_location"], "office")
        self.assertIn("work", step["_act"])

    def test_mirror_is_skipped_when_the_snapshot_is_stale(self):
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60 * 60)

        # The agent must fall back to autonomous behaviour, untouched.
        self.assertEqual(self.agent["locations"]["current"], "家")
        self.assertEqual(step["_act"], "看书")

    def test_mirror_skips_an_out_of_map_report_but_still_mirrors_the_action(self):
        store.append_reports(7, [_report("a", 1000, node_id=None, out_of_map=True)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)

        # Location is NOT fabricated when the user is outside map coverage...
        self.assertEqual(self.agent["locations"]["current"], "家")
        # ...but the reported activity is still real and still mirrors.
        self.assertIn("work", step["_act"])

    def test_mirror_does_nothing_for_an_agent_with_no_twin(self):
        step = self._fresh_step()
        stages.twin_mirror({"id": 99, "locations": {"current": "家"}}, step, self.ctx, now_ts=1000)
        self.assertEqual(step["_act"], "看书")

    def test_mirror_is_audited(self):
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        stages.twin_mirror(self.agent, self._fresh_step(), self.ctx, now_ts=1000 + 60)

        names = [
            payload["name"]
            for table, payload in self.ctx.recorder.records
            if table == "controller.intervention"
        ]
        self.assertIn("set_agent_twin_state", names)

    def test_mirror_is_disabled_when_config_says_so(self):
        self.ctx.config["twin"]["enabled"] = False
        store.append_reports(7, [_report("a", 1000)], root=self.root)
        step = self._fresh_step()
        stages.twin_mirror(self.agent, step, self.ctx, now_ts=1000 + 60)
        self.assertEqual(step["_act"], "看书")


class TestTwinPerceive(_TwinStageCase):
    def test_perceive_appends_new_reports_to_perception(self):
        store.append_reports(7, [_report("a", 1000, note="在公司加班")], root=self.root)
        step = self._fresh_step()
        stages.twin_perceive(self.agent, step, self.ctx)
        self.assertIn("在公司加班", step["_perception"])

    def test_perceive_does_not_replay_the_same_report_twice(self):
        store.append_reports(7, [_report("a", 1000, note="加班")], root=self.root)
        first = self._fresh_step()
        stages.twin_perceive(self.agent, first, self.ctx)
        second = self._fresh_step()
        stages.twin_perceive(self.agent, second, self.ctx)
        self.assertNotIn("加班", second["_perception"])

    def test_perceive_advances_the_offset_across_reports(self):
        store.append_reports(7, [_report("a", 1000, note="早上")], root=self.root)
        stages.twin_perceive(self.agent, self._fresh_step(), self.ctx)
        store.append_reports(7, [_report("b", 2000, note="下午")], root=self.root)
        step = self._fresh_step()
        stages.twin_perceive(self.agent, step, self.ctx)
        self.assertIn("下午", step["_perception"])
        self.assertNotIn("早上", step["_perception"])

    def test_perceive_writes_an_episode(self):
        from gaworld.memory.experience import load_agent_episodes

        store.append_reports(7, [_report("a", 1000, note="加班")], root=self.root)
        stages.twin_perceive(self.agent, self._fresh_step(), self.ctx)
        episodes = load_agent_episodes(7, cfg=self.ctx.config)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["source"], "twin")

    def test_perceive_does_nothing_for_an_agent_with_no_twin(self):
        step = self._fresh_step()
        stages.twin_perceive({"id": 99}, step, self.ctx)
        self.assertEqual(step["_perception"], "现在是早上。")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_stages.py -v`

Expected: FAIL — `ImportError: cannot import name 'stages' from 'gaworld.twin'`

- [ ] **Step 3: Write the implementation**

Create `gaworld/twin/stages.py`:

```python
"""Pipeline stages that let real phone reports drive a simulated agent.

Two stages with two different insertion points, which is why they are two
functions rather than one::

    perceive → [twin_perceive] → interrupts → plan → …
        … → select_action → [twin_mirror] → reflect

``twin_perceive`` runs after ``perceive`` so real context reaches ``plan`` and
the agent can decide how to react. ``twin_mirror`` runs after
``select_action`` so the agent plans and moves normally and only then has its
location and action overwritten. Placing the mirror before ``move`` would let
``move`` overwrite it straight back — the failure is silent, which is why
``test_mirror_runs_after_move`` exists.

Neither stage may use closure state: loaded via ``"module:function"`` they get
only ``(agent, step, sim)``, so day/time come from ``sim.clock``.
"""

from __future__ import annotations

import time

from gaworld.memory.experience import append_agent_episode
from gaworld.twin import store


PLUGIN_ID = "twin"

# Reported tag -> the activity label the simulation uses.
TAG_ACTIVITY = {
    "commute": "通勤",
    "work": "工作",
    "study": "学习",
    "meal": "吃饭",
    "shopping": "购物",
    "rest": "休息",
    "social": "社交",
    "exercise": "运动",
    "errand": "办事",
    "other": "其他",
}


def _cfg(sim):
    return dict((getattr(sim, "config", None) or {}).get("twin") or {})


def _enabled(cfg):
    return bool(cfg.get("enabled", False))


def _root(cfg):
    return cfg.get("root", store.DEFAULT_ROOT)


def _has_twin(agent, root):
    """Whether this agent is bound to a phone. Cheap enough to run per tick."""
    return store.read_snapshot(agent.get("id"), root=root) is not None


def _set_agent_twin_state(ctx, agent_id=None, location=None, action=None, activity=None):
    """Intervention: write the string-valued twin fields onto an agent.

    The standard ``set_agent_state`` accepts floats only, so it cannot carry
    location or action. Routing through an intervention keeps every mirror
    write in the ``controller.intervention`` audit table — without that trail,
    later analysis cannot tell a simulated behaviour from an injected one.
    """
    agent = ctx.agents_by_id.get(agent_id) if hasattr(ctx, "agents_by_id") else None
    if agent is None:
        agent = getattr(ctx, "_twin_target", None)
    if agent is None:
        raise ValueError(f"unknown agent {agent_id!r}")
    if location:
        agent.setdefault("locations", {})["current"] = str(location)
    if action:
        agent["_twin_action"] = str(action)
    if activity:
        agent["_twin_activity"] = str(activity)
    return {"agent_id": agent_id, "location": location, "action": action}


def _ensure_intervention(sim):
    """Register the twin intervention on first use.

    Registration lives here rather than in ``gaworld/kernel/interventions.py``
    because that module is documented as domain-free. Assignment is idempotent,
    so calling this every tick is harmless.
    """
    controller = getattr(sim, "controller", None)
    if controller is None:
        return None
    controller.register_intervention("set_agent_twin_state", _set_agent_twin_state)
    return controller


def twin_mirror(agent, step, sim, now_ts=None):
    """Overwrite the agent's location and action with the latest real report."""
    cfg = _cfg(sim)
    if not _enabled(cfg):
        return
    root = _root(cfg)
    snapshot = store.read_snapshot(agent.get("id"), root=root)
    if snapshot is None:
        return

    now = time.time() if now_ts is None else float(now_ts)
    if not store.is_fresh(snapshot, now, cfg.get("snapshot_ttl_minutes", 30)):
        # Stale: the agent reverts to autonomous behaviour rather than being
        # pinned to a position the user left hours ago.
        return

    tag = str(snapshot.get("action_tag", "other"))
    activity = TAG_ACTIVITY.get(tag, TAG_ACTIVITY["other"])
    note = str(snapshot.get("note", "")).strip()
    action = f"{activity}（现实：{tag}）" if not note else f"{activity}（现实：{tag}／{note}）"

    # Out-of-map fixes carry no usable node, so location is left alone. The
    # activity is still real, so it still mirrors.
    location = snapshot.get("node_id") if not snapshot.get("out_of_map") else None

    controller = _ensure_intervention(sim)
    if controller is not None:
        sim._twin_target = agent
        try:
            controller.intervene(
                "set_agent_twin_state",
                sim,
                agent_id=agent.get("id"),
                location=location,
                action=action,
                activity=activity,
            )
        finally:
            sim._twin_target = None

    if location:
        step["_location"] = location
        step["_resolved_location"] = location
    step["_act"] = action
    step["_effective_activity"] = activity
    step["_outcome"] = f"在【{activity}】中执行了【{action}】"
    step["_twin_mirrored"] = True


def twin_perceive(agent, step, sim):
    """Feed reports the agent has not seen yet into its perception and memory."""
    cfg = _cfg(sim)
    if not _enabled(cfg):
        return
    root = _root(cfg)
    agent_id = agent.get("id")
    if not _has_twin(agent, root):
        return

    ext = sim.agent_ext(agent, PLUGIN_ID)
    last_ts = ext.get("last_ts")
    fresh = store.load_reports(agent_id, root=root, since_ts=last_ts)
    if not fresh:
        return

    clock = getattr(sim, "clock", None)
    day = getattr(clock, "day", 0)
    time_str = getattr(clock, "time_str", "")

    lines = []
    for record in fresh:
        tag = str(record.get("action_tag", "other"))
        activity = TAG_ACTIVITY.get(tag, TAG_ACTIVITY["other"])
        where = record.get("node_id") or "地图之外"
        note = str(record.get("note", "")).strip()
        lines.append(f"你在现实中于【{where}】{activity}" + (f"：{note}" if note else ""))

        append_agent_episode(
            agent_id,
            {
                "day": day,
                "time": time_str,
                "location": where,
                "final_activity": activity,
                "action": activity,
                "content": lines[-1],
                "source": "twin",
                "report_id": record.get("report_id"),
            },
            cfg=getattr(sim, "config", None),
        )

    ext["last_ts"] = max(float(r.get("ts", 0)) for r in fresh)
    step["_perception"] = (step.get("_perception", "") + " " + " ".join(lines)).strip()
    step["_twin_perceived"] = len(fresh)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_stages.py -v`

Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add gaworld/twin/stages.py tests/test_twin_stages.py
git commit -m "feat(twin): mirror and perception-injection pipeline stages"
```

---

## Task 2: Stage-ordering guard

**Files:**
- Modify: `tests/test_twin_stages.py` (append one test class)

The spec calls the mirror-before-`move` mistake out explicitly because it fails silently: the stage runs, writes the right values, and `move` overwrites them. A test that only checks `twin_mirror`'s output in isolation cannot catch it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_twin_stages.py`, before the `if __name__` block:

```python
class TestStageOrdering(_TwinStageCase):
    def test_mirror_after_move_survives_but_before_move_does_not(self):
        """Encode WHY the mirror sits after select_action.

        Simulates the two candidate orderings against a stand-in `move` that
        rewrites location the way the real one does. Only the correct ordering
        leaves the real location standing.
        """
        store.append_reports(7, [_report("a", 1000)], root=self.root)

        def fake_move(agent, step, sim):
            agent.setdefault("locations", {})["current"] = "模拟推断的地点"
            step["_location"] = "模拟推断的地点"
            step["_resolved_location"] = "模拟推断的地点"

        # Wrong ordering: mirror then move.
        agent_wrong = {"id": 7, "name": "cw", "locations": {"current": "家"}}
        step_wrong = self._fresh_step()
        stages.twin_mirror(agent_wrong, step_wrong, self.ctx, now_ts=1060)
        fake_move(agent_wrong, step_wrong, self.ctx)
        self.assertEqual(step_wrong["_location"], "模拟推断的地点")

        # Correct ordering: move then mirror.
        agent_right = {"id": 7, "name": "cw", "locations": {"current": "家"}}
        step_right = self._fresh_step()
        fake_move(agent_right, step_right, self.ctx)
        stages.twin_mirror(agent_right, step_right, self.ctx, now_ts=1060)
        self.assertEqual(step_right["_location"], "office")

    def test_configured_pipeline_places_the_stages_correctly(self):
        """The documented CONFIG ordering must actually satisfy the contract."""
        order = [
            "prepare", "perceive", "gaworld.twin.stages:twin_perceive", "interrupts",
            "plan", "adjust_activity", "move", "select_action",
            "gaworld.twin.stages:twin_mirror", "reflect", "update_state",
            "broadcast", "memorize", "record",
        ]
        self.assertLess(order.index("perceive"), order.index("gaworld.twin.stages:twin_perceive"))
        self.assertLess(order.index("gaworld.twin.stages:twin_perceive"), order.index("plan"))
        self.assertLess(order.index("move"), order.index("gaworld.twin.stages:twin_mirror"))
        self.assertLess(
            order.index("select_action"), order.index("gaworld.twin.stages:twin_mirror")
        )
        self.assertLess(order.index("gaworld.twin.stages:twin_mirror"), order.index("reflect"))
        self.assertLess(order.index("gaworld.twin.stages:twin_mirror"), order.index("memorize"))
```

- [ ] **Step 2: Run the tests**

Run: `python3 -m pytest tests/test_twin_stages.py -v`

Expected: PASS, 13 tests. Both new tests should pass immediately against the Task 1 implementation — they encode the ordering rationale rather than driving new code.

- [ ] **Step 3: Verify the stages actually load through the real pipeline resolver**

This confirms the `"module:function"` strings in the config resolve, which the ordering test above cannot prove:

```bash
python3 -c "
from gaworld.sim.pipeline import StagePipeline
p = StagePipeline.from_config(
    {'agent_step': ['gaworld.twin.stages:twin_perceive', 'gaworld.twin.stages:twin_mirror']},
    builtin={},
)
print(p.stage_names)
"
```

Expected output:

```
['gaworld.twin.stages:twin_perceive', 'gaworld.twin.stages:twin_mirror']
```

If either resolves to nothing, `from_config` logs a warning and skips it — check the module path spelling rather than editing `pipeline.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_twin_stages.py
git commit -m "test(twin): guard the mirror-after-move stage ordering"
```

---

## Task 3: Offline calibration script

**Files:**
- Create: `scripts/twin_calibrate.py`
- Test: `tests/test_twin_calibrate.py`

Channel C from spec §4.2. It aggregates accumulated reports into a habits patch and **writes nothing without explicit approval** — letting collected data silently rewrite an experimental subject would make later results unattributable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_twin_calibrate.py`:

```python
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import twin_calibrate
from gaworld.twin import store


def _report(report_id, ts, node_id, tag, hour):
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": 30.27, "lng": 120.15, "acc_m": 10, "source": "gps"},
        "grid": {"x": 1.0, "y": 0.0},
        "node_id": node_id,
        "out_of_map": False,
        "action_tag": tag,
        "note": "",
        "hour": hour,
    }


class TestTwinCalibrate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "twin")
        # Three mornings at the office, one evening at the gym.
        store.append_reports(
            7,
            [
                _report("a", 1000, "office", "work", 9),
                _report("b", 2000, "office", "work", 9),
                _report("c", 3000, "office", "work", 9),
                _report("d", 4000, "gym", "exercise", 19),
            ],
            root=self.root,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_aggregate_counts_locations(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        self.assertEqual(summary["frequent_locations"]["office"], 3)
        self.assertEqual(summary["frequent_locations"]["gym"], 1)

    def test_aggregate_counts_activity_tags(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        self.assertEqual(summary["action_tags"]["work"], 3)
        self.assertEqual(summary["action_tags"]["exercise"], 1)

    def test_aggregate_reports_total_and_span(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        self.assertEqual(summary["total_reports"], 4)
        self.assertEqual(summary["first_ts"], 1000)
        self.assertEqual(summary["last_ts"], 4000)

    def test_aggregate_on_an_agent_with_no_reports(self):
        summary = twin_calibrate.aggregate(99, root=self.root)
        self.assertEqual(summary["total_reports"], 0)
        self.assertEqual(summary["frequent_locations"], {})

    def test_build_patch_only_includes_locations_above_the_threshold(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        patch = twin_calibrate.build_patch(summary, min_occurrences=3)
        self.assertIn("office", patch["frequent_locations"])
        self.assertNotIn("gym", patch["frequent_locations"])

    def test_render_diff_is_human_readable(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        diff = twin_calibrate.render_diff(7, twin_calibrate.build_patch(summary, 3))
        self.assertIn("office", diff)
        self.assertIn("7", diff)

    def test_apply_refuses_without_approval(self):
        out = os.path.join(self._tmp.name, "patch.json")
        written = twin_calibrate.apply_patch(7, {"frequent_locations": {"office": 3}},
                                             out_path=out, approved=False)
        self.assertFalse(written)
        self.assertFalse(os.path.exists(out))

    def test_apply_writes_only_when_approved(self):
        out = os.path.join(self._tmp.name, "patch.json")
        written = twin_calibrate.apply_patch(7, {"frequent_locations": {"office": 3}},
                                             out_path=out, approved=True)
        self.assertTrue(written)
        with open(out, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["agent_id"], 7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_twin_calibrate.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'twin_calibrate'`

- [ ] **Step 3: Write the implementation**

Create `scripts/twin_calibrate.py`:

```python
"""Offline profile calibration from accumulated twin reports (spec channel C).

Aggregates real location and activity history into a habits patch and prints a
human-readable diff. It writes NOTHING unless ``--approve`` is passed.

That gate is the point of the script. Letting collected data silently rewrite
an experimental subject's profile would make later results unattributable: a
run that changed could not be traced to a config change versus an unnoticed
profile drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gaworld.twin import store


def aggregate(agent_id, root=store.DEFAULT_ROOT):
    """Summarize an agent's full report history."""
    reports = store.load_reports(agent_id, root=root)
    locations = Counter()
    tags = Counter()
    for record in reports:
        node_id = record.get("node_id")
        if node_id:
            locations[str(node_id)] += 1
        tags[str(record.get("action_tag", "other"))] += 1
    timestamps = [float(r.get("ts", 0)) for r in reports]
    return {
        "agent_id": int(agent_id),
        "total_reports": len(reports),
        "frequent_locations": dict(locations),
        "action_tags": dict(tags),
        "first_ts": min(timestamps) if timestamps else None,
        "last_ts": max(timestamps) if timestamps else None,
    }


def build_patch(summary, min_occurrences=3):
    """Keep only signals seen often enough to be a habit rather than a one-off."""
    return {
        "agent_id": summary["agent_id"],
        "frequent_locations": {
            name: count
            for name, count in summary["frequent_locations"].items()
            if count >= int(min_occurrences)
        },
        "action_tags": {
            name: count
            for name, count in summary["action_tags"].items()
            if count >= int(min_occurrences)
        },
        "derived_from_reports": summary["total_reports"],
    }


def render_diff(agent_id, patch):
    """Render the patch for a human to read before approving it."""
    lines = [f"Agent {agent_id} — proposed calibration", ""]
    lines.append(f"  derived from {patch.get('derived_from_reports', 0)} reports")
    lines.append("")
    lines.append("  frequent locations:")
    for name, count in sorted(
        patch.get("frequent_locations", {}).items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"    {name}: {count}")
    lines.append("")
    lines.append("  activity tags:")
    for name, count in sorted(patch.get("action_tags", {}).items(), key=lambda kv: -kv[1]):
        lines.append(f"    {name}: {count}")
    return "\n".join(lines)


def apply_patch(agent_id, patch, out_path, approved=False):
    """Write the patch only when explicitly approved. Returns whether it wrote."""
    if not approved:
        return False
    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = dict(patch)
    payload["agent_id"] = int(agent_id)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_id", type=int)
    parser.add_argument("--root", default=store.DEFAULT_ROOT)
    parser.add_argument("--min-occurrences", type=int, default=3)
    parser.add_argument("--out", default="output/twin/calibration.json")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="actually write the patch; without this the script only prints the diff",
    )
    args = parser.parse_args(argv)

    summary = aggregate(args.agent_id, root=args.root)
    if not summary["total_reports"]:
        print(f"Agent {args.agent_id} has no reports; nothing to calibrate.")
        return 1

    patch = build_patch(summary, min_occurrences=args.min_occurrences)
    print(render_diff(args.agent_id, patch))
    print("")

    if apply_patch(args.agent_id, patch, args.out, approved=args.approve):
        print(f"Written to {args.out}")
    else:
        print("Dry run. Re-run with --approve to write this patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_twin_calibrate.py -v`

Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/twin_calibrate.py tests/test_twin_calibrate.py
git commit -m "feat(twin): offline calibration script with human-review gate"
```

---

## Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run every twin test**

Run: `python3 -m pytest tests/test_twin_*.py -q`

Expected: 62 passed (41 from Plan 1, 13 stages, 8 calibrate).

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest tests/ -q`

Expected: 5 failures in `test_memory_consolidation_decay.py`, `test_memory_recall_and_review.py`, and `test_routine_change_commitment.py`. **These are pre-existing and unrelated to twin work** — they were failing before Plan 1 started. Any *other* failure is yours; investigate it.

- [ ] **Step 3: Confirm the stages resolve through the real pipeline**

```bash
python3 -c "
from gaworld.sim.pipeline import StagePipeline, DEFAULT_AGENT_STEP_ORDER
order = list(DEFAULT_AGENT_STEP_ORDER)
order.insert(order.index('interrupts'), 'gaworld.twin.stages:twin_perceive')
order.insert(order.index('reflect'), 'gaworld.twin.stages:twin_mirror')
builtin = {name: (lambda a, s, c: None) for name in DEFAULT_AGENT_STEP_ORDER}
p = StagePipeline.from_config({'agent_step': order}, builtin=builtin)
names = p.stage_names
assert 'gaworld.twin.stages:twin_mirror' in names, 'mirror did not resolve'
assert names.index('move') < names.index('gaworld.twin.stages:twin_mirror')
assert names.index('gaworld.twin.stages:twin_mirror') < names.index('reflect')
print('pipeline ok:', len(names), 'stages')
"
```

Expected: `pipeline ok: 14 stages`

- [ ] **Step 4: Exercise the calibration CLI end to end**

```bash
python3 - <<'PY'
from gaworld.twin import store
rows = [{"report_id": f"r{i}", "ts": 1000 + i, "loc": {"lat": 30.27, "lng": 120.15},
         "grid": {"x": 0, "y": 0}, "node_id": "office", "out_of_map": False,
         "action_tag": "work", "note": ""} for i in range(5)]
store.append_reports(999, rows, root="output/twin")
print("seeded")
PY
python3 scripts/twin_calibrate.py 999 --root output/twin
```

Expected: a diff listing `office: 5` and `work: 5`, ending with `Dry run. Re-run with --approve to write this patch.` Confirm no file was written:

```bash
test -f output/twin/calibration.json && echo "LEAKED - dry run wrote a file" || echo "dry run wrote nothing (correct)"
```

- [ ] **Step 5: Clean up the seeded data**

```bash
rm -rf output/twin/agent_999
```

- [ ] **Step 6: Commit nothing**

This task changes no files. If `git status` shows twin changes, something in an earlier task was left uncommitted — resolve that before finishing.

---

## Done When

- `python3 -m pytest tests/test_twin_*.py -q` passes, 62 tests.
- The full suite shows only the 5 known pre-existing failures.
- Task 4 Step 3 prints `pipeline ok: 14 stages`.
- The calibration dry run writes nothing.
- No file outside `gaworld/twin/stages.py`, `scripts/twin_calibrate.py`, and the two test files was modified.

## Deliberately Not In This Plan

- `site/mobile/` PWA — Plan 3.
- Enabling the twin by default. `CONFIG["twin"]["enabled"]` stays `False`, and the pipeline entries are not added to the shipped default order. Turning it on is an explicit act, which is what makes twin-on versus twin-off a usable experimental control.
- Applying the calibration patch to `data/hangzhou_profiles_with_names.md`. The script emits a patch file; feeding it into the profile is a manual, reviewed step by design.

## Known Risk

Another session is concurrently editing `generative_city_sim.py`. This plan does not modify that file, and the stage contract it depends on (`step` keys, `sim.clock`, `SimContext`) is stable API rather than line numbers. But if the concurrent work renames any `step` key in the table at the top of this plan, `twin_mirror` will silently stop taking effect. Task 2's ordering test would still pass — it uses a stand-in `move`. Re-read that table against `generative_city_sim.py` if the mirror ever appears to do nothing.
