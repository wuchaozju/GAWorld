"""Offline regressions for resumable OI rate limits and conservative parsing."""

import copy
import json

import pytest
import requests

from gaworld.research.organization_intelligence import experiment, protocol
from tests.test_organization_intelligence import fake, residents


def http_error(status=429, code=2062, retry_after=None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"error": {"message": f"Token Plan ({code})"}}).encode()
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return requests.HTTPError("provider failed", response=response)


def test_rate_limit_recognizes_falsey_429_response_and_retry_floor():
    from gaworld.research.organization_intelligence.recovery import rate_limit

    info = rate_limit(http_error(retry_after=600), now=1000)
    assert info["kind"] == "token_plan_2062" and info["retry_at"] == 1600
    assert rate_limit(http_error(retry_after=1), now=1000)["retry_at"] == 1300
    assert rate_limit(http_error(code=0, retry_after=90), now=1000)["retry_at"] == 1090
    assert rate_limit(http_error(status=401), now=1000) is None


def test_replay_restores_partial_task_without_repeating_provider_calls():
    spec = protocol.freeze({"repeats": 1}, residents(), {"name": "test"})
    complete = []
    expected = experiment.run(spec, fake, complete.append)
    prefix = copy.deepcopy(complete[:6])
    events, submitted = [], []

    def llm(prompt):
        submitted.append(prompt)
        return fake(prompt)

    actual = experiment.run(spec, llm, events.append, replay=prefix)
    assert actual == expected
    assert len(submitted) == 103 and len(events) == 109
    assert all(e["replayed"] for e in events[:6])
    assert all(not e.get("replayed") for e in events[6:])
    assert submitted[0] == complete[6]["prompt"]


@pytest.mark.parametrize("change", ["prompt", "answer", "number", "status"])
def test_replay_tampering_stops_before_any_new_call(change):
    spec = protocol.freeze({"repeats": 1}, residents(), {"name": "test"})
    complete = []
    experiment.run(spec, fake, complete.append)
    event = copy.deepcopy(complete[0])
    event[change] = {
        "prompt": "other context",
        "answer": {"choice": 2, "message": "changed"},
        "number": 9,
        "status": "parse_error",
    }[change]
    submitted = []
    with pytest.raises(ValueError):
        experiment.run(spec, lambda p: submitted.append(p) or fake(p), lambda e: None, replay=[event])
    assert submitted == []


def test_new_protocol_can_escape_only_complete_message_content_without_guessing_choice():
    raw = '{"choice":2,"message":"继续按"高物资优先"选择。\n第二行"}'
    with pytest.raises(ValueError):
        experiment.parse(raw)
    assert experiment.parse(raw, repair=True) == {"choice": 2, "message": '继续按"高物资优先"选择。\n第二行'}


@pytest.mark.parametrize(
    "raw",
    [
        '{"message":"选2"}',
        '{"choice":2,"message":"unfinished',
        '{"choice":0,"message":"x","choice":2}',
        '{"choice":2,"message":"x","extra":true}',
        '{"choice":true,"message":"x"}',
        '{"choice":7,"message":"x"}',
    ],
)
def test_repair_never_invents_a_missing_choice_or_ignores_extra_fields(raw):
    with pytest.raises(ValueError):
        experiment.parse(raw, repair=True)


def test_spacing_waits_for_slot_and_cooperatively_checks_stop():
    from gaworld.research.organization_intelligence.recovery import wait_for_slot

    now, flags, checks = [5.0], [], []

    def wait(seconds):
        now[0] += seconds

    started = wait_for_slot(0, 10, lambda: checks.append(True), flags.append, wait, clock=lambda: now[0])
    assert started == 10 and flags == [True, False] and checks

    def stop():
        raise RuntimeError("stop requested")

    with pytest.raises(RuntimeError, match="stop requested"):
        wait_for_slot(0, 10, stop, flags.append, wait, clock=lambda: 1)
    assert flags[-1] is False


@pytest.mark.parametrize(
    "raw",
    [
        r'{"choice":2,"message":"x\\",0,"y"}',
        r'{"choice":2,"message":"x\\" : "y"}',
    ],
)
def test_repair_rejects_structural_quote_after_even_backslashes(raw):
    with pytest.raises(ValueError):
        experiment.parse(raw, repair=True)
