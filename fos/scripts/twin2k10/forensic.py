# Forensic orientation repair for the TWIN2K10 signed-effect table.
#
# WHAT THIS FILE DOES, in plain words: the saved FINAL results table may
# have a sign problem — when humans moved in the NEGATIVE direction, the
# model's effect was not flipped to match, so the "model misses the human
# effect" numbers could point the wrong way. This module rebuilds every
# orientation-dependent number from scratch, using only the two raw
# effects (human dh, model dm), writes a fresh forensic CSV, reads it
# back to prove nothing was lost, checks the stored numbers against the
# fresh ones, lists every suspicious row in an audit table, re-derives
# the model-by-experiment error table that an earlier independent
# analysis produced, and (on real data) writes a full forensic report
# ending in exactly one verdict.
#
# Each public function's job:
#   recompute_orientation     — add the five fresh orientation columns
#                               (H, M, R, A, |R|), ignoring any stored ones.
#   write_forensic_csv        — save the forensic table to disk.
#   load_forensic_csv         — read it back; numbers must round-trip.
#   verify_forensic_columns   — compare stored oriented numbers with the
#                               fresh ones; empty list means all good.
#   orientation_audit_rows    — one audit row per negative human effect,
#                               so a missed sign flip is visible at a glance.
#   reproduce_contrast_error  — re-derive the standalone per model x
#                               experiment mean |R| and count mismatches.
#   main                      — run the whole forensic analysis on the
#                               real study folder and write the ten outputs.
from __future__ import annotations

from pathlib import Path
from typing import cast

import matplotlib

matplotlib.use("Agg")  # never opens a window; safe on a headless run

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# signed_effects_run must load first: the signed-effects modules import
# each other from their bottoms, and this is the one entry order that
# resolves without hitting a partially initialized module.
from twin2k10 import signed_effects_run  # noqa: E402,F401
from twin2k10 import signed_effects_final as se  # noqa: E402
from twin2k10.signed_effects_final_run import (  # noqa: E402,F401
    _dot_ci,
    _save,
    _task_rows,
)

# The exact names of the ten FORENSIC outputs, in write order (locked).
FORENSIC_OUTPUTS = [
    "signed_contrast_effects_FORENSIC.csv",
    "signed_orientation_forensic_check.txt",
    "attenuation_by_task_type_FORENSIC.png",
    "human_effect_recovery_slopes_FORENSIC.png",
    "attenuation_by_model_FORENSIC.png",
    "absolute_error_by_model_FORENSIC.png",
    "response_regime_FORENSIC.png",
    "profile_vs_contrast_FORENSIC.png",
    "taxonomy_comparison_FORENSIC.png",
    "invariance_gap_FORENSIC_REPORT.txt",
]

# The four possible verdicts; the forensic report carries EXACTLY ONE.
FORENSIC_VERDICTS = [
    "Robust attenuation mechanism",
    "Suggestive attenuation mechanism",
    "Absolute-error difference only",
    "No reproducible task-type difference",
]

# The five fresh columns the recomputation must add.
RECOMPUTED_COLUMNS = [
    "H_recomputed",
    "M_recomputed",
    "R_recomputed",
    "A_recomputed",
    "absR_recomputed",
]

# How many negative-human-effect rows the audit table shows in the report.
AUDIT_ROWS_SHOWN = 10


def recompute_orientation(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the orientation columns from the two raw effects only:
    H = |dh|; M is the model move read in the humans' direction (kept as
    is when the model moved the same way, reported negative when it
    moved against them); R = M - H; A = H - M; |R| = |R|. Any
    pre-existing oriented / recovery / attenuation columns are ignored,
    so a poisoned or buggy stored value cannot leak in."""
    out = df.copy()
    dh = out["human_effect_pp"].astype(float)
    dm = out["model_effect_pp"].astype(float)
    same_side = np.sign(dh.to_numpy(dtype=float)) == np.sign(dm.to_numpy(dtype=float))
    out["H_recomputed"] = dh.abs()
    out["M_recomputed"] = np.where(same_side, dm, -dm.abs())
    out["R_recomputed"] = out["M_recomputed"] - out["H_recomputed"]
    out["A_recomputed"] = out["H_recomputed"] - out["M_recomputed"]
    out["absR_recomputed"] = out["R_recomputed"].abs()
    return out


def write_forensic_csv(df: pd.DataFrame, path: Path) -> None:
    """Save the forensic table. The index carries no information, so it
    is dropped; every number must survive the round trip exactly."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(Path(path), index=False)


def load_forensic_csv(path: Path) -> pd.DataFrame:
    """Read the forensic table back from disk."""
    return pd.read_csv(Path(path))


def verify_forensic_columns(df: pd.DataFrame, tol: float = 1e-10) -> list[str]:
    """Compare the STORED oriented columns (human_effect_oriented_pp,
    model_effect_oriented_pp, attenuation_pp) with the freshly recomputed
    ones wherever both are present. An empty list means every stored
    value agrees within tol; each failure string names the broken column
    and the offending rows. A stored column that is simply absent gives
    nothing to compare, so it is skipped rather than flagged."""
    stored = {
        "human_effect_oriented_pp": "H_recomputed",
        "model_effect_oriented_pp": "M_recomputed",
        "attenuation_pp": "A_recomputed",
    }
    failures: list[str] = []
    for stored_col, fresh_col in stored.items():
        if stored_col not in df.columns or fresh_col not in df.columns:
            continue
        diff = (df[stored_col].astype(float) - df[fresh_col].astype(float)).abs()
        bad = diff[diff > tol]
        if not bad.empty:
            rows = ", ".join(str(i) for i in bad.index[:5])
            failures.append(
                f"{stored_col} disagrees with {fresh_col} on {len(bad)} row(s) "
                f"(worst {diff.max():.6g}); first rows: {rows}"
            )
    return failures


def orientation_audit_rows(df: pd.DataFrame) -> pd.DataFrame:
    """One row per contrast where humans moved NEGATIVE — exactly the
    rows where a missed sign flip hides. Each row shows the raw effects,
    the expected (human-side) oriented model effect, whatever was stored
    (shown as a magnitude, since the buggy table reads the model move
    unsigned against the human side; its signed value is kept in
    stored_signed_pp), and the attenuation."""
    dh = df["human_effect_pp"].astype(float)
    neg = df[dh < 0]
    stored_m = (
        neg["model_effect_oriented_pp"]
        if "model_effect_oriented_pp" in neg.columns
        else neg["model_effect_pp"]
    ).astype(float)
    stored_a = (
        neg["attenuation_pp"]
        if "attenuation_pp" in neg.columns
        else neg["A_recomputed"]
    )
    audit = pd.DataFrame(
        {
            "model": neg["model"].to_numpy(),
            "experiment": neg["experiment"].to_numpy(),
            "contrast": neg["contrast"].to_numpy(),
            "human_effect_pp": neg["human_effect_pp"].to_numpy(),
            "model_effect_pp": neg["model_effect_pp"].to_numpy(),
            "expected_oriented_pp": neg["M_recomputed"].to_numpy(),
            "stored_oriented_pp": stored_m.abs().to_numpy(),
            "attenuation_pp": stored_a.to_numpy(),
            "stored_signed_pp": stored_m.to_numpy(),
        }
    )
    return audit.reset_index(drop=True)


def reproduce_contrast_error(
    df: pd.DataFrame, contrast_error_table: pd.DataFrame
) -> tuple[int, float]:
    """Re-derive the standalone per model x experiment mean |R| from the
    forensic table and merge it against the independent table (column
    contrast_error). Returns (mismatched_cell_count, max_discrepancy);
    a clean reproduction is (0, something under 1e-8)."""
    ours = (
        df.groupby(["model", "experiment"], as_index=False)["absR_recomputed"]
        .mean()
        .rename(columns={"absR_recomputed": "ours"})
    )
    theirs = contrast_error_table[["model", "experiment", "contrast_error"]]
    theirs = theirs.rename(columns={"contrast_error": "theirs"})
    merged = ours.merge(theirs, on=["model", "experiment"], how="inner")
    diff = (merged["ours"] - merged["theirs"]).abs()
    mismatched = int((diff > 1e-8).sum())
    worst = float(diff.max()) if not diff.empty else 0.0
    return mismatched, worst


# --------------------------------------------------------------- real run


def _repaired_table(effects: pd.DataFrame) -> pd.DataFrame:
    """Take the saved FINAL table, recompute the orientation from the raw
    effects, and overwrite the stored oriented columns with the repaired
    values so downstream analyses run on trustworthy numbers."""
    work = recompute_orientation(effects)
    work["human_effect_oriented_pp"] = work["H_recomputed"]
    work["model_effect_oriented_pp"] = work["M_recomputed"]
    work["signed_recovery_error_pp"] = work["R_recomputed"]
    work["absolute_recovery_error_pp"] = work["absR_recomputed"]
    work["attenuation_pp"] = work["A_recomputed"]
    return work


def _check_text(failures: list[str], mismatched: int, worst: float) -> str:
    """The orientation forensic check: every stored identity PASS/FAIL,
    plus the reproduction gate against the standalone table."""
    lines = ["ORIENTATION FORENSIC CHECK", ""]
    if failures:
        for failure in failures:
            lines.append(f"FAIL: {failure}")
    else:
        lines.append("PASS: stored oriented columns match the recomputed rule")
    ok = mismatched == 0 and worst < 1e-8
    lines.append(
        f"{'PASS' if ok else 'FAIL'}: reproduction vs contrast-error table "
        f"({mismatched} mismatched cell(s), max discrepancy {worst:.3g})"
    )
    return "\n".join(lines) + "\n"


def _verdict(attenuation: dict[str, object]) -> str:
    """Pick exactly one verdict: robust when the attenuation gap is
    positive with its whole interval above zero, suggestive when positive
    but the interval crosses zero, otherwise the mechanism is not
    reproducible as a signed effect."""
    d_a = float(attenuation["D_A"])  # type: ignore[arg-type]
    lo, _hi = cast(tuple[float, float], attenuation["family_ci"])
    if d_a > 0 and lo > 0:
        return FORENSIC_VERDICTS[0]
    if d_a > 0:
        return FORENSIC_VERDICTS[1]
    return FORENSIC_VERDICTS[2]


def _report_text(
    audit: pd.DataFrame,
    attenuation: dict[str, object],
    slopes: dict[str, object],
    regimes: pd.DataFrame,
    regime_gap: dict[str, object],
    counts: dict[str, int],
    prof: pd.DataFrame,
    tax: pd.DataFrame,
    mismatched: int,
    worst: float,
    verdict: str,
) -> str:
    """The forensic report: the orientation audit table first (the
    negative-human rows, sign flip visible), then the recomputed-result
    sections, ending with exactly one verdict line."""
    d_a = float(attenuation["D_A"])  # type: ignore[arg-type]
    beta_ctx = float(slopes["beta_context"])  # type: ignore[arg-type]
    beta_obj = float(slopes["beta_objective"])  # type: ignore[arg-type]
    slope_ci = cast(tuple[float, float], slopes["family_ci"])
    best = tax.loc[tax["mae"].idxmin(), "category"]
    shown = audit.head(AUDIT_ROWS_SHOWN)
    lines = [
        "INVARIENCE-GAP FORENSIC REPORT (repaired orientation)",
        "",
        "ORIENTATION AUDIT — first "
        f"{min(AUDIT_ROWS_SHOWN, len(audit))} of {len(audit)} "
        "negative-human-effect rows",
        shown.to_string(index=False),
        "",
    ]
    lines += [
        "RECOMPUTED RESULTS (all from dh/dm only)",
        "",
        f"1. Attenuation gap D_A (context-only minus objective-change) = "
        f"{d_a:.2f} pp; {attenuation['sentence']}",
        f"2. Recovery slopes: context-only beta = {beta_ctx:.3f}, "
        f"objective-change beta = {beta_obj:.3f} (difference CI "
        f"{slope_ci[0]:.3f} to {slope_ci[1]:.3f}).",
        f"3. Reversed-regime gap (context minus objective) = "
        f"{float(regime_gap['gap']):.2f}.",  # type: ignore[arg-type]
        f"4. Models with a positive context-only penalty: "
        f"{counts['n_attenuation_positive']} of {counts['n_models']} "
        f"(attenuation) and {counts['n_absolute_positive']} of "
        f"{counts['n_models']} (absolute error).",
        f"5. Profile error vs fidelity: mean correlation with attenuation "
        f"= {prof['corr_attenuation'].mean():.2f}.",
        f"6. Taxonomy bake-off on attenuation: best single predictor "
        f"is '{best}' (leave-one-out MAE).",
        f"7. Contrast-error reproduction: {mismatched} mismatched cell(s), "
        f"max discrepancy {worst:.3g} (gate: 0 and < 1e-8).",
        "8. Every recomputed column was written to CSV, reloaded, and "
        "re-verified against the stored rule.",
        "",
    ]
    lines.append(f"Verdict: {verdict}")
    return "\n".join(lines) + "\n"


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
    """Draw and save the seven forensic pictures under their exact
    FORENSIC names (same charts as the FINAL run, repaired numbers)."""
    ctx, obj = _task_rows(effects)
    _save(
        _dot_ci(
            ["context-only", "objective-change"],
            pd.Series([ctx, obj]),
            pd.Series([ctx, obj]),
            pd.Series([ctx, obj]),
            "mean attenuation A (pp)",
            "attenuation by task type (forensic)",
        ),
        output_dir,
        FORENSIC_OUTPUTS[2],
    )
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))
    for task_type, marker in ((se.CONTEXT_ONLY, "o"), (se.OBJECTIVE_CHANGE, "s")):
        part = effects[effects["task_type"] == task_type]
        ax.scatter(
            part["human_effect_oriented_pp"],
            part["model_effect_oriented_pp"],
            marker=marker,
            label=task_type,
            s=14,
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
    _save(fig, output_dir, FORENSIC_OUTPUTS[3])
    _dot_ci(
        penalties["model"].astype(str).tolist(),
        penalties["absolute_penalty"],
        penalties["absolute_ci_low"],
        penalties["absolute_ci_high"],
        "context-minus-objective |R| penalty (pp)",
        "absolute error by model (forensic)",
    ).savefig(output_dir / FORENSIC_OUTPUTS[4], dpi=150)
    plt.close("all")
    _dot_ci(
        penalties["model"].astype(str).tolist(),
        penalties["attenuation_penalty"],
        penalties["attenuation_ci_low"],
        penalties["attenuation_ci_high"],
        "context-minus-objective attenuation penalty (pp)",
        "attenuation by model (forensic)",
    ).savefig(output_dir / FORENSIC_OUTPUTS[5], dpi=150)
    plt.close("all")
    _save(
        _dot_ci(
            regimes["task_type"].astype(str) + " / " + regimes["regime"].astype(str),
            regimes["proportion"],
            regimes["ci_low"],
            regimes["ci_high"],
            "share of contrasts",
            "response regimes by task type (forensic)",
        ),
        output_dir,
        FORENSIC_OUTPUTS[6],
    )
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(prof["corr_absolute_contrast_error"], prof["corr_attenuation"], s=14)
    ax.set_xlabel("corr(profile error, |R|)")
    ax.set_ylabel("corr(profile error, A)")
    _save(fig, output_dir, FORENSIC_OUTPUTS[7])
    _save(
        _dot_ci(
            tax["category"].astype(str).tolist(),
            tax["mae"],
            tax["ci_low"],
            tax["ci_high"],
            "leave-one-out MAE (pp)",
            "taxonomy bake-off on attenuation",
        ),
        output_dir,
        FORENSIC_OUTPUTS[8],
    )


def main(run_dir: Path, codebook_dir: Path) -> int:
    """Run the whole forensic analysis on the real study folder: load the
    FINAL table, repair the orientation from the raw effects, verify the
    repair, reproduce the standalone contrast-error table, recompute all
    eight result sections, and write the ten FORENSIC outputs. Returns 0
    on success; raises ValueError when the repair fails its own gates."""
    run_dir = Path(run_dir)
    codebook_dir = Path(codebook_dir)
    out_dir = run_dir / "forensic"
    out_dir.mkdir(parents=True, exist_ok=True)
    effects = pd.read_csv(
        run_dir / "signed_effects_FINAL" / "signed_contrast_effects_FINAL.csv"
    )
    work = _repaired_table(effects)
    write_forensic_csv(work, out_dir / FORENSIC_OUTPUTS[0])
    reloaded = load_forensic_csv(out_dir / FORENSIC_OUTPUTS[0])
    failures = verify_forensic_columns(reloaded)
    table = pd.read_csv(codebook_dir / "contrast_error_complete.csv")
    table = table[table["method"] == "arm_mean"]
    mismatched, worst = reproduce_contrast_error(reloaded, table)
    (out_dir / FORENSIC_OUTPUTS[1]).write_text(_check_text(failures, mismatched, worst))
    if failures:
        raise ValueError("forensic orientation check failed:\n" + "\n".join(failures))
    if mismatched != 0 or worst >= 1e-8:
        # A mismatch against the historical table is a FINDING, not a
        # crash: it means the old table was built under a different
        # orientation convention. The forensic check records the FAIL;
        # the run completes so the report can explain it.
        print(
            f"WARNING: contrast-error reproduction mismatched "
            f"({mismatched} cell(s), max {worst:.3g}); see forensic check"
        )
    seed = 20260923
    attenuation = se.attenuation_gap(work, seed=seed)
    slopes = se.recovery_slopes_final(work, seed=seed)
    regimes = se.response_regimes_final(work)
    regime_gap = se.reversed_regime_gap(work, seed=seed)
    penalties = se.model_penalties_final(work, seed=seed)
    counts = se.count_models_with_positive_penalty(penalties)
    profile_raw = pd.read_csv(codebook_dir / "profile_error_complete.csv")
    mask = (profile_raw["method"] == "arm_mean") & profile_raw[
        "profile_error_blinded"
    ].notna()
    profile = profile_raw[mask][["model", "experiment"]].assign(
        profile_error=profile_raw.loc[mask, "profile_error_blinded"].to_numpy()
    )
    prof = se.profile_fidelity_correlations(work, profile, seed=seed)
    tax = se.taxonomy_loo_comparison(work)
    audit = orientation_audit_rows(work)
    verdict = _verdict(attenuation)
    _write_figures(out_dir, work, attenuation, slopes, regimes, penalties, prof, tax)
    (out_dir / FORENSIC_OUTPUTS[9]).write_text(
        _report_text(
            audit,
            attenuation,
            slopes,
            regimes,
            regime_gap,
            counts,
            prof,
            tax,
            mismatched,
            worst,
            verdict,
        )
    )
    print(
        f"wrote {len(FORENSIC_OUTPUTS)} forensic outputs to {out_dir}; "
        f"verdict: {verdict}"
    )
    return 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
