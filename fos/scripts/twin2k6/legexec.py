# This file executes one study cell: it turns a (model, persona, experiment,
# arm, blinding) cell into the exact two prompts, sends them to the loaded
# model through the proven R1 first-token logprob scorer, folds the answer
# letters with the twin2k6 K-branch scoring, and stamps every audit field
# the study's record schema (spec §11) asks for. A cell whose call fails is
# still returned as a record — kept, flagged succeeded=False, with the error
# text — so a resumed run never re-hides a failure. This module holds no
# loop and no file writing; cells.py owns durability and resume.

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from logprob_scoring import make_first_token_scorer

from twin2k6 import cells, config, experiments, prompts, registry, scoring

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
    """The pinned inference settings stamped on every record (spec §11).

    seed is the study's design seed (config.SEED); the HTTP request itself
    carries exactly the R1 request shape (temperature 1.0, max_tokens =
    scan window, logprobs + top_logprobs = top-k).
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


def prompt_sha256(system_prompt: str, user_prompt: str) -> str:
    """The audit hash of one prompt pair (house convention: system + US)."""
    return hashlib.sha256(
        (system_prompt + "\x1e" + user_prompt).encode("utf-8")
    ).hexdigest()


def label_map(spec, stimulus: dict) -> dict[str, str]:
    """What each answer letter showed in the prompt (letter -> option text).

    Mirrors prompts._option_lines rendering: catalogue options verbatim,
    or the letter's scored value for the option-less sunk-cost question.
    """
    options = stimulus.get("options")
    if options is None:
        return {
            letter: str(spec.label_values[letter]) for letter in spec.label_letters
        }
    return {letter: option for letter, option in zip(spec.label_letters, options)}


def _now_iso() -> str:
    """The current UTC time as an ISO-8601 string (record timestamps)."""
    return datetime.now(timezone.utc).isoformat()


def _neutralize_failed(spec, scored: dict) -> dict:
    """Blank the scored-outcome numbers of a failed call (None, never 0.0).

    A failed call produced no measurement; keeping score_labels' zero-mass
    defaults would silently drag the analysis arm means toward zero. The
    audit fields (top_logprobs, decision position) stay exactly as scored.
    """
    scored[spec.outcome_field] = None
    scored["expected_response"] = None
    if spec.safe_letters is not None:
        scored["p_safe_raw"] = None
        scored["p_safe_norm"] = None
    return scored


def _failed_record(context: LegContext, cell: Cell, system_prompt: str,
                   user_prompt: str, error: str, elapsed: float) -> dict:
    """The kept-but-failed record for one cell whose call raised."""
    _model, _persona_id, experiment, arm, _blind = cell
    spec = experiments.EXPERIMENTS[experiment]
    stimulus = context.stimuli[dict(spec.arms)[arm]]
    return {
        "model_id": context.model_id,
        "qid": stimulus["qid"],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_sha256": prompt_sha256(system_prompt, user_prompt),
        "options_original": stimulus.get("options"),
        "label_map": label_map(spec, stimulus),
        "top_logprobs": [],
        "decision_position": None,
        "skipped_prefix": [],
        "skipped_len": None,
        "p_raw": {letter: None for letter in spec.label_letters},
        "p_norm": {letter: None for letter in spec.label_letters},
        "branch_mass": 0.0,
        spec.outcome_field: None,
        "expected_response": None,
        "low_branch_mass": True,
        "elapsed_seconds": elapsed,
        "timestamp": _now_iso(),
        "inference": context.inference,
        "succeeded": False,
        "error": error,
    }


def _call_scorer(scorer: Callable, messages: list[dict]) -> dict:
    """One scorer call with its wall-clock time, failures turned into rows.

    Returns the scorer's raw result dict plus elapsed_seconds; an OSError-
    style failure that make_first_token_scorer already flags (succeeded
    False) passes through, and anything that raises becomes a synthetic
    failed result instead of killing the leg.
    """
    started = time.monotonic()
    try:
        raw = scorer(messages)
    except Exception as exc:  # noqa: BLE001 — surfaced on the record below
        raw = {"succeeded": False, "raw_logprob_response": f"{type(exc).__name__}: {exc}"}
    return {**raw, "elapsed_seconds": time.monotonic() - started}


def execute_cell(context: LegContext, scorer: Callable, cell: Cell) -> dict:
    """Run one cell end to end and return its record (never raises).

    Builds the prompts, calls the scorer once, folds the K answer letters
    with twin2k6.scoring, and stamps the full spec-§11 field set. A failed
    call keeps its row: succeeded=False, the error text, and None (never
    0.0) in the scored-outcome fields the analysis averages.
    """
    _model, persona_id, experiment, arm, blind = cell
    spec = experiments.EXPERIMENTS[experiment]
    stimulus = context.stimuli[dict(spec.arms)[arm]]
    persona = context.personas[persona_id]
    system_prompt = prompts.build_system_prompt(experiment, blind == "blinded")
    user_prompt = prompts.build_user_prompt(persona, experiment, arm)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    raw = _call_scorer(scorer, messages)
    scored = scoring.score_labels(
        raw.get("top_logprobs") or [],
        experiment,
        decision_position=raw.get("decision_position"),
        skipped_prefix=raw.get("skipped_prefix"),
        skipped_len=raw.get("skipped_len"),
    )
    succeeded = bool(raw.get("succeeded"))
    record = {
        "model_id": context.model_id,
        "qid": stimulus["qid"],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "prompt_sha256": prompt_sha256(system_prompt, user_prompt),
        "options_original": stimulus.get("options"),
        "label_map": label_map(spec, stimulus),
        **scored,
        "expected_response": scored[spec.outcome_field],
        "elapsed_seconds": float(raw["elapsed_seconds"]),
        "timestamp": _now_iso(),
        "inference": context.inference,
        "succeeded": succeeded,
        "error": None if succeeded
        else (raw.get("raw_logprob_response") or "call failed"),
    }
    if not succeeded:
        _neutralize_failed(spec, record)
    return record


def make_transport(context: LegContext, on_record: Callable[[dict], None],
                   scorer: Callable | None = None) -> Callable:
    """The cells.run_cells transport for one model: execute + notify.

    on_record fires after each cell's record exists (the runner uses it
    for progress counting); it never influences the record itself.
    scorer overrides the model's real HTTP scorer (offline tests inject
    a fake here — the same injectable-transport pattern as the R1 code).
    """
    scorer = scorer if scorer is not None else make_scorer(context)

    def transport(cell: Cell) -> dict:
        record = execute_cell(context, scorer, cell)
        on_record(record)
        return record

    return transport


def leg_cells(model: str, persona_ids: list[int],
              experiment: str, blind: str) -> list[Cell]:
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


def leg_dir(run_root: Path, model: str, experiment: str, blind: str) -> Path:
    """One leg's directory: <root>/<safe_model>/<experiment>_<blind>."""
    return Path(run_root) / registry.safe_model_name(model) / f"{experiment}_{blind}"
