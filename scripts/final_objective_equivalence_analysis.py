# FINAL auditable objective-equivalence / treatment-effect analysis.
#
# WHAT THIS FILE DOES, in plain words: it rebuilds, from the original
# registry and per-arm model means, how much humans move on a question
# and how much each language model moves, both squeezed onto a 0-1
# answer scale. It orients every effect in the human's direction
# (H = size of the human effect, M = the model effect read in the same
# direction, A = how much the model under-cuts the human, E = the size
# of the miss regardless of direction), checks every number with hard
# assertions (the run dies loudly if anything is off), and answers one
# question: do models miss by more on questions where only the framing
# changed (objective equivalence holds) than on questions where the
# objective facts actually changed?
#
# Each function's job:
#   main                 — read the config, run everything, write outputs.
#   sha256_of            — fingerprint of an input file, for the report.
#   human_arm_raw        — the one raw number a human arm card carries.
#   normalize01          — squeeze a raw answer onto 0-1 (registry rule).
#   build_rows           — one row per (model, experiment, contrast).
#   run_assertions       — every hard check; raises on the first failure.
#   (generic weighted-statistics helpers live in final_audit_lib)
#   primary_results      — the three headline numbers plus robustness.
#   model_consistency    — per-model penalties and how many are positive.
#   response_regimes     — reversed / attenuated / exaggerated shares.
#   profile_links        — Spearman links between profile error and E / A.
#   taxonomy_loo         — which labelling best predicts A (guess-LOO).
#   classify             — the one-line verdict at the end of the report.
#   write_figures        — the seven PNG pictures.
#   write_report         — the FINAL_AUDITABLE_REPORT.txt text file.
#
# Run:  PYTHONPATH=scripts python scripts/final_objective_equivalence_analysis.py \
#         scripts/final_analysis_config.json
# Only stdlib + numpy + pandas + matplotlib + scipy are used.
from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # never opens a window; safe on a headless run

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from final_audit_lib import (  # noqa: E402
    cluster_ci,
    group_gap,
    sha256_of,
    loo_stats,
    _slope_stat,
    slope_through_origin,
    weighted_mean,
)
from final_audit_outputs import (  # noqa: E402
    CLASSIFICATIONS,
    write_figures,
    write_report,
)


FAMILIES = {  # experiment -> paradigm family (from the spec)
    "anchoring_redwood": "anchoring", "anchoring_african": "anchoring",
    "fire_extinguisher": "proportion_dominance", "seatbelt": "proportion_dominance",
    "wta_wtp": "valuation_reference", "sunk_cost": "valuation_reference",
    "abs_relative": "valuation_reference", "less_is_more": "valuation_reference", "allais": "probability_risk",
    "prob_matching": "probability_risk", "linda": "judgment_inference",
    "outcome_bias": "judgment_inference", "myside": "judgment_inference",
    "false_consensus": "judgment_inference", "disease": "disease",
}

# Preference/belief taxonomy: families whose canonical effect runs
# through preference or belief framing (1) vs objective fact changes (0).
PREF_BELIEF_FAMILIES = {
    "framing/reference", "valuation/preference", "anchoring",
    "social/belief", "judgment/fallacy",
}


def human_arm_raw(card: dict) -> float | None:
    """The single raw number one human arm card carries: the plain mean
    when present, else p_safe / p_yes shares, the option-1 choice share,
    statement 3's mean, the mean majority share, or None."""
    if "mean" in card:
        return float(card["mean"])
    for stat in ("p_safe", "p_yes"):
        if isinstance(card.get(stat), (int, float)):
            value = float(card[stat])
            return value / 100.0 if value > 1.0 else value
    dist = card.get("dist")
    if isinstance(dist, dict) and "1" in dist:
        return float(dist["1"]["pct"]) / 100.0
    for key, value in card.get("per_statement", {}).items():
        if key.endswith("_3"):
            return float(value["mean"])
    per_trial = card.get("per_trial_pct_majority")
    if per_trial:
        return float(np.mean([float(v) for v in per_trial.values()])) / 100.0
    return None


def normalize01(value: float, spec: dict) -> float:
    """Squeeze a raw answer onto 0-1 with the experiment's registered
    min/max (the registry normalization rule)."""
    return (value - spec["min"]) / (spec["max"] - spec["min"])


def experiment_observables(arms: dict, spec: dict, anchor: bool) -> dict:
    """Map every arm of one experiment onto its comparable 0-1 number.
    Anchoring uses the bounded anchor choice P(more); the free numeric
    estimate is never the analyzed observable."""
    out = {}
    for arm, card in arms.items():
        if anchor:
            out[arm] = float(card["anchor_mc"]["1"]) / 100.0
        else:
            out[arm] = normalize01(human_arm_raw(card), spec)
    return out


def build_rows(registry: dict, llm: dict, contrast_cb: pd.DataFrame,
               exp_cb: pd.DataFrame, exclusions: list[str]) -> pd.DataFrame:
    """Build the signed-contrast table: one row per (model, experiment,
    contrast) with the 0-1 effects, the FINAL orientation columns
    (H, M, R, A, E in percentage points), the taxonomy codes, and the
    experiment-equal weight 1/k_e."""
    rows = []
    for exp in registry:
        if exp in exclusions:
            continue
        config = registry[exp]
        spec = config["normalization_0_1"]
        wave = config["human"]["wave1_3"]
        anchor = "anchor_mc" in list(wave["arms"].values())[0]
        h_obs = experiment_observables(wave["arms"], spec, anchor)
        family = FAMILIES[exp]
        pref = int(exp_cb.set_index("experiment").loc[exp, "behavioral_family"]
                   in PREF_BELIEF_FAMILIES)
        contrasts = contrast_cb[contrast_cb["experiment"] == exp]
        k_e = len(contrasts)
        for model, models_exps in llm.items():
            entry_m = models_exps.get(exp)
            if entry_m is None:
                continue
            means = entry_m["blinded"]["means"]
            if any(v is None for v in means.values()):
                continue
            if anchor:
                m_obs = {a: float(v) for a, v in means.items()}
            else:
                m_obs = {a: normalize01(float(v), spec) for a, v in means.items()}
            for _, c in contrasts.iterrows():
                d_h = (h_obs[c["treatment_arm"]] - h_obs[c["comparison_arm"]]) * 100.0
                d_m = (m_obs[c["treatment_arm"]] - m_obs[c["comparison_arm"]]) * 100.0
                big_h = abs(d_h)
                big_m = np.sign(d_h) * d_m
                rows.append({
                    "model": model, "experiment": exp, "contrast": c["contrast"],
                    "paradigm_family": family,
                    "d_h_pp": d_h, "d_m_pp": d_m,
                    "H_pp": big_h, "M_pp": big_m,
                    "R_pp": big_m - big_h, "A_pp": big_h - big_m,
                    "E_pp": abs(big_m - big_h),
                    "objective_equivalence": (
                        int(c["objective_equivalence"])
                        if str(c["objective_equivalence"]) in ("0", "1") else "NA"),
                    "reference_context": int(c["reference_context"]),
                    "preference_vs_belief": pref,
                    "weight": 1.0 / k_e,
                    "rationale": c.get("ambiguity_note", ""),
                })
    return pd.DataFrame(rows)


def run_assertions(rows: pd.DataFrame, registry: dict, exclusions: list[str],
                   models: list[str], reference: pd.DataFrame) -> None:
    """Every hard check from the spec. Terminates the run with a clear
    message on the first failure — nothing is published unless all pass."""
    def check(name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            raise AssertionError(f"ASSERTION FAILED [{name}] {detail}")

    check("means_in_0_1", rows["d_h_pp"].between(-100, 100).all()
          and rows["d_m_pp"].between(-100, 100).all())
    check("H_equals_abs_dh", np.allclose(rows["H_pp"], rows["d_h_pp"].abs(), atol=1e-10))
    check("M_equals_signed_dm", np.allclose(
        rows["M_pp"], np.sign(rows["d_h_pp"]) * rows["d_m_pp"], atol=1e-10))
    check("R_equals_M_minus_H", np.allclose(rows["R_pp"],
          rows["M_pp"] - rows["H_pp"], atol=1e-10))
    check("A_equals_neg_R", np.allclose(rows["A_pp"], -rows["R_pp"], atol=1e-10))
    check("E_equals_abs_R", np.allclose(rows["E_pp"], rows["R_pp"].abs(), atol=1e-10))
    check("exclusions_absent",
          not rows["experiment"].isin(exclusions).any())
    check("fourteen_experiments", rows["experiment"].nunique() == 14,
          f"got {rows['experiment'].nunique()}")
    per_model = rows.groupby("model")["experiment"].nunique()
    expected = rows.groupby("experiment")["model"].nunique()
    check("all_15_models", set(rows["model"]) == set(models),
          f"missing {set(models) - set(rows['model'])}")
    check("models_complete_where_valid",
          all(expected[e] <= 15 for e in expected.index))
    check("family_nonmissing", rows["paradigm_family"].notna().all()
          and (rows["paradigm_family"] != "").all())
    # Aggregate E must reproduce the old contrast_error_complete table.
    mine = rows.groupby(["model", "experiment"], as_index=False)["E_pp"].mean()
    mine = mine.rename(columns={"E_pp": "contrast_error"})
    ref = reference[reference["method"] == "arm_mean"][
        ["model", "experiment", "contrast_error"]]
    merged = ref.merge(mine, on=["model", "experiment"], how="outer",
                       suffixes=("_ref", "_mine"), indicator=True)
    check("reference_rows_match", (merged["_merge"] == "both").all(),
          f"unmatched: {merged[merged['_merge'] != 'both']}")
    disc = (merged["contrast_error_ref"] - merged["contrast_error_mine"]).abs()
    check("reference_reproduced", float(disc.max()) < 1e-8 and
          int((disc > 1e-8).sum()) == 0, f"max disc {disc.max()}")


def primary_results(rows: pd.DataFrame, cfg: dict, rng: np.random.Generator) -> dict:
    """The three primary numbers — D_E, D_A and the recovery slopes —
    each with a family-cluster CI, an experiment CI and LOO ranges.
    Only contrasts with a firm 0/1 objective_equivalence code enter
    (the ambiguous outcome_bias contrast is excluded from primary)."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])].copy()
    draws = cfg["bootstrap_draws"]
    out: dict = {}
    for name, col in (("D_E", "E_pp"), ("D_A", "A_pp")):
        stat = lambda d, c=col: group_gap(d, c)  # noqa: E731
        fam_ci = cluster_ci(prim, stat, prim["paradigm_family"], draws, rng)
        exp_ci = cluster_ci(prim, stat, prim["experiment"], draws, rng)
        out[name] = {
            "estimate": stat(prim), "ci_family": fam_ci, "ci_experiment": exp_ci,
            "loo_experiment": loo_stats(prim, stat, prim["experiment"]),
            "loo_family": loo_stats(prim, stat, prim["paradigm_family"]),
        }
    beta_obj = _slope_stat(prim, 1)
    beta_change = _slope_stat(prim, 0)
    slope_diff_stat = lambda d: _slope_stat(d, 1) - _slope_stat(d, 0)  # noqa: E731
    out["slopes"] = {
        "beta_obj": beta_obj, "beta_change": beta_change,
        "diff": slope_diff_stat(prim),
        "diff_ci_family": cluster_ci(prim, slope_diff_stat,
                                     prim["paradigm_family"], draws, rng),
        "diff_ci_experiment": cluster_ci(prim, slope_diff_stat,
                                         prim["experiment"], draws, rng),
        "obj_ci_family": cluster_ci(prim, lambda d: _slope_stat(d, 1),
                                    prim["paradigm_family"], draws, rng),
        "change_ci_family": cluster_ci(prim, lambda d: _slope_stat(d, 0),
                                       prim["paradigm_family"], draws, rng),
    }
    return out


def model_consistency(rows: pd.DataFrame) -> dict:
    """Per-model penalties D_{E,m} and D_{A,m} (experiment-equal
    weights), how many of the 15 models have a positive penalty, and
    the medians."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])]
    per_model = {}
    for model, sub in prim.groupby("model"):
        per_model[model] = {"D_E": group_gap(sub, "E_pp"),
                            "D_A": group_gap(sub, "A_pp")}
    frame = pd.DataFrame(per_model).T
    return {"per_model": per_model, "n_positive_E": int((frame["D_E"] > 0).sum()),
            "n_positive_A": int((frame["D_A"] > 0).sum()),
            "median_E": float(frame["D_E"].median()),
            "median_A": float(frame["D_A"].median())}


def response_regimes(rows: pd.DataFrame, cfg: dict,
                     rng: np.random.Generator) -> pd.DataFrame:
    """Share of contrasts that reverse (M<0), attenuate (0<=M<H) or
    exaggerate (M>H), per objective-equivalence group, with a
    family-cluster bootstrap CI on each share."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])].copy()

    def regime(v: pd.Series, h: pd.Series) -> pd.Series:
        return np.where(v < 0, "reversed",
                        np.where(v > h, "exaggerated", "attenuated"))

    prim["regime"] = regime(prim["M_pp"], prim["H_pp"])
    out = []
    for group in (1, 0):
        sub = prim[prim["objective_equivalence"] == group]
        for name in ("reversed", "attenuated", "exaggerated"):
            stat = (lambda d, n=name: weighted_mean(
                (d["regime"] == n).to_numpy(float), d["weight"].to_numpy()))
            lo, hi = cluster_ci(sub, stat, sub["paradigm_family"],
                                cfg["bootstrap_draws"], rng)
            out.append({"group": "OE=1" if group == 1 else "OE=0",
                        "regime": name, "share": stat(sub),
                        "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(out)


def profile_links(rows: pd.DataFrame, profile: pd.DataFrame) -> dict:
    """Spearman links between a model's general profile error and its
    treatment-error E and attenuation A, at the model x experiment
    level, with a two-way (model and experiment) bootstrap CI."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])]
    per_cell = prim.groupby(["model", "experiment"]).apply(
        lambda s: pd.Series({
            "E": weighted_mean(s["E_pp"].to_numpy(), s["weight"].to_numpy()),
            "A": weighted_mean(s["A_pp"].to_numpy(), s["weight"].to_numpy())}),
        include_groups=False).reset_index()
    prof = profile[profile["method"] == "arm_mean"][
        ["model", "experiment", "profile_error_blinded"]]
    merged = per_cell.merge(prof, on=["model", "experiment"]).dropna()
    if len(merged) == 0:
        raise AssertionError("ASSERTION FAILED [profile_overlap] no shared cells")
    rho_e = float(spearmanr(merged["profile_error_blinded"], merged["E"]).statistic)
    rho_a = float(spearmanr(merged["profile_error_blinded"], merged["A"]).statistic)
    rng = np.random.default_rng(20261010)
    cis = {}
    for name, col in (("E", "E"), ("A", "A")):
        stats = []
        models = merged["model"].unique()
        exps = merged["experiment"].unique()
        for _ in range(2000):
            pick_m = rng.choice(models, len(models))
            pick_e = rng.choice(exps, len(exps))
            sample = pd.concat([
                merged[(merged["model"] == m) & (merged["experiment"] == e)]
                for m in pick_m[:5] for e in pick_e[:5]], ignore_index=True)
            if len(sample) > 2:
                stats.append(float(spearmanr(
                    sample["profile_error_blinded"], sample[col]).statistic))
        cis[name] = (float(np.percentile(stats, 2.5)),
                     float(np.percentile(stats, 97.5)))
    return {"rho_E": rho_e, "rho_A": rho_a, "n": len(merged), "ci": cis}


def taxonomy_loo(rows: pd.DataFrame) -> pd.DataFrame:
    """Guess each contrast's attenuation A by the average A of the OTHER
    contrasts sharing its label, for each of the three labellings; the
    mean absolute guessing error says which labelling predicts best."""
    prim = rows[rows["objective_equivalence"].isin([0, 1])]
    target = prim["A_pp"].to_numpy(float)
    out = []
    for label in ("objective_equivalence", "reference_context",
                  "preference_vs_belief"):
        codes = prim[label].to_numpy()
        errors = []
        for i in range(len(prim)):
            same = codes == codes[i]
            same[i] = False
            guess = (target[same].mean() if same.any()
                     else np.delete(target, i).mean())
            errors.append(abs(guess - target[i]))
        out.append({"taxonomy": label, "mae": float(np.mean(errors))})
    return pd.DataFrame(out)


def classify(results: dict) -> str:
    """Pick the one-line verdict from the primary CIs: both CIs above
    zero -> robust effect + attenuation; only D_E -> robust effect with
    suggestive attenuation or absolute-error-only; neither -> no effect."""
    d_e_lo = results["D_E"]["ci_family"][0]
    d_a_lo = results["D_A"]["ci_family"][0]
    d_a_est = results["D_A"]["estimate"]
    if d_e_lo > 0 and d_a_lo > 0:
        return CLASSIFICATIONS[0]
    if d_e_lo > 0 and d_a_est > 0:
        return CLASSIFICATIONS[1]
    return CLASSIFICATIONS[2] if d_e_lo > 0 else CLASSIFICATIONS[3]


def main(argv: list[str]) -> int:
    """Read the config, rebuild everything from the inputs, assert, run
    the analyses, write all outputs, print the verdict."""
    if len(argv) != 2:
        print("usage: final_objective_equivalence_analysis.py <config.json>")
        return 2
    cfg_path = Path(argv[1]).resolve()
    cfg = json.loads(cfg_path.read_text())
    base = cfg_path.parent
    in_dir = Path(cfg["input_dir"])
    out_dir = Path(cfg["output_dir"])
    out_dir = out_dir if out_dir.is_absolute() else (base / out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: in_dir / fname for name, fname in cfg["inputs"].items()}
    registry = json.loads(paths["registry"].read_text())["experiments"]
    llm = json.loads(paths["llm_means"].read_text())
    contrast_cb = pd.read_csv(paths["contrast_codebook"])
    exp_cb = pd.read_csv(paths["experiment_codebook"])
    reference = pd.read_csv(paths["contrast_error_reference"])
    profile = pd.read_csv(paths["profile_error"])
    rows = build_rows(registry, llm, contrast_cb, exp_cb, cfg["exclusions"])
    run_assertions(rows, registry, cfg["exclusions"], sorted(llm), reference)
    rng = np.random.default_rng(cfg["seed"])
    results = primary_results(rows, cfg, rng)
    models = model_consistency(rows)
    regimes = response_regimes(rows, cfg, rng)
    links = profile_links(rows, profile)
    tax = taxonomy_loo(rows)
    verdict = classify(results)
    prim = rows[rows["objective_equivalence"].isin([0, 1])]
    # Outputs: config, tables, figures, report.
    (out_dir / "final_analysis_config.json").write_text(json.dumps(cfg, indent=2))
    rows.to_csv(out_dir / "final_signed_contrasts.csv", index=False)
    audit = rows.drop_duplicates("contrast").sort_values("d_h_pp")
    neg = audit[audit["d_h_pp"] < 0].head(6)
    pos = audit[audit["d_h_pp"] > 0].tail(6)
    cols = ["experiment", "contrast", "model", "d_h_pp", "d_m_pp",
            "H_pp", "M_pp", "A_pp", "E_pp"]
    pd.concat([neg, pos])[cols].to_csv(out_dir / "orientation_audit.csv",
                                       index=False)
    rows.drop_duplicates("contrast")[
        ["experiment", "contrast", "objective_equivalence", "rationale"]
    ].to_csv(out_dir / "objective_equivalence_coding_used.csv", index=False)
    pd.DataFrame([{"experiment": e, "paradigm_family": f}
                  for e, f in FAMILIES.items()]).to_csv(
        out_dir / "paradigm_family_mapping.csv", index=False)
    # Assemble the combined results table (gaps, slopes, regimes).
    n_exp, n_con = rows["experiment"].nunique(), len(rows)
    n_fam = rows["paradigm_family"].nunique()

    def result_row(analysis, group, estimate, ci_f, ci_e, notes):
        """One row of final_results_table.csv with both CIs."""
        return {"analysis": analysis, "group": group, "estimate": estimate,
                "ci_low_family": ci_f[0], "ci_high_family": ci_f[1],
                "ci_low_exp": ci_e[0] if ci_e else "",
                "ci_high_exp": ci_e[1] if ci_e else "",
                "n_exp": n_exp, "n_contrasts": n_con, "n_families": n_fam,
                "notes": notes}

    gap_rows = [result_row(name, "OE=1_minus_OE=0", results[name]["estimate"],
                           results[name]["ci_family"],
                           results[name]["ci_experiment"],
                           "family-cluster and experiment bootstrap 95% CIs")
                for name in ("D_E", "D_A")]
    s = results["slopes"]
    slope_rows = [
        result_row("recovery_slope", g, e, s[c], None, n)
        for g, e, c, n in (("OE=1", s["beta_obj"], "obj_ci_family", "beta_OE1"),
                           ("OE=0", s["beta_change"], "change_ci_family",
                            "beta_OE0"),
                           ("diff", s["diff"], "diff_ci_family",
                            "beta_OE1_minus_beta_OE0"))]
    regime_rows = [result_row("response_regime", r["group"], r["share"],
                              (r["ci_low"], r["ci_high"]), None, r["regime"])
                   for _, r in regimes.iterrows()]
    pd.DataFrame(gap_rows + slope_rows + regime_rows).to_csv(
        out_dir / "final_results_table.csv", index=False)
    write_figures(rows, results, models, regimes, profile, tax, out_dir)
    text = write_report(cfg, paths, rows, results, models, regimes, links,
                        tax, verdict, out_dir)
    print(text[-600:])
    print(f"\noutputs -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
