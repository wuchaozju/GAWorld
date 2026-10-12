# This file is the study's preflight examiner. After a preflight run (one
# persona answering every experiment arm, with and without the blinding
# note, on every model) it re-reads the kept records and judges each model
# on TECHNICAL grounds only — did the prompt render, was the exact survey
# wording present, did the model return readable top-logprobs at the
# decision position, are the letter probabilities saved. It never judges
# whether an answer is sensible. A model whose replies came back with
# EMPTY top-logprobs at the decision position (the known gemma-4-31b GGUF
# failure signature) is flagged "STOP — technical failure" and written to
# skipped_models.json so the full run can leave that model out. Preflight
# never starts the full run itself.

import json
from datetime import datetime, timezone
from pathlib import Path

from twin2k6 import experiments, prompts, scoring

# The one model whose control-token sequence the preflight watches for in
# the skipped-prefix audit (informational reporting, never a failure).
CONTROL_SEQUENCE_MODEL = "gemma-4-26b-a4b"


def _is_sha256(value) -> bool:
    """Whether a value looks like a hex sha256 digest (64 hex characters)."""
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def check_record(record: dict, stimuli: dict[str, dict]) -> dict[str, bool]:
    """The seven technical checks for one kept preflight record.

    All boolean, all mechanical: prompt renders (non-empty texts + sha),
    the arm's exact verbatim question is in the user prompt, every answer
    letter's option line is in the user prompt, top-logprobs came back at
    the decision position, a decision position was found, every allowed
    letter that appears in the top-k has its raw probability saved, and
    the branch mass is calculable (strictly between 0 and 1).
    """
    experiment = record["experiment"]
    spec = experiments.EXPERIMENTS[experiment]
    question = stimuli[record["qid"]]["question_text"]
    user_prompt = record["user_prompt"]
    letters_in_top_k = scoring._raw_letter_probabilities(
        record.get("top_logprobs") or [],
        scoring._stripped_form_to_letter(spec),
    )
    p_raw = record.get("p_raw") or {}
    return {
        "prompt_renders": bool(record.get("system_prompt"))
        and bool(user_prompt)
        and _is_sha256(record.get("prompt_sha256")),
        "exact_wording": question in user_prompt,
        "label_map_in_prompt": all(
            f"{letter}. {text}" in user_prompt
            for letter, text in (record.get("label_map") or {}).items()
        ),
        "top_logprobs_returned": bool(record.get("top_logprobs")),
        "decision_position_found": record.get("decision_position") is not None,
        "labels_saved": all(
            p_raw.get(letter) is not None for letter in letters_in_top_k
        ),
        "branch_mass_ok": 0.0 < float(record.get("branch_mass") or 0.0) <= 1.0,
    }


def _mean_branch_mass(records: list[dict]) -> float | None:
    """The mean branch mass over records that have one (None when no data)."""
    masses = [float(r["branch_mass"]) for r in records if r.get("branch_mass")]
    if not masses:
        return None
    return sum(masses) / len(masses)


def summarize_model(model: str, records: list[dict],
                    stimuli: dict[str, dict]) -> dict:
    """One model's technical summary: pass counts per check + STOP flag.

    A model is flagged STOP — technical failure exactly when ANY record
    came back with empty top-logprobs (the known GGUF failure signature);
    every other count is reported for the operator but only advises.
    """
    checks = [check_record(record, stimuli) for record in records]
    names = [
        "prompt_renders", "exact_wording", "label_map_in_prompt",
        "top_logprobs_returned", "decision_position_found", "labels_saved",
        "branch_mass_ok",
    ]
    empty_top_logprobs = sum(
        1 for record in records if not record.get("top_logprobs")
    )
    control_exercised = sum(
        1 for record in records
        if CONTROL_SEQUENCE_MODEL == record.get("model")
        and "<|channel>" in (record.get("skipped_prefix") or [])
    )
    with_prefix = sum(
        1 for record in records if record.get("skipped_prefix")
    )
    return {
        "model": model,
        "records": len(records),
        "succeeded": sum(1 for record in records if record.get("succeeded")),
        "checks": {
            name: sum(1 for check in checks if check.get(name)) for name in names
        },
        "empty_top_logprobs": empty_top_logprobs,
        "mean_branch_mass": _mean_branch_mass(records),
        "records_with_skipped_prefix": with_prefix,
        "control_sequence_exercised": control_exercised,
        "stop": empty_top_logprobs > 0,
    }


def leakage_check(personas: list[dict]) -> dict:
    """Whether any persona block could carry behavioural Twin2K fields.

    The persona pool must hold ONLY the 11 demographic fields prompts.py
    renders; anything extra (attitudes, product favourites, twin2k-specific
    measures) would leak study material into every prompt. Returns the
    verdict plus the offending key names when the check fails.
    """
    allowed = set(prompts.PERSONA_FIELDS)
    leaked = sorted(
        {key for persona in personas for key in persona if key not in allowed}
    )
    return {
        "ok": not leaked,
        "personas_checked": len(personas),
        "unexpected_fields": leaked,
    }


def _check_lines(summary: dict) -> list[str]:
    """The per-check markdown lines of one model's report section."""
    total = summary["records"] or 1
    mean_bm = summary["mean_branch_mass"]
    lines = [
        f"- prompt renders: {summary['checks']['prompt_renders']}/{total}",
        f"- exact Twin2K wording present: "
        f"{summary['checks']['exact_wording']}/{total}",
        f"- label mapping present in prompt: "
        f"{summary['checks']['label_map_in_prompt']}/{total}",
        f"- top-logprobs returned at decision position: "
        f"{summary['checks']['top_logprobs_returned']}/{total}",
        f"- decision position found: "
        f"{summary['checks']['decision_position_found']}/{total} "
        f"(records with a skipped control prefix: "
        f"{summary['records_with_skipped_prefix']}; "
        f"{CONTROL_SEQUENCE_MODEL} control sequence exercised: "
        f"{summary['control_sequence_exercised']})",
        f"- raw candidate probabilities saved for allowed labels: "
        f"{summary['checks']['labels_saved']}/{total}",
        f"- branch mass 0 < bm ≤ 1: {summary['checks']['branch_mass_ok']}/{total}"
        f"; mean branch_mass = "
        f"{round(mean_bm, 4) if mean_bm is not None else 'n/a'}",
    ]
    return lines


def build_report(summaries: list[dict], leakage: dict, header: dict) -> str:
    """The full PREFLIGHT_REPORT.md text (technical verdicts, no behaviour).

    header carries the run facts (mode, run dir, models, record count);
    summaries are the per-model technical summaries in run order.
    """
    lines = [
        "# PREFLIGHT REPORT — twin2k6 (TECHNICAL CHECKS ONLY)",
        "",
        f"- run dir: `{header['run_dir']}`",
        f"- finished: {datetime.now(timezone.utc).isoformat()}",
        f"- records: {header['records']} "
        "(1 persona × 16 arms × 2 blind × models run)",
        f"- models run: {len(summaries)}",
        "",
        "## Per-model verdicts",
        "",
        "| model | records | succeeded | empty top_logprobs | mean bm | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        verdict = "STOP — technical failure" if summary["stop"] else "ok"
        mean_bm = summary["mean_branch_mass"]
        lines.append(
            f"| {summary['model']} | {summary['records']} | "
            f"{summary['succeeded']} | {summary['empty_top_logprobs']} | "
            f"{'' if mean_bm is None else round(mean_bm, 4)} | {verdict} |"
        )
    lines += ["", "## Check details", ""]
    for summary in summaries:
        lines += [f"### {summary['model']}", *_check_lines(summary), ""]
    lines += [
        "## Leakage re-check",
        "",
        (
            f"OK — all {leakage['personas_checked']} pool personas carry "
            "only the 11 demographic fields; no behavioural Twin2K fields "
            "in any persona block."
        )
        if leakage["ok"]
        else (
            f"FAILED — unexpected persona fields found: "
            f"{leakage['unexpected_fields']}"
        ),
        "",
        "## Decision",
        "",
    ]
    stopped = [summary["model"] for summary in summaries if summary["stop"]]
    if stopped:
        lines += [
            f"- STOP — technical failure: {', '.join(stopped)} "
            "(empty top_logprobs at the decision position; recorded in "
            "skipped_models.json — do NOT change their prompts/decoding).",
            "",
        ]
    lines += [
        "- Preflight does NOT auto-launch the full run; the orchestrator "
        "decides.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(preflight_dir: Path, records_by_model: dict[str, list[dict]],
                  personas: list[dict], header: dict) -> dict:
    """Examine a finished preflight and write its report + skip list.

    Writes PREFLIGHT_REPORT.md and (when any model hit the failure
    signature) skipped_models.json into the preflight directory. Returns
    the summary payload (also handy for logs). Records are read from the
    caller in memory — the files themselves were written by the runner.
    """
    preflight_dir = Path(preflight_dir)
    stimuli = experiments.load_stimuli()
    summaries = [
        summarize_model(model, records, stimuli)
        for model, records in records_by_model.items()
    ]
    leakage = leakage_check(personas)
    report = build_report(summaries, leakage, header)
    (preflight_dir / "PREFLIGHT_REPORT.md").write_text(report, encoding="utf-8")
    stopped = [summary["model"] for summary in summaries if summary["stop"]]
    if stopped:
        (preflight_dir / "skipped_models.json").write_text(
            json.dumps({"skipped_models": stopped,
                        "reason": "empty top_logprobs at decision position",
                        "written": datetime.now(timezone.utc).isoformat()},
                       indent=2) + "\n",
            encoding="utf-8",
        )
    return {"summaries": summaries, "leakage": leakage, "stopped": stopped}
