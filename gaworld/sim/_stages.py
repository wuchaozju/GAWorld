"""The twelve built-in stages of one agent step, lifted out of ``run_simulation``.

They were closures over ``run_simulation``'s locals. Now they are plain
functions ``fn(agent, step, sim, *, scope)``: ``step`` is the per-step data bus
and ``sim`` the kernel context, exactly as before (see
``gaworld/sim/pipeline.py``), and ``scope`` (:class:`StepScope`) carries what
the closures used to see:

* the run's objects, the current day and the current tick, which
  ``run_simulation`` writes into the scope before every agent step (closures
  late-bind, so a value rebound between ticks is what the next step sees, and
  the refresh keeps that);
* the settings ``generative_city_sim`` reads at import (``STATEFUL``,
  ``HUMAN_REALISM_*``, ``GOALS_*``, ``REPLAN_*``, ...) and its ``CONFIG``,
  passed in from there so that tests and callers that set
  ``sim.STATEFUL`` / ``sim.CONFIG`` keep reaching the stages; they become
  ``CONFIG`` lookups when ``run_simulation`` itself moves;
* the helpers that still live in ``generative_city_sim`` (``planning``,
  ``reflection``, ``update_state``, ``infer_event_effect``,
  ``resolve_location``, ``persist_agent_locations_if_changed``); each field
  goes once its function has a home in ``gaworld``.

Everything else is imported from where it lives, so a test that wants to
intercept, say, ``choose_action`` inside a run patches ``gaworld.sim._stages``.
``builtin_stages(scope)`` binds the scope and returns the name -> stage map
``StagePipeline.from_config`` expects.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

import numpy as np

from gaworld.apps.visualizer import build_agent_step_payload
from gaworld.behavior.dynamic import insert_activity_into_schedule as dynamic_insert_activity
from gaworld.cognition.realism import (
    compute_episode_salience,
    infer_episode_tags,
    infer_interaction_signal,
    relationship_update,
    update_habits_from_episode,
    update_needs,
)
from gaworld.distributed.comm import (
    extract_sender_agent_ids,
    format_inbox_context,
)
from gaworld.goals import match_goal_relevance
from gaworld.kernel import ActionRequest
from gaworld.logging_setup import get_logger
from gaworld.memory.experience import append_agent_episode
from gaworld.memory.store import (
    append_agent_log,
    vector_db_add_entry,
)
from gaworld.sim._action import (
    choose_action,
    ensure_action_space_for_activity,
    get_location_action_bias,
    save_action_space,
)
from gaworld.sim._cognition import (
    get_social_context,
    perception,
    social_influence,
)
from gaworld.sim._location import move_agent
from gaworld.sim._memory_recall import (
    _build_decision_reference_bundle,
    _build_recall_context_labels,
    _is_location_time_relevant,
    evoke_memory,
    maybe_review_memories,
)
from gaworld.sim._schedule import (
    _activity_commitment_level,
    apply_schedule_override,
    format_plan_text,
    format_reflection_text,
    get_activity_for_time,
    replan_affected_interval,
    reshape_day_for_life_event,
    resolve_life_event_activities,
)
from gaworld.sim._step import (
    _event_severity,
    _pick_reshape_life_event,
    format_transient_thought,
    maybe_adjust_activity,
    maybe_generate_transient_thought,
)
from gaworld.sim._utils import (
    _clean_env_context,
    _clean_reflection,
    _minutes_to_time_str,
    _time_str_to_minutes,
)

_LOG = get_logger("gaworld.sim")


@dataclass
class StepScope:
    """What the stages read besides ``agent``, ``step`` and ``sim`` (see the module docstring)."""

    # settings, from generative_city_sim
    config: Any = None
    distributed_config: Any = None
    goals_config: Any = None
    goals_enabled: Any = None
    human_realism_config: Any = None
    human_realism_enabled: Any = None
    life_event_reshape_enabled: Any = None
    life_event_reshape_window: Any = None
    log_simple: Any = None
    replan_defer_gap: Any = None
    replan_enabled: Any = None
    replan_window_minutes: Any = None
    stateful: Any = None
    # helpers still in generative_city_sim
    planning: Any = None
    reflection: Any = None
    update_state: Any = None
    infer_event_effect: Any = None
    resolve_location: Any = None
    persist_agent_locations_if_changed: Any = None
    # the run
    agents: Any = None
    agents_by_id: Any = None
    city_map: Any = None
    city_map_text: Any = None
    actions: Any = None
    hook_bus: Any = None
    extension_state: Any = None
    distributed_client: Any = None
    llm_budget_by_agent: Any = None
    state_history: Any = None
    visualizer: Any = None
    news_cache: Any = None
    # the day
    day: Any = None
    schedule_map: Any = None
    daily_logs: Any = None
    # the tick
    time_str: Any = None
    step_minutes: Any = None
    policy: Any = None
    env_events: Any = None
    env_context: Any = None
    distributed_inbox: Any = None
    frame_steps: Any = None

    def set(self, **values: Any) -> None:
        """Assign fields; an unknown name is a bug at the call site, so it raises."""
        for name, value in values.items():
            if name not in self.__dataclass_fields__:
                raise AttributeError(f"StepScope has no field {name!r}")
            setattr(self, name, value)


def _stage_prepare(agent, step, sim, *, scope):
    agent_id = agent["id"]
    # K3e: event-producer plugins contribute per-agent env events here
    # (life events, ...); contributions merge with the day/tick env feed.
    # The life-events plugin also records its events and exposes them as
    # step["life_events"].
    agent_env_events = list(step.get("_tick_env_events", scope.env_events) or []) + scope.hook_bus.collect(
        "env.events.compose",
        agent=agent,
        day=scope.day,
        time_str=scope.time_str,
        step=step,
        daily_logs=scope.daily_logs,
    )
    scheduled_activity = get_activity_for_time(scope.schedule_map[agent_id], scope.time_str)
    inbox_messages = scope.distributed_inbox.get(agent_id, [])
    social_context = get_social_context(agent, scope.agents_by_id)
    inbox_context = format_inbox_context(
        inbox_messages,
        max_items=int(scope.distributed_config.get("max_inbound_per_step", 3)),
    )
    if inbox_context:
        social_context = f"{social_context} {inbox_context}".strip()
        inbox_log = f"[DistributedInbox {agent['name']} @ {scope.time_str}] {inbox_context}\n"
        scope.daily_logs[agent_id] += inbox_log
        append_agent_log(agent, inbox_log)
        vector_db_add_entry(
            agent_id,
            "distributed_in",
            inbox_context,
            sim_day=scope.day,
            sim_time=scope.time_str,
        )

    policy_desc = None
    if scope.policy:
        policy_desc = scope.policy.get("description") or scope.policy.get("name")
    step["_state_before"] = dict(agent.get("state", {}))
    step.update(
        {
            "scheduled_activity": scheduled_activity,
            "activity": scheduled_activity,
            "social_context": social_context,
            "policy_desc": policy_desc,
            "life_events": step.get("life_events", []),
        }
    )
    scope.hook_bus.emit(
        "on_agent_pre_step",
        day=scope.day,
        time_str=scope.time_str,
        config=scope.config,
        agent=agent,
        agents=scope.agents,
        agents_by_id=scope.agents_by_id,
        city_map=scope.city_map,
        city_map_text=scope.city_map_text,
        schedule_map=scope.schedule_map,
        actions=scope.actions,
        env_events=agent_env_events,
        env_context=scope.env_context,
        policy=scope.policy,
        step=step,
        extension_state=scope.extension_state,
    )
    scheduled_activity = step.get("scheduled_activity", scheduled_activity)
    # K3e: the "人生事件：…" context line now rides perception.compose
    # (LifeEventsPlugin) and renders after the local-physical snippet.
    step_env_context = scope.env_context
    step["_env_events"] = agent_env_events
    step["_inbox_messages"] = inbox_messages
    step["_env_context"] = step_env_context


def _stage_perceive(agent, step, sim, *, scope):
    scheduled_activity = step.get("scheduled_activity", "")
    social_context = step.get("social_context", "")
    policy_desc = step.get("policy_desc")
    agent_env_events = step.get("_env_events", [])
    step_env_context = step.get("_env_context", "")
    # K4: surface Controller denials from the previous step so the
    # agent can perceive why its action didn't happen.
    _denials = agent.pop("_action_denials", None)
    if _denials:
        _denial_text = "；".join(str(d) for d in _denials)
        step_env_context = (
            f"{step_env_context}\n刚才的行动受阻：{_denial_text}"
            if step_env_context
            else f"刚才的行动受阻：{_denial_text}"
        )
    # K3g: the local-physical snapshot (agent["_local_physical"] + the
    # "身边的物理环境" line) rides perception.compose at priority 30.
    # K2: plugins contribute perception snippets (collect semantics —
    # with no subscribers this is a no-op and behavior is unchanged).
    for _snippet in scope.hook_bus.collect(
        "perception.compose",
        agent=agent,
        day=scope.day,
        time_str=scope.time_str,
        scheduled_activity=scheduled_activity,
        env_context=step_env_context,
        social_context=social_context,
        env_events=agent_env_events,
        policy=scope.policy,
        policy_desc=policy_desc,
        news=scope.news_cache[:5],
    ):
        _snippet = str(_snippet).strip()
        if _snippet:
            step_env_context = f"{step_env_context}\n{_snippet}" if step_env_context else _snippet
    step["_env_context"] = step_env_context
    # K3c: plugins contribute prompt sections rendered inside the
    # perception prompt (e.g. the Skill library block).
    extra_sections = scope.hook_bus.collect(
        "perception.sections",
        agent=agent,
        day=scope.day,
        time_str=scope.time_str,
        scheduled_activity=scheduled_activity,
        social_context=social_context,
    )
    # Core cognition loop: perceive -> plan -> (maybe) change routine -> act -> reflect.
    step["_perception"] = perception(
        agent,
        scope.time_str,
        social_context,
        step_env_context,
        policy_desc if scope.policy else None,
        extra_sections=extra_sections,
    )


def _stage_interrupts(agent, step, sim, *, scope):
    scheduled_activity = step.get("scheduled_activity", "")
    # K3i: interrupt/thought computation rides the interrupts.compose
    # filter (DynamicBehaviorPlugin; engines return {} for "no change",
    # never None). None here means no producer ran — fall back to the
    # legacy spontaneity path, matching the old enabled/disabled branch.
    transient_thought = scope.hook_bus.filter(
        "interrupts.compose",
        None,
        agent=agent,
        step=step,
        day=scope.day,
        time_str=scope.time_str,
    )
    if transient_thought is None:
        transient_thought = maybe_generate_transient_thought(
            agent,
            scope.time_str,
            scheduled_activity,
            step.get("_perception", ""),
            env_events=step.get("_env_events", []),
            policy_desc=step.get("policy_desc"),
            social_context=step.get("social_context", ""),
            inbox_messages=step.get("_inbox_messages", []),
        )
    step["_transient_thought"] = transient_thought


def _stage_plan(agent, step, sim, *, scope):
    scheduled_activity = step.get("scheduled_activity", "")
    perc = step.get("_perception", "")
    social_context = step.get("social_context", "")
    step_recollections = step.setdefault("_recollections", [])
    plan_commitment = _activity_commitment_level(scheduled_activity)
    plan_prefetch_refs = _build_decision_reference_bundle(
        agent,
        scheduled_activity,
        time_str=scope.time_str,
        location=agent.get("locations", {}).get("current", ""),
        env_context=step.get("_env_context", ""),
        env_events=step.get("_env_events", []),
        policy_desc=step.get("policy_desc"),
        social_context=social_context,
    )
    plan_recall = evoke_memory(
        agent,
        "planning",
        scheduled_activity,
        perc,
        social_context if plan_prefetch_refs.get("social_network_relevant") else "",
        plan_prefetch_refs.get("physical_env_text", "")
        if plan_prefetch_refs.get("physical_env_relevant")
        else "",
        plan_prefetch_refs.get("social_env_text", "")
        if plan_prefetch_refs.get("social_env_relevant")
        else "",
        context_labels=_build_recall_context_labels(
            agent,
            activity=scheduled_activity,
            time_str=scope.time_str if plan_prefetch_refs.get("location_time_relevant") else "",
            location=agent.get("locations", {}).get("current", "")
            if plan_prefetch_refs.get("location_time_relevant")
            else "",
            commitment_level=plan_commitment,
        ),
    )
    if plan_recall.get("recollection"):
        step_recollections.append(plan_recall["recollection"])
    plan_refs = dict(plan_prefetch_refs)
    plan_refs["memory_hint"] = plan_recall.get("hint", "")
    plan_refs["recollection"] = plan_recall.get("recollection", "")
    plan_refs["transient_thought"] = step.get("_transient_thought")
    plan = scope.planning(agent, perc, recall_context=plan_recall, decision_refs=plan_refs)
    step["_plan_struct"] = plan
    step["_plan_text"] = format_plan_text(plan)


def _stage_adjust_activity(agent, step, sim, *, scope):
    agent_id = agent["id"]
    scheduled_activity = step.get("scheduled_activity", "")
    transient_thought = step.get("_transient_thought")
    activity, change_reason, changed = maybe_adjust_activity(
        agent,
        scope.time_str,
        scheduled_activity,
        step.get("_perception", ""),
        step.get("_plan_text", ""),
        step.get("_env_context", ""),
        step.get("_env_events", []),
        step.get("policy_desc"),
        transient_thought=transient_thought,
        social_context=step.get("social_context", ""),
    )
    # --- Dynamic behaviour system: apply if LLM didn't change ---
    _dyn_result = transient_thought.get("dynamic_result") if isinstance(transient_thought, dict) else None
    if _dyn_result and not changed and _dyn_result.get("changed"):
        activity = _dyn_result["activity"]
        change_reason = _dyn_result.get("reason", "动态行为系统触发")
        changed = True
    # Apply mood delta from dynamic system
    if _dyn_result and _dyn_result.get("mood_delta"):
        _mood_d = float(_dyn_result["mood_delta"])
        state = agent.get("state", {})
        state["emotion"] = max(0.0, min(1.0, float(state.get("emotion", 0.5)) + _mood_d))
    # Apply schedule insertion from dynamic system
    if _dyn_result and _dyn_result.get("schedule_insert") and changed:
        _si = _dyn_result["schedule_insert"]
        _sched_tuples = [
            (s.get("time", ""), s.get("activity", "")) if isinstance(s, dict) else s
            for s in scope.schedule_map.get(agent_id, [])
        ]
        _new_sched = dynamic_insert_activity(
            _sched_tuples,
            _si["insert_time"],
            _si["activity"],
            duration_minutes=_si.get("duration_minutes", 30),
            resumable=True,
            original_activity=_si.get("original_activity", scheduled_activity),
        )
        # Convert back to schedule format used by the simulator
        scope.schedule_map[agent_id] = [{"time": t, "activity": a} for t, a in _new_sched]
    # Log social encounters from dynamic system
    if _dyn_result and _dyn_result.get("social_encounters"):
        for _enc in _dyn_result["social_encounters"]:
            _LOG.debug("agent_%s social_encounter: %s", agent_id, _enc.get("activity", ""))

    # A pre-step hook may force an activity (e.g. economy income-seek);
    # it wins only when it actually changed the seeded value. The pre-K2
    # code re-read step["activity"] unconditionally, letting the seeded
    # scheduled_activity clobber the LLM/dynamic adjustment above —
    # which silently disabled routine changes on the mainline path.
    hook_activity = step.get("activity", scheduled_activity)
    if hook_activity != scheduled_activity:
        activity = hook_activity
    if activity != scheduled_activity and not changed:
        changed = True
        hook_reason = str(step.get("change_reason", "")).strip()
        if hook_reason:
            change_reason = hook_reason
    if changed:
        scope.schedule_map[agent_id] = apply_schedule_override(
            scope.schedule_map[agent_id],
            scope.time_str,
            activity,
        )
        updated = ensure_action_space_for_activity(agent, scope.actions[agent_id], activity)
        if updated and scope.stateful:
            save_action_space(agent_id, scope.actions[agent_id])

    # P3: a *persistent* anomaly (non-resumable physical / emergency
    # reaction) makes the disrupted activity unworkable for a while —
    # defer its upcoming slots rather than only patching this step.
    if scope.replan_enabled and changed and isinstance(_dyn_result, dict):
        _itr = _dyn_result.get("interrupt") or {}
        _extra = _itr.get("extra", {}) if isinstance(_itr, dict) else {}
        _persistent_anomaly = (
            isinstance(_itr, dict)
            and not _itr.get("resumable", True)
            and (bool(_extra.get("anomaly")) or _extra.get("event_type") in ("emergency", "local_physical"))
        )
        _cur_min = _time_str_to_minutes(scope.time_str)
        if _persistent_anomaly and scheduled_activity and _cur_min is not None:
            _sched_tuples = [
                (s.get("time", ""), s.get("activity", "")) if isinstance(s, dict) else tuple(s)
                for s in scope.schedule_map.get(agent_id, [])
            ]
            _new_sched, _replan_changes = replan_affected_interval(
                _sched_tuples,
                scope.time_str,
                _minutes_to_time_str(min(24 * 60 - 1, _cur_min + scope.replan_window_minutes)),
                is_affected=lambda t, a, _d=scheduled_activity: a == _d,
                defer=True,
                defer_gap_minutes=scope.replan_defer_gap,
            )
            if _replan_changes:
                scope.schedule_map[agent_id] = _new_sched
                _replan_log = (
                    f"[Replan {scope.time_str}] 因突发异常重排日程，"
                    f"顺延 {len(_replan_changes)} 项（{scheduled_activity}）\n"
                )
                scope.daily_logs[agent_id] += _replan_log
                append_agent_log(agent, _replan_log)
    # Part B: a serious, routine-impacting life event (illness, family
    # emergency, being framed) deterministically bends the rest of the day
    # around it — bypassing the probabilistic routine-change gate above,
    # which a high-commitment activity's resistance would usually win.
    if scope.life_event_reshape_enabled:
        _reshape_ev = _pick_reshape_life_event(step.get("life_events", []))
        if _reshape_ev is not None:
            _sched_tuples = [
                (s.get("time", ""), s.get("activity", "")) if isinstance(s, dict) else tuple(s)
                for s in scope.schedule_map.get(agent_id, [])
            ]
            _imm, _fol = resolve_life_event_activities(_reshape_ev)
            _new_sched, _reshape_changes = reshape_day_for_life_event(
                _sched_tuples,
                scope.time_str,
                _reshape_ev,
                window_minutes=scope.life_event_reshape_window,
                immediate_activity=_imm,
                follow_activity=_fol,
            )
            if _reshape_changes:
                scope.schedule_map[agent_id] = [{"time": t, "activity": a} for t, a in _new_sched]
                activity = _imm
                changed = True
                change_reason = f"人生事件：{_reshape_ev.get('title', '突发事件')}"
                for _evt_activity in (_imm, _fol):
                    _upd = ensure_action_space_for_activity(agent, scope.actions[agent_id], _evt_activity)
                    if _upd and scope.stateful:
                        save_action_space(agent_id, scope.actions[agent_id])
                _reshape_log = (
                    f"[LifeReshape {scope.time_str}] 因“{_reshape_ev.get('title', '突发事件')}”"
                    f"（严重度 {_event_severity(_reshape_ev):.2f}）重排当天，"
                    f"改动 {len(_reshape_changes)} 项\n"
                )
                scope.daily_logs[agent_id] += _reshape_log
                append_agent_log(agent, _reshape_log)

    # K3i: observers react to the applied interrupt result (e.g. the
    # spatial-preferences plugin records location-bound anomalies).
    scope.hook_bus.emit(
        "interrupt.applied",
        agent=agent,
        step=step,
        dyn_result=_dyn_result,
        changed=changed,
        scheduled_activity=scheduled_activity,
        day=scope.day,
        time_str=scope.time_str,
    )
    step["_activity"] = activity
    step["_changed"] = changed
    step["_change_reason"] = change_reason


def _stage_move(agent, step, sim, *, scope):
    activity = step.get("_activity", step.get("scheduled_activity", ""))
    desired_location = scope.resolve_location(agent, activity, scope.time_str, scope.city_map)
    # K3i: plugins may rewrite the resolved location (aversion-aware
    # redirection rides this filter).
    desired_location = scope.hook_bus.filter(
        "location.resolve",
        desired_location,
        agent=agent,
        activity=activity,
        day=scope.day,
        time_str=scope.time_str,
    )
    # K4: structured moves pass the Controller's validation gate. A
    # denial keeps the agent where it is (move_agent falls back to the
    # origin) and surfaces the reason in its next perception.
    if desired_location:
        _verdict = sim.controller.validate(
            ActionRequest(
                agent_id=agent["id"],
                name="move",
                params={"to": desired_location, "activity": activity},
            ),
            sim,
        )
        if not _verdict.allowed:
            agent.setdefault("_action_denials", []).append(
                f"你想前往【{desired_location}】，但没能成行：{_verdict.reason}"
            )
            desired_location = None
        elif _verdict.rewritten is not None:
            desired_location = _verdict.rewritten.params.get("to", desired_location)
    movement = move_agent(
        agent,
        desired_location=desired_location,
        activity=activity,
        time_str=scope.time_str,
        step_minutes=scope.step_minutes,
        city_map=scope.city_map,
    )
    scope.hook_bus.emit(
        "agent.moved",
        agent=agent,
        activity=activity,
        movement=movement,
        city_map=scope.city_map,
        day=scope.day,
        time_str=scope.time_str,
    )
    if scope.stateful:
        scope.persist_agent_locations_if_changed(agent)
    step["_movement"] = movement
    step["_location"] = movement["display_location"]
    step["_resolved_location"] = movement["resolved_location"]
    step["_travel"] = movement["travel"]


def _stage_select_action(agent, step, sim, *, scope):
    agent_id = agent["id"]
    activity = step.get("_activity", step.get("scheduled_activity", ""))
    movement = step.get("_movement", {})
    travel = step.get("_travel", {})
    resolved_location = step.get("_resolved_location", "")
    perc = step.get("_perception", "")
    plan_text = step.get("_plan_text", "")
    step_recollections = step.setdefault("_recollections", [])
    effective_activity = activity
    if travel.get("status") in {"departed", "in_transit"}:
        act = f"乘坐{travel.get('mode', '交通工具')}移动"
        action_meta = {
            "decision_driver": "时空约束",
            "commitment_level": _activity_commitment_level(activity),
            "scores": {act: {"weight": 1.0, "components": {}, "styles": ["quick"]}},
        }
        outcome = (
            f"从【{resolved_location}】前往【{movement['target_location']}】，"
            f"使用【{travel.get('mode', '未知方式')}】，路程约 {travel.get('distance_km', 0.0):.1f} km，"
            f"预计 {travel.get('minutes', 0)} 分钟"
        )
        location_bias = {}
        effective_activity = f"前往{movement['target_location']}"
    else:
        location_bias = get_location_action_bias(
            agent,
            resolved_location,
            scope.city_map_text,
            scope.actions[agent_id],
        )
        location_time_relevant = _is_location_time_relevant(
            activity, time_str=scope.time_str, location=resolved_location
        )
        action_prefetch_refs = _build_decision_reference_bundle(
            agent,
            activity,
            time_str=scope.time_str,
            location=resolved_location,
            env_context=step.get("_env_context", ""),
            env_events=step.get("_env_events", []),
            policy_desc=step.get("policy_desc"),
            social_context=step.get("social_context", ""),
        )
        action_recall = evoke_memory(
            agent,
            "action",
            activity,
            perc,
            plan_text,
            step.get("social_context", "") if action_prefetch_refs.get("social_network_relevant") else "",
            action_prefetch_refs.get("physical_env_text", "")
            if action_prefetch_refs.get("physical_env_relevant")
            else "",
            action_prefetch_refs.get("social_env_text", "")
            if action_prefetch_refs.get("social_env_relevant")
            else "",
            resolved_location if location_time_relevant else "",
            scope.time_str if location_time_relevant else "",
            context_labels=_build_recall_context_labels(
                agent,
                activity=activity,
                time_str=scope.time_str if location_time_relevant else "",
                location=resolved_location if location_time_relevant else "",
                commitment_level=_activity_commitment_level(activity),
            ),
        )
        if action_recall.get("recollection"):
            step_recollections.append(action_recall["recollection"])
        action_refs = dict(action_prefetch_refs)
        action_refs["memory_hint"] = action_recall.get("hint", "")
        action_refs["recollection"] = action_recall.get("recollection", "")
        action_refs["transient_thought"] = step.get("_transient_thought")
        act, action_meta = choose_action(
            agent,
            activity,
            scope.actions[agent_id],
            context=f"{activity} {perc} {plan_text}",
            location_bias=location_bias,
            location=resolved_location,
            time_str=scope.time_str,
            recall_context=action_recall,
            decision_refs=action_refs,
            return_debug=True,
            candidate_provider=lambda resident, current_activity: scope.hook_bus.collect(
                "action.candidates",
                agent=resident,
                activity=current_activity,
                day=scope.day,
                time_str=scope.time_str,
            ),
        )
        # K2: plugins may rewrite the selected action (filter
        # semantics — with no subscribers the value passes through).
        act = scope.hook_bus.filter(
            "action.selected",
            act,
            agent=agent,
            activity=activity,
            day=scope.day,
            time_str=scope.time_str,
            location=resolved_location,
        )
        outcome = f"在【{activity}】中执行了【{act}】"
        # K3h: plugins may rewrite the outcome (real-work dispatch and
        # artifact absorption ride this filter).
        outcome = scope.hook_bus.filter(
            "action.outcome",
            outcome,
            agent=agent,
            activity=activity,
            action=act,
            day=scope.day,
            time_str=scope.time_str,
            location=resolved_location,
        )
    step["_effective_activity"] = effective_activity
    step["_act"] = act
    step["_action_meta"] = action_meta
    step["_outcome"] = outcome


def _stage_reflect(agent, step, sim, *, scope):
    effective_activity = step.get("_effective_activity", step.get("_activity", ""))
    act = step.get("_act", "")
    outcome = step.get("_outcome", "")
    resolved_location = step.get("_resolved_location", "")
    action_meta = step.get("_action_meta", {})
    step_recollections = step.setdefault("_recollections", [])
    reflection_recall = evoke_memory(
        agent,
        "reflection",
        effective_activity,
        act,
        outcome,
        scope.time_str
        if _is_location_time_relevant(effective_activity, time_str=scope.time_str, location=resolved_location)
        else "",
        context_labels=_build_recall_context_labels(
            agent,
            activity=effective_activity,
            time_str=scope.time_str
            if _is_location_time_relevant(
                effective_activity, time_str=scope.time_str, location=resolved_location
            )
            else "",
            location=resolved_location
            if _is_location_time_relevant(
                effective_activity, time_str=scope.time_str, location=resolved_location
            )
            else "",
            commitment_level=action_meta.get(
                "commitment_level", _activity_commitment_level(effective_activity)
            ),
        ),
    )
    if reflection_recall.get("recollection"):
        step_recollections.append(reflection_recall["recollection"])
    refl = scope.reflection(agent, outcome, recall_context=reflection_recall)
    step["_refl_struct"] = refl
    step["_refl_text"] = format_reflection_text(refl)
    if scope.human_realism_enabled:
        update_needs(
            agent,
            scope.time_str,
            effective_activity,
            cfg=scope.human_realism_config,
            changed=step.get("_changed", False),
            travel=step.get("_travel", {}),
        )


def _stage_update_state(agent, step, sim, *, scope):
    agent_env_events = step.get("_env_events", [])
    policy_desc = step.get("policy_desc")
    if agent_env_events:
        for ev in agent_env_events:
            inferred = scope.infer_event_effect(
                agent, ev.get("description", ev.get("name", "")), ev.get("type", "event")
            )
            for k, v in inferred.items():
                agent["state"][k] += v
    # K3e: plugins apply their own state deltas here (life-event
    # state_effects, ...), before social influence and the state update.
    scope.hook_bus.emit("state.effects", agent=agent, step=step, day=scope.day, time_str=scope.time_str)

    if scope.policy:
        inferred = scope.infer_event_effect(agent, policy_desc, "policy")
        for k, v in inferred.items():
            agent["state"][k] += v

    social_influence(agent, scope.agents_by_id)
    scope.update_state(agent)


def _stage_broadcast(agent, step, sim, *, scope):
    agent_id = agent["id"]
    sent_remote_messages = []
    if scope.distributed_client.enabled:
        sent_remote_messages = scope.distributed_client.send_agent_messages(
            agent,
            day=scope.day,
            time_str=scope.time_str,
            activity=step.get("_effective_activity", ""),
            reflection=step.get("_refl_text", ""),
            outcome=step.get("_outcome", ""),
        )
        if sent_remote_messages:
            sent_summary = "; ".join(
                f"to#{int(msg.get('to_agent', 0))}:{str(msg.get('text', ''))[:40]}"
                for msg in sent_remote_messages
                if isinstance(msg, dict)
            )
            if sent_summary:
                sent_log = f"[DistributedOutbox {agent['name']} @ {scope.time_str}] {sent_summary}\n"
                scope.daily_logs[agent_id] += sent_log
                append_agent_log(agent, sent_log)
                vector_db_add_entry(
                    agent_id,
                    "distributed_out",
                    sent_summary,
                    sim_day=scope.day,
                    sim_time=scope.time_str,
                )


def _stage_memorize(agent, step, sim, *, scope):
    agent_id = agent["id"]
    scheduled_activity = step.get("scheduled_activity", "")
    effective_activity = step.get("_effective_activity", "")
    act = step.get("_act", "")
    outcome = step.get("_outcome", "")
    refl_text = step.get("_refl_text", "")
    refl = step.get("_refl_struct", {})
    plan = step.get("_plan_struct", {})
    plan_text = step.get("_plan_text", "")
    perc = step.get("_perception", "")
    transient_thought = step.get("_transient_thought")
    agent_env_events = step.get("_env_events", [])
    agent_life_events = step.get("life_events", [])
    policy_desc = step.get("policy_desc")
    state_before = step.get("_state_before", {})
    travel = step.get("_travel", {})
    movement = step.get("_movement", {})
    location = step.get("_location", "")
    action_meta = step.get("_action_meta", {})
    change_reason = step.get("_change_reason")
    step_recollections = step.setdefault("_recollections", [])
    if scope.human_realism_enabled:
        partners = list(agent.get("_recent_social_partners", []))
        for sender_id in extract_sender_agent_ids(step.get("_inbox_messages", [])):
            if sender_id not in partners:
                partners.append(sender_id)
        signal = infer_interaction_signal(refl_text)
        for pid in partners:
            relationship_update(agent, pid, signal, scope.human_realism_config)
        state_after = dict(agent.get("state", {}))
        delta = {}
        for key, before_v in state_before.items():
            after_v = state_after.get(key)
            if isinstance(before_v, (int, float)) and isinstance(after_v, (int, float)):
                delta[key] = float(after_v) - float(before_v)
        thought_intensity = (
            float(transient_thought.get("intensity", 0.0)) if isinstance(transient_thought, dict) else 0.0
        )
        event_intensity = min(
            1.0,
            0.2 * len(agent_env_events) + (0.2 if scope.policy else 0.0) + 0.18 * thought_intensity,
        )
        recent_actions = [e.get("action", "") for e in agent.get("episodes", [])[-20:] if isinstance(e, dict)]
        novelty = 1.0 if act not in recent_actions else 0.2
        priorities = agent.get("intentions", {}).get("priorities", [])
        goal_relevance = 0.2
        for p in priorities:
            if p and (p in effective_activity or p in plan_text or p in refl_text):
                goal_relevance = 0.8
                break
        if scope.goals_enabled:
            goal_relevance = max(
                goal_relevance,
                match_goal_relevance(
                    agent.get("goals"),
                    effective_activity,
                    plan_text,
                    refl_text,
                    config=scope.goals_config,
                ),
            )
        salience = compute_episode_salience(
            delta.get("stress", 0.0),
            event_intensity,
            novelty,
            goal_relevance,
        )
        tags = infer_episode_tags(
            effective_activity,
            act,
            refl_text,
            env_events=[ev.get("description", ev.get("name", "")) for ev in agent_env_events],
            policy_event=policy_desc if scope.policy else "",
        )
        need_snapshot = {
            "energy": round(float(state_after.get("energy", 0.75)), 3),
            "hunger": round(float(state_after.get("hunger", 0.25)), 3),
            "social_need": round(float(state_after.get("social_need", 0.40)), 3),
            "fatigue_debt": round(float(state_after.get("fatigue_debt", 0.20)), 3),
            "self_control": round(float(state_after.get("self_control", 0.60)), 3),
            "time_pressure": round(float(state_after.get("time_pressure", 0.25)), 3),
        }
        episode = {
            "episode_id": str(uuid.uuid4()),
            "day": scope.day,
            "time": scope.time_str,
            "scheduled_activity": scheduled_activity,
            "final_activity": effective_activity,
            "action": act,
            "location": location,
            "target_location": movement.get("target_location", ""),
            "travel": travel,
            "env_events": [ev.get("description", ev.get("name", "")) for ev in agent_env_events],
            "life_events": [dict(event) for event in agent_life_events],
            "policy_event": policy_desc if scope.policy else "",
            "social_partners": partners,
            "perception": perc,
            "plan": plan_text,
            "plan_struct": plan,
            "outcome": outcome,
            "reflection": refl_text,
            "reflection_struct": refl,
            "transient_thought": transient_thought or {},
            "state_before": state_before,
            "state_after": state_after,
            "need_snapshot": need_snapshot,
            "delta": delta,
            "tags": tags,
            "recollections": list(step_recollections),
            "salience": salience,
            "valence": float(np.clip(delta.get("emotion", 0.0), -1.0, 1.0)),
            "decision_driver": action_meta.get("decision_driver", "惯性延续"),
            "change_reason": change_reason or "",
            "commitment_level": action_meta.get(
                "commitment_level", _activity_commitment_level(effective_activity)
            ),
            "expected_outcome": str(plan.get("expected_outcome", "")).strip(),
            "created_at_day": scope.day,
        }
        episode["growth_matches"] = []
        episode["growth_progress"] = {"matches": [], "minutes": 0, "level_changes": {}}
        # K3d: the interests plugin fills the growth keys and updates
        # the agent's growth profile on this event; the empty defaults
        # above keep the episode schema stable when it's disabled.
        scope.hook_bus.emit(
            "episode.compose",
            agent=agent,
            episode=episode,
            step_minutes=scope.step_minutes,
            day=scope.day,
            time_str=scope.time_str,
        )
        agent.setdefault("episodes", []).append(episode)
        update_habits_from_episode(agent, episode, scope.human_realism_config)
        append_agent_episode(agent_id, episode)
        episode_text = (
            f"Day {scope.day} {scope.time_str} {effective_activity}/{act} @ {location} "
            f"driver={episode['decision_driver']} commitment={episode['commitment_level']} "
            f"thought={format_transient_thought(transient_thought) if transient_thought else 'none'} "
            f"needs={json.dumps(need_snapshot, ensure_ascii=False)} "
            f"tags={','.join(tags)} salience={salience:.2f} reflection={refl_text}"
        )
        vector_db_add_entry(agent_id, "episode", episode_text, sim_day=scope.day, sim_time=scope.time_str)
        agent["last_activity"] = effective_activity
        agent["last_action"] = act
        memory_review = maybe_review_memories(
            agent,
            scope.day,
            scope.time_str,
            recent_episode=episode,
            llm_budget_ctx=scope.llm_budget_by_agent.get(agent_id),
        )
    else:
        memory_review = ""
        agent["last_activity"] = effective_activity
        agent["last_action"] = act
    agent["last_reflection"] = refl_text
    for metric in scope.state_history[agent["id"]]:
        scope.state_history[agent["id"]][metric].append(agent["state"][metric])
    step["_memory_review"] = memory_review


def _stage_record(agent, step, sim, *, scope):
    scheduled_activity = step.get("scheduled_activity", "")
    effective_activity = step.get("_effective_activity", "")
    act = step.get("_act", "")
    outcome = step.get("_outcome", "")
    refl_text = step.get("_refl_text", "")
    refl = step.get("_refl_struct", {})
    plan = step.get("_plan_struct", {})
    plan_text = step.get("_plan_text", "")
    perc = step.get("_perception", "")
    transient_thought = step.get("_transient_thought")
    step_env_context = step.get("_env_context", "")
    changed = step.get("_changed", False)
    change_reason = step.get("_change_reason")
    location = step.get("_location", "")
    resolved_location = step.get("_resolved_location", "")
    movement = step.get("_movement", {})
    travel = step.get("_travel", {})
    action_meta = step.get("_action_meta", {})
    memory_review = step.get("_memory_review", "")
    step_recollections = step.setdefault("_recollections", [])

    # --- activity header (fold RoutineChange into one line) ---
    if changed:
        reason_text = change_reason or "临时改变"
        _activity_header = f"{scheduled_activity} → {effective_activity} ({reason_text})"
    else:
        _activity_header = scheduled_activity

    # --- optional lines (only rendered when non-empty) ---
    recall_line = ""
    unique_recollections = []
    for item in step_recollections:
        text = str(item).strip()
        if text and text not in unique_recollections:
            unique_recollections.append(text)
    if unique_recollections:
        recall_line = f"Recall: {' | '.join(unique_recollections)}\n"
    transient_thought_line = ""
    if transient_thought:
        transient_thought_line = f"Thought: {format_transient_thought(transient_thought)}\n"
    memory_review_line = f"Review: {memory_review}\n" if memory_review else ""
    decision_line = ""
    if action_meta.get("decision_driver"):
        decision_line = (
            f"Driver: {action_meta.get('decision_driver')} "
            f"(commit={action_meta.get('commitment_level', '')})\n"
        )
    needs_line = ""
    if scope.human_realism_enabled:
        needs_line = (
            "Needs: "
            f"nrg={agent['state'].get('energy', 0.75):.2f} "
            f"hun={agent['state'].get('hunger', 0.25):.2f} "
            f"soc={agent['state'].get('social_need', 0.40):.2f} "
            f"fat={agent['state'].get('fatigue_debt', 0.20):.2f} "
            f"ctrl={agent['state'].get('self_control', 0.60):.2f} "
            f"tprs={agent['state'].get('time_pressure', 0.25):.2f}\n"
        )

    # --- compact location + travel (collapsed to 1 line) ---
    _travel_status = travel.get("status", "stationary")
    if _travel_status != "stationary":
        _travel_info = (
            f"  [{travel.get('mode', '?')} "
            f"{travel.get('distance_km', 0.0):.1f}km "
            f"{travel.get('minutes', 0)}min]"
        )
        _loc_line = f"Loc: {location} → {resolved_location}{_travel_info}\n"
    else:
        _travel_info = ""
        _loc_line = f"Loc: {resolved_location}\n"

    # --- env context (omitted when empty) ---
    _env_line = f"Env: {step_env_context}\n" if step_env_context else ""

    # -------------------------------------------------------
    # Simple mode: one clean block per tick, Chinese-only,
    # stripping LLM reasoning leakage and repeated boilerplate.
    # Verbose mode: full details for debugging.
    # -------------------------------------------------------
    if scope.log_simple:
        _env_simple = _clean_env_context(step_env_context)
        _refl_simple = _clean_reflection(refl_text)
        log = (
            f"\n── [{agent['name']} @ {scope.time_str}] {_activity_header} ──\n"
            f"Loc: {resolved_location}{_travel_info}\n"
            + (f"Env: {_env_simple}\n" if _env_simple else "")
            + f"Act: {act}\n"
            f"Refl: {_refl_simple}\n"
        )
    else:
        log = (
            f"\n── [{agent['name']} @ {scope.time_str}] {_activity_header} ──\n"
            f"{_loc_line}"
            f"{_env_line}"
            f"Perc: {perc}\n"
            f"Plan: {plan_text}\n"
            f"{transient_thought_line}"
            f"{recall_line}"
            f"Act: {act}  |  Out: {outcome}\n"
            f"{decision_line}"
            f"{needs_line}"
            f"Refl: {refl_text}\n"
            f"{memory_review_line}"
        )
    print(log)
    scope.daily_logs[agent["id"]] += log
    append_agent_log(agent, log)
    vector_db_add_entry(agent["id"], "log", log, sim_day=scope.day, sim_time=scope.time_str)
    vector_db_add_entry(agent["id"], "plan", plan_text, sim_day=scope.day, sim_time=scope.time_str)
    vector_db_add_entry(agent["id"], "reflection", refl_text, sim_day=scope.day, sim_time=scope.time_str)
    vector_db_add_entry(agent["id"], "action", outcome, sim_day=scope.day, sim_time=scope.time_str)
    step.update(
        {
            "perception": perc,
            "plan": plan_text,
            "plan_struct": plan,
            "transient_thought": transient_thought or {},
            "activity": effective_activity,
            "action": act,
            "outcome": outcome,
            "reflection": refl_text,
            "reflection_struct": refl,
            "log": log,
            "env_context": step_env_context,
            "changed": changed,
            "change_reason": change_reason,
            "location": location,
            "resolved_location": resolved_location,
            "target_location": movement.get("target_location", ""),
            "travel": travel,
        }
    )
    # One compact row per agent-step on the shared Recorder stream, so
    # `/api/events/stream?tables=agent.step` can follow the city live.
    # The long LLM texts (perception/plan/reflection) stay in the trace.
    if sim.recorder is not None:
        sim.recorder.record(
            "agent.step",
            {
                "agent_id": agent.get("id"),
                "name": agent.get("name", ""),
                "scheduled_activity": scheduled_activity,
                "activity": effective_activity,
                "action": act,
                "location": resolved_location or location,
                "target_location": movement.get("target_location", ""),
                "changed": bool(changed),
                "change_reason": change_reason,
            },
        )
    if scope.visualizer is not None:
        payload = build_agent_step_payload(
            agent,
            time_str=scope.time_str,
            location=location,
            resolved_location=resolved_location,
            target_location=movement.get("target_location", ""),
            scheduled_activity=scheduled_activity,
            activity=effective_activity,
            action=act,
            outcome=outcome,
            perception=perc,
            plan=plan_text,
            reflection=refl_text,
            changed=changed,
            change_reason=change_reason,
            travel=travel,
        )
        scope.frame_steps.append(payload)
        # Publish this resident right away. A tick costs one model call per
        # resident, so the dashboard's map used to stay empty until all of
        # them were done; now it fills in while the tick is still running.
        note_agent_step = getattr(scope.visualizer, "note_agent_step", None)
        if note_agent_step is not None:
            note_agent_step(
                scope.day,
                scope.time_str,
                payload,
                env_context=scope.env_context,
                env_events=scope.env_events,
                policy=scope.policy,
            )


def builtin_stages(scope: StepScope) -> dict[str, Callable]:
    """The built-in stages by name, bound to *scope*."""
    stages = {
        "prepare": _stage_prepare,
        "perceive": _stage_perceive,
        "interrupts": _stage_interrupts,
        "plan": _stage_plan,
        "adjust_activity": _stage_adjust_activity,
        "move": _stage_move,
        "select_action": _stage_select_action,
        "reflect": _stage_reflect,
        "update_state": _stage_update_state,
        "broadcast": _stage_broadcast,
        "memorize": _stage_memorize,
        "record": _stage_record,
    }
    return {name: partial(fn, scope=scope) for name, fn in stages.items()}
