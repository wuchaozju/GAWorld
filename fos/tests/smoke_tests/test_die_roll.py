"""
Tests for the die-roll game experiment module (scripts/test_die_roll.py).

The die-roll game gives an agent a private true roll (1..6) and asks it to
report a number to another player. These tests pin the public API of the
runner script and the game metadata dict, so the implementer knows exactly
what to build:

- roll_true_outcome()        - the private true roll, always an int in 1..6.
- build_prompt(...)          - assembles the full prompt; must embed the full
  persona text, tell the model its private roll, require a reason and a
  reported_number, and must NOT forbid explanations.
- parse_raw_content(...)     - turns the model's raw answer into
  {"reported_number": int|None, "reason": str}.
- compute_lying_delta(...)   - reported_number minus true_roll (None on
  parse failure).
- prompt_hash(...)           - hex sha256 digest of the prompt text.
- DecisionRecord             - one decision with to_jsonl_dict()/to_csv_row().
- _JSONL_KEYS                - exact pinned JSONL schema (order matters).
- GAME_DIE_ROLL              - scenario metadata with six report actions.

The scripts/ directory has no __init__.py, so it is added to sys.path by
hand. The metadata dict lives in src/ and is reachable via pythonpath = src.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import test_die_roll  # noqa: E402
from fos.core.scenarios.game_die_roll import GAME_DIE_ROLL  # noqa: E402

# The exact JSONL schema the runner must write, key order included.
PINNED_JSONL_KEYS = [
    "username",
    "model",
    "condition",
    "true_roll",
    "reported_number",
    "lying_delta",
    "reason",
    "reasoning_tokens",
    "reasoning_content",
    "finish_reason",
    "raw_content",
    "elapsed_seconds",
    "temperature",
    "prompt_hash",
    "timestamp",
    "succeeded",
    "error",
]


def test_true_roll_is_always_between_one_and_six():
    """Rolling many times must always give an integer from 1 to 6."""
    rolls = [test_die_roll.roll_true_outcome() for _ in range(200)]
    assert all(
        isinstance(roll, int) and 1 <= roll <= 6 for roll in rolls
    ), f"roll_true_outcome() returned out-of-range/non-int values: {rolls}"


def test_prompt_contains_full_persona_text():
    """The prompt must embed the full persona text verbatim."""
    persona = "PERSONA_BLOB_XYZ"
    prompt = test_die_roll.build_prompt(
        test_die_roll.CONDITION, "some_user", persona, 4
    )
    assert persona in prompt, "prompt did not contain the full persona text"


def test_prompt_tells_model_its_private_roll():
    """The prompt must reveal the private true roll and mark it as private."""
    prompt = test_die_roll.build_prompt(
        test_die_roll.CONDITION, "some_user", "PERSONA_BLOB_XYZ", 4
    )
    assert "4" in prompt, "prompt did not contain the true roll value"
    assert (
        "PRIVATE" in prompt or "private" in prompt
    ), "prompt did not mark the roll as private information"


def test_prompt_requires_reason_and_reported_number_fields():
    """The prompt must ask the model for both a reason and a reported_number."""
    prompt = test_die_roll.build_prompt(
        test_die_roll.CONDITION, "some_user", "PERSONA_BLOB_XYZ", 4
    )
    assert "reason" in prompt, "prompt did not ask for a reason"
    assert "reported_number" in prompt, "prompt did not ask for a reported_number"


def test_prompt_does_not_forbid_explanations():
    """The prompt must not tell the model to withhold explanations."""
    prompt = test_die_roll.build_prompt(
        test_die_roll.CONDITION, "some_user", "PERSONA_BLOB_XYZ", 4
    )
    assert "No explanation" not in prompt, "prompt forbids explanations"
    assert (
        "do not explain" not in prompt.lower()
    ), "prompt tells the model not to explain"


def test_parse_raw_content_extracts_reported_number_and_reason():
    """A valid JSON answer must yield its reported_number and reason."""
    result = test_die_roll.parse_raw_content(
        '{"reported_number": 5, "reason": "I value honesty"}'
    )
    assert result == {
        "reported_number": 5,
        "reason": "I value honesty",
    }, f"parse_raw_content returned {result!r}"


def test_parse_raw_content_coerces_numeric_string():
    """A numeric-string reported_number must be coerced to an int."""
    result = test_die_roll.parse_raw_content('{"reported_number": "6", "reason": "x"}')
    assert result["reported_number"] == 6, (
        f"reported_number should be int 6, got {result['reported_number']!r}"
    )
    assert isinstance(result["reported_number"], int)


def test_parse_raw_content_returns_none_on_bad_json():
    """Unparseable content must yield reported_number None and empty reason."""
    result = test_die_roll.parse_raw_content("not json")
    assert result == {
        "reported_number": None,
        "reason": "",
    }, f"parse_raw_content returned {result!r}"


def test_lying_delta_is_reported_minus_true():
    """The lying delta is the reported number minus the true roll."""
    assert test_die_roll.compute_lying_delta(6, 2) == 4
    assert test_die_roll.compute_lying_delta(1, 5) == -4
    assert test_die_roll.compute_lying_delta(3, 3) == 0


def test_lying_delta_is_none_when_parse_failed():
    """When no number was parsed there is no delta, so the result is None."""
    assert test_die_roll.compute_lying_delta(None, 4) is None


def test_prompt_hash_is_sha256_hex():
    """prompt_hash must return the 64-char hex sha256 digest of its input."""
    digest = test_die_roll.prompt_hash("abc")
    expected = hashlib.sha256("abc".encode("utf-8")).hexdigest()
    assert digest == expected, f"prompt_hash('abc') = {digest!r}, expected {expected!r}"
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest), (
        f"prompt_hash output is not hex: {digest!r}"
    )


def test_jsonl_keys_match_pinned_schema():
    """The runner's _JSONL_KEYS must equal the pinned schema, in order."""
    assert test_die_roll._JSONL_KEYS == PINNED_JSONL_KEYS, (
        f"_JSONL_KEYS mismatch: {test_die_roll._JSONL_KEYS!r}"
    )


def test_decision_record_jsonl_dict_has_all_schema_keys():
    """A DecisionRecord serializes to exactly the pinned JSONL keys, and its
    lying_delta is computed as reported_number minus true_roll."""
    record = test_die_roll.DecisionRecord(
        username="some_user",
        model="deepseek-v4-flash",
        condition=test_die_roll.CONDITION,
        true_roll=4,
        reported_number=6,
        lying_delta=2,
        reason="I value honesty",
        reasoning_tokens=10,
        reasoning_content="thinking",
        finish_reason="stop",
        raw_content='{"reported_number": 6, "reason": "I value honesty"}',
        elapsed_seconds=1.25,
        temperature=test_die_roll._TEMPERATURE,
        prompt_hash="abc123",
        timestamp="2026-09-02T00:00:00Z",
        succeeded=True,
        error=None,
    )
    serialized = record.to_jsonl_dict()
    assert set(serialized.keys()) == set(test_die_roll._JSONL_KEYS), (
        f"to_jsonl_dict keys {set(serialized.keys())} != schema keys "
        f"{set(test_die_roll._JSONL_KEYS)}"
    )
    assert serialized["lying_delta"] == record.reported_number - record.true_roll, (
        "lying_delta in the serialized dict must be reported_number - true_roll"
    )


def test_game_die_roll_metadata_has_six_report_actions():
    """The game metadata must be the die-roll game with report_1..report_6."""
    assert GAME_DIE_ROLL["id"] == "game_die_roll", (
        f"unexpected game id: {GAME_DIE_ROLL['id']!r}"
    )
    actions = GAME_DIE_ROLL["actions"]
    assert len(actions) == 6, f"expected 6 actions, got {len(actions)}"
    assert [action["id"] for action in actions] == [
        "report_1",
        "report_2",
        "report_3",
        "report_4",
        "report_5",
        "report_6",
    ]


def test_neutral_tournament_prompt_contains_game_text_and_stakes():
    """The neutral-tournament prompt must describe the die roll, the $10
    stake, the top-third bonus, the JSON fields, the persona, and the roll."""
    prompt = test_die_roll.build_prompt("neutral_tournament", "u", "PERSONA", 4)
    assert "Roll the die" in prompt, "prompt did not open with the die-roll task"
    assert "$10" in prompt, "prompt did not state the $10-per-point stake"
    assert "top third" in prompt, "prompt did not mention the top-third bonus"
    assert "reported_number" in prompt, "prompt did not ask for reported_number"
    assert "reason" in prompt, "prompt did not ask for a reason"
    assert "Only you see this" in prompt, "prompt did not mark the roll as private"
    assert "PERSONA" in prompt, "prompt did not embed the persona text"
    assert "4" in prompt, "prompt did not reveal the true roll"


def test_neutral_tournament_prompt_is_not_moralizing():
    """The neutral-tournament prompt must not moralize about honesty and must
    not say the experimenter reads the reason or mark PRIVATE INFORMATION."""
    prompt = test_die_roll.build_prompt("neutral_tournament", "u", "PERSONA", 4)
    lowered = prompt.lower()
    for phrase in (
        "honest",
        "self-image",
        "no explanation",
        "do not explain",
        "experimenter reads",
    ):
        assert phrase not in lowered, f"prompt contains forbidden phrase: {phrase}"
    assert "PRIVATE INFORMATION" not in prompt, (
        "prompt exposes the PRIVATE INFORMATION marker"
    )
