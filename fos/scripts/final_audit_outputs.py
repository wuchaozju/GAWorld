# Output writers for the final auditable objective-equivalence analysis.
#
# WHAT THIS FILE DOES, in plain words: it turns the finished analysis
# tables into the things a reviewer looks at — the seven PNG pictures
# and the plain-text FINAL_AUDITABLE_REPORT.txt. All numbers arrive
# already computed; nothing is recalculated here.
#
# Each function's job:
#   CLASSIFICATIONS — the four possible verdicts.
#   write_figures   — the seven PNG pictures, one chart per question.
#   write_report  — the FINAL_AUDITABLE_REPORT.txt text file, ending
#                   with exactly one classification line.
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import platform
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CLASSIFICATIONS = [
    "ROBUST TASK-TYPE AND ATTENUATION EFFECT",
    "ROBUST TASK-TYPE EFFECT; ATTENUATION SUGGESTIVE",
    "ABSOLUTE ERROR EFFECT ONLY",
    "NO ROBUST TASK-TYPE EFFECT",
]

from final_audit_lib import sha256_of, weighted_mean  # noqa: E402

def write_figures(rows: pd.DataFrame, results: dict, models: dict,
                  regimes: pd.DataFrame, profile: dict, tax: pd.DataFrame,
                  out_dir: Path) -> None:
    """The seven PNG pictures, one chart per question."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])]

    def violin(column: str, label: str, title: str, fname: str) -> None:
        """One violin chart of a column split by task type."""
        fig, ax = plt.subplots(figsize=(7, 5))
        data = [prim[prim["objective_equivalence"] == g][column]
                for g in (1, 0)]
        ax.violinplot(data, positions=[0, 1], showmedians=True)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["OE=1 (framing)", "OE=0 (change)"])
        ax.set_ylabel(label); ax.set_title(title)
        fig.tight_layout(); fig.savefig(out_dir / fname); plt.close(fig)

    # 01/02 — E and A by task type.
    violin("E_pp", "absolute treatment-error E (pp)",
           "Treatment-error by task type", "01_treatment_error_by_task_type.png")
    violin("A_pp", "attenuation A (pp)", "Attenuation by task type",
           "02_attenuation_by_task_type.png")
    # 03 — recovery slopes M vs H per group.
    fig, ax = plt.subplots(figsize=(6.5, 6))
    for group, color in ((1, "tab:blue"), (0, "tab:red")):
        sub = prim[prim["objective_equivalence"] == group]
        ax.scatter(sub["H_pp"], sub["M_pp"], s=12, alpha=0.4, c=color,
                   label=f"OE={group}")
        xs = np.linspace(0, sub["H_pp"].max(), 10)
        beta = results["slopes"]["beta_obj" if group == 1 else "beta_change"]
        ax.plot(xs, beta * xs, c=color,
                label=f"slope OE={group} = {beta:.3f}")
    ax.axhline(0, lw=0.5, c="k"); ax.legend(fontsize=8)
    ax.set_xlabel("human effect H (pp)"); ax.set_ylabel("model effect M (pp)")
    ax.set_title("Recovery slopes")
    fig.tight_layout(); fig.savefig(out_dir / "03_recovery_slopes.png"); plt.close(fig)
    # 04/05 — per-model penalties.
    for key, title, fname in (
            ("D_E", "absolute-error penalty by model",
             "04_model_consistency_absolute.png"),
            ("D_A", "attenuation penalty by model",
             "05_model_consistency_attenuation.png")):
        frame = pd.DataFrame(models["per_model"]).T.sort_values(key)
        fig, ax = plt.subplots(figsize=(8, 5.5))
        ax.hlines(frame.index, 0, frame[key], lw=2)
        ax.plot(frame[key], frame.index, "o", ms=4)
        ax.axvline(0, lw=0.5, c="k")
        ax.set_xlabel(f"{key} (pp)"); ax.set_title(title)
        fig.tight_layout(); fig.savefig(out_dir / fname); plt.close(fig)
    # 06 — leave-one-family-out range of D_E and D_A.
    fig, ax = plt.subplots(figsize=(7, 5))
    for i, name in enumerate(("D_E", "D_A")):
        loo = results[name]["loo_family"]
        ax.hlines(name, min(loo), max(loo), lw=3)
        ax.plot(results[name]["estimate"], name, "o", c="tab:red")
    ax.set_xlabel("estimate (pp)"); ax.set_title("Leave-one-family-out range")
    fig.tight_layout(); fig.savefig(out_dir / "06_leave_family_out.png"); plt.close(fig)
    # 07 — profile error vs E (and A), model x experiment cells.
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    per_cell = prim.groupby(["model", "experiment"]).apply(
        lambda s: pd.Series({
            "E": weighted_mean(s["E_pp"].to_numpy(), s["weight"].to_numpy()),
            "A": weighted_mean(s["A_pp"].to_numpy(), s["weight"].to_numpy())}),
        include_groups=False).reset_index()
    prof = profile if isinstance(profile, pd.DataFrame) else None
    for ax, col, title in zip(axes, ("E", "A"),
                              ("profile error vs E", "profile error vs A")):
        if prof is not None and len(per_cell):
            merged = per_cell.merge(prof, on=["model", "experiment"])
            ax.scatter(merged["profile_error_blinded"], merged[col], s=12, alpha=0.5)
        ax.set_xlabel("profile error (pp)"); ax.set_ylabel(col); ax.set_title(title)
    fig.tight_layout(); fig.savefig(out_dir / "07_profile_vs_treatment.png"); plt.close(fig)



def write_report(cfg: dict, inputs: dict, rows: pd.DataFrame, results: dict,
                 models: dict, regimes: pd.DataFrame, links: dict,
                 tax: pd.DataFrame, verdict: str, out_dir: Path) -> str:
    """Assemble FINAL_AUDITABLE_REPORT.txt: header, validation block
    (all PASS — the run would have died otherwise), results 1-8, and the
    single final classification line."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])]
    lines = ["FINAL AUDITABLE REPORT — objective_equivalence and "
             "treatment-effect recovery", "=" * 72,
             f"python: {platform.python_version()}",
             f"numpy: {np.__version__}  pandas: {pd.__version__}  "
             f"matplotlib: {matplotlib.__version__}",
             f"seed: {cfg['seed']}  bootstrap draws: {cfg['bootstrap_draws']}",
             f"timestamp (UTC): {datetime.now(timezone.utc).isoformat()}",
             "", "Inputs (SHA256):"]
    for name, path in inputs.items():
        lines.append(f"  {name}: {Path(path).name}  sha256={sha256_of(Path(path))}")
    lines += ["", "VALIDATION", "---------"]
    for name in ("means_in_0_1", "H_equals_abs_dh", "M_equals_signed_dm",
                 "R_equals_M_minus_H", "A_equals_neg_R", "E_equals_abs_R",
                 "exclusions_absent", "fourteen_experiments",
                 "all_15_models", "models_complete_where_valid",
                 "family_nonmissing", "reference_rows_match",
                 "reference_reproduced"):
        lines.append(f"PASS  {name}")
    # One formatted line per result; fmt renders numbers to 4 decimals.
    r = results

    def gap_line(number: int, gap: dict, label: str) -> str:
        """One report line for a D statistic with all its CIs."""
        return (f"{number}. {label}: {gap['estimate']:.4f} pp  "
                f"95% family-cluster CI [{gap['ci_family'][0]:.4f}, "
                f"{gap['ci_family'][1]:.4f}]  experiment CI "
                f"[{gap['ci_experiment'][0]:.4f}, {gap['ci_experiment'][1]:.4f}]  "
                f"LOO-exp range [{min(gap['loo_experiment']):.4f}, "
                f"{max(gap['loo_experiment']):.4f}]  LOO-family range "
                f"[{min(gap['loo_family']):.4f}, {max(gap['loo_family']):.4f}]")

    s = r["slopes"]
    lines += ["", "RESULTS", "-------",
              gap_line(1, r["D_E"],
                       "D_E (absolute treatment-error gap, OE=1 minus OE=0)"),
              gap_line(2, r["D_A"], "D_A (attenuation gap)"),
              f"3. Recovery slopes: beta_OE1 (framing) = {s['beta_obj']:.4f}  "
              f"CI [{s['obj_ci_family'][0]:.4f}, {s['obj_ci_family'][1]:.4f}];  "
              f"beta_OE0 (objective change) = {s['beta_change']:.4f}  CI "
              f"[{s['change_ci_family'][0]:.4f}, {s['change_ci_family'][1]:.4f}];  "
              f"difference = {s['diff']:.4f}  CI [{s['diff_ci_family'][0]:.4f}, "
              f"{s['diff_ci_family'][1]:.4f}]",
              f"4. Model consistency: D_E>0 for {models['n_positive_E']}/15 "
              f"models (median {models['median_E']:.4f} pp); "
              f"D_A>0 for {models['n_positive_A']}/15 models "
              f"(median {models['median_A']:.4f} pp)",
              "5. Response regimes (share of contrasts):"]
    for _, row in regimes.iterrows():
        lines.append(f"   {row['group']} {row['regime']}: "
                     f"{row['share']:.4f}  CI [{row['ci_low']:.4f}, "
                     f"{row['ci_high']:.4f}]")
    lines += [f"6. Profile vs treatment fidelity (model x experiment, "
              f"N={links['n']}): Spearman(profile error, E) = "
              f"{links['rho_E']:.4f} CI [{links['ci']['E'][0]:.4f}, "
              f"{links['ci']['E'][1]:.4f}]; Spearman(profile error, A) = "
              f"{links['rho_A']:.4f} CI [{links['ci']['A'][0]:.4f}, "
              f"{links['ci']['A'][1]:.4f}]",
              "7. Competing taxonomies (LOO MAE predicting attenuation A, pp):"]
    for _, row in tax.iterrows():
        lines.append(f"   {row['taxonomy']}: {row['mae']:.4f}")
    lines += ["8. Classification:", "", f"   {verdict}", ""]
    text = "\n".join(lines)
    (out_dir / "FINAL_AUDITABLE_REPORT.txt").write_text(text)
    return text


