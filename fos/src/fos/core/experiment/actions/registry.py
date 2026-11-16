"""
Action registry for experiments.

Contains all pre-built actions that scenarios can use.
Actions are registered by name and looked up during execution.

Contains: ACTION_REGISTRY, get_action, register_action
"""
from fos.core.experiment.actions.definitions import (
    ActionDefinition,
    ParameterSpec,
    EffectSpec,
)


# Pre-built action definitions
CHOOSE_ACTION = ActionDefinition(
    name="choose",
    description="Select an option from available choices",
    parameters=[
        ParameterSpec("choice", "enum", [], required=True),
    ],
    effects=[],
    requires=None,
    handler=None,
)

MOVE_ACTION = ActionDefinition(
    name="move",
    description="Move to an adjacent tile on the grid",
    parameters=[
        ParameterSpec("direction", "enum", ["north", "south", "east", "west"], required=True),
    ],
    effects=[
        EffectSpec("agent.position", "update_spatial", None),
    ],
    requires=["spatial"],
    handler=None,  # Will be set after handlers module is loaded
)

CONTRIBUTE_ACTION = ActionDefinition(
    name="contribute",
    description="Contribute resources to a pool",
    parameters=[
        ParameterSpec("amount", "number", [], required=True),
        ParameterSpec("pool", "enum", ["main"], required=False),
    ],
    effects=[
        EffectSpec("agent.resources.tokens", "subtract", "amount"),
        EffectSpec("extensions.pools.main", "add", "amount"),
    ],
    requires=["resources", "pools"],
    handler=None,
)

TALK_ACTION = ActionDefinition(
    name="talk",
    description="Send a message to another agent",
    parameters=[
        ParameterSpec("target", "agent", [], required=True),
        ParameterSpec("message", "text", [], required=True),
    ],
    effects=[],
    requires=None,
    handler=None,  # Will be set after handlers module is loaded
)

ESTIMATE_ACTION = ActionDefinition(
    name="estimate",
    description="Provide a numerical estimate",
    parameters=[
        ParameterSpec("value", "number", [], required=True),
    ],
    effects=[],
    requires=None,
    handler=None,
)

VOTE_ACTION = ActionDefinition(
    name="vote",
    description="Vote for an option",
    parameters=[
        ParameterSpec("choice", "enum", [], required=True),
    ],
    effects=[],
    requires=["voting"],
    handler=None,
)


# === Council Action Definitions ===

COUNCIL_SPEAK_ACTION = ActionDefinition(
    name="speak",
    description="Share your thoughts with the council",
    parameters=[
        ParameterSpec("message", "text", [], required=True),
    ],
    effects=[
        EffectSpec("all", "broadcast", None),
    ],
    requires=None,
    handler=None,  # Will be bound in _bind_handlers
)

COUNCIL_SKIP_ACTION = ActionDefinition(
    name="skip",
    description="Pass your turn without speaking",
    parameters=[],
    effects=[],
    requires=None,
    handler=None,  # Simple action, no handler needed
)

START_VOTING_ACTION = ActionDefinition(
    name="start_voting",
    description="Initiate voting on the proposal",
    parameters=[
        ParameterSpec("title", "text", [], required=False),
    ],
    effects=[
        EffectSpec("voting_started", "state_change", None),
    ],
    requires=None,
    handler=None,  # Will be bound in _bind_handlers
)

COUNCIL_VOTE_ACTION = ActionDefinition(
    name="council_vote",
    description="Cast your vote (yes/no/abstain)",
    parameters=[
        ParameterSpec("choice", "enum", ["yes", "no", "abstain"], required=True),
    ],
    effects=[
        EffectSpec("votes", "state_change", None),
    ],
    requires=["voting_started"],
    handler=None,  # Will be bound in _bind_handlers
)

CONCLUDE_ACTION = ActionDefinition(
    name="conclude",
    description="End the meeting after voting",
    parameters=[],
    effects=[
        EffectSpec("concluded", "state_change", None),
    ],
    requires=["voting_started"],
    handler=None,  # Will be bound in _bind_handlers
)

VOTE_YES_ACTION = ActionDefinition(
    name="vote_yes",
    description="Vote in favor of the proposal",
    parameters=[],
    effects=[
        EffectSpec("votes", "state_change", None),
    ],
    requires=["voting_started"],
    handler=None,  # Will be bound in _bind_handlers
)

VOTE_NO_ACTION = ActionDefinition(
    name="vote_no",
    description="Vote against the proposal",
    parameters=[],
    effects=[
        EffectSpec("votes", "state_change", None),
    ],
    requires=["voting_started"],
    handler=None,  # Will be bound in _bind_handlers
)

ABSTAIN_ACTION = ActionDefinition(
    name="abstain",
    description="Abstain from voting (neither yes nor no)",
    parameters=[],
    effects=[
        EffectSpec("votes", "state_change", None),
    ],
    requires=["voting_started"],
    handler=None,  # Will be bound in _bind_handlers
)


# === PGG Actions ===
# "allocate" and "keep" are record-only: token deduction and pool
# contributions are handled by the payoff engine, not action effects.

ALLOCATE_ACTION = ActionDefinition(
    name="allocate",
    description="Allocate resources to the group account",
    parameters=[],
    effects=[],
    requires=None,
    handler=None,
    record_only=True,
)
KEEP_ACTION = ActionDefinition(
    name="keep",
    description="Keep all your resources this round",
    parameters=[],
    effects=[],
    requires=None,
    handler=None,
    record_only=True,
)

REDUCE_ACTION = ActionDefinition(
    name="reduce",
    description="Spend deduction tokens to reduce another agent's payoff",
    parameters=[
        ParameterSpec("target", "agent", [], required=True),
        ParameterSpec("amount", "number", [], required=True),
    ],
    effects=[
        EffectSpec("agent.resources.deduction_budget", "subtract", "amount"),
    ],
    requires=["resources"],
    handler=None,  # Will be bound in _bind_handlers
)


# === Sociology Record-Only Actions ===
# These actions are valid for logging/observation but do not mutate state.
# They have no handler and no effects — they record agent choices only.

def _make_record_only(name: str, description: str) -> ActionDefinition:
    """Create a record-only action definition."""
    return ActionDefinition(
        name=name,
        description=description,
        parameters=[],
        effects=[],
        requires=None,
        handler=None,
        record_only=True,
    )

EXPRESS_OPINION_ACTION = _make_record_only("express_opinion", "Share your current viewpoint on the topic")
SHARE_CONTENT_ACTION = _make_record_only("share_content", "Share information reinforcing your position")
DISENGAGE_ACTION = _make_record_only("disengage", "Withdraw from engagement with opposing views")
REINFORCE_INGROUP_ACTION = _make_record_only("reinforce_ingroup", "Engage with and amplify similar viewpoints")
CHALLENGE_OUTGROUP_ACTION = _make_record_only("challenge_outgroup", "Actively argue against opposing views")
SEEK_COMMON_GROUND_ACTION = _make_record_only("seek_common_ground", "Find shared values across opinion divides")
COMPLY_PUBLICLY_ACTION = _make_record_only("comply_publicly", "Visibly accept and follow the norm or directive")
COMPLY_COVERTLY_RESIST_ACTION = _make_record_only("comply_covertly_resist", "Formally comply but privately circumvent or ignore")
RESIST_OPENLY_ACTION = _make_record_only("resist_openly", "Openly refuse or challenge the norm or directive")
PERSUADE_OTHERS_ACTION = _make_record_only("persuade_others", "Convince others to adopt your position or action")
FORM_COALITION_ACTION = _make_record_only("form_coalition", "Organize with like-minded others for collective action")
TRANSMIT_FAITHFULLY_ACTION = _make_record_only("transmit_faithfully", "Pass the policy on exactly as received without changes")
REINTERPRET_DOWNWARD_ACTION = _make_record_only("reinterpret_downward", "Adapt or modify the policy when passing it down the chain")
COMPLY_DIRECTIVE_ACTION = _make_record_only("comply_directive", "Accept and implement the instruction from above")
RESIST_QUIETLY_ACTION = _make_record_only("resist_quietly", "Formally comply but avoid real implementation")
REPORT_UP_ACTION = _make_record_only("report_up", "Escalate an obstacle or issue to a higher authority")
CREATE_WORKAROUND_ACTION = _make_record_only("create_workaround", "Build an informal path around the official rule")
SHARE_RESOURCES_ACTION = _make_record_only("share_resources", "Give some of your resources to another agent")
HOARD_ACTION = _make_record_only("hoard", "Keep all resources for yourself")
PROPOSE_TRADE_ACTION = _make_record_only("propose_trade", "Offer to exchange resources")
FORM_CONTRACT_ACTION = _make_record_only("form_contract", "Propose a formal cooperative agreement")
HONOR_CONTRACT_ACTION = _make_record_only("honor_contract", "Fulfill an existing agreement")
DEFECT_FROM_CONTRACT_ACTION = _make_record_only("defect_from_contract", "Break an agreement for personal gain")
SEND_MESSAGE_ACTION = _make_record_only("send_message", "Send a message to the group")
YIELD_ACTION = _make_record_only("yield", "Pass or pause without sending a message")
REPORT_UPWARD_ACTION = _make_record_only("report_upward", "Report execution difficulty to a direct superior")
ESCALATE_COMPLAINT_ACTION = _make_record_only("escalate_complaint", "Escalate a complaint to a higher-level superior")
CONSULT_PEER_ACTION = _make_record_only("consult_peer", "Privately consult a connected peer on the same tier")
NOTIFY_SUBORDINATE_ACTION = _make_record_only("notify_subordinate", "Privately notify a directly connected subordinate")
ANNOUNCE_POLICY_ADJUSTMENT_ACTION = _make_record_only("announce_policy_adjustment", "Issue a policy adjustment announcement")


# === Grid World Record-Only Actions ===
# look_around: observation, no state mutation. Honest record-only.
# rest: explicit no-op. Honest record-only.

LOOK_AROUND_ACTION = _make_record_only("look_around", "Observe your surroundings")
REST_ACTION = _make_record_only("rest", "Do nothing this turn")


# The registry dictionary
ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "choose": CHOOSE_ACTION,
    "move": MOVE_ACTION,
    "contribute": CONTRIBUTE_ACTION,
    "talk": TALK_ACTION,
    "estimate": ESTIMATE_ACTION,
    "vote": VOTE_ACTION,
    # Council actions - minimal set for controlled experiments
    "speak": COUNCIL_SPEAK_ACTION,
    "skip": COUNCIL_SKIP_ACTION,
    "start_voting": START_VOTING_ACTION,  # Keep for backward compatibility
    "council_vote": COUNCIL_VOTE_ACTION,  # Keep for backward compatibility
    "vote_yes": VOTE_YES_ACTION,  # NEW - explicit vote action
    "vote_no": VOTE_NO_ACTION,    # NEW - explicit vote action
    "abstain": ABSTAIN_ACTION,    # NEW - explicit vote action
    "conclude": CONCLUDE_ACTION,  # Keep for backward compatibility
    # PGG actions
    "allocate": ALLOCATE_ACTION,
    "keep": KEEP_ACTION,
    "reduce": REDUCE_ACTION,
    # Sociology record-only actions
    "express_opinion": EXPRESS_OPINION_ACTION,
    "share_content": SHARE_CONTENT_ACTION,
    "disengage": DISENGAGE_ACTION,
    "reinforce_ingroup": REINFORCE_INGROUP_ACTION,
    "challenge_outgroup": CHALLENGE_OUTGROUP_ACTION,
    "seek_common_ground": SEEK_COMMON_GROUND_ACTION,
    "comply_publicly": COMPLY_PUBLICLY_ACTION,
    "comply_covertly_resist": COMPLY_COVERTLY_RESIST_ACTION,
    "resist_openly": RESIST_OPENLY_ACTION,
    "persuade_others": PERSUADE_OTHERS_ACTION,
    "form_coalition": FORM_COALITION_ACTION,
    "transmit_faithfully": TRANSMIT_FAITHFULLY_ACTION,
    "reinterpret_downward": REINTERPRET_DOWNWARD_ACTION,
    "comply_directive": COMPLY_DIRECTIVE_ACTION,
    "resist_quietly": RESIST_QUIETLY_ACTION,
    "report_up": REPORT_UP_ACTION,
    "create_workaround": CREATE_WORKAROUND_ACTION,
    "share_resources": SHARE_RESOURCES_ACTION,
    "hoard": HOARD_ACTION,
    "propose_trade": PROPOSE_TRADE_ACTION,
    "form_contract": FORM_CONTRACT_ACTION,
    "honor_contract": HONOR_CONTRACT_ACTION,
    "defect_from_contract": DEFECT_FROM_CONTRACT_ACTION,
    "send_message": SEND_MESSAGE_ACTION,
    "yield": YIELD_ACTION,
    "report_upward": REPORT_UPWARD_ACTION,
    "escalate_complaint": ESCALATE_COMPLAINT_ACTION,
    "consult_peer": CONSULT_PEER_ACTION,
    "notify_subordinate": NOTIFY_SUBORDINATE_ACTION,
    "announce_policy_adjustment": ANNOUNCE_POLICY_ADJUSTMENT_ACTION,
    # Grid World record-only actions
    "look_around": LOOK_AROUND_ACTION,
    "rest": REST_ACTION,
}


def get_action(name: str) -> ActionDefinition | None:
    """Get action definition by name.

    Args:
        name: Action name

    Returns:
        ActionDefinition or None if not found
    """
    return ACTION_REGISTRY.get(name)


def register_action(action: ActionDefinition) -> None:
    """Register a new action or override existing.

    Args:
        action: ActionDefinition to register
    """
    ACTION_REGISTRY[action.name] = action


# Late binding of handlers to avoid circular imports
def _bind_handlers():
    """Bind handler functions to actions after module load."""
    from fos.core.experiment.actions.handlers import (
        handle_move,
        handle_talk,
        handle_council_speak,
        handle_start_voting,
        handle_vote,
        handle_vote_yes,
        handle_vote_no,
        handle_abstain,
        handle_conclude,
        handle_reduce,
    )
    ACTION_REGISTRY["move"].handler = handle_move
    ACTION_REGISTRY["talk"].handler = handle_talk
    # Council action handlers
    ACTION_REGISTRY["speak"].handler = handle_council_speak
    ACTION_REGISTRY["start_voting"].handler = handle_start_voting
    ACTION_REGISTRY["council_vote"].handler = handle_vote
    ACTION_REGISTRY["vote_yes"].handler = handle_vote_yes
    ACTION_REGISTRY["vote_no"].handler = handle_vote_no
    ACTION_REGISTRY["abstain"].handler = handle_abstain
    ACTION_REGISTRY["conclude"].handler = handle_conclude
    # PGG reduction action handler
    ACTION_REGISTRY["reduce"].handler = handle_reduce


# Bind handlers on first import
_bind_handlers()
