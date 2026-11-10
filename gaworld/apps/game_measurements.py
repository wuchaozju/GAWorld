"""Archive measurement guards shared with the standalone benchmark entrypoint."""

from __future__ import annotations

from typing import Any

from gaworld.apps.game_reactions import boolean_answer, scale_integer


def mechanism_versions(records: list[dict[str, Any]]) -> list[str]:
    return sorted({str(record["result"].get("mechanism_version") or "legacy") for record in records})


def disaster_measurements(records: list[dict[str, Any]]) -> tuple[int, int, dict[str, Any]]:
    """Use independent, explicit denominators, including in archive readers."""
    panics: list[int] = []
    helps: list[bool] = []
    eligible = 0
    for record in records:
        scores: list[int] = []
        answers: list[bool] = []
        for agent in record["result"].get("agents") or []:
            for reaction in agent.get("reactions") or []:
                # Legacy 'other' included failed defaults. New valid unknown
                # actions carry an explicit validity flag and usable fields.
                if reaction.get("action") == "其他" and "valid_action" not in reaction:
                    continue
                if reaction.get("parse_status") == "invalid":
                    continue
                score = scale_integer(reaction.get("panic"), 1, 5)
                answer = boolean_answer(reaction.get("help"))
                if score is not None:
                    scores.append(score)
                if answer is not None:
                    answers.append(answer)
        eligible += bool(scores and answers)
        panics.extend(scores)
        helps.extend(answers)
    return (
        eligible,
        min(len(panics), len(helps)),
        {
            "extreme_share": round(panics.count(5) / len(panics), 4) if panics else None,
            "help_rate": round(sum(helps) / len(helps), 4) if helps else None,
            "panic_n": len(panics),
            "help_n": len(helps),
        },
    )
