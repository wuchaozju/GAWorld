"""Identity cue checks compare matched prompts without changing the main study."""

import copy

import pytest

from gaworld.research import replication as rp


def study(enabled=True):
    return {
        "items": [
            {
                "id": "Q1",
                "text": "给对象评分",
                "kind": "number",
                "min": 0,
                "max": 10,
                "equivalence_margin": 2,
                "identity_margin": 0.5,
            }
        ],
        "results": [{"item": "Q1", "mean": 5, "sd": 1, "n": 100}],
        "identity_probe": {
            "enabled": enabled,
            "template": "被评价对象的身份线索：{{identity}}。",
            "a": "甲身份",
            "b": "乙身份",
        },
    }


def run(spec, answer, **kwargs):
    return rp.run_replication(
        spec=spec,
        answer=answer,
        sample_size=12,
        seed=123,
        population=[{"id": i, "age": 30, "name": f"受访居民{i}"} for i in range(12)],
        profile_fn=lambda *_: "档案保持原样",
        workers=1,
        **kwargs,
    )


def identity_check(result):
    return next(
        c for c in result["comparison"]["cells"][0]["result_checks"]["checks"] if c["id"] == "identity"
    )


def data(n=40):
    return [
        {
            "agent_id": i,
            "condition": "C1",
            "ok": True,
            "answers": {"Q1": 5},
            "probes": {
                "identity_a": {"answers": {"Q1": 4}},
                "identity_b": {"answers": {"Q1": 4.2 + (i % 2) * 0.1}},
            },
        }
        for i in range(n)
    ]


def compare(spec, rows):
    return {"comparison": rp.compare(rp.normalize_spec(spec), rows, "between")}


def test_enabled_identity_settings_and_separate_margin_survive_normalization():
    s = rp.normalize_spec(study())
    assert s.get("identity_probe") == study()["identity_probe"]
    assert s["items"][0].get("identity_margin") == 0.5


@pytest.mark.parametrize(
    "change",
    [
        {"template": "没有占位符"},
        {"template": "{{identity}} {{identity}}"},
        {"a": ""},
        {"b": "甲身份"},
        {"a": ["甲身份"]},
        {"a": "a" * 101},
    ],
)
def test_invalid_enabled_settings_rejected_before_any_call(change):
    s = study()
    s["identity_probe"].update(change)
    calls = []
    with pytest.raises(ValueError, match="身份"):
        run(s, lambda prompt: calls.append(prompt) or '{"Q1":5}')
    assert not calls


def test_default_off_does_not_add_calls_or_evidence():
    calls = []
    result = run(study(False), lambda p: calls.append(p) or '{"Q1":5}')
    assert len(calls) == 12
    assert identity_check(result)["status"] == "untested"


def test_matched_variants_preserve_main_answers_and_counterbalance_order():
    calls = []

    def answer(prompt):
        calls.append(prompt)
        return '{"Q1": 2}' if "被评价对象的身份线索" in prompt else '{"Q1": 5}'

    result = run(study(), answer)
    assert len(calls) == 36
    assert all(r["answers"]["Q1"] == 5 for r in result["responses"])
    assert result["check_protocol"]["planned_calls"] == 36
    orders = [tuple(r["probe_order"]) for r in result["responses"]]
    assert orders.count(("identity_a", "identity_b")) == 6
    assert orders.count(("identity_b", "identity_a")) == 6
    again = run(study(), answer)
    assert orders == [tuple(r["probe_order"]) for r in again["responses"]]
    for i, response in enumerate(result["responses"]):
        prompts = calls[i * 3 + 1 : i * 3 + 3]
        assert prompts[0].replace("甲身份", "乙身份") == prompts[1].replace("甲身份", "乙身份")
        assert "档案保持原样" in prompts[0]
        assert all(p["prompt_hash"] for p in response["probes"].values())
    assert result["check_protocol"]["identity_probe"]["contrast"] == "B - A"
    assert "甲身份" in rp.export_markdown(result)


def test_identity_difference_uses_its_own_margin_and_original_units():
    s = study()
    c = identity_check(compare(s, data()))
    assert c["status"] == "stable"
    assert c["evidence"]["difference"] == pytest.approx(0.25)
    assert c["evidence"]["pairs"] == 40
    s["items"][0]["identity_margin"] = None
    c = identity_check(compare(s, data()))
    assert c["status"] == "detected"  # never inherit human equivalence_margin=2
    assert c["evidence"]["margin"] is None
    assert "不公正" in c["detail"]


def test_missing_identity_pairs_prevent_whole_sample_equivalence():
    rows = data()
    rows[0]["probes"]["identity_b"] = {"answers": {}, "error": "timeout"}
    c = identity_check(compare(study(), rows))
    assert c["status"] == "insufficient"
    assert c["evidence"]["missing_b"] == 1
    assert c["evidence"]["errors_b"] == 1
    assert c["evidence"]["pairs"] == 39


def test_duplicate_identity_pairs_cannot_create_inference():
    c = identity_check(compare(study(), data() * 3))
    assert c["status"] == "insufficient"
    assert "ci" not in c["evidence"]


def test_identity_pair_availability_is_not_conditioned_on_main_success():
    rows = data()
    for row in rows:
        row.update(ok=False, answers={}, error="main failed")
    assert identity_check(compare(study(), rows))["evidence"]["pairs"] == 40


def test_nominal_identity_changes_are_descriptive_for_every_option():
    s = study()
    s["items"] = [{"id": "Q1", "text": "选择", "kind": "choice", "options": ["左", "右"]}]
    s["results"] = [{"item": "Q1", "distribution": {"左": 0.5, "右": 0.5}}]
    rows = data()
    for row in rows:
        row["answers"]["Q1"] = 0
        row["probes"]["identity_a"]["answers"]["Q1"] = 0
        row["probes"]["identity_b"]["answers"]["Q1"] = 1
    c = identity_check(compare(s, rows))
    assert c["status"] == "observed"
    assert c["evidence"]["option_shifts"] == {"左": -1, "右": 1}
    assert c["evidence"]["switch_rate"] == 1


def test_identity_levels_do_not_imply_treatment_effect_or_interaction_checks():
    s = study()
    s["conditions"] = [{"id": "C1"}, {"id": "C2"}]
    s["results"][0]["condition"] = "C1"
    s["results"] += [{"item": "Q1", "condition": "C2", "mean": 6, "sd": 1, "n": 100}]
    rows = data()
    second = copy.deepcopy(rows)
    for row in second:
        row["condition"] = "C2"
    result = compare(s, rows + second)["comparison"]
    assert (
        next(c for c in result["effects"][0]["result_checks"]["checks"] if c["id"] == "identity")["status"]
        == "untested"
    )
    assert (
        next(c for c in result["cells"][0]["result_checks"]["checks"] if c["id"] == "interaction")["status"]
        == "untested"
    )


def test_authored_subgroup_identity_check_needs_no_subgroup_human_reference():
    s = study()
    s["groups"] = [{"id": "G1", "label": "青年", "age_min": 20, "age_max": 40}]
    residents = [{"agent_id": i, "age": 30 if i < 20 else 50} for i in range(40)]
    result = rp.compare(rp.normalize_spec(s), data(), "between", residents)
    assert len(result["group_cells"]) == 1
    group = result["group_cells"][0]
    assert group["human"] is None
    identity = next(c for c in group["result_checks"]["checks"] if c["id"] == "identity")
    assert identity["evidence"]["pairs"] == 20
    assert identity["evidence"]["family_size"] == 2
    assert result["summary"]["group_cells_compared"] == 0
    assert result["summary"]["group_level_accuracy"] is None


def test_unreported_subgroup_does_not_replace_reported_human_gap_base():
    s = study()
    s["groups"] = [
        {"id": "G0", "age_min": 1, "age_max": 19},
        {"id": "G1", "age_min": 20, "age_max": 40},
        {"id": "G2", "age_min": 41, "age_max": 70},
    ]
    s["results"] += [
        {"item": "Q1", "group": g, "mean": h, "sd": 1, "n": 100} for g, h in [("G1", 4), ("G2", 6)]
    ]
    residents = [{"agent_id": i, "age": 30 if i < 20 else 50} for i in range(40)]
    enabled = rp.compare(rp.normalize_spec(s), data(), "between", residents)
    s["identity_probe"]["enabled"] = False
    disabled = rp.compare(rp.normalize_spec(s), data(), "between", residents)
    assert len(enabled["group_gaps"]) == len(disabled["group_gaps"]) == 1
    assert enabled["group_gaps"][0]["ref"] == disabled["group_gaps"][0]["ref"]
    assert enabled["summary"]["score"] == disabled["summary"]["score"]
