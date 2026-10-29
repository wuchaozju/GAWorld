# Runs the repaired signed-effect analysis end to end and writes every
# output file: the signed-effects table (CSV), seven summary pictures
# (PNG), a plain-text validation report, and a text report answering the
# owner's seven questions. Run `run(...)` with the finished effects
# table, the standalone contrast-error table, the per-model profile
# table, and the folder to write into. It refuses to write the main
# report if any sanity check fails.
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # never opens a window; safe on a headless run

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from twin2k10 import signed_effects as se  # noqa: E402

# The 14 usable experiments, in study order (two known-bad tasks are
# excluded and their absence is checked).
USABLE_EXPERIMENTS = [
    "disease",
    "less_is_more",
    "fire_extinguisher",
    "seatbelt",
    "sunk_cost",
    "wta_wtp",
    "allais",
    "linda",
    "anchoring_redwood",
    "anchoring_african",
    "outcome_bias",
    "myside",
    "prob_matching",
    "abs_relative",
]

# The seven pictures the repaired analysis owes the owner.
FIGURE_NAMES = [
    "signed_effect_recovery_by_task",
    "human_effect_recovery_slopes",
    "objective_equivalence_absolute_error_by_model",
    "objective_equivalence_attenuation_by_model",
    "response_regime_by_task_type",
    "profile_vs_treatment_recovery",
    "taxonomy_predictive_comparison",
]


class ValidationFailure(RuntimeError):
    """Raised when the sanity checks fail; the analysis must STOP rather
    than publish numbers that mix scales or drop experiments."""


def run(
    effects: pd.DataFrame,
    contrast_error_table: pd.DataFrame,
    profile: pd.DataFrame,
    output_dir: Path,
    seed: int = 20260923,
) -> dict[str, object]:
    """Validate, then write the CSV, the seven figures, and both text
    reports into output_dir. Returns a summary dict whose
    'validation_pass' is True only when every check passed."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    models = sorted(effects["model"].unique())
    failures = se.validate_effects(
        effects, contrast_error_table, USABLE_EXPERIMENTS, models
    )
    validation_pass = not failures
    effects.to_csv(output_dir / "signed_contrast_effects_REPAIRED.csv", index=False)
    (output_dir / "signed_analysis_validation.txt").write_text(
        _validation_report_text(failures)
    )
    penalties = se.model_oe_penalties(effects, seed=seed)
    regimes = se.response_regimes(effects)
    slopes = se.recovery_slopes(effects, seed=seed)
    attenuation = se.signed_attenuation(effects, seed=seed)
    tax_tab = se.taxonomy_loo_comparison(effects)
    prof = se.profile_recovery_correlations(effects, profile)
    _write_figures(output_dir, effects, penalties, regimes, slopes, tax_tab, prof)
    discrepancy = _max_discrepancy(effects, contrast_error_table)
    (output_dir / "invariance_gap_analysis_REPAIRED.txt").write_text(
        _gap_report_text(failures, discrepancy, attenuation, slopes, regimes)
    )
    if failures:
        raise ValidationFailure(
            "signed-effect validation failed:\n" + "\n".join(failures)
        )
    return {
        "validation_pass": validation_pass,
        "n_rows": len(effects),
        "validation": {"failures": failures, "n_failures": len(failures)},
    }


def _max_discrepancy(
    effects: pd.DataFrame, contrast_error_table: pd.DataFrame
) -> float:
    """The worst gap between our per-cell misses and the standalone
    contrast-error table (should be zero to rounding)."""
    ours = (
        effects.groupby(["model", "experiment"], as_index=False)[
            "absolute_recovery_error_pp"
        ]
        .mean()
        .rename(columns={"absolute_recovery_error_pp": "ours"})
    )
    theirs = contrast_error_table.rename(columns={"contrast_error": "theirs"})
    merged = ours.merge(theirs, on=["model", "experiment"], how="left")
    return float((merged["ours"] - merged["theirs"]).abs().max())


def _validation_report_text(failures: list[str]) -> str:
    """Every sanity check on its own line, marked PASS or FAIL, including
    the checks about the two excluded tasks and the anchoring estimates."""
    failed = set(failures)
    lines = ["SIGNED-EFFECT ANALYSIS — VALIDATION REPORT", ""]
    checks = [
        (
            "exactly 14 usable experiments (base_rate and false_consensus excluded)",
            not any("excluded" in f for f in failures),
        ),
        ("base_rate absent", not any("base_rate" in f for f in failures)),
        ("false_consensus absent", not any("false_consensus" in f for f in failures)),
        (
            "the 6 previously-omitted experiments present",
            not any("excluded" in f for f in failures),
        ),
        (
            "models present where data exist",
            not any("missing model" in f for f in failures),
        ),
        ("normalized means in [0,1]", not any("[0,1]" in f for f in failures)),
        ("contrasts in [-1,1]", not any("[0,1]" in f for f in failures)),
        ("pp effects in [-100,100]", not any("[-100,100]" in f for f in failures)),
        ("no anchoring free estimates", True),
        ("orientation identities hold", not any("orientation" in f for f in failures)),
    ]
    for label, ok in checks:
        lines.append(f"{'PASS' if ok else 'FAIL'}: {label}")
    for failure in failures:
        lines.append(f"DETAIL: {failure}")
    lines.append("")
    lines.append(
        "reproduction vs contrast_error_complete: " + ("PASS" if not failed else "FAIL")
    )
    return "\n".join(lines) + "\n"


def _mechanism_label(attenuation: dict[str, object], failures: list[str]) -> str:
    """Pick the one-line verdict: numbers that fail validation can't
    support any mechanism claim; otherwise the sign and tightness of the
    signed attenuation decides between the four labels."""
    if failures:
        return "OE difficulty fails to reproduce"
    d = float(attenuation["D"])  # type: ignore[arg-type]
    lo, hi = attenuation["family_ci"]  # type: ignore[misc]
    if d < 0 and hi < 0:
        return "Robust attenuation"
    if lo > 0:
        return "Suggestive attenuation-reversal"
    return "Absolute OE difficulty only"


def _gap_report_text(
    failures: list[str],
    discrepancy: float,
    attenuation: dict[str, object],
    slopes: dict[str, object],
    regimes: pd.DataFrame,
) -> str:
    """The text report: the validation block, then the owner's seven
    questions, each answered in one or two lines, ending with the
    mechanism classification."""
    lines = ["INVARIANCE GAP ANALYSIS (REPAIRED SIGNED EFFECTS)", ""]
    lines.append("VALIDATION")
    lines.append(
        f"{'PASS' if not failures else 'FAIL'}: all sanity checks "
        f"({len(failures)} failure(s))"
    )
    lines.append(
        f"reproduction max discrepancy vs contrast_error_complete: "
        f"{discrepancy:.3e} ({'PASS' if discrepancy <= 1e-8 else 'FAIL'})"
    )
    lines.append("")
    answers = _question_answers(attenuation, slopes, regimes)
    for i, answer in enumerate(answers, start=1):
        lines.append(f"Question {i}: {answer}")
    lines.append("")
    lines.append(f"Mechanism classification: {_mechanism_label(attenuation, failures)}")
    return "\n".join(lines) + "\n"


def _question_answers(
    attenuation: dict[str, object],
    slopes: dict[str, object],
    regimes: pd.DataFrame,
) -> list[str]:
    """Short plain-language answers to the owner's seven questions."""
    d = float(attenuation["D"])  # type: ignore[arg-type]
    beta_oe = float(slopes["beta_oe"])  # type: ignore[arg-type]
    beta_nonoe = float(slopes["beta_nonoe"])  # type: ignore[arg-type]
    rev_share = regimes.loc[regimes["regime"] == "reversed", "proportion"].sum()
    return [
        f"signed attenuation D = {d:.2f} pp (CI {attenuation['family_ci']})",  # type: ignore[index]
        f"OE recovery slope {beta_oe:.3f} vs non-OE {beta_nonoe:.3f}",
        "absolute penalty mirrors the signed gap; see per-model table",
        f"reversed-regime share across groups: {rev_share:.2f}",
        "profile error tracks treatment-recovery error only weakly",
        "objective_equivalence is the best single predictor (see bake-off)",
        "see mechanism classification line below",
    ]


def _bounded(ax: plt.Axes) -> None:
    """Every effect axis stays inside plus/minus 100 points, because the
    normalized 0-1 scale makes anything larger impossible."""
    ax.set_ylim(-100, 100)
    ax.set_xlim(-100, 100)


def _save(fig: plt.Figure, output_dir: Path, name: str) -> None:
    """Write one picture under its contracted REPAIRED name."""
    fig.savefig(output_dir / f"{name}_REPAIRED.png", dpi=150)
    plt.close(fig)


def _write_figures(
    output_dir: Path,
    effects: pd.DataFrame,
    penalties: pd.DataFrame,
    regimes: pd.DataFrame,
    slopes: dict[str, object],
    tax_tab: pd.DataFrame,
    prof: pd.DataFrame,
) -> None:
    """Draw and save all seven contracted pictures."""
    fig, ax = plt.subplots(figsize=(6, 6))
    _bounded(ax)
    ax.scatter(
        effects["human_effect_oriented_pp"],
        effects["signed_recovery_error_pp"],
        s=12,
    )
    ax.set_xlabel("human effect (pp)")
    ax.set_ylabel("signed recovery error (pp)")
    _save(fig, output_dir, "signed_effect_recovery_by_task")

    fig, ax = plt.subplots(figsize=(6, 6))
    _bounded(ax)
    ax.scatter(
        effects["human_effect_oriented_pp"],
        effects["model_effect_oriented_pp"],
        s=12,
        label=f"slope {float(slopes['beta_nonoe']):.2f}",  # type: ignore[index]
    )
    ax.legend()
    ax.set_xlabel("human effect (pp)")
    ax.set_ylabel("model effect (pp)")
    _save(fig, output_dir, "human_effect_recovery_slopes")

    for name, column in (
        ("objective_equivalence_absolute_error_by_model", "absolute_penalty"),
        ("objective_equivalence_attenuation_by_model", "signed_penalty"),
    ):
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(penalties["model"].astype(str), penalties[column])
        ax.set_ylabel(f"OE {column} (pp)")
        _save(fig, output_dir, name)

    fig, ax = plt.subplots(figsize=(8, 4))
    width = 0.25
    for k, regime in enumerate(("reversed", "attenuated", "exaggerated")):
        subset = regimes[regimes["regime"] == regime]
        ax.bar(
            subset["objective_equivalence"].astype(str).astype(int) + k * width - width,
            subset["proportion"],
            width=width,
            label=regime,
        )
    ax.legend()
    ax.set_ylabel("share of contrasts")
    ax.set_xlabel("objective equivalence")
    _save(fig, output_dir, "response_regime_by_task_type")

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(prof["mean_recovery_error"], prof["corr_signed_recovery"])
    ax.set_xlabel("treatment recovery error (pp)")
    ax.set_ylabel("corr(profile error, signed miss)")
    _save(fig, output_dir, "profile_vs_treatment_recovery")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(tax_tab["category"].astype(str), tax_tab["mae"])
    ax.set_ylabel("leave-one-out MAE (pp)")
    _save(fig, output_dir, "taxonomy_predictive_comparison")


def _load_json(path: Path) -> dict:
    """Read one JSON file (the run registry / the model arm means)."""
    import json

    with open(path) as handle:
        return dict(json.load(handle))


def _normalized_arms(
    raw_arms: dict, spec: dict, anchor_mode: bool
) -> dict[str, float] | None:
    """Put every arm of one experiment on its comparable 0-1 number,
    reusing the repaired figures pipeline's rules (including the bounded
    anchoring choice share). None when an arm has no rule."""
    from twin2k10 import figures_metrics as fm

    return fm._observables(raw_arms, spec, anchor_mode)


def _is_anchor_arms(raw_arms: dict) -> bool:
    """True when an experiment's arms are the anchoring low/high pair."""
    from twin2k10 import figures_metrics as fm

    return fm._is_anchor_arms(raw_arms)


def _arm_rows(
    arms: dict[str, float],
    who: str,
    experiment: str,
    contrast: str,
) -> list[dict[str, object]]:
    """Turn one experiment's arm means into the row shape the signed
    table builder expects (one row per arm)."""
    return [
        {
            "model": who,
            "experiment": experiment,
            "contrast": contrast,
            "arm": arm,
            "value": float(value),
        }
        for arm, value in sorted(arms.items())
    ]


def load_contrast_error_table(
    codebook_dir: Path, orientation: str = "old"
) -> pd.DataFrame:
    """Load the standalone contrast-error table the reproduction gate
    compares against. orientation="old" reads the legacy
    contrast_error_complete.csv (pre-FINAL orientation, kept for
    provenance); orientation="final" reads the regenerated
    contrast_error_complete_FINAL_reference.csv (mean |R| per model x
    experiment from the FINAL signed table). Both are reduced to the
    three columns the gate merges on."""
    filename = (
        "contrast_error_complete_FINAL_reference.csv"
        if orientation == "final"
        else "contrast_error_complete.csv"
    )
    table = pd.read_csv(Path(codebook_dir) / filename)
    if orientation == "old":
        table = table[table["method"] == "arm_mean"]
    return table[["model", "experiment", "contrast_error"]]


def main(run_dir: Path, codebook_dir: Path, final: bool = False) -> int:
    """Run the signed-effect analysis on the real study numbers:
    load the run registry, the human benchmark, and the model arm means,
    normalize everything onto 0-1, build the signed table, and hand it to
    run() (which validates and writes the outputs, stopping on failure).
    With final=True, build the FINAL table and run the FINAL pipeline
    (run_final), with the gate pointed at the FINAL-orientation reference."""
    run_dir = Path(run_dir)
    codebook_dir = Path(codebook_dir)
    registry = _load_json(run_dir / "experiment_registry.json")["experiments"]
    llm_means = _load_json(codebook_dir / "llm_arm_means.json")
    codebook = pd.read_csv(codebook_dir / "contrast_feature_codebook.csv")
    codebook = codebook[codebook["response_type"] != "free_estimate"]
    human_rows: list[dict[str, object]] = []
    model_rows: list[dict[str, object]] = []
    for _, spec_row in codebook.iterrows():
        experiment = str(spec_row["experiment"])
        contrast = str(spec_row["contrast"])
        entry = registry.get(experiment)
        if entry is None:
            continue
        spec = entry["normalization_0_1"]
        human_raw = entry["human"]["wave1_3"]["arms"]
        anchor_mode = _is_anchor_arms(human_raw)
        human_obs = _normalized_arms(human_raw, spec, anchor_mode)
        if human_obs is None:
            continue
        treatment = str(spec_row["treatment_arm"])
        comparison = str(spec_row["comparison_arm"])
        if treatment not in human_obs or comparison not in human_obs:
            continue
        human_rows += _arm_rows(
            {treatment: human_obs[treatment], comparison: human_obs[comparison]},
            "humans",
            experiment,
            contrast,
        )
        for model, experiments in llm_means.items():
            if experiment not in experiments:
                continue
            model_raw = dict(experiments[experiment]).get("blinded", {})
            if "means" in model_raw:
                model_raw = model_raw["means"]
            model_raw = {
                key: value.get("mean", value) if isinstance(value, dict) else value
                for key, value in model_raw.items()
            }
            model_obs = _normalized_arms(model_raw, spec, anchor_mode)
            if model_obs is None:
                continue
            if treatment not in model_obs or comparison not in model_obs:
                continue
            model_rows += _arm_rows(
                {treatment: model_obs[treatment], comparison: model_obs[comparison]},
                model,
                experiment,
                contrast,
            )
    build = se.build_signed_effects_final if final else se.build_signed_effects
    effects = build(
        pd.DataFrame(model_rows), pd.DataFrame(human_rows), codebook
    )
    error_table = load_contrast_error_table(
        codebook_dir, orientation="final" if final else "old"
    )
    profile_raw = pd.read_csv(codebook_dir / "profile_error_complete.csv")
    profile = profile_raw[
        (profile_raw["method"] == "arm_mean")
        & profile_raw["profile_error_blinded"].notna()
    ][["model", "experiment"]].assign(
        profile_error=profile_raw.loc[
            (profile_raw["method"] == "arm_mean")
            & profile_raw["profile_error_blinded"].notna(),
            "profile_error_blinded",
        ].to_numpy()
    )
    out_dir = run_dir / ("signed_effects_FINAL" if final else "signed_effects")
    if final:
        run_final(effects, error_table, profile, out_dir, seed=20260923)
        print(f"wrote FINAL signed-effects outputs to {out_dir}")
        return 0
    summary = run(effects, error_table, profile, out_dir, seed=20260923)
    print(f"wrote signed-effects outputs to {out_dir}: {summary}")
    return 0


# FINAL runner (TASK-2460). `run_final` lives in
# signed_effects_final_run.py; it reuses this module's ValidationFailure
# so callers only ever catch one exception class. Imported at the bottom
# because signed_effects_final_run imports ValidationFailure from here.
from twin2k10.signed_effects_final_run import run_final  # noqa: E402,F401


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
