# Locked tests for the conservative fold_forms policy (TASK-1578, RED
# phase; tests ONLY - no implementation lives here).
#
# WHY THESE TESTS EXIST: which token spellings count as "yes"/"no" was
# decided by a generic junk-strip (strip leading punctuation, lowercase,
# compare the label's head word) - which silently folds ambiguous
# punctuation-glue forms like "(no", "=yes" and "=no". The user ordered
# a CONSERVATIVE policy: folding becomes an EXPLICIT enumerated list of
# literal token strings (the audit's recommended default, RESULT-1576) -
# bare forms, their case variants, and pure leading-whitespace BPE
# spellings fold; punctuation glue and prefix look-alikes NEVER fold;
# and the list is extendable through config, replacing the default.
#
# All offline: pure functions over synthetic top-k lists; no network,
# no model loads. The 62 locked offline tests in the existing files stay
# green.
import inspect
import json
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

YES_NO = ("yes", "no")

# One decision-position top-k carrying every form class: the listed
# forms first (yes branch, then no branch), then the punctuation-glue
# forms that must NOT fold, then prefix look-alikes and ordinary words
# that never folded and must never start folding.
FOLD_TOP_K = [
    {"token": "yes", "logprob": -0.50},
    {"token": "Yes", "logprob": -2.00},
    {"token": "YES", "logprob": -3.00},
    {"token": " yes", "logprob": -4.00},
    {"token": "no", "logprob": -1.00},
    {"token": "No", "logprob": -2.50},
    {"token": "NO", "logprob": -3.50},
    {"token": " no", "logprob": -4.50},
    {"token": "\tno", "logprob": -10.00},
    {"token": "(no", "logprob": -7.00},
    {"token": "=yes", "logprob": -7.50},
    {"token": "=no", "logprob": -8.00},
    {"token": "not", "logprob": -6.00},
    {"token": "none", "logprob": -6.50},
    {"token": "nobody", "logprob": -7.00},
    {"token": " maybe", "logprob": -5.00},
]
LISTED_P_YES = math.exp(-0.50) + math.exp(-2.00) + math.exp(-3.00) + math.exp(-4.00)
LISTED_P_NO = (
    math.exp(-1.00)
    + math.exp(-2.50)
    + math.exp(-3.50)
    + math.exp(-4.50)
    + math.exp(-10.00)
)


def _require_parameter(function, name: str, owner: str) -> None:
    """Fail in plain language on a missing parameter (RED = feature gone)."""
    assert name in inspect.signature(function).parameters, (
        f"{owner} must accept a {name!r} parameter - this behaviour cannot "
        f"be configured without it (got: {inspect.signature(function)})"
    )


def test_the_conservative_default_folds_exactly_the_listed_yes_and_no_forms():
    """The default fold list is the audit's enumeration: bare forms, case
    variants and pure leading-whitespace forms fold; punctuation glue,
    prefix look-alikes and ordinary words never fold."""
    from logprob_scoring import purchase_branch_mass

    mass = purchase_branch_mass(FOLD_TOP_K, labels=YES_NO)
    assert mass["p_yes"] == pytest.approx(LISTED_P_YES), (
        f"only the listed yes forms (yes/Yes/YES/' yes') may count toward "
        f"p_yes; got {mass['p_yes']} - a punctuation-glue form still folds"
    )
    assert mass["p_no"] == pytest.approx(LISTED_P_NO), (
        f"only the listed no forms (no/No/NO/' no'/'\\tno') may count "
        f"toward p_no; got {mass['p_no']} - a punctuation-glue form "
        "still folds"
    )
    assert mass["matched_yes_tokens"] == ["yes", "Yes", "YES", " yes"], (
        "the matched-form lists must show exactly which literal forms "
        "folded, in top-k order"
    )
    assert mass["matched_no_tokens"] == ["no", "No", "NO", " no", "\tno"]


@pytest.mark.parametrize("glue", ["(no", "=yes", "=no"])
def test_punctuation_glue_forms_never_fold_into_either_branch(glue: str):
    """'(no', '=yes' and '=no' are ambiguous punctuation glue (they show
    up in both yes- and no-answering calls); the conservative default
    must leave every one of them unfolded."""
    from logprob_scoring import purchase_branch_mass

    mass = purchase_branch_mass([{"token": glue, "logprob": -7.0}], labels=YES_NO)
    assert mass["p_yes"] is None, (
        f"{glue!r} must not fold into the yes branch - the conservative "
        "default folds only the enumerated literal forms"
    )
    assert mass["p_no"] is None, (
        f"{glue!r} must not fold into the no branch - the conservative "
        "default folds only the enumerated literal forms"
    )
    assert mass["matched_yes_tokens"] == []
    assert mass["matched_no_tokens"] == []


def test_case_and_whitespace_variants_still_fold_under_the_conservative_default():
    """Dropping case or leading-whitespace variants would NOT be
    conservative (they are the same label word, and their mass is
    material): each listed variant class must land in its branch."""
    from logprob_scoring import purchase_branch_mass

    case = purchase_branch_mass(
        [
            {"token": "Yes", "logprob": math.log(0.02)},
            {"token": "YES", "logprob": math.log(0.01)},
            {"token": "No", "logprob": math.log(0.04)},
            {"token": "NO", "logprob": math.log(0.01)},
        ],
        labels=YES_NO,
    )
    assert case["p_yes"] == pytest.approx(0.03), (
        "the case variants Yes/YES are the same label word and must fold"
    )
    assert case["p_no"] == pytest.approx(0.05), (
        "the case variants No/NO are the same label word and must fold"
    )

    whitespace = purchase_branch_mass(
        [
            {"token": " yes", "logprob": math.log(0.30)},
            {"token": " no", "logprob": math.log(0.10)},
            {"token": "\tno", "logprob": math.log(0.02)},
        ],
        labels=YES_NO,
    )
    assert whitespace["p_yes"] == pytest.approx(0.30), (
        "the leading-space form ' yes' is the standard BPE spelling and must fold"
    )
    assert whitespace["p_no"] == pytest.approx(0.12), (
        "the leading-space and leading-tab forms ' no'/'\\tno' must fold"
    )


def test_fold_forms_are_extendable_through_config():
    """The fold lists are config, not law: a per-branch list of exact
    literal strings REPLACES the default (and threads into the scorer)."""
    from logprob_scoring import make_first_token_scorer, purchase_branch_mass

    _require_parameter(purchase_branch_mass, "fold_forms", "branch matcher")
    custom = {"yes": ["sure"], "no": ["nope", " nope"]}
    mass = purchase_branch_mass(
        [
            {"token": "sure", "logprob": -0.30},
            {"token": "yes", "logprob": -1.00},
            {"token": " nope", "logprob": -2.00},
            {"token": "nope", "logprob": -2.50},
            {"token": "no", "logprob": -3.00},
        ],
        labels=YES_NO,
        fold_forms=custom,
    )
    assert mass["p_yes"] == pytest.approx(math.exp(-0.30)), (
        "a configured fold list REPLACES the default: 'sure' counts, "
        "the default form 'yes' does not"
    )
    assert mass["matched_yes_tokens"] == ["sure"]
    assert mass["p_no"] == pytest.approx(math.exp(-2.00) + math.exp(-2.50))
    assert mass["matched_no_tokens"] == [" nope", "nope"]

    _require_parameter(make_first_token_scorer, "fold_forms", "make_first_token_scorer")
    from logprob_scoring import parse_first_token_response

    parsed = parse_first_token_response(
        json_body([(" sure", -0.30, [{"token": " sure", "logprob": -0.30}])]),
        labels=YES_NO,
        fold_forms=custom,
    )
    assert parsed["p_yes"] == pytest.approx(math.exp(-0.30)), (
        "the configured fold list must thread into the reply parser"
    )

    body = json_body([(" sure", -0.30, [{"token": " sure", "logprob": -0.30}])])
    post = _FakePost(body)
    result = _first_token_scorer(post, fold_forms=custom)(
        [{"role": "user", "content": "buy?"}]
    )
    assert result["p_yes"] == pytest.approx(math.exp(-0.30)), (
        "the configured fold list must thread into the production scorer"
    )
    assert result["matched_yes_tokens"] == [" sure"]


def json_body(positions: list) -> str:
    """One OpenAI-style reply of (chosen token, logprob, top-k) positions."""
    blocks = [
        {"token": token, "logprob": logprob, "top_logprobs": top_k}
        for token, logprob, top_k in positions
    ]
    content = "".join(token for token, _, _ in positions)
    choice = {"message": {"content": content}, "logprobs": {"content": blocks}}
    return json.dumps({"choices": [choice]})


BASE_URL, MODEL = "http://127.0.0.1:9", "vendor/model"


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple:
        self.calls.append((url, payload))
        return 200, self.body


def _first_token_scorer(post: _FakePost, **kwargs):
    """The production first_token scorer over the injected fake transport."""
    from logprob_scoring import make_first_token_scorer

    return make_first_token_scorer(BASE_URL, MODEL, post=post, labels=YES_NO, **kwargs)
