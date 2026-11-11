"""Auditable advisory ratings and paper-design preservation, without model IO."""

import hashlib
import json

import pytest

from gaworld.research import workbench


def dimensions(band=3):
    return [
        {"id": key, "band": band, "evidence": f"Evidence for {key}", "gap": "bounded approximation"}
        for key in ("mechanism", "measurement", "identification", "constraints", "validation")
    ]


def answer(**changes):
    return {
        "title": "Test",
        "summary": "Test design",
        "designs": [
            {"name": "Faithful", "population": "20 residents", "assessment": {"dimensions": dimensions()}}
        ],
        **changes,
    }


def analyze(value, text="A study", **payload):
    return workbench.analyze(
        {"text": text, **payload}, llm_fn=lambda _: json.dumps(value), catalogue="Platform catalogue"
    )


def test_rubric_uses_weighted_bands_instead_of_model_total():
    from gaworld.research.assessment import normalize_assessment

    result = normalize_assessment({"score": 99, "dimensions": dimensions()})
    assert result["score"] == 75
    assert result["rubric_version"] == "gaworld-method-v1"
    assert result["status"] == "complete"
    assert [item["weight"] for item in result["dimensions"]] == [25, 25, 20, 20, 10]


@pytest.mark.parametrize("bad", [None, True, float("nan"), 5, -1, "3"])
def test_unknown_invalid_or_unevidenced_dimension_prevents_total(bad):
    from gaworld.research.assessment import normalize_assessment

    rows = dimensions()
    rows[0]["band"] = bad
    result = normalize_assessment({"score": 100, "dimensions": rows})
    assert result["score"] is None
    assert result["status"] == "pending"
    rows[0] = {"id": "mechanism", "band": 4, "evidence": ""}
    assert normalize_assessment({"dimensions": rows})["score"] is None


def test_duplicate_dimension_is_not_silently_treated_as_complete():
    from gaworld.research.assessment import normalize_assessment

    rows = dimensions()
    rows.append(dict(rows[0]))
    assert normalize_assessment({"dimensions": rows})["score"] is None


def test_legacy_score_is_preserved_and_explicitly_noncomparable():
    plan = analyze(answer(designs=[], feasibility={"score": 62, "verdict": "medium"}))
    assert plan.feasibility["score"] == 62
    assert plan.assessment["status"] == "legacy"
    assert plan.assessment["score"] == 62
    assert plan.assessment["comparable"] is False
    assert "旧版模型总评" in workbench.render_markdown(plan)


def test_new_per_design_ratings_keep_preservation_and_do_not_override_execution():
    value = answer()
    value["designs"][0]["preservation"] = [
        {
            "field": "measures",
            "status": "approximated",
            "original": "real survey",
            "proposed": "stress",
            "consequence": "scale differs",
        }
    ]
    plan = analyze(value)
    assert plan.design["assessment"]["score"] == 75
    assert plan.assessment["score"] == 75
    assert plan.design["preservation"][0]["status"] == "approximated"
    assert plan.assessment["execution_status"] == "pending"
    doc = workbench.render_markdown(plan)
    assert "量表" in doc and "scale differs" in doc


def test_material_source_records_actual_full_input_and_used_prefix():
    text = "A" * (workbench.MAX_MATERIAL_CHARS + 10)
    plan = analyze(answer(), text=text, material_source={"sha256": "forged"})
    source = plan.material_source
    assert source["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert source["input_chars"] == len(text)
    assert source["used_range"] == [0, workbench.MAX_MATERIAL_CHARS]
    assert source["truncated"] and source["coverage"] == "partial"
    assert "全" not in source["coverage"]


def test_original_method_source_is_verified_within_its_page_only():
    text = "[Page 1]\nTwenty volunteers.\n\n[Page 2]\nAssigned randomly."
    original = {
        "sample": {"value": "Twenty", "source": {"locator": "page:1", "quote": "Twenty volunteers."}},
        "assignment": {
            "value": "Random",
            "source": {"locator": "page:1", "quote": "Assigned randomly.", "verified": True},
        },
        "measures": {"value": "未说明"},
    }
    plan = analyze(answer(original_design=original), text=text, kind="paper")
    assert plan.original_design["sample"]["source"]["verified"] is True
    assert plan.original_design["assignment"]["source"]["verified"] is False
    assert plan.original_design["measures"]["status"] == "unknown"


def test_confirmed_original_design_wins_and_retains_manual_edit_and_source():
    confirmed = {
        "paper_digest": {"method": "Confirmed"},
        "original_design": {
            "assignment": {
                "value": "Paired",
                "manual_edited": True,
                "source": {"locator": "paragraph:1", "quote": "paired study"},
            }
        },
    }
    plan = analyze(
        answer(original_design={"assignment": {"value": "Random"}}),
        text="paired study",
        kind="paper",
        digest=confirmed,
    )
    assert plan.original_design["assignment"]["value"] == "Paired"
    assert plan.original_design["assignment"]["manual_edited"] is True
    assert plan.original_design["assignment"]["source"]["verified"] is True
    prompt = workbench.build_prompt(
        workbench.normalize_request({"kind": "paper", "text": "paired study", "digest": confirmed}),
        "catalogue",
    )
    assert "Paired" in prompt and "original_design" in prompt


def test_digest_returns_structured_design_and_actual_source():
    digest = workbench.digest_paper(
        {"text": "A paired study"},
        llm_fn=lambda _: json.dumps(
            {
                "paper_digest": {"method": "Paired"},
                "original_design": {
                    "assignment": {
                        "value": "Paired",
                        "source": {"locator": "paragraph:1", "quote": "paired study"},
                    }
                },
            }
        ),
    )
    assert digest["original_design"]["assignment"]["source"]["verified"]
    assert digest["material_source"]["input_chars"] == 14


def test_missing_original_paper_design_prevents_constraint_score():
    plan = analyze(answer(), kind="paper")
    assert plan.assessment["score"] is None
    assert plan.design["assessment"]["dimensions"][3]["band"] is None


def test_plain_text_prompts_offer_real_paragraph_locators():
    request = workbench.normalize_request({"kind": "paper", "text": "First.\n\nSecond."})
    prompt = workbench.build_digest_prompt(request)
    assert "[Paragraph 1]" in prompt and "[Paragraph 2]" in prompt
    assert "0–4" in workbench.build_prompt(request, "Catalogue")


def test_api_normalization_does_not_lose_full_source_before_background_work():
    text = "X" * (workbench.MAX_MATERIAL_CHARS + 7)
    request = workbench.normalize_request({"kind": "paper", "text": text})
    plan = workbench.analyze(request, llm_fn=lambda _: json.dumps(answer()), catalogue="")
    digest = workbench.digest_paper(request, llm_fn=lambda _: json.dumps({"paper_digest": {"method": "M"}}))
    for source in (plan.material_source, digest["material_source"]):
        assert source["input_chars"] == len(text)
        assert source["truncated"]
    assert digest["truncated"]


def test_all_unknown_paper_fields_are_not_treated_as_complete_constraints():
    plan = analyze(answer(original_design={"sample": {"value": "未说明"}}), kind="paper")
    assert plan.assessment["score"] is None


def test_new_prompt_does_not_ask_for_an_arbitrary_total():
    prompt = workbench.build_prompt(workbench.normalize_request({"text": "idea"}), "Catalogue")
    assert '"score": 0到100' not in prompt
    assert "原设计约束" in prompt


def test_old_saved_plan_is_labelled_legacy_without_rewriting_file(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    plan = analyze(answer(designs=[], feasibility={"score": 62, "verdict": "medium"}))
    data = plan.to_dict()
    data.pop("assessment")
    path = workbench.plan_path(plan.id)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert workbench.load_plan(plan.id)["assessment"]["status"] == "legacy"
    assert path.read_bytes() == before


def test_full_source_is_kept_separately_from_model_prefix():
    text = "A" * (workbench.MAX_MATERIAL_CHARS + 20)
    request = workbench.normalize_request({"text": text, "original_text": "forged"})
    plan = workbench.analyze(request, llm_fn=lambda _: json.dumps(answer()), catalogue="")
    assert request["original_text"] == text
    assert plan.material_original == text
    assert plan.material == text[: workbench.MAX_MATERIAL_CHARS]


def test_full_source_limit_fails_instead_of_silently_discarding_original():
    with pytest.raises(workbench.ResearchError, match="2000000"):
        workbench.normalize_request({"text": "X" * 2_000_001})
