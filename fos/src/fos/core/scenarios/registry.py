"""
Scenario registry for FOS experiment builder.

Provides static scenario metadata for all available experiment templates.
Each scenario defines parameters, actions, and settings for the frontend.
"""

from typing import Dict, List, Any
from .actions import CATEGORY_ACTION_LIBRARIES
from ...i18n import T, get_request_locale


# ============================================================================
# Game Theory Scenarios
# ============================================================================

PRISONERS_DILEMMA: Dict[str, Any] = {
    "id": "prisoners_dilemma",
    "name": "Prisoner's Dilemma",
    "category": "game_theory",
    "description": "Two suspects are arrested and held separately. Each must decide whether to betray the other or remain silent. Your payoff depends on both your choice and your partner's choice.",
    "grouping_mode": "pairwise",
    "payoff_type": "matrix",
    "interaction_mode": "simultaneous",
    "display_type": "payoff_matrix",
    "matrix_meta": {
        "symmetric": False,
        "rows": ["Cooperate", "Defect"],
        "cols": ["Cooperate", "Defect"],
        "cells": {
            "cooperate_cooperate": {"row": 3, "col": 3},
            "cooperate_defect": {"row": 0, "col": 5},
            "defect_cooperate": {"row": 5, "col": 0},
            "defect_defect": {"row": 1, "col": 1},
        }
    },
    "description_template": "Two agents choose between {action_1} or {action_2}. Payoff depends on both choices.",
    "parameters": [
        {
            "id": "cooperate_reward",
            "key": "cooperate_reward",
            "label": "Both Cooperate",
            "type": "integer",
            "default": 3,
            "ui_hint": "number",
            "min": 0,
            "max": 10,
        },
        {
            "id": "sucker_penalty",
            "key": "sucker_penalty",
            "label": "You Cooperate, They Defect",
            "type": "integer",
            "default": 0,
            "ui_hint": "number",
            "min": 0,
            "max": 10,
        },
        {
            "id": "temptation_reward",
            "key": "temptation_reward",
            "label": "You Defect, They Cooperate",
            "type": "integer",
            "default": 5,
            "ui_hint": "number",
            "min": 0,
            "max": 10,
        },
        {
            "id": "defect_penalty",
            "key": "defect_penalty",
            "label": "Both Defect",
            "type": "integer",
            "default": 1,
            "ui_hint": "number",
            "min": 0,
            "max": 10,
        },
        {
            "id": "action_1",
            "key": "action_1",
            "label": "Action 1 Name",
            "type": "string",
            "default": "Cooperate",
            "ui_hint": "text",
        },
        {
            "id": "action_2",
            "key": "action_2",
            "label": "Action 2 Name",
            "type": "string",
            "default": "Defect",
            "ui_hint": "text",
        },
    ],
    "actions": [
        {"id": "cooperate", "name": "Cooperate", "description": "Work together with your partner"},
        {"id": "defect", "name": "Defect", "description": "Pursue your own interest"},
    ],
}

BATTLE_OF_THE_SEXES: Dict[str, Any] = {
    "id": "battle_of_the_sexes",
    "name": "Battle of the Sexes",
    "category": "game_theory",
    "description": "A couple wants to coordinate on an evening activity. One prefers opera, the other prefers football. They get positive payoff if they coordinate, but each prefers their own activity.",
    "grouping_mode": "pairwise",
    "payoff_type": "matrix",
    "interaction_mode": "simultaneous",
    "display_type": "payoff_matrix",
    "matrix_meta": {
        "symmetric": False,
        "rows": ["Opera", "Football"],
        "cols": ["Opera", "Football"],
        "cells": {
            "opera_opera": {"row": 3, "col": 1},
            "opera_football": {"row": 0, "col": 0},
            "football_opera": {"row": 0, "col": 0},
            "football_football": {"row": 1, "col": 3},
        }
    },
    "description_template": "Two agents coordinate. One prefers {action_1}, the other {action_2}.",
    "parameters": [
        {
            "id": "preferred_mispreferred",
            "key": "preferred_mispreferred",
            "label": "Preferred / Mispreferred Payoff",
            "type": "integer",
            "default": 3,
            "ui_hint": "slider",
            "min": 1,
            "max": 5,
        },
        {
            "id": "mispreferred_payoff",
            "key": "mispreferred_payoff",
            "label": "Mispreferred Alone Payoff",
            "type": "integer",
            "default": 0,
            "ui_hint": "slider",
            "min": 0,
            "max": 5,
        },
        {
            "id": "action_1_name",
            "key": "action_1_name",
            "label": "Action 1 Name",
            "type": "string",
            "default": "Opera",
            "ui_hint": "text",
            "category": "actions",
        },
        {
            "id": "action_1_description",
            "key": "action_1_description",
            "label": "Action 1 Description",
            "type": "string",
            "default": "Go to the opera",
            "ui_hint": "text",
            "category": "actions",
        },
        {
            "id": "action_2_name",
            "key": "action_2_name",
            "label": "Action 2 Name",
            "type": "string",
            "default": "Football",
            "ui_hint": "text",
            "category": "actions",
        },
        {
            "id": "action_2_description",
            "key": "action_2_description",
            "label": "Action 2 Description",
            "type": "string",
            "default": "Go to the football game",
            "ui_hint": "text",
            "category": "actions",
        },
    ],
    "actions": [
        {"id": "opera", "name": "Opera", "description": "Go to the opera"},
        {"id": "football", "name": "Football", "description": "Go to the football game"},
    ],
}

STAG_HUNT: Dict[str, Any] = {
    "id": "stag_hunt",
    "name": "Stag Hunt",
    "category": "game_theory",
    "description": "Hunters must all choose stag (high reward) or hare (safe but low reward). Stag requires everyone to cooperate. If even one person chooses hare, the stag escapes and stag hunters get nothing.",
    "grouping_mode": "group",
    "payoff_type": "matrix",
    "interaction_mode": "simultaneous",
    "display_type": "payoff_matrix",
    "matrix_meta": {
        "symmetric": True,
        "rows": ["Stag", "Hare"],
        "cols": ["Stag", "Hare"],
        "cells": {
            "stag_stag": {"value": 5},
            "stag_hare": {"value": 0},
            "hare_stag": {"value": 1},
            "hare_hare": {"value": 1},
        }
    },
    "description_template": "Group chooses {action_1} (risky, high reward if all cooperate) or {action_2} (safe, lower reward).",
    "parameters": [
        {
            "id": "stag_reward",
            "key": "stag_reward",
            "label": "Stag Reward (if all choose)",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 1,
            "max": 10,
        },
        {
            "id": "hare_reward",
            "key": "hare_reward",
            "label": "Hare Reward (always)",
            "type": "integer",
            "default": 1,
            "ui_hint": "slider",
            "min": 0,
            "max": 5,
        },
        {
            "id": "action_1_name",
            "key": "action_1_name",
            "label": "Action 1 Name",
            "type": "string",
            "default": "Stag",
            "ui_hint": "text",
            "category": "actions",
        },
        {
            "id": "action_1_description",
            "key": "action_1_description",
            "label": "Action 1 Description",
            "type": "string",
            "default": "Hunt the stag (requires all to cooperate)",
            "ui_hint": "text",
            "category": "actions",
        },
        {
            "id": "action_2_name",
            "key": "action_2_name",
            "label": "Action 2 Name",
            "type": "string",
            "default": "Hare",
            "ui_hint": "text",
            "category": "actions",
        },
        {
            "id": "action_2_description",
            "key": "action_2_description",
            "label": "Action 2 Description",
            "type": "string",
            "default": "Hunt the hare (safe but lower reward)",
            "ui_hint": "text",
            "category": "actions",
        },
    ],
    "actions": [
        {"id": "stag", "name": "Stag", "description": "Hunt the stag (requires all to cooperate)"},
        {"id": "hare", "name": "Hare", "description": "Hunt the hare (safe but lower reward)"},
    ],
}

# ============================================================================
# Sociology Scenarios
# ============================================================================

SOCIAL_NORM_DISRUPTION: Dict[str, Any] = {
    "id": "social_norm_disruption",
    "name": "Social Norm Disruption",
    "category": "sociology",
    "description": "A new rule is suddenly imposed on the group. Agents with different social status and temperament must decide how to respond.",
    "grouping_mode": "group",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "norm_strength",
            "key": "norm_strength",
            "label": "Norm Strength",
            "type": "number",
            "default": 0.8,
            "ui_hint": "percentage",
        },
        {
            "id": "agent_status_distribution",
            "key": "agent_status_distribution",
            "label": "Agent Status Distribution",
            "type": "string",
            "default": "mixed",
            "ui_hint": "select",
            "options": ["high_status", "low_status", "mixed"],
        },
    ],
    "actions": [],
    "category_actions": "sociology",
    "default_action_ids": ["comply_publicly", "comply_covertly_resist", "resist_openly", "persuade_others"],
}

POLICY_EROSION: Dict[str, Any] = {
    "id": "policy_erosion",
    "name": "Policy Meaning Erosion",
    "category": "sociology",
    "description": "A configurable multi-level hierarchy must transmit a policy from top to bottom. Each level may preserve, reinterpret, distort, or block the directive.",
    "grouping_mode": "individual",
    "payoff_type": "none",
    "interaction_mode": "sequential",
    "display_type": "params",
    "parameters": [
        {
            "id": "cascade_mode",
            "key": "cascade_mode",
            "label": "Cascade Mode",
            "type": "string",
            "default": "strict_cascade",
            "ui_hint": "select",
            "options": ["strict_cascade", "distortion_cascade"],
            "description": "Choose whether downstream tiers must pass the policy faithfully or may distort and block it.",
        },
        {
            "id": "distortion_strength",
            "key": "distortion_strength",
            "label": "Distortion Strength",
            "type": "number",
            "default": 0.6,
            "ui_hint": "percentage",
            "description": "How strongly agents rewrite the policy when distortion mode is active.",
        },
        {
            "id": "conflict_sensitivity",
            "key": "conflict_sensitivity",
            "label": "Conflict Sensitivity",
            "type": "number",
            "default": 0.5,
            "ui_hint": "percentage",
            "description": "How strongly perceived value conflicts increase resistance to transmission.",
        },
        {
            "id": "block_probability",
            "key": "block_probability",
            "label": "Block Probability",
            "type": "number",
            "default": 0.25,
            "ui_hint": "percentage",
            "description": "Base chance that an agent stops the policy instead of forwarding it in distortion mode.",
        },
        {
            "id": "num_agents_per_tier",
            "key": "num_agents_per_tier",
            "label": "Agents per Tier",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 2,
            "max": 10,
            "description": "How many agents are created for each hierarchy level.",
        },
        {
            "id": "policy_text",
            "key": "policy_text",
            "label": "Initial Background Context",
            "type": "string",
            "default": "All employees must complete mandatory training by Friday",
            "ui_hint": "textarea",
            "placeholder": "Enter the opening background or situation shown before the policy cascade begins.",
            "description": "Used only to set the opening background for round 1. It does not automatically become the protected source policy for later relay.",
        },
    ],
    "actions": [],
    "category_actions": "sociology",
    "default_action_ids": ["transmit_faithfully", "reinterpret_downward", "comply_directive", "resist_quietly"],
}

POLICY_CASCADE_EXPERIMENT: Dict[str, Any] = {
    "id": "policy_cascade_experiment",
    "name": "Policy Cascade (Experiment)",
    "category": "sociology",
    "description": "A multi-tier hierarchy transmits a policy from top to bottom using the Pipeline A experiment engine. Each level may preserve, reinterpret, distort, or block the directive.",
    "grouping_mode": "individual",
    "payoff_type": "none",
    "interaction_mode": "sequential",
    "display_type": "params",
    "parameters": [
        {
            "id": "tier_order",
            "key": "tier_order",
            "label": "Tier Order",
            "type": "string",
            "default": "top, mid, low",
            "ui_hint": "text",
            "description": "Comma-separated hierarchy levels from highest to lowest.",
        },
        {
            "id": "cascade_mode",
            "key": "cascade_mode",
            "label": "Cascade Mode",
            "type": "string",
            "default": "strict_cascade",
            "ui_hint": "select",
            "options": ["strict_cascade", "distortion_cascade"],
            "description": "Choose whether downstream tiers must pass the policy faithfully or may distort and block it.",
        },
        {
            "id": "distortion_strength",
            "key": "distortion_strength",
            "label": "Distortion Strength",
            "type": "number",
            "default": 0.6,
            "ui_hint": "percentage",
            "description": "How strongly agents rewrite the policy when distortion mode is active.",
        },
        {
            "id": "conflict_sensitivity",
            "key": "conflict_sensitivity",
            "label": "Conflict Sensitivity",
            "type": "number",
            "default": 0.5,
            "ui_hint": "percentage",
            "description": "How strongly perceived value conflicts increase resistance to transmission.",
        },
        {
            "id": "block_probability",
            "key": "block_probability",
            "label": "Block Probability",
            "type": "number",
            "default": 0.25,
            "ui_hint": "percentage",
            "description": "Base chance that an agent stops the policy instead of forwarding it in distortion mode.",
        },
        {
            "id": "num_agents_per_tier",
            "key": "num_agents_per_tier",
            "label": "Agents per Tier",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 2,
            "max": 10,
            "description": "How many agents are created for each hierarchy level.",
        },
        {
            "id": "policy_text",
            "key": "policy_text",
            "label": "Initial Background Context",
            "type": "string",
            "default": "All employees must complete mandatory training by Friday",
            "ui_hint": "textarea",
            "placeholder": "Enter the opening background or situation shown before the policy cascade begins.",
            "description": "Used only to set the opening background for round 1. It does not automatically become the protected source policy for later relay.",
        },
    ],
    "actions": [],
    "category_actions": "sociology",
    "default_action_ids": ["transmit_faithfully", "reinterpret_downward", "comply_directive", "resist_quietly"],
}

ECHO_CHAMBER: Dict[str, Any] = {
    "id": "echo_chamber",
    "name": "Echo Chamber",
    "category": "sociology",
    "description": "Agents with initial opinions interact and share information. They prefer connections with similar views, leading to potential polarization.",
    "grouping_mode": "neighbor",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "connection_homogeneity",
            "key": "connection_homogeneity",
            "label": "Connection Homogeneity",
            "type": "number",
            "default": 0.7,
            "ui_hint": "percentage",
        },
        {
            "id": "opinion_distribution",
            "key": "opinion_distribution",
            "label": "Initial Opinion Distribution",
            "type": "string",
            "default": "balanced",
            "ui_hint": "select",
            "options": ["balanced", "polarized", "random"],
        },
    ],
    "actions": [],
    "category_actions": "sociology",
    "default_action_ids": ["express_opinion", "reinforce_ingroup", "share_content", "disengage"],
}

RESOURCE_SCARCITY: Dict[str, Any] = {
    "id": "resource_scarcity",
    "name": "Resource Scarcity",
    "category": "sociology",
    "description": "A community has limited resources. Agents must decide whether to cooperate by sharing or compete by hoarding. Tests trust and collective action.",
    "grouping_mode": "group",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "resource_amount",
            "key": "resource_amount",
            "label": "Total Resources",
            "type": "integer",
            "default": 100,
            "ui_hint": "slider",
            "min": 10,
            "max": 200,
        },
        {
            "id": "initial_distribution",
            "key": "initial_distribution",
            "label": "Initial Distribution",
            "type": "string",
            "default": "equal",
            "ui_hint": "select",
            "options": ["equal", "random", "skewed"],
        },
    ],
    "actions": [],
    "category_actions": "sociology",
    "default_action_ids": ["share_resources", "hoard", "propose_trade", "form_contract"],
}

XIHU_YILIANBAO: Dict[str, Any] = {
    "id": "xihu_yilianbao",
    "name": "Xihu Yilianbao Enrollment Diffusion",
    "category": "sociology",
    "description": "Eligible residents receive one of the A0-A8 information interventions, then decide whether to enroll for themselves or family members under government endorsement, message complexity, household medical burden, competitor news, and neighborhood discussion.",
    "grouping_mode": "individual",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "xihu_package_id",
            "key": "xihu_package_id",
            "label": "Package ID",
            "type": "string",
            "default": "round1",
            "ui_hint": "text",
        },
        {
            "id": "intervention_arm",
            "key": "intervention_arm",
            "label": "Intervention Arm",
            "type": "string",
            "default": "A0",
            "ui_hint": "select",
            "options": ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"],
        },
    ],
    "actions": [],
    "category_actions": "sociology",
    "default_action_ids": ["express_opinion", "persuade_others", "seek_common_ground", "disengage"],
}

# ============================================================================
# Discussion / Open Scenarios
# ============================================================================

OPEN_DISCUSSION: Dict[str, Any] = {
    "id": "open_discussion",
    "name": "Open Discussion",
    "category": "discussion",
    "description": "Agents discuss a topic freely. No structured decisions - just conversation.",
    "grouping_mode": "individual",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "topic",
            "key": "topic",
            "label": "Discussion Topic",
            "type": "string",
            "default": "What should we have for lunch?",
            "ui_hint": "textarea",
        },
    ],
    "actions": [
        {"id": "speak", "name": "Speak", "description": "Say something to the group"},
    ],
}

COUNCIL_CHAMBER: Dict[str, Any] = {
    "id": "council_chamber",
    "name": "Council Chamber",
    "category": "discussion",
    "description": "Formal deliberation with voting and procedural rules. Participants debate proposals, call for votes, and make collective decisions.",
    "grouping_mode": "individual",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "proposal_text",
            "key": "proposal_text",
            "label": "Proposal Text",
            "type": "string",
            "default": "",
            "ui_hint": "textarea",
        },
        {
            "id": "voting_threshold",
            "key": "voting_threshold",
            "label": "Voting Threshold",
            "type": "number",
            "default": 0.5,
            "ui_hint": "slider",
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
        },
        {
            "id": "max_rounds",
            "key": "max_rounds",
            "label": "Max Debate Rounds",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 1,
            "max": 10,
        },
    ],
    "actions": [
        {"id": "speak", "name": "Speak", "description": "Make a statement during deliberation"},
        {"id": "skip", "name": "Skip", "description": "Pass your turn"},
        {"id": "vote_yes", "name": "Vote Yes", "description": "Vote in favor of the proposal"},
        {"id": "vote_no", "name": "Vote No", "description": "Vote against the proposal"},
        {"id": "abstain", "name": "Abstain", "description": "Neither yes nor no"},
    ],
}

# ============================================================================
# Spatial Scenarios (Grid-Based)
# ============================================================================

GRID_WORLD: Dict[str, Any] = {
    "id": "grid_world",
    "name": "Grid World",
    "category": "spatial",
    "description": "Agents move on a grid, collecting resources and observing their environment.",
    "grouping_mode": "neighbor",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "grid_size",
            "key": "grid_size",
            "label": "Grid Size",
            "type": "integer",
            "default": 10,
            "ui_hint": "slider",
            "min": 5,
            "max": 20,
        },
        {
            "id": "resource_count",
            "key": "resource_count",
            "label": "Resource Count",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 1,
            "max": 20,
        },
    ],
    "actions": [
        {"id": "move", "name": "Move", "description": "Move to an adjacent tile (north/south/east/west)"},
        {"id": "look_around", "name": "Look Around", "description": "Observe surroundings (observation only)"},
        {"id": "rest", "name": "Rest", "description": "Do nothing this turn"},
    ],
}

GAWORLD: Dict[str, Any] = {
    "id": "gaworld",
    "name": "scenario_templates.gaworld.name",
    "category": "generative_city",
    "description": "scenario_templates.gaworld.description",
    "grouping_mode": "all",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "timeline",
    "parameters": [
        {
            "id": "execution_profile",
            "key": "execution_profile",
            "label": "scenario_templates.gaworld.parameters.execution_profile.label",
            "description": "scenario_templates.gaworld.parameters.execution_profile.description",
            "type": "string",
            "default": "fast",
            "ui_hint": "select",
            "options": ["fast", "balanced", "full_fidelity"],
        },
        {
            "id": "information_mode",
            "key": "information_mode",
            "label": "scenario_templates.gaworld.parameters.information_mode.label",
            "description": "scenario_templates.gaworld.parameters.information_mode.description",
            "type": "string",
            "default": "city_news",
            "ui_hint": "select",
            "options": ["off", "city_news", "active_flow"],
        },
        {
            "id": "daily_life_mode",
            "key": "daily_life_mode",
            "label": "scenario_templates.gaworld.parameters.daily_life_mode.label",
            "description": "scenario_templates.gaworld.parameters.daily_life_mode.description",
            "type": "string",
            "default": "some_variation",
            "ui_hint": "select",
            "options": ["stable_routines", "some_variation", "flexible_daily_life"],
        },
        {
            "id": "people_mode",
            "key": "people_mode",
            "label": "scenario_templates.gaworld.parameters.people_mode.label",
            "description": "scenario_templates.gaworld.parameters.people_mode.description",
            "type": "string",
            "default": "adaptive_behavior",
            "ui_hint": "select",
            "options": ["simple_behavior", "adaptive_behavior", "rich_human_behavior"],
        },
        {
            "id": "memory_mode",
            "key": "memory_mode",
            "label": "scenario_templates.gaworld.parameters.memory_mode.label",
            "description": "scenario_templates.gaworld.parameters.memory_mode.description",
            "type": "string",
            "default": "some_continuity",
            "ui_hint": "select",
            "options": ["in_the_moment", "some_continuity", "rich_memory"],
        },
        {
            "id": "seed",
            "key": "seed",
            "label": "scenario_templates.gaworld.parameters.seed.label",
            "description": "scenario_templates.gaworld.parameters.seed.description",
            "type": "integer",
            "default": 42,
            "ui_hint": "number",
        },
    ],
    "actions": [
        {
            "id": "work",
            "name": "scenario_templates.gaworld.actions.work.name",
            "description": "scenario_templates.gaworld.actions.work.description",
        },
        {
            "id": "social_interact",
            "name": "scenario_templates.gaworld.actions.social_interact.name",
            "description": "scenario_templates.gaworld.actions.social_interact.description",
        },
        {
            "id": "consume_media",
            "name": "scenario_templates.gaworld.actions.consume_media.name",
            "description": "scenario_templates.gaworld.actions.consume_media.description",
        },
        {
            "id": "move",
            "name": "scenario_templates.gaworld.actions.move.name",
            "description": "scenario_templates.gaworld.actions.move.description",
        },
        {
            "id": "rest",
            "name": "scenario_templates.gaworld.actions.rest.name",
            "description": "scenario_templates.gaworld.actions.rest.description",
        },
    ],
}

# ============================================================================
# Social Deduction
# ============================================================================

WEREWOLF: Dict[str, Any] = {
    "id": "werewolf",
    "name": "Werewolf",
    "category": "social_deduction",
    "description": "A social deduction game where villagers try to identify werewolves among them while werewolves try to eliminate villagers at night.",
    "grouping_mode": "role_based",
    "payoff_type": "none",
    "interaction_mode": "sequential",
    "display_type": "params",
    "supported": False,
    "unsupported_reason": (
        "Werewolf requires a dedicated role/phase runtime before being re-enabled. "
        "Do not include in active regression expectations."
    ),
    "parameters": [
        {
            "id": "num_werewolves",
            "key": "num_werewolves",
            "label": "Number of Werewolves",
            "type": "integer",
            "default": 1,
            "ui_hint": "slider",
            "min": 1,
            "max": 3,
        },
        {
            "id": "num_villagers",
            "key": "num_villagers",
            "label": "Number of Villagers",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 3,
            "max": 10,
        },
    ],
    "actions": [
        {"id": "vote", "name": "Vote", "description": "Vote to eliminate a suspect"},
        {"id": "speak", "name": "Speak", "description": "Share your thoughts"},
    ],
}

# ============================================================================
# Custom Scenario
# ============================================================================

CUSTOM: Dict[str, Any] = {
    "id": "custom",
    "name": "Custom Scenario",
    "category": "custom",
    "description": "Open-ended networked conversation driven by a researcher-provided scenario prompt.",
    "grouping_mode": "neighbor",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "custom_prompt",
            "key": "custom_prompt",
            "label": "Custom Scenario Prompt",
            "type": "string",
            "default": "",
            "ui_hint": "textarea",
            "placeholder": "Describe the situation, roles, constraints, and what agents should discuss.",
            "description": "The scenario/context prompt shown to every agent.",
        },
        {
            "id": "turn_ordering",
            "key": "turn_ordering",
            "label": "Turn Ordering",
            "type": "string",
            "default": "sequential",
            "ui_hint": "select",
            "options": ["sequential", "random_sequential", "simultaneous"],
            "description": "How agents take turns in this open-ended conversation.",
        },
    ],
    "actions": [
        {"id": "speak", "name": "Speak", "description": "Say something to the group"},
        {"id": "skip", "name": "Skip", "description": "Pass without speaking this turn"},
    ],
    "default_action_ids": ["speak", "skip"],
}

# ============================================================================
# Public Goods Game
# ============================================================================

PUBLIC_GOODS: Dict[str, Any] = {
    "id": "public_goods",
    "name": "Public Goods Game",
    "category": "game_theory",
    "description": "Each person has resources and decides how much to contribute to a shared pool. The pool is multiplied and distributed equally among all members, regardless of contribution.",
    "grouping_mode": "group",
    "payoff_type": "pool",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "resource_name",
            "key": "resource_name",
            "label": "Resource Name",
            "type": "string",
            "default": "tokens",
            "ui_hint": "text",
            "category": "resource",
            "description": "Name of the resource (e.g., tokens, money, points)",
        },
        {
            "id": "tokens_per_round",
            "key": "tokens_per_round",
            "label": "Amount per Round",
            "type": "integer",
            "default": 10,
            "ui_hint": "number",
            "min": 1,
            "category": "resource",
            "description": "Amount of resources each agent receives per round",
        },
        {
            "id": "multiplier",
            "key": "multiplier",
            "label": "Pool Multiplier",
            "type": "number",
            "default": 1.3,
            "ui_hint": "number",
            "step": 0.01,
            "category": "resource",
            "description": "Multiplier applied to total group contributions before equal distribution",
        },
        # Deduction settings (punishment mechanism with neutral naming)
        {
            "id": "deduction_budget_per_phase",
            "key": "deduction_budget_per_phase",
            "label": "Deduction Budget per Phase",
            "type": "integer",
            "default": 0,
            "ui_hint": "number",
            "min": 0,
            "max": 100,
            "category": "deduction",
            "description": "Deduction points each agent receives per deduct phase. Set to 0 to disable.",
        },
        {
            "id": "deduction_cost_ratio",
            "key": "deduction_cost_ratio",
            "label": "Cost Ratio (1 : N)",
            "type": "number",
            "default": 3.0,
            "ui_hint": "number",
            "min": 1.0,
            "step": 0.1,
            "category": "deduction",
            "description": "How much target payoff is reduced per deduction point spent. Higher = stronger effect.",
        },
        {
            "id": "deduction_anonymous",
            "key": "deduction_anonymous",
            "label": "Anonymous Deductions",
            "type": "boolean",
            "default": False,
            "ui_hint": "toggle",
            "category": "deduction",
            "description": "When enabled, targets don't see who deducted from them.",
        },
    ],
    # All actions registered - phase filtering handled by get_scene_actions()
    "actions": [
        {
            "id": "allocate",
            "name": "Allocate",
            "description": "Allocate resources to the group account",
            "parameters": [
                {
                    "name": "amount",
                    "type": "integer",
                    "required": True,
                    "description": "How many tokens to contribute this round (integer, 0 to {tokens_per_round})",
                }
            ]
        },
        {"id": "keep", "name": "Keep", "description": "Keep all your resources this round"},
        {
            "id": "reduce",
            "name": "Reduce",
            "description": "Reduce another agent's resources",
            "parameters": [
                {
                    "name": "target",
                    "type": "string",
                    "required": True,
                    "description": "Name of the agent to reduce",
                },
                {
                    "name": "amount",
                    "type": "integer",
                    "required": True,
                    "description": "How many deduction points to spend",
                }
            ]
        },
        {"id": "skip", "name": "Skip", "description": "Do nothing this phase"},
    ],
    # Note: resources schema set dynamically in _initialize_state using resource_name
    "state_schema": {
        "extensions": {"pools": {"main": 0}},
        # Resources initialized dynamically - see ExperimentScene._initialize_state
    },
}

# ============================================================================
# Graph Coloring
# ============================================================================

COORDINATION_GAME: Dict[str, Any] = {
    "id": "coordination_game",
    "name": "Coordination Game",
    "category": "game_theory",
    "description": "You and your neighbors each pick an option. You can see what your neighbors chose in previous rounds.",
    "grouping_mode": "neighbor",
    "payoff_type": "feedback",
    "interaction_mode": "sequential",
    "display_type": "params",
    "parameters": [
        {
            "id": "choices",
            "key": "choices",
            "label": "Available Choices",
            "type": "string",
            "default": "red, blue, green",
            "ui_hint": "text",
            "description": "Comma-separated list of choices agents can pick from",
            "generates_actions": True,
        },
        {
            "id": "goal",
            "key": "goal",
            "label": "Coordination Goal",
            "type": "string",
            "default": "differ",
            "ui_hint": "select",
            "options": ["match", "differ"],
            "description": "Whether agents should try to match or differ from their neighbors",
        },
    ],
    "actions": [],
    "state_schema": {
        "extensions": {"choices": {}, "graph": {"edges": []}},
        "visibility": "neighbors",
    },
}

# ============================================================================
# Contagion Spread Scenario
# ============================================================================

CONTAGION: Dict[str, Any] = {
    "id": "contagion",
    "name": "Contagion Spread",
    "category": "spatial",
    "description": "Agents on a grid can spread contagion through proximity and social interactions. Watch as infection spreads through the population while agents move and communicate.",
    "grouping_mode": "neighbor",
    "payoff_type": "none",
    "interaction_mode": "simultaneous",
    "display_type": "params",
    "parameters": [
        {
            "id": "initial_infected",
            "key": "initial_infected",
            "label": "Initial Infected Agents",
            "type": "integer",
            "default": 1,
            "ui_hint": "slider",
            "min": 1,
            "max": 5,
            "description": "Number of agents that start infected",
        },
        {
            "id": "proximity_probability",
            "key": "proximity_probability",
            "label": "Proximity Transmission Rate",
            "type": "number",
            "default": 0.3,
            "ui_hint": "slider",
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
            "description": "Probability of transmission when agents are adjacent",
        },
        {
            "id": "action_probability",
            "key": "action_probability",
            "label": "Action Transmission Rate",
            "type": "number",
            "default": 0.5,
            "ui_hint": "slider",
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
            "description": "Probability of transmission when infected agent speaks to susceptible",
        },
        {
            "id": "recovery_turns",
            "key": "recovery_turns",
            "label": "Turns Until Recovery",
            "type": "integer",
            "default": 5,
            "ui_hint": "slider",
            "min": 1,
            "max": 20,
            "description": "Number of turns before infected agents recover",
        },
        {
            "id": "grid_size",
            "key": "grid_size",
            "label": "Grid Size",
            "type": "integer",
            "default": 10,
            "ui_hint": "slider",
            "min": 5,
            "max": 20,
            "description": "Size of the grid (N x N)",
        },
    ],
    "actions": [
        {"id": "move", "name": "Move", "description": "Move to an adjacent cell"},
        {"id": "speak", "name": "Speak", "description": "Talk to a nearby agent (may transmit contagion)"},
    ],
}

# ============================================================================
# Registry
# ============================================================================

ALL_SCENARIOS: List[Dict[str, Any]] = [
    PRISONERS_DILEMMA,
    BATTLE_OF_THE_SEXES,
    STAG_HUNT,
    SOCIAL_NORM_DISRUPTION,
    POLICY_EROSION,
    ECHO_CHAMBER,
    RESOURCE_SCARCITY,
    XIHU_YILIANBAO,
    OPEN_DISCUSSION,
    COUNCIL_CHAMBER,
    GRID_WORLD,
    GAWORLD,
    WEREWOLF,
    PUBLIC_GOODS,
    COORDINATION_GAME,
    CONTAGION,
    CUSTOM,
]


def _translate_scenario(template: dict, locale: str) -> dict:
    """Return a copy of a scenario template with translated text fields."""
    result = dict(template)
    key_prefix = template.get("id", "")
    name = T(f"scenario_templates.{key_prefix}.name", locale=locale)
    desc = T(f"scenario_templates.{key_prefix}.description", locale=locale)
    # Only overwrite when a real translation was found
    if name != f"scenario_templates.{key_prefix}.name":
        result["name"] = name
    if desc != f"scenario_templates.{key_prefix}.description":
        result["description"] = desc

    # Translate description_template if present (game theory scenarios)
    if "description_template" in result:
        dt = T(f"scenario_templates.{key_prefix}.description_template", locale=locale)
        if dt != f"scenario_templates.{key_prefix}.description_template":
            result["description_template"] = dt

    if "parameters" in result:
        translated_params = []
        for p in result["parameters"]:
            param = dict(p)
            param_key = p.get("key", p.get("id", ""))
            label = T(f"scenario_templates.{key_prefix}.parameters.{param_key}.label", locale=locale)
            pdesc = T(f"scenario_templates.{key_prefix}.parameters.{param_key}.description", locale=locale)
            if label != f"scenario_templates.{key_prefix}.parameters.{param_key}.label":
                param["label"] = label
            if pdesc != f"scenario_templates.{key_prefix}.parameters.{param_key}.description":
                param["description"] = pdesc
            translated_params.append(param)
        result["parameters"] = translated_params

    if "actions" in result:
        translated_actions = []
        for a in result["actions"]:
            action = dict(a)
            action_id = a.get("id", "")
            aname = T(f"scenario_templates.{key_prefix}.actions.{action_id}.name", locale=locale)
            adesc = T(f"scenario_templates.{key_prefix}.actions.{action_id}.description", locale=locale)
            if aname != f"scenario_templates.{key_prefix}.actions.{action_id}.name":
                action["name"] = aname
            if adesc != f"scenario_templates.{key_prefix}.actions.{action_id}.description":
                action["description"] = adesc
            translated_actions.append(action)
        result["actions"] = translated_actions

    return result


def get_all_scenarios(locale: str | None = None) -> List[Dict[str, Any]]:
    """Get all available scenario definitions.

    Args:
        locale: Language code. Falls back to request context or default.

    Returns:
        List of scenario dictionaries with metadata.
    """
    effective_locale = locale or get_request_locale()
    scenarios = []
    for scenario in ALL_SCENARIOS:
        # Skip unsupported scenarios (e.g., Werewolf)
        if scenario.get("supported") is False:
            continue
        # Copy scenario to avoid mutating original
        scenario_copy = scenario.copy()

        # Add category_actions for sociology scenarios
        if scenario_copy.get("category_actions") and isinstance(scenario_copy["category_actions"], str):
            category = scenario_copy["category_actions"]
            if category in CATEGORY_ACTION_LIBRARIES:
                scenario_copy["category_actions"] = CATEGORY_ACTION_LIBRARIES[category]
        scenarios.append(_translate_scenario(scenario_copy, effective_locale))
    return scenarios


def get_scenario(scenario_id: str, locale: str | None = None) -> Dict[str, Any] | None:
    """Get a specific scenario by ID.

    Args:
        scenario_id: The unique scenario identifier
        locale: Language code. Falls back to request context or default.

    Returns:
        A translated copy of the scenario dict, or None if not found.
    """
    effective_locale = locale or get_request_locale()
    for scenario in ALL_SCENARIOS:
        if scenario["id"] == scenario_id:
            scenario = scenario.copy()
            if scenario.get("category_actions") and isinstance(scenario["category_actions"], str):
                category = scenario["category_actions"]
                if category in CATEGORY_ACTION_LIBRARIES:
                    scenario["category_actions"] = CATEGORY_ACTION_LIBRARIES[category]
            return _translate_scenario(scenario, effective_locale)
    return None


def get_scenario_actions(scenario_id: str, locale: str | None = None) -> List[Dict[str, Any]]:
    """Get actions for a specific scenario.

    Args:
        scenario_id: The unique scenario identifier
        locale: Language code. Falls back to request context or default.

    Returns:
        List of action dicts with 'id' and 'description' keys.
        Returns empty list if scenario not found.
    """
    scenario = get_scenario(scenario_id, locale=locale)
    if not scenario:
        return []

    # If using category_actions
    if scenario.get("category_actions"):
        category_actions = scenario["category_actions"]
        if isinstance(category_actions, list):
            return [{"id": a["id"], "name": a["name"], "description": a["description"]} for a in category_actions]
        return []

    # If using direct actions
    return [
        {"id": a["id"], "name": a["name"], "description": a["description"]}
        for a in scenario.get("actions", [])
    ]
