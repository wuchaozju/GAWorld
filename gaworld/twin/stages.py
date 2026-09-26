"""Pipeline stages that let real phone reports drive a simulated agent.

Two stages with two different insertion points, which is why they are two
functions rather than one::

    perceive → [twin_perceive] → interrupts → plan → …
        … → select_action → [twin_mirror] → reflect

``twin_perceive`` runs after ``perceive`` so real context reaches ``plan`` and
the agent can decide how to react. ``twin_mirror`` runs after
``select_action`` so the agent plans and moves normally and only then has its
location and action overwritten. Placing the mirror before ``move`` would let
``move`` overwrite it straight back — the failure is silent, which is why the
ordering guard test exists.

Neither stage may use closure state: loaded via ``"module:function"`` they get
only ``(agent, step, sim)``, so day/time come from ``sim.clock``.
"""

from __future__ import annotations

import time

from gaworld.memory.experience import append_agent_episode
from gaworld.twin import store
from gaworld.world.away import AWAY_PREFIX, away_label


PLUGIN_ID = "twin"

#: Re-exported for the callers that imported it from here. The definition
#: moved to :mod:`gaworld.world.away` once simulated trips started producing
#: the same marker: what "异地" means to the rest of the world has to be one
#: answer, not two.
__all__ = ["AWAY_PREFIX", "twin_mirror", "twin_perceive"]

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
    agent = None
    agents_by_id = getattr(ctx, "agents_by_id", None)
    if agents_by_id:
        agent = agents_by_id.get(agent_id)
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

    # A fix outside the mapped city is still a real position. Rather than
    # leaving the agent where the simulation last put it — which would quietly
    # assert it is in town when it is not — mark it as away, naming the place
    # when we can. Never snap to a nearest node: that would fabricate a
    # location and poison the calibration corpus.
    if snapshot.get("out_of_map"):
        place = str(snapshot.get("place") or "").strip()
        location = away_label(place)
    else:
        location = snapshot.get("node_id")

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
        if record.get("node_id"):
            where = record["node_id"]
        else:
            place = str(record.get("place") or "").strip()
            where = away_label(place)
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
