# This file executes one study cell: it turns a (model, persona,
# experiment, arm, blinding) cell into the exact prompts, makes ONE
# first-token scorer call per item of the arm in survey order (a choice
# item on its letter prompt, a digit item on its own rating/estimate
# prompt), folds every call's top-k into that item's label distribution,
# and stamps the full record the study's schema asks for: the choice
# item's fields at the top level and every digit item under
# record["digit_items"]. A cell whose calls fail is still returned as a
# record — kept, flagged succeeded=False, with the error text — so a
# resumed run never re-hides a failure. This module holds no loop and no
# file writing; cells.py owns durability and resume.

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from logprob_scoring import make_first_token_scorer

from twin2k10 import (
    cells,
    config,
    experiments,
    prompts,
    registry,
    scoring,
)

# One cell of the study grid: (model, persona_id, experiment, arm, blind).
Cell = tuple


@dataclass(frozen=True)
class LegContext:
    """Everything one model's cell transport needs, fixed for the model.

    Fields:
      model      — the short study id (e.g. "gpt-oss-20b");
      model_id   — the manager registry id sent as the request's "model";
      base_url   — the llama-server root the calls go to;
      personas   — the shared persona pool (persona_id indexes this list);
      stimuli    — the shipped survey questions keyed by question id;
      inference  — the pinned inference-settings dict stamped on records.
    """

    model: str
    model_id: str
    base_url: str
    personas: list[dict]
    stimuli: dict[str, dict]
    inference: dict


def inference_settings(base_url: str) -> dict:
    """The pinned inference settings stamped on every record.

    seed is the study's design seed (config.SEED); the HTTP requests
    themselves carry the R1 first-token shape (temperature 1.0,
    max_tokens = scan window, logprobs + top_logprobs = top-k) without a
    request seed. There are no sampling knobs: every numeric answer is
    one deterministic first-token call.
    """
    return {
        "temperature": config.TEMPERATURE,
        "top_k": config.TOP_K,
        "scan_tokens": config.SCAN_TOKENS,
        "seed": config.SEED,
        "base_url": base_url,
        "logprob_mode": "first_token",
    }


def make_leg_context(model: str, base_url: str, personas: list[dict]) -> LegContext:
    """One model's frozen cell context: ids, pool, prompts, settings."""
    return LegContext(
        model=model,
        model_id=registry.manager_model_id(model),
        base_url=base_url,
        personas=personas,
        stimuli=experiments.load_stimuli(),
        inference=inference_settings(base_url),
    )


def make_scorer(context: LegContext) -> Callable:
    """The R1 first-token scorer for one model, with its control sequences.

    Built on logprob_scoring.make_first_token_scorer with the study's scan
    window (8), top-k coverage (100) and the model's control-token
    sequences from the registry map (gemma-4-26b-a4b's channel header).
    """
    return make_first_token_scorer(
        context.base_url,
        context.model_id,
        scan_tokens=config.SCAN_TOKENS,
        top_k=config.TOP_K,
        control_sequences=registry.control_sequences(context.model),
    )


def make_digit_scorer(context: LegContext) -> Callable:
    """The first-token scorer for digit items, with the deeper window.

    Identical to make_scorer except the scan window is the digit scan
    knob (config.DIGIT_SCAN_TOKENS = 16): Granite-style models write
    lead-in prose before the digit, so digit calls generate a deeper
    window for scoring.scan_digit_positions to walk. The choice scorer's
    window (8) never changes.
    """
    return make_first_token_scorer(
        context.base_url,
        context.model_id,
        scan_tokens=config.DIGIT_SCAN_TOKENS,
        top_k=config.TOP_K,
        control_sequences=registry.control_sequences(context.model),
    )


def prompt_sha256(system_prompt: str, user_prompt: str) -> str:
    """The audit hash of one prompt pair (house convention: system + US)."""
    return hashlib.sha256(
        (system_prompt + "\x1e" + user_prompt).encode("utf-8")
    ).hexdigest()


def _now_iso() -> str:
    """The current UTC time as an ISO-8601 string (record timestamps)."""
    return datetime.now(timezone.utc).isoformat()


def label_map(stimulus: dict) -> dict[str, str]:
    """What each answer letter showed in the prompt (letter -> option text).

    Mirrors the choice-question rendering in prompts.py; a question with
    no options (digit items) maps to an empty dict.
    """
    options = stimulus.get("options")
    labels = stimulus.get("labels")
    if not options or not labels:
        return {}
    return dict(zip(labels, options))


def _item_messages(
    system_prompt: str, persona: dict, experiment: str, arm: str, item: dict
) -> list[dict]:
    """One item's ready-to-send chat messages: system + its OWN user prompt.

    Each first-token item is asked on its own single-question prompt, so
    a rating call never sees another policy's statement and a digit
    estimate call never sees the anchor question.
    """
    user_prompt = prompts.build_user_prompt(persona, experiment, arm, item=item)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _run_item(scorer: Callable, messages: list[dict]) -> dict:
    """One first-token scorer call with its wall-clock time.

    Returns the scorer's raw result dict plus elapsed_seconds; anything
    that raises becomes a synthetic failed result instead of killing the
    leg (the failure stays visible on the record).
    """
    started = time.monotonic()
    try:
        raw = scorer(messages)
    except Exception as exc:  # noqa: BLE001 — surfaced on the record below
        raw = {
            "succeeded": False,
            "raw_logprob_response": f"{type(exc).__name__}: {exc}",
        }
    return {**raw, "elapsed_seconds": time.monotonic() - started}


def _score_item(experiment: str, item: dict, raw: dict) -> dict:
    """Fold one item's decision-position top-k into its label distribution.

    Uses the item's own labels (choice letters or digit labels) so a
    digit item scores through exactly the choice machinery — same floor,
    same branch mass, same payload keys.
    """
    return scoring.score_labels(
        raw.get("top_logprobs") or [],
        experiment,
        labels=tuple(item["labels"]),
        decision_position=raw.get("decision_position"),
        skipped_prefix=raw.get("skipped_prefix"),
        skipped_len=raw.get("skipped_len"),
    )


def _score_digit_item(experiment: str, item: dict, raw: dict) -> dict:
    """Score one digit item through the multi-position scan.

    Runs scoring.scan_digit_positions over every generated position's
    top-k and takes the item's p_raw / p_norm from the CHOSEN position's
    LEADING-digit distribution (keyed by the item's digit labels), so a
    model answering with multi-digit number tokens ("379") still fills
    the digit its token starts with — an all-None distribution is then
    impossible for a parseable answer. digit_mass stays the same scan
    mass preflight gates on; the audit fields (top_logprobs, skipped
    prefix/length) are stamped as before.
    """
    labels = tuple(item["labels"])
    positions = raw.get("per_position_top_k") or []
    if positions:
        scan = scoring.scan_digit_positions(positions, labels)
        index = scan["decision_position"]
        chosen = positions[index - 1] if index else []
        decision_position = index
    else:
        # No per-position window on this result (an offline fake or an
        # older transport): the decision-position top-k IS the scan.
        chosen = raw.get("top_logprobs") or []
        decision_position = raw.get("decision_position")
        scan = scoring.scan_digit_positions([chosen], labels)
    scored = scoring.score_labels(
        chosen,
        experiment,
        labels=labels,
        decision_position=decision_position,
        skipped_prefix=raw.get("skipped_prefix"),
        skipped_len=raw.get("skipped_len"),
    )
    scored["p_raw"] = scan["p_raw"]
    scored["p_norm"] = scan["p_norm"]
    scored["branch_mass"] = scan["digit_mass"]
    scored["low_branch_mass"] = scan["digit_mass"] < config.LOW_BRANCH_MASS_THRESHOLD
    scored["digit_mass"] = scan["digit_mass"]
    return scored


def _failed_text(raw: dict) -> str:
    """One failed call's error text (the exception, or a plain fallback)."""
    return raw.get("raw_logprob_response") or "call failed"


def _choice_part(
    experiment: str, scorer: Callable, items: list[dict], message_list: list[list[dict]]
) -> dict:
    """The choice-scoring fragment of one record (empty when no choice).

    Scores the arm's choice item with one first-token call; a failed
    call scores as "no letter found", which the preflight emptiness
    check flags.
    """
    for item, messages in zip(items, message_list):
        if item["kind"] != "choice":
            continue
        raw = _run_item(scorer, messages)
        scored = _score_item(experiment, item, raw)
        return {
            "choice_qid": item["qid"],
            **scored,
            "choice_succeeded": bool(raw.get("succeeded")),
            "choice_error": (None if raw.get("succeeded") else _failed_text(raw)),
            "choice_elapsed_seconds": float(raw["elapsed_seconds"]),
        }
    return {}


def _digit_part(
    experiment: str, scorer: Callable, items: list[dict], message_list: list[list[dict]]
) -> list[dict]:
    """One digit_items entry per digit item of the arm, in survey order.

    Each entry is one item's own label distribution plus its own prompt
    audit pair — the same payload shape a choice record carries, so a
    rating distribution reads exactly like a letter distribution.
    """
    entries: list[dict] = []
    for item, messages in zip(items, message_list):
        if item["kind"] != "digit":
            continue
        raw = _run_item(scorer, messages)
        scored = _score_digit_item(experiment, item, raw)
        succeeded = bool(raw.get("succeeded"))
        entries.append(
            {
                "qid": item["qid"],
                "row": item["row"],
                "statement": item["statement"],
                "user_prompt": messages[-1]["content"],
                "prompt_sha256": prompt_sha256(
                    messages[0]["content"], messages[-1]["content"]
                ),
                **scored,
                "succeeded": succeeded,
                "error": None if succeeded else _failed_text(raw),
                "elapsed_seconds": float(raw["elapsed_seconds"]),
            }
        )
    return entries


def _base_record(
    context: LegContext,
    cell: Cell,
    arm_qids: tuple[str, ...],
    system_prompt: str,
    user_prompt: str,
) -> dict:
    """The identity-and-prompt head of one record.

    Stamps the run-level fields (model ids, prompts, their hash, the
    arm's question ids, the label map) that every part of the record
    shares. The record-level user prompt is the arm's FIRST item's
    prompt — every item's own prompt is stamped on the item itself (the
    choice part's fields, or the digit_items entries).
    """
    _model, persona_id, experiment, arm, blind = cell
    first_choice = next(
        (
            context.stimuli[qid]
            for qid in arm_qids
            if context.stimuli[qid]["response_kind"] == "choice"
        ),
        None,
    )
    return {
        "model_id": context.model_id,
        "experiment": experiment,
        "arm": arm,
        "blind": blind,
        "qids": list(arm_qids),
        "qid": arm_qids[0],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_sha256": prompt_sha256(system_prompt, user_prompt),
        "options_original": (first_choice or {}).get("options"),
        "label_map": label_map(first_choice) if first_choice else {},
        "inference": context.inference,
        "timestamp": _now_iso(),
    }


def _audit_top_logprobs(choice: dict, digit_entries: list[dict]) -> list | None:
    """The canonical top_logprobs audit list for one record.

    A choice question's decision-position top-k wins; an arm without one
    contributes its first digit item's top-k, the same field shape every
    preflight record is judged on. None when the arm had no calls at all
    (never the case in practice).
    """
    if choice:
        return choice.get("top_logprobs")
    if digit_entries:
        return digit_entries[0]["top_logprobs"]
    return None


def _stamp_status(record: dict, choice: dict, digit_entries: list[dict]) -> None:
    """Stamp the record's footer: the success flag and the error text.

    succeeded is True only when EVERY first-token call behind the record
    (the choice call and every digit-item call) succeeded — one failing
    item fails the whole record, never a silent row. Failures surface as
    the kept record's error text so a resumed run never re-hides them.
    """
    problems: list[str] = []
    if choice and choice.get("choice_error"):
        problems.append(str(choice["choice_error"]))
    problems.extend(str(entry["error"]) for entry in digit_entries if entry["error"])
    record["succeeded"] = not problems
    record["error"] = (
        None
        if not problems
        else ("; ".join(problems) or f"{len(problems)} call(s) failed")
    )


def execute_cell(
    context: LegContext,
    scorer: Callable,
    cell: Cell,
    digit_scorer: Callable | None = None,
) -> dict:
    """Run one cell end to end and return its record (never raises).

    Builds the system prompt once and one prompt PER first-token item of
    the arm, makes exactly one scorer call per item in survey order, and
    stamps everything on one record: the choice item's fields at the top
    level, every digit item under digit_items. succeeded is True only
    when every call behind the record succeeded; failures keep their row
    with the error text so a resumed run never re-hides them.
    """
    _model, persona_id, experiment, arm, blind = cell
    arm_qids = experiments.EXPERIMENTS[experiment].arm_qids(arm)
    persona = context.personas[persona_id]
    items = experiments.arm_items(experiment, arm, context.stimuli)
    system_prompt = prompts.build_system_prompt(experiment, blind == "blinded")
    message_list = [
        _item_messages(system_prompt, persona, experiment, arm, item) for item in items
    ]
    record = _base_record(
        context, cell, arm_qids, system_prompt, message_list[0][-1]["content"]
    )
    choice = _choice_part(experiment, scorer, items, message_list)
    digit_entries = _digit_part(experiment, digit_scorer or scorer, items, message_list)
    record.update(choice)
    record["digit_items"] = digit_entries
    audit = _audit_top_logprobs(choice, digit_entries)
    if audit is not None:
        record["top_logprobs"] = audit
    _stamp_status(record, choice, digit_entries)
    return record


def make_transport(
    context: LegContext,
    on_record: Callable[[dict], None],
    scorer: Callable | None = None,
) -> Callable:
    """The cells.run_cells transport for one model: execute + notify.

    on_record fires after each cell's record exists (the runner uses it
    for progress counting); it never influences the record itself.
    scorer overrides the model's real HTTP callable (offline tests
    inject fakes here — the same injectable-transport pattern as the R1
    code).
    """
    if scorer is None:
        scorer = make_scorer(context)
        digit_scorer = make_digit_scorer(context)

    def transport(cell: Cell) -> dict:
        record = execute_cell(context, scorer, cell, digit_scorer=digit_scorer)
        on_record(record)
        return record

    return transport


def leg_cells(
    model: str, persona_ids: list[int], experiment: str, blind: str
) -> list[Cell]:
    """One leg's cells in pinned order: persona, then arm in registry order.

    Built with cells.enumerate_cells (single experiment map, single
    blinding filter) so a leg's cell list is the study's own enumeration.
    """
    planned = cells.enumerate_cells(
        models=[model],
        personas=persona_ids,
        experiments_map={experiment: experiments.EXPERIMENTS[experiment]},
    )
    return [cell for cell in planned if cell[4] == blind]


def leg_dir(run_root, model: str, experiment: str, blind: str):
    """One leg's directory: <root>/<safe_model>/<experiment>_<blind>."""
    from pathlib import Path

    return Path(run_root) / registry.safe_model_name(model) / f"{experiment}_{blind}"
