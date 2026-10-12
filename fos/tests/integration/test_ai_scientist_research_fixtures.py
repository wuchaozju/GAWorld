from __future__ import annotations

import json
from pathlib import Path

import pytest

from fos.backend.services.ai_scientist import build_semantic_schema, heuristic_analysis, suggest_templates


FIXTURE_MANIFEST = Path(__file__).resolve().parents[1] / "fixtures" / "research_papers" / "fixture_manifest.json"
FIXTURES = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
SCENARIO_FIXTURES = [
    {
        "id": "public_goods",
        "name": "Public Goods Game",
        "category": "game_theory",
        "description": "Participants choose how much to contribute to a shared pool or keep privately.",
        "actions": [{"name": "contribute"}, {"name": "keep"}],
    },
    {
        "id": "prisoners_dilemma",
        "name": "Prisoner's Dilemma",
        "category": "game_theory",
        "description": "Participants choose whether to cooperate or defect in repeated pairwise interaction.",
        "actions": [{"name": "cooperate"}, {"name": "defect"}],
    },
    {
        "id": "coordination_game",
        "name": "Coordination Game",
        "category": "game_theory",
        "description": "Participants repeatedly choose from a shared menu and benefit when their choices match.",
        "actions": [{"name": "option_a"}, {"name": "option_b"}],
    },
    {
        "id": "contagion",
        "name": "Contagion Spread",
        "category": "spatial",
        "description": "Behavior or infection spreads across local network ties through repeated exposure.",
        "actions": [{"name": "move"}, {"name": "speak"}],
    },
]


@pytest.mark.parametrize(
    ("fixture_id", "expected_scenario_id"),
    [(item["id"], item["expected_scenario_id"]) for item in FIXTURES],
)
def test_research_fixtures_map_to_expected_scenarios(
    fixture_id: str,
    expected_scenario_id: str,
) -> None:
    fixture = next(item for item in FIXTURES if item["id"] == fixture_id)
    schema = build_semantic_schema(fixture["text"], language="en")
    suggestions = suggest_templates(
        fixture["text"],
        SCENARIO_FIXTURES,
        top_k=3,
        source_sections=schema.get("source_sections"),
        semantic_schema=schema,
        language="en",
    )
    result = heuristic_analysis(fixture["text"], suggestions, language="en", source_sections=schema.get("source_sections"))

    assert result["recommended_scenario_id"] == expected_scenario_id
    assert result["scenario_description"]
    assert result["actions"]
    assert result["source_sections"]
