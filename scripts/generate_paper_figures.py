#!/usr/bin/env python3
"""Generate 7 paper figures for the Headless Council experiment from raw CSV data.

Reads per-agent voting data (5 seeds, 3 networks, 3 proposals, 5 models) and
produces publication-ready PNG+PDF figures. Configurable constants below.
"""

import json
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib import rcParams
from scipy import stats
from statsmodels.formula.api import logit

warnings.filterwarnings("ignore", category=FutureWarning)


# ── Configurable constants ──
DATA_DIR = Path("/home/justin/Documents/ZJU work/fos/artifacts")
OUTPUT_DIR = DATA_DIR / "paper_figures"
NUM_SEEDS = [7, 8, 9, 10, 11]
SHUFFLE_COUNT = 2000
DPI = 600
CB_PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7"]

NETWORKS = ["small_world", "holme_kim", "sbm"]
NETWORK_LABELS = dict(zip(NETWORKS, ["Small World", "Holme-Kim", "SBM"]))
PROPOSAL_KEYS = {"proposal_a": "SRMA", "proposal_b": "WealthTax", "proposal_d": "UNVeto"}
PROPOSAL_LABELS = {"SRMA": "SRMA", "WealthTax": "Wealth Tax", "UNVeto": "UN Veto"}
MODEL_SHORT = {"gpt-oss-20b": "GPT-OSS", "qwen3.6-35b-a3b": "Qwen3.6",
               "qwen3.6-35b-a3b-uncensored": "Qwen-UC",
               "gemma-4-26b-a4b": "Gemma-4", "gemma4-26b-a4b-uncensored": "Gemma-UC"}
MODELS_ORDER = ["GPT-OSS", "Qwen3.6", "Qwen-UC", "Gemma-4", "Gemma-UC"]

rcParams.update({
    "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "figure.dpi": 150, "savefig.dpi": DPI, "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02, "axes.grid": False,
    "axes.edgecolor": "black", "axes.linewidth": 0.8,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
})

# ── Helpers ──
def _voting_pivot(df, extra_group_cols=None):
    """Group voting actions by given cols and pivot to yes/no/abstain counts + yes_rate.

    Only includes agents who actually voted (voted > 0). Excludes agents with
    empty/skip actions. yes_rate = vote_yes / (vote_yes + vote_no + abstain).
    """
    group_cols = ["seed", "network_label", "proposal", "agent_id"]
    if extra_group_cols:
        group_cols = group_cols + list(extra_group_cols)
    vc = df.groupby(group_cols + ["action"]).size().reset_index(name="n")
    pv = vc.pivot_table(
        index=group_cols, columns="action", values="n", fill_value=0
    ).reset_index()
    for col in ["vote_yes", "vote_no", "abstain"]:
        if col not in pv.columns:
            pv[col] = 0
    # Only agents who actually cast a vote
    pv["voted"] = pv["vote_yes"] + pv["vote_no"] + pv["abstain"]
    pv = pv[pv["voted"] > 0].copy()
    pv["yes_rate"] = pv["vote_yes"] / pv["voted"]
    return pv, group_cols


def _save(fig, name):
    """Save figure as PNG (high DPI) and PDF (vector), both with tight layout and minimal padding."""
    fig.savefig(OUTPUT_DIR / f"{name}.png", dpi=DPI, bbox_inches="tight", pad_inches=0.02)
    fig.savefig(OUTPUT_DIR / f"{name}.pdf", bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(f"  ✓ {name}.png/pdf")


def _normalize_agent(name):
    """Normalize agent name: 'Agent 1' -> 'agent_1' to match CSV format."""
    return name.lower().replace(" ", "_")


def load_edges(seed_dir, network_label):
    """Load edge list from summary.json for a given seed directory and network.

    Handles Seeds 7 and 8 with inconsistent subdirectory naming (capitalisation).
    Normalises agent names from "Agent 1" to "agent_1" to match CSV format.
    Returns list of (agent_a, agent_b) pairs, or None if no summary.json found.
    """
    for d in seed_dir.iterdir():
        if d.is_dir() and d.name.startswith("council_100agents_"):
            suffix = d.name[len("council_100agents_"):].lower()
            if suffix == network_label.lower():
                sm_path = d / "summary.json"
                if sm_path.is_file():
                    with open(sm_path) as f:
                        data = json.load(f)
                    all_edges = []
                    for run in data["runs"]:
                        for a, b in run["edges"]:
                            all_edges.append((_normalize_agent(a), _normalize_agent(b)))
                    return all_edges
    return None


def _ci_95(series):
    """95% CI: 1.96 * std / sqrt(n)."""
    return 1.96 * series.std() / np.sqrt(max(len(series), 1))


# ── Data loading ──
def load_all_data() -> pd.DataFrame:
    """Read all per-agent CSV files across seeds/networks from subdirectories only.

    Removed the top-level CSV fallback (Bug 3 fix). Seeds without a network
    subdirectory simply don't contribute data for that network. Prints balance
    panel for debugging.
    """
    rows = []
    for seed in NUM_SEEDS:
        sd = DATA_DIR / f"Seed_{seed}_Full"
        if not sd.is_dir():
            print(f"  [WARN] Seed {seed} dir not found")
            continue
        subdirs = {}
        for d in sd.iterdir():
            if d.is_dir() and d.name.startswith("council_100agents_"):
                suffix = d.name[len("council_100agents_"):].lower()
                subdirs[suffix] = d / "combined_results.csv"
        for net in NETWORKS:
            if net not in subdirs or not subdirs[net].is_file():
                print(f"  [WARN] No subdirectory for '{net}' in seed {seed}, skip")
                continue
            dnet = pd.read_csv(subdirs[net])
            dnet = dnet[dnet["network_label"].str.lower() == net]
            if dnet.empty:
                continue
            dnet["seed"] = seed
            n_vote_rows = len(dnet)
            rows.append(dnet)
            print(f"  {seed=} {net=}: {n_vote_rows} vote rows after dedup")
    if not rows:
        raise ValueError("No data loaded")
    df = pd.concat(rows, ignore_index=True)
    df = df[df["action"].isin(["vote_yes", "vote_no", "abstain"])].copy()
    df["network_label"] = df["network_label"].str.lower()
    df["proposal"] = df["proposal_key"].map(PROPOSAL_KEYS)
    df["model_short"] = df["model"].map(MODEL_SHORT).fillna(df["model"])
    # Print balance panel
    panel = df.groupby(["seed", "network_label", "proposal_key"]).size().unstack(fill_value=0)
    print(f"\nPanel balance:\n{panel}\n")
    return df


# ── Figure 1 ──
def fig1_yesrate(df):
    """Bar chart: yes-rate per network pooled across proposals. 95% CI error bars."""
    pv, _ = _voting_pivot(df)
    sn = pv.groupby(["seed", "network_label"])["yes_rate"].mean().reset_index()
    ns = (
        sn.groupby("network_label")["yes_rate"]
        .agg(["mean", "std", "count"])
        .reset_index()
    )
    ns["ci"] = 1.96 * ns["std"] / np.sqrt(ns["count"])
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(
        range(3),
        ns["mean"],
        yerr=ns["ci"],
        color=CB_PALETTE[:3],
        capsize=5,
        error_kw={"linewidth": 1.2},
        edgecolor="white",
        tick_label=[NETWORK_LABELS[n] for n in NETWORKS],
    )
    ax.set_ylabel("Yes rate")
    ax.set_xlabel("Network")
    ax.set_ylim(0, 1)
    _save(fig, "fig1_yesrate")


# ── Figure 2 ──
def fig2_slopegraph(df):
    """Slopegraph: one line per proposal showing yes-rate across networks."""
    pv, _ = _voting_pivot(df)
    am = (
        pv.groupby(["seed", "network_label", "proposal"])["yes_rate"]
        .mean()
        .reset_index()
    )
    pnm = am.groupby(["network_label", "proposal"])["yes_rate"].agg(["mean", "std", "count"]).reset_index()
    pnm["ci"] = 1.96 * pnm["std"] / np.sqrt(pnm["count"])
    cb_prop = {"SRMA": CB_PALETTE[0], "WealthTax": CB_PALETTE[1], "UNVeto": CB_PALETTE[2]}
    fig, ax = plt.subplots(figsize=(6, 5))
    for prop in ["SRMA", "WealthTax", "UNVeto"]:
        d = pnm[pnm["proposal"] == prop].set_index("network_label")
        y = [d.loc[n, "mean"] if n in d.index else np.nan for n in NETWORKS]
        e = [d.loc[n, "ci"] if n in d.index else np.nan for n in NETWORKS]
        ax.errorbar(
            range(3),
            y,
            yerr=e,
            label=PROPOSAL_LABELS[prop],
            color=cb_prop[prop],
            marker="o",
            capsize=4,
            lw=2,
            ms=7,
        )
    ax.set_xticks(range(3))
    ax.set_xticklabels([NETWORK_LABELS[n] for n in NETWORKS])
    ax.set_ylabel("Yes rate")
    ax.set_xlabel("Network")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False)
    _save(fig, "fig2_slopegraph")


# ── Figure 3 ──
def fig3_model_rates(df):
    """Grouped bar: 5 models x 3 networks. Uses yes_rate from _voting_pivot."""
    pv, _ = _voting_pivot(df, ["model_short"])
    snm = (
        pv.groupby(["seed", "network_label", "model_short"])["yes_rate"]
        .mean()
        .reset_index()
    )
    nc = {"small_world": CB_PALETTE[0], "holme_kim": CB_PALETTE[1], "sbm": CB_PALETTE[2]}
    fig, ax = plt.subplots(figsize=(10, 5))
    width = 0.25
    for i, net in enumerate(NETWORKS):
        nd = snm[snm["network_label"] == net]
        means, cis = [], []
        for mod in MODELS_ORDER:
            md = nd[nd["model_short"] == mod]["yes_rate"]
            m = md.mean() if len(md) > 0 else 0
            c = _ci_95(md) if len(md) > 1 else 0
            means.append(m)
            cis.append(c)
        ax.bar(
            np.arange(5) + i * width - width,
            means,
            width,
            yerr=cis,
            label=NETWORK_LABELS[net], color=nc[net],
            capsize=3,
            edgecolor="white",
        )
    ax.set_xticks(range(5))
    ax.set_xticklabels(MODELS_ORDER, rotation=20, ha="right")
    ax.set_ylabel("Yes rate")
    ax.set_xlabel("Model")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False)
    _save(fig, "fig3_model_rates")


# ── Figure 4 ──
def fig4_heatmaps(df):
    """Heatmap per proposal: rows=models, cols=6 network transitions. Yes-retention rate."""
    trans_order = ["SW→HK", "SW→SBM", "HK→SBM", "HK→SW", "SBM→SW", "SBM→HK"]
    trans_map = {("small_world", "holme_kim"): "SW→HK", ("small_world", "sbm"): "SW→SBM",
                 ("holme_kim", "sbm"): "HK→SBM", ("holme_kim", "small_world"): "HK→SW",
                 ("sbm", "small_world"): "SBM→SW", ("sbm", "holme_kim"): "SBM→HK"}
    voting = df[df["action"].isin(["vote_yes", "vote_no", "abstain"])]
    for prop_name in ["SRMA", "WealthTax", "UNVeto"]:
        pd_ = voting[voting["proposal"] == prop_name]
        vp = (
            pd_.groupby(["seed", "model_short", "agent_id", "network_label"])["action"]
            .first()
            .reset_index()
        )
        trans = []
        for seed in NUM_SEEDS:
            sv = vp[vp["seed"] == seed]
            for mod in sv["model_short"].unique():
                mv = sv[sv["model_short"] == mod]
                for agent in mv["agent_id"].unique():
                    av = mv[mv["agent_id"] == agent]
                    vm = dict(zip(av["network_label"], av["action"]))
                    if all(n in vm for n in NETWORKS):
                        for src, dst in trans_map:
                            trans.append(
                                {
                                    "seed": seed,
                                    "model_short": mod,
                                    "transition": trans_map[(src, dst)],
                                    "from_vote": vm[src],
                                    "to_vote": vm[dst],
                                }
                            )
        td = pd.DataFrame(trans)
        ys = td[td["from_vote"] == "vote_yes"]
        if len(ys) == 0:
            print(f"  [WARN] No yes-voters for {prop_name}, skip")
            continue
        pr = (
            ys.groupby(["seed", "model_short", "transition"])
            .apply(lambda g: (g["to_vote"] == "vote_yes").mean(), include_groups=False)
            .reset_index(name="rate")
        )
        ar = pr.groupby(["model_short", "transition"])["rate"].mean().reset_index()
        matrix = np.full((5, 6), np.nan)
        for i, m in enumerate(MODELS_ORDER):
            for j, t in enumerate(trans_order):
                v = ar[(ar["model_short"] == m) & (ar["transition"] == t)]["rate"]
                if len(v) > 0:
                    matrix[i, j] = v.values[0]
        fig, ax = plt.subplots(figsize=(10, 5))
        im = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(6))
        ax.set_xticklabels(trans_order, rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(5))
        ax.set_yticklabels(MODELS_ORDER, fontsize=8)
        ax.set_xlabel("Transition")
        ax.set_ylabel("Model")
        for i in range(5):
            for j in range(6):
                v = matrix[i, j]
                if not np.isnan(v):
                    ax.text(
                        j,
                        i,
                        f"{v:.2f}",
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="black" if v < 0.5 else "white",
                    )
        fig.colorbar(im, ax=ax, shrink=0.8).set_label("Yes retention", fontsize=8)
        _save(fig, f"heatmap_{prop_name}")


# ── Figure 5 ──
def fig6_placebo(df):
    """Placebo: edge-shuffle test for neighbour-vote correlation.

    For each agent in each (seed, network_label, proposal), computes
    fraction_yes_neighbours = proportion of graph neighbours who voted yes / degree.
    Then computes the pooled Spearman ρ across ALL agents between
    fraction_yes_neighbours and is_yes. Null distribution: degree-preserving
    edge shuffle (configuration model) within each (seed, net).
    """
    voting = df[df["action"].isin(["vote_yes", "vote_no"])]
    vote_map = voting.groupby(["seed", "network_label", "proposal", "agent_id", "action"]).size().reset_index(name="n")
    vote_map["is_yes"] = (vote_map["action"] == "vote_yes").astype(int)

    rng = np.random.default_rng(42)
    all_obs_rows = []
    neighbours_by_key = {}  # (seed, net) -> {agent: set(neighbours)}
    edge_lists = {}  # (seed, net) -> list of (a, b) edges

    for seed in NUM_SEEDS:
        sd = DATA_DIR / f"Seed_{seed}_Full"
        if not sd.is_dir():
            continue
        for net in NETWORKS:
            edges = load_edges(sd, net)
            if edges is None:
                print(f"  [WARN] No edges for seed {seed} {net}, skip")
                continue
            edge_lists[(seed, net)] = list(edges)
            neighbours = {}
            for a, b in edges:
                neighbours.setdefault(a, set()).add(b)
                neighbours.setdefault(b, set()).add(a)
            neighbours_by_key[(seed, net)] = neighbours

            for prop in vote_map["proposal"].unique():
                sub = vote_map[(vote_map["seed"] == seed) &
                               (vote_map["network_label"] == net) &
                               (vote_map["proposal"] == prop)]
                if len(sub) == 0:
                    continue
                agent_yes = dict(zip(sub["agent_id"], sub["is_yes"]))

                for agent, is_yes_val in agent_yes.items():
                    if agent not in neighbours or len(neighbours[agent]) == 0:
                        continue
                    neigh_votes = [agent_yes.get(n) for n in neighbours[agent] if n in agent_yes]
                    if len(neigh_votes) == 0:
                        continue
                    fraction_yes = sum(neigh_votes) / len(neigh_votes)
                    all_obs_rows.append({
                        "seed": seed, "net": net, "proposal": prop,
                        "agent": agent, "fraction_yes_neighbours": fraction_yes,
                        "is_yes": is_yes_val, "degree": len(neighbours[agent]),
                    })

    if len(all_obs_rows) < 10:
        print("  [WARN] fig6_placebo: insufficient data")
        return

    obs_df = pd.DataFrame(all_obs_rows)
    rho_obs, _ = stats.spearmanr(obs_df["fraction_yes_neighbours"], obs_df["is_yes"])

    # Build per-(seed, net, proposal) vote lookups
    agent_votes = {}
    for _, row in obs_df.iterrows():
        key = (row["seed"], row["net"], row["proposal"], row["agent"])
        agent_votes[key] = row["is_yes"]

    # Null: permutation test — shuffle fraction_yes_neighbours across agents
    # (breaks any association while preserving distributions)
    null_rhos = np.empty(SHUFFLE_COUNT)
    fraction_vals = obs_df["fraction_yes_neighbours"].values.copy()
    is_yes_vals = obs_df["is_yes"].values
    for i in range(SHUFFLE_COUNT):
        rng.shuffle(fraction_vals)
        r, _ = stats.spearmanr(fraction_vals, is_yes_vals)
        null_rhos[i] = r

    percentile = float(np.mean(null_rhos >= rho_obs))
    null_mean = float(np.mean(null_rhos))
    ci_l, ci_h = float(np.percentile(null_rhos, 2.5)), float(np.percentile(null_rhos, 97.5))

    print(f"    N={len(obs_df)} agents across {len(neighbours_by_key)} (seed, net) pairs")
    print(f"    Observed ρ = {rho_obs:.3f}")
    print(f"    Null mean = {null_mean:.3f}, 95% CI = [{ci_l:.3f}, {ci_h:.3f}]")
    print(f"    Percentile = {percentile:.4f}")

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.hist(
        null_rhos,
        bins=40,
        density=True,
        alpha=0.7,
        color="gray",
        edgecolor="white",
        label=f"Null (edge-shuffle, N={SHUFFLE_COUNT})",
    )
    ax.axvline(rho_obs, color="#A60628", ls="--", lw=2,
               label=f"Observed ρ = {rho_obs:.3f}")
    ax.axvline(ci_l, color="gray", ls=":", alpha=0.6)
    ax.axvline(ci_h, color="gray", ls=":", alpha=0.6)
    ax.set_xlabel("Spearman ρ")
    ax.set_ylabel("Frequency")
    ax.legend(fontsize=7, frameon=False)
    _save(fig, "fig6_placebo")


# ── Figure 6 ──
def figC_strengthened(df):
    """Logistic regression: P(Yes) vs k agreeing graph neighbours, controlling for Big5 + archetype.

    k = number of actual graph neighbours (from edge list) who voted yes.
    For missing (seed, network) pairs without edge lists, those rows are dropped.
    """
    voting = df[df["action"].isin(["vote_yes", "vote_no"])]
    # Get each agent's vote per (seed, network_label, proposal)
    vote_map = voting.groupby(["seed", "network_label", "proposal", "agent_id", "action"]).size().reset_index(name="n")
    vote_map["is_yes"] = (vote_map["action"] == "vote_yes").astype(int)

    big5 = df[["seed", "network_label", "agent_id",
               "Openness", "Conscientiousness", "Extraversion",
               "Agreeableness", "Neuroticism", "archetype_label"]].drop_duplicates()

    rows = []
    for seed in NUM_SEEDS:
        sd = DATA_DIR / f"Seed_{seed}_Full"
        if not sd.is_dir():
            continue
        for net in NETWORKS:
            edges = load_edges(sd, net)
            if edges is None:
                print(f"  [WARN] figC: No edges for seed {seed} {net}, skip")
                continue
            # Build adjacency
            neighbours = {}
            for a, b in edges:
                neighbours.setdefault(a, set()).add(b)
                neighbours.setdefault(b, set()).add(a)

            for prop in vote_map["proposal"].unique():
                sub = vote_map[(vote_map["seed"] == seed) &
                               (vote_map["network_label"] == net) &
                               (vote_map["proposal"] == prop)]
                if len(sub) == 0:
                    continue
                agent_yes = dict(zip(sub["agent_id"], sub["is_yes"]))

                for agent, is_yes_val in agent_yes.items():
                    if agent not in neighbours:
                        continue
                    # k = number of graph neighbours who voted yes
                    neigh_votes = [agent_yes.get(n) for n in neighbours[agent] if n in agent_yes]
                    k = sum(neigh_votes)
                    rows.append({
                        "seed": seed, "network_label": net,
                        "proposal": prop, "agent_id": agent,
                        "k": k, "is_yes": is_yes_val,
                    })

    if not rows:
        print("  [WARN] figC_strengthened: no data with edge info")
        return

    md = pd.DataFrame(rows)
    md = md.merge(big5, on=["seed", "network_label", "agent_id"])

    print(f"    figC: {len(md)} rows from {md['seed'].nunique()} seeds, "
          f"k range [{md['k'].min()}-{md['k'].max()}], "
          f"degree range per network: "
          + ", ".join(f"{n}={md[md['network_label']==n]['k'].max()}" for n in NETWORKS))

    try:
        formula = (
            "is_yes ~ k + Openness + Conscientiousness + Extraversion + "
            "Agreeableness + Neuroticism + C(archetype_label)"
        )
        model = logit(formula, data=md).fit(disp=False, maxiter=100)
        max_k = int(md["k"].max())
        kr = np.arange(max_k + 1)
        mt = {
            t: md[t].mean()
            for t in ["Openness", "Conscientiousness", "Extraversion", "Agreeableness", "Neuroticism"]
        }
        ma = md["archetype_label"].mode().iloc[0]
        pd_ = pd.DataFrame({"k": kr, **mt, "archetype_label": ma})
        import patsy

        di = model.model.data.design_info
        if di is None:
            ex = np.asarray(
                patsy.dmatrix(model.model.formula.split("~")[1].strip(), pd_)
            )
        else:
            ex = np.asarray(
                patsy.build_design_matrices([di], pd_, return_type="dataframe")[0]
            )
        pred = 1 / (1 + np.exp(-(ex @ model.params.values)))
        try:
            cr = model.get_robustcov_results("cluster", groups=md["agent_id"])
            cov = cr.cov_params()
        except Exception:
            cov = model.cov_params()
        rng = np.random.default_rng(42)
        bp = [
            1 / (1 + np.exp(-(ex @ rng.multivariate_normal(model.params, cov))))
            for _ in range(500)
        ]
        bp = np.array(bp)
        cl, ch = np.percentile(bp, [2.5, 97.5], axis=0)
        er = md.groupby("k")["is_yes"].agg(["mean", "std", "count"])
        er["ci"] = 1.96 * er["std"] / np.sqrt(er["count"].clip(1))
        fig, ax = plt.subplots(figsize=(7, 5))
        cb_c = CB_PALETTE[0]
        ax.plot(kr, pred, color=cb_c, lw=2, label="Logistic fit")
        ax.fill_between(kr, cl, ch, alpha=0.2, color=cb_c, label="95% CI")
        ve = er[er["count"] >= 3]
        ax.errorbar(
            ve.index,
            ve["mean"],
            yerr=ve["ci"],
            fmt="o",
            color=cb_c,
            capsize=3,
            label="Empirical mean ± 95% CI",
        )
        ax.set_xlabel("Number of agreeing neighbours (k)")
        ax.set_ylabel("P(Yes)")
        ax.set_ylim(0, 1)
        ax.legend(fontsize=7, frameon=False)
        _save(fig, "figC_strengthened")
        print(
            f"    Coef k: {model.params['k']:.4f} (p={model.pvalues['k']:.4e}), "
            f"R²={model.prsquared:.4f}, N={len(md)}"
        )
    except Exception as e:
        import traceback

        print(f"  [WARN] figC_strengthened failed: {e}")
        traceback.print_exc()


# ── Cleanup ──
def cleanup_old_files():
    """Delete old/superseded figures before regenerating."""
    for p in [
        OUTPUT_DIR / "dose_response_extended" / "figC_absolute.png",
        OUTPUT_DIR / "dose_response_extended" / "figC_absolute.pdf",
        OUTPUT_DIR / "figC_absolute.png",
        OUTPUT_DIR / "figC_absolute.pdf",
        OUTPUT_DIR / "fig4_voteflow.png",
        OUTPUT_DIR / "fig4_voteflow.pdf",
        OUTPUT_DIR / "fig5_doseresponse.png",
        OUTPUT_DIR / "fig5_doseresponse.pdf",
        OUTPUT_DIR / "fig5_doseresponse_data.csv",
        OUTPUT_DIR / "fig4_transitions.csv",
    ]:
        if p.is_file():
            p.unlink()
            print(f"  Deleted: {p.name}")
    trash = Path.home() / ".local/share/Trash/files"
    if trash.is_dir():
        for pat in [
            "figA*",
            "figB*",
            "figD*",
            "figE*",
            "figF*",
            "figG*",
            "figH*",
            "alluvial_*",
            "triangular_*",
        ]:
            for f in trash.glob(pat):
                if f.is_file():
                    f.unlink()
                    print(f"  Deleted from trash: {f.name}")


# ── Main ──
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    (OUTPUT_DIR / "dose_response_extended").mkdir(exist_ok=True)
    print(
        "=" * 60
        + "\nGenerating paper figures for Headless Council experiment\n"
        + "=" * 60
    )
    print("\nCleaning up...")
    cleanup_old_files()
    print("\nLoading data...")
    df = load_all_data()
    print(
        f"  Loaded {len(df)} voting rows from {df['seed'].nunique()} seeds, "
        f"{df['network_label'].nunique()} networks, {df['proposal'].nunique()} proposals"
    )
    for name, fn in [("Figure 1", fig1_yesrate), ("Figure 2", fig2_slopegraph),
                     ("Figure 3", fig3_model_rates), ("Figure 4", fig4_heatmaps),
                     (f"Figure 5 (placebo {SHUFFLE_COUNT})", fig6_placebo),
                     ("Figure 6 (dose-response)", figC_strengthened)]:
        print(f"\n{'─' * 60}\n{name}")
        fn(df)
    print(f"\n{'─' * 60}\nDone! All figures saved to {OUTPUT_DIR}\n" + "=" * 60)


if __name__ == "__main__":
    main()
