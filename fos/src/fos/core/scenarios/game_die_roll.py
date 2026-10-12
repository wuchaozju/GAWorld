"""
Scenario definition for the private die-roll honesty task (Abeler et al. 2019).

A single agent rolls a fair six-sided die in private and then reports a
number from 1 to 6. The agent's payment is proportional to the number it
reports, so reporting higher earns more; only the agent ever sees the true
roll, so the experimenter can never verify the report.

Contains: GAME_DIE_ROLL
"""

from typing import Any, Dict

from ...i18n import T

GAME_DIE_ROLL: Dict[str, Any] = {
    "id": "game_die_roll",
    "name": "Private Die-Roll Honesty Task",
    "category": "honesty",
    "description": T("scenario_templates.game_die_roll.description"),
    "grouping_mode": "individual",
    "payoff_type": "direct",
    "interaction_mode": "solo",
    "display_type": "description_only",
    "description_template": (
        "A private fair die roll determines your true outcome, but only you "
        "see it. Report any number from 1 to 6; your payment matches the "
        "number you report."
    ),
    "parameters": [],
    "actions": [
        {"id": "report_1", "name": "Report 1", "description": T("scenario_templates.game_die_roll.actions.report_1.description")},
        {"id": "report_2", "name": "Report 2", "description": T("scenario_templates.game_die_roll.actions.report_2.description")},
        {"id": "report_3", "name": "Report 3", "description": T("scenario_templates.game_die_roll.actions.report_3.description")},
        {"id": "report_4", "name": "Report 4", "description": T("scenario_templates.game_die_roll.actions.report_4.description")},
        {"id": "report_5", "name": "Report 5", "description": T("scenario_templates.game_die_roll.actions.report_5.description")},
        {"id": "report_6", "name": "Report 6", "description": T("scenario_templates.game_die_roll.actions.report_6.description")},
    ],
}
