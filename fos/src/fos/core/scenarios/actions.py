"""
Action library definitions for FOS scenarios.

Provides categorized action sets that scenarios can reference.
Each category contains actions relevant to that domain.

Actions are stored as dictionaries with 'name' and 'description' keys.
These are returned to the frontend for display and selection.

Contains: CATEGORY_ACTION_LIBRARIES
"""

from fos.i18n import T

# Sociology action library - 22 actions for social dynamics scenarios
SOCIOLOGY_ACTIONS = [
    {'id': 'comply_publicly', 'name': 'Comply Publicly', 'description': T('Visibly accept and follow the norm or directive')},
    {'id': 'comply_covertly_resist', 'name': 'Comply Covertly Resist', 'description': T('Formally comply but privately circumvent or ignore')},
    {'id': 'resist_openly', 'name': 'Resist Openly', 'description': T('Openly refuse or challenge the norm or directive')},
    {'id': 'persuade_others', 'name': 'Persuade Others', 'description': T('Convince others to adopt your position or action')},
    {'id': 'form_coalition', 'name': 'Form Coalition', 'description': T('Organize with like-minded others for collective action')},
    {'id': 'transmit_faithfully', 'name': 'Transmit Faithfully', 'description': T('Pass the policy on exactly as received without changes')},
    {'id': 'reinterpret_downward', 'name': 'Reinterpret Downward', 'description': T('Adapt or modify the policy when passing it down the chain')},
    {'id': 'comply_directive', 'name': 'Comply with Directive', 'description': T('Accept and implement the instruction from above')},
    {'id': 'resist_quietly', 'name': 'Resist Quietly', 'description': T('Formally comply but avoid real implementation')},
    {'id': 'report_up', 'name': 'Report Up', 'description': T('Escalate an obstacle or issue to a higher authority')},
    {'id': 'create_workaround', 'name': 'Create Workaround', 'description': T('Build an informal path around the official rule')},
    {'id': 'express_opinion', 'name': 'Express Opinion', 'description': T('Share your current viewpoint on the topic')},
    {'id': 'reinforce_ingroup', 'name': 'Reinforce Ingroup', 'description': T('Engage with and amplify similar viewpoints')},
    {'id': 'challenge_outgroup', 'name': 'Challenge Outgroup', 'description': T('Actively argue against opposing views')},
    {'id': 'seek_common_ground', 'name': 'Seek Common Ground', 'description': T('Find shared values across opinion divides')},
    {'id': 'share_content', 'name': 'Share Content', 'description': T('Share information reinforcing your position')},
    {'id': 'disengage', 'name': 'Disengage', 'description': T('Withdraw from engagement with opposing views')},
    {'id': 'share_resources', 'name': 'Share Resources', 'description': T('Give some of your resources to another agent')},
    {'id': 'hoard', 'name': 'Hoard', 'description': T('Keep all resources for yourself')},
    {'id': 'propose_trade', 'name': 'Propose Trade', 'description': T('Offer to exchange resources')},
    {'id': 'form_contract', 'name': 'Form Contract', 'description': T('Propose a formal cooperative agreement')},
    {'id': 'honor_contract', 'name': 'Honor Contract', 'description': T('Fulfill an existing agreement')},
    {'id': 'defect_from_contract', 'name': 'Defect from Contract', 'description': T('Break an agreement for personal gain')},
]

# Action libraries organized by category
CATEGORY_ACTION_LIBRARIES = {
    'sociology': SOCIOLOGY_ACTIONS,
    # Future categories can be added here:
    # 'game_theory': GAME_THEORY_ACTIONS,
    # 'discussion': DISCUSSION_ACTIONS,
    # 'grid_world': GRID_WORLD_ACTIONS,
    # 'social_deduction': SOCIAL_DEDUCTION_ACTIONS,
}
