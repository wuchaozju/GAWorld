from __future__ import annotations

import asyncio
import logging
import logging as _logging
import os as _os
import sys
import time
from typing import Dict

from fos.core.agent import Agent
from fos.core.event import PublicEvent
from fos.core.ordering import ControlledOrdering, CycledOrdering, SequentialOrdering
from fos.core.registry import (
    ACTION_SPACE_MAP,
    SCENE_ACTIONS,
    SCENE_MAP,
    get_scene_class,
)
from fos.core.simtree import SimTree
from fos.core.simulator import Simulator
from fos.core.environment_config import EnvironmentConfig
from fos.scenarios.basic import make_clients_from_env
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.game_configs import create_council_config
from fos.core.experiment.scenes.council_experiment import CouncilExperimentScene
from fos.backend.services.simtree_adapter_serialization import (
    deserialize_experiment_scene,
    serialize_experiment_adapter,
)
from fos.backend.services.simtree_gaworld import (
    resolve_gaworld_agent_ids,
    resolve_gaworld_agents,
    resolve_gaworld_path,
)
from fos.backend.services.simtree_knowledge import (
    update_agent_knowledge as update_tree_agent_knowledge,
    update_global_knowledge as update_tree_global_knowledge,
)
from fos.backend.services.simtree_registry_lifecycle import (
    SimTreeRecord,
    wire_tree_broadcast,
)
from fos.i18n import T, get_request_locale


_GAWORLD_PATH: str | None = _os.environ.get("GAWORLD_PATH")
_log = _logging.getLogger(__name__)
logger = logging.getLogger(__name__)
_logging_handler = logging.StreamHandler(sys.stdout)
_logging_handler.setLevel(logging.DEBUG)
_logging_handler.setFormatter(logging.Formatter("[SIMTREE RUNTIME] %(message)s"))
logger.addHandler(_logging_handler)
_log.setLevel(_logging.INFO)
_log.info(f"[GAWorld] GAWORLD_PATH resolved at import: {_GAWORLD_PATH!r}")


def _resolve_gaworld_path() -> str | None:
    """Resolve GAWorld path, checking env at call time as well as import time.

    This handles cases where GAWORLD_PATH is set via dotenv or other means
    after the module was first imported (e.g., when load_dotenv() runs in main.py).
    """
    return resolve_gaworld_path(_GAWORLD_PATH)


def _normalize_language(value: str | None) -> str:
    lang = str(value or "").strip()
    return lang or "en"


def _resolve_initial_event(cfg: dict, fallback: str = "") -> str:
    """Pick initial event content from scene_config with simple fallbacks."""
    val = str(cfg.get("initial_event") or "").strip()
    if not val:
        events = cfg.get("initial_events") or []
        if isinstance(events, list) and events:
            first = str(events[0] or "").strip()
            if first:
                val = first
    if not val:
        desc = str(cfg.get("description") or "").strip()
        if desc:
            val = desc
    return val or fallback


def _is_english_language(lang: str) -> bool:
    lower = lang.lower()
    return lower.startswith("en") or "english" in lower


def _resolve_gaworld_agents(agent_config: dict) -> list[dict]:
    return resolve_gaworld_agents(agent_config)


def _resolve_gaworld_agent_ids(params: dict, agents: list[dict]) -> list[str]:
    return resolve_gaworld_agent_ids(params, agents)


def _quiet_logger(event_type: str, data: dict) -> None:
    return


class ExperimentRunnerAdapter:
    """Minimal adapter so ExperimentScene works with SimTree.

    Provides the interface SimTree expects (.run(), .agents, .clients)
    without requiring a full Simulator with legacy Agents.
    """

    def __init__(self, scene: ExperimentScene, clients: dict):
        self.scene = scene
        self.clients = clients
        self.agents = {}  # Empty dict - no legacy agents
        self.events: list[dict] = []
        self._llm_client = clients.get("chat") or clients.get("default")
        self._provider_clients: dict = clients.get("providers", {}) if clients else {}
        self.log_event = None  # Will be set by SimTree._attach_log_handler

        # Pre-initialize to populate scene.agents so UI can render agent cards without running a round
        if not self.scene.agents and (
            self._llm_client is not None
            or getattr(self.scene, "TYPE", "") == "gaworld_scene"
        ):
            self.scene.initialize(
                self._llm_client or object(), provider_clients=self._provider_clients
            )

    def _scene_agent_map(self) -> dict[str, object]:
        """Return experiment agents by name for adapter-only compatibility paths."""
        return {
            getattr(agent, "name", ""): agent
            for agent in getattr(self.scene, "agents", []) or []
            if getattr(agent, "name", "")
        }

    def run(self, max_turns: int = 1) -> None:
        """Run experiment rounds (each 'turn' = one round)."""
        if not self.scene.runner:
            self.scene.initialize(
                self._llm_client, provider_clients=self._provider_clients
            )

        for _ in range(max_turns):
            if self.scene.is_complete():
                break
            try:
                from profiling import prof
                _p = prof()
                _phase = getattr(self.scene, "cycle_phase", None)
                if _p and _phase is not None:
                    _p.set_phase(getattr(_phase, "value", str(_phase)))
            except Exception:
                pass
            try:
                print(f"[DEBUG] adapter.run: about to call _run_scene_round, turn={_}", flush=True)
                self._run_scene_round()
            except Exception as exc:
                self._emit_runtime_error(exc)
                raise

            # CYCLE PHASE FIX: Advance round counter and check for phase transitions
            # This is the ACTUAL code path used by the backend!
            if hasattr(self.scene, "_advance_round"):
                logger.info(
                    f"[CYCLE PHASE FIX] Calling scene._advance_round() for {type(self.scene).__name__}"
                )
                self.scene._advance_round()
                logger.info(
                    f"[CYCLE PHASE FIX] Phase is now: {getattr(self.scene, 'cycle_phase', 'N/A')}, rounds_in_phase: {getattr(self.scene, 'rounds_in_cycle_phase', 'N/A')}"
                )

    def _run_scene_round(self) -> None:
        """Run one async scene round from either a worker thread or direct call."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.scene.run_round(self._emit_event))
            return

        loop.run_until_complete(self.scene.run_round(self._emit_event))

    def _emit_runtime_error(self, error: Exception) -> None:
        """Send scene failures to the node log before raising them."""
        self._emit_event(
            "error",
            {
                "message": str(error),
                "scene_type": getattr(self.scene, "TYPE", type(self.scene).__name__),
            },
        )

    def _emit_event(self, event_type: str, data: dict) -> None:
        """Collect events for SimTree and emit to log handler."""
        self.events.append({"type": event_type, "data": data})
        # Also emit to log handler if set (for UI logs display)
        if self.log_event is not None:
            self.log_event(event_type, data)

    def serialize(self) -> dict:
        """Serialize for SimTree compatibility."""
        return serialize_experiment_adapter(self.scene)

    @classmethod
    def deserialize(cls, data: dict, clients: dict, log_handler=None):
        """Deserialize for SimTree compatibility."""
        scene = deserialize_experiment_scene(data)
        adapter = cls(scene, clients)
        adapter.scene.current_round = data.get("turns", 0)
        return adapter

    def reset_event_queue(self) -> None:
        """No-op for SimTree compatibility (adapter has no event queue)."""
        pass

    def cleanup_runtime_resources(self) -> None:
        """Stop scene-owned resources when the adapter leaves memory."""
        cleanup = getattr(self.scene, "cleanup_runtime_resources", None)
        if cleanup is not None:
            cleanup()

    def emit_remaining_events(self) -> None:
        """No-op for SimTree compatibility (adapter has no event queue)."""
        pass

    def broadcast(self, event, receivers=None) -> None:
        """Broadcast a public event to the experiment scene.

        Args:
            event: PublicEvent or similar event object with text attribute
        """
        targets = list(self._scene_agent_map().values())
        allowed = {str(name).strip() for name in (receivers or []) if str(name).strip()}
        if allowed:
            targets = [
                agent for agent in targets if getattr(agent, "name", "") in allowed
            ]

        text = ""
        if hasattr(event, "to_string"):
            try:
                text = str(event.to_string()).strip()
            except Exception:
                text = ""
        if not text:
            text = str(
                getattr(event, "text", None)
                or getattr(event, "content", None)
                or getattr(event, "message", None)
                or ""
            ).strip()
        if not text:
            text = str(event)

        for agent in targets:
            if hasattr(agent, "add_env_feedback"):
                agent.add_env_feedback(text)

        payload = {
            "text": text,
            "recipients": [
                getattr(agent, "name", "")
                for agent in targets
                if getattr(agent, "name", "")
            ],
            "scoped": bool(allowed),
            "type": type(event).__name__,
        }
        self._emit_event("system_broadcast", payload)

    def inject_host_message(self, message: str) -> None:
        """Inject a host message into all agents' context for the next round.

        Args:
            message: Host message text to inject
        """
        self.scene.inject_host_message(message)


def get_runtime_agent_map(simulator) -> dict[str, object]:
    """Return a name->agent mapping for either runtime architecture."""
    if isinstance(simulator, ExperimentRunnerAdapter):
        return simulator._scene_agent_map()
    return getattr(simulator, "agents", {}) or {}


def get_runtime_agent_count(simulator) -> int:
    """Return the visible runtime agent count for either simulator style."""
    return len(get_runtime_agent_map(simulator))


def get_runtime_agent_profile(agent: object) -> str:
    """Return the best available user-facing profile string for an agent."""
    properties = getattr(agent, "properties", {}) or {}
    return str(
        getattr(agent, "user_profile", "")
        or getattr(agent, "role_prompt", "")
        or properties.get("profile")
        or properties.get("description")
        or properties.get("role")
        or ""
    ).strip()


def _build_tree_for_scene(scene_type: str, clients: dict | None = None) -> SimTree:
    # Normalize scene_type to registry keys (allow aliases like 'experiment' -> 'experiment_scene')
    scene_key = scene_type if scene_type in SCENE_MAP else f"{scene_type}_scene"
    scene_cls = get_scene_class(scene_key)
    if scene_cls is None:
        raise ValueError(
            T("api.errors.simtree.unsupported_scene_type", scene_type=scene_type)
        )
    active = clients or make_clients_from_env()
    scene = scene_cls("preview", "")
    agents = [
        # minimal placeholder agent; real agents come from agent_config at runtime
        Agent.deserialize(
            {
                "name": "Alice",
                "user_profile": "",
                "style": "",
                "initial_instruction": "",
                "role_prompt": "",
                "action_space": [],
                "properties": {},
            }
        )
    ]
    sim = Simulator(
        agents,
        scene,
        active,
        event_handler=_quiet_logger,
        ordering=SequentialOrdering(),
    )
    return SimTree.new(sim, active)


def _apply_agent_config(simulator, agent_config: dict | None):
    if not agent_config:
        return
    items = agent_config.get("agents") or []
    agents_list = list(simulator.agents.values())
    count = min(len(items), len(agents_list))
    # First apply names/profiles by position, then rebuild mapping
    for i in range(count):
        cfg = items[i] or {}
        agent = agents_list[i]
        new_name = str(cfg.get("name") or "").strip()
        if new_name:
            agent.name = new_name

        # Try multiple field names for profile (frontend compatibility)
        # Priority: profile > user_profile > userProfile (camelCase)
        profile = (
            str(cfg.get("profile") or "").strip()
            or str(cfg.get("user_profile") or "").strip()
            or str(cfg.get("userProfile") or "").strip()
        )
        if profile:
            agent.user_profile = profile

        # Try role_prompt field (snake_case from frontend)
        role_prompt = (
            str(cfg.get("role_prompt") or "").strip()
            or str(cfg.get("rolePrompt") or "").strip()
        )
        if role_prompt and hasattr(agent, "role_prompt"):
            agent.role_prompt = role_prompt

        # Apply all frontend-edited properties
        properties = cfg.get("properties") or {}
        if isinstance(properties, dict):
            if not hasattr(agent, "properties") or agent.properties is None:
                agent.properties = {}
            agent.properties.update(properties)

        llm_config = cfg.get("llm_config") or cfg.get("llmConfig") or {}
        if llm_config:
            if not hasattr(agent, "properties") or agent.properties is None:
                agent.properties = {}
            agent.properties["llm_config"] = llm_config

        provider_id = cfg.get("provider_id") or cfg.get("providerId")
        if provider_id is not None:
            if not hasattr(agent, "properties") or agent.properties is None:
                agent.properties = {}
            agent.properties["provider_id"] = provider_id

        # Ensure defaults for required fields
        if not hasattr(agent, "history") or agent.history is None:
            agent.history = {}
        if not hasattr(agent, "memory") or agent.memory is None:
            agent.memory = []
        if not hasattr(agent, "score") or agent.score is None:
            agent.score = 0

        language = str(cfg.get("language") or "").strip()
        if language:
            agent.language = language
    # Rebuild agents mapping to reflect renames
    simulator.agents = {a.name: a for a in agents_list}
    # Now apply actions (scene common + selected) per agent
    for i in range(count):
        cfg = items[i] or {}
        agent = agents_list[i]
        selected = [str(a) for a in (cfg.get("action_space") or [])]
        if not selected:
            reg = {}
            selected = (reg.get("basic") or []) + (reg.get("allowed") or [])
        scene_actions = simulator.scene.get_scene_actions(agent) or []
        picked = []
        for key in selected:
            act = ACTION_SPACE_MAP.get(key)
            if act is not None:
                picked.append(act)
        merged = []
        seen: set[str] = set()
        for act in list(scene_actions) + picked:
            n = getattr(act, "NAME", None)
            if n and n not in seen:
                merged.append(act)
                seen.add(n)
        agent.action_space = merged
    # Refresh ordering candidates after renames
    simulator.ordering.set_simulation(simulator)


def _build_tree_for_sim(sim_record, clients: dict | None = None) -> SimTree:
    scene_type = sim_record.scene_type
    # Normalize scene_type to registry keys (allow aliases like 'experiment' -> 'experiment_scene')
    scene_key = scene_type if scene_type in SCENE_MAP else f"{scene_type}_scene"
    scene_cls = get_scene_class(scene_key)
    if scene_cls is None:
        raise ValueError(
            T("api.errors.simtree.unsupported_scene_type", scene_type=scene_type)
        )

    cfg = getattr(sim_record, "scene_config", {}) or {}
    name = getattr(sim_record, "name", scene_type)
    fallback_initial = str(
        getattr(sim_record, "description", "")
        or getattr(sim_record, "notes", "")
        or name
        or ""
    )
    initial_event_content = _resolve_initial_event(cfg, fallback_initial)
    if scene_key == "policy_cascade_scene":
        params = cfg.get("parameters") or {}
        opening_notice = str(params.get("policy_text") or "").strip()
        if opening_notice:
            initial_event_content = opening_notice
    if not initial_event_content and scene_key == "policy_cascade_scene":
        initial_event_content = (
            "Three-tier policy cascade: transmit the full policy top → mid → low; "
            "each level may reinterpret or resist."
        )

    # Debug logging to show which scene type is being used
    logger.debug(f"\n{'=' * 60}")
    logger.debug(f"BUILDING TREE FOR SIMULATION: {sim_record.id}")
    logger.debug(f"Scene type: {scene_type}")
    logger.debug(f"Scene key: {scene_key}")
    logger.debug(
        f"Scene class: {scene_cls.__name__ if hasattr(scene_cls, '__name__') else scene_cls}"
    )
    logger.debug(f"Scene config: {cfg}")
    logger.debug(f"{'=' * 60}\n")

    agent_config = getattr(sim_record, "agent_config", {}) or {}
    items = agent_config.get("agents") or []
    first_language = None
    for cfg_agent in items:
        lang = str(cfg_agent.get("language") or "").strip()
        if lang:
            first_language = lang
            break
    preferred_language = _normalize_language(cfg.get("language") or first_language)

    def _localized(en_text: str, zh_text: str) -> str:
        return en_text if _is_english_language(preferred_language) else zh_text

    # Build scene via constructor based on type
    # Use normalized scene_key for matching below
    if scene_key in {"simple_chat_scene", "emotional_conflict_scene"}:
        # Use generalized initial events; constructor initial can be empty
        scene = scene_cls(name, "")
    elif scene_key == "council_scene":
        draft = str(cfg.get("draft_text") or "")
        scene = scene_cls(name, "")
    elif scene_key == "landlord_scene":
        num_decks = int(cfg.get("num_decks", 1))
        seed = cfg.get("seed")
        seed_int = int(seed) if seed is not None else None
        scene = scene_cls(
            name,
            _localized("New game: Dou Dizhu.", "新一局斗地主开始。"),
            seed=seed_int,
            num_decks=num_decks,
        )
    elif scene_key == "werewolf_scene":
        initial = initial_event_content or _localized(
            "Welcome to Werewolf.", "欢迎来到狼人游戏。"
        )
        role_map = cfg.get("role_map") or None
        moderator_names = cfg.get("moderator_names") or None
        scene = scene_cls(
            name, initial, role_map=role_map, moderator_names=moderator_names
        )
    elif scene_key == "generic_scene":
        # GenericScene needs available_actions from scene_config
        raw_actions = cfg.get("available_actions") or []
        available_actions: list[str] | None = None
        if isinstance(raw_actions, list):
            names: list[str] = []
            for item in raw_actions:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict) and "name" in item:
                    # Frontend sometimes sends objects; use the name field
                    n = str(item.get("name") or "").strip()
                    if n:
                        names.append(n)
            available_actions = names if names else None
        scene = scene_cls(
            name,
            initial_event_content,
            available_actions=available_actions,
        )
    elif scene_key == "experiment_template":
        # ExperimentScene - standalone, no legacy Simulator needed
        # Unwrap generic_config if the config is nested (frontend sends nested structure)
        inner_cfg = cfg.get("generic_config") or cfg

        scenario_id = inner_cfg.get("scenario_id", "custom")

        # GAP-CLOSURE-01: Use CouncilExperimentScene for council scenarios
        # Support both "council" and "council_chamber" scenario_ids (frontend uses council_chamber)
        if scenario_id in ("council", "council_chamber"):
            # NO DEFAULTS - fail fast if parameters are missing
            params = inner_cfg.get("parameters", {})

            # Handle parameter name mapping: max_rounds -> deliberation_rounds
            # Frontend may send 'max_rounds' but backend expects 'deliberation_rounds'
            if "deliberation_rounds" not in params and "max_rounds" in params:
                params["deliberation_rounds"] = params["max_rounds"]
                logger.info(
                    f"[PARAMETER MAPPING] Mapped max_rounds={params['max_rounds']} to deliberation_rounds"
                )

            if "deliberation_rounds" not in params:
                raise ValueError(
                    T("api.errors.simtree.deliberation_rounds_required", params=params)
                )
            if "voting_threshold" not in params:
                raise ValueError(
                    T("api.errors.simtree.voting_threshold_required", params=params)
                )
            if "proposal_text" not in params:
                raise ValueError(
                    T("api.errors.simtree.proposal_text_required", params=params)
                )

            council_game_config = create_council_config(
                proposal_text=params["proposal_text"],
                deliberation_rounds=params["deliberation_rounds"],
                voting_threshold=params["voting_threshold"],
            )
            config = ExperimentConfig(
                agents=agent_config.get("agents", []),
                actions=[{"name": a} for a in council_game_config.actions],
                parameters={
                    "deliberation_rounds": council_game_config.deliberation_rounds,
                    "voting_threshold": council_game_config.voting_threshold,
                    "proposal_text": council_game_config.proposal_text,
                },
                description=council_game_config.description,
                scenario_id="council_chamber",
                round_visibility="sequential",
                social_network=inner_cfg.get("social_network") or {},
                locale=inner_cfg.get("locale") or get_request_locale(),
                global_knowledge=inner_cfg.get("global_knowledge", {}),
            )
            logger.debug(
                f"[COUNCIL_EXPERIMENT] Creating CouncilExperimentScene with parameters: {config.parameters}"
            )
            scene = CouncilExperimentScene(config)
        else:
            config = ExperimentConfig(
                agents=agent_config.get("agents", []),
                actions=inner_cfg.get("actions", []),
                parameters=inner_cfg.get("parameters", {}),
                description=inner_cfg.get("description", ""),
                scenario_id=scenario_id,
                round_visibility=inner_cfg.get("round_visibility", "simultaneous"),
                social_network=inner_cfg.get("social_network") or {},
                locale=inner_cfg.get("locale") or get_request_locale(),
                global_knowledge=inner_cfg.get("global_knowledge", {}),
            )
            logger.debug(
                f"[EXPERIMENT] Creating ExperimentConfig with parameters: {cfg.get('parameters', {})}"
            )
            scene = ExperimentScene(config)

        # Use adapter instead of full Simulator
        adapter = ExperimentRunnerAdapter(scene, clients or make_clients_from_env())

        logger.debug(f"Created ExperimentScene with adapter: {config.scenario_id}")

        return SimTree.new(adapter, adapter.clients)
    elif scene_key == "council_experiment":
        # REFACTOR-COUNCIL-06: Council experiment using experiment framework
        # NO DEFAULTS - fail fast if parameters are missing

        # Handle parameter name mapping: max_rounds -> deliberation_rounds
        # Frontend may send 'max_rounds' but backend expects 'deliberation_rounds'
        if "deliberation_rounds" not in cfg and "max_rounds" in cfg:
            cfg["deliberation_rounds"] = cfg["max_rounds"]
            logger.info(
                f"[PARAMETER MAPPING] Mapped max_rounds={cfg['max_rounds']} to deliberation_rounds"
            )

        if "deliberation_rounds" not in cfg:
            raise ValueError(
                T(
                    "api.errors.simtree.deliberation_rounds_required_keys",
                    keys=list(cfg.keys()),
                )
            )
        if "voting_threshold" not in cfg:
            raise ValueError(
                T(
                    "api.errors.simtree.voting_threshold_required_keys",
                    keys=list(cfg.keys()),
                )
            )
        if "proposal_text" not in cfg:
            raise ValueError(
                T(
                    "api.errors.simtree.proposal_text_required_keys",
                    keys=list(cfg.keys()),
                )
            )

        # Create CouncilConfig with council-specific parameters
        council_game_config = create_council_config(
            proposal_text=cfg["proposal_text"],
            deliberation_rounds=cfg["deliberation_rounds"],
            voting_threshold=cfg["voting_threshold"],
        )

        config = ExperimentConfig(
            agents=agent_config.get("agents", []),
            actions=[{"name": a} for a in council_game_config.actions],
            parameters={
                "deliberation_rounds": council_game_config.deliberation_rounds,
                "voting_threshold": council_game_config.voting_threshold,
                "proposal_text": council_game_config.proposal_text,
            },
            description=council_game_config.description,
            scenario_id="council_chamber",
            round_visibility="sequential",  # Council uses sequential rounds
            social_network=cfg.get("social_network") or {},
            locale=cfg.get("locale") or get_request_locale(),
            global_knowledge=cfg.get("global_knowledge", {}),
        )
        logger.debug(
            f"[COUNCIL_EXPERIMENT] Creating CouncilExperimentScene with parameters: {config.parameters}"
        )
        scene = CouncilExperimentScene(config)

        # Use adapter instead of full Simulator
        adapter = ExperimentRunnerAdapter(scene, clients or make_clients_from_env())

        logger.debug("Created CouncilExperimentScene with adapter: council")

        return SimTree.new(adapter, adapter.clients)
    elif scene_key == "policy_cascade_experiment":
        from fos.core.scenes.policy_cascade_experiment import (
            PolicyCascadeExperimentScene,
        )

        params = cfg.get("parameters", {})
        config = ExperimentConfig(
            agents=agent_config.get("agents", []),
            actions=[
                {
                    "name": "send_message",
                    "description": T("experiment.action.send_message"),
                },
                {"name": "yield", "description": T("experiment.action.yield")},
                {
                    "name": "report_upward",
                    "description": T("experiment.action.report_upward"),
                },
                {
                    "name": "escalate_complaint",
                    "description": T("experiment.action.escalate_complaint"),
                },
                {
                    "name": "consult_peer",
                    "description": T("experiment.action.consult_peer"),
                },
                {
                    "name": "notify_subordinate",
                    "description": T("experiment.action.notify_subordinate"),
                },
                {
                    "name": "announce_policy_adjustment",
                    "description": T("experiment.action.announce_policy_adjustment"),
                },
            ],
            parameters=params,
            description=str(params.get("policy_text", "")),
            scenario_id="policy_cascade",
            round_visibility="sequential",
            social_network=cfg.get("social_network") or {},
            locale=cfg.get("locale", "en"),
            global_knowledge=cfg.get("global_knowledge", {}),
        )
        scene = PolicyCascadeExperimentScene(config)
        adapter = ExperimentRunnerAdapter(scene, clients or make_clients_from_env())
        return SimTree.new(adapter, adapter.clients)
    elif scene_key == "contagion_scene":
        from fos.core.contagion.scene import ContagionScene
        from fos.core.contagion.states import ContagionState
        from fos.core.contagion.rules import StateTransition
        from fos.core.map.grid import GameMap

        params = cfg.get("parameters", {})
        grid_size = int(params.get("grid_size", 10))
        proximity_prob = float(params.get("proximity_probability", 0.3))
        action_prob = float(params.get("action_probability", 0.5))
        recovery_turns = int(params.get("recovery_turns", 5))
        initial_infected = int(params.get("initial_infected", 1))

        game_map = GameMap(width=grid_size, height=grid_size)

        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.INFECTED,
                trigger_type="proximity",
                probability=proximity_prob,
            ),
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.INFECTED,
                trigger_type="action",
                probability=action_prob,
            ),
            StateTransition(
                from_state=ContagionState.INFECTED,
                to_state=ContagionState.RECOVERED,
                trigger_type="decay",
                probability=1.0,
                decay_turns=recovery_turns,
            ),
        ]

        scene = ContagionScene(
            name=name,
            initial_event=initial_event_content,
            game_map=game_map,
            rules=rules,
            initial_infected_count=initial_infected,
        )

        # Use adapter instead of full Simulator (same as experiment_template)
        adapter = ExperimentRunnerAdapter(scene, clients or make_clients_from_env())

        logger.debug(
            f"Created ContagionScene with adapter: grid={grid_size}x{grid_size}"
        )

        return SimTree.new(adapter, adapter.clients)
    elif scene_key == "gaworld_scene":
        from fos.core.experiment.scenes.gaworld import GAWorldScene

        gaworld_path = _resolve_gaworld_path()
        if not gaworld_path:
            raise ValueError("gaworld.error.path_not_set")

        inner_cfg = cfg.get("generic_config") or cfg
        gaworld_params = inner_cfg.get("parameters", {})
        gaworld_params["gaworld_path"] = gaworld_path
        logger.info(
            "GAWorld tree build: gaworld_path=%s, params_keys=%s",
            gaworld_path,
            list(gaworld_params.keys()),
        )
        gaworld_agents = _resolve_gaworld_agents(agent_config)
        gaworld_params["agent_ids"] = _resolve_gaworld_agent_ids(
            gaworld_params, gaworld_agents
        )
        config = ExperimentConfig(
            agents=gaworld_agents,
            actions=inner_cfg.get("actions", gaworld_params.get("actions", [])),
            parameters=gaworld_params,
            scenario_id="gaworld",
            locale=inner_cfg.get("locale", "zh"),
            global_knowledge=inner_cfg.get("global_knowledge", {}),
        )
        scene = GAWorldScene(config)
        adapter = ExperimentRunnerAdapter(scene, clients or make_clients_from_env())
        return SimTree.new(adapter, adapter.clients)
    else:
        scene = scene_cls(name, initial_event_content)
        if scene_key == "policy_cascade_scene" and hasattr(
            scene, "configure_from_config"
        ):
            scene.configure_from_config(cfg)

    # 存储社交网络拓扑到场景状态中（如果配置了的话）
    social_network = cfg.get("social_network") or {}
    if social_network:
        scene.state["social_network"] = social_network

    if hasattr(scene, "initial_event") and isinstance(scene.initial_event, PublicEvent):
        if not getattr(scene.initial_event, "code", None):
            scene.initial_event.code = "initial_event"
        if not getattr(scene.initial_event, "params", None):
            content = getattr(scene.initial_event, "content", "")
            scene.initial_event.params = {
                "content": content,
                "lang": preferred_language,
            }

    # Build agents from agent_config
    built_agents = []
    for cfg_agent in items:
        aname = str(cfg_agent.get("name") or "").strip() or "Agent"
        profile = str(
            cfg_agent.get("profile")
            or cfg_agent.get("user_profile")
            or cfg_agent.get("userProfile")
            or ""
        )
        role_prompt = str(
            cfg_agent.get("role_prompt")
            or cfg_agent.get("rolePrompt")
            or cfg_agent.get("role")
            or ""
        )

        # Avoid triplication: legacy Agent.system_prompt() renders both user_profile and role_prompt.
        # If they contain the same text, clear profile so it doesn't duplicate in user_profile.
        if profile and role_prompt and profile.strip() == role_prompt.strip():
            profile = ""

        selected = [str(a) for a in (cfg_agent.get("action_space") or [])]
        props = dict(cfg_agent.get("properties") or {})
        llm_config = cfg_agent.get("llm_config") or cfg_agent.get("llmConfig") or {}
        provider_id = cfg_agent.get("provider_id") or cfg_agent.get("providerId")
        if llm_config:
            props["llm_config"] = llm_config
        if provider_id is not None:
            props["provider_id"] = provider_id
        language = _normalize_language(cfg_agent.get("language") or preferred_language)
        # scene common actions from registry (fallback to scene introspection)
        # Use normalized scene_key so short names (e.g., 'village') map correctly.
        reg = SCENE_ACTIONS.get(scene_key, {})
        basic_names = list(reg.get("basic", []))
        allowed_names = list(reg.get("allowed", []))

        seen = set()
        merged_names = []
        source_names = basic_names + (selected if selected else allowed_names)
        for n in source_names:
            if n and n not in seen:
                seen.add(n)
                merged_names.append(n)
        # Get knowledge base from agent config
        knowledge_base = list(
            cfg_agent.get("knowledgeBase") or cfg_agent.get("knowledge_base") or []
        )
        # Get documents from agent config
        documents = dict(cfg_agent.get("documents") or {})
        agent_data = {
            "name": aname,
            "user_profile": profile,
            "style": "",
            "initial_instruction": "",
            "role_prompt": role_prompt,
            "language": language,
            "action_space": merged_names,
            "properties": props,
            "knowledge_base": knowledge_base,
            "documents": documents,
        }
        new_agent = Agent.deserialize(agent_data)
        built_agents.append(new_agent)

    ordering = SequentialOrdering()
    if scene_type == "landlord_scene":

        def next_active(sim):
            s = sim.scene
            p = s.state.get("phase")
            if p == "bidding":
                if s.state.get("bidding_stage") == "call":
                    i = s.state.get("bid_turn_index")
                    return (s.state.get("players") or [None])[i]
                elig = list(s.state.get("rob_eligible") or [])
                acted = dict(s.state.get("rob_acted") or {})
                if not elig:
                    return None
                names = list(s.state.get("players") or [])
                start = s.state.get("bid_turn_index", 0)
                for off in range(len(names)):
                    idx = (start + off) % len(names)
                    name = names[idx]
                    if name in elig and not acted.get(name, False):
                        return name
                return None
            if p == "doubling":
                order = list(s.state.get("doubling_order") or [])
                acted = dict(s.state.get("doubling_acted") or {})
                for name in order:
                    if not acted.get(name, False):
                        return name
                return None
            if p == "playing":
                players = s.state.get("players") or []
                idx = s.state.get("current_turn", 0)
                if players:
                    return players[idx % len(players)]
            return None

        ordering = ControlledOrdering(next_fn=next_active)
    elif scene_type == "werewolf_scene":
        # Build cycled schedule similar to scenario builder
        roles = cfg.get("role_map") or {}
        names = [a.name for a in built_agents]
        wolves = [n for n in names if roles.get(n) == "werewolf"]
        witches = [n for n in names if roles.get(n) == "witch"]
        seers = [n for n in names if roles.get(n) == "seer"]
        seq = wolves + wolves + seers + witches + names + names + ["Moderator"]
        ordering = CycledOrdering(seq)

    # Read environment config from scene_config
    environment_enabled = bool(cfg.get("environment_enabled", False))
    environment_config = EnvironmentConfig(enabled=environment_enabled)

    sim = Simulator(
        built_agents,
        scene,
        clients or make_clients_from_env(),
        event_handler=_quiet_logger,
        ordering=ordering,
        max_steps_per_turn=3 if scene_type == "landlord_scene" else 5,
        environment_config=environment_config,
    )
    # Set global knowledge reference on all agents
    global_knowledge = cfg.get("global_knowledge", {})
    if global_knowledge:
        for agent in built_agents:
            agent.set_global_knowledge(global_knowledge)

    # Broadcast configured initial events as public events
    for text in cfg.get("initial_events") or []:
        if isinstance(text, str) and text.strip():
            ev = PublicEvent(text)
            ev.code = "initial_event"
            ev.params = {"content": text, "lang": preferred_language}
            sim.broadcast(ev)
    # For council, include draft announcement as an initial event if provided
    if scene_type == "council_scene":
        draft = str(cfg.get("draft_text") or "").strip()
        if draft:
            text = _localized(
                "The chamber will now consider the following draft for debate and vote:\n{draft}",
                "议事厅将讨论并表决以下草案：\n{draft}",
            ).format(draft=draft)
            ev = PublicEvent(text)
            ev.code = "council_draft"
            ev.params = {"draft": draft, "lang": preferred_language}
            sim.broadcast(ev)
    return SimTree.new(sim, sim.clients)


class SimTreeRegistry:
    def __init__(self) -> None:
        self._records: Dict[str, SimTreeRecord] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self, simulation_id: str, scene_type: str, clients: dict | None = None
    ) -> SimTreeRecord:
        key = simulation_id.upper()
        record = self._records.get(key)
        if record is not None:
            record.touch()
            return record
        async with self._lock:
            record = self._records.get(key)
            if record is not None:
                record.touch()
                return record
            tree = await asyncio.to_thread(_build_tree_for_scene, scene_type, clients)
            record = SimTreeRecord(tree)
            wire_tree_broadcast(record, tree, asyncio.get_running_loop(), logger)
            self._records[key] = record
            return record

    async def get_or_create_from_sim(
        self, sim_record, clients: dict | None = None
    ) -> SimTreeRecord:
        key = sim_record.id.upper()
        record = self._records.get(key)
        if record is not None:
            record.touch()
            if (
                not record.running
                and getattr(sim_record, "latest_state", None)
                and record.tree.serialize() != sim_record.latest_state
            ):
                loop = asyncio.get_running_loop()
                tree = SimTree.deserialize(
                    sim_record.latest_state, clients or make_clients_from_env()
                )
                wire_tree_broadcast(record, tree, loop, logger)
                record.replace_tree(tree)
            return record
        async with self._lock:
            record = self._records.get(key)
            if record is not None:
                record.touch()
                if (
                    not record.running
                    and getattr(sim_record, "latest_state", None)
                    and record.tree.serialize() != sim_record.latest_state
                ):
                    loop = asyncio.get_running_loop()
                    tree = SimTree.deserialize(
                        sim_record.latest_state, clients or make_clients_from_env()
                    )
                    wire_tree_broadcast(record, tree, loop, logger)
                    record.replace_tree(tree)
                return record
            # 优先使用最新持久化的 latest_state 进行恢复；否则重新构建
            if getattr(sim_record, "latest_state", None):
                try:
                    tree = SimTree.deserialize(
                        sim_record.latest_state, clients or make_clients_from_env()
                    )
                except Exception:
                    logger.exception(
                        "Failed to deserialize latest_state, fallback to rebuild"
                    )
                    tree = await asyncio.to_thread(
                        _build_tree_for_sim, sim_record, clients
                    )
            else:
                tree = await asyncio.to_thread(_build_tree_for_sim, sim_record, clients)
            record = SimTreeRecord(tree)
            wire_tree_broadcast(record, tree, asyncio.get_running_loop(), logger)
            self._records[key] = record
            return record

    def remove(self, simulation_id: str) -> None:
        record = self._records.pop(simulation_id.upper(), None)
        if record is not None:
            record.cleanup_runtime_resources()

    def get(self, simulation_id: str) -> SimTreeRecord | None:
        record = self._records.get(simulation_id.upper())
        if record is not None:
            record.touch()
        return record

    def evict_idle_records(
        self,
        idle_ttl_seconds: float,
        now: float | None = None,
        max_records: int | None = None,
    ) -> list[str]:
        """Remove cached trees that are idle and safe to discard."""
        current_time = now if now is not None else time.monotonic()
        candidates = [
            (key, record)
            for key, record in self._records.items()
            if record.is_idle(idle_ttl_seconds, current_time)
        ]
        if max_records is not None and len(self._records) > max_records:
            overflow = len(self._records) - max_records
            extra_candidates = sorted(
                [
                    (key, record)
                    for key, record in self._records.items()
                    if not record.running and not record.subs
                ],
                key=lambda item: item[1].last_accessed_at,
            )
            for item in extra_candidates[:overflow]:
                if item not in candidates:
                    candidates.append(item)

        evicted: list[str] = []
        for key, record in candidates:
            if self._records.get(key) is not record:
                continue
            record.cleanup_runtime_resources()
            self._records.pop(key, None)
            evicted.append(key)
        return evicted

    def update_agent_knowledge(self, simulation_id: str, agent_config: dict) -> bool:
        """
        Update agent knowledge bases and documents in all nodes of an existing tree.
        This preserves simulation state while updating knowledge.

        IMPORTANT: This function MERGES knowledge/documents - it only updates agents
        that are explicitly in the config, and preserves existing data for agents
        not in the config.

        Returns True if tree was found and updated, False if no tree exists.
        """
        key = simulation_id.upper()
        record = self._records.get(key)
        if record is None:
            return False
        return update_tree_agent_knowledge(record, agent_config)

    def metrics(self) -> dict:
        """
        Return a snapshot of registry health metrics for the /api/health endpoint.

        Exposes only the data the health check needs, keeping internal state private.
        Called by the health route — do not access _records directly from outside this class.
        """
        active_simulations = len(self._records)
        active_websocket_connections = sum(
            len(record.subs) for record in self._records.values()
        )
        tree_nodes = sum(
            len(getattr(record.tree, "nodes", {}) or {})
            for record in self._records.values()
        )
        gaworld_subprocesses = 0
        for record in self._records.values():
            for node in getattr(record.tree, "nodes", {}).values():
                sim = node.get("sim") if isinstance(node, dict) else None
                scene = getattr(sim, "scene", None)
                managers = []
                manager = getattr(scene, "_subprocess_manager", None)
                if manager is not None:
                    managers.append(manager)
                comparative = getattr(scene, "_comparative_managers", None)
                if comparative:
                    managers.extend(list(comparative))
                for item in managers:
                    is_alive = getattr(item, "is_alive", None)
                    if is_alive is not None and is_alive():
                        gaworld_subprocesses += 1
        return {
            "active_simulations": active_simulations,
            "active_websocket_connections": active_websocket_connections,
            "tree_nodes": tree_nodes,
            "gaworld_subprocesses": gaworld_subprocesses,
        }

    def update_global_knowledge(
        self, simulation_id: str, global_knowledge: dict
    ) -> bool:
        """
        Update global knowledge reference in all agents of an existing tree.

        Returns True if tree was found and updated, False if no tree exists.
        """
        key = simulation_id.upper()
        record = self._records.get(key)
        if record is None:
            return False
        return update_tree_global_knowledge(record, global_knowledge)


SIM_TREE_REGISTRY = SimTreeRegistry()
