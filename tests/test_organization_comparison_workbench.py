import importlib.util
import json

import pytest


@pytest.fixture(autouse=True)
def no_real_request_waits(monkeypatch):
    import time

    from gaworld.research.organization_intelligence.comparison import execution

    monkeypatch.setattr(execution, "wait_for_request", lambda *a, **kw: None)
    monkeypatch.setattr(time, "sleep", lambda *a: None)


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


def test_default_comparison_holds_everything_but_the_topology_equal():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    candidate = {**baseline("full", 3), "review": True, "revisions": 1}
    p = protocol.freeze({"candidate": candidate, "count": 1}, [{"id": i} for i in range(3)], {"model": "x"})
    assert p["scope"] == "topology"
    assert p["scope_factors"]["candidate"] == ["topology"]
    assert p["scope_factors"]["baseline"] == []
    assert p["baseline"]["review"] is True
    assert p["baseline"]["revisions"] == 1
    assert p["baseline"]["roles"] == candidate["roles"]


def test_a_factor_asked_to_differ_is_left_alone_and_widens_the_scope():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    candidate = {**baseline("full", 3), "review": True, "revisions": 1}
    p = protocol.freeze(
        {"candidate": candidate, "count": 1, "factors": {"review": "candidate"}},
        [{"id": i} for i in range(3)],
        {"model": "x"},
    )
    assert p["scope"] == "whole_method"
    assert set(p["scope_factors"]["candidate"]) == {"review"}
    assert not p["baseline"]["review"]
    # A factor that was not asked to differ is held equal, so the result can
    # be attributed to one mechanism.
    assert p["baseline"]["topology"]["kind"] == candidate["topology"]["kind"]


def test_every_factor_same_is_refused():
    modules()
    from gaworld.research.organization_intelligence.comparison import protocol

    with pytest.raises(ValueError, match="至少"):
        protocol.resolve_factors({"factors": dict.fromkeys(protocol.FACTORS, "same")})
    with pytest.raises(ValueError, match="same"):
        protocol.resolve_factors({"factors": {"topology": "whatever"}})


def test_custom_baseline_keeps_the_roles_its_author_wrote():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    candidate = {**baseline("full", 2), "roles": ["分析", "核对"]}
    custom = {**baseline("independent", 2), "roles": ["甲", "乙"]}
    p = protocol.freeze(
        {"candidate": candidate, "baseline": "custom", "baseline_method": custom, "count": 1},
        [{"id": 1}, {"id": 2}],
        {"model": "x"},
    )
    assert p["baseline"]["roles"] == ["甲", "乙"]
    assert p["scope_factors"]["candidate"] == ["roles", "topology"]


def test_both_arms_receive_the_organization_rules_they_need():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    candidate = {
        **baseline("full", 2),
        "rules": [{"text": "先各自写出证据再统一结论", "origin": "user", "quote": ""}],
    }
    p = protocol.freeze(
        {"candidate": candidate, "baseline": "hierarchy", "count": 1},
        [{"id": 1}, {"id": 2}],
        {"model": "x"},
    )
    assert any("先各自写出证据再统一结论" in line for line in p["instructions"]["candidate"])
    assert any("层级组织" in line for line in p["instructions"]["baseline"])
    assert all(p["instructions"]["baseline"])


def test_resource_limits_follow_the_shape_of_the_method():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    candidate = {**baseline("full", 12), "rounds": 6}
    p = protocol.freeze({"candidate": candidate, "count": 1}, [{"id": i} for i in range(12)], {"model": "x"})
    needed = candidate and p["plan"]["calls_per_cell"]["candidate"]
    assert needed == 12 * (1 + 6) + 1
    assert p["limits"]["calls"] >= needed
    assert p["limits"]["prompt_chars"] > 12 * 4000
    assert p["plan"]["sufficient"]


def test_plan_reports_cells_calls_and_the_earliest_finish():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    p = protocol.freeze(
        {"candidate": baseline("full", 3), "count": 4, "repeats": 2},
        [{"id": i} for i in range(3)],
        {"model": "x"},
    )
    assert p["plan"]["cells"] == 16
    assert p["plan"]["total_calls"] == 8 * (
        p["plan"]["calls_per_cell"]["candidate"] + p["plan"]["calls_per_cell"]["baseline"]
    )
    assert p["plan"]["min_seconds"] == int(
        p["plan"]["total_calls"] * p["plan"]["min_interval_seconds"] / p["plan"]["concurrency"]
    )


def test_a_limit_below_the_shape_is_a_warning_and_the_run_is_refused():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    p = protocol.freeze(
        {"candidate": baseline("full", 3), "count": 1, "limits": {"calls": 1}},
        [{"id": i} for i in range(3)],
        {"model": "x"},
    )
    assert not p["plan"]["sufficient"]
    assert any("调用次数上限" in w for w in p["plan"]["warnings"])


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
            db.touch(record["id"], control="pause")
        return '{"answer":"A"}'

    runner.run(db, record["id"], call)
    assert db.merged(record["id"])["status"] == "paused"
    db.touch(record["id"], control="")
    runner.run(db, record["id"], call)
    assert db.merged(record["id"])["status"] == "completed"
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


def test_a_cell_that_cannot_be_measured_is_not_scored_as_a_wrong_answer(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    spec = protocol.freeze(
        {
            "candidate": baseline("independent", 2),
            "baseline": "independent",
            "benchmark": b.builtin(count=1, slots=2),
            "repeats": 1,
            "limits": {"calls": 1},
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
            "analysis": {},
        },
    )
    runner.run(db, record["id"], lambda prompt, **kw: '{"answer":"A"}')
    final = db.audit(record["id"])
    assert final["status"] == "completed"
    assert final["rows"]
    assert all(row["measured"] is False for row in final["rows"])
    assert all(row["score"] is None for row in final["rows"])
    assert all(row["invalid_reason"] == "budget_exceeded" for row in final["rows"])
    # The numbers that were measured are still reported.
    assert final["analysis"]["verdict"] == "incomplete"
    assert final["analysis"]["arms"]["candidate"]["mean"] is None
    assert final["analysis"]["unmeasured_rows"] == len(final["rows"])


def test_descriptive_statistics_are_reported_even_when_the_run_is_incomplete(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    spec = protocol.freeze(
        {
            "candidate": baseline("independent", 2),
            "baseline": "independent",
            "benchmark": b.builtin(count=2, slots=2),
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
            "analysis": {},
        },
    )
    runner.run(db, record["id"], lambda prompt, **kw: '{"answer":"A"}')
    result = db.audit(record["id"])["analysis"]
    assert result["complete"]
    assert result["arms"]["candidate"]["calls"] > 0
    assert result["arms"]["candidate"]["completion_rate"] == 1.0


def test_the_run_writes_an_append_only_log_and_leaves_the_record_alone(tmp_path):
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
            "analysis": {},
        },
    )
    prompts = []

    def llm(prompt, **kw):
        prompts.append(prompt)
        return '{"answer":"A"}'

    runner.run(db, record["id"], llm)
    events = (db.directory(record["id"]) / "events.jsonl").read_text().splitlines()
    assert len(events) >= 4
    assert all(json.loads(line)["cell"] for line in events)
    # The evidence of a request lives in the cell file and the log, not in the
    # study record that is rewritten for every cell.
    record_text = (db.directory(record["id"]) / "record.json").read_text()
    assert all(prompt not in record_text for prompt in prompts)
    assert '"attempts":' not in record_text


def test_the_two_arms_do_not_share_one_random_graph(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    spec = protocol.freeze(
        {
            "candidate": baseline("random", 3),
            "baseline": "random",
            "benchmark": b.builtin(count=1, slots=3),
            "repeats": 1,
        },
        [{"id": 1}, {"id": 2}, {"id": 3}],
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
            "analysis": {},
        },
    )
    runner.run(db, record["id"], lambda prompt, **kw: '{"answer":"A"}')
    rows = {row["arm"]: row for row in db.audit(record["id"])["rows"]}
    assert rows["candidate"]["edges"] != rows["baseline"]["edges"]


def test_a_provider_error_marks_one_cell_and_the_run_continues(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    spec = protocol.freeze(
        {
            "candidate": baseline("independent", 2),
            "baseline": "independent",
            "benchmark": b.builtin(count=2, slots=2),
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
            "analysis": {},
        },
    )

    def llm(prompt, **kw):
        raise RuntimeError("provider is down")

    runner.run(db, record["id"], llm)
    final = db.audit(record["id"])
    assert final["status"] == "completed"
    assert len(final["rows"]) == 4
    assert all(row["measured"] is False for row in final["rows"])
    assert all(row["invalid_reason"] == "request_failed" for row in final["rows"])
    assert all(row["score"] is None for row in final["rows"])


def test_a_failed_request_is_retried_once_before_the_cell_is_given_up(tmp_path):
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
            "analysis": {},
        },
    )
    seen = []

    def llm(prompt, **kw):
        seen.append(prompt)
        if len(seen) == 1:
            raise RuntimeError("provider is down")
        return '{"answer":"A"}'

    runner.run(db, record["id"], llm)
    final = db.audit(record["id"])
    assert all(row["measured"] for row in final["rows"])
    assert len(seen) == 5  # 4 calls plus the one that was retried


def test_a_saved_judge_answer_is_reused_after_an_interruption(tmp_path):
    b, _ = modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, runner, store

    bank = b.validate(
        [{"id": "q", "category": "open", "prompt": "write", "rubric": "quality 0-1"}], scorer="rubric"
    )
    spec = protocol.freeze(
        {
            "candidate": baseline("independent", 2),
            "baseline": "independent",
            "benchmark": bank,
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
            "analysis": {},
        },
    )
    judges = []

    def llm(prompt, **kw):
        if "rubric" in prompt:
            judges.append(prompt)
            return '{"score":0.5}'
        return '{"answer":"A"}'

    runner.run(db, record["id"], llm)
    assert len(judges) == 2  # one judge per cell
    # An interruption between the judge's answer and the written row: the
    # answer is in the cell's evidence, the row is not there yet.
    final = db.audit(record["id"])
    cell = final["rows"][0]["cell"]
    db.update(record["id"], lambda r: r.update(rows=[row for row in r["rows"] if row["cell"] != cell]))
    db.update(record["id"], lambda r: r.update(status="interrupted"))
    judges.clear()
    runner.run(db, record["id"], llm)
    # The cell runs again, but neither its members nor its judge are asked
    # again: the answers already paid for are in its evidence.
    assert len(judges) == 0
    rows = db.audit(record["id"])["rows"]
    assert len(rows) == 2
    assert all(row["score"] is not None for row in rows)


def test_the_fingerprint_follows_the_meaning_and_not_the_files(monkeypatch):
    modules()
    from gaworld.research.organization_intelligence.comparison import protocol

    first = protocol.runtime_fingerprint()
    assert first == protocol.runtime_fingerprint()
    monkeypatch.setattr(protocol.organization_engine, "VERSION", "organization-engine-99")
    assert protocol.runtime_fingerprint() != first
    # The bytes of the files are recorded separately, for the audit trail.
    assert protocol.code_fingerprint() != first


def test_a_resume_under_a_different_prompt_is_refused_and_not_scored(tmp_path, monkeypatch):
    b, _ = modules()
    from gaworld.collaboration import organization_engine
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
            "analysis": {},
        },
    )
    runner.run(db, record["id"], lambda prompt, **kw: '{"answer":"A"}')
    rows = db.audit(record["id"])["rows"]
    cell = rows[0]["cell"]
    db.update(record["id"], lambda r: r.update(rows=[row for row in r["rows"] if row["cell"] != cell]))
    db.update(record["id"], lambda r: r.update(status="interrupted"))
    # The engine now sends a different prompt for the same method.
    monkeypatch.setattr(organization_engine, "instructions", lambda method: ["另一种做法"])
    runner.run(db, record["id"], lambda prompt, **kw: '{"answer":"A"}')
    final = db.audit(record["id"])
    drifted = [row for row in final["rows"] if row["cell"] == cell]
    assert drifted and drifted[0]["measured"] is False
    assert drifted[0]["invalid_reason"] == "protocol_drift"
    assert drifted[0]["score"] is None
    assert final["status"] == "interrupted"


def test_two_studies_on_one_model_may_not_run_at_the_same_time(tmp_path):
    modules()
    import fcntl

    from gaworld.apps import organization_comparison_api
    from gaworld.research.organization_intelligence.comparison import store

    db = store.Store(tmp_path)
    first = db.create(
        "C",
        {
            "status": "running",
            "protocol": {"model": {"name": "m"}},
            "protocol_hash": "x",
            "rows": [],
            "analysis": {},
        },
    )
    second = db.create(
        "C",
        {
            "status": "draft",
            "protocol": {"model": {"name": "m"}},
            "protocol_hash": "x",
            "rows": [],
            "analysis": {},
        },
    )
    lease = (db.directory(first["id"]) / "runner.lock").open("a")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(ValueError, match="该模型已有"):
            organization_comparison_api._guard_capacity(db, second)
    finally:
        lease.close()
    assert first["id"] != second["id"]


def test_at_most_two_studies_run_at_the_same_time(tmp_path):
    modules()
    import fcntl

    from gaworld.apps import organization_comparison_api
    from gaworld.research.organization_intelligence.comparison import store

    db = store.Store(tmp_path)
    running = [
        db.create(
            "C",
            {
                "status": "running",
                "protocol": {"model": {"name": f"m{index}"}},
                "protocol_hash": "x",
                "rows": [],
                "analysis": {},
            },
        )
        for index in range(2)
    ]
    third = db.create(
        "C",
        {
            "status": "draft",
            "protocol": {"model": {"name": "other"}},
            "protocol_hash": "x",
            "rows": [],
            "analysis": {},
        },
    )
    leases = [(db.directory(item["id"]) / "runner.lock").open("a") for item in running]
    for lease in leases:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(ValueError, match="最多同时"):
            organization_comparison_api._guard_capacity(db, third)
    finally:
        for lease in leases:
            lease.close()


def test_more_than_one_candidate_can_be_compared_against_the_same_control():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    p = protocol.freeze(
        {
            "candidate": baseline("full", 2),
            "baseline": "independent",
            "count": 1,
            "candidates": [
                {"label": "层级做法", "method": baseline("hierarchy", 2)},
                {"label": "随机做法", "method": baseline("random", 2)},
            ],
        },
        [{"id": 1}, {"id": 2}],
        {"model": "x"},
    )
    ids = [arm["id"] for arm in p["arms"]]
    assert ids == ["candidate", "candidate-2", "candidate-3", "baseline"]
    assert p["arms"][-1]["is_control"] is True
    # The two arms of a two-arm study keep the seeds they had before the
    # candidates existed.
    assert p["arms"][0]["seed_offset"] == 0
    assert p["arms"][-1]["seed_offset"] == 1
    assert [arm["seed_offset"] for arm in p["arms"][1:-1]] == [2, 3]
    assert p["expected"] == len(p["benchmark"]["tasks"]) * p["repeats"] * 4
    assert set(p["instructions"]) == set(ids)
    # Every candidate has its own scope against the shared control.
    assert p["scope_factors"]["candidate-2"] == ["topology"]
    assert p["scope_factors"]["baseline"] == []


def test_a_candidate_needs_its_own_name_and_the_same_number_of_roles():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    with pytest.raises(ValueError, match="名称"):
        protocol.freeze(
            {
                "candidate": baseline("full", 2),
                "count": 1,
                "candidates": [{"method": baseline("hierarchy", 2)}],
            },
            [{"id": 1}, {"id": 2}],
            {"model": "x"},
        )
    with pytest.raises(ValueError, match="角色数量"):
        protocol.freeze(
            {
                "candidate": baseline("full", 2),
                "count": 1,
                "candidates": [{"label": "三人", "method": baseline("hierarchy", 3)}],
            },
            [{"id": 1}, {"id": 2}],
            {"model": "x"},
        )
    with pytest.raises(ValueError, match="最多"):
        protocol.freeze(
            {
                "candidate": baseline("full", 2),
                "count": 1,
                "candidates": [
                    {"label": "甲", "method": baseline("hierarchy", 2)},
                    {"label": "乙", "method": baseline("random", 2)},
                    {"label": "丙", "method": baseline("full", 2)},
                ],
            },
            [{"id": 1}, {"id": 2}],
            {"model": "x"},
        )


def test_every_candidate_gets_its_own_verdict_against_the_control():
    _, a = modules()
    rows = []
    for index in range(30):
        task = f"q{index}"
        rows.append(
            {"task_id": task, "repeat": 0, "arm": "candidate", "score": 0.9, "valid": True, "measured": True}
        )
        rows.append(
            {
                "task_id": task,
                "repeat": 0,
                "arm": "candidate-2",
                "score": 0.5,
                "valid": True,
                "measured": True,
            }
        )
        rows.append(
            {"task_id": task, "repeat": 0, "arm": "baseline", "score": 0.4, "valid": True, "measured": True}
        )
    result = a.analyze(rows, expected=90, arms=["candidate", "candidate-2", "baseline"])
    assert result["verdict"] == "better"
    assert result["candidates"]["candidate"]["verdict"] == "better"
    assert result["candidates"]["candidate-2"]["verdict"] == "better"
    assert result["candidates"]["candidate"]["difference"] == 0.5
    assert result["candidates"]["candidate-2"]["difference"] == pytest.approx(0.1)
    # The candidate that is not better is not called better.
    weak = [dict(row, score=0.4) if row["arm"] == "candidate" else row for row in rows]
    assert (
        a.analyze(weak, expected=90, arms=["candidate", "candidate-2", "baseline"])["candidates"][
            "candidate"
        ]["verdict"]
        == "uncertain"
    )


def test_an_unmeasured_cell_leaves_the_other_candidates_readable():
    _, a = modules()
    rows = [
        {"task_id": "q1", "repeat": 0, "arm": "candidate", "score": 0.8, "valid": True, "measured": True},
        {
            "task_id": "q1",
            "repeat": 0,
            "arm": "candidate-2",
            "score": None,
            "valid": False,
            "measured": False,
        },
        {"task_id": "q1", "repeat": 0, "arm": "baseline", "score": 0.5, "valid": True, "measured": True},
    ]
    result = a.analyze(rows, expected=3, arms=["candidate", "candidate-2", "baseline"])
    assert result["complete"] is False
    assert result["verdict"] == "incomplete"
    assert result["arms"]["candidate-2"]["unmeasured"] == 1
    assert result["arms"]["candidate"]["mean"] == 0.8


def test_a_protocol_frozen_before_the_arms_existed_is_still_readable():
    modules()
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol

    spec = protocol.freeze(
        {"candidate": baseline("full", 2), "count": 1}, [{"id": 1}, {"id": 2}], {"model": "x"}
    )
    old = {key: value for key, value in spec.items() if key != "arms"}
    arms = protocol.arms_of(old)
    assert [arm["id"] for arm in arms] == ["candidate", "baseline"]
    assert [arm["seed_offset"] for arm in arms] == [0, 1]
