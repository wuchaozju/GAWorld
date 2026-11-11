import copy
import importlib.util
import json

import pytest
import requests


def http_error(code=2062, status=429, retry_after=None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"error": {"message": f"Token Plan limit ({code}) SECRET-KEY"}}).encode()
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return requests.HTTPError("contains SECRET-KEY", response=response)


def failures():
    assert importlib.util.find_spec("gaworld.llm.failures"), "safe HTTP failure diagnostics missing"
    from gaworld.llm import failures

    return failures


def test_token_plan_rate_limit_and_quota_are_distinguished_without_secrets():
    f = failures()
    rate = f.describe(http_error(), now=100)
    quota = f.describe(http_error(2067), now=100)
    assert rate["http_status"] == 429 and rate["provider_code"] == "2062"
    assert rate["kind"] == "token_plan_rate_limit"
    assert quota["kind"] == "token_plan_quota"
    assert rate["retry_at"] >= 400
    assert "SECRET-KEY" not in json.dumps(rate)
    assert rate["message"] != "HTTPError"


def test_retry_after_is_not_shortened_and_auth_errors_are_not_rate_limits():
    f = failures()
    assert f.describe(http_error(retry_after=900), now=100)["retry_at"] == 1000
    assert f.describe(http_error(status=401), now=100)["kind"] == "authentication"


def test_request_hook_runs_only_for_new_network_attempts():
    from gaworld.collaboration import organization_engine as engine
    from gaworld.collaboration.organization_methods import baseline

    state, hooks = {}, []
    method, members, task = (
        baseline("independent", 2),
        [{"id": 1}, {"id": 2}],
        {"prompt": "q", "options": ["A"]},
    )
    kwargs = {"state": state, "before_request": lambda: hooks.append("request")}
    engine.run_method(method, members, task, lambda *a, **k: '{"answer":"A"}', **kwargs)
    engine.run_method(method, members, task, lambda *a, **k: pytest.fail("must replay"), **kwargs)
    assert len(hooks) == 2


def test_failed_attempt_keeps_safe_http_diagnostics():
    from gaworld.collaboration import organization_engine as engine
    from gaworld.collaboration.organization_methods import baseline

    state = {}
    with pytest.raises(requests.HTTPError):
        engine.run_method(
            baseline("independent", 2),
            [{"id": 1}, {"id": 2}],
            {"prompt": "q"},
            lambda *a, **k: (_ for _ in ()).throw(http_error()),
            state=state,
        )
    assert state["attempts"][0]["error_info"]["http_status"] == 429


def test_pacing_is_interruptible_and_does_not_allocate_an_attempt(tmp_path):
    from gaworld.research.organization_intelligence.comparison import execution
    from gaworld.research.organization_intelligence.comparison.store import Store

    db = Store(tmp_path)
    r = db.create("C", {"last_request_at": 100, "control": ""})
    ticks = [101.0]

    def sleep(seconds):
        ticks[0] += seconds

    execution.wait_for_request(db, r["id"], 10, lambda: None, clock=lambda: ticks[0], sleep=sleep)
    assert ticks[0] == pytest.approx(110)
    assert db.get(r["id"])["waiting"] is None

    def stop():
        raise InterruptedError("paused")

    with pytest.raises(InterruptedError):
        execution.wait_for_request(db, r["id"], 10, stop, clock=lambda: ticks[0], sleep=sleep)


def test_pacing_deadline_crossed_during_check_never_sleeps_negative(tmp_path):
    from gaworld.research.organization_intelligence.comparison import execution
    from gaworld.research.organization_intelligence.comparison.store import Store

    db = Store(tmp_path)
    r = db.create("C", {"last_request_at": 100})
    ticks = [109.9]

    def check():
        ticks[0] += 0.2

    def sleep(seconds):
        assert seconds >= 0
        ticks[0] += seconds

    execution.wait_for_request(db, r["id"], 10, check, clock=lambda: ticks[0], sleep=sleep)


def test_http_limit_preserves_progress_and_can_prepare_verified_recovery(tmp_path, monkeypatch):
    from gaworld.collaboration.organization_methods import baseline
    from gaworld.research.organization_intelligence.comparison import protocol, recovery, runner
    from gaworld.research.organization_intelligence.comparison.store import Store

    db = Store(tmp_path)
    spec = protocol.freeze(
        {"candidate": baseline("full", 2), "count": 2, "repeats": 1},
        [{"id": 1}, {"id": 2}],
        {"name": "test", "model": "test"},
    )
    # One lane, so the order of the requests is the order of the cells.
    spec["execution_policy"] = {**spec["execution_policy"], "concurrency": 1}
    original = db.create(
        "C",
        {
            "protocol": spec,
            "protocol_hash": protocol.digest(spec),
            "status": "draft",
            "states": {},
            "rows": [],
            "control": "",
            "analysis": {},
        },
    )
    monkeypatch.setattr(runner.execution, "wait_for_request", lambda *a, **k: None)
    calls = []

    def call(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 8:
            raise http_error()
        return '{"answer":"A"}'

    runner.run(db, original["id"], call)
    interrupted = db.get(original["id"])
    assert interrupted["status"] == "rate_limited"
    assert len(interrupted["rows"]) == 1
    assert interrupted["error_info"]["provider_code"] == "2062"
    before = (db.directory(original["id"]) / "record.json").read_bytes()
    linked = recovery.prepare(db, interrupted)
    assert linked["status"] == "draft"
    assert linked["rows"] == interrupted["rows"]
    assert linked["recovery"]["verified_responses"] == 7
    assert linked["protocol"]["model"] == spec["model"]
    assert len(calls) == 8
    assert before == (db.directory(original["id"]) / "record.json").read_bytes()
    # Corrupted responses/prompts cannot be imported into a recovery.
    bad = copy.deepcopy(db.load_state(original["id"], "0:0:baseline"))
    bad["calls"][0]["prompt_hash"] = "tampered"
    db.save_state(original["id"], "0:0:baseline", bad)
    with pytest.raises(ValueError):
        recovery.prepare(db, interrupted)
