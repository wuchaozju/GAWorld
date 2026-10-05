#!/usr/bin/env python3
"""
GAWorld-Bench harness (v0.1)

Implements the scoring + aggregation core for GAWorld-Bench.
See ../GAWORLD_BENCH_DESIGN.md for the full design.

Implemented in v0.1:
  - Track A  (macro empirical fit, real anchors, schema-correct extractors)
  - Track C  (causal validity: known-sign + placebo + determinism)
  - Scorecard aggregation with a trust gate
  - Auto-report: every run writes results/report.md (+ timestamped archive) with
    per-track diagnosis and data-driven improvement suggestions.
  - --synthetic mode: fabricates structurally-correct fixtures so the whole
    pipeline runs without an LLM / simulation (used for verification + trial).
    Its scorecard carries trust gate FIXTURE and is written under
    results/synthetic/, never over the headline results/scorecard.json.

Implemented in v0.1.7:
  - Track B, games level: three stylized facts over archived playground games
    (referendum conformity, disaster panic rare / help common, rumor continued
    influence). Abstains below five usable games per fact.

Implemented in v0.1.8:
  - Track D, human judges: from archived 谁是真人 rooms, how often people
    take residents for people against how often they recognise each other.
    The design's four LLM-judge dimensions remain unimplemented.

Track E is stubbed (returns n/a) and left for later versions.

Usage (run from the repo-root benchmark/ folder):
    python gaworld_bench.py --synthetic
    python gaworld_bench.py --all                      # default: score real output/
    python gaworld_bench.py --track A --output-dir ../output
    python gaworld_bench.py --track B [--games-dir ../output/games]
    python gaworld_bench.py --track D [--games-dir ../output/games]   # reads <games-dir>/whois
    # Track C, live (runs compare-event; needs an LLM provider):
    python gaworld_bench.py --track C --run --days 3 --seed 42 [--llm-provider minimax]
    # Track C, from already-produced comparison dirs:
    python gaworld_bench.py --track C --comparisons-root ../output/comparisons \\
        --placebo-dir <dir> --det-a <state.csv> --det-b <state.csv>
    python gaworld_bench.py --all --run --days 3 --seed 42
"""

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # benchmark/ -> repo root
RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"
SIMULATOR = PROJECT_ROOT / "generative_city_sim.py"
COMPARISONS_OUT = PROJECT_ROOT / "output" / "comparisons"

# ── Track A: real-world anchors (城镇口径). See design doc §2 / §6. ───────────
#
# ``scope`` says which statistical population an anchor describes. An anchor
# whose scope is not the one being simulated is reported but **not scored**:
# ``data/citymap.md`` covers roughly 19 x 15 km of one Hangzhou district,
# where more than half of all commutes are under 5 km, while the commuting
# figures below describe Hangzhou as a whole. Measured across the whole
# distance-decay range the district reproduces the city's "within 5 km" share
# (52.3% vs 52%) but cannot reach its mean commute distance (5.94 km at best
# vs 8.1 km) — the tail simply does not exist on a 19 km map. Scoring the
# district against city figures measures the mismatch, not the model.
# See the congestion proposal §15.
ANCHORS = {
    "engel_coefficient": {"value": 0.288, "tol": 0.15, "scope": "national_urban",
                          "source": "国家统计局2024公报 (城镇28.8%)"},
    "savings_rate":      {"value": 0.35, "tol": 0.30, "scope": "national_urban",
                          "source": "2024 口径敏感, 区间30-43%"},
    "commute_minutes":   {"value": 34.5, "tol": 0.25, "scope": "city_wide",
                          "source": "2024中国主要城市通勤监测报告 (杭州)"},
    "transit_share":     {"value": 0.476, "tol": 0.25, "scope": "city_wide",
                          "source": "杭州市交通运输局2024"},
    "wealth_gini":       {"value": 0.70, "tol": 0.30, "scope": "national_urban",
                          "source": "CHFS/瑞信财富报告: 中国家庭财富Gini≈0.6-0.75"},
}

#: wealth_gini is computed over these employment statuses only (see Track A).
LABOUR_FORCE = frozenset({"employed", "unemployed"})

# ── Provenance of every scored number (MECHANISM_PROVENANCE.md, rule 3) ──────
# The weakest grade among the mechanisms behind a metric, what that mechanism
# is, and — for the two Track A columns that are a lookup of a configured table
# rather than an outcome — that the fit measures the table, not the model.
# Scores are unchanged; this is what a reader needs before citing one.
METRIC_PROVENANCE = {
    "engel_coefficient": {
        "grade": "c", "weakest": "spending.engel_curve 按月净收入分五档查表（系数未注明出处）",
        "echo": "快照里的值就是按收入查 engel_curve 得到的预算参数，不是从实际分类消费算出来的——拟合量的是这张表",
    },
    "savings_rate": {
        "grade": "c", "weakest": "spending.engel_curve 按月净收入分五档查表（系数未注明出处）",
        "echo": "快照里的值就是按收入查 engel_curve 得到的计划储蓄率，不是从实际收支算出来的——拟合量的是这张表",
    },
    "wealth_gini": {
        "grade": "c", "weakest": "开局存款 = 月净收入 × U(1, 6) 个月（initial_savings_months_*，定的）；收入锚点本身是 (a)",
    },
    "commute_minutes": {
        "grade": "c", "weakest": "distance_decay、agents_represent（按目标标定的旋钮）",
    },
    "transit_share": {
        "grade": "c", "weakest": "agents_represent、PCU 折算（定的）",
    },
}

#: Every Track C sign test reads a core state metric, and every core state
#: answers an event through one model call proposing its delta
#: (``infer_event_effect``) before hand-set dynamics carry it. Kept in step
#: with ``gaworld/research/measures.py`` by a test.
STATE_PROVENANCE = {
    "grade": "c",
    "weakest": "事件对九维状态的影响由一次模型调用直接给出（infer_event_effect），再经手写均值回归（update_state）——"
               "已知符号检验检的是模型对这件事的判断能否穿过状态动态传到指标上，不是对现实因果的独立检验",
}

#: Scope of the population actually being simulated. Anchors outside it are
#: context, not criteria.
SIM_SCOPE = "district"
#: Scopes an anchor may carry and still be scored against a district run.
SCORED_SCOPES = frozenset({"national_urban", "district"})

# ── Track C: known-sign interventions (metrics present in comparison_metrics.csv) ─
# Each maps an intervention dir name -> (state metric, expected delta sign).
SIGN_TESTS = [
    {"name": "traffic_restriction", "metric": "mobility_intent",   "sign": +1,
     "why": "限行→出行摩擦上升→流动意愿上升"},
    {"name": "layoff_shock",        "metric": "econ_security",     "sign": -1,
     "why": "裁员→收入骤降→经济安全感下降"},
    {"name": "layoff_shock",        "metric": "stress",            "sign": +1,
     "why": "裁员→压力上升"},
    {"name": "tax_cut",             "metric": "econ_security",     "sign": +1,
     "why": "减税→可支配收入上升→经济安全感上升"},
]
PLACEBO_EPS = 0.05      # |delta_mean| below this counts as "no effect"
DET_TOL = 1e-9          # float tolerance for determinism check

# Live-run config: maps each sign-test key -> (event-name, event-description)
# passed to `generative_city_sim.py compare-event`.
INTERVENTIONS = {
    "traffic_restriction": ("临时交通限行", "主干道限行导致通勤时间上升并影响出行决策"),
    "layoff_shock":        ("大规模裁员冲击", "部分企业裁员导致相关居民收入骤降"),
    "tax_cut":             ("个税减税", "个人所得税下调提高居民可支配收入"),
}
PLACEBO_EVENT = ("图书馆闭馆时间微调", "市图书馆闭馆时间调整10分钟，几乎不影响居民生活")

# Keywords for classifying an existing (timestamped, Chinese-named) comparison dir.
INTERVENTION_KEYWORDS = {
    "traffic_restriction": ("限行", "交通", "traffic"),
    "layoff_shock":        ("裁员", "失业", "layoff"),
    "tax_cut":             ("减税", "个税", "tax"),
}
PLACEBO_KEYWORDS = ("图书馆", "闭馆", "placebo")


# ── small IO helpers (stdlib only; no pandas dependency) ─────────────────────
def read_csv_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _floats(rows: list[dict], col: str) -> list[float]:
    out = []
    for r in rows:
        v = r.get(col)
        if v in (None, "", "nan", "NaN"):
            continue
        try:
            out.append(float(v))
        except ValueError:
            continue
    return out


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def gini(values: list[float]) -> float | None:
    """Gini coefficient over non-negative values (negatives clipped to 0)."""
    vals = sorted(max(0.0, v) for v in values)
    n = len(vals)
    total = sum(vals)
    if n == 0 or total <= 0:
        return None
    cum = 0.0
    weighted = 0.0
    for i, v in enumerate(vals, start=1):
        cum += v
        weighted += i * v
    return (2.0 * weighted) / (n * total) - (n + 1.0) / n


# ── Track A ──────────────────────────────────────────────────────────────────
def track_a_macro_fit(output_dir: Path) -> dict:
    """Compare aggregate sim statistics against real anchors."""
    metrics = {}
    n_samples = 0
    snap = output_dir / "economy" / "wealth_snapshot.csv"
    if snap.exists():
        rows = read_csv_rows(snap)
        n_samples = len(rows)
        for key in ("engel_coefficient", "savings_rate"):
            vals = _floats(rows, key)
            if vals:
                metrics[key] = statistics.fmean(vals)
        # Distribution-level: wealth Gini over net worth
        # (balance + housing fund − debt); debt column absent in old runs.
        # Only over the labour force: students, homemakers and retirees get a
        # (c)-class placeholder income band (8–22 元/h, MECHANISM_PROVENANCE),
        # not a modelled one, and it would pull the Gini toward equality.
        # Outputs written before the employment_status column fall back to
        # everyone, and say so.
        has_status = any("employment_status" in r for r in rows)
        gini_rows = [r for r in rows if r.get("employment_status") in LABOUR_FORCE] \
            if has_status else rows
        gini_population = (f"labour_force ({len(gini_rows)}/{len(rows)})" if has_status
                           else f"all ({len(rows)}; 旧输出无 employment_status 列，口径偏宽)")
        net_worth = []
        for r in gini_rows:
            try:
                nw = (float(r.get("balance") or 0)
                      + float(r.get("housing_fund") or 0)
                      - float(r.get("debt") or 0))
            except ValueError:
                continue
            net_worth.append(nw)
        g = gini(net_worth) if net_worth else None
        if g is not None:
            metrics["wealth_gini"] = g

    # commute_minutes / transit_share are optional: only scored if the sim
    # emitted the relevant files (not present in current default output).
    commute = output_dir / "state" / "commute_summary.csv"
    if commute.exists():
        vals = _floats(read_csv_rows(commute), "avg_travel_time")
        if vals:
            metrics["commute_minutes"] = statistics.fmean(vals)

    scored = {}
    context = {}
    populations = {"wealth_gini": gini_population} if "wealth_gini" in metrics else {}
    for key, sim in metrics.items():
        a = ANCHORS[key]
        rel_err = abs(sim - a["value"]) / a["value"]
        row = {"sim": round(sim, 4), "anchor": a["value"],
               "rel_err": round(rel_err, 4), "scope": a.get("scope", "unknown"),
               "source": a["source"]}
        if key in populations:
            row["population"] = populations[key]
        row.update(METRIC_PROVENANCE.get(key, {}))
        if a.get("scope") in SCORED_SCOPES:
            row["score"] = round(clamp01(1 - rel_err / a["tol"]), 4)
            scored[key] = row
        else:
            # Reported so the number stays visible, kept out of the score so a
            # scope mismatch cannot masquerade as model error.
            row["score"] = None
            row["note"] = f"scope {a.get('scope')} != sim scope {SIM_SCOPE}; context only"
            context[key] = row

    if not scored and not context:
        return {"track": "A", "status": "n/a",
                "note": "no economy/wealth_snapshot.csv found"}

    # Money-conservation audit: a hard gate, not an anchor fit. If the sim
    # exported conservation_audit.csv, max |drift| must stay within one cent.
    conservation = None
    audit = output_dir / "economy" / "conservation_audit.csv"
    if audit.exists():
        drifts = _floats(read_csv_rows(audit), "drift")
        if drifts:
            max_drift = max(abs(d) for d in drifts)
            conservation = {"max_abs_drift": round(max_drift, 4),
                            "pass": max_drift <= 0.01}

    s_vals = [m["score"] for m in scored.values()]
    score = statistics.fmean(s_vals) if s_vals else 0.0
    passed = bool(s_vals) and score >= 0.6 and all(s > 0 for s in s_vals)
    if conservation is not None:
        passed = passed and conservation["pass"]
    result = {"track": "A", "status": "ok", "score": round(score, 4),
              "pass": passed, "metrics": scored, "n_samples": n_samples,
              "sim_scope": SIM_SCOPE}
    if context:
        # Out-of-scope anchors ride along as context so the numbers stay
        # visible without steering the score.
        result["context_metrics"] = context
    if not s_vals:
        result["status"] = "no_in_scope_anchors"
        result["note"] = ("every anchor found is out of scope for a "
                          f"{SIM_SCOPE} run; see the congestion proposal §15")
    if conservation is not None:
        result["conservation"] = conservation
    return result


# ── Track C ──────────────────────────────────────────────────────────────────
# A1: score on the POST-EVENT effect (delta_final), not delta_mean. delta_mean
# averages over the whole run incl. pre-event steps and dilutes the signal 5-7x
# (see IMPROVEMENT_PLAN.md R1). delta_mean is kept only as a reference field.
EFFECT_COL = "delta_final"


def _event_effect(metrics_csv: Path, metric: str) -> dict | None:
    """Return {effect, delta_final, delta_mean} for a metric, or None if absent.

    `effect` is delta_final (post-event); falls back to delta_mean if the column
    is missing (older outputs).
    """
    for r in read_csv_rows(metrics_csv):
        if r.get("metric") != metric:
            continue
        def _get(col):
            try:
                return float(r[col])
            except (KeyError, ValueError):
                return None
        final, mean = _get("delta_final"), _get("delta_mean")
        effect = final if final is not None else mean
        if effect is None:
            return None
        return {"effect": effect, "delta_final": final, "delta_mean": mean}
    return None


def _metrics_path(src: Path) -> Path:
    """Accept either a comparison dir or a comparison_metrics.csv path."""
    return src / "comparison_metrics.csv" if src.is_dir() else src


def _load_current_epoch() -> int | None:
    """The simulator's current comparability epoch, read by file path so the
    harness stays importable without the simulator's dependencies."""
    import importlib.util
    path = PROJECT_ROOT / "gaworld" / "core" / "comparability.py"
    try:
        spec = importlib.util.spec_from_file_location("_gaworld_comparability", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolve annotations through it
        spec.loader.exec_module(module)
        return int(module.CURRENT_EPOCH)
    except (OSError, ImportError, AttributeError, ValueError, TypeError):
        return None


CURRENT_EPOCH = _load_current_epoch()


def _dir_epoch(comparison_dir: Path | None) -> int | None:
    """The code epoch a compare-event dir was produced by (its run_meta.json);
    None for dirs written before epochs were stamped."""
    if not comparison_dir:
        return None
    d = comparison_dir if comparison_dir.is_dir() else comparison_dir.parent
    try:
        value = json.loads((d / "run_meta.json").read_text(encoding="utf-8")).get("comparability_epoch")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, int) else None


def _dir_is_fast(comparison_dir: Path | None) -> bool:
    """True if a comparison dir was produced with --fast (from its run_meta.json)."""
    if not comparison_dir:
        return False
    d = comparison_dir if comparison_dir.is_dir() else comparison_dir.parent
    meta = d / "run_meta.json"
    if meta.exists():
        try:
            return bool(json.loads(meta.read_text(encoding="utf-8")).get("fast", False))
        except (json.JSONDecodeError, OSError):
            return False
    return False


def track_c_causal(sign_sources: dict[str, Path], placebo_dir: Path | None,
                   det_a: Path | None, det_b: Path | None,
                   incomplete: list[Path] | None = None) -> dict:
    """Causal validity: sign-correctness (post-event) + placebo + determinism.

    sign_sources maps a sign-test name -> comparison dir (or metrics csv).
    """
    out = {"track": "C", "status": "ok"}

    # C1 — known-sign, scored on the post-event effect (delta_final; A1)
    sign_results = []
    for t in SIGN_TESTS:
        src = sign_sources.get(t["name"])
        mcsv = _metrics_path(src) if src else None
        eff = _event_effect(mcsv, t["metric"]) if mcsv and mcsv.exists() else None
        delta = eff["effect"] if eff else None
        ok = delta is not None and (delta * t["sign"] > 0)
        sign_results.append({**{k: t[k] for k in ("name", "metric", "sign", "why")},
                             "grade": STATE_PROVENANCE["grade"],
                             "delta": delta,
                             "delta_final": eff["delta_final"] if eff else None,
                             "delta_mean": eff["delta_mean"] if eff else None,
                             "correct": ok})
    n_eval = sum(1 for r in sign_results if r["delta"] is not None)
    n_ok = sum(1 for r in sign_results if r["correct"])
    sign_score = (n_ok / n_eval) if n_eval else 0.0
    out["sign"] = {"score": round(sign_score, 4), "n_eval": n_eval, "n_correct": n_ok,
                   "effect_col": EFFECT_COL, "tests": sign_results}
    out["provenance"] = dict(STATE_PROVENANCE)

    # C2 placebo + C3 determinism (shared with the multi-seed scorer)
    placebo_score, out["placebo"] = _placebo_block(placebo_dir)
    det_score, out["determinism"] = _determinism_block(det_a, det_b)
    if incomplete:  # A5
        out["incomplete"] = [p.name for p in incomplete]
    # low-fidelity flag: any scored comparison dir produced with --fast
    out["fast"] = any(_dir_is_fast(d) for d in list(sign_sources.values()) + [placebo_dir])
    # which code produced each comparison (gaworld/core/comparability.py)
    out["epochs"] = {name: _dir_epoch(src) for name, src in sign_sources.items() if src}
    if placebo_dir:
        out["epochs"]["placebo"] = _dir_epoch(placebo_dir)

    coverage = n_eval / len(SIGN_TESTS)
    out["coverage"] = round(coverage, 4)
    base, out["score"] = _aggregate_c(sign_score, placebo_score, det_score, coverage)
    out["score_uncovered"] = base
    out["pass"] = (sign_score >= 0.75) and (placebo_score is None or placebo_score >= 0.8) \
        and (coverage >= 0.75)
    out["det_status"] = out["determinism"]["status"]
    return out


# ── shared Track C sub-blocks ────────────────────────────────────────────────
def _placebo_block(placebo_dir: Path | None) -> tuple[float | None, dict]:
    if placebo_dir and (placebo_dir / "comparison_metrics.csv").exists():
        rows = read_csv_rows(placebo_dir / "comparison_metrics.csv")
        deltas = _floats(rows, EFFECT_COL) or _floats(rows, "delta_mean")
        within = [abs(d) < PLACEBO_EPS for d in deltas]
        score = (sum(within) / len(within)) if within else 0.0
        worst = max((abs(d) for d in deltas), default=0.0)
        return score, {"score": round(score, 4), "eps": PLACEBO_EPS,
                       "n_metrics": len(deltas), "max_abs_delta": round(worst, 4)}
    return None, {"score": None, "note": "no completed placebo comparison"}


def _determinism_block(det_a: Path | None, det_b: Path | None) -> tuple[float | None, dict]:
    if det_a and det_b and det_a.exists() and det_b.exists():
        score, n = _determinism_score(det_a, det_b)
        status = "ok" if score >= 1.0 - 1e-12 else "fail"
        return score, {"score": round(score, 6), "n_points": n, "status": status}
    return None, {"score": None, "status": "unassessed", "note": "no baseline pair provided"}


def _aggregate_c(sign_score: float, placebo_score, det_score, coverage: float) -> tuple[float, float]:
    parts, weights = [sign_score], [0.5]
    if placebo_score is not None:
        parts.append(placebo_score); weights.append(0.25)
    if det_score is not None:
        parts.append(det_score); weights.append(0.25)
    base = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
    return round(base, 4), round(base * coverage, 4)  # (uncovered, coverage-discounted A3)


def _determinism_score(a: Path, b: Path) -> tuple[float, int]:
    """Long-format state files: agent_id,step,metric,value. Fraction matching."""
    def index(p: Path) -> dict:
        d = {}
        for r in read_csv_rows(p):
            try:
                d[(r["agent_id"], r["step"], r["metric"])] = float(r["value"])
            except (KeyError, ValueError):
                continue
        return d
    da, db = index(a), index(b)
    keys = set(da) & set(db)
    if not keys:
        return 0.0, 0
    match = sum(1 for k in keys if math.isclose(da[k], db[k], abs_tol=DET_TOL))
    return match / len(keys), len(keys)


def resolve_from_comparisons(
        root: Path) -> tuple[dict[str, Path], Path | None, list[Path]]:
    """Classify existing comparison dirs by keyword; newest match per key wins.

    Also returns `incomplete`: dirs that match a keyword but never produced
    comparison_metrics.csv (interrupted runs; A5).
    """
    sign_sources: dict[str, Path] = {}
    placebo: Path | None = None
    incomplete: list[Path] = []
    if not root.exists():
        return sign_sources, placebo, incomplete
    keyword_sets = [*INTERVENTION_KEYWORDS.values(), PLACEBO_KEYWORDS]
    for d in sorted((p for p in root.iterdir() if p.is_dir()),
                    key=lambda p: p.stat().st_mtime):  # newer overwrites older
        nm = d.name.lower()
        matched = any(any(k.lower() in nm for k in kws) for kws in keyword_sets)
        if not (d / "comparison_metrics.csv").exists():
            if matched:
                incomplete.append(d)
            continue
        for key, kws in INTERVENTION_KEYWORDS.items():
            if any(k.lower() in nm for k in kws):
                sign_sources[key] = d
        if any(k.lower() in nm for k in PLACEBO_KEYWORDS):
            placebo = d
    return sign_sources, placebo, incomplete


def _run_compare_event(name: str, desc: str, days: int, seed: int,
                       provider: str | None, fast: bool = False) -> Path | None:
    """Invoke `generative_city_sim.py compare-event`; return the new comparison dir."""
    cmd = [sys.executable, str(SIMULATOR), "compare-event",
           "--event-name", name, "--event-description", desc,
           "--event-day", "2", "--event-time", "09:00",
           "--sim-days", str(days), "--seed", str(seed)]
    if provider:
        cmd += ["--llm-provider", provider]
    if fast:
        cmd += ["--fast"]
    print(f"[bench] compare-event: {name} (days={days}, seed={seed})")
    before = {p.name for p in COMPARISONS_OUT.glob("*")} if COMPARISONS_OUT.exists() else set()
    r = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if r.returncode != 0:
        print(f"[bench] WARN: compare-event failed for '{name}' (rc={r.returncode})")
        return None
    new = [p for p in COMPARISONS_OUT.glob("*")
           if p.is_dir() and p.name not in before]
    return max(new, key=lambda p: p.stat().st_mtime, default=None)


def orchestrate_track_c(days: int, seed: int, provider: str | None,
                        det_a: Path | None, det_b: Path | None,
                        fast: bool = False) -> dict:
    """Live Track C: run compare-event for each intervention + placebo, then score.

    Requires a working LLM provider; each call runs a full paired simulation.
    Determinism is only assessed if --det-a/--det-b are supplied.
    """
    sign_sources: dict[str, Path] = {}
    for key, (name, desc) in INTERVENTIONS.items():
        d = _run_compare_event(name, desc, days, seed, provider, fast=fast)
        if d:
            sign_sources[key] = d
    placebo_dir = _run_compare_event(*PLACEBO_EVENT, days, seed, provider, fast=fast)
    if not sign_sources and placebo_dir is None:
        return {"track": "C", "status": "n/a",
                "note": "live compare-event runs failed — check LLM provider / config"}
    return track_c_causal(sign_sources, placebo_dir, det_a, det_b)


# ── A2: cross-seed significance ──────────────────────────────────────────────
# 95% two-sided Student-t critical values by degrees of freedom (n-1).
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
        15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
        27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def ci95(samples: list[float]) -> tuple[float | None, float | None, bool, int]:
    """Return (mean, halfwidth, significant, n). significant = 95% CI excludes 0.

    n<2 yields no CI and significant=False (one point can't establish significance).
    """
    n = len(samples)
    if n == 0:
        return None, None, False, 0
    m = statistics.fmean(samples)
    if n < 2:
        return m, None, False, n
    hw = _T95.get(n - 1, 1.96) * statistics.stdev(samples) / math.sqrt(n)
    return m, hw, abs(m) > hw, n


def _metrics_for_intervention(name: str) -> list[str]:
    return [t["metric"] for t in SIGN_TESTS if t["name"] == name]


def track_c_multiseed(samples_by_test: dict[tuple[str, str], list[float]],
                      placebo_dir: Path | None, det_a: Path | None,
                      det_b: Path | None, incomplete: list[Path] | None = None,
                      fast: bool = False) -> dict:
    """Significance-aware Track C: score the sign only on tests whose effect is
    significant across seeds (95% CI excludes 0). Non-significant tests are
    reported as 'ns' and excluded from the sign numerator/denominator (A2)."""
    out = {"track": "C", "status": "ok", "mode": "multiseed", "fast": bool(fast)}
    tests = []
    n_sig = n_correct = n_data = 0
    for t in SIGN_TESTS:
        s = samples_by_test.get((t["name"], t["metric"]), [])
        m, hw, sig, n = ci95(s)
        if n > 0:
            n_data += 1
        correct = bool(sig and m is not None and m * t["sign"] > 0)
        if sig:
            n_sig += 1
            n_correct += int(correct)
        tests.append({**{k: t[k] for k in ("name", "metric", "sign", "why")},
                      "grade": STATE_PROVENANCE["grade"],
                      "mean": None if m is None else round(m, 4),
                      "ci95": None if hw is None else round(hw, 4),
                      "n": n, "significant": sig, "correct": correct})
    sign_score = (n_correct / n_sig) if n_sig else 0.0
    out["sign"] = {"score": round(sign_score, 4), "n_eval": n_sig, "n_correct": n_correct,
                   "n_significant": n_sig, "n_data": n_data, "effect_col": EFFECT_COL,
                   "tests": tests}
    out["provenance"] = dict(STATE_PROVENANCE)

    placebo_score, out["placebo"] = _placebo_block(placebo_dir)
    det_score, out["determinism"] = _determinism_block(det_a, det_b)
    if incomplete:
        out["incomplete"] = [p.name for p in incomplete]

    coverage = n_data / len(SIGN_TESTS)
    sig_coverage = n_sig / len(SIGN_TESTS)
    max_n = max((len(s) for s in samples_by_test.values()), default=0)
    out["max_samples"] = max_n
    out["insufficient_seeds"] = max_n < 2  # significance needs ≥2 seeds per test
    if out["insufficient_seeds"]:
        out["note"] = f"每项最多 {max_n} 个样本；显著性检验需 ≥2 个 seed。用 --seeds a,b,c 多 seed 重跑。"
    out["coverage"] = round(coverage, 4)
    out["significance_coverage"] = round(sig_coverage, 4)
    base, out["score"] = _aggregate_c(sign_score, placebo_score, det_score, coverage)
    out["score_uncovered"] = base
    out["pass"] = (sign_score >= 0.75) and (coverage >= 0.75) and (sig_coverage >= 0.5) \
        and (placebo_score is None or placebo_score >= 0.8)
    out["det_status"] = out["determinism"]["status"]
    return out


CHECKPOINT_PATH = RESULTS_DIR / "checkpoint_multiseed.json"


def _load_checkpoint() -> dict | None:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_checkpoint(state: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_PATH.with_name(CHECKPOINT_PATH.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CHECKPOINT_PATH)


def orchestrate_track_c_multiseed(seeds: list[int], days: int, provider: str | None,
                                  det_a: Path | None, det_b: Path | None,
                                  resume: bool = False, fast: bool = False) -> dict:
    """Run each intervention across seeds and score with significance.

    Checkpoint/resume (--continue): progress is saved to CHECKPOINT_PATH after
    every completed (intervention, seed) unit. If a compare-event call fails
    (e.g. LLM quota), the partial state is kept and the run stops with a resume
    hint; re-running with resume=True skips the units already done.
    """
    plan = [(key, seed) for key in INTERVENTIONS for seed in seeds]
    completed: dict[tuple[str, str], dict] = {}  # (key, seed) -> {metric: effect}

    ckpt = _load_checkpoint() if resume else None
    if ckpt is not None:
        if ckpt.get("days") != days or sorted(ckpt.get("seeds", [])) != sorted(seeds):
            return {"track": "C", "status": "n/a",
                    "note": f"--continue 的 days/seeds 与已存进度不一致（存={ckpt.get('days')}天"
                            f"/{ckpt.get('seeds')}）。请用相同参数，或删除 {CHECKPOINT_PATH} 重新开始。"}
        for u in ckpt.get("completed", []):
            completed[(u["intervention"], u["seed"])] = u["metrics"]
        print(f"[bench] --continue: 已完成 {len(completed)}/{len(plan)} 个单元，续跑剩余。")
    elif resume:
        print("[bench] --continue: 未找到 checkpoint，从头开始。")

    def _persist():
        _save_checkpoint({
            "seeds": seeds, "days": days, "n_units": len(plan),
            "completed": [{"intervention": k, "seed": s, "metrics": m}
                          for (k, s), m in completed.items()],
        })

    for key, seed in plan:
        if (key, seed) in completed:
            continue
        name, desc = INTERVENTIONS[key]
        d = _run_compare_event(name, desc, days, seed, provider, fast=fast)
        mcsv = (d / "comparison_metrics.csv") if d else None
        if not (mcsv and mcsv.exists()):
            _persist()  # save progress so far, then stop for the user to retry later
            return {"track": "C", "status": "incomplete",
                    "note": f"compare-event 在 {key}/seed={seed} 失败（可能 API 用量超限）。"
                            f"已保存进度 {len(completed)}/{len(plan)} → 配额恢复后用 "
                            f"`--continue`（相同 --seeds/--days）续跑。"}
        completed[(key, seed)] = {m: eff["effect"] for m in _metrics_for_intervention(key)
                                  if (eff := _event_effect(mcsv, m))}
        _persist()  # checkpoint after each successful unit

    samples: dict[tuple[str, str], list[float]] = {}
    for (key, _seed), metrics in completed.items():
        for metric, effect in metrics.items():
            samples.setdefault((key, metric), []).append(effect)
    if not samples:
        return {"track": "C", "status": "n/a",
                "note": "multi-seed runs produced no data — check LLM provider / config"}
    CHECKPOINT_PATH.unlink(missing_ok=True)  # done -> clear checkpoint
    return track_c_multiseed(samples, None, det_a, det_b, None, fast=fast)


# ── Track B: stylized facts from archived playground games ───────────────────
#
# The rumor, referendum and disaster games archive every finished game to
# output/games/<kind>/*.json (gaworld/apps/game_archive.py). Each fact pools
# every eligible game of its kind. Too little data abstains
# (``reproduced: None``) instead of failing; an abstention still costs the
# score, the way coverage does in Track C.
#
# Level — read before citing any of this. A resident here answers one prompt
# after seeing the room's tally (referendum), the neighbours' actions
# (disaster) or a correction (rumor): a one-step agent → crowd → agent loop,
# not the agent → environment → agent loop trackb_spatial.py measures, and
# every prompt carries a cue, written next to its fact. All three are grade
# (c) (MECHANISM_PROVENANCE.md): they say what a persona prompt answers,
# never how large a real effect is. The disaster thresholds turn "rare" and
# "common" into numbers; the claim is the qualitative one.
#
# Why no rumor S-curve: a game has at most 14 residents, 5 rounds and a
# forward reaches at most 4 new people, so the cumulative-reach curve's shape
# is mostly that arithmetic. Its continued-influence check reads a turn the
# model actually answers.
GAMES_DIR = PROJECT_ROOT / "output" / "games"
GAME_KINDS = ("referendum", "disaster", "rumor")
#: Fewer eligible games than this and a fact abstains.
MIN_GAMES = 5
B_ALPHA = 0.05            # one-sided
PANIC_EXTREME_MAX = 0.2   # share of panic == 5
HELP_RATE_MIN = 0.5
CIE_RESIDUAL_MIN = 0.25   # mean belief after correction ≥ this × before
B_PASS = 0.5              # design §2: score_B ≥ 0.5
#: An off-vocabulary or unreadable disaster reply — not counted.
DISASTER_OTHER = "其他"

B_FACTS = [
    {"id": "referendum_conformity", "kind": "referendum", "name": "公开表决向多数靠拢（从众）",
     "criterion": "不带宣传口径、私下有严格多数的对局里，朝多数改的票显著多于背离多数的（单侧二项检验 p<0.05）",
     "min_units": 8, "unit": "张定向改票",
     "reference": "Asch 1956; Deutsch & Gerard 1955",
     "cue": "正式表决的提示词写着「看到多数人怎么想之后改主意不丢人」，也写着「不要为了合群而改」——两个方向都提了，但从众被点了名",
     "advice": "不填宣传口径"},
    {"id": "disaster_panic_rare", "kind": "disaster", "name": "灾害中极度恐慌少见、互助常见",
     "criterion": f"极度恐慌（panic=5）占比 ≤ {PANIC_EXTREME_MAX} 且顾得上帮别人的占比 ≥ {HELP_RATE_MIN}"
                  "（阈值是事先定的约定，把「少见/常见」落成数，不是文献给的数字）",
     "min_units": 20, "unit": "条反应",
     "reference": "Quarantelli 2001; Drury, Cocking & Reicher 2009",
     "cue": "恐慌是 1–5 的自评，不是行为；「是否顾得上帮别人」是必答项，「救助他人」是六个选项之一",
     "advice": ""},
    {"id": "rumor_continued_influence", "kind": "rumor", "name": "辟谣后相信度下降但不归零（持续影响效应）",
     "criterion": f"被辟谣的相信者里，相信度下降的显著多于上升的（单侧符号检验 p<0.05），"
                  f"且辟谣后平均相信度 ≥ 辟谣前的 {CIE_RESIDUAL_MIN:.0%}",
     "min_units": 8, "unit": "个被辟谣的相信者",
     "reference": "Lewandowsky et al. 2012; Walter & Tukachinsky 2020",
     "cue": "辟谣那一轮的提示词会告诉居民他先前信了多少——残留可能是对这个数字的锚定，不一定是持续影响",
     "advice": "让辟谣发生：得有人选「辟谣」，被辟谣的人当时还相信"},
]


def load_games(games_dir: Path) -> tuple[dict[str, list[dict]], int]:
    """Archived games by kind, and how many files could not be read."""
    games: dict[str, list[dict]] = {}
    unreadable = 0
    for kind in GAME_KINDS:
        for path in sorted((games_dir / kind).glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                unreadable += 1
                continue
            if isinstance(record, dict) and isinstance(record.get("result"), dict):
                games.setdefault(kind, []).append(record)
            else:
                unreadable += 1
    return games, unreadable


def binom_upper_p(k: int, n: int) -> float:
    """One-sided P(X ≥ k) for X ~ Binomial(n, 1/2)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def _fact_conformity(games: list[dict]) -> tuple[int, int, dict, bool]:
    """Private ballot → public ballot, on the axis minority −1 / 弃权 0 / majority +1."""
    toward = away = eligible = 0
    for record in games:
        run = record["result"]
        if str(run.get("campaign") or "").strip():
            continue  # a slogan is persuasion, not the room
        voters = run.get("voters") or []
        private = [(v.get("private") or {}).get("stance") for v in voters]
        yes, no = private.count("支持"), private.count("反对")
        if yes == no:
            continue  # no majority to conform to
        major, minor = ("支持", "反对") if yes > no else ("反对", "支持")
        axis = {major: 1, "弃权": 0, minor: -1}
        eligible += 1
        for voter in voters:
            before = axis.get((voter.get("private") or {}).get("stance"))
            after = axis.get((voter.get("public") or {}).get("stance"))
            if before is None or after is None or before == after:
                continue
            if after > before:
                toward += 1
            else:
                away += 1
    n = toward + away
    p = binom_upper_p(toward, n) if n else None
    values = {"toward": toward, "away": away, "p": None if p is None else float(f"{p:.3g}")}
    return eligible, n, values, p is not None and p < B_ALPHA


def _fact_panic(games: list[dict]) -> tuple[int, int, dict, bool]:
    n = extreme = helped = eligible = 0
    for record in games:
        reactions = [r for agent in record["result"].get("agents") or []
                     for r in agent.get("reactions") or [] if r.get("action") != DISASTER_OTHER]
        if not reactions:
            continue
        eligible += 1
        n += len(reactions)
        extreme += sum(1 for r in reactions if r.get("panic") == 5)
        helped += sum(1 for r in reactions if r.get("help"))
    share = extreme / n if n else None
    rate = helped / n if n else None
    values = {"extreme_share": None if share is None else round(share, 4),
              "help_rate": None if rate is None else round(rate, 4)}
    return eligible, n, values, bool(n) and share <= PANIC_EXTREME_MAX and rate >= HELP_RATE_MIN


def _fact_continued_influence(games: list[dict]) -> tuple[int, int, dict, bool]:
    """Belief before and after the one correction a believer can receive.

    A rumor node speaks a second time only when it believed the rumor and
    was then told it is false, so two entries in ``beliefs`` are exactly a
    corrected believer. Games archived before ``beliefs`` existed are skipped.
    """
    pairs: list[tuple[int, int]] = []
    eligible = 0
    for record in games:
        nodes = record["result"].get("nodes") or []
        if not any("beliefs" in node for node in nodes):
            continue
        eligible += 1
        pairs += [(int(b[0]), int(b[1])) for node in nodes
                  for b in [node.get("beliefs") or []] if len(b) >= 2]
    down = sum(1 for before, after in pairs if after < before)
    up = sum(1 for before, after in pairs if after > before)
    p = binom_upper_p(down, down + up) if down + up else None
    pre = statistics.fmean(b for b, _ in pairs) if pairs else None
    post = statistics.fmean(a for _, a in pairs) if pairs else None
    residual = post / pre if pre else None
    values = {"down": down, "up": up, "p": None if p is None else float(f"{p:.3g}"),
              "before": None if pre is None else round(pre, 1),
              "after": None if post is None else round(post, 1),
              "residual": None if residual is None else round(residual, 4)}
    ok = p is not None and p < B_ALPHA and residual is not None and residual >= CIE_RESIDUAL_MIN
    return eligible, len(pairs), values, ok


_FACT_FNS = {
    "referendum_conformity": _fact_conformity,
    "disaster_panic_rare": _fact_panic,
    "rumor_continued_influence": _fact_continued_influence,
}


def track_b_games(games_dir: Path) -> dict:
    """Track B (games level): the pre-registered facts over every archived game."""
    games, unreadable = load_games(games_dir)
    facts = []
    for spec in B_FACTS:
        eligible, units, values, ok = _FACT_FNS[spec["id"]](games.get(spec["kind"], []))
        if eligible < MIN_GAMES:
            reproduced, abstain = None, f"可用对局 {eligible}/{MIN_GAMES}"
        elif units < spec["min_units"]:
            reproduced, abstain = None, f"样本 {units}/{spec['min_units']} {spec['unit']}"
        else:
            reproduced, abstain = bool(ok), ""
        facts.append({**spec, "grade": "c", "games": eligible, "units": units,
                      "values": values, "reproduced": reproduced, "abstain": abstain})
    providers: dict[str, int] = {}
    for record in (r for kind in GAME_KINDS for r in games.get(kind, [])):
        name = record.get("provider") or "未记录"
        providers[name] = providers.get(name, 0) + 1
    assessed = [f for f in facts if f["reproduced"] is not None]
    out = {"track": "B", "level": "games", "games_dir": _repo_relative(games_dir),
           "games": {kind: len(games.get(kind, [])) for kind in GAME_KINDS},
           "unreadable": unreadable, "providers": providers, "facts": facts,
           "n_assessed": len(assessed),
           "n_reproduced": sum(1 for f in assessed if f["reproduced"])}
    if not assessed:
        return {**out, "status": "n/a",
                "note": f"对局不足（每条需 ≥{MIN_GAMES} 局可用对局，见报告）"}
    score = out["n_reproduced"] / len(B_FACTS)  # abstentions count against it
    return {**out, "status": "ok", "score": round(score, 4), "pass": score >= B_PASS,
            "coverage": round(len(assessed) / len(B_FACTS), 4)}


# ── Track D: can people tell residents from people? ──────────────────────────
#
# The 谁是真人 game (gaworld/apps/whois_api.py) seats residents and people in
# one anonymous group chat; after it, every person marks each other number
# human or resident. Revealed rooms are archived to output/games/whois/*.json.
# This is the one Track D signal that is not a model judging a model: the
# judges are people. Of the design's four Track D dimensions (an LLM-judge
# scorecard) none is implemented yet; this is a fifth, human-judged one.
#
#   score_D = min(1, P(resident judged human) / P(person judged human))
#
# 1.0 = people mistake residents for people as often as they recognise each
# other. Pass at 0.7 (design §2). Read with the cues: residents are asked for
# short spoken messages and are not told about the guessing; judges are
# fellow players; one judge casts several ballots, so the intervals below
# (Wilson, per ballot) are optimistic.
D_MIN_ROOMS = 5
D_MIN_RESIDENT_JUDGMENTS = 20
D_MIN_HUMAN_JUDGMENTS = 10
D_PASS = 0.7


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n trials."""
    if n <= 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def track_d_whois(games_dir: Path) -> dict:
    """Track D (human judges): residents' pass rate against people's own."""
    rooms, unreadable = [], 0
    for path in sorted((games_dir / "whois").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable += 1
            continue
        res = ((record.get("result") or {}).get("results") if isinstance(record, dict) else None)
        if isinstance(res, dict):
            rooms.append(record)
        else:
            unreadable += 1
    sums = {"resident_judged_human": 0, "resident_judgments": 0, "human_judged_human": 0, "human_judgments": 0}
    correct = total = 0
    providers: dict[str, int] = {}
    for record in rooms:
        res = record["result"]["results"]
        for key in sums:
            sums[key] += int(res.get(key) or 0)
        for judge in res.get("judges") or []:
            correct += int(judge.get("correct") or 0)
            total += int(judge.get("total") or 0)
        name = record.get("provider") or "未记录"
        providers[name] = providers.get(name, 0) + 1
    rn, hn = sums["resident_judgments"], sums["human_judgments"]
    out = {
        "track": "D", "level": "human_judges", "games_dir": _repo_relative(games_dir),
        "rooms": len(rooms), "unreadable": unreadable, "providers": providers, **sums,
        "resident_pass_rate": round(sums["resident_judged_human"] / rn, 4) if rn else None,
        "resident_ci": wilson(sums["resident_judged_human"], rn),
        "human_rate": round(sums["human_judged_human"] / hn, 4) if hn else None,
        "human_ci": wilson(sums["human_judged_human"], hn),
        "accuracy": round(correct / total, 4) if total else None,
        "dimensions": "人类判别（设计里的四个 LLM 评审维度未实现）",
    }
    short = []
    if len(rooms) < D_MIN_ROOMS:
        short.append(f"对局 {len(rooms)}/{D_MIN_ROOMS}")
    if rn < D_MIN_RESIDENT_JUDGMENTS:
        short.append(f"对居民的判断 {rn}/{D_MIN_RESIDENT_JUDGMENTS}")
    if hn < D_MIN_HUMAN_JUDGMENTS:
        short.append(f"对真人的判断 {hn}/{D_MIN_HUMAN_JUDGMENTS}")
    if short or not out["human_rate"]:
        return {**out, "status": "n/a", "abstain": "；".join(short) or "真人从没被判成真人，没有对照",
                "note": "「谁是真人」对局不足（见报告）"}
    score = min(1.0, out["resident_pass_rate"] / out["human_rate"])
    return {**out, "status": "ok", "score": round(score, 4), "pass": score >= D_PASS}


# ── Scorecard ────────────────────────────────────────────────────────────────
#: Where a fixture scorecard goes. Kept apart from the headline card so that a
#: pipeline check can never be read as a simulation result (it once was: the
#: 2026-09-25 headline "OK / 0.9361" was the --synthetic fixture).
SYNTHETIC_DIR = RESULTS_DIR / "synthetic"


def _git_info() -> dict:
    """{commit, dirty} of the repo the scored outputs came from (best effort)."""
    def run(*args):
        try:
            # --no-optional-locks: a read must never leave .git/index.lock
            # behind (it did, from a sandbox that cannot unlink).
            p = subprocess.run(["git", "--no-optional-locks", *args], cwd=str(PROJECT_ROOT),
                               capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return p.stdout.strip() if p.returncode == 0 else None
    commit = run("rev-parse", "HEAD")
    if not commit:
        return {}
    return {"commit": commit, "dirty": bool(run("status", "--porcelain"))}


def _repo_relative(value):
    """Paths inside the repo are recorded relative to it, so a card reads the
    same on the machine that wrote it and the one that opens it."""
    if not isinstance(value, Path):
        return value
    try:
        return str(value.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(value)


def build_provenance(*, synthetic: bool, inputs: dict) -> dict:
    """Where the scored numbers came from. ``source`` decides the trust gate."""
    return {
        "source": "synthetic" if synthetic else "real",
        "inputs": {k: _repo_relative(v) for k, v in inputs.items() if v is not None},
        "git": _git_info(),
        "argv": sys.argv[1:],
    }


def build_scorecard(tracks: dict, provenance: dict | None = None) -> dict:
    implemented = {k: v for k, v in tracks.items()
                   if isinstance(v, dict) and v.get("status") == "ok"}
    composite = (statistics.fmean([v["score"] for v in implemented.values()])
                 if implemented else None)
    # trust gate (A4, tri-state): determinism failure poisons the card;
    # never-tested determinism is UNVERIFIED, not a free OK.
    det_status = tracks.get("C", {}).get("det_status")  # ok / fail / unassessed / None
    trust = {"fail": "UNTRUSTWORTHY", "ok": "OK"}.get(det_status, "UNVERIFIED")
    reasons = {"fail": ["确定性失败：同种子两次运行结果不一致"],
               "ok": []}.get(det_status, ["确定性未测（未提供 --det-a/--det-b）"])
    # Comparisons produced by older code measure that code, not this one; a
    # card mixing them describes no single version of the model.
    epochs = tracks.get("C", {}).get("epochs") or {}
    stale = sorted(name for name, epoch in epochs.items() if epoch != CURRENT_EPOCH)
    if stale:
        reasons.append(f"{len(stale)}/{len(epochs)} 个对照不是当前代码版本（版本 {CURRENT_EPOCH}）产生的："
                       + "、".join(f"{n}={epochs[n] if epochs[n] is not None else '未标'}" for n in stale)
                       + " → 用 --run 重跑")
        if trust == "OK":
            trust = "UNVERIFIED"
    provenance = provenance or {"source": "unspecified"}
    if provenance.get("source") == "synthetic":
        # Fixtures exercise the scoring code, not the simulator. Their numbers
        # are chosen to pass, so no gate value may suggest they are evidence.
        trust = "FIXTURE"
        reasons = ["合成夹具：只验证评测代码路径"]
    passed = [k for k, v in implemented.items() if v.get("pass")]
    headline = (min(passed, key=lambda k: implemented[k]["score"])
                if passed else None)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "trust_gate": trust,
        "trust_reasons": reasons,
        "provenance": provenance,
        "fast": bool(tracks.get("C", {}).get("fast", False)),  # low-fidelity (--fast) run?
        "composite_hint": round(composite, 4) if composite is not None else None,
        "headline_track": headline,
        "tracks": tracks,
        "note": "composite is a trend hint only — read tracks separately (design §3).",
    }


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def render_scorecard_md(sc: dict) -> str:
    L = ["# GAWorld-Bench Scorecard", "",
         f"- generated: {sc['generated']}",
         f"- **trust gate: {sc['trust_gate']}**"
         + (f"（{'；'.join(sc['trust_reasons'])}）" if sc.get("trust_reasons") else ""),
         f"- composite hint: {sc['composite_hint']}  _(trend only, 弱证据)_",
         f"- headline (weakest passing track): {sc['headline_track']}"]
    prov = sc.get("provenance") or {}
    git = prov.get("git") or {}
    L.append(f"- 数据来源: `{prov.get('source', 'unspecified')}`"
             + (f" · git `{git['commit'][:8]}`{'（有未提交改动）' if git.get('dirty') else ''}"
                if git.get("commit") else ""))
    if sc["trust_gate"] == "FIXTURE":
        L.insert(2, "> ⚠️ **合成夹具（--synthetic）**：数字是为让每条检查都通过而预设的，"
                    "只证明评测代码能跑通，**不是 GAWorld 仿真结果**，不得引用。")
        L.insert(3, "")
    if sc.get("fast"):
        L.append("- ⚡ **低保真运行（--fast）**：确定性认知 + 跳过每日总结/日记 + 3 agent；"
                 "结论仅供快速定向，勿当全保真结果。")
    L += ["", "| Track | 命题 | score | pass |", "|---|---|---|---|"]
    names = {"A": "宏观经验拟合", "B": "Stylized-facts（对局层）", "C": "因果反事实 ⭐",
             "D": "可信度一致性", "E": "可复现/成本"}
    for k in ("A", "B", "C", "D", "E"):
        t = sc["tracks"].get(k, {})
        if t.get("status") == "ok":
            L.append(f"| {k} | {names[k]} | {t.get('score')} | "
                     f"{'PASS' if t.get('pass') else 'FAIL'} |")
        else:
            L.append(f"| {k} | {names[k]} | n/a | {t.get('note', '未实现')} |")
    c = sc["tracks"].get("C", {})
    if c.get("status") == "ok":  # coverage transparency: a 1.0 from 1/4 tests is not full validation
        sign = c.get("sign", {})
        plc = c.get("placebo", {}).get("score")
        det_status = c.get("determinism", {}).get("status", "未评估")
        if c.get("mode") == "multiseed":  # A2: significant-only sign + significance coverage
            if c.get("insufficient_seeds"):
                head = (f"- Track C[多seed]: ⚠️ 样本不足——每项最多 {c.get('max_samples')} 个，"
                        f"显著性需 ≥2 个 seed（数据覆盖 {c.get('coverage')}）。用 --seeds a,b,c 重跑")
            else:
                head = (f"- Track C[多seed]: 符号 {sign.get('n_correct')}/{sign.get('n_significant')} 显著且正确"
                        f"（显著覆盖 {c.get('significance_coverage')}，数据覆盖 {c.get('coverage')}，95%CI）")
        else:
            head = (f"- Track C: 符号 {sign.get('n_correct')}/{sign.get('n_eval')} 正确"
                    f"（覆盖 {c.get('coverage')}，按 `{sign.get('effect_col')}` 事件后效应）")
        L += ["", head + f" · 安慰剂 {'未评估' if plc is None else plc} · 确定性 {det_status}"]
        if c.get("incomplete"):
            L.append(f"- ⚠️ 运行未完成（缺 comparison_metrics.csv）: {', '.join(c['incomplete'])}")
    b = sc["tracks"].get("B", {})
    if b.get("facts"):
        rest = len(b["facts"]) - b["n_assessed"]
        L.append(f"- Track B[对局层]: 复现 {b['n_reproduced']}/{b['n_assessed']} 条可评"
                 + (f"（另 {rest} 条弃权）" if rest else "") + " · 对局 "
                 + " / ".join(f"{k} {n}" for k, n in b["games"].items())
                 + (f" · ⚠️ 混合 {len(b['providers'])} 个模型" if len(b.get("providers") or {}) > 1 else ""))
    d = sc["tracks"].get("D", {})
    if d.get("level") == "human_judges":
        L.append(f"- Track D[人类判别]: 居民被判为真人 {_pct(d.get('resident_pass_rate'))}"
                 f"（{d.get('resident_judgments', 0)} 次判断）· 真人被判为真人 {_pct(d.get('human_rate'))}"
                 f"（{d.get('human_judgments', 0)} 次）· 对局 {d.get('rooms', 0)}"
                 + (f" · ⚠️ 混合 {len(d['providers'])} 个模型" if len(d.get("providers") or {}) > 1 else ""))
    # MECHANISM_PROVENANCE rule 3: every cited metric with its weakest dependency.
    sourced = []
    a = sc["tracks"].get("A", {})
    if a.get("status") == "ok":
        for key, m in sorted((a.get("metrics") or {}).items()):
            if m.get("grade"):
                sourced.append(f"- `{key}` ({m['grade']})：{m.get('weakest', '')}"
                               + (f" ⚠️ **回显**：{m['echo']}" if m.get("echo") else ""))
    if c.get("status") == "ok" and c.get("provenance"):
        sourced.append(f"- Track C 各项（{'、'.join(sorted({t['metric'] for t in c.get('sign', {}).get('tests', [])}))}）"
                       f" ({c['provenance']['grade']})：{c['provenance']['weakest']}")
    if b.get("status") == "ok":
        sourced.append("- Track B 各条 (c)：模型扮演居民对一段提示词的一步回应，提示词里各有线索（见报告）；"
                       "不是 agent→环境→agent 回路的涌现")
    if sourced:
        L += ["", "**指标来源**（最弱一级依赖，定义见 MECHANISM_PROVENANCE.md；(c) 不得单独立论）", *sourced]
    return "\n".join(L) + "\n"


def _results_dir_for(sc: dict) -> Path:
    return SYNTHETIC_DIR if sc.get("trust_gate") == "FIXTURE" else RESULTS_DIR


def save_scorecard(sc: dict) -> None:
    out = _results_dir_for(sc)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(
        json.dumps(sc, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "scorecard.md").write_text(
        render_scorecard_md(sc), encoding="utf-8")
    print(f"[bench] wrote {out/'scorecard.json'}")
    print(f"[bench] wrote {out/'scorecard.md'}")


# ── Report + data-driven improvement suggestions ─────────────────────────────
def _report_track_a(t: dict) -> tuple[list[str], list[str]]:
    """Returns (diagnosis lines, recommendations) for Track A from its numbers."""
    lines, recs = [], []
    n = t.get("n_samples")
    if n:
        lines.append(f"样本：{n} 个 agent 快照。")
    ctx = t.get("context_metrics", {})
    if ctx:
        lines.append(
            f"口径不符、仅作参考（仿真口径：{t.get('sim_scope', '?')}）："
            + "、".join(
                f"`{k}` sim {m['sim']} vs {m['anchor']}（{m['scope']}）"
                for k, m in sorted(ctx.items())
            ) + "。这些数字不参与打分——拿片区去比全市，量的是口径差不是模型误差。")
    metrics = t.get("metrics", {})
    worst = None
    for key, m in sorted(metrics.items(), key=lambda kv: kv[1]["score"]):
        mark = "✓" if m["score"] >= 0.8 else "✗"
        lines.append(f"- `{key}`: sim {m['sim']} vs 锚点 {m['anchor']} "
                     f"(误差 {m['rel_err'] * 100:.1f}%) {mark}  _{m['source']}_"
                     + (f"（计算范围：{m['population']}）" if m.get("population") else "")
                     + (f" · 来源 ({m['grade']})" if m.get("grade") else "")
                     + (" · ⚠️ 回显" if m.get("echo") else ""))
        if worst is None or m["score"] < worst[1]["score"]:
            worst = (key, m)
    if worst and worst[1]["score"] < 0.8:
        k, m = worst
        tip = ("明确口径：『住户存款/收入』口径偏高(~43%)，『可支配收入流量储蓄』口径约30-35%"
               if k == "savings_rate" else "核对该指标的仿真计算与聚合方式")
        recs.append(f"主要拖累项 `{k}`（误差 {m['rel_err'] * 100:.1f}%）：{tip}，再校准锚点/容差。")
    if n is not None and n < 10:
        recs.append(f"样本仅 {n} 个，统计不稳；增大 agent 数或延长仿真天数后再评估宏观拟合。")
    echoes = sorted(k for k, m in metrics.items() if m.get("echo"))
    if echoes:
        recs.append(f"{'、'.join(f'`{k}`' for k in echoes)} 是输入回显：快照里记的是按收入查 engel_curve 的预算参数。"
                    "改从实际分类消费（食品支出 / 总消费、1 − 支出 / 收入）计算之前，这几项拟合得再好也不是模型证据。")
    recs.append("提醒：Track A 属弱证据（验证的是写进模型的参数）。Track C 的指标同为 (c) 级——"
                "事件影响由模型判断给出，见「指标来源」。")
    return lines, recs


def _report_track_c_multiseed(t: dict) -> tuple[list[str], list[str]]:
    lines, recs = [], []
    sign = t.get("sign", {})
    if t.get("insufficient_seeds"):
        lines.append(f"⚠️ 样本不足：每项最多 {t.get('max_samples')} 个样本，无法评估显著性（需 ≥2 个 seed）。")
        lines.append("（数据已产出，说明 provider 正常；这不是模型失败，只是 seed 太少。）")
        recs.append("用 ≥2（建议 ≥3）个 seed 重跑：`--seeds 1,2,3 [--continue]`，才能算 95%CI 与显著性。")
        return lines, recs
    lines.append(f"符号 {sign.get('n_correct')}/{sign.get('n_significant')} 显著且正确"
                 f"（显著覆盖 {t.get('significance_coverage')}，数据覆盖 {t.get('coverage')}，95%CI）。")
    lines += _provenance_lines(t)
    ns = []
    for r in sign.get("tests", []):
        if r["n"] == 0:
            lines.append(f"- `{r['name']}/{r['metric']}`: 无数据（未评估）")
            continue
        ci = "" if r["ci95"] is None else f"±{r['ci95']:.4f}"
        if not r["significant"]:
            tag = "ns(不显著)"
            ns.append(r)
        else:
            tag = "✓" if r["correct"] else "✗"
        arrow = "↑" if r["sign"] > 0 else "↓"
        lines.append(f"- `{r['name']}/{r['metric']}`: Δ={r['mean']:+.4f}{ci} (n={r['n']}) 期望{arrow} {tag}")
    if ns:
        recs.append(f"{len(ns)} 项不显著（95%CI 含 0）：增加 seed 数或确认效应是否真实，"
                    "不要据不显著结果下因果结论。")
    wrong = [r for r in sign.get("tests", []) if r["significant"] and not r["correct"]]
    if wrong:
        recs.append("有显著但方向相反的项 → 检查该干预的事件→指标因果接线。")
    if t.get("significance_coverage", 0) < 0.5:
        recs.append("显著项不足一半：单 seed 噪声大，增加 seed 或延长仿真。")
    _track_c_common_recs(t, recs)
    return lines, recs


def _provenance_lines(t: dict) -> list[str]:
    prov = t.get("provenance") or {}
    return [f"指标来源 ({prov['grade']})：{prov['weakest']}。"] if prov.get("grade") else []


def _track_c_common_recs(t: dict, recs: list[str]) -> None:
    if t.get("incomplete"):
        recs.append(f"补跑未完成的对照（{', '.join(t['incomplete'])}）。")
    plc = t.get("placebo", {}).get("score")
    if plc is None:
        recs.append("安慰剂未评估：补一个能跑完的空事件对照。")
    elif plc < 0.8:
        recs.append(f"安慰剂泄漏（{plc}）：空事件也产生效应 → 排查与事件无关的漂移/噪声。")
    det = t.get("determinism", {}).get("status")
    if det == "unassessed":
        recs.append("确定性未评估：提供两份同 seed baseline（`--det-a/--det-b`）。")
    elif det == "fail":
        recs.append("⚠️ 非确定！先修随机源，否则整套结果不可信。")


def _report_track_c(t: dict) -> tuple[list[str], list[str]]:
    if t.get("mode") == "multiseed":
        return _report_track_c_multiseed(t)
    lines, recs = [], []
    sign = t.get("sign", {})
    lines.append(f"符号 {sign.get('n_correct')}/{sign.get('n_eval')} 正确"
                 f"（覆盖 {t.get('coverage')}，按 `{sign.get('effect_col')}` 事件后效应）。")
    lines += _provenance_lines(t)
    failed = []
    for r in sign.get("tests", []):
        if r["delta"] is None:
            lines.append(f"- `{r['name']}/{r['metric']}`: 无对应运行（未评估）")
        else:
            mark = "✓" if r["correct"] else "✗"
            arrow = "↑" if r["sign"] > 0 else "↓"
            ref = "" if r["delta_mean"] is None else f"（delta_mean {r['delta_mean']:+.4f}）"
            lines.append(f"- `{r['name']}/{r['metric']}`: Δ={r['delta']:+.4f} 期望{arrow} {mark}{ref}")
            if not r["correct"]:
                failed.append(r)
    if t.get("incomplete"):
        lines.append(f"- ⚠️ 运行未完成: {', '.join(t['incomplete'])}")
        recs.append(f"补跑未完成的对照（{', '.join(t['incomplete'])}）：重跑 compare-event "
                    "直到生成 comparison_metrics.csv。")
    if failed:
        mx = max(abs(r["delta"]) for r in failed)
        if mx < PLACEBO_EPS:
            recs.append(f"失败项效应量极小（|Δ|≤{mx:.3f}，与安慰剂同量级）→ 符号由噪声主导，"
                        "不是『方向反了』。经济类干预改用 ≥30 天仿真，并加显著性检验（跨 seed/agent）。")
        else:
            recs.append(f"失败项效应明显（|Δ|max={mx:.3f}）却方向相反 → 检查事件→指标因果接线是否接反"
                        "（如裁员事件是否真正触发 economy 的收入冲击，而非仅注入感知文本）。")
    if sign.get("n_eval", 0) < len(SIGN_TESTS):
        recs.append(f"符号覆盖不足（{sign.get('n_eval')}/{len(SIGN_TESTS)}）：用 `--run` 补跑缺失干预。")
    plc = t.get("placebo", {}).get("score")
    if plc is None:
        recs.append("安慰剂未评估：补一个空事件 compare-event 运行（确保生成 comparison_metrics.csv）。")
    elif plc < 0.8:
        recs.append(f"安慰剂泄漏（{plc}）：空事件也产生效应 → 排查与事件无关的漂移/随机噪声。")
    det = t.get("determinism", {}).get("score")
    if det is None:
        recs.append("确定性未评估：提供两份同 seed baseline（`--det-a/--det-b`）验证可复现性。")
    elif det < 1.0:
        recs.append(f"⚠️ 非确定（{det}）！先修随机源，否则整套结果不可信。")
    return lines, recs


def _fact_detail(f: dict) -> str:
    v = f.get("values") or {}
    if f["id"] == "referendum_conformity":
        return f"朝多数 {v.get('toward')} / 背离 {v.get('away')}" + ("" if v.get("p") is None else f"，p={v['p']:.3g}")
    if f["id"] == "disaster_panic_rare":
        if v.get("extreme_share") is None:
            return "无反应"
        return f"极度恐慌 {v['extreme_share']:.0%}，互助 {v['help_rate']:.0%}（{f['units']} 条反应）"
    if v.get("before") is None:
        return "无被辟谣的相信者"
    return (f"{f['units']} 人：下降 {v.get('down')} / 上升 {v.get('up')}"
            + ("" if v.get("p") is None else f"，p={v['p']:.3g}")
            + f"；平均相信 {v['before']}% → {v['after']}%（残留 {v['residual']:.0%}）")


def _report_track_b(t: dict) -> tuple[list[str], list[str]]:
    lines, recs = [], []
    lines.append("对局：" + " / ".join(f"{k} {n}" for k, n in t["games"].items())
                 + f"（`{t['games_dir']}`）"
                 + (f"；{t['unreadable']} 个文件读不了" if t.get("unreadable") else ""))
    lines.append("层级：居民看到众人的表态 / 邻居的行动 / 一次辟谣后，对一段提示词的一步回应——"
                 "不是 agent→环境→agent 回路的涌现（那一类见 `trackb_spatial.py`）。各条都是 (c) 级，只读定性结论。")
    providers = t.get("providers") or {}
    if len(providers) > 1:
        lines.append("⚠️ 混合了 " + "、".join(f"{k} {n} 局" for k, n in providers.items())
                     + "：合并检验把不同模型当成一个总体。")
        recs.append("对局来自多个模型：按模型分开存档目录（`--games-dir`）各评一次，再比较。")
    for f in t["facts"]:
        mark = {True: "✓ 复现", False: "✗ 未复现", None: "○ 弃权"}[f["reproduced"]]
        why = f"（{f['abstain']}）" if f["abstain"] else f"：{_fact_detail(f)}"
        lines.append(f"- `{f['id']}` {f['name']} — {mark}{why}")
        lines.append(f"  - 判据：{f['criterion']}。参照：{f['reference']}")
        lines.append(f"  - 提示词线索：{f['cue']}")
        if f["reproduced"] is None:
            extra = f"，{f['advice']}" if f.get("advice") else ""
            recs.append(f"`{f['id']}` 弃权（{f['abstain']}）→ 在游乐场多玩几局 {f['kind']}{extra}。")
        elif not f["reproduced"]:
            recs.append(f"`{f['id']}` 未复现（{_fact_detail(f)}）→ 先看上面的提示词线索是否在起作用；"
                        "不要为了凑出规律去改提示词。")
    return lines, recs


def _report_track_d(t: dict) -> tuple[list[str], list[str]]:
    lines, recs = [], []
    lines.append(f"「谁是真人」对局 {t['rooms']} 局（`{t['games_dir']}/whois`）"
                 + (f"；{t['unreadable']} 个文件读不了" if t.get("unreadable") else ""))

    def ci(pair):
        return "" if not pair else f"，95% 区间 {pair[0]:.0%}–{pair[1]:.0%}"

    lines.append(f"- 居民被判为真人：{t['resident_judged_human']}/{t['resident_judgments']}"
                 f"（{_pct(t.get('resident_pass_rate'))}{ci(t.get('resident_ci'))}）")
    lines.append(f"- 真人被判为真人：{t['human_judged_human']}/{t['human_judgments']}"
                 f"（{_pct(t.get('human_rate'))}{ci(t.get('human_ci'))}）")
    if t.get("accuracy") is not None:
        lines.append(f"- 判断准确率 {_pct(t['accuracy'])}（50% 上下就是分不出来）")
    if t.get("status") == "ok":
        lines.append(f"- score_D = min(1, 居民 ÷ 真人) = {t['score']}（≥ {D_PASS} 算通过）")
    else:
        lines.append(f"- 弃权：{t.get('abstain')}")
        recs.append(f"「谁是真人」样本不足（{t.get('abstain')}）→ 在游戏场多开几局，每局至少两个真人座位"
                    "（只有一个真人时没人判断真人，没有对照）。")
    lines.append("- 线索：居民被要求短句、口语，且不知道有人在猜；评委是同桌玩家；一位评委投多张票，区间偏乐观。"
                 "设计里 Track D 的四个 LLM 评审维度未实现，这是另加的人类判别维度。")
    providers = t.get("providers") or {}
    if len(providers) > 1:
        lines.append("⚠️ 混合了 " + "、".join(f"{k} {n} 局" for k, n in providers.items()) + "。")
        recs.append("对局来自多个模型：按模型分开存档目录各评一次。")
    if t.get("status") == "ok" and not t.get("pass"):
        recs.append("居民比真人更容易被认出来 → 先读几局的对话找出破绽（太长、太完整、没有自己的生活细节），"
                    "再决定改人设还是改提示词；改提示词换来的分数要另起一批对局评。")
    return lines, recs


def generate_report(sc: dict) -> str:
    tr = sc["tracks"]
    overview = "\n".join(render_scorecard_md(sc).splitlines()[1:])  # reuse table, drop H1
    L = ["# GAWorld-Bench 运行报告", "",
         "## 结果概览", overview, "",
         "## 分项诊断与建议", ""]
    next_steps: list[str] = []
    gate_step = {
        "FIXTURE": "【信任门槛】这是合成夹具，只验证评测代码路径 → 要评测模型请去掉 --synthetic 重跑。",
        "UNTRUSTWORTHY": "【信任门槛】确定性失败 → 先修随机源，结果暂不可信。",
        "UNVERIFIED": "【信任门槛】" + "；".join(sc.get("trust_reasons") or ["未验证"]) + " → 补齐之前结论只算未验证。",
    }.get(sc["trust_gate"])
    if gate_step:
        next_steps.append(gate_step)

    names = {"A": "宏观经验拟合", "B": "Stylized-facts（对局层）", "C": "因果反事实 ⭐", "D": "可信度（人类判别）"}
    builders = {"A": _report_track_a, "B": _report_track_b, "C": _report_track_c, "D": _report_track_d}
    for k in ("C", "B", "D", "A"):  # core track first
        t = tr.get(k, {})
        # B and D report their abstentions too
        if t.get("status") != "ok" and not t.get("facts") and t.get("level") != "human_judges":
            continue
        if t.get("status") == "ok":
            verdict = f"{t.get('score')} {'PASS' if t.get('pass') else 'FAIL'}"
        else:
            verdict = "未评估"
        diag, recs = builders[k](t)
        L += [f"### Track {k} — {names[k]} — {verdict}", *diag, ""]
        if recs:
            L += ["建议：", *[f"{i}. {r}" for i, r in enumerate(recs, 1)], ""]
        next_steps += [f"【Track {k}】{r}" for r in recs]

    na = [k for k in ("B", "D", "E") if tr.get(k, {}).get("status") != "ok"
          and not tr.get(k, {}).get("facts") and tr.get(k, {}).get("level") != "human_judges"]
    if na:
        L += [f"### 未评估：Track {', '.join(na)}",
              "这些有效性维度尚未评估，当前结论存在盲区（见设计文档路线图 §7）。", ""]

    L += ["## 下一步（按优先级）", ""]
    L += [f"{i}. {s}" for i, s in enumerate(next_steps, 1)] or ["- 暂无（所有已实现 track 通过）。"]
    return "\n".join(L) + "\n"


def save_report(sc: dict) -> None:
    out = _results_dir_for(sc)
    out.mkdir(parents=True, exist_ok=True)
    md = generate_report(sc)
    (out / "report.md").write_text(md, encoding="utf-8")
    archive = out / "reports"
    archive.mkdir(exist_ok=True)
    ts = sc["generated"].replace(":", "").replace("-", "")
    (archive / f"report_{ts}.md").write_text(md, encoding="utf-8")
    print(f"[bench] wrote {out/'report.md'} (+ archive copy)")


# ── Synthetic fixtures (verification / no-LLM trial) ─────────────────────────
def make_synthetic(root: Path) -> dict:
    """Fabricate structurally-correct outputs so the pipeline runs end-to-end."""
    econ = root / "output" / "economy"; econ.mkdir(parents=True, exist_ok=True)
    # wealth_snapshot near the anchors (engel~0.29, savings~0.33) -> Track A high
    with open(econ / "wealth_snapshot.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["agent_id", "engel_coefficient", "savings_rate"])
        for i, (e, s) in enumerate([(0.31, 0.30), (0.27, 0.36), (0.30, 0.33),
                                    (0.29, 0.31), (0.28, 0.34)], 1):
            w.writerow([i, e, s])

    comps = root / "output" / "comparisons"
    # one correct-sign comparison per intervention
    fixtures = {
        "traffic_restriction": [("mobility_intent", +0.08), ("stress", +0.01)],
        "layoff_shock":        [("econ_security", -0.12), ("stress", +0.09)],
        "tax_cut":             [("econ_security", +0.06), ("mobility_intent", 0.0)],
    }
    for name, deltas in fixtures.items():
        d = comps / name; d.mkdir(parents=True, exist_ok=True)
        _write_metrics(d / "comparison_metrics.csv", deltas)
    # placebo: all deltas tiny
    placebo = comps / "placebo_library_hours"; placebo.mkdir(parents=True, exist_ok=True)
    _write_metrics(placebo / "comparison_metrics.csv",
                   [("emotion", 0.004), ("stress", -0.011), ("econ_security", 0.002),
                    ("mobility_intent", 0.008)])
    # determinism: two identical baseline state files
    st = root / "output" / "state"; st.mkdir(parents=True, exist_ok=True)
    rows = [("1", "0", "emotion", "0.50"), ("1", "1", "emotion", "0.52"),
            ("2", "0", "stress", "0.40"), ("2", "1", "stress", "0.41")]
    for fn in ("baseline_run_a.csv", "baseline_run_b.csv"):
        with open(st / fn, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["agent_id", "step", "metric", "value"])
            w.writerows(rows)
    games = make_synthetic_games(root / "output" / "games")
    return {"output_dir": root / "output", "games_dir": games,
            "sign_sources": {k: comps / k for k in fixtures},
            "placebo_dir": placebo, "det_a": st / "baseline_run_a.csv",
            "det_b": st / "baseline_run_b.csv"}


def make_synthetic_games(games_dir: Path) -> Path:
    """Five archived games per kind, shaped like the real archive, chosen to
    reproduce all three Track B facts and pass Track D."""
    def vote(stance):
        return {"stance": stance, "strength": 60, "say": ""}

    def game(kind, i, result):
        folder = games_dir / kind
        folder.mkdir(parents=True, exist_ok=True)
        record = {"kind": kind, "job_id": f"{kind}-{i:08x}", "provider": "synthetic", "result": result}
        (folder / f"20261003-00000{i}-{kind}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")

    private = ["支持", "支持", "支持", "反对", "反对", "弃权"]
    public = ["支持", "支持", "支持", "支持", "反对", "支持"]  # two moves toward the majority
    for i in range(MIN_GAMES):
        game("referendum", i, {"campaign": "", "voters": [
            {"agent_id": n, "private": vote(a), "public": vote(b)}
            for n, (a, b) in enumerate(zip(private, public, strict=True), 1)]})
        game("disaster", i, {"agents": [
            {"agent_id": 1, "reactions": [{"action": "打探消息", "panic": 3, "help": True},
                                          {"action": "救助他人", "panic": 2, "help": True}]},
            {"agent_id": 2, "reactions": [{"action": "囤积物资", "panic": 4, "help": False},
                                          {"action": "照常生活", "panic": 3, "help": True}]}]})
        game("rumor", i, {"nodes": [
            {"agent_id": 1, "beliefs": [80, 40]},
            {"agent_id": 2, "beliefs": [90, 30]},
            {"agent_id": 3, "beliefs": [20]}]})
        # Two people, three residents; each person marks the other four.
        game("whois", i, {"results": {
            "resident_judged_human": 5, "resident_judgments": 6,
            "human_judged_human": 2, "human_judgments": 2,
            "judges": [{"alias": "1号", "correct": 3, "total": 4}, {"alias": "4号", "correct": 2, "total": 4}]}})
    return games_dir


def make_synthetic_multiseed() -> dict[tuple[str, str], list[float]]:
    """Fabricate per-(intervention,metric) delta_final samples across 5 seeds.

    3 of 4 tests are tight + significant + correct; tax/econ_security straddles 0
    (non-significant) to exercise the 'ns' path.
    """
    return {
        ("traffic_restriction", "mobility_intent"): [0.30, 0.32, 0.34, 0.31, 0.33],
        ("layoff_shock", "econ_security"): [-0.05, -0.06, -0.04, -0.055, -0.045],
        ("layoff_shock", "stress"): [0.17, 0.16, 0.18, 0.15, 0.19],
        ("tax_cut", "econ_security"): [0.02, -0.01, 0.03, -0.02, 0.01],  # ns
    }


def _write_metrics(path: Path, deltas: list[tuple[str, float]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "baseline_final", "event_final", "delta_final",
                    "baseline_mean", "event_mean", "delta_mean"])
        for m, d in deltas:  # synthetic: delta_final == delta_mean == d
            w.writerow([m, 0.5, 0.5 + d, d, 0.5, 0.5 + d, d])


# ── CLI ──────────────────────────────────────────────────────────────────────
def _default_output_dir() -> Path:
    """The run root a fresh simulator process would write to: ``output/``, or
    ``output/cities/<slug>/`` once a city is selected. Plain ``output/`` is
    stale after a city switch (and is where the test suite used to write)."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from gaworld.settings import CONFIG
        root = CONFIG.get("run_output_dir") or "output"
    except Exception as exc:  # fall back rather than refuse to score
        print(f"[bench] WARN: could not read the simulator config ({exc}); scoring output/")
        root = "output"
    return PROJECT_ROOT / root


def main() -> int:
    p = argparse.ArgumentParser(description="GAWorld-Bench harness (v0.1)")
    p.add_argument("--track", choices=["A", "B", "C", "D"], help="run a single track")
    p.add_argument("--all", action="store_true", help="run all implemented tracks")
    p.add_argument("--synthetic", action="store_true",
                   help="fabricate fixtures and run without LLM/sim")
    p.add_argument("--output-dir", type=Path, help="sim output dir (Track A)")
    p.add_argument("--games-dir", type=Path,
                   help="Track B: archived playground games (default: output/games)")
    p.add_argument("--comparisons-root", type=Path, help="Track C: read existing comparisons dir")
    p.add_argument("--placebo-dir", type=Path, help="Track C: placebo comparison dir")
    p.add_argument("--det-a", type=Path, help="Track C: baseline state file A")
    p.add_argument("--det-b", type=Path, help="Track C: baseline state file B")
    p.add_argument("--run", action="store_true",
                   help="Track C: live-run compare-event (needs an LLM provider)")
    p.add_argument("--days", type=int, default=3, help="sim days for live --run")
    p.add_argument("--seed", type=int, default=42, help="random seed for live --run")
    p.add_argument("--seeds", help="A2 multi-seed significance mode: comma list, e.g. 1,2,3,4,5")
    p.add_argument("--continue", dest="resume", action="store_true",
                   help="resume a multi-seed --run from its saved checkpoint (after a quota/API failure)")
    p.add_argument("--fast", action="store_true",
                   help="fast mode for --run: fewer LLM calls + 3-agent cohort (for local models; lower fidelity)")
    p.add_argument("--llm-provider", help="provider passed to compare-event (e.g. minimax)")
    args = p.parse_args()
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()] if args.seeds else None

    syn_sign_sources = None
    if args.synthetic:
        fx = make_synthetic(Path(tempfile.mkdtemp(prefix="gaworld_bench_")))
        args.output_dir = args.output_dir or fx["output_dir"]
        args.games_dir = args.games_dir or fx["games_dir"]
        syn_sign_sources = fx["sign_sources"]
        args.placebo_dir = args.placebo_dir or fx["placebo_dir"]
        args.det_a = args.det_a or fx["det_a"]
        args.det_b = args.det_b or fx["det_b"]

    run_a = args.all or args.track == "A"
    run_b = args.all or args.track == "B"
    run_c = args.all or args.track == "C"
    run_d = args.all or args.track == "D"
    if not (run_a or run_b or run_c or run_d):
        run_a = run_b = run_c = run_d = True  # default: everything implemented

    tracks: dict = {}
    if run_a:
        out_dir = args.output_dir or _default_output_dir()
        tracks["A"] = track_a_macro_fit(out_dir)
    games_dir = args.games_dir or GAMES_DIR
    if run_b:
        tracks["B"] = track_b_games(games_dir)
    if run_d:
        tracks["D"] = track_d_whois(games_dir)
    if run_c:
        if seeds is not None:  # A2 multi-seed significance mode
            if args.synthetic:
                tracks["C"] = track_c_multiseed(make_synthetic_multiseed(),
                                                args.placebo_dir, args.det_a, args.det_b)
            elif args.run or args.resume:
                tracks["C"] = orchestrate_track_c_multiseed(
                    seeds, args.days, args.llm_provider, args.det_a, args.det_b,
                    resume=args.resume, fast=args.fast)
            else:
                tracks["C"] = {"track": "C", "status": "n/a",
                               "note": "--seeds 多seed模式需配 --run（实跑，需 provider）或 --synthetic"}
        elif syn_sign_sources is not None:
            tracks["C"] = track_c_causal(syn_sign_sources, args.placebo_dir,
                                         args.det_a, args.det_b)
        elif args.run:
            tracks["C"] = orchestrate_track_c(args.days, args.seed, args.llm_provider,
                                              args.det_a, args.det_b, fast=args.fast)
        else:
            root = args.comparisons_root or COMPARISONS_OUT  # default: scan output/comparisons
            ss, auto_placebo, incomplete = resolve_from_comparisons(root)
            placebo = args.placebo_dir or auto_placebo
            if not ss and placebo is None and not incomplete:
                tracks["C"] = {"track": "C", "status": "n/a",
                               "note": f"在 {root} 未找到可匹配的 comparison 运行; "
                                       "用 --run 实跑或先生成 compare-event 结果"}
            else:
                tracks["C"] = track_c_causal(ss, placebo, args.det_a, args.det_b,
                                             incomplete=incomplete)
    tracks.setdefault("B", {"status": "n/a", "note": "未运行（--track B）"})
    tracks.setdefault("D", {"status": "n/a", "note": "未运行（--track D）"})
    tracks.setdefault("E", {"status": "n/a", "note": "确定性见 Track C; 成本未实现 (v0.2)"})

    provenance = build_provenance(synthetic=args.synthetic, inputs={
        "output_dir": out_dir if run_a else None,
        "games_dir": games_dir if (run_b or run_d) else None,
        "comparisons_root": (args.comparisons_root or COMPARISONS_OUT)
        if run_c and not (args.synthetic or args.run or args.resume) else None,
        "placebo_dir": args.placebo_dir, "det_a": args.det_a, "det_b": args.det_b,
        "live_run": bool(args.run or args.resume) or None,
    })
    sc = build_scorecard(tracks, provenance)
    save_scorecard(sc)
    save_report(sc)  # every run emits a report with improvement suggestions
    print("\n" + render_scorecard_md(sc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
