"""Research brief recovery remains bounded and never fabricates state data."""

import json

import pytest

from gaworld.llm.run_state import RunLedger
from gaworld.sim._fastforward import _run_digest


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = str(tmp_path / "briefs.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    monkeypatch.setenv("GAWORLD_RESEARCH_DAILY_BRIEF", "1")
    return RunLedger(path)


def run(llm):
    return _run_digest(
        {"id": 1},
        prompt="Only output JSON",
        task="fast_forward_day",
        max_delta=0.1,
        brief_max_chars=240,
        max_memories=1,
        llm_fn=llm,
    )


def test_complete_json_after_thinking_and_prose_is_usable(ledger):
    response = (
        "<think>Example: {not JSON}</think>Here is the output:\n```json\n"
        + json.dumps(
            {"brief": "Actual day", "state_changes": {"stress": -0.02}, "memory": "Learned something"}
        )
        + "\n```"
    )
    result = run(lambda *a, **kw: response)
    assert result["brief"] == "Actual day"
    assert result["state_changes"]["stress"] == -0.02
    assert ledger.snapshot()["valid_briefs"] == 1


def test_one_malformed_response_can_be_repaired_without_spending_failure_budget(ledger):
    responses = iter(
        ['{"brief": "cut off', json.dumps({"brief": "Recovered day", "state_changes": {"stress": -0.01}})]
    )
    calls = []

    def llm(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return next(responses)

    result = run(llm)
    assert result["brief"] == "Recovered day"
    assert len(calls) == 2
    assert calls[1][1]["task"] == "fast_forward_day"
    assert calls[1][1]["max_tokens"] == 4096
    stats = ledger.snapshot()
    assert stats["invalid_briefs"] == 0
    assert stats["brief_parse_failures"] == 1
    assert stats["recovered_briefs"] == 1


def test_two_unusable_responses_stop_the_world_and_record_diagnostics(ledger):
    calls = []
    secret = "never-persist-this-model-response"

    def llm(*args, **kwargs):
        calls.append(1)
        return secret

    with pytest.raises(RuntimeError, match=r"简报.*两次"):
        run(llm)
    assert len(calls) == 2
    stats = ledger.snapshot()
    assert stats["invalid_briefs"] == 1
    assert stats["brief_parse_failures"] == 2
    assert stats["last_brief_failure"]["agent_id"] == 1
    assert secret not in json.dumps(stats)


def test_provider_exception_is_not_retried_as_a_format_error(ledger):
    calls = []

    def llm(*args, **kwargs):
        calls.append(1)
        raise ConnectionError("provider unavailable")

    with pytest.raises(RuntimeError, match="调用失败") as error:
        run(llm)
    assert isinstance(error.value.__cause__, ConnectionError)
    assert calls == [1]
    assert ledger.snapshot()["invalid_briefs"] == 0


def test_unclosed_thinking_example_is_repaired_instead_of_used(ledger):
    responses = iter(
        [
            '<think>Example {"brief":"sample","state_changes":{}}',
            '{"brief":"Actual day","state_changes":{}}',
        ]
    )
    result = run(lambda *a, **kw: next(responses))
    assert result["brief"] == "Actual day"
    stats = ledger.snapshot()
    assert stats["valid_briefs"] == 1
    assert stats["brief_parse_failures"] == 1
    assert stats["last_brief_failure"]["category"] == "truncated_thinking"


def test_two_unclosed_thinking_examples_produce_no_valid_brief(ledger):
    with pytest.raises(RuntimeError, match="truncated_thinking"):
        run(lambda *a, **kw: '<think>Example {"brief":"sample","state_changes":{}}')
    assert ledger.snapshot()["valid_briefs"] == 0
    assert ledger.snapshot()["invalid_briefs"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"brief": "day"},
        {"brief": ["wrong type"], "state_changes": {}},
        {"brief": "day", "state_changes": {"stress": "invented"}},
    ],
)
def test_incomplete_schema_is_not_accepted_as_real_brief_data(ledger, payload):
    with pytest.raises(RuntimeError, match="简报"):
        run(lambda *a, **kw: json.dumps(payload))
    assert ledger.snapshot()["invalid_briefs"] == 1


def test_error_message_does_not_claim_previous_valid_days_are_missing(ledger):
    run(lambda *a, **kw: '{"brief":"valid day","state_changes":{}}')
    for _ in range(3):
        with pytest.raises(RuntimeError):
            run(lambda *a, **kw: "invalid JSON")
    state = ledger.snapshot()
    assert state["aborted"]
    assert state["valid_briefs"] == 1
    assert "没有可用简报数据" not in state["reason"]
