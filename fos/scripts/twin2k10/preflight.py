# This file is the twin2k10 study's preflight examiner. Its core is ONE
# pure function, decide(records), that takes the preflight records in
# memory and returns a stop-or-proceed verdict — touching no files and no
# network. It says STOP exactly on technical failure criteria: a record
# whose top-logprobs came back empty (the known GGUF failure signature),
# a choice record where no answer letter could be read, or a digit item
# whose pass/fail state drags the model's digit pass rate below the
# 0.90 gate (empty top-k is the one absolute transport failure; an
# all-None distribution with real top-k text is a rate-gated model
# failure per owner policy 2026-09-22). It
# never judges whether an answer is sensible, and sampling-era record
# fields are simply never inspected. The file also writes the preflight
# report and the skipped-models list the runner uses to leave broken
# models out of the full run.

import json
from datetime import datetime, timezone
from pathlib import Path

from twin2k10 import config


def _record_label(record: dict) -> str:
    """One record's short "who/what" tag for a stop reason line."""
    return f"{record.get('model')}/{record.get('experiment')}/{record.get('arm')}"


def _choice_reasons(record: dict) -> list[str]:
    """The stop reasons a record's choice-scoring fields give (may be []).

    Empty top-logprobs is the known GGUF failure signature. A p_raw where
    EVERY letter is None means no answer letter could be read at all — a
    single missing letter next to found ones is normal, not a failure.
    A digit-bearing record whose top_logprobs field is ABSENT (not empty)
    has no choice call of its own to judge — the digit items are judged
    on their own entries below.
    """
    reasons: list[str] = []
    has_digit_items = bool(record.get("digit_items"))
    if not record.get("top_logprobs") and not (
        has_digit_items and "top_logprobs" not in record
    ):
        reasons.append(
            f"{_record_label(record)}: empty top_logprobs at the decision "
            "position (GGUF failure signature)"
        )
    p_raw = record.get("p_raw")
    if p_raw and all(value is None for value in p_raw.values()):
        reasons.append(f"{_record_label(record)}: no answer letter readable in p_raw")
    return reasons


def _digit_reasons(record: dict) -> tuple[list[str], list[tuple[dict, str]]]:
    """One record's digit-item verdict: absolute reasons + weak items.

    Returns (reasons, outcomes): reasons are the absolute technical
    failures that stop a model at any pass rate; each outcome is a
    (item, passed, reason) triple for one rate-counted digit item —
    passed items carry reason None, failing items carry the reason the
    item failed (sub-gate mass, or no readable digit).

    Every digit_items entry is judged exactly like a choice record: its
    top-logprobs must be non-empty (empty is the GGUF failure signature
    — an absolute STOP). An all-None p_raw with REAL top_logprobs text
    is a MODEL-behavior failure (owner policy 2026-09-22): it is
    rate-counted as a failure and flagged, never an absolute STOP. A
    single weak digit next to found ones is normal, not a failure.
    Sampling-era record fields are never looked at.
    """
    reasons: list[str] = []
    outcomes: list[tuple[dict, bool, str | None]] = []
    for item in record.get("digit_items") or []:
        where = _item_label(record, item)
        if not item.get("top_logprobs"):
            reasons.append(
                f"{where}: empty top_logprobs at the decision "
                "position (GGUF failure signature)"
            )
            if "digit_mass" in item:
                outcomes.append(
                    (item, False, _digit_mass_reason(item, where))
                )
            continue
        if "digit_mass" in item:
            # Sub-gate mass: the all-None distribution is a symptom of
            # the same weakness, not a separate failure — the mass
            # reason (mass + position) is the item's failure reason.
            dominance_reason = _digit_mass_reason(item, where)
            if dominance_reason:
                outcomes.append((item, False, dominance_reason))
            elif _p_raw_all_none(item):
                outcomes.append(
                    (
                        item,
                        False,
                        f"{where}: no answer digit readable in the item's "
                        "p_raw",
                    )
                )
            else:
                outcomes.append((item, True, None))
            continue
        if _p_raw_all_none(item):
            outcomes.append(
                (
                    item,
                    False,
                    f"{where}: no answer digit readable in the item's "
                    "p_raw",
                )
            )
            continue
        # Legacy readable item: no mass gate to judge, counted as a
        # passing digit item in the rate.
        outcomes.append((item, True, None))
    return reasons, outcomes


def _p_raw_all_none(item: dict) -> bool:
    """Whether one digit item's p_raw exists but holds no readable digit."""
    p_raw = item.get("p_raw")
    return bool(p_raw) and all(value is None for value in p_raw.values())


def _digit_mass_reason(item: dict, where: str) -> str | None:
    """The sub-gate message for one scanned digit item (None if it passes).

    The item's digit_mass (the best position's total digit probability)
    must reach the dominance gate — below it the model never wrote a
    dominant digit anywhere in the scan window, and the message names
    the mass and position. Items without a digit_mass field (legacy
    shape) are never gated.
    """
    mass = item.get("digit_mass") or 0.0
    if mass >= config.DIGIT_MASS_PREFLIGHT_THRESHOLD:
        return None
    return (
        f"{where}: digit mass {mass:.2f} at best position "
        f"{item.get('decision_position')} is below the "
        f"{config.DIGIT_MASS_PREFLIGHT_THRESHOLD} dominance gate"
    )


def _item_label(record: dict, item: dict) -> str:
    """One digit item's short "who/what" tag for a stop reason line."""
    row = item.get("row")
    at = f" row {row}" if row is not None else ""
    return f"{_record_label(record)}: digit item {item.get('qid')}{at}"


def _digit_rate_verdict(
    stats: dict, reasons: list[str]
) -> dict[str, dict]:
    """Turn per-model digit tallies into the per_model verdict block.

    Each model gets its digit_pass_rate (dominant items over scanned
    items) and its flagged rows. A model below the DIGIT_PASS_RATE_GATE
    STOPs: its sub-gate items become stop reasons, and the rate-naming
    reason is appended last so the item messages stay first.
    """
    per_model: dict[str, dict] = {}
    for model, tally in stats.items():
        passed, total = tally["passed"], tally["total"]
        rate = passed / total if total else 1.0
        per_model[model] = {
            "digit_pass_rate": rate,
            "flagged": tally["flagged"],
        }
        if total and rate < config.DIGIT_PASS_RATE_GATE:
            reasons.extend(tally["dominance_reasons"])
            reasons.append(
                f"{model}: digit dominance pass rate {passed}/{total} = "
                f"{rate:.3f} is below the {config.DIGIT_PASS_RATE_GATE} "
                "gate (worst items named above)"
            )
    return per_model


def decide(records: list[dict]) -> dict:
    """The pure stop-or-proceed verdict over a batch of preflight records.

    Returns {"stop": bool, "reasons": list[str], "per_model": dict} —
    stop is True exactly when reasons is non-empty. Absolute technical
    failures stop at any rate; digit dominance is rate-gated per model:
    at or above DIGIT_PASS_RATE_GATE the weak items only WARN-flag,
    below it the model stops and the reason names the failing rate.
    Reads its arguments only: the same records always produce the same
    verdict, and calling it changes nothing.
    """
    reasons: list[str] = []
    stats: dict[str, dict] = {}
    for record in records:
        model = str(record.get("model"))
        tally = stats.setdefault(
            model,
            {"passed": 0, "total": 0, "flagged": [], "dominance_reasons": []},
        )
        reasons.extend(_choice_reasons(record))
        absolute, outcomes = _digit_reasons(record)
        reasons.extend(absolute)
        for item, passed, failure_reason in outcomes:
            tally["total"] += 1
            if passed:
                tally["passed"] += 1
                continue
            tally["flagged"].append(
                {
                    "qid": item.get("qid"),
                    "row": item.get("row"),
                    "digit_mass": item.get("digit_mass"),
                }
            )
            tally["dominance_reasons"].append(failure_reason)
    per_model = _digit_rate_verdict(stats, reasons)
    return {"stop": bool(reasons), "reasons": reasons, "per_model": per_model}


def _rate_block(records: list[dict]) -> dict[str, dict]:
    """The per-model rate/flagged block decide() computes, re-derived.

    The report writer and JSON writer receive plain reasons strings, so
    they re-run the pure decide() over the same records to recover each
    model's digit pass rate and flagged rows.
    """
    return decide(records)["per_model"]


def build_report(
    run_dir: Path, per_model: dict[str, list[dict]], verdict: dict[str, list[str]]
) -> str:
    """The PREFLIGHT_REPORT.md text: technical verdicts, no behaviour.

    per_model maps each model to its preflight records; verdict maps each
    STOP-flagged model to its reasons (a model absent from the verdict
    passed).
    """
    total = sum(len(records) for records in per_model.values())
    lines = [
        "# PREFLIGHT REPORT — twin2k10 (TECHNICAL CHECKS ONLY)",
        "",
        f"- run dir: `{run_dir}`",
        f"- finished: {datetime.now(timezone.utc).isoformat()}",
        f"- records: {total} (1 persona x 19 arms x 2 blind per model)",
        f"- models run: {len(per_model)}",
        "",
        "## Per-model verdicts",
        "",
    ]
    rates = _rate_block([r for rs in per_model.values() for r in rs])
    for model, records in per_model.items():
        reasons = verdict.get(model, [])
        rate = rates.get(model, {}).get("digit_pass_rate")
        rate_text = f" (digit pass rate {rate:.3f})" if rate is not None else ""
        lines.append(
            f"- {model}: {len(records)} records — "
            + ("PROCEED" if not reasons else "STOP")
            + rate_text
        )
        for reason in reasons:
            lines.append(f"  - {reason}")
        for row in rates.get(model, {}).get("flagged", []):
            mass = row.get("digit_mass")
            mass_text = f"{mass:.2f}" if mass is not None else "n/a"
            lines.append(
                f"  - WARN flagged: digit item {row.get('qid')} row "
                f"{row.get('row')} (digit mass {mass_text})"
            )
    lines += [
        "",
        "## Decision",
        "",
        (
            "- STOP — every model failed the technical preflight; the "
            "full run will not start."
        )
        if len(verdict) == len(per_model) and per_model
        else (
            "- PROCEED — full run starts without the STOP-flagged models "
            "listed in skipped_models.json."
        ),
        "- Preflight does NOT re-run its finished cells on resume; the "
        "full run skips every cell already durable in the leg files.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    preflight_dir: Path, per_model: dict[str, list[dict]], verdict: dict[str, list[str]]
) -> dict:
    """Examine a finished preflight and write its report + skip list.

    Writes PREFLIGHT_REPORT.md always, preflight_verdict.json with the
    per-model machine-readable rates + flagged rows, and
    skipped_models.json when any model is STOP-flagged, all into the
    run directory. Returns the verdict payload (also handy for logs).
    Records are read from the caller in memory — the leg files
    themselves were written by the runner's durable record loop.
    """
    preflight_dir = Path(preflight_dir)
    report = build_report(preflight_dir, per_model, verdict)
    (preflight_dir / "PREFLIGHT_REPORT.md").write_text(report, encoding="utf-8")
    rates = _rate_block([r for rs in per_model.values() for r in rs])
    (preflight_dir / "preflight_verdict.json").write_text(
        json.dumps({"per_model": rates}, indent=2) + "\n", encoding="utf-8"
    )
    if verdict:
        (preflight_dir / "skipped_models.json").write_text(
            json.dumps(
                {
                    "skipped_models": sorted(verdict),
                    "reason": "preflight technical failure (see PREFLIGHT_REPORT.md)",
                    "written": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {"verdict": verdict}
