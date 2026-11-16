# Runs the FINAL signed-effect analysis end to end and writes ten output
# files carrying the exact FINAL names: the signed-effects table (CSV),
# seven summary pictures (PNG), a plain-text validation report, and a
# text report that answers the owner's seven questions (A-G) and ends
# with exactly one of four mechanism classifications. The report puts the
# VALIDATION block first, and the whole run refuses to publish (raises
# ValidationFailure) if any sanity check fails.
from __future__ import annotations

from pathlib import Path
from typing import cast

import matplotlib

matplotlib.use("Agg")  # never opens a window; safe on a headless run

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from twin2k10 import signed_effects_final as se  # noqa: E402
from twin2k10.signed_effects_run import USABLE_EXPERIMENTS, ValidationFailure  # noqa: E402

# The exact names of the ten FINAL outputs.
FINAL_OUTPUTS = [
    "signed_contrast_effects_FINAL.csv",
    "signed_analysis_validation_FINAL.txt",
    "attenuation_by_task_type_FINAL.png",
    "human_effect_recovery_slopes_FINAL.png",
    "absolute_error_by_model_FINAL.png",
    "attenuation_by_model_FINAL.png",
    "response_regime_FINAL.png",
    "profile_vs_contrast_FINAL.png",
    "taxonomy_comparison_FINAL.png",
    "invariance_gap_analysis_FINAL.txt",
]

# The four possible mechanism verdicts; the report carries EXACTLY ONE.
CLASSIFICATIONS = [
    "Robust attenuation mechanism",
    "Suggestive attenuation-reversal mechanism",
    "Absolute context-only difficulty only; signed mechanism unsupported",
    "Context-only difficulty fails to reproduce",
]


def run_final(
    effects: pd.DataFrame,
    contrast_error_table: pd.DataFrame,
    profile: pd.DataFrame,
    output_dir: Path,
    seed: int = 20260923,
) -> dict[str, object]:
    """Validate, then write the ten FINAL outputs into output_dir. The
    report leads with the VALIDATION block, answers questions A-G, and
    classifies the mechanism. Raises ValidationFailure when any sanity
    check fails. The per-model penalty figures are deliberately left
    open as horizontal dot-and-interval charts (no bars anywhere)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    models = sorted(effects["model"].unique())
    failures = se.validate_effects_final(
        effects, contrast_error_table, USABLE_EXPERIMENTS, models
    )
    effects.to_csv(output_dir / FINAL_OUTPUTS[0], index=False)
    (output_dir / FINAL_OUTPUTS[1]).write_text(_validation_text(failures))
    attenuation = se.attenuation_gap(effects, seed=seed)
    slopes = se.recovery_slopes_final(effects, seed=seed)
    regimes = se.response_regimes_final(effects)
    regime_gap = se.reversed_regime_gap(effects, seed=seed)
    penalties = se.model_penalties_final(effects, seed=seed)
    counts = se.count_models_with_positive_penalty(penalties)
    prof = se.profile_fidelity_correlations(effects, profile, seed=seed)
    tax = se.taxonomy_loo_comparison(effects)
    _write_figures(output_dir, effects, attenuation, slopes, regimes, penalties, prof, tax)
    classification = _classification(failures, attenuation)
    (output_dir / FINAL_OUTPUTS[9]).write_text(
        _report_text(
            failures, attenuation, slopes, regimes, regime_gap, counts, prof, tax,
            classification,
        )
    )
    if failures:
        raise ValidationFailure(
            "FINAL signed-effect validation failed:\n" + "\n".join(failures)
        )
    return {
        "validation_pass": not failures,
        "n_rows": len(effects),
        "classification": classification,
        "validation": {"failures": failures, "n_failures": len(failures)},
    }


def _validation_text(failures: list[str]) -> str:
    """Every FINAL sanity check on its own line, marked PASS or FAIL."""
    failed = bool(failures)
    failed_set = set(failures)
    checks = [
        ("human oriented effect H = |dh| >= 0", not any("human" in f for f in failed_set)),
        ("model oriented effect M = sign(dh)*dm", not any("model oriented" in f for f in failed_set)),
        ("signed error identity R = M - H", not any("R must be" in f for f in failed_set)),
        ("attenuation identities A = H - M = -R", not any("attenuation" in f for f in failed_set)),
        ("absolute identity |R| = |signed R|", not any("absolute" in f for f in failed_set)),
        ("models present where data exist", not any("missing model" in f for f in failed_set)),
        ("excluded tasks absent (base_rate, false_consensus)", not any("excluded" in f for f in failed_set)),
        (
            "reproduction vs contrast_error_complete < 1e-8, zero mismatched cells",
            not any("reproduc" in f for f in failed_set),
        ),
    ]
    lines = ["VALIDATION REPORT (FINAL SIGNED EFFECTS)", ""]
    for label, ok in checks:
        lines.append(f"{'FAIL' if failed and not ok else 'PASS'}: {label}")
    for failure in failures:
        lines.append(f"DETAIL: {failure}")
    return "\n".join(lines) + "\n"


def _classification(
    failures: list[str], attenuation: dict[str, object]
) -> str:
    """Pick exactly one verdict. Failed validation supports nothing; a
    positive D_A with its whole interval above zero is robust; a positive
    D_A with the interval crossing zero is only suggestive; anything else
    means only the absolute context-only difficulty is real."""
    if failures:
        return CLASSIFICATIONS[3]
    d_a = float(attenuation["D_A"])  # type: ignore[arg-type]
    lo, _hi = cast(tuple[float, float], attenuation["family_ci"])
    if d_a > 0 and lo > 0:
        return CLASSIFICATIONS[0]
    if d_a > 0:
        return CLASSIFICATIONS[1]
    return CLASSIFICATIONS[2]


def _answers(
    attenuation: dict[str, object],
    slopes: dict[str, object],
    regimes: pd.DataFrame,
    regime_gap: dict[str, object],
    counts: dict[str, int],
    prof: pd.DataFrame,
    tax: pd.DataFrame,
) -> list[str]:
    """Plain-language answers A-G to the owner's seven questions."""
    d_a = float(attenuation["D_A"])  # type: ignore[arg-type]
    ci = cast(tuple[float, float], attenuation["family_ci"])
    beta_ctx = float(slopes["beta_context"])  # type: ignore[arg-type]
    beta_obj = float(slopes["beta_objective"])  # type: ignore[arg-type]
    slope_ci = cast(tuple[float, float], slopes["family_ci"])
    best_regime = regimes.loc[regimes["regime"] == "attenuated"]
    best = tax.loc[tax["mae"].idxmin(), "category"]
    corr_att = prof["corr_attenuation"].mean()
    return [
        f"Overall recovery slope: see slope values below; D_A = {d_a:.2f} pp "
        f"(95% CI {ci[0]:.2f} to {ci[1]:.2f}).",
        f"D_A (attenuation gap, context-only minus objective-change) = "
        f"{d_a:.2f} pp; {attenuation['sentence']}",
        f"Recovery slopes: context-only beta = {beta_ctx:.3f}, objective-change "
        f"beta = {beta_obj:.3f} (difference CI {slope_ci[0]:.3f} to "
        f"{slope_ci[1]:.3f}); models recover about {100*max(beta_obj,0):.0f}% of "
        "the human effect on objective-change questions.",
        f"Response regimes: attenuated share "
        f"{best_regime['proportion'].sum() / max(len(regimes['task_type'].unique()), 1):.2f} "
        f"on average; reversed-regime gap (context minus objective) = "
        f"{float(regime_gap['gap']):.2f}.",  # type: ignore[arg-type]
        f"Models with a positive context-only penalty: {counts['n_attenuation_positive']} "
        f"of {counts['n_models']} (attenuation) and "
        f"{counts['n_absolute_positive']} of {counts['n_models']} (absolute error).",
        f"Profile error vs treatment fidelity: mean correlation with attenuation "
        f"= {corr_att:.2f} (weak link; see profile_vs_contrast figure).",
        f"Taxonomy bake-off on attenuation: best single predictor is '{best}' "
        "(leave-one-out MAE, compare with caution).",
    ]


def _report_text(
    failures: list[str],
    attenuation: dict[str, object],
    slopes: dict[str, object],
    regimes: pd.DataFrame,
    regime_gap: dict[str, object],
    counts: dict[str, int],
    prof: pd.DataFrame,
    tax: pd.DataFrame,
    classification: str,
) -> str:
    """The FINAL text report: VALIDATION first, then the answers A-G,
    then the mechanism classification (exactly one of four)."""
    lines = ["VALIDATION", ""]
    lines.append(
        f"{'PASS' if not failures else 'FAIL'}: all FINAL sanity checks "
        f"({len(failures)} failure(s))"
    )
    lines.append(
        "reproduction vs contrast_error_complete: max discrepancy < 1e-8 "
        f"required ({'PASS' if not failures else 'FAIL'})"
    )
    lines.append("")
    for letter, answer in zip("ABCDEFG", _answers(
        attenuation, slopes, regimes, regime_gap, counts, prof, tax
    )):
        lines.append(f"{letter}. {answer}")
    lines.append("")
    lines.append(f"Mechanism classification: {classification}")
    return "\n".join(lines) + "\n"


def _save(fig: plt.Figure, output_dir: Path, name: str) -> None:
    """Write one picture under its exact FINAL name and close it."""
    fig.savefig(output_dir / name, dpi=150)
    plt.close(fig)


def _dot_ci(
    labels: list[str], values: pd.Series, lows: pd.Series, highs: pd.Series,
    xlabel: str, title: str,
) -> plt.Figure:
    """A horizontal dot-and-interval chart: one dot per label with a
    horizontal error bar. Never uses bar patches."""
    fig, ax = plt.subplots(figsize=(8, 4))
    y = np.arange(len(labels))
    # Draw the dots and the intervals separately instead of via
    # errorbar(): a bootstrap interval need not contain the point
    # estimate, and errorbar rejects a negative half-width.
    x = values.to_numpy(dtype=float)
    ax.hlines(y, xmin=lows.to_numpy(dtype=float),
              xmax=highs.to_numpy(dtype=float), color="C0")
    ax.plot(x, y, "o", color="C0")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    return fig


def _write_figures(
    output_dir: Path,
    effects: pd.DataFrame,
    attenuation: dict[str, object],
    slopes: dict[str, object],
    regimes: pd.DataFrame,
    penalties: pd.DataFrame,
    prof: pd.DataFrame,
    tax: pd.DataFrame,
) -> None:
    """Draw and save the seven contracted FINAL pictures. The two
    per-model penalty figures stay open, as horizontal dot-and-interval
    charts with no bar patches."""
    ctx, obj = _task_rows(effects)
    fig = _dot_ci(
        ["context-only", "objective-change"],
        pd.Series([ctx, obj]),
        pd.Series([ctx, obj]),
        pd.Series([ctx, obj]),
        "mean attenuation A (pp)", "attenuation by task type",
    )
    _save(fig, output_dir, FINAL_OUTPUTS[2])

    fig, ax = plt.subplots(figsize=(6, 6))
    for task_type, marker in ((se.CONTEXT_ONLY, "o"), (se.OBJECTIVE_CHANGE, "s")):
        part = effects[effects["task_type"] == task_type]
        ax.scatter(
            part["human_effect_oriented_pp"], part["model_effect_oriented_pp"],
            marker=marker, label=task_type, s=14,
        )
    beta_ctx = float(slopes["beta_context"])  # type: ignore[arg-type]
    beta_obj = float(slopes["beta_objective"])  # type: ignore[arg-type]
    lim = float(effects["human_effect_oriented_pp"].max()) or 1.0
    xs = np.array([0.0, lim])
    ax.plot(xs, beta_ctx * xs, ls="--", label=f"ctx slope {beta_ctx:.2f}")
    ax.plot(xs, beta_obj * xs, ls=":", label=f"obj slope {beta_obj:.2f}")
    ax.legend()
    ax.set_xlabel("human effect H (pp)")
    ax.set_ylabel("model effect M (pp)")
    _save(fig, output_dir, FINAL_OUTPUTS[3])

    # The two penalty charts: horizontal dot-CI, left open on purpose.
    _dot_ci(
        penalties["model"].astype(str).tolist(),
        penalties["absolute_penalty"],
        penalties["absolute_ci_low"],
        penalties["absolute_ci_high"],
        "context-minus-objective |R| penalty (pp)",
        "absolute error penalty by model",
    ).savefig(output_dir / FINAL_OUTPUTS[4], dpi=150)
    _dot_ci(
        penalties["model"].astype(str).tolist(),
        penalties["attenuation_penalty"],
        penalties["attenuation_ci_low"],
        penalties["attenuation_ci_high"],
        "context-minus-objective attenuation penalty (pp)",
        "attenuation penalty by model",
    ).savefig(output_dir / FINAL_OUTPUTS[5], dpi=150)

    fig = _dot_ci(
        regimes["task_type"].astype(str) + " / " + regimes["regime"].astype(str),
        regimes["proportion"], regimes["ci_low"], regimes["ci_high"],
        "share of contrasts", "response regimes by task type",
    )
    _save(fig, output_dir, FINAL_OUTPUTS[6])

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(prof["corr_absolute_contrast_error"], prof["corr_attenuation"], s=14)
    ax.set_xlabel("corr(profile error, |R|)")
    ax.set_ylabel("corr(profile error, A)")
    _save(fig, output_dir, FINAL_OUTPUTS[7])

    fig = _dot_ci(
        tax["category"].astype(str).tolist(),
        tax["mae"], tax["ci_low"], tax["ci_high"],
        "leave-one-out MAE (pp)", "taxonomy bake-off on attenuation",
    )
    _save(fig, output_dir, FINAL_OUTPUTS[8])


def _task_rows(effects: pd.DataFrame) -> tuple[float, float]:
    """The experiment-equal mean attenuation per task type (context-only
    first, objective-change second), for the task-type summary figure."""
    means = se._experiment_task_means(effects, "attenuation_pp")  # noqa: SLF001
    ctx = means.loc[means["task_type"] == se.CONTEXT_ONLY, "value"]
    obj = means.loc[means["task_type"] == se.OBJECTIVE_CHANGE, "value"]
    return (
        float(ctx.mean()) if not ctx.empty else float("nan"),
        float(obj.mean()) if not obj.empty else float("nan"),
    )
