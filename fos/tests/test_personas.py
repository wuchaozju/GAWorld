# Contract tests for `fos.experiments.personas`, the persona generation kit
# of the Gui & Toubia (2025) unblinding study (Web Appendix D). After the
# paper-fidelity drift fix (TASK-1483) the elicitation prompt is paper
# Prompt 10 VERBATIM: it opens "You are a consumer with the following
# characteristics:", lists the 11 Title-Case demographic fill-ins, and ends
# with the purchase question — it never asks the model to invent behavioural
# scores, and its system line is the paper Prompt 2/10 customer line. The
# depth axis has exactly the two paper levels {1, 2} (none = bare survey,
# demographics = the 11 fields); the model-invented behavioural tiers of the
# pre-drift five-tier ladder are gone. The tests for the bundled census file
# data/configs/census_marginals_us_approx.json skip (pytest.skip) while that
# file is missing, so they stay independent of the module state.
#
# Coverage per spec item (see the test classes below for the details):
#   1. PERSONA_FIELDS — 11 paper fields in order.
#   2. build_persona_elicitation_prompt() — paper Prompt 10: consumer opener,
#      the 11 Title-Case demographic fill-in labels in order, category/store
#      paragraphs after the block, the store price left as a blank, and the
#      purchase question as the final field; no outcome-selecting opener, no
#      WTP slot, no invented behavioural-score blanks.
#   3. parse_persona(raw) — the 11 keys, int casts, $/comma stripping,
#      wrapper/preamble tolerance, None when a field is missing.
#   4. generate_personas(...) — exactly n chat_fn calls, (personas, skipped),
#      deterministic per seed, and the paper Prompt 2/10 system line (the
#      old "market study" system is drift and must be gone).
#   5. render_demographics_block(persona) — 11 "Field: value" lines in order.
#   6. BEHAVIORAL_MEASURES — the five paper Appendix E panel measures as
#      NAMES only. The pre-drift kit rendered model-INVENTED score/percentile
#      blanks for them (render_extended_block); that invented-score rendering
#      is drift and must be gone — an extended-block entry point is removed
#      outright or must refuse the removed behavioural tiers, and no
#      demographics rendering may ever emit a measure or a percentile.
#   6b. render_persona_fields(persona, depth) — the depth renderer over the
#      two paper levels: none renders nothing, demographics renders the 11
#      canonical fields, partial persona dicts render without KeyError (the
#      TASK-1456 behavior), and the removed behavioural tiers raise
#      ValueError. The renderer may be removed outright (test_paper_fidelity
#      allows it) — those tests then skip.
#   7. check_persona_diversity(personas) — the five diversity stats.
#   8. check_persona_coherence(personas) — violations/rates/examples over the
#      five paper rules (names pinned below).
#   9. compare_to_census(...) + load_census_marginals(path=None).
#  10. scripts/generate_personas.py — main(argv=None), __main__ guard, the
#      eight flags with defaults, socket-free import, --help exits 0.
#
# API assumptions pinned by this file (documented for the implement agent):
#   * Coherence "rates" keys: age_range, children_capacity,
#     income_nonnegative, retirement_age, household_size_min.
#   * "n_violations" counts events (a persona breaking two rules counts
#     twice); "examples" lists each violating persona dict once.
#   * "distinct_ratio" is (unique - 1) / (n - 1).
#   * compare_to_census "gap" is sample mean - census mean (numeric) or the
#     total-variation distance 0.5 * sum(|sample - census|) (shares);
#     "sample" is the sample mean or sample share dict.
#   * The CLI script exposes _parse_args(argv=None) -> argparse.Namespace
#     (same seam test_persona_depth.py pins on unblinding_sweep.py).


import importlib.util
import inspect
import re
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_personas.py"
CENSUS_PATH = REPO_ROOT / "data" / "configs" / "census_marginals_us_approx.json"

EXPECTED_FIELDS = [
    "age",
    "gender",
    "education",
    "household_income",
    "occupation",
    "ethnicity",
    "marital_status",
    "household_size",
    "number_of_children",
    "state",
    "home_ownership",
]

# The five behavioral measures of the paper's Appendix E measured panel
# (Twin-2K-500). After the drift fix these are NAMES ONLY: the persona
# elicitation prompt must never ask the model to invent their scores or
# percentiles (pinned in the prompt tests below). The list itself may stay
# as the canonical Appendix E covariate names.
EXPECTED_MEASURES = [
    "tightwad_spendthrift",
    "discount_rate",
    "present_bias",
    "risk_aversion",
    "loss_aversion",
]

# The paper's verbatim Prompt 2 / Prompt 10 system line (RESULT-1474 §1):
# the customer fills in the blanks and returns comma-separated values.
# generate_personas must send exactly this line as the system message.
PROMPT2_SYSTEM = (
    "You, AI, are a customer. Your task is to fill in the blanks. "
    "Return the completed information in comma-separated values, without any "
    "extra text."
)

# The 11 Appendix D demographic labels, verbatim order (Prompt 10). The
# elicitation prompt must carry them as "<Label>:" fill-in lines right after
# the consumer opener.
PROMPT10_LABELS = [
    "Age", "Gender", "Education level", "Household income", "Occupation",
    "Ethnicity", "Marital status", "Household size", "Number of children",
    "State of residence", "Home ownership",
]

# The two paper persona depth levels, shallowest first. Each level's
# rendered field set adds the level's own fields on top of the level below.
DEPTHS = ["none", "demographics"]

# The field names render_persona_fields must show per depth for a persona
# that carries every canonical demographic field. The levels are strictly
# nested: demographics adds the 11 canonical fields to "none". The
# behavioural tiers of the pre-drift five-tier ladder (tightwad/
# time_preference/risk_preference) are gone and must be rejected.
DEPTH_FIELD_SETS = {
    "none": set(),
    "demographics": set(EXPECTED_FIELDS),
}

# One canned, fully-formed eleven-field answer the fake chat returns.
_CANNED_RAW = "\n".join(
    [
        "age: 35",
        "gender: female",
        "education: college",
        "household_income: $86,500",
        "occupation: teacher",
        "ethnicity: white",
        "marital_status: married",
        "household_size: 4",
        "number_of_children: 2",
        "state: CA",
        "home_ownership: own",
    ]
)

# The dict parse_persona(_CANNED_RAW) must produce.
_CANNED_PERSONA = {
    "age": 35,
    "gender": "female",
    "education": "college",
    "household_income": 86500,
    "occupation": "teacher",
    "ethnicity": "white",
    "marital_status": "married",
    "household_size": 4,
    "number_of_children": 2,
    "state": "CA",
    "home_ownership": "own",
}


def _personas_module():
    """Return the fos.experiments.personas module (imported per test).

    The module does not exist yet, so a top-level import would kill the whole
    file at collection time. Importing it per test lets each test fail on its
    own with the same ModuleNotFoundError and keeps the census skip tests
    independent of the module import.
    """
    from fos.experiments import personas  # noqa: PLC0415

    return personas


def _persona(**overrides):
    """One valid eleven-field persona dict; overrides win per key."""
    base = {
        "age": 35,
        "gender": "female",
        "education": "college",
        "household_income": 86500,
        "occupation": "teacher",
        "ethnicity": "white",
        "marital_status": "married",
        "household_size": 4,
        "number_of_children": 2,
        "state": "CA",
        "home_ownership": "own",
    }
    base.update(overrides)
    return base


def _full_persona(**overrides):
    """A persona that still carries the five behavioural measure dicts.

    Legacy shape: on-disk persona pools from the pre-drift five-tier runs can
    contain "name": {"score", "percentile"} entries. The paper-fidelity fix
    must make sure NO renderer draws those model-invented scores — these
    fixtures prove the demographics renderer ignores the entries and that no
    extended-block entry point may draw them.
    """
    persona = _persona(
        age=60,
        occupation="retired professor",
        household_income=42000,
        household_size=2,
        number_of_children=0,
    )
    persona.update(
        {
            "tightwad_spendthrift": {"score": 42, "percentile": 18},
            "discount_rate": {"score": 6.2, "percentile": 71},
            "present_bias": {"score": 33, "percentile": 9},
            "risk_aversion": {"score": 7.5, "percentile": 88},
            "loss_aversion": {"score": 4.0, "percentile": 62},
        }
    )
    persona.update(overrides)
    return persona


def _render_persona_fields(persona, depth):
    """Run the depth renderer, or skip when the implementation removed it.

    test_paper_fidelity allows render_persona_fields to be removed outright
    (nothing could then draw the removed behavioural tiers), so these tests
    skip in that implementation instead of erroring on a missing attribute.
    """
    render = getattr(_personas_module(), "render_persona_fields", None)
    if render is None:
        pytest.skip("render_persona_fields was removed outright")
    return render(persona, depth)


class _FakeChat:
    """Injected chat function: records every call, never touches a network.

    Answers are drawn from a list that cycles, so a run is fully reproducible
    for the same call sequence. Each call is stored as (messages, temperature)
    so tests can inspect what was sent.
    """

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, messages, temperature):
        self.calls.append((messages, temperature))
        return self.answers[len(self.calls) % len(self.answers)]


# 1. PERSONA_FIELDS


class TestPersonaFields:
    def test_persona_fields_lists_all_eleven_paper_fields_in_order(self):
        assert _personas_module().PERSONA_FIELDS == EXPECTED_FIELDS

    def test_persona_fields_holds_unique_strings(self):
        fields = _personas_module().PERSONA_FIELDS
        assert len(fields) == len(set(fields))
        assert all(isinstance(field, str) for field in fields)


# 2. build_persona_elicitation_prompt() — paper Prompt 10 (Web Appendix D)


class TestBuildPersonaElicitationPrompt:
    """The elicitation prompt is paper Prompt 10 verbatim.

    It opens with the neutral consumer self-description, lists the 11
    Title-Case demographic fill-in labels right after it, then the category /
    store paragraphs, the store price left as a blank, and ends with the
    purchase question. The pre-drift outcome-selecting opener, the WTP slot,
    and the model-invented behavioural-score blanks must appear nowhere.
    """

    _CATEGORY = "Soft Drinks - Carbonated"
    _PRODUCT = "Coca-Cola Soda Pop, 12 fl oz, 12 Pack Cans"

    def _prompt_lines(self):
        prompt = _personas_module().build_persona_elicitation_prompt(
            self._CATEGORY, self._PRODUCT
        )
        return [line.strip() for line in prompt.splitlines() if line.strip()]

    def test_prompt_names_the_category_and_the_product(self):
        prompt = _personas_module().build_persona_elicitation_prompt(
            self._CATEGORY, self._PRODUCT
        )
        assert self._CATEGORY in prompt
        assert self._PRODUCT in prompt

    def test_prompt_opens_with_the_paper_consumer_line(self):
        first = self._prompt_lines()[0]
        assert first == "You are a consumer with the following characteristics:", (
            f"persona prompt must open with the paper's consumer line, got {first!r}"
        )

    def test_demographic_block_is_the_11_paper_fields_in_order(self):
        lines = self._prompt_lines()
        block = lines[1:12]
        assert len(block) == 11, (
            f"demographic block must have 11 fill-in lines, got {len(block)}"
        )
        for label, line in zip(PROMPT10_LABELS, block):
            assert line.startswith(f"{label}:"), (
                f"expected '{label}:' as a fill-in line, got {line!r}"
            )

    def test_category_and_store_paragraphs_follow_the_demographic_block(self):
        lines = self._prompt_lines()
        category_index = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("Please consider the following product category:")
        )
        assert category_index > 11, (
            "the category line must come after the 11 demographic fill-ins"
        )
        store_index = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("Suppose you are in a grocery store")
        )
        assert store_index > category_index

    def test_prompt_leaves_the_store_price_as_a_blank_not_a_wtp_slot(self):
        # The paper persona step leaves the current store price unfilled (no
        # price prior); the pre-drift "Price this person would pay" WTP slot
        # is a counterfactual and must be gone.
        prompt = _personas_module().build_persona_elicitation_prompt(
            self._CATEGORY, self._PRODUCT
        )
        assert "The product is currently priced at" in prompt
        assert "[a number with up to 2 decimal points]" in prompt
        assert "Price this person would pay" not in prompt

    def test_prompt_ends_with_the_purchase_question_as_the_final_field(self):
        lines = self._prompt_lines()
        purchase_lines = [
            i
            for i, line in enumerate(lines)
            if line.startswith("Would you or would you not purchase")
        ]
        assert purchase_lines, "persona prompt must ask the purchase question"
        purchase_index = purchase_lines[-1]
        assert '["purchase" or "not purchase"]' in lines[purchase_index]
        price_index = next(
            i
            for i, line in enumerate(lines)
            if line.startswith("The product is currently priced at")
        )
        assert price_index < purchase_index, (
            "the store price line must precede the purchase question"
        )
        tail = lines[purchase_index + 1 :]
        assert len(tail) <= 1 and (not tail or tail[0].startswith("Return example")), (
            f"nothing but an optional Return example may follow the purchase "
            f"question, got {tail!r}"
        )

    def test_no_old_outcome_selecting_or_wtp_drift_text(self):
        prompt = _personas_module().build_persona_elicitation_prompt(
            self._CATEGORY, self._PRODUCT
        )
        for drifted in (
            "Write the profile of a person who would buy this product",
            "Price this person would pay",
            "Reply with the completed template below in a single message",
        ):
            assert drifted not in prompt, f"drift text still present: {drifted!r}"

    def test_prompt_never_asks_the_model_to_invent_behavioural_scores(self):
        prompt = _personas_module().build_persona_elicitation_prompt(
            self._CATEGORY, self._PRODUCT
        )
        for measure in EXPECTED_MEASURES:
            assert measure not in prompt, (
                f"model-invented measure blank still asked: {measure!r}"
            )
        assert "percentile" not in prompt, "score/percentile blanks must be gone"


# 3. parse_persona()


class TestParsePersona:
    def test_parse_persona_reads_a_canned_eleven_field_answer(self):
        parsed = _personas_module().parse_persona(_CANNED_RAW)
        assert parsed == _CANNED_PERSONA

    def test_parse_persona_returns_exactly_the_eleven_persona_keys(self):
        parsed = _personas_module().parse_persona(_CANNED_RAW)
        assert set(parsed) == set(_personas_module().PERSONA_FIELDS)

    def test_parse_persona_int_casts_the_numeric_fields(self):
        parsed = _personas_module().parse_persona(_CANNED_RAW)
        assert parsed["age"] == 35 and isinstance(parsed["age"], int)
        assert parsed["household_size"] == 4 and isinstance(
            parsed["household_size"], int
        )
        assert parsed["number_of_children"] == 2 and isinstance(
            parsed["number_of_children"], int
        )
        assert parsed["household_income"] == 86500 and isinstance(
            parsed["household_income"], int
        )

    def test_parse_persona_keeps_the_text_fields_as_strings(self):
        parsed = _personas_module().parse_persona(_CANNED_RAW)
        for field in (
            "gender",
            "education",
            "occupation",
            "ethnicity",
            "marital_status",
            "state",
            "home_ownership",
        ):
            assert isinstance(parsed[field], str), field

    def test_parse_persona_strips_dollar_signs_and_commas_from_income(self):
        raw = _CANNED_RAW.replace("$86,500", "$45,000")
        parsed = _personas_module().parse_persona(raw)
        assert parsed["household_income"] == 45000

    def test_parse_persona_tolerates_a_reasoning_channel_wrapper(self):
        raw = "<|channel>the respondent is a teacher\n<channel|>" + _CANNED_RAW
        parsed = _personas_module().parse_persona(raw)
        assert parsed == _CANNED_PERSONA

    def test_parse_persona_tolerates_special_token_tails(self):
        raw = _CANNED_RAW + "\n<|im_end|>\n<|im_start|>system\nYou are a"
        parsed = _personas_module().parse_persona(raw)
        assert parsed == _CANNED_PERSONA

    def test_parse_persona_ignores_preamble_lines_before_the_answer(self):
        raw = "Here is the completed persona profile.\n" + _CANNED_RAW
        parsed = _personas_module().parse_persona(raw)
        assert parsed == _CANNED_PERSONA

    def test_parse_persona_returns_none_when_any_field_is_missing(self):
        missing = _CANNED_RAW.replace("state: CA\n", "")
        assert _personas_module().parse_persona(missing) is None
        assert _personas_module().parse_persona("not a persona at all") is None
        assert _personas_module().parse_persona("") is None


# 4. generate_personas()


class TestGeneratePersonas:
    def test_generate_personas_signature_matches_the_contract(self):
        params = inspect.signature(_personas_module().generate_personas).parameters
        assert list(params)[:4] == ["category", "product", "n", "chat_fn"]
        assert params["temperature"].default == 1.0
        assert params["seed"].default is None

    def test_generate_personas_calls_chat_exactly_n_times(self):
        chat = _FakeChat([_CANNED_RAW] * 3)
        personas, skipped = _personas_module().generate_personas(
            "Snacks", "Chips", 3, chat
        )
        assert len(chat.calls) == 3
        assert skipped == 0
        assert personas == [_CANNED_PERSONA] * 3

    def test_generate_personas_returns_a_personas_and_skipped_tuple(self):
        chat = _FakeChat([_CANNED_RAW])
        result = _personas_module().generate_personas("Snacks", "Chips", 2, chat)
        assert isinstance(result, tuple) and len(result) == 2
        personas, skipped = result
        assert isinstance(personas, list)
        assert isinstance(skipped, int)

    def test_generate_personas_counts_unparseable_answers_as_skipped(self):
        chat = _FakeChat([_CANNED_RAW, "I refuse to answer.", _CANNED_RAW])
        personas, skipped = _personas_module().generate_personas(
            "Snacks", "Chips", 3, chat
        )
        assert len(chat.calls) == 3
        assert skipped == 1
        assert personas == [_CANNED_PERSONA, _CANNED_PERSONA]

    def test_generate_personas_sends_a_prompt_that_names_the_product(self):
        chat = _FakeChat([_CANNED_RAW])
        _personas_module().generate_personas(
            "Snacks", "Lay's Classic Potato Chips", 1, chat
        )
        assert chat.calls
        prompt = " ".join(m["content"] for m in chat.calls[0][0])
        assert "Lay's Classic Potato Chips" in prompt

    def test_generate_personas_sends_the_paper_customer_system_line(self):
        # The pre-drift "market study" system line is drift; generate_personas
        # must use the paper Prompt 2 / Prompt 10 customer system line.
        chat = _FakeChat([_CANNED_RAW])
        _personas_module().generate_personas("Snacks", "Chips", 1, chat)
        assert chat.calls
        system = chat.calls[0][0][0]["content"]
        assert system == PROMPT2_SYSTEM, (
            f"persona generation system must be the paper Prompt 2/10 system "
            f"line, got {system!r}"
        )
        assert "market study" not in system

    def test_generate_personas_forwards_the_temperature_to_chat(self):
        chat = _FakeChat([_CANNED_RAW])
        _personas_module().generate_personas(
            "Snacks", "Chips", 2, chat, temperature=0.8
        )
        assert chat.calls
        assert {t for _messages, t in chat.calls} == {0.8}

    def test_generate_personas_defaults_temperature_to_one(self):
        chat = _FakeChat([_CANNED_RAW])
        _personas_module().generate_personas("Snacks", "Chips", 2, chat)
        assert chat.calls
        assert {t for _messages, t in chat.calls} == {1.0}

    def test_generate_personas_is_deterministic_for_the_same_seed(self):
        answers = [_CANNED_RAW, _CANNED_RAW.replace("teacher", "nurse")]
        first, _ = _personas_module().generate_personas(
            "Snacks", "Chips", 4, _FakeChat(answers), seed=42
        )
        second, _ = _personas_module().generate_personas(
            "Snacks", "Chips", 4, _FakeChat(answers), seed=42
        )
        assert first == second

    def test_generate_personas_with_zero_n_makes_no_calls(self):
        chat = _FakeChat([_CANNED_RAW])
        personas, skipped = _personas_module().generate_personas(
            "Snacks", "Chips", 0, chat
        )
        assert chat.calls == []
        assert personas == []
        assert skipped == 0


# 5. render_demographics_block()


class TestRenderDemographicsBlock:
    def test_render_demographics_block_emits_one_line_per_field_in_order(self):
        persona = _persona()
        expected = [
            f"{field}: {persona[field]}" for field in _personas_module().PERSONA_FIELDS
        ]
        rendered = _personas_module().render_demographics_block(persona)
        assert rendered.splitlines() == expected

    def test_render_demographics_block_reflects_the_persona_values(self):
        persona = _persona(age=71, state="TX", household_income=120000)
        rendered = _personas_module().render_demographics_block(persona)
        assert "age: 71" in rendered
        assert "state: TX" in rendered
        assert "household_income: 120000" in rendered


# 6. BEHAVIORAL_MEASURES (names only) — the invented-score rendering is gone


class TestBehavioralMeasures:
    def test_behavioral_measures_lists_the_five_paper_measures(self):
        assert _personas_module().BEHAVIORAL_MEASURES == EXPECTED_MEASURES

    def test_behavioral_measures_names_are_unique_strings(self):
        measures = _personas_module().BEHAVIORAL_MEASURES
        assert len(measures) == len(set(measures))
        assert all(isinstance(name, str) and name for name in measures)


class TestNoInventedBehaviouralScoreRendering:
    """The model-invented behavioural-score block (drift row 3) is gone.

    The pre-drift kit rendered "name: score (P<pct> percentile)" lines for
    five model-invented measures through render_extended_block. After the fix
    only the two paper depth levels exist: the demographics renderer must
    never emit a measure or a percentile even when the persona dict still
    carries legacy measure entries, and an extended-block entry point must
    be removed outright or must refuse the removed behavioural tiers.
    """

    def test_demographics_rendering_never_emits_measures_or_percentiles(self):
        render = getattr(_personas_module(), "render_demographics_block", None)
        if render is None:
            return  # no demographics renderer left - nothing can draw measures
        rendered = render(_full_persona())
        assert "percentile" not in rendered
        for measure in EXPECTED_MEASURES:
            assert measure not in rendered, (
                f"demographics renderer must not draw measure {measure!r}"
            )

    def test_extended_block_entry_point_is_gone_or_rejects_removed_tiers(self):
        extended = getattr(_personas_module(), "render_extended_block", None)
        if extended is None:
            return  # removed outright - nothing can draw invented scores
        # The extended block rendered the risk_preference tier, which no
        # longer exists; rendering it must fail loudly, never invent scores.
        with pytest.raises(ValueError):
            extended(_full_persona())


# 6b. render_persona_fields(persona, depth) — the two-level depth rendering


def _rendered_field_names(rendered: str) -> set[str]:
    """Return the field names that head a "name: value" line in a block.

    Notes (lines starting "<note:") and prose never count, so the result is
    exactly the persona fields the renderer chose to show.
    """
    names: set[str] = set()
    for line in rendered.splitlines():
        name, separator, _ = line.partition(":")
        name = name.strip()
        if separator and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            names.add(name)
    return names


class TestRenderPersonaFields:
    """The depth renderer over the two paper levels {1, 2}.

    render_persona_fields(persona, depth) renders the SAME persona dict at
    one of the two levels: "none" renders nothing and "demographics" adds
    the 11 canonical fields, so the rendered field sets nest strictly.
    Partial personas keep the TASK-1456 tolerance: missing keys are skipped,
    never KeyError. The removed behavioural tiers of the five-tier ladder
    raise ValueError. The renderer may be removed outright
    (test_paper_fidelity allows it) — those tests then skip.
    """

    def test_none_depth_renders_no_fields(self):
        rendered = _render_persona_fields(_persona(), "none")
        assert rendered == ""
        assert _rendered_field_names(rendered) == set()

    def test_demographics_depth_renders_exactly_the_eleven_canonical_fields(self):
        rendered = _render_persona_fields(_persona(), "demographics")
        assert _rendered_field_names(rendered) == DEPTH_FIELD_SETS["demographics"]
        persona = _persona()
        assert rendered.splitlines() == [
            f"{field}: {persona[field]}"
            for field in _personas_module().PERSONA_FIELDS
        ]

    def test_rendered_field_sets_nest_strictly_across_the_two_levels(self):
        sets = [
            _rendered_field_names(_render_persona_fields(_persona(), depth))
            for depth in DEPTHS
        ]
        assert sets[0] < sets[1], "rendered field sets must nest strictly"

    def test_render_persona_fields_rejects_an_unknown_or_removed_depth(self):
        # "extended" was the superseded third tier, and the behavioural tiers
        # of the five-tier ladder are removed; none of them may render.
        for depth in (
            "extended",
            "deep",
            "occluded",
            "tightwad",
            "time_preference",
            "risk_preference",
        ):
            with pytest.raises(ValueError):
                _render_persona_fields(_persona(), depth)

    def test_partial_persona_renders_without_keyerror_at_every_depth(self):
        # TASK-1456 behavior: a dict missing most fields still renders the
        # fields it carries — the canonical ones it has plus extra scalar keys
        # such as city — and never raises KeyError, at any level. Measure
        # dicts the persona carries are legacy entries and never appear.
        partial = {
            "age": 35,
            "occupation": "teacher",
            "city": "Hangzhou",
            "tightwad_spendthrift": {"score": 42, "percentile": 18},
        }
        for depth in DEPTHS:
            rendered = _render_persona_fields(partial, depth)
            names = _rendered_field_names(rendered)
            if depth == "none":
                assert names == set()
                continue
            assert names == {"age", "occupation", "city"}, depth


# 7. check_persona_diversity()


class TestCheckPersonaDiversity:
    def test_identical_personas_report_zero_distinctness(self):
        result = _personas_module().check_persona_diversity([_persona()] * 500)
        assert set(result) == {
            "n",
            "unique",
            "top_repeat_count",
            "top_repeat_share",
            "distinct_ratio",
        }
        assert result["n"] == 500
        assert result["unique"] == 1
        assert result["top_repeat_count"] == 500
        assert result["top_repeat_share"] == pytest.approx(1.0)
        assert result["distinct_ratio"] == pytest.approx(0.0)

    def test_all_distinct_personas_report_full_distinctness(self):
        personas = [_persona(age=age) for age in range(20, 520)]
        result = _personas_module().check_persona_diversity(personas)
        assert result["n"] == 500
        assert result["unique"] == 500
        assert result["top_repeat_count"] == 1
        assert result["top_repeat_share"] == pytest.approx(1 / 500)
        assert result["distinct_ratio"] == pytest.approx(1.0)

    def test_diversity_report_breaks_ties_by_exact_dict_content(self):
        personas = [_persona()] * 3 + [_persona(age=44)] * 2 + [_persona(age=55)]
        result = _personas_module().check_persona_diversity(personas)
        assert result["n"] == 6
        assert result["unique"] == 3
        assert result["top_repeat_count"] == 3
        assert result["top_repeat_share"] == pytest.approx(0.5)
        assert result["distinct_ratio"] == pytest.approx(0.4)


# 8. check_persona_coherence()


COHERENCE_RULES = {
    "age_range",
    "children_capacity",
    "income_nonnegative",
    "retirement_age",
    "household_size_min",
}


class TestCheckPersonaCoherence:
    def test_clean_personas_report_no_violations(self):
        personas = [
            _persona(),
            _persona(age=18, household_size=1, number_of_children=0),
        ]
        result = _personas_module().check_persona_coherence(personas)
        assert set(result) == {"n_violations", "rates", "examples"}
        assert result["n_violations"] == 0
        assert set(result["rates"]) == COHERENCE_RULES
        assert all(rate == 0.0 for rate in result["rates"].values())
        assert result["examples"] == []

    def test_age_outside_the_paper_range_is_a_violation(self):
        personas = [_persona(), _persona(age=17)]
        result = _personas_module().check_persona_coherence(personas)
        assert result["rates"]["age_range"] == pytest.approx(0.5)

    def test_too_many_children_for_the_household_is_a_violation(self):
        personas = [_persona(), _persona(household_size=1, number_of_children=1)]
        result = _personas_module().check_persona_coherence(personas)
        assert result["rates"]["children_capacity"] == pytest.approx(0.5)

    def test_negative_income_is_a_violation(self):
        personas = [_persona(), _persona(household_income=-5)]
        result = _personas_module().check_persona_coherence(personas)
        assert result["rates"]["income_nonnegative"] == pytest.approx(0.5)

    def test_retired_occupation_below_age_fifty_is_a_violation(self):
        personas = [_persona(), _persona(age=40, occupation="Retired Teacher")]
        result = _personas_module().check_persona_coherence(personas)
        assert result["rates"]["retirement_age"] == pytest.approx(0.5)

    def test_empty_household_is_a_violation(self):
        personas = [_persona(), _persona(household_size=0)]
        result = _personas_module().check_persona_coherence(personas)
        assert result["rates"]["household_size_min"] == pytest.approx(0.5)

    def test_n_violations_counts_events_and_examples_list_offenders_once(self):
        double_offender = _persona(age=17, household_income=-5)
        result = _personas_module().check_persona_coherence(
            [_persona(), double_offender]
        )
        assert result["n_violations"] == 2
        assert len(result["examples"]) == 1
        assert result["examples"] == [double_offender]

    def test_boundary_values_are_not_violations(self):
        personas = [
            _persona(age=18),
            _persona(age=100),
            _persona(household_income=0),
            _persona(household_size=1, number_of_children=0),
            _persona(age=60, occupation="retired nurse"),
        ]
        result = _personas_module().check_persona_coherence(personas)
        assert result["n_violations"] == 0


# 9. compare_to_census() and load_census_marginals()


class TestCompareToCensus:
    def test_numeric_fields_report_mean_gap(self):
        personas = [
            _persona(age=20),
            _persona(age=30),
            _persona(age=40),
            _persona(age=50),
        ]
        result = _personas_module().compare_to_census(personas, {"age": {"mean": 60}})
        assert set(result) == {"age"}
        assert result["age"]["sample"] == pytest.approx(35.0)
        assert result["age"]["census"] == pytest.approx(60.0)
        assert result["age"]["gap"] == pytest.approx(-25.0)

    def test_categorical_fields_report_total_variation_distance(self):
        personas = [
            _persona(gender="female"),
            _persona(gender="female"),
            _persona(gender="female"),
            _persona(gender="male"),
        ]
        marginals = {"gender": {"shares": {"female": 0.52, "male": 0.48}}}
        result = _personas_module().compare_to_census(personas, marginals)
        assert set(result) == {"gender"}
        assert result["gender"]["sample"] == pytest.approx(
            {"female": 0.75, "male": 0.25}
        )
        assert result["gender"]["census"] == marginals["gender"]["shares"]
        tv = 0.5 * (abs(0.75 - 0.52) + abs(0.25 - 0.48))
        assert result["gender"]["gap"] == pytest.approx(tv)

    def test_result_has_exactly_the_fields_given_in_marginals(self):
        personas = [_persona(age=30), _persona(age=50)]
        marginals = {"age": {"mean": 40}, "state": {"shares": {"CA": 0.5, "TX": 0.5}}}
        result = _personas_module().compare_to_census(personas, marginals)
        assert set(result) == {"age", "state"}


class TestLoadCensusMarginals:
    def test_load_census_marginals_reads_the_bundled_file_when_it_exists(self):
        if not CENSUS_PATH.exists():
            pytest.skip(
                "census_marginals_us_approx.json is created by the implement task"
            )
        loaded = _personas_module().load_census_marginals()
        for field in (
            "age",
            "gender",
            "education",
            "household_income",
            "state",
            "home_ownership",
        ):
            assert field in loaded, f"bundled census file lacks {field!r}"
            entry = loaded[field]
            assert "mean" in entry or "shares" in entry, field

    def test_load_census_marginals_accepts_an_explicit_path(self, tmp_path):
        payload = {"age": {"mean": 42.0}, "gender": {"shares": {"female": 0.5}}}
        census_file = tmp_path / "census.json"
        census_file.write_text(
            '{"age": {"mean": 42.0}, "gender": {"shares": {"female": 0.5}}}'
        )
        loaded = _personas_module().load_census_marginals(census_file)
        assert loaded == payload


# 10. scripts/generate_personas.py


def _load_personas_script():
    """Import scripts/generate_personas.py by file path (no package import)."""
    spec = importlib.util.spec_from_file_location("generate_personas", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"no loader for {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module.__name__, None)
    return module


class TestGeneratePersonasScript:
    def test_script_defines_main_behind_a_main_guard(self):
        module = _load_personas_script()
        assert callable(module.main)
        assert "argv" in inspect.signature(module.main).parameters
        assert inspect.signature(module.main).parameters["argv"].default is None
        assert 'if __name__ == "__main__":' in SCRIPT_PATH.read_text()

    def test_importing_the_script_never_opens_a_socket(self):
        def _forbid_socket(*_args, **_kwargs):
            raise AssertionError("importing generate_personas must not open a socket")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(socket, "socket", _forbid_socket)
        try:
            module = _load_personas_script()
        finally:
            monkeypatch.undo()
        assert callable(module.main)

    def test_script_help_exits_zero_and_lists_every_option(self, capsys):
        module = _load_personas_script()
        with pytest.raises(SystemExit) as excinfo:
            module.main(["--help"])
        assert excinfo.value.code == 0
        help_text = capsys.readouterr().out
        for option in (
            "--category",
            "--product",
            "--n",
            "--out",
            "--model",
            "--base-url",
            "--temperature",
            "--seed",
        ):
            assert option in help_text, f"missing option {option} in --help"

    def test_parser_applies_the_documented_defaults(self):
        module = _load_personas_script()
        args = module._parse_args(["--category", "Snacks", "--product", "Chips"])
        assert args.category == "Snacks"
        assert args.product == "Chips"
        assert args.n == 500
        assert args.out == "results/personas"
        assert args.base_url == "http://127.0.0.1:8080"
        assert args.temperature == 1.0
        assert args.seed is None

    def test_parser_reads_every_explicit_option(self):
        module = _load_personas_script()
        args = module._parse_args(
            [
                "--category",
                "Soft Drinks - Carbonated",
                "--product",
                "Coca-Cola",
                "--n",
                "3",
                "--out",
                "results/pilot",
                "--model",
                "qwen3-8b",
                "--base-url",
                "http://localhost:1234/v1",
                "--temperature",
                "0.8",
                "--seed",
                "7",
            ]
        )
        assert args.category == "Soft Drinks - Carbonated"
        assert args.product == "Coca-Cola"
        assert args.n == 3
        assert args.out == "results/pilot"
        assert args.model == "qwen3-8b"
        assert args.base_url == "http://localhost:1234/v1"
        assert args.temperature == 0.8
        assert args.seed == 7
