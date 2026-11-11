"""Reader summaries use recorded evidence, including its limits."""

from gaworld.research import reading


def test_plan_summary_explains_selected_comparison_without_inventing_cost():
    plan = {
        "research_questions": ["Does support reduce stress?"],
        "designs": [
            {
                "name": "Core",
                "population": "20 residents",
                "timeline": "5 days",
                "conditions": [
                    {"name": "Control", "manipulation": "none"},
                    {"name": "Support", "manipulation": "grant"},
                ],
                "measures": [{"name": "Stress", "operationalization": "mean state"}],
            },
            {"name": "Extension", "population": "40 residents", "timeline": "10 days"},
        ],
        "recommended_design": 0,
    }
    brief = reading.plan_summary(plan)
    assert "20 residents" in str(brief)
    assert "Control" in str(brief) and "Support" in str(brief)
    assert "40 residents" in str(reading.plan_summary(plan, 1))
    assert "未提供" in str(brief)


def test_results_explain_verdict_and_direction_only_limit():
    study = {
        "protocol": {"hypotheses": [{"id": "H1", "statement": "Support lowers stress"}]},
        "evaluation": {
            "hypotheses": [
                {
                    "id": "H1",
                    "statement": "Support lowers stress",
                    "verdict": "inconclusive",
                    "direction_only": True,
                    "mean_effect": -0.2,
                    "reasons": ["只有一个种子"],
                }
            ],
            "quality": {"issues": []},
        },
    }
    brief = reading.study_summary(study)
    assert brief["findings"][0]["verdict"] == "inconclusive"
    assert "只有一个种子" in brief["findings"][0]["evidence"]
    assert "大小" in brief["findings"][0]["limit"]
    assert "真实" in brief["notice"]


def test_missing_results_are_not_described_as_a_null_effect():
    for stage in ["protocol", "running", "error"]:
        brief = reading.study_summary({"stage": stage, "error": "interrupted"})
        assert brief["findings"] == []
        assert "无效" not in brief["lead"]
        assert brief["next"]


def test_english_summary_and_markdown_share_reading_order():
    brief = reading.study_summary(
        {
            "language": "en",
            "stage": "evaluated",
            "evaluation": {
                "hypotheses": [{"id": "H1", "verdict": "supported", "reasons": ["paired evidence"]}]
            },
        }
    )
    markdown = reading.markdown(brief)
    assert markdown.startswith("## At a glance")
    assert "Supported in this simulation" in markdown
    assert "paired evidence" in markdown
    assert "real people" in markdown
