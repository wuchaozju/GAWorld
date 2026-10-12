"""
This file reads simulation state and turns it into host suggestions or host events.

Each function here does one clear job:
- `get_user_llm_clients` loads a user's saved model client when one exists.
- `get_simulation_state` finds the current simulator node and basic state.
- `generate_environment_suggestions` builds grounded suggestions from real behavior.
- `broadcast_environment_event` injects one host event into the selected node.
- `dismiss_suggestions` marks the current suggestion window as already seen.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select

from fos.backend.models.external_event_record import ExternalEventRecord
from fos.backend.models.simulation import Simulation
from fos.backend.models.user import ProviderConfig
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY
from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter, get_runtime_agent_map
from fos.core.environment_analyzer import EnvironmentAnalyzer
from fos.core.environment_config import EnvironmentConfig
from fos.core.environment_context_builder import build_environment_context
from fos.i18n import T

logger = logging.getLogger(__name__)


async def get_user_llm_clients(db, user_id: int) -> dict[str, Any] | None:
    """Get saved model clients for one user when they exist."""
    from fos.core.llm import create_llm_client
    from fos.core.llm_config import LLMConfig

    result = await db.execute(select(ProviderConfig).where(ProviderConfig.user_id == user_id))
    providers = result.scalars().all()
    if not providers:
        return None

    active = [provider for provider in providers if (provider.config or {}).get("active")]
    provider = active[0] if active else providers[0]
    config_data = provider.config or {}
    llm_config = LLMConfig(
        dialect=config_data.get("dialect", "openai"),
        api_key=config_data.get("api_key", ""),
        model=config_data.get("model", "gpt-4o-mini"),
        base_url=config_data.get("base_url"),
        temperature=config_data.get("temperature", 0.7),
    )
    client = create_llm_client(llm_config)
    return {"chat": client, "default": client}


async def get_simulation_state(
    simulation_id: str,
    db,
    user_id: int,
    node_id: int | None = None,
) -> dict[str, Any] | None:
    """Find the current simulator node and return the basic runtime state."""
    result = await db.execute(
        select(Simulation).where(
            Simulation.id == simulation_id.upper(),
            Simulation.owner_id == user_id,
        )
    )
    simulation = result.scalar_one_or_none()
    if simulation is None:
        return None

    scene_config = simulation.scene_config or {}
    environment_enabled = bool(scene_config.get("environment_enabled", False))

    registry_key = simulation_id.upper()
    record = SIM_TREE_REGISTRY.get(registry_key)
    if record is None:
        logger.warning("Simulation %s not found in SIM_TREE_REGISTRY", simulation_id)
        record = await SIM_TREE_REGISTRY.get_or_create_from_sim(simulation)

    tree = record.tree
    simulator, current_node_id = _resolve_simulator_node(tree, simulation_id, node_id)
    if simulator is None or current_node_id is None:
        return _empty_simulation_state(environment_enabled, record)

    if hasattr(simulator, "environment_config") and simulator.environment_config is not None:
        simulator.environment_config.enabled = environment_enabled

    turns = _read_simulator_turns(simulator)
    logger.info(
        "Simulation %s: turns=%s, config_enabled=%s (from db)",
        simulation_id,
        turns,
        environment_enabled,
    )

    config = (
        simulator.environment_config.serialize()
        if hasattr(simulator, "environment_config") and simulator.environment_config
        else EnvironmentConfig(enabled=environment_enabled).serialize()
    )
    return {
        "turns": turns,
        "config": config,
        "_suggestions_viewed_intervals": record._suggestions_viewed_intervals,
        "clients": getattr(simulator, "clients", None),
        "node_id": current_node_id,
        "tree": tree,
        "simulator": simulator,
    }


async def generate_environment_suggestions(
    simulation_id: str,
    db,
    user_id: int,
    node_id: int | None = None,
) -> list[dict[str, Any]]:
    """Build grounded environment suggestions from real simulation behavior."""
    state = await get_simulation_state(simulation_id, db, user_id, node_id)
    if not state:
        raise ValueError(T("api.errors.simulation_not_found"))

    result = await db.execute(
        select(Simulation).where(
            Simulation.id == simulation_id.upper(),
            Simulation.owner_id == user_id,
        )
    )
    simulation = result.scalar_one_or_none()
    if simulation is None:
        raise ValueError(T("api.errors.simulation_not_found"))

    clients = state.get("clients") or await get_user_llm_clients(db, user_id)
    recent_external_events = await _load_recent_external_events(db, simulation_id)
    simulator = state.get("simulator")
    if simulator is not None:
        context = build_environment_context(
            simulator,
            recent_external_events=recent_external_events,
        )
    else:
        context = {
            "current_turn": state["turns"],
            "agent_count": len((simulation.agent_config or {}).get("agents", [])),
            "recent_actions": [],
            "recent_rounds": [],
            "action_totals": {},
            "recent_events": recent_external_events,
            "scene_signals": {},
            "agents": [],
        }
    context["simulation_id"] = simulation_id.upper()
    context["scene_type"] = simulation.scene_type
    context["environment_enabled"] = bool((simulation.scene_config or {}).get("environment_enabled", False))

    analyzer = EnvironmentAnalyzer(clients)
    suggestions = analyzer.generate_suggestions(context, count=3)
    logger.info("Generated %s grounded suggestions for simulation %s", len(suggestions), simulation_id)
    return suggestions


async def broadcast_environment_event(
    simulation_id: str,
    event_data: dict[str, Any],
    db,
    user_id: int,
) -> bool:
    """Inject one host event into the selected node and persist the tree state."""
    requested_node_id = event_data.get("node_id")
    state = await get_simulation_state(
        simulation_id,
        db,
        user_id,
        int(requested_node_id) if requested_node_id is not None else None,
    )
    if not state:
        raise ValueError(T("api.errors.simulation_not_found"))

    result = await db.execute(
        select(Simulation).where(
            Simulation.id == simulation_id.upper(),
            Simulation.owner_id == user_id,
        )
    )
    simulation = result.scalar_one_or_none()
    if simulation is None:
        raise ValueError(T("api.errors.simulation_not_found"))

    simulator = state.get("tree").nodes[state["node_id"]].get("sim")
    if not simulator:
        raise ValueError(T("api.errors.simulator_not_found"))

    is_policy_scene = False
    try:
        is_policy_scene = getattr(simulator.scene, "TYPE", "") == "policy_cascade_scene"
    except Exception:
        is_policy_scene = False

    notice_only_flag = bool(event_data.get("notice_only")) if is_policy_scene else False
    mode = str(event_data.get("event_type") or "").strip().lower()
    description = str(event_data.get("description") or "")

    receivers = None
    if "receivers" in event_data:
        raw = event_data.get("receivers")
        if not raw:
            raise ValueError(T("api.errors.receivers_empty"))
        receivers = [str(receiver).strip() for receiver in raw if str(receiver).strip()]
        if not receivers:
            raise ValueError(T("api.errors.receivers_empty"))

    if not notice_only_flag and mode == "broadcast":
        from fos.core.event import PublicEvent

        event = PublicEvent(content=description, prefix="SYSTEM BROADCAST")
        simulator.broadcast(event, receivers=receivers)
    else:
        _deliver_notice_only_event(simulator, description, mode, is_policy_scene, receivers)

    simulation.latest_state = state.get("tree").serialize()
    await db.commit()

    record = SIM_TREE_REGISTRY.get(simulation_id)
    if record:
        interval = getattr(getattr(simulator, "environment_config", None), "turn_interval", 5)
        turns = _read_simulator_turns(simulator)
        current_interval_milestone = (turns // interval) * interval
        record._suggestions_viewed_intervals.add(current_interval_milestone)
        logger.info("Marked interval %s as viewed for simulation %s", current_interval_milestone, simulation_id)

    return True


async def dismiss_suggestions(
    simulation_id: str,
    db,
    user_id: int,
) -> bool:
    """Mark the current suggestion interval as already seen."""
    state = await get_simulation_state(simulation_id, db, user_id)
    if not state:
        raise ValueError(T("api.errors.simulation_not_found"))

    record = SIM_TREE_REGISTRY.get(simulation_id)
    if record:
        simulator = state.get("tree").nodes[state["node_id"]].get("sim")
        if simulator:
            interval = simulator.environment_config.turn_interval
            current_interval_milestone = (_read_simulator_turns(simulator) // interval) * interval
            record._suggestions_viewed_intervals.add(current_interval_milestone)
            logger.info("Dismissed interval %s for simulation %s", current_interval_milestone, simulation_id)
            return True
    return False


async def _load_recent_external_events(db, simulation_id: str) -> list[dict[str, Any]]:
    """Load the newest saved external event rows for suggestion grounding."""
    result = await db.execute(
        select(ExternalEventRecord)
        .where(ExternalEventRecord.simulation_id == simulation_id.upper())
        .order_by(desc(ExternalEventRecord.event_timestamp))
        .limit(5)
    )
    records = result.scalars().all()
    return [
        {
            "id": record.id,
            "type": record.event_type,
            "title": record.title,
            "severity": record.severity,
            "status": record.status,
            "source": record.source,
        }
        for record in records
    ]


def _resolve_simulator_node(tree, simulation_id: str, node_id: int | None) -> tuple[Any | None, int | None]:
    """Pick the requested node or the newest leaf and return its simulator."""
    if node_id is not None:
        current_node_id = int(node_id)
        current_node = tree.nodes.get(current_node_id)
        if not current_node:
            logger.warning("Requested node %s not found for simulation %s", current_node_id, simulation_id)
            return _resolve_leaf_simulator(tree, simulation_id)
        simulator = current_node.get("sim")
        if not simulator:
            logger.warning("No simulator found in requested node %s", current_node_id)
            return None, None
        return simulator, current_node_id
    return _resolve_leaf_simulator(tree, simulation_id)


def _resolve_leaf_simulator(tree, simulation_id: str) -> tuple[Any | None, int | None]:
    """Pick the newest leaf node and return its simulator."""
    leaves = tree.leaves()
    if not leaves:
        logger.warning("No leaf nodes found for simulation %s", simulation_id)
        return None, None
    current_node_id = leaves[0]
    current_node = tree.nodes.get(current_node_id)
    if not current_node:
        logger.warning("Current node %s not found in tree", current_node_id)
        return None, None
    simulator = current_node.get("sim")
    if not simulator:
        logger.warning("No simulator found in node %s", current_node_id)
        return None, None
    return simulator, current_node_id


def _empty_simulation_state(environment_enabled: bool, record) -> dict[str, Any]:
    """Build the fallback state used when the tree has no usable simulator."""
    return {
        "turns": 0,
        "config": EnvironmentConfig(enabled=environment_enabled).serialize(),
        "_suggestions_viewed_intervals": record._suggestions_viewed_intervals,
        "clients": None,
        "node_id": None,
        "tree": record.tree,
        "simulator": None,
    }


def _read_simulator_turns(simulator: Any) -> int:
    """Read turns from either simulator style used in this codebase."""
    turns = getattr(simulator, "turns", None)
    if turns is None and hasattr(simulator, "scene"):
        turns = getattr(simulator.scene, "current_round", 0)
    return int(turns or 0)


def _deliver_notice_only_event(
    simulator: Any,
    description: str,
    mode: str,
    is_policy_scene: bool,
    receivers: list[str] | None,
) -> None:
    """Send a notice-only event through the same path host injections already use."""
    runtime_agents = get_runtime_agent_map(simulator)
    if receivers is not None:
        for name in receivers:
            agent = runtime_agents.get(name)
            if agent:
                _add_env_feedback(agent, description)
        if isinstance(simulator, ExperimentRunnerAdapter):
            if hasattr(simulator, "_emit_event"):
                simulator._emit_event("public_event", {"message": description, "scoped": True, "recipients": receivers})
            return
        if hasattr(simulator.scene, "inject_host_message"):
            scoped_prefix = f"[Private notice to {', '.join(receivers)}]\n" if receivers else ""
            simulator.scene.inject_host_message(f"{scoped_prefix}{description}")
            if hasattr(simulator, "_emit_event"):
                simulator._emit_event("public_event", {"message": description, "scoped": True, "recipients": receivers})
        elif is_policy_scene:
            simulator.scene.on_private_event(
                simulator,
                "environment",
                {"description": description, "event_type": mode, "notice_only": True},
                receivers,
            )
        else:
            simulator.scene.on_private_event(
                simulator,
                "environment",
                {"description": description, "event_type": mode},
                receivers,
            )
        return

    if hasattr(simulator.scene, "inject_host_message"):
        simulator.scene.inject_host_message(description)
        if hasattr(simulator, "_emit_event"):
            simulator._emit_event("public_event", {"message": description, "scoped": False, "recipients": []})
    else:
        for agent in runtime_agents.values():
            _add_env_feedback(agent, description)

    if hasattr(simulator.scene, "inject_host_message"):
        return
    if is_policy_scene:
        simulator.scene.on_event(
            simulator,
            "environment",
            {"description": description, "event_type": mode, "notice_only": True},
        )
        return
    simulator.scene.on_event(simulator, "environment", {"description": description, "event_type": mode})


def _add_env_feedback(agent: Any, description: str) -> None:
    """Send environment feedback to either agent style used in this repo."""
    try:
        agent.add_env_feedback(description, images=[])
    except TypeError:
        agent.add_env_feedback(description)
