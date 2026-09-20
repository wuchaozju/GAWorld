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

Track B / D / E are stubbed (return n/a) and left for v0.2+.

Usage (run from the repo-root benchmark/ folder):
    python gaworld_bench.py --synthetic
    python gaworld_bench.py --all                      # default: score real output/
    python gaworld_bench.py --track A --output-dir ../output
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
ANCHORS = {
    "engel_coefficient": {"value": 0.288, "tol": 0.15,
                          "source": "国家统计局2024公报 (城镇28.8%)"},
    "savings_rate":      {"value": 0.35, "tol": 0.30,
                          "source": "2024 口径敏感, 区间30-43%"},
    "commute_minutes":   {"value": 34.5, "tol": 0.25,
                          "source": "2024中国主要城市通勤监测报告 (杭州)"},
    "transit_share":     {"value": 0.476, "tol": 0.25,
                          "source": "杭州市交通运输局2024"},
    "wealth_gini":       {"value": 0.70, "tol": 0.30,
                          "source": "CHFS/瑞信财富报告: 中国家庭财富Gini≈0.6-0.75"},
}

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
        net_worth = []
        for r in rows:
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
    for key, sim in metrics.items():
        a = ANCHORS[key]
        rel_err = abs(sim - a["value"]) / a["value"]
        s = clamp01(1 - rel_err / a["tol"])
        scored[key] = {"sim": round(sim, 4), "anchor": a["value"],
                       "rel_err": round(rel_err, 4), "score": round(s, 4),
                       "source": a["source"]}

    if not scored:
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
    score = statistics.fmean(s_vals)
    passed = score >= 0.6 and all(s > 0 for s in s_vals)
    if conservation is not None:
        passed = passed and conservation["pass"]
    result = {"track": "A", "status": "ok", "score": round(score, 4),
              "pass": passed, "metrics": scored, "n_samples": n_samples}
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
                             "delta": delta,
                             "delta_final": eff["delta_final"] if eff else None,
                             "delta_mean": eff["delta_mean"] if eff else None,
                             "correct": ok})
    n_eval = sum(1 for r in sign_results if r["delta"] is not None)
    n_ok = sum(1 for r in sign_results if r["correct"])
    sign_score = (n_ok / n_eval) if n_eval else 0.0
    out["sign"] = {"score": round(sign_score, 4), "n_eval": n_eval, "n_correct": n_ok,
                   "effect_col": EFFECT_COL, "tests": sign_results}

    # C2 placebo + C3 determinism (shared with the multi-seed scorer)
    placebo_score, out["placebo"] = _placebo_block(placebo_dir)
    det_score, out["determinism"] = _determinism_block(det_a, det_b)
    if incomplete:  # A5
        out["incomplete"] = [p.name for p in incomplete]
    # low-fidelity flag: any scored comparison dir produced with --fast
    out["fast"] = any(_dir_is_fast(d) for d in list(sign_sources.values()) + [placebo_dir])

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
                      "mean": None if m is None else round(m, 4),
                      "ci95": None if hw is None else round(hw, 4),
                      "n": n, "significant": sig, "correct": correct})
    sign_score = (n_correct / n_sig) if n_sig else 0.0
    out["sign"] = {"score": round(sign_score, 4), "n_eval": n_sig, "n_correct": n_correct,
                   "n_significant": n_sig, "n_data": n_data, "effect_col": EFFECT_COL,
                   "tests": tests}

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


# ── Scorecard ────────────────────────────────────────────────────────────────
def build_scorecard(tracks: dict) -> dict:
    implemented = {k: v for k, v in tracks.items()
                   if isinstance(v, dict) and v.get("status") == "ok"}
    composite = (statistics.fmean([v["score"] for v in implemented.values()])
                 if implemented else None)
    # trust gate (A4, tri-state): determinism failure poisons the card;
    # never-tested determinism is UNVERIFIED, not a free OK.
    det_status = tracks.get("C", {}).get("det_status")  # ok / fail / unassessed / None
    trust = {"fail": "UNTRUSTWORTHY", "ok": "OK"}.get(det_status, "UNVERIFIED")
    passed = [k for k, v in implemented.items() if v.get("pass")]
    headline = (min(passed, key=lambda k: implemented[k]["score"])
                if passed else None)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "trust_gate": trust,
        "fast": bool(tracks.get("C", {}).get("fast", False)),  # low-fidelity (--fast) run?
        "composite_hint": round(composite, 4) if composite is not None else None,
        "headline_track": headline,
        "tracks": tracks,
        "note": "composite is a trend hint only — read tracks separately (design §3).",
    }


def render_scorecard_md(sc: dict) -> str:
    L = ["# GAWorld-Bench Scorecard", "",
         f"- generated: {sc['generated']}",
         f"- **trust gate: {sc['trust_gate']}**",
         f"- composite hint: {sc['composite_hint']}  _(trend only, 弱证据)_",
         f"- headline (weakest passing track): {sc['headline_track']}"]
    if sc.get("fast"):
        L.append("- ⚡ **低保真运行（--fast）**：确定性认知 + 跳过每日总结/日记 + 3 agent；"
                 "结论仅供快速定向，勿当全保真结果。")
    L += ["", "| Track | 命题 | score | pass |", "|---|---|---|---|"]
    names = {"A": "宏观经验拟合", "B": "Stylized-facts", "C": "因果反事实 ⭐",
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
    return "\n".join(L) + "\n"


def save_scorecard(sc: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "scorecard.json").write_text(
        json.dumps(sc, indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS_DIR / "scorecard.md").write_text(
        render_scorecard_md(sc), encoding="utf-8")
    print(f"[bench] wrote {RESULTS_DIR/'scorecard.json'}")
    print(f"[bench] wrote {RESULTS_DIR/'scorecard.md'}")


# ── Report + data-driven improvement suggestions ─────────────────────────────
def _report_track_a(t: dict) -> tuple[list[str], list[str]]:
    """Returns (diagnosis lines, recommendations) for Track A from its numbers."""
    lines, recs = [], []
    n = t.get("n_samples")
    if n:
        lines.append(f"样本：{n} 个 agent 快照。")
    metrics = t.get("metrics", {})
    worst = None
    for key, m in sorted(metrics.items(), key=lambda kv: kv[1]["score"]):
        mark = "✓" if m["score"] >= 0.8 else "✗"
        lines.append(f"- `{key}`: sim {m['sim']} vs 锚点 {m['anchor']} "
                     f"(误差 {m['rel_err'] * 100:.1f}%) {mark}  _{m['source']}_")
        if worst is None or m["score"] < worst[1]["score"]:
            worst = (key, m)
    if worst and worst[1]["score"] < 0.8:
        k, m = worst
        tip = ("明确口径：『住户存款/收入』口径偏高(~43%)，『可支配收入流量储蓄』口径约30-35%"
               if k == "savings_rate" else "核对该指标的仿真计算与聚合方式")
        recs.append(f"主要拖累项 `{k}`（误差 {m['rel_err'] * 100:.1f}%）：{tip}，再校准锚点/容差。")
    if n is not None and n < 10:
        recs.append(f"样本仅 {n} 个，统计不稳；增大 agent 数或延长仿真天数后再评估宏观拟合。")
    recs.append("提醒：Track A 属弱证据（验证的是写进模型的参数），强证据看 Track C。")
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


def generate_report(sc: dict) -> str:
    tr = sc["tracks"]
    overview = "\n".join(render_scorecard_md(sc).splitlines()[1:])  # reuse table, drop H1
    L = ["# GAWorld-Bench 运行报告", "",
         "## 结果概览", overview, "",
         "## 分项诊断与建议", ""]
    next_steps: list[str] = []
    if sc["trust_gate"] != "OK":
        next_steps.append("【信任门槛】确定性失败 → 先修随机源，结果暂不可信。")

    names = {"A": "宏观经验拟合", "C": "因果反事实 ⭐"}
    builders = {"A": _report_track_a, "C": _report_track_c}
    for k in ("C", "A"):  # core track first
        t = tr.get(k, {})
        if t.get("status") != "ok":
            continue
        verdict = "PASS" if t.get("pass") else "FAIL"
        diag, recs = builders[k](t)
        L += [f"### Track {k} — {names[k]} — {t.get('score')} {verdict}", *diag, ""]
        if recs:
            L += ["建议：", *[f"{i}. {r}" for i, r in enumerate(recs, 1)], ""]
        next_steps += [f"【Track {k}】{r}" for r in recs]

    na = [k for k in ("B", "D", "E") if tr.get(k, {}).get("status") != "ok"]
    if na:
        L += [f"### 未实现：Track {', '.join(na)}",
              "这些有效性维度尚未评估，当前结论存在盲区（见设计文档路线图 §7）。", ""]

    L += ["## 下一步（按优先级）", ""]
    L += [f"{i}. {s}" for i, s in enumerate(next_steps, 1)] or ["- 暂无（所有已实现 track 通过）。"]
    return "\n".join(L) + "\n"


def save_report(sc: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    md = generate_report(sc)
    (RESULTS_DIR / "report.md").write_text(md, encoding="utf-8")
    archive = RESULTS_DIR / "reports"
    archive.mkdir(exist_ok=True)
    ts = sc["generated"].replace(":", "").replace("-", "")
    (archive / f"report_{ts}.md").write_text(md, encoding="utf-8")
    print(f"[bench] wrote {RESULTS_DIR/'report.md'} (+ archive copy)")


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
    return {"output_dir": root / "output",
            "sign_sources": {k: comps / k for k in fixtures},
            "placebo_dir": placebo, "det_a": st / "baseline_run_a.csv",
            "det_b": st / "baseline_run_b.csv"}


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
def main() -> int:
    p = argparse.ArgumentParser(description="GAWorld-Bench harness (v0.1)")
    p.add_argument("--track", choices=["A", "C"], help="run a single track")
    p.add_argument("--all", action="store_true", help="run all implemented tracks")
    p.add_argument("--synthetic", action="store_true",
                   help="fabricate fixtures and run without LLM/sim")
    p.add_argument("--output-dir", type=Path, help="sim output dir (Track A)")
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
        syn_sign_sources = fx["sign_sources"]
        args.placebo_dir = args.placebo_dir or fx["placebo_dir"]
        args.det_a = args.det_a or fx["det_a"]
        args.det_b = args.det_b or fx["det_b"]

    run_a = args.all or args.track == "A"
    run_c = args.all or args.track == "C"
    if not (run_a or run_c):
        run_a = run_c = True  # default: everything implemented

    tracks: dict = {}
    if run_a:
        out_dir = args.output_dir or (PROJECT_ROOT / "output")  # sensible default
        tracks["A"] = track_a_macro_fit(out_dir)
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
    tracks.setdefault("B", {"status": "n/a", "note": "未实现 (v0.3)"})
    tracks.setdefault("D", {"status": "n/a", "note": "未实现 (v0.4)"})
    tracks.setdefault("E", {"status": "n/a", "note": "确定性见 Track C; 成本未实现 (v0.2)"})

    sc = build_scorecard(tracks)
    save_scorecard(sc)
    save_report(sc)  # every run emits a report with improvement suggestions
    print("\n" + render_scorecard_md(sc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
