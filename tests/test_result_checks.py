"""Behavioral boundaries for result checks: no missing-data or equivalence shortcuts."""

import copy

from gaworld.research import replication as rp


def spec():
    return rp.normalize_spec(
        {
            "title": "checks",
            "human_design": "between",
            "items": [
                {
                    "id": "Q1",
                    "text": "评分",
                    "kind": "number",
                    "min": 0,
                    "max": 10,
                    "equivalence_margin": 0.5,
                    "audit_wording": "请给出评分",
                }
            ],
            "conditions": [{"id": "C1"}, {"id": "C2"}],
            "results": [
                {"item": "Q1", "condition": c, "mean": mean, "sd": 1, "n": 100}
                for c, mean in [("C1", 4), ("C2", 6)]
            ],
        }
    )


def responses(n=100):
    return [
        {"agent_id": i, "condition": c, "answers": {"Q1": mean + (i % 2 - 0.5)}, "ok": True}
        for c, mean in [("C1", 4), ("C2", 6)]
        for i in range(n)
    ]


def test_spec_preserves_explicit_margin_and_human_design():
    s = spec()
    assert s["items"][0].get("equivalence_margin") == 0.5
    assert s.get("human_design") == "between"
    assert s["items"][0].get("audit_wording") == "请给出评分"


def test_human_effect_equivalence_requires_both_uncertainties():
    s = spec()
    comparison = rp.compare(s, responses(), "paired")
    check = comparison["effects"][0].get("result_checks", {})
    assert check.get("checks"), "attach checks to the specific effect"
    human = next(c for c in check["checks"] if c["id"] == "human")
    assert human["status"] == "stable"
    assert human["evidence"]["difference"] == 0
    s["results"][0]["sd"] = None
    human = next(
        c
        for c in rp.compare(s, responses(), "paired")["effects"][0]["result_checks"]["checks"]
        if c["id"] == "human"
    )
    assert human["status"] == "insufficient"


def test_paired_humans_without_covariance_do_not_get_equivalence():
    s = spec()
    s["human_design"] = "paired"
    result = rp.compare(s, responses(), "paired")["effects"][0]
    assert (
        next(c for c in result["result_checks"]["checks"] if c["id"] == "human")["status"] == "insufficient"
    )


def test_duplicate_and_partial_answers_are_visible():
    data = responses(8)
    data[0]["answers"]["Q1"] = None
    data.append(copy.deepcopy(data[1]))
    result = rp.compare(spec(), data, "paired")
    quality = result.get("response_quality", {})
    assert quality.get("duplicate_records") == 1
    assert quality["missing_answers"] == 1
    assert quality["records"] == 17
    assert (
        next(c for c in result["effects"][0]["result_checks"]["checks"] if c["id"] == "human")["status"]
        != "stable"
    )


def test_unchecked_dimensions_never_pass():
    result = rp.compare(spec(), responses(), "paired")
    checks = result["effects"][0].get("result_checks", {}).get("checks", [])
    assert checks
    assert next(c for c in checks if c["id"] == "interaction")["status"] == "untested"
    assert next(c for c in checks if c["id"] == "model")["status"] == "untested"


def test_order_probe_is_opt_in_and_maps_back_to_original_labels():
    s = rp.normalize_spec(
        {
            "items": [{"id": "Q1", "text": "选什么", "kind": "choice", "options": ["甲", "乙"]}],
            "results": [{"item": "Q1", "distribution": {"甲": 1}}],
        }
    )
    people = [{"id": i, "age": 30, "name": str(i)} for i in range(6)]
    calls = []

    def answer(prompt):
        calls.append(prompt)
        return '{"Q1": 1}' if "1. 甲" in prompt else '{"Q1": 2}'

    kwargs = {
        "spec": s,
        "population": people,
        "sample_size": 6,
        "profile_fn": lambda *_: "",
        "answer": answer,
        "workers": 1,
    }
    base = rp.run_replication(**kwargs)
    assert len(calls) == 6
    s["bias_checks"] = {"order": True}
    calls.clear()
    run = rp.run_replication(**kwargs)
    assert len(calls) == 12
    assert run["comparison"]["cells"][0]["agent"] == base["comparison"]["cells"][0]["agent"]
    assert all(r["probes"]["order"]["answers"]["Q1"] == 0 for r in run["responses"])
    assert run["check_protocol"]["planned_calls"] == 12


def test_all_failed_run_preserves_evidence_and_export():
    def broken(_):
        raise TimeoutError("offline")

    run = rp.run_replication(
        spec=spec(),
        answer=broken,
        sample_size=6,
        population=[{"id": i, "age": 30, "name": str(i)} for i in range(6)],
        profile_fn=lambda *_: "",
        workers=1,
    )
    assert run["failed"] == 6
    assert run["comparison"]["summary"]["score"] is None
    assert "偏向性与适用范围" in rp.export_markdown(run)
    assert "缺失" in rp.export_markdown(run)


def test_batch_cards_do_not_invent_cross_model_equivalence():
    from gaworld.research import batch_compare
    from tests.test_research_batch_compare import record

    comparison = batch_compare.compare(record())
    assert comparison.get("result_checks")
    check = comparison["contrasts"][0]["result_checks"]["checks"]
    model = next(c for c in check if c["id"] == "model")
    assert model["status"] != "stable"
    assert model["evidence"]["difference"] == 4
    assert "偏向性与适用范围" in batch_compare.markdown(record(), comparison)


def test_interval_checks_do_not_equate_non_significance_with_equivalence():
    from gaworld.research.result_checks import interval_check

    assert interval_check("human", 0, [(1, 5)], 0.1)["status"] == "insufficient"
    assert interval_check("human", 0, [(0.0001, 100)], 0.1)["status"] == "stable"
    assert interval_check("human", 2, [(0.001, 100)], 0.1)["status"] == "detected"
    assert interval_check("human", 0, [(0, 1)], 0.1)["status"] == "insufficient"
    assert interval_check("human", 0, [(0.0001, 100)])["status"] == "insufficient"


def test_hypothesis_cards_are_exported_even_without_measurements():
    from gaworld.research.evaluate import evaluate
    from gaworld.research.interpret import build_interpret_prompt
    from tests.test_research_study import make_protocol

    p = make_protocol()
    result = evaluate(p, [])
    assert result["hypotheses"][0].get("result_checks")
    assert "未检验" in build_interpret_prompt(p, result)


def test_duplicate_probe_records_cannot_produce_detection():
    s = spec()
    s["bias_checks"]["wording"] = True
    data = responses(2)
    for r in data:
        r["probes"] = {"wording": {"answers": {"Q1": r["answers"]["Q1"] + r["agent_id"]}}}
    result = rp.compare(s, data * 100, "paired")
    for row in result["cells"]:
        assert (
            next(c for c in row["result_checks"]["checks"] if c["id"] == "wording")["status"]
            == "insufficient"
        )


def test_malformed_optional_settings_do_not_crash_normalization():
    assert rp.normalize_spec({"bias_checks": True})["bias_checks"] == {"order": False, "wording": False}


def test_api_saves_failed_answers_before_optional_interpretation(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from gaworld.apps import replication_api as api

    run = {"id": "rep-evidence", "failed": 2, "responses": [{"ok": False}, {"ok": False}]}
    monkeypatch.setattr(rp, "run_replication", lambda **_: copy.deepcopy(run))
    saves = []
    monkeypatch.setattr(rp, "save_run", lambda r: saves.append(copy.deepcopy(r)))
    interpret = Mock(side_effect=TimeoutError("offline"))
    monkeypatch.setattr(api, "_interpret", interpret)
    monkeypatch.setattr(api._JOBS, "run", lambda worker: worker(lambda *_: None))
    api.start_run({"spec": spec()})
    assert saves and saves[0]["id"] == "rep-evidence"
    assert not interpret.called


def test_answer_workers_preserve_request_context_and_prompt_provenance():
    import contextvars

    request_owner = contextvars.ContextVar("replication_test_owner", default="lost")
    token = request_owner.set("owner/world")
    seen = []

    def answer(prompt):
        seen.append(request_owner.get())
        return '{"Q1": 4}'

    try:
        run = rp.run_replication(
            spec=spec(),
            answer=answer,
            sample_size=6,
            population=[{"id": i, "age": 30, "name": str(i)} for i in range(6)],
            profile_fn=lambda *_: "profile",
            workers=3,
        )
    finally:
        request_owner.reset(token)
    assert seen == ["owner/world"] * 6
    assert run["check_protocol"]["personas_hash"]
    assert all(r["prompt_hash"] for r in run["responses"])


def test_model_route_is_frozen_and_never_falls_back(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import pytest

    from gaworld.apps import replication_api as api
    from gaworld.llm import providers

    backend = SimpleNamespace(model="model-a", base_url="https://example.test/v1")
    config = {"llm": {"providers": {"a": {"model": "model-a", "api_key": "secret"}}}}
    router = SimpleNamespace(providers={"a": backend}, config=config)
    monkeypatch.setattr(providers, "LLM_ROUTER", router)
    resolve = Mock(return_value="a")
    monkeypatch.setattr(providers, "resolve_provider", resolve)
    call = Mock(return_value="ok")
    monkeypatch.setattr(providers, "call_llm", call)
    monkeypatch.setattr(api, "_LLM_OVERRIDE", None)
    answer = api._llm("", "answer", 0.9, 100)
    assert answer("first") == "ok"
    assert answer("second") == "ok"
    assert resolve.call_count == 1
    assert call.call_args.kwargs["provider"] == "a"
    assert call.call_args.kwargs["allow_fallback"] is False
    assert answer.provenance["model"] == "model-a"
    assert "secret" not in str(answer.provenance)
    backend.model = "model-b"
    with pytest.raises(RuntimeError, match="模型配置"):
        answer("third")
    assert call.call_count == 2


def test_potentially_overlapping_human_groups_need_covariance():
    s = spec()
    s["items"][0]["equivalence_margin"] = 10
    s["groups"] = [{"id": "G1", "age_min": 20, "age_max": 60}, {"id": "G2", "age_min": 30, "age_max": 70}]
    s["results"] += [
        {"item": "Q1", "condition": "C1", "group": g, "mean": 4, "sd": 1, "n": 100} for g in ("G1", "G2")
    ]
    s = rp.normalize_spec(s)
    people = [{"agent_id": i, "age": 20 if i < 50 else 70} for i in range(100)]
    result = rp.compare(s, responses(), "paired", residents=people)
    human = next(c for c in result["group_gaps"][0]["result_checks"]["checks"] if c["id"] == "human")
    assert human["status"] == "insufficient"
    assert "协方差" in human["detail"]
