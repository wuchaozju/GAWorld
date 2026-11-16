import random as _random
from typing import List, Tuple

from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.scenes.council_experiment import CouncilExperimentScene
from fos.core.experiment.scenes.gaworld.scene import GAWorldScene
from fos.core.experiment.scene import ExperimentScene
from fos.core.contagion.scene import ContagionScene
from fos.core.scenes.policy_cascade_experiment import PolicyCascadeExperimentScene
from fos.core.scenes.policy_cascade import PolicyCascadeScene

ACTION_SPACE_MAP: dict = {}


SCENE_MAP = {
    "council_experiment": CouncilExperimentScene,
    "experiment_template": ExperimentScene,
    "contagion_scene": ContagionScene,
    "policy_cascade_experiment": PolicyCascadeExperimentScene,
    "policy_cascade_scene": PolicyCascadeScene,
    "gaworld_scene": GAWorldScene,
}


def get_scene_class(scene_key: str):
    """Get a scene class from SCENE_MAP, handling lazy loading.

    Args:
        scene_key: The key to look up in SCENE_MAP

    Returns:
        The scene class (callable if it was a lazy loader)
    """
    scene_cls = SCENE_MAP.get(scene_key)
    if scene_cls is None:
        return None
    # If it's a callable (lazy loader), call it to get the actual class
    if callable(scene_cls) and not isinstance(scene_cls, type):
        return scene_cls()
    return scene_cls


# Scene action registry: declares common (basic) actions provided by the scene
# and optional per-agent actions that can be toggled. Keep action names aligned
# with ACTION_SPACE_MAP keys.
SCENE_ACTIONS: dict[str, dict[str, list[str]]] = {
    "council_experiment": {  # REFACTOR-COUNCIL-06: Council experiment uses experiment scene actions
        "basic": [],
        "allowed": [],
    },
    "experiment_template": {
        "basic": [],
        "allowed": [],
    },
    "contagion_scene": {
        "basic": ["move", "speak_to"],
        "allowed": [],
    },
    "gaworld_scene": {
        "basic": ["work", "social_interact", "consume_media", "move", "rest"],
        "allowed": [],
    },
}

def pair_agents_randomly(agents: List[str], round_num: int) -> List[Tuple[str, str]]:
    """Deterministically pair agents by round_num seed (no global state side-effects)."""
    rng = _random.Random(round_num)
    shuffled = list(agents)
    rng.shuffle(shuffled)
    return [(shuffled[i], shuffled[i + 1]) for i in range(0, len(shuffled) - 1, 2)]


def werewolf_visibility_scope(
    agent: str, state: dict, all_agents: List[str]
) -> List[str]:
    """Mafia members see each other; villagers see only themselves."""
    roles = state.get("roles", {})
    if roles.get(agent) == "mafia":
        return [a for a, r in roles.items() if r == "mafia"]
    return [agent]


INFORMATION_MODEL_MAP: dict = {
    # Scene keys must exactly match SCENE_MAP keys
    "council_experiment": InformationModel(scope_type="all", recent_window=3, include_scores=False),  # REFACTOR-COUNCIL-06
    "policy_cascade_scene": InformationModel(scope_type="all", recent_window=3),
    "policy_cascade_experiment": InformationModel(
        scope_type="neighborhood",
        recent_window=5,
        include_scores=False,
    ),
    "experiment_template": InformationModel(scope_type="all", recent_window=3),
    # Scenario-level keys (used when scene_type == scenario id)
    "prisoners_dilemma": InformationModel(
        scope_type="pair",
        pairing_fn=pair_agents_randomly,
        recent_window=3,
        payoff_template="Round {N}: {my_action} vs {partner_action} → {payoff} pts",
    ),
    # Aliases for frontend compatibility (frontend may use hyphens)
    "prisoners-dilemma": InformationModel(
        scope_type="pair",
        pairing_fn=pair_agents_randomly,
        recent_window=3,
        payoff_template="Round {N}: {my_action} vs {partner_action} → {payoff} pts",
    ),
    "public_goods": InformationModel(scope_type="all", recent_window=3),
    "public-goods": InformationModel(scope_type="all", recent_window=3),
    # Graph Coloring / Coordination Game - neighbor-based coordination with feedback (no scores)
    "graph_coloring": InformationModel(
        scope_type="neighborhood",
        recent_window=5,
        include_scores=False,  # No scores for feedback-type games
    ),
    "graph-coloring": InformationModel(
        scope_type="neighborhood",
        recent_window=5,
        include_scores=False,
    ),
    "coordination_game": InformationModel(
        scope_type="neighborhood",
        recent_window=5,
        include_scores=False,
    ),
    "coordination-game": InformationModel(
        scope_type="neighborhood",
        recent_window=5,
        include_scores=False,
    ),
    # Sociology scenarios - no payoff scores to show
    "social_norm_disruption": InformationModel(scope_type="all", recent_window=3, include_scores=False),
    "policy_erosion": InformationModel(scope_type="all", recent_window=3, include_scores=False),
    "echo_chamber": InformationModel(scope_type="neighborhood", recent_window=3, include_scores=False),
    "resource_scarcity": InformationModel(scope_type="all", recent_window=3, include_scores=False),
    "open_discussion": InformationModel(scope_type="all", recent_window=3, include_scores=False),
    "werewolf": InformationModel(scope_type="all", recent_window=3, include_scores=False),  # LEGACY: unsupported
    "grid_world": InformationModel(scope_type="neighborhood", recent_window=3, include_scores=False),
    "contagion_scene": InformationModel(scope_type="neighborhood", recent_window=3, include_scores=False),
    "gaworld_scene": InformationModel(scope_type="all", recent_window=3, include_scores=False),
    # Fallback for unknown scene types
    "_default": InformationModel(scope_type="all", recent_window=3),
}


def get_information_model(scene_type: str) -> InformationModel:
    """Return the InformationModel for a scene type, with _default fallback.

    Normalizes hyphens to underscores for lookup (frontend uses 'prisoners-dilemma',
    backend uses 'prisoners_dilemma').
    """
    normalized = scene_type.replace("-", "_")
    if normalized in INFORMATION_MODEL_MAP:
        return INFORMATION_MODEL_MAP[normalized]

    from fos.core.scenarios.registry import get_scenario

    scenario = get_scenario(normalized)
    if scenario is None:
        return INFORMATION_MODEL_MAP["_default"]

    grouping_mode = scenario.get("grouping_mode", "all")
    payoff_type = scenario.get("payoff_type", "none")

    if grouping_mode == "neighbor":
        scope_type = "neighborhood"
    elif grouping_mode == "pairwise":
        scope_type = "pair"
    else:
        scope_type = "all"

    return InformationModel(
        scope_type=scope_type,
        pairing_fn=pair_agents_randomly if scope_type == "pair" else None,
        recent_window=3,
        include_scores=payoff_type not in ("none", "feedback", ""),
    )


# Scene descriptions for selection UI and docs
SCENE_DESCRIPTIONS: dict[str, str] = {
    "council_experiment": "Council experiment using experiment framework with multi-round deliberation context and phase-based action filtering.",
    "experiment_template": "Social science experiment using Three-Layer Architecture (constrained decoding, structured prompts, validation). Supports custom actions and simultaneous/sequential rounds.",
    "contagion_scene": "SEIR contagion dynamics on a grid. Agents spread infection through proximity and social interactions, with configurable transmission rates and recovery.",
    "policy_cascade_experiment": "Pipeline A policy cascade scene. Agents at different organizational tiers share and distort policy information as it passes through the hierarchy.",
    "gaworld_scene": "gaworld.scene.description",
}
