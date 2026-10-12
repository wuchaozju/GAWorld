# Contract tests for the CSV answer format of
# fos.experiments.personas.parse_persona, the prompt-10 conformance fix.
#
# WHY THESE TESTS EXIST: the persona elicitation prompt is paper Prompt 10
# VERBATIM (Gui & Toubia 2025, Web Appendix D). Its system line tells the
# customer to "Return the completed information in comma-separated values",
# and its own "Return example" shows the exact CSV shape. A real model
# answers exactly that way — the TASK-1517 smoke (nemotron Q8, 4/4 draws)
# produced lines like
#     "42, female, master's degree, 62000, marketing manager, Hispanic,
#      single, 4, 2, TX, rent, 4.99, purchase"
# — yet parse_persona rejected every one of them, because it only read
# lines labelled with the INTERNAL underscore keys ("household_income:",
# "marital_status:", ...) that no instruction in the prompt ever asks for.
# The parser's canned fixture (tests/test_personas.py _CANNED_RAW) used
# exactly that key shape, so the tests passed while real persona pools
# could not be generated (every draw counted as "skipped").
#
# THE CORRECT BEHAVIOUR THESE TESTS PIN (TASK-1520):
#   1. A CSV answer line whose fields are the 11 Appendix-D demographics in
#      Prompt 10's order parses into the persona dict — all 11 fields
#      captured, with the correct types (age, household income, household
#      size, number of children as int; the rest as strings).
#   2. Both canonical smoke shapes from RESULT-1517 parse (transcribed
#      verbatim below).
#   3. Extra trailing fields (the prompt's purchase answer, the store price,
#      anything else after the 11th demographic) are ignored — the first
#      11 fields win, and no extra keys appear.
#   4. Invalid answers — too few fields, a non-numeric whole-number field,
#      plain prose — return None, never a crash.
#   5. The OLD underscore-key "field: value" format keeps parsing: the fix
#      ADDS CSV support without breaking the format the existing
#      TestParsePersona tests (tests/test_personas.py) pin. Those existing
#      tests are untouched and must keep passing unchanged.
#
# Provenance of the pinned lines:
#   * SMOKE_RAW_ONE / SMOKE_RAW_TWO — verbatim model answers quoted in
#     RESULT-1517 (implement OUTBOX) §"The blocker" and LAUNCH-READY.md
#     (the same evidence file, straight ASCII apostrophes as quoted).
#   * RETURN_EXAMPLE_LINE — the prompt's own "Return example" line, which
#     build_persona_elicitation_prompt emits verbatim (ASCII in the source);
#     note the paper's no-space "Asian,married" quirk (RESULT-1474 §Prompt
#     10), preserved in the module's prompt and here.

from fos.experiments import personas

# The paper-verbatim Prompt 2 / Prompt 10 system line (from test_personas.py
# PROMPT2_SYSTEM): the model is asked to answer in CSV with no extra text.
# The pinned lines below are the FULL model answers (not the labels).

# --- Canonical answer shapes (provenance-commented) ---------------------

# Verbatim from RESULT-1517 §The blocker (nemotron Q8 smoke, draw 1 of the
# 4/4 compliant draws) and LAUNCH-READY.md:
# 11 demographics in Prompt 10 order (age, gender, education, household
# income, occupation, ethnicity, marital status, household size, number of
# children, state, home ownership), then the price and the purchase answer
# as trailing fields that must be ignored.
SMOKE_RAW_ONE = (
    "42, female, master's degree, 62000, marketing manager, Hispanic, "
    "single, 4, 2, TX, rent, 4.99, purchase"
)

# Verbatim from LAUNCH-READY.md (the second quoted smoke draw; straight
# ASCII apostrophe as printed there). Same shape as SMOKE_RAW_ONE.
SMOKE_RAW_TWO = (
    "32, female, bachelor's degree, 45000, teacher, White, married, 4, 2, "
    "TX, rent, 3.49, purchase"
)

# The prompt's OWN "Return example" line, as build_persona_elicitation_prompt
# emits it (personas.py) and as RESULT-1474 §Prompt 10 transcribes it
# (ASCII apostrophe in the source; the paper's no-space "Asian,married"
# quirk kept verbatim — a CSV splitter must treat it as two fields,
# "Asian" and "married").
RETURN_EXAMPLE_LINE = (
    "35, female, bachelor's degree, 50000, software engineer, Asian,married, "
    "3, 1, CA, own, 3.99, purchase"
)


def _smoke_one_persona():
    """The persona dict SMOKE_RAW_ONE must parse into, keyed by the 11
    canonical PERSONA_FIELDS names (int for whole-number fields)."""
    return {
        "age": 42,
        "gender": "female",
        "education": "master's degree",
        "household_income": 62000,
        "occupation": "marketing manager",
        "ethnicity": "Hispanic",
        "marital_status": "single",
        "household_size": 4,
        "number_of_children": 2,
        "state": "TX",
        "home_ownership": "rent",
    }


def _smoke_two_persona():
    """The persona dict SMOKE_RAW_TWO must parse into."""
    return {
        "age": 32,
        "gender": "female",
        "education": "bachelor's degree",
        "household_income": 45000,
        "occupation": "teacher",
        "ethnicity": "White",
        "marital_status": "married",
        "household_size": 4,
        "number_of_children": 2,
        "state": "TX",
        "home_ownership": "rent",
    }


def _return_example_persona():
    """The persona dict RETURN_EXAMPLE_LINE must parse into."""
    return {
        "age": 35,
        "gender": "female",
        "education": "bachelor's degree",
        "household_income": 50000,
        "occupation": "software engineer",
        "ethnicity": "Asian",
        "marital_status": "married",
        "household_size": 3,
        "number_of_children": 1,
        "state": "CA",
        "home_ownership": "own",
    }


# The persona dict every *_persona() above must equal: exactly the eleven
# canonical keys. A parser that mapped CSV positions onto any other key set
# (e.g. the paper labels with spaces, or extra "price"/"purchase" keys)
# fails these tests — parse_persona's contract is the internal key names.

def _parse(raw):
    """Run parse_persona on one raw answer."""
    return personas.parse_persona(raw)


class TestParsePersonaCsvAnswers:
    """Prompt-10-conformant CSV answers parse into persona dicts.

    parse_persona must accept a comma-separated completion whose fields are
    the 11 Appendix-D demographics in Prompt 10's order (the shape the
    prompt itself requests and real models return). Today's code returns
    None for every one of these — RED until the fix lands.
    """

    def test_csv_answer_in_prompt_field_order_parses_into_a_persona(self):
        # The prompt's own return-example line: 11 demographics in order,
        # then the price and purchase answer. All 11 fields must come
        # through, trailing fields ignored.
        parsed = _parse(RETURN_EXAMPLE_LINE)
        assert parsed == _return_example_persona(), (
            f"CSV answer in Prompt 10 field order must parse into the full "
            f"persona dict, got {parsed!r}"
        )

    def test_csv_answer_captures_all_eleven_fields_with_the_right_types(self):
        # age, household_income, household_size and number_of_children are
        # whole numbers -> int; the rest stay strings.
        parsed = _parse(RETURN_EXAMPLE_LINE)
        assert parsed is not None
        assert set(parsed) == set(personas.PERSONA_FIELDS)
        for field in ("age", "household_income", "household_size",
                      "number_of_children"):
            assert isinstance(parsed[field], int), (
                f"{field} must be an int, got {parsed[field]!r}"
            )
        for field in ("gender", "education", "occupation", "ethnicity",
                      "marital_status", "state", "home_ownership"):
            assert isinstance(parsed[field], str), (
                f"{field} must be a string, got {parsed[field]!r}"
            )
        assert parsed["age"] == 35
        assert parsed["household_income"] == 50000
        assert parsed["household_size"] == 3
        assert parsed["number_of_children"] == 1

    def test_smoke_shape_one_marketing_manager_parses(self):
        # Verbatim smoke answer 1 (RESULT-1517 §The blocker / LAUNCH-READY):
        # the 13-field CSV with the store price and purchase answer after
        # the 11 demographics must parse into the 11-field persona.
        parsed = _parse(SMOKE_RAW_ONE)
        assert parsed == _smoke_one_persona(), (
            f"smoke shape 1 (marketing manager) must parse, got {parsed!r}"
        )

    def test_smoke_shape_two_teacher_parses(self):
        # Verbatim smoke answer 2 (LAUNCH-READY.md): same shape, White
        # ethnicity capitalised exactly as the model wrote it.
        parsed = _parse(SMOKE_RAW_TWO)
        assert parsed == _smoke_two_persona(), (
            f"smoke shape 2 (teacher) must parse, got {parsed!r}"
        )

    def test_no_space_between_csv_fields_parses_like_spaced_fields(self):
        # The paper prints "Asian,married" (no space) in Prompt 10's return
        # example. The no-space answer must give the same two fields as the
        # space-separated twin, so a missing space never merges fields.
        no_space = _parse(RETURN_EXAMPLE_LINE)
        assert no_space is not None, (
            "the Prompt 10 return-example CSV must parse at all"
        )
        spaced = _parse(RETURN_EXAMPLE_LINE.replace("Asian,married",
                                                    "Asian, married"))
        assert spaced is not None, (
            "the space-separated twin must parse at all"
        )
        assert no_space == spaced, (
            "'Asian,married' and 'Asian, married' must parse identically"
        )
        assert no_space["ethnicity"] == "Asian"
        assert no_space["marital_status"] == "married"


class TestTrailingFieldsIgnored:
    """Extra fields after the 11th demographic never break or leak keys.

    The persona prompt appends the store price and the purchase question
    after the 11 demographics, so real answers carry 13 fields. The rule
    pinned here: the FIRST 11 comma-separated fields are the demographics;
    everything after them is ignored. No "price" or "purchase" keys may
    appear, and the 11 canonical fields keep their values.
    """

    def test_trailing_price_and_purchase_answer_are_ignored(self):
        parsed = _parse(SMOKE_RAW_ONE)
        assert parsed is not None
        assert set(parsed) == set(personas.PERSONA_FIELDS), (
            f"trailing fields must not add keys, got {sorted(parsed)!r}"
        )
        assert parsed == _smoke_one_persona()

    def test_first_eleven_fields_win_over_arbitrary_trailing_junk(self):
        # Ten extra junk fields after the 11 demographics: the persona must
        # still be exactly the first 11 fields.
        raw = (
            "54, male, some college, 41000, nurse, Black, widowed, 2, 1, "
            "OH, own, whatever, nonsense, 1, 2, 3, 4, 5, 6, 7, 8"
        )
        parsed = _parse(raw)
        assert parsed is not None
        assert parsed["age"] == 54
        assert parsed["gender"] == "male"
        assert parsed["education"] == "some college"
        assert parsed["household_income"] == 41000
        assert parsed["occupation"] == "nurse"
        assert parsed["ethnicity"] == "Black"
        assert parsed["marital_status"] == "widowed"
        assert parsed["household_size"] == 2
        assert parsed["number_of_children"] == 1
        assert parsed["state"] == "OH"
        assert parsed["home_ownership"] == "own"
        assert set(parsed) == set(personas.PERSONA_FIELDS)


class TestInvalidCsvAnswersReturnNone:
    """Malformed answers are not personas: None, never a crash.

    parse_persona's contract for the underscore format is "missing field or
    bad whole number -> None"; the CSV format keeps the same contract.
    """

    def test_too_few_fields_returns_none(self):
        # Only 3 of the 11 demographics: the answer cannot be a persona.
        assert _parse("35, female, bachelor's degree") is None

    def test_ten_fields_missing_one_returns_none(self):
        # All demographics but home ownership: still incomplete.
        raw = (
            "35, female, bachelor's degree, 50000, software engineer, "
            "Asian, married, 3, 1, CA"
        )
        assert _parse(raw) is None

    def test_non_numeric_age_returns_none(self):
        # Age is a whole-number field; a word there must not crash or slip
        # through as a persona.
        raw = (
            "old, female, bachelor's degree, 50000, software engineer, "
            "Asian, married, 3, 1, CA, own"
        )
        assert _parse(raw) is None

    def test_non_numeric_income_returns_none(self):
        # Household income is a whole-number field.
        raw = (
            "35, female, bachelor's degree, lots, software engineer, "
            "Asian, married, 3, 1, CA, own"
        )
        assert _parse(raw) is None

    def test_prose_answer_returns_none_not_a_crash(self):
        # A refusal or prose reply is not a comma-separated completion.
        assert _parse("I cannot answer that.") is None
        assert _parse("") is None


class TestUnderscoreFormatStillParses:
    """Backwards compatibility: the old key-labelled format keeps working.

    The existing parse tests (tests/test_personas.py TestParsePersona, with
    the _CANNED_RAW "field: value" fixture) stay untouched and must keep
    passing after the fix. This file pins the same rule from the CSV side:
    parse_persona must support BOTH formats — the underscore-key labelled
    lines (what the old tooling produced) AND the comma-separated Prompt 10
    completion (what the prompt asks real models for).
    """

    _CANNED_KEY_RAW = "\n".join(
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

    _CANNED_KEY_PERSONA = {
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

    def test_underscore_key_format_still_parses_unchanged(self):
        # The exact canned shape the existing tests pin (including the
        # "$86,500" income with its dollar sign and comma) must keep
        # producing the same persona dict.
        parsed = _parse(self._CANNED_KEY_RAW)
        assert parsed == self._CANNED_KEY_PERSONA, (
            "the underscore-key 'field: value' format must keep parsing "
            "when CSV support is added"
        )
        assert parsed["household_income"] == 86500
