import importlib.util
import json

import pytest


def modules():
    assert importlib.util.find_spec("gaworld.research.organization_intelligence.comparison"), (
        "comparison package missing"
    )
    from gaworld.research.organization_intelligence.comparison import analysis, benchmarks

    return benchmarks, analysis


def test_import_csv_mapping_and_no_hidden_answers_in_public_task():
    b, _ = modules()
    data = b.import_data(
        "id,kind,question,answer\nq1,reasoning,Choose A,A\n",
        "csv",
        {"category": "kind", "prompt": "question", "reference": "answer"},
    )
    assert len(data["tasks"]) == 1
    assert "reference" not in b.public_task(data["tasks"][0], 3)
    assert data["tasks"][0]["reference"] == "A"
    assert b.score(data["tasks"][0], {"answer": "A"})["score"] == 1


def test_import_rejects_duplicates_missing_and_code():
    b, _ = modules()
    q = {"id": "q", "category": "x", "prompt": "p", "reference": "A"}
    with pytest.raises(ValueError, match="重复"):
        b.import_data("\n".join([json.dumps(q)] * 2), "jsonl")
    with pytest.raises(ValueError):
        b.import_data('{"id":"q","prompt":"p","script":"danger"}', "jsonl")


def test_builtins_are_seeded_and_objectively_scorable():
    b, _ = modules()
    for kind in ("information", "allocation"):
        bank = b.builtin(kind, count=6, slots=3, seed=22)
        assert bank == b.builtin(kind, count=6, slots=3, seed=22)
        for q in bank["tasks"]:
            assert b.score(q, {"answer": q["reference"]})["score"] == 1
            public = b.public_task(q, 3)
            assert len(public["observations"]) == 3
            assert "reference" not in public


def test_invalid_constraint_solution_gets_predeclared_failure_score():
    b, _ = modules()
    q = b.builtin("allocation", count=1)["tasks"][0]
    assert b.score(q, {"answer": [99]})["score"] == 0


def paired(count=30, repeats=1):
    return [
        {"task_id": f"q{i}", "repeat": r, "arm": arm, "score": value, "valid": True, "metrics": {"calls": 3}}
        for i in range(count)
        for r in range(repeats)
        for arm, value in [("candidate", 1), ("baseline", 0)]
    ]


def test_analysis_clustered_by_task_and_rejects_incomplete_duplicate():
    _, a = modules()
    rows = paired(repeats=3)
    result = a.analyze(rows, expected=180)
    assert result["verdict"] == "better"
    assert result["independent_tasks"] == 30
    assert result["difference"] == 1
    assert a.analyze(rows[:-1], expected=180)["verdict"] == "incomplete"
    assert a.analyze([*rows, rows[0]], expected=181)["verdict"] == "incomplete"


def test_small_samples_and_uncertainty_do_not_claim_equivalence():
    _, a = modules()
    assert a.analyze(paired(2), expected=4)["verdict"] == "uncertain"
    rows = paired()
    for row in rows:
        row["score"] = 0.5
    result = a.analyze(rows, expected=60)
    assert result["verdict"] == "uncertain"
    assert "相同" not in result["conclusion"]


def test_negative_and_practical_threshold():
    _, a = modules()
    rows = paired()
    for row in rows:
        row["score"] = 1 - row["score"]
    assert a.analyze(rows, expected=60)["verdict"] == "worse"
    assert a.analyze(paired(), expected=60, delta=1)["verdict"] == "uncertain"


def test_frozen_run_resumes_without_duplicate_calls_and_keeps_raw_evidence(tmp_path):
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    bank = modules()[0].builtin(count=2)
    spec = protocol.freeze(
        {"candidate": baseline("full", 3), "benchmark": bank, "repeats": 1},
        [{"id": i} for i in range(3)],
        {"name": "test", "model": "test"},
    )
    db = store.Store(tmp_path)
    record = db.create(
        "C",
        {
            "status": "draft",
            "protocol": spec,
            "protocol_hash": protocol.digest(spec),
            "rows": [],
            "states": {},
            "control": "",
            "analysis": {},
        },
    )
    count = []

    def llm(prompt, **kwargs):
        count.append(prompt)
        return '{"answer":"A"}'

    runner.run(db, record["id"], llm)
    final = db.audit(record["id"])
    assert final["status"] == "completed"
    assert len(final["rows"]) == 4
    attempts = sum(len(s["attempts"]) for s in final["states"].values())
    assert attempts == len(count)
    runner.run(db, record["id"], llm)
    assert len(count) == attempts
    assert final["analysis"]["complete"]
    assert all("reference" not in prompt for prompt in count)


def test_method_material_quotes_are_verified():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import material

    method = baseline("full", 3)
    method["rules"] = [{"text": "invented", "origin": "source", "quote": "absent"}]
    result = material.extract("Members share reports.", "paper", lambda prompt: json.dumps(method))
    assert result["rules"][0]["origin"] == "inferred"
    assert result["source"]["text"] == "Members share reports."


def test_malformed_material_never_falls_back_to_a_generic_organization():
    modules()
    from gaworld.research.organization_intelligence.comparison import material

    with pytest.raises(ValueError, match="规则"):
        material.extract("Members share reports.", "paper", lambda prompt: "not JSON")


def test_review_mechanism_changes_compare_whole_method():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    candidate = {**baseline("full", 3), "review": True, "revisions": 1}
    p = protocol.freeze({"candidate": candidate, "count": 1}, [{"id": i} for i in range(3)], {"model": "x"})
    assert p["scope"] == "whole_method"
    assert not p["baseline"]["review"]


def test_import_cannot_forge_allocation_optimum_or_choice_reference():
    b, _ = modules()
    q = b.builtin("allocation", count=1)["tasks"][0]
    q["constraints"]["optimum"] = 0.01
    with pytest.raises(ValueError):
        b.validate([q], scorer="allocation")
    q = {"id": "q", "category": "x", "prompt": "p", "options": ["A", "B"], "reference": "Z"}
    with pytest.raises(ValueError):
        b.validate([q], scorer="choice")


def test_model_judging_has_separate_audit_and_total_budget(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    bank = b.validate(
        [{"id": "q", "category": "open", "prompt": "write", "rubric": "score quality 0-1"}], scorer="rubric"
    )
    spec = protocol.freeze(
        {
            "candidate": baseline("independent", 2),
            "baseline": "independent",
            "benchmark": bank,
            "repeats": 1,
            "limits": {"calls": 3},
        },
        [{"id": 1}, {"id": 2}],
        {"model": "x"},
    )
    db = store.Store(tmp_path)
    r = db.create(
        "C",
        {
            "status": "draft",
            "protocol": spec,
            "protocol_hash": protocol.digest(spec),
            "rows": [],
            "states": {},
            "control": "",
        },
    )
    calls = []

    def call(prompt, **kw):
        calls.append(prompt)
        return '{"score":0.5}' if kw["agent_id"] is None else '{"answer":"done"}'

    runner.run(db, r["id"], call)
    final = db.audit(r["id"])
    assert final["status"] == "completed"
    assert sum(row["metrics"]["calls"] for row in final["rows"]) == len(calls)
    assert len(calls) <= spec["budget"]["max_requests"]
    assert all(s["scoring_attempts"] for s in final["states"].values())


def test_analysis_reports_costs_and_exploratory_categories():
    _, a = modules()
    rows = paired()
    for row in rows:
        row["category"] = "reasoning"
        row["metrics"].update(input_chars=100, output_chars=20, elapsed=0.5)
    result = a.analyze(rows, expected=60)
    assert result["arms"]["candidate"]["input_chars"] == 3000
    assert result["arms"]["candidate"]["elapsed"] == 15
    assert result["categories"][0]["category"] == "reasoning"
    assert result["categories"][0]["exploratory"] is True


@pytest.mark.parametrize("scorer", ["choice", "exact", "allocation", "rubric"])
def test_missing_final_answer_always_gets_failure_score_without_judging(scorer):
    b, _ = modules()
    q = b.builtin("allocation", count=1)["tasks"][0]
    q.update(scorer=scorer, rubric="quality")
    calls = []
    result = b.score(q, {"answer": None}, judge=lambda p: calls.append(p) or '{"score":1}')
    assert result["score"] == 0
    assert not result["valid"]
    assert not calls


@pytest.mark.parametrize("answer", ["Z", {"answer": "A"}, ["A"]])
def test_invalid_choice_does_not_count_as_completed(answer):
    b, _ = modules()
    q = b.builtin(count=1)["tasks"][0]
    result = b.score(q, {"answer": answer})
    assert result["score"] == 0
    assert not result["valid"]


def test_comparison_pause_keeps_attempt_and_resume_reuses_it(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    spec = protocol.freeze(
        {
            "candidate": baseline("independent", 2),
            "baseline": "independent",
            "benchmark": b.builtin(count=1, slots=2),
            "repeats": 1,
        },
        [{"id": 1}, {"id": 2}],
        {"model": "test"},
    )
    db = store.Store(tmp_path)
    record = db.create(
        "C",
        {
            "status": "draft",
            "protocol": spec,
            "protocol_hash": protocol.digest(spec),
            "rows": [],
            "states": {},
            "control": "",
        },
    )
    calls = []

    def call(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            db.update(record["id"], lambda r: r.update(control="pause"))
        return '{"answer":"A"}'

    runner.run(db, record["id"], call)
    assert db.get(record["id"])["status"] == "paused"
    db.update(record["id"], lambda r: r.update(control=""))
    runner.run(db, record["id"], call)
    assert db.get(record["id"])["status"] == "completed"
    assert len(calls) == 4


def test_call_evidence_is_stored_per_cell_not_rewritten_into_progress_record(tmp_path):
    modules()
    from gaworld.research.organization_intelligence.comparison.store import Store

    db = Store(tmp_path)
    r = db.create("C", {"states": {}})
    cell = "0:0:candidate"
    db.save_state(r["id"], cell, {"calls": [{"response": "PRIVATE-EVIDENCE"}], "attempts": []})
    assert db.load_state(r["id"], cell)["calls"][0]["response"] == "PRIVATE-EVIDENCE"
    assert "PRIVATE-EVIDENCE" not in (db.directory(r["id"]) / "record.json").read_text()
