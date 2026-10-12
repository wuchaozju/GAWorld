"""
Persona generation for the Gui & Toubia (2025) unblinding study (Web
Appendix D), plus audit reports checking a batch against the paper's
coherence rules and against approximate US census marginals.

A persona is a single LLM completion of the paper's Prompt 10 (Appendix D):
it opens with the neutral consumer self-description ("You are a consumer
with the following characteristics:"), lists the 11 demographic fields as
fill-ins, and ends with the purchase question. The system line is the
paper's Prompt 2/10 customer line. The depth ladder has exactly the two
paper levels {1, 2}: "none" (bare survey) and "demographics" (the 11
fields). The model-invented behavioural tiers (tightwad/time_preference/
risk_preference) of the pre-drift five-tier ladder are gone; BEHAVIORAL_
MEASURES survives only as the Appendix E panel names. This module never
talks to a network; a chat function is injected by the caller.

What each function does:
    build_persona_elicitation_prompt()  - Paper Prompt 10 verbatim (user text).
    parse_persona(raw)  - Read an answer (CSV completion or key-labelled
                         lines) into an 11-field persona, or None.
    generate_personas(...)  - Draw n personas via chat_fn; (personas, skipped).
    render_persona_fields(persona, depth)  - One of the two depth levels'
                                             fields of a persona.
    render_demographics_block(persona)  - The demographics-tier fields.
    check_persona_diversity(personas)  - How varied a batch of personas is.
    check_persona_coherence(personas)  - How many paper rules a batch breaks.
    compare_to_census(personas, ...)  - Gap between a batch and US census.
    load_census_marginals(path)  - Read the bundled census marginals file.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from fos.experiments.sweep_kit import _SPECIAL_TOKEN, _strip_channel_wrappers
from fos.i18n import T

# The eleven demographic fields of the paper's persona profile, in the order
# the prompt template and every renderer must use them.
PERSONA_FIELDS = [
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
# elicitation prompt never asks the model to invent their scores or
# percentiles (Appendix E awaits real measured data), so nothing renders or
# prompts them.
BEHAVIORAL_MEASURES = [
    "tightwad_spendthrift",
    "discount_rate",
    "present_bias",
    "risk_aversion",
    "loss_aversion",
]

# The paper's verbatim Prompt 2 / Prompt 10 system line (RESULT-1474 §1):
# the customer fills in the blanks and returns comma-separated values.
# Persona generation sends exactly this line as the system message.
PERSONA_SYSTEM = (
    "You, AI, are a customer. Your task is to fill in the blanks. "
    "Return the completed information in comma-separated values, without any "
    "extra text."
)

# The two paper persona depth levels. "none" renders nothing; "demographics"
# renders the 11 canonical fields. The removed behavioural tiers of the
# pre-drift five-tier ladder are not listed and must raise ValueError.
_PERSONA_DEPTHS = ("none", "demographics")

# Fields whose value must be a whole number once "$", commas and spaces are
# removed; every other field is kept as the text the model wrote.
_INT_FIELDS = {"age", "household_income", "household_size", "number_of_children"}

# A chat function: message list and temperature in, raw model text out.
ChatFn = Callable[[list[dict[str, str]], float], str]

# Numeric edits allowed inside a whole-number field value before casting.
_NUMBER_JUNK = "$,"

# Words that mark an occupation as retired, matched on word boundaries so
# "retired teacher" counts but "pre-retirement training" does not.
_RETIRED_WORD = re.compile(r"\bretire", re.IGNORECASE)

# Words the coherence report needs to recognise when reading a persona.
_RETIREMENT_AGE = 50
_AGE_MIN = 18
_AGE_MAX = 100

# How the census marginals file is found when no explicit path is given.
_CENSUS_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "configs"
    / "census_marginals_us_approx.json"
)

# The 11 demographic fill-in lines of paper Prompt 10 (Appendix D), verbatim
# labels and bracketed hints (ASCII quotes), in the paper's order. These are
# the lines that follow the consumer opener inside the elicitation prompt.
_PERSONA_FILLIN_LINES = (
    "Age: [a whole number]",
    "Gender:",
    "Education level:",
    "Household income: [a whole number]",
    "Occupation:",
    "Ethnicity:",
    "Marital status:",
    "Household size: [a whole number]",
    "Number of children: [a whole number]",
    "State of residence: [state]",
    'Home ownership: [e.g., "own," "rent"]',
)


def build_persona_elicitation_prompt(category: str, product: str) -> str:
    """Return the step-A persona prompt: paper Prompt 10 verbatim.

    The user text opens with the paper's neutral consumer self-description,
    lists the 11 demographic fill-ins (Appendix D) in the paper's order,
    then the category and store paragraphs, leaves the store price as a
    blank (no price prior, no willingness-to-pay slot), and ends with the
    purchase question and the paper's return example. The old
    outcome-selecting opener (which asked the model to write a buyer's
    profile) and the model-invented behavioural-score blanks are gone.
    """
    demographic_block = "\n".join(_PERSONA_FILLIN_LINES)
    return (
        "You are a consumer with the following characteristics:\n"
        f"{demographic_block}\n\n"
        f"Please consider the following product category: {category}.\n\n"
        "Suppose you are in a grocery store, and you see the following "
        f"product in that category: {product}.\n\n"
        "The product is currently priced at [a number with up to 2 decimal "
        "points].\n\n"
        f'Would you or would you not purchase {product}? ["purchase" or '
        '"not purchase"]\n'
        "Return example: 35, female, bachelor's degree, 50000, software "
        "engineer, Asian,married, 3, 1, CA, own, 3.99, purchase"
    )


def parse_persona(raw: str) -> dict[str, Any] | None:
    """Read a model answer into an eleven-field persona dict, or None.

    Two answer shapes are accepted. First, the legacy "field: value" lines
    for PERSONA_FIELDS (the pre-drift tooling format, pinned by the existing
    TestParsePersona tests). Second, the Prompt 10 comma-separated
    completion the prompt itself asks real models for: one line whose first
    eleven comma-separated fields are the eleven demographics in
    PERSONA_FIELDS order, with any later fields (store price, purchase
    answer, junk) ignored. The answer may carry a reasoning-channel wrapper
    or chat-template tokens (both stripped first) and any number of prose
    lines before or after the answer; a whole-number field that is empty or
    not a whole number after "$" and "," are removed makes the answer not
    a persona. A reply that leaves any field missing or unparsable in both
    shapes returns None.
    """
    if not isinstance(raw, str):
        return None
    cleaned = _SPECIAL_TOKEN.sub("", _strip_channel_wrappers(raw))
    parsed = _parse_underscore_answer(cleaned)
    if parsed is None:
        parsed = _parse_csv_answer(cleaned)
    return parsed


def _parse_underscore_answer(cleaned: str) -> dict[str, Any] | None:
    """Read a key-labelled "field: value" answer into a persona, or None.

    Every PERSONA_FIELDS line must appear at most once with a non-empty
    value; repeated lines for one field are ignored. Whole-number fields are
    cast to int after "$" and "," are removed, and a field that cannot be
    cast leaves the whole reply not a persona.
    """
    parsed: dict[str, Any] = {}
    for line in cleaned.splitlines():
        name, separator, value = line.partition(":")
        if not separator:
            continue
        name = name.strip().lower()
        if name not in PERSONA_FIELDS or name in parsed:
            continue
        value = value.strip()
        if not value or "[" in value:
            continue
        if name in _INT_FIELDS:
            digits = value.translate(str.maketrans("", "", _NUMBER_JUNK)).strip()
            if not digits:
                continue
            try:
                parsed[name] = int(digits)
            except ValueError:
                continue
        else:
            parsed[name] = value
    if len(parsed) != len(PERSONA_FIELDS):
        return None
    return {field: parsed[field] for field in PERSONA_FIELDS}


def _parse_csv_answer(cleaned: str) -> dict[str, Any] | None:
    """Read the Prompt 10 comma-separated completion into a persona, or None.

    Each line is tried in turn: the first line whose first eleven
    comma-separated fields are the eleven demographics in PERSONA_FIELDS
    order (trailing fields ignored) becomes the persona. A line that splits
    into fewer than eleven fields, or whose whole-number fields do not cast,
    is skipped, so prose around the answer never blocks the real completion.
    """
    for line in cleaned.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < len(PERSONA_FIELDS):
            continue
        parsed = _parse_csv_fields(fields[: len(PERSONA_FIELDS)])
        if parsed is not None:
            return parsed
    return None


def _parse_csv_fields(fields: list[str]) -> dict[str, Any] | None:
    """Map eleven comma-separated fields onto the persona dict, or None.

    The fields are zipped onto PERSONA_FIELDS in order; a missing, empty or
    still-unfilled ("[") value anywhere makes the whole line not a persona.
    Whole-number fields are cast to int after "$" and "," are removed.
    """
    parsed: dict[str, Any] = {}
    for name, value in zip(PERSONA_FIELDS, fields):
        if not value or "[" in value:
            return None
        if name in _INT_FIELDS:
            digits = value.translate(str.maketrans("", "", _NUMBER_JUNK)).strip()
            if not digits:
                return None
            try:
                parsed[name] = int(digits)
            except ValueError:
                return None
        else:
            parsed[name] = value
    return parsed


def generate_personas(
    category: str,
    product: str,
    n: int,
    chat_fn: ChatFn,
    temperature: float = 1.0,
    seed: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Draw n personas through chat_fn; return (personas, skipped).

    One chat call per persona: the Prompt 10 prompt goes in the user message
    under the paper's Prompt 2/10 system line and the model's raw answer is
    parsed. Answers that do not parse to a full persona are counted in
    skipped, never in personas. The temperature is forwarded to every call;
    seed is accepted for a uniform call signature (chat_fn is the source of
    randomness, so the same injected function and seed reproduce the same
    batch).
    """
    del seed  # chat_fn is the only source of randomness.
    personas: list[dict[str, Any]] = []
    skipped = 0
    user_prompt = build_persona_elicitation_prompt(category, product)
    messages = [
        {"role": "system", "content": PERSONA_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    for _ in range(n):
        raw = chat_fn(messages, temperature)
        persona = parse_persona(raw)
        if persona is None:
            skipped += 1
        else:
            personas.append(persona)
    return personas, skipped


def render_persona_fields(persona: dict[str, Any], depth: str) -> str:
    """Render the fields one persona depth tier shows, "field: value" lines.

    The paper's two-level depth renderer: the SAME persona dict renders
    nothing at "none" and the canonical demographic fields at
    "demographics" (in PERSONA_FIELDS order, plus extra scalar keys such as
    city the persona carries). Missing keys are skipped, never KeyError (the
    TASK-1456 tolerance); legacy measure dicts a persona may still carry are
    never drawn (their model-invented scores are drift). Any other depth —
    including the removed behavioural tiers and the superseded "extended" —
    raises ValueError.
    """
    if depth == "none":
        return ""
    if depth not in _PERSONA_DEPTHS:
        raise ValueError(
            T(
                "error.personas.unsupported_depth",
                depth=repr(depth),
                supported=", ".join(_PERSONA_DEPTHS),
            )
        )
    lines = [
        f"{field}: {persona[field]}" for field in PERSONA_FIELDS if field in persona
    ]
    lines.extend(
        f"{field}: {value}"
        for field, value in persona.items()
        if field not in PERSONA_FIELDS and not isinstance(value, dict)
    )
    return "\n".join(lines)


def render_demographics_block(persona: dict[str, Any]) -> str:
    """Return one "field: value" line per field the demographics tier shows.

    A thin wrapper over render_persona_fields at the "demographics" tier, so
    callers that name that tier directly (partial personas included) keep the
    exact same rendering. A persona with none of the canonical fields
    renders an empty string, as before.
    """
    if not any(field in persona for field in PERSONA_FIELDS):
        return ""
    return render_persona_fields(persona, "demographics")


def _canonical_key(persona: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Turn a persona dict into a hashable key for counting duplicates."""
    return tuple(sorted(persona.items()))


def check_persona_diversity(personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Report how varied a batch of personas is, as five statistics.

    unique is the number of distinct profiles, top_repeat_count is how often
    the most common profile appears, top_repeat_share is that count over n,
    and distinct_ratio is (unique - 1) / (n - 1) — the share of persona pairs
    that differ. An empty batch reports zeros.
    """
    n = len(personas)
    counts = Counter(_canonical_key(persona) for persona in personas)
    unique = len(counts)
    top_repeat_count = max(counts.values(), default=0)
    if n > 1:
        distinct_ratio = (unique - 1) / (n - 1)
    else:
        distinct_ratio = 0.0
    return {
        "n": n,
        "unique": unique,
        "top_repeat_count": top_repeat_count,
        "top_repeat_share": top_repeat_count / n if n else 0.0,
        "distinct_ratio": distinct_ratio,
    }


def _rule_violations(persona: dict[str, Any]) -> list[str]:
    """List every paper coherence rule one persona breaks, by rule name."""
    broken: list[str] = []
    age = persona.get("age")
    if not isinstance(age, int) or age < _AGE_MIN or age > _AGE_MAX:
        broken.append("age_range")
    household_size = persona.get("household_size")
    children = persona.get("number_of_children")
    if (
        isinstance(household_size, int)
        and isinstance(children, int)
        and children >= household_size
    ):
        broken.append("children_capacity")
    income = persona.get("household_income")
    if isinstance(income, int) and income < 0:
        broken.append("income_nonnegative")
    occupation = persona.get("occupation")
    if (
        isinstance(occupation, str)
        and _RETIRED_WORD.search(occupation) is not None
        and isinstance(age, int)
        and age < _RETIREMENT_AGE
    ):
        broken.append("retirement_age")
    if isinstance(household_size, int) and household_size < 1:
        broken.append("household_size_min")
    return broken


def check_persona_coherence(personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Report how many personas break the paper's five coherence rules.

    The report carries n_violations (each broken rule counts once, so one
    persona breaking two rules counts twice), a rates dict with one 0..1
    share per rule name, and examples listing each offending persona dict
    exactly once.
    """
    rule_names = [
        "age_range",
        "children_capacity",
        "income_nonnegative",
        "retirement_age",
        "household_size_min",
    ]
    n = len(personas)
    fires = {name: 0 for name in rule_names}
    total = 0
    examples: list[dict[str, Any]] = []
    for persona in personas:
        broken = _rule_violations(persona)
        if broken:
            total += len(broken)
            examples.append(persona)
            for name in broken:
                fires[name] += 1
    rates = {name: fires[name] / n if n else 0.0 for name in rule_names}
    return {"n_violations": total, "rates": rates, "examples": examples}


def _numeric_gap(personas: list[dict[str, Any]], field: str) -> float:
    """Mean of one numeric field across a batch, or 0.0 when batch is empty."""
    if not personas:
        return 0.0
    return sum(persona[field] for persona in personas) / len(personas)


def _share_dict(
    personas: list[dict[str, Any]], field: str, categories: list[str]
) -> dict[str, float]:
    """Share of each category value for one categorical field.

    Categories listed in the census marginals that nobody chose get share 0;
    values the batch chose that the census does not list still appear, so the
    sample report never silently drops people.
    """
    if not personas:
        return {category: 0.0 for category in categories}
    counts = Counter(persona[field] for persona in personas)
    names = list(dict.fromkeys([*categories, *counts]))
    return {name: counts.get(name, 0) / len(personas) for name in names}


def compare_to_census(
    personas: list[dict[str, Any]], marginals: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Compare a persona batch with census marginals, for gap reporting.

    Numeric marginals ("mean") compare the sample mean minus the census mean;
    categorical marginals ("shares") compare via total-variation distance,
    0.5 times the summed absolute share differences. Only the fields named in
    marginals appear in the report, each carrying the sample value, the
    census value, and the gap.
    """
    report: dict[str, dict[str, Any]] = {}
    for field, marginal in marginals.items():
        if "mean" in marginal:
            sample = _numeric_gap(personas, field)
            census = float(marginal["mean"])
            report[field] = {
                "sample": sample,
                "census": census,
                "gap": sample - census,
            }
        else:
            shares = marginal.get("shares")
            if not isinstance(shares, dict) or not shares:
                continue
            sample = _share_dict(personas, field, list(shares))
            census = {str(category): float(share) for category, share in shares.items()}
            distance = 0.5 * sum(
                abs(sample.get(category, 0.0) - census[category]) for category in census
            )
            report[field] = {
                "sample": {category: sample.get(category, 0.0) for category in census},
                "census": census,
                "gap": distance,
            }
    return report


def load_census_marginals(path: str | Path | None = None) -> dict[str, Any]:
    """Read the census marginals JSON from a path (bundled file by default).

    The bundled file holds APPROXIMATE US population marginals for gap
    reporting only — never for statistical inference. An explicit path is
    read as-is.
    """
    target = Path(path) if path is not None else _CENSUS_DEFAULT
    return json.loads(target.read_text(encoding="utf-8"))
