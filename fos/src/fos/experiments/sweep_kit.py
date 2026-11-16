"""
Sweep and diagnostic runners for the Gui & Toubia (2025) unblinding study.

This module is the executable layer that sits on top of
fos.experiments.randomization. It builds the survey prompts from the paper,
runs them against an injected chat function (so tests never touch a network),
and writes self-describing results. It contains no network code of its own.

What each function does:
    build_blinded_system_prompt()          - The paper Prompt 2/10 system
                                             line: the model plays a customer
                                             and fills in the blanks.
    build_unblinded_system_prompt(design)  - The Prompt-6 system prompt: the
                                             fill task plus the design's
                                             unblinding paragraph. For a
                                             blinded design it is exactly the
                                             Prompt-2/10 prompt.
    build_purchase_user_prompt(...)        - The Prompt-2 purchase survey shown
                                             to the customer (buy or not buy).
    build_covariate_fillin_prompt(...)     - One Prompt 1/7/8 probe that asks
                                             the model to fill in a covariate
                                             (past price, competing price,
                                             expiry days, or household income)
                                             at a given price.
    parse_purchase(text)                   - Reads the model's one-line answer:
                                             True for "purchase"/"yes", False
                                             for "not purchase"/"no", None
                                             otherwise.
    parse_fillin_number(text)              - Reads a "$8.26"-style answer as a
                                             float, or None for garbage.
    _first_answer_line(text)              - First line of an answer after
                                             wrapper stripping, spans turned
                                             into single spaces.
    _first_line_has_token_span(text)      - True when a <|...|> span sits on
                                             the answer's first line (tells
                                             the parser a span made the word
                                             boundary).
    _strip_channel_wrappers(text)          - Removes the llama-server
                                             reasoning-channel marker that some
                                             models wrap around their answer.
    aggregate_demand(records, levels)      - Turns sweep records into one
                                             {level, p_buy, n} bucket per price
                                             level, sorted low to high.
    build_record(...)                      - One self-describing result row for
                                             a single chat call.
    run_sweep(...)                         - Runs the full demand sweep
                                             (products x levels x draws) under
                                             one blinding condition.
    run_persona_sweep(...)                 - Persona sweep: one chat call per
                                             (product x level x persona) at
                                             temperature 0.0, rendering the
                                             persona block into the prompt.
    run_logprob_sweep(...)                 - R1LP logprob sweep: one scoring
                                             pass per (product x level x draw)
                                             through an injected scorer.
    run_logprob_persona_sweep(...)         - R1LP persona logprob sweep: one
                                             scoring pass per (product x
                                             level x persona).
    run_diagnostic(...)                    - Runs the confounding diagnostic
                                             (products x levels x covariate
                                             kinds x draws) under one blinding
                                             condition.
    summarize_confounding(records, design) - Summarizes covariate confounding
                                             per kind, mirroring
                                             randomization.check_confounding.
    write_manifest(path, ...)              - Writes a JSON run manifest with a
                                             timestamp, never shelling out.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fos.experiments.randomization import (
    RandomizationDesign,
    check_confounding,
    covariate_count_for_depth,
)
from fos.i18n import T

# The paper fixes temperature at 1.0 and draws each response independently.
_TEMPERATURE = 1.0

# Paper step B: persona sweeps fix temperature at 0.0 on every call, because
# the heterogeneity must come from the personas, not from sampling noise.
_PERSONA_TEMPERATURE = 0.0

# Separator between the system and user prompt halves when hashing them; the
# record's prompt_sha256 is sha256(system + this + user).
_PROMPT_SEPARATOR = "\x1e"

# The paper's verbatim Prompt 2 / Prompt 10 system line (RESULT-1474 §1):
# the customer fills in the blanks and returns comma-separated values. The
# blinded purchase condition uses exactly this line -- the Prompt-5
# shortening ("fill in the blank ... without extra text") is drift and is
# gone.
_BLINDED_TASK = (
    "You, AI, are a customer. Your task is to fill in the blanks. "
    "Return the completed information in comma-separated values, without any "
    "extra text."
)

# The survey that both conditions put in the user message (paper Prompt 2).
# The two response-word slots ({answer_pos}/{answer_neg}) are filled from
# the single response_format config value: the historical defaults
# ("purchase" / "not purchase") render today's bytes exactly, so every
# stored prompt_sha256 stays stable; the R1-YESNO profile fills
# "yes" / "no". The question sentence's own "not purchase" is the
# question, not a response word, and never changes.
_PURCHASE_SURVEY = (
    "Please consider the following product category: {category}.\n"
    "Suppose you are in a grocery store, and you see the following product in "
    "that category: {product}.\n"
    "The product is currently priced at ${price:.2f}. Would you or would you "
    'not purchase the product? ["{answer_pos}" or "{answer_neg}"]\n'
    "Return example: {answer_pos}"
)

# One fill-in-the-blank probe per covariate (paper Prompts 1, 7 and 8,
# plus the income probe). Each probe keeps the paper's own sentence order
# and wording: last_price (Prompt 1) asks for the past price first and
# states the focal price after it, while competing_price (Prompt 7) and
# expiry_days (Prompt 8) state the focal price first, and the income probe
# asks for the total family income as a whole number.
_COVARIATE_PROBES = {
    "last_price": (
        "The last time you purchased this product, it was priced at $ "
        "[a number with up to 2 decimal points].\n"
        "The product is currently priced at: ${price:.2f}.\n"
        "Return example 1: 3.29"
    ),
    "competing_price": (
        "The product is currently priced at: ${price:.2f}.\n"
        "The price of a similar competing product from a different brand is "
        "[a number with up to 2 decimal points].\n"
        "Return example 1: 3.29"
    ),
    "expiry_days": (
        "The product is currently priced at: ${price:.2f}.\n"
        "The expiration date of the product is [a whole "
        "number] days from now.\n"
        "Return example 1: 10"
    ),
    "household_income": (
        "The product is currently priced at: ${price:.2f}.\n"
        "The total family income of the consumer is [a whole number].\n"
        "Return example 1: 50000"
    ),
}

# A chat function injected by the caller: sends a message list and a temperature,
# returns the model's raw text answer. Runners never open a network connection.
ChatFn = Callable[[list[dict[str, str]], float], str]

# google/gemma-4-26b-a4b (llama-server) can wrap its answer in a
# reasoning-channel marker: the recorded form is an opening "<|channel>", the
# model's internal text, then a closing "<channel|>" right before the real
# answer (for example "<|channel>thought\n<channel|>purchase"). The second
# branch is the symmetric form with the pipe on the other side. Both are
# stripped (non-greedy, crossing newlines) so the parsers only ever see the
# answer text itself.
_CHANNEL_WRAPPER = re.compile(
    r"<\|channel>.*?<channel\|>|<\|channel\|>.*?<\|channel>", re.DOTALL
)

# A chat-template token a model may keep emitting after it has answered, for
# example "purchase<|im_end|>\n<|im_start|>system\nYou," (meta/muse-glimmer):
# the answer comes first, the leaked template text after it is junk. The
# answer-line cleaner below turns each <|...|> span into ONE SPACE (never
# deletes it) so the words around the span never glue together
# ("purchase<|message|>final" must stay readable as "purchase final"). This
# runs AFTER the channel-wrapper strip above, whose own markers must stay
# intact to pair up. Note: sibling modules (personas, pilot_model) import this
# same pattern and delete spans outright for their own field-value parsing,
# which is why only the cleaner here substitutes spaces.
_SPECIAL_TOKEN = re.compile(r"<\|[^>]*\|>")


def _strip_channel_wrappers(text: str) -> str:
    """Remove any llama-server reasoning-channel marker from an answer.

    The wrapper is the channel open/close pair with whatever the model wrote
    between them; the answer ("purchase", "not purchase", a number) comes
    after the closing marker and is left untouched. Text with no marker comes
    back unchanged.
    """
    return _CHANNEL_WRAPPER.sub("", text)


# Junk allowed in front of the real answer on its line: whitespace, quotes,
# brackets, sentence punctuation and a stray dollar sign (for fill-in numbers).
_LEADING_JUNK = " \t\"'$.,;:!?()[]{}"


def _first_answer_line(text: str) -> str:
    """Return the lowercased first line of an answer, template junk removed.

    The channel wrapper is stripped first (the answer follows it), then every
    <|...|> chat-template token (which the answer precedes) becomes one space
    and runs of spaces collapse to one, so a span never glues the words
    around it ("purchase<|message|>final" reads "purchase final", not
    "purchasefinal"); only the first line is kept and lowercased, so leaked
    template turns or explanations written after the answer are dropped.
    """
    cleaned = _SPECIAL_TOKEN.sub(" ", _strip_channel_wrappers(text))
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip().split("\n", 1)[0].strip().lower()


def _first_line_has_token_span(text: str) -> bool:
    """True when a <|...|> token sits on the answer's first line.

    Mirrors _first_answer_line's wrapper strip and first-line split (without
    the span-to-space substitution), so the parser can tell a span-made word
    boundary from ordinary prose spacing on the answer line.
    """
    unwrapped = _strip_channel_wrappers(text).strip()
    return _SPECIAL_TOKEN.search(unwrapped.split("\n", 1)[0]) is not None


def _probe_intro(category: str, product: str) -> str:
    """Return the two shared opening lines of every covariate probe."""
    return (
        f"Please consider the following product category: {category}.\n"
        "Suppose you are in a grocery store, and you see the following "
        f"product in that category: {product}."
    )


def _seeded_rng(design: RandomizationDesign, seed: int | None) -> random.Random:
    """Build the internal generator that replays identical treatment sequences.

    The per-run seed argument wins when given; otherwise the design's own seed
    is used. With no seed anywhere the generator seeds from the system clock,
    so such runs are intentionally not reproducible.
    """
    chosen = seed if seed is not None else design.seed
    return random.Random(chosen)


def _price_for_level(regular_price: float, level: float) -> float:
    """Convert a percentage-of-regular-price level into a dollar price.

    A level of 100 means the regular price itself; a level of 200 means twice
    it. The result is rounded to cents.
    """
    return round(regular_price * level / 100.0, 2)


def _system_prompt(design: RandomizationDesign, blinding: str) -> str:
    """Pick the system prompt that matches the blinding condition."""
    if blinding == "blinded":
        return build_blinded_system_prompt()
    return build_unblinded_system_prompt(design)


def build_blinded_system_prompt() -> str:
    """Return the blinded system prompt: the paper Prompt 2/10 line.

    The customer fills in the blanks and returns comma-separated values,
    without any extra text (RESULT-1474 §1, Prompt 2 / Prompt 10). The
    Prompt-5 shortening used pre-fix is drift.
    """
    return _BLINDED_TASK


def build_unblinded_system_prompt(design: RandomizationDesign) -> str:
    """Return the unblinded (Prompt 6) system prompt for this design.

    The design's unblinding paragraph (what is randomized, over what support,
    that the subject is blind to it) is prepended to the Prompt-2/10 fill
    task. A blinded design renders no paragraph, so the result is exactly the
    blinded prompt and the two conditions share an identical user prompt.
    """
    paragraph = design.render_unblinding()
    if not paragraph:
        return build_blinded_system_prompt()
    return (
        f"{paragraph}\n\n"
        "The customer is given the following survey. Your task is to fill in "
        "the blank. Return the completed information without extra text."
    )


def split_response_format(response_format: str | None) -> tuple[str, str]:
    """Split the one response_format value into its two answer words.

    This is the single source of truth for both the prompt's response-word
    slots and the scorer's branch labels, so the two can never drift apart.
    None keeps the historical "purchase" / "not purchase" wording; any
    "<positive>/<negative>" pair splits on the one slash. A value without
    the "/" separator is refused loudly - silently mis-splitting it would
    put the wrong words in front of the models and the scorer.
    """
    if response_format is None:
        return ("purchase", "not purchase")
    pieces = response_format.split("/")
    if len(pieces) != 2 or not all(piece.strip() for piece in pieces):
        raise ValueError(
            T("error.sweep_kit.response_format_invalid", value=repr(response_format))
        )
    return (pieces[0].strip(), pieces[1].strip())


def build_purchase_user_prompt(
    category: str, product: str, price: float, response_format: str | None = None
) -> str:
    """Return the Prompt-2 purchase survey for one product at one price.

    response_format fills the survey's two response-word slots (see
    split_response_format); None keeps the historical prompt byte-identical.
    """
    answer_pos, answer_neg = split_response_format(response_format)
    return _PURCHASE_SURVEY.format(
        category=category,
        product=product,
        price=price,
        answer_pos=answer_pos,
        answer_neg=answer_neg,
    )


def build_covariate_fillin_prompt(
    kind: str, category: str, product: str, price: float
) -> str:
    """Return the Prompt 1/7/8 probe that fills one covariate at one price.

    kind must be one of "last_price", "competing_price", "expiry_days" or
    "household_income"; anything else raises a ValueError so a typo never
    silently probes the wrong covariate.
    """
    if kind not in _COVARIATE_PROBES:
        raise ValueError(T("error.sweep_kit.unsupported_fillin_kind", kind=repr(kind)))
    probe = _COVARIATE_PROBES[kind].format(price=price)
    return f"{_probe_intro(category, product)}\n{probe}"


def parse_purchase(text: str) -> bool | None:
    """Read a one-line purchase answer: True, False, or None for anything else.

    When the first line carries a chat-template span, the span boundary is
    what separates the decision from whatever the model kept writing, so the
    first word(s) of the line decide: "purchase"/"yes" mean True,
    "not purchase"/"no" mean False, and prose after the span is ignored (a
    real muse-glimmer record "not purchase<|im_end|>...Please consider..."
    reads False, not None). Without a span the whole first line must be the
    answer phrase — prose that merely starts with the word ("Purchase decision
    is a personal choice") is None — case-insensitively, with quotes and
    punctuation tolerated. Llama-server wrappers are removed first.
    """
    if not isinstance(text, str):
        return None
    body = _first_answer_line(text).lstrip(_LEADING_JUNK)
    if not body:
        return None
    if _first_line_has_token_span(text):
        # A span split the answer open mid-word, so read only the first word.
        if re.match(r"not\s+purchase(?=[^a-z0-9]|$)", body):
            return False
        if re.match(r"purchase(?=[^a-z0-9]|$)", body):
            return True
        if re.match(r"yes(?=[^a-z0-9]|$)", body):
            return True
        if re.match(r"no(?=[^a-z0-9]|$)", body):
            return False
        return None
    if re.match(r"not\s+purchase(?=[^a-z0-9]*$)", body):
        return False
    if re.match(r"purchase(?=[^a-z0-9]*$)", body):
        return True
    if re.match(r"yes(?=[^a-z0-9]*$)", body):
        return True
    if re.match(r"no(?=[^a-z0-9]*$)", body):
        return False
    return None


def parse_fillin_number(text: str) -> float | None:
    """Read a "$8.26"-style fill-in answer as a float.

    The number must be the first thing on the first line; a leading dollar
    sign, whitespace, quotes and punctuation are tolerated. Text that starts
    with letters ("about 5 dollars") or a malformed number ("8.2.6") is not
    a number and yields None. Llama-server wrappers and chat-template tokens
    are removed first.
    """
    if not isinstance(text, str):
        return None
    body = _first_answer_line(text).lstrip(_LEADING_JUNK)
    if not body:
        return None
    match = re.match(r"(\d+(?:\.\d+)?)(?=[^a-z0-9]*$)", body)
    if match is None:
        return None
    return float(match.group(1))


def aggregate_demand(
    records: list[dict[str, Any]], levels: list[float]
) -> list[dict[str, Any]]:
    """Bucket sweep records into one demand point per treatment level.

    Each record must carry "treatment_value" and "parsed_purchase". Records
    whose answer did not parse are ignored; among the parsed records n is the
    count and p_buy the share that chose to purchase. The levels argument may
    arrive unsorted; returned buckets are sorted by level ascending.
    """
    buckets: list[dict[str, Any]] = []
    for level in sorted(levels):
        at_level = [r for r in records if r["treatment_value"] == level]
        parsed = [r for r in at_level if r["parsed_purchase"] is not None]
        purchases = sum(1 for r in parsed if r["parsed_purchase"] is True)
        p_buy = purchases / len(parsed) if parsed else 0.0
        buckets.append({"level": level, "p_buy": p_buy, "n": len(parsed)})
    return buckets


def build_record(
    design: RandomizationDesign,
    blinding: str,
    model: str,
    product: str,
    category: str,
    treatment_value: float,
    raw: str,
    parsed: bool | None,
    elapsed_seconds: float,
    seed: int | None,
    *,
    persona_depth: str = "none",
    covariate_count: int = 0,
    system_prompt: str = "",
    user_prompt: str = "",
    extra: dict[str, Any] | None = None,
    succeeded: bool | None = None,
) -> dict[str, Any]:
    """Build one self-describing record for a single chat call.

    The record always carries the design (as JSON), the treatment value, the
    blinding condition, model, product and category, the model's raw answer,
    its parsed purchase decision, the wall-clock seconds the call took, the
    seed, and whether the call succeeded (that is, whether the answer
    parsed). A clean "not purchase" therefore succeeds; an unparsed answer
    does not.

    The optional persona and prompt fields complete the audit trail: the
    persona depth used, how many covariates that depth pins, the exact system
    and user prompts sent to the chat function, and prompt_sha256 (the sha256
    hex digest of system + "\x1e" + user) so a stored record can later be
    proven to match the prompts that produced it.

    The R1LP logprob runners use the keyword-only hooks: extra merges the
    scorer's logprob fields into the record, and succeeded overrides the
    parse-derived flag so a successful scoring call counts as a success even
    though its parsed_purchase stays None. Both default to the historical
    behaviour, so every existing caller's record is byte-identical.
    """
    record = {
        "design": design.to_json(),
        "treatment_value": treatment_value,
        "blinding": blinding,
        "model": model,
        "product": product,
        "category": category,
        "raw_content": raw,
        "parsed_purchase": parsed,
        "elapsed_seconds": elapsed_seconds,
        "succeeded": parsed is not None,
        "seed": seed,
        "persona_depth": persona_depth,
        "covariate_count": covariate_count,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_sha256": hashlib.sha256(
            (system_prompt + _PROMPT_SEPARATOR + user_prompt).encode("utf-8")
        ).hexdigest(),
    }
    if extra:
        record.update(extra)
    if succeeded is not None:
        record["succeeded"] = succeeded
    return record


def run_sweep(
    design: RandomizationDesign,
    products: list[dict[str, Any]],
    model: str,
    chat_fn: ChatFn,
    draws: int = 1,
    blinding: str | None = None,
    seed: int | None = None,
    persona_depth: str = "none",
    *,
    skip_first: int = 0,
    on_record: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run the demand sweep: one chat call per product, level and draw.

    products are {"category", "product", "regular_price"} dicts and chat_fn is
    an injected chat function (message list and temperature in, raw text out).
    The blinding condition defaults to the design's own blinding when not
    given. A grid design visits each level exactly draws times; a uniform
    design draws fresh values from the seeded internal generator. Each call
    becomes one build_record row whose treatment value stays inside the
    design's support.

    The stored design inside every record is the design with blinding set to
    the condition this run actually used (the run-level blinding wins over
    the design's own), so a "blinded" run can never leave an "unblinded"
    design behind in its own records. persona_depth names how deep the
    persona block of the study goes; its covariate_count is stamped on every
    record alongside the exact system and user prompts sent.

    Cell-level resume hooks (the launch wrapper's per-cell durability):
    skip_first skips that many already-completed leading cells (the cells a
    resumed leg found durably in its own records file) without calling
    chat_fn, and on_record, when given, is called with each newly built
    record the instant it is produced so the caller can append it to disk
    before the next cell starts. Both default to no-ops, so callers that do
    not pass them see exactly the historical single-shot behavior.
    """
    mode = design.blinding if blinding is None else blinding
    stored_design = replace(design, blinding=mode)
    covariate_count = covariate_count_for_depth(persona_depth)
    system = _system_prompt(design, mode)
    rng = _seeded_rng(design, seed)
    levels = design.grid()
    records: list[dict[str, Any]] = []
    cell = 0
    for product in products:
        for level in levels:
            for _ in range(draws):
                if cell < skip_first:  # cell already durably completed
                    cell += 1
                    # keep the uniform draw stream aligned with a fresh
                    # same-seed run even when the cell itself is skipped
                    if design.distribution == "uniform":
                        rng.uniform(design.min_value, design.max_value)
                    continue
                cell += 1
                value = (
                    level
                    if design.distribution == "grid"
                    else rng.uniform(design.min_value, design.max_value)
                )
                price = _price_for_level(product["regular_price"], value)
                user = build_purchase_user_prompt(
                    product["category"], product["product"], price
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
                started = time.monotonic()
                raw = chat_fn(messages, _TEMPERATURE)
                elapsed = time.monotonic() - started
                record = build_record(
                    stored_design,
                    mode,
                    model,
                    product["product"],
                    product["category"],
                    value,
                    raw,
                    parse_purchase(raw),
                    elapsed,
                    seed,
                    persona_depth=persona_depth,
                    covariate_count=covariate_count,
                    system_prompt=system,
                    user_prompt=user,
                )
                records.append(record)
                if on_record is not None:
                    on_record(record)
    return records


def _persona_renderer(persona_depth: str) -> Callable[[dict[str, Any]], str] | None:
    """Return a renderer that shows one persona depth tier's fields.

    The import is deliberately deferred to call time: the sibling module
    src/fos/experiments/personas.py lands on main separately, so importing it
    at module import time would make sweep_kit unimportable in the meantime.
    A "none" depth needs no renderer and never touches the module; every
    other tier returns a closure over that module's depth-truncating
    render_persona_fields at the requested depth, so the same renderer serves
    all five tiers. An unknown depth never reaches this function:
    run_persona_sweep validates it first through covariate_count_for_depth.
    """
    if persona_depth == "none":
        return None

    from fos.experiments import personas  # noqa: PLC0415 - deferred sibling import

    def render(persona: dict[str, Any]) -> str:
        return personas.render_persona_fields(persona, persona_depth)

    return render


def _persona_user_prompt(
    category: str,
    product: str,
    price: float,
    renderer: Callable[[dict[str, Any]], str] | None,
    persona: dict[str, Any],
    response_format: str | None = None,
) -> str:
    """Return the purchase survey with the persona block rendered in front.

    The rendered block names the embodied customer (age, city, occupation and
    the rest of the persona fields); the survey itself stays byte-identical
    to the plain sweep's so only the persona text differs. A depth with no
    block (or a renderer that produces nothing) returns the plain survey.
    response_format threads through to the survey's response-word slots.
    """
    survey = build_purchase_user_prompt(
        category, product, price, response_format=response_format
    )
    if renderer is None:
        return survey
    block = renderer(persona)
    if not block:
        return survey
    return f"EMBODY THIS PERSON:\n{block}\n\n{survey}"


def run_persona_sweep(
    design: RandomizationDesign,
    personas_by_product: dict[str, dict[str, Any]],
    model: str,
    chat_fn: ChatFn,
    blinding: str | None = None,
    persona_depth: str = "none",
    seed: int | None = None,
    *,
    skip_first: int = 0,
    on_record: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Run the persona demand sweep: one chat call per product, level, persona.

    personas_by_product maps a product name to {"category", "personas"} (and
    optionally "regular_price"): each embodied persona is a dict whose fields
    are rendered into the user prompt by the sibling personas module (see
    _persona_renderer). Every call runs at temperature 0.0 (paper step B: the
    heterogeneity comes from the personas, not from sampling).

    Returns (records, skipped_empty): one record per (product x level x
    persona) call and the count of empty-dict personas that were skipped
    without a chat call. Records carry the standard sweep keys plus the
    persona dict, its 0-based index inside the product's persona list, the
    persona depth and its covariate count; the stored design carries the
    blinding this run actually used (the same fix as run_sweep).

    Cell-level resume hooks (the launch wrapper's per-cell durability):
    skip_first skips that many already-completed leading cells without
    calling chat_fn, and on_record, when given, is called with each newly
    built record the instant it is produced. Both default to no-ops, so
    callers that do not pass them see the historical single-shot behavior.
    """
    mode = design.blinding if blinding is None else blinding
    stored_design = replace(design, blinding=mode)
    covariate_count = covariate_count_for_depth(persona_depth)
    renderer = _persona_renderer(persona_depth)
    system = _system_prompt(design, mode)
    rng = _seeded_rng(design, seed)
    levels = design.grid()
    records: list[dict[str, Any]] = []
    skipped_empty = 0
    cell = 0
    for product_name, info in personas_by_product.items():
        category = info["category"]
        regular_price = info.get("regular_price")
        for persona_index, persona in enumerate(info["personas"]):
            if not persona:
                skipped_empty += 1
                continue
            for level in levels:
                if cell < skip_first:  # cell already durably completed
                    cell += 1
                    # keep the uniform draw stream aligned with a fresh
                    # same-seed run even when the cell itself is skipped
                    if design.distribution == "uniform":
                        rng.uniform(design.min_value, design.max_value)
                    continue
                cell += 1
                value = (
                    level
                    if design.distribution == "grid"
                    else rng.uniform(design.min_value, design.max_value)
                )
                if regular_price is not None:
                    price = _price_for_level(regular_price, value)
                else:
                    price = value
                user = _persona_user_prompt(
                    category, product_name, price, renderer, persona
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
                started = time.monotonic()
                raw = chat_fn(messages, _PERSONA_TEMPERATURE)
                elapsed = time.monotonic() - started
                record = build_record(
                    stored_design,
                    mode,
                    model,
                    product_name,
                    category,
                    value,
                    raw,
                    parse_purchase(raw),
                    elapsed,
                    seed,
                    persona_depth=persona_depth,
                    covariate_count=covariate_count,
                    system_prompt=system,
                    user_prompt=user,
                )
                record["persona"] = persona
                record["persona_index"] = persona_index
                records.append(record)
                if on_record is not None:
                    on_record(record)
    return records, skipped_empty


# A logprob scorer injected by the caller (see scripts/logprob_scoring.py):
# it takes the chat messages and returns that prompt's logprob fields.
ScorerFn = Callable[[list[dict[str, str]]], dict[str, Any]]


def run_logprob_sweep(
    design: RandomizationDesign,
    products: list[dict[str, Any]],
    model: str,
    scorer_fn: ScorerFn,
    draws: int = 1,
    blinding: str | None = None,
    seed: int | None = None,
    persona_depth: str = "none",
    *,
    skip_first: int = 0,
    on_record: Callable[[dict[str, Any]], None] | None = None,
    response_format: str | None = None,
) -> list[dict[str, Any]]:
    """Run the R1LP logprob sweep: one scoring pass per (product x level x draw).

    The exact same prompts, design and cell enumeration as run_sweep, but
    each cell goes through an injected logprob scorer instead of a sampling
    chat function: the scorer returns the model's own p(buy) fields, which
    are merged into the record (see build_record's extra/succeeded hooks).
    parsed_purchase therefore stays None and succeeded is the scoring
    call's success, so the record schema extends today's rather than
    replacing it. response_format picks the prompt's response words and is
    stamped on every record beside parse_mode="first_token_logprob", so a
    record is always self-describing about how it was asked and parsed.

    skip_first and on_record keep the launch wrapper's cell-granular
    durability contract: a resumed leg executes only the missing cells and
    every new record is handed out the instant it is produced. draws
    defaults to 1 - R1LP makes ONE scoring pass per prompt.
    """
    mode = design.blinding if blinding is None else blinding
    stored_design = replace(design, blinding=mode)
    covariate_count = covariate_count_for_depth(persona_depth)
    system = _system_prompt(design, mode)
    rng = _seeded_rng(design, seed)
    levels = design.grid()
    records: list[dict[str, Any]] = []
    cell = 0
    for product in products:
        for level in levels:
            for _ in range(draws):
                if cell < skip_first:  # cell already durably completed
                    cell += 1
                    if design.distribution == "uniform":
                        rng.uniform(design.min_value, design.max_value)
                    continue
                cell += 1
                value = (
                    level
                    if design.distribution == "grid"
                    else rng.uniform(design.min_value, design.max_value)
                )
                price = _price_for_level(product["regular_price"], value)
                user = build_purchase_user_prompt(
                    product["category"],
                    product["product"],
                    price,
                    response_format=response_format,
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
                started = time.monotonic()
                result = scorer_fn(messages)
                elapsed = time.monotonic() - started
                record = build_record(
                    stored_design,
                    mode,
                    model,
                    product["product"],
                    product["category"],
                    value,
                    result.get("raw_content", ""),
                    None,
                    elapsed,
                    seed,
                    persona_depth=persona_depth,
                    covariate_count=covariate_count,
                    system_prompt=system,
                    user_prompt=user,
                    extra={
                        **result,
                        "response_format": response_format,
                        "parse_mode": "first_token_logprob",
                    },
                    succeeded=bool(result.get("succeeded")),
                )
                records.append(record)
                if on_record is not None:
                    on_record(record)
    return records


def run_logprob_persona_sweep(
    design: RandomizationDesign,
    personas_by_product: dict[str, dict[str, Any]],
    model: str,
    scorer_fn: ScorerFn,
    blinding: str | None = None,
    persona_depth: str = "none",
    seed: int | None = None,
    *,
    skip_first: int = 0,
    on_record: Callable[[dict[str, Any]], None] | None = None,
    response_format: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Run the R1LP persona logprob sweep: one scoring pass per persona cell.

    The persona twin of run_logprob_sweep: the same persona block in the
    prompt and the same (product x persona x level) enumeration as
    run_persona_sweep, but each cell is scored once for its p(buy) instead
    of sampled. Records carry persona and persona_index so the analysis can
    average p(buy) over a model's personas; response_format works exactly
    as in run_logprob_sweep (prompt wording + record stamps). Returns
    (records, skipped_empty) exactly like run_persona_sweep.
    """
    mode = design.blinding if blinding is None else blinding
    stored_design = replace(design, blinding=mode)
    covariate_count = covariate_count_for_depth(persona_depth)
    renderer = _persona_renderer(persona_depth)
    system = _system_prompt(design, mode)
    rng = _seeded_rng(design, seed)
    levels = design.grid()
    records: list[dict[str, Any]] = []
    skipped_empty = 0
    cell = 0
    for product_name, info in personas_by_product.items():
        category = info["category"]
        regular_price = info.get("regular_price")
        for persona_index, persona in enumerate(info["personas"]):
            if not persona:
                skipped_empty += 1
                continue
            for level in levels:
                if cell < skip_first:  # cell already durably completed
                    cell += 1
                    if design.distribution == "uniform":
                        rng.uniform(design.min_value, design.max_value)
                    continue
                cell += 1
                value = (
                    level
                    if design.distribution == "grid"
                    else rng.uniform(design.min_value, design.max_value)
                )
                if regular_price is not None:
                    price = _price_for_level(regular_price, value)
                else:
                    price = value
                user = _persona_user_prompt(
                    category,
                    product_name,
                    price,
                    renderer,
                    persona,
                    response_format=response_format,
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
                started = time.monotonic()
                result = scorer_fn(messages)
                elapsed = time.monotonic() - started
                record = build_record(
                    stored_design,
                    mode,
                    model,
                    product_name,
                    category,
                    value,
                    result.get("raw_content", ""),
                    None,
                    elapsed,
                    seed,
                    persona_depth=persona_depth,
                    covariate_count=covariate_count,
                    system_prompt=system,
                    user_prompt=user,
                    extra={
                        **result,
                        "response_format": response_format,
                        "parse_mode": "first_token_logprob",
                    },
                    succeeded=bool(result.get("succeeded")),
                )
                record["persona"] = persona
                record["persona_index"] = persona_index
                records.append(record)
                if on_record is not None:
                    on_record(record)
    return records, skipped_empty


def run_diagnostic(
    design: RandomizationDesign,
    products: list[dict[str, Any]],
    kinds: list[str],
    chat_fn: ChatFn,
    draws: int = 1,
    blinding: str | None = None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Run the confounding diagnostic: fill covariates at randomized prices.

    For each product, level and covariate kind the model gets draws chat calls
    that ask it to fill in that one covariate given the current price. Every
    successfully parsed answer becomes a flat record {design.variable: level,
    kind: filled number} plus the product and category being probed — the
    shape randomization.check_confounding consumes (its numeric keys), with
    the product columns kept so within-product correlation stays possible.
    Answers that do not parse to a number are dropped, because a missing
    value cannot be correlated with the treatment.
    """
    mode = design.blinding if blinding is None else blinding
    system = _system_prompt(design, mode)
    rng = _seeded_rng(design, seed)
    levels = design.grid()
    records: list[dict[str, Any]] = []
    for product in products:
        for level in levels:
            for kind in kinds:
                value = (
                    level
                    if design.distribution == "grid"
                    else rng.uniform(design.min_value, design.max_value)
                )
                price = _price_for_level(product["regular_price"], value)
                user = build_covariate_fillin_prompt(
                    kind, product["category"], product["product"], price
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
                for _ in range(draws):
                    raw = chat_fn(messages, _TEMPERATURE)
                    filled = parse_fillin_number(raw)
                    if filled is not None:
                        records.append(
                            {
                                design.variable: value,
                                kind: filled,
                                "product": product["product"],
                                "category": product["category"],
                            }
                        )
    return records


def summarize_confounding(
    records: list[dict[str, Any]], design: RandomizationDesign
) -> dict[str, dict[str, float | str]]:
    """Summarize confounding for every numeric covariate kind in the records.

    Each record must hold the treatment under design.variable and one or more
    numeric covariate keys. Kinds are inferred as every numeric record key
    other than the design variable — non-numeric context columns (product,
    category, and the like) are ignored because a string column cannot be
    rank-correlated with the treatment. Each kind is correlated with the
    treatment through randomization.check_confounding, so the report carries
    rho, its bootstrap confidence interval, and the ok/mild/severe flag —
    never a p-value.
    """
    kinds = sorted(
        {
            key
            for record in records
            for key, value in record.items()
            if key != design.variable
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
    )
    summary: dict[str, dict[str, float | str]] = {}
    for kind in kinds:
        with_kind = [record for record in records if kind in record]
        summary[kind] = check_confounding(with_kind, design.variable, kind)
    return summary


def write_manifest(
    path: str | Path,
    design: RandomizationDesign,
    model: str,
    draws: int,
    blinding: str | list[str],
    products: list[dict[str, Any]],
    base_url: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a JSON run manifest describing one sweep, then return its path.

    A single-condition run stores the design JSON and the blinding string. A
    multi-condition run (blinding as a list, as the CLI passes for "both")
    stores blinding_scope and one design per condition under "designs", each
    entry's blinding matching its key — a "both" run can no longer leave one
    unblinded design describing both conditions. Both layouts keep the run
    metadata, an ISO-8601 written-at timestamp, and any extra keys merged at
    the top level. It never shells out (no git SHA, no network) so it works
    offline and in tests.
    """
    written_at = datetime.now(timezone.utc).isoformat()
    if isinstance(blinding, str):
        payload: dict[str, Any] = {
            "design": design.to_json(),
            "model": model,
            "draws": draws,
            "blinding": blinding,
            "products": products,
            "base_url": base_url,
            "written_at": written_at,
        }
    else:
        scope = list(blinding)
        payload = {
            "blinding_scope": scope,
            "designs": {
                condition: replace(design, blinding=condition).to_json()
                for condition in scope
            },
            "model": model,
            "draws": draws,
            "products": products,
            "base_url": base_url,
            "written_at": written_at,
        }
    if extra:
        payload.update(extra)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target
