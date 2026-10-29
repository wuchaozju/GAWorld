"""Contract tests for the backend AI Scientist drafting surface.

These tests intentionally verify stable structural fields rather than every
localized sentence. They are the guardrail for module splitting: moving code is
allowed, changing deterministic behavior is not.
"""

from __future__ import annotations

from fos.backend.services.ai_scientist import (
    TemplateSuggestion,
    build_llm_analysis_scaffold,
    collect_analysis_quality_issues,
    heuristic_analysis,
    localize_analysis_output,
    normalize_llm_analysis_output,
    parse_llm_json,
    suggest_templates,
)
from fos.backend.services.ai_scientist import draft_analysis
from fos.backend.services.ai_scientist import json_repair
from fos.backend.services.ai_scientist import localization
from fos.backend.services.ai_scientist import semantic_schema
from fos.backend.services.ai_scientist import template_matching
from fos.core.scenarios import get_all_scenarios


SHARED_POOL_TEXT = (
    "Abstract\n"
    "Participants receive 20 tokens each round. They decide how many tokens to contribute "
    "to a shared public pool or keep in a private account. The public pool is multiplied "
    "by 1.6 and distributed equally among four group members. We measure contribution "
    "levels and free riding."
)


def test_ai_scientist_deterministic_snapshot_for_shared_pool_text() -> None:
    suggestions = suggest_templates(SHARED_POOL_TEXT, get_all_scenarios(), top_k=3)

    result = heuristic_analysis(SHARED_POOL_TEXT, suggestions, language="en")

    assert [(item.id, round(item.score, 3)) for item in suggestions] == [
        ("public_goods", 0.195),
        ("coordination_game", 0.058),
        ("contagion", 0.046),
    ]
    assert result["recommended_scenario_id"] == "custom"
    assert result["recommendation_confidence"] == 0.195
    assert result["review_required"] is True
    assert result["recommended_params"] == {
        "source_title": "Abstract",
        "participant_roles": ["participants"],
        "decision_action_labels": [
            "Contribute to target",
            "Keep private reserves",
            "Delegate choice",
        ],
        "interaction_topology_hint": "The public pool is multiplied by 1.6 and distributed equally among four group members.",
        "interaction_structure_hint": "shared_target_threshold",
    }
    assert [item["name"] for item in result["actions"]] == [
        "Contribute to target",
        "Keep private reserves",
        "Delegate choice",
    ]
    assert result["agents"] == [
        {
            "label": "participants",
            "description": "Participants deciding how much to contribute toward a shared target.",
            "count": 4,
        }
    ]
    assert sorted(result["evidence_by_field"]) == [
        "actions",
        "constraints",
        "decision_context",
        "information_structure",
        "interaction_structure",
        "interaction_topology",
        "key_variables",
        "outcomes",
        "participants",
        "payoff_rules",
        "research_goal",
        "setting",
    ]


def test_ai_scientist_scaffold_snapshot_for_shared_pool_text() -> None:
    scaffold = build_llm_analysis_scaffold(
        SHARED_POOL_TEXT,
        get_all_scenarios(),
        language="en",
        top_k=3,
    )

    assert sorted(scaffold) == [
        "cleaned_text",
        "evidence_by_field",
        "evidence_packet",
        "helper_hints",
        "recognition_text",
        "semantic_schema",
        "source_outline",
        "source_sections",
        "template_suggestions",
    ]
    assert [(item.id, round(item.score, 3)) for item in scaffold["template_suggestions"]] == [
        ("public_goods", 0.331),
        ("stag_hunt", 0.015),
        ("battle_of_the_sexes", 0.011),
    ]
    assert scaffold["semantic_schema"]["interaction_structure"] == {
        "type": "shared_target_threshold",
        "confidence": 2,
        "family": "threshold_public_good_collective_target",
        "display_label": "Threshold public good / collective target",
    }
    assert [section["title"] for section in scaffold["source_sections"][:2]] == ["Title", "Abstract"]
    assert scaffold["helper_hints"]["candidate_parameters"]["interaction_structure_hint"] == "shared_target_threshold"
    assert scaffold["helper_hints"]["candidate_parameters"]["tokens_per_round"] == 20
    assert scaffold["helper_hints"]["candidate_settings"][-1]["value"] == "public_goods"
    assert scaffold["evidence_packet"]["title"] == "Abstract"
    assert scaffold["evidence_packet"]["document_quality"] == {
        "section_count": 2,
        "title_detected": True,
        "contains_structured_outline": False,
        "structure_family": "threshold_public_good_collective_target",
    }


def test_ai_scientist_normalize_model_output_contract() -> None:
    suggestion = TemplateSuggestion(
        id="public_goods",
        name="Public Goods Game",
        category="game_theory",
        description="Shared pool contribution study.",
        score=0.65,
        reason="Matched public goods keywords.",
    )
    semantic_schema = {
        "key_variables": ["contribution"],
        "evidence_map": {
            "actions": ["participants decide whether to contribute or keep"],
            "participants": ["four participants received tokens"],
        },
    }

    result = normalize_llm_analysis_output(
        {
            "scenario_description": "A repeated public-pool contribution game.",
            "settings": [{"key": "tokens_per_round", "value": "20", "reason": "explicit"}],
            "actions": [{"name": "contribute", "description": "Put tokens in the shared pool."}],
            "agents": [{"label": "participants", "description": "Group members", "count": 4}],
            "recommended_scenario_id": "public_goods",
            "recommended_scenario_reason": "The document describes public pool contributions.",
            "recommendation_confidence": 0.84,
            "review_required": False,
            "recommended_params": {"tokens_per_round": 20},
        },
        semantic_schema=semantic_schema,
        source_sections=[
            {
                "id": "abstract",
                "title": "Abstract",
                "excerpt": "Participants contribute or keep tokens.",
                "page": 1,
            }
        ],
        template_suggestions=[suggestion],
    )

    assert result["scenario_description"] == "A repeated public-pool contribution game."
    assert result["recommended_scenario_id"] == "public_goods"
    assert result["recommendation_confidence"] == 0.84
    assert result["review_required"] is False
    assert result["recommended_params"] == {"tokens_per_round": 20}
    assert result["key_variables"] == ["contribution"]
    assert result["evidence_by_field"] == semantic_schema["evidence_map"]
    assert result["source_sections"][0]["title"] == "Abstract"


def test_ai_scientist_split_modules_keep_public_contract() -> None:
    assert json_repair.parse_llm_json is parse_llm_json
    assert template_matching.TemplateSuggestion is TemplateSuggestion
    assert template_matching.suggest_templates is suggest_templates
    assert semantic_schema.build_llm_analysis_scaffold is build_llm_analysis_scaffold
    assert draft_analysis.heuristic_analysis is heuristic_analysis
    assert draft_analysis.normalize_llm_analysis_output is normalize_llm_analysis_output
    assert draft_analysis.collect_analysis_quality_issues is collect_analysis_quality_issues
    assert localization.localize_analysis_output is localize_analysis_output
