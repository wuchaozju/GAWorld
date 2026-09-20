"""Orchestration: units -> per-item scores -> ablation discrimination -> scorecard."""

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from . import ablate, judge as judge_mod, loader, renderer
from .aggregate import build_scorecard, discrimination, krippendorff_alpha_ordinal
from .rules import FACT_ITEMS, RULE_ITEMS
from .sampler import build_units

RUBRIC_PATH = Path(__file__).with_name("rubrics.json")


def load_rubric(path: Path | None = None) -> dict:
    path = Path(path or RUBRIC_PATH)
    raw = path.read_bytes()
    rubric = json.loads(raw.decode("utf-8"))
    rubric["rubric_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return rubric


def _units_for(item: dict, units: list[dict]) -> list[dict]:
    return [u for u in units if u["kind"] == item["unit"]]


def _prior_episodes(data: dict, unit: dict) -> list[dict]:
    return data["episodes"].get(unit.get("agent_id"), [])


def missing_capabilities(item: dict, caps: dict) -> list[str]:
    return [c for c in item.get("requires", []) if not caps.get(c)]


def score_item(item: dict, units: list[dict], data: dict, *,
               providers: list[str], min_days: int, samples_per_judge: int,
               judge_call=None) -> list[dict]:
    """One entry per unit. Rule items never touch the LLM."""
    iid = item["id"]
    missing = missing_capabilities(item, data.get("capabilities") or {})
    if missing:
        # The run simply does not contain what this item asks about. Abstain --
        # scoring it 0 would blame the model for a missing artifact.
        return [{"unit_id": u["unit_id"], "score": None, "abstain": True,
                 "evidence": [], "reasoning": f"本次运行缺少：{'、'.join(missing)}",
                 "missing_capabilities": missing}
                for u in _units_for(item, units)] or [
            {"unit_id": "-", "score": None, "abstain": True, "evidence": [],
             "reasoning": f"本次运行缺少：{'、'.join(missing)}",
             "missing_capabilities": missing}]

    results = []
    for unit in _units_for(item, units):
        facts = {}
        if iid in RULE_ITEMS:
            fn = RULE_ITEMS[iid][0]
            res = fn(unit, min_days=min_days) if iid == "R2.1" else fn(unit)
            res["unit_id"] = unit["unit_id"]
            results.append(res)
            continue
        if iid in FACT_ITEMS:
            fn = FACT_ITEMS[iid][0]
            pre = fn(unit, _prior_episodes(data, unit)) if iid == "R1.1" else fn(unit)
            facts = pre["facts"]
        if not providers:
            results.append({"unit_id": unit["unit_id"], "score": None, "abstain": True,
                            "evidence": [], "reasoning": "未配置 judge，跳过 LLM 条目",
                            "facts": facts})
            continue
        verdict = judge_mod.judge_item(
            item, renderer.render(unit), facts,
            providers=providers, samples_per_judge=samples_per_judge, call=judge_call)
        verdict["unit_id"] = unit["unit_id"]
        verdict["facts"] = facts
        results.append(verdict)
    return results


def _mean(results: list[dict]) -> float | None:
    vals = [r["score"] for r in results if not r.get("abstain") and r.get("score") is not None]
    return sum(vals) / len(vals) if vals else None


def run(data: dict, *, providers: list[str] | None = None, sample_seed: int = 42,
        min_days: int = 30, samples_per_judge: int = 3, ablations: list[str] | None = None,
        rubric_path: Path | None = None, targets: dict | None = None,
        judge_call=None) -> dict:
    rubric = load_rubric(rubric_path)
    providers = providers or []
    data.setdefault("capabilities", loader.capabilities(data))
    sampled = build_units(data, seed=sample_seed, min_days=min_days, targets=targets)
    units = sampled["units"]

    item_results: dict[str, list[dict]] = {}
    for item in rubric["items"]:
        item_results[item["id"]] = score_item(
            item, units, data, providers=providers, min_days=min_days,
            samples_per_judge=samples_per_judge, judge_call=judge_call)

    disc = _run_ablations(rubric, units, data, ablations or [], providers=providers,
                          min_days=min_days, samples_per_judge=samples_per_judge,
                          item_results=item_results, judge_call=judge_call)

    reliability = _reliability(item_results, rubric, disc)
    manifest = dict(sampled["manifest"])
    manifest["rubric_hash"] = rubric["rubric_hash"]
    manifest["judges"] = providers
    manifest["ablations_run"] = ablations or []
    manifest["run_mode"] = data.get("run_mode", "unknown")
    manifest["capabilities"] = data["capabilities"]
    manifest["missing_capabilities"] = sorted(
        {c for k, v in data["capabilities"].items() if not v for c in [k]})

    scorecard = build_scorecard(rubric, item_results, sampled["coverage"],
                                discrimination_by_item=disc, reliability=reliability,
                                manifest=manifest)
    scorecard["raw_results"] = item_results
    return scorecard


def _run_ablations(rubric, units, data, names, *, providers, min_days,
                   samples_per_judge, item_results, judge_call) -> dict:
    """For each requested operator, re-score only the items it targets."""
    if not names:
        return {}
    by_item: dict[str, list[float]] = defaultdict(list)
    id_to_item = {i["id"]: i for i in rubric["items"]}

    for name in names:
        targets = rubric["ablations"][name]["targets"]
        op_seed = int(hashlib.sha256(name.encode()).hexdigest()[:6], 16)
        corrupted = [ablate.apply(name, u, data, seed=op_seed) for u in units]
        for iid in targets:
            item = id_to_item.get(iid)
            if item is None:
                continue
            res = score_item(item, corrupted, data, providers=providers,
                             min_days=min_days, samples_per_judge=samples_per_judge,
                             judge_call=judge_call)
            m = _mean(res)
            if m is not None:
                by_item[iid].append(m)

    out = {}
    for iid, means in by_item.items():
        real = _mean(item_results.get(iid, []))
        # Worst case across operators: an item only counts as discriminating if
        # it catches *every* corruption it claims to catch.
        out[iid] = discrimination(real, max(means)) if means else None
    return out


def _reliability(item_results: dict, rubric: dict, disc: dict) -> dict:
    ratings = []
    spreads = []
    for results in item_results.values():
        for r in results:
            votes = r.get("votes") or []
            if len(votes) >= 2:
                ratings.append([v["score"] for v in votes])
            if r.get("vote_spread") is not None:
                spreads.append(r["vote_spread"])
    alpha = krippendorff_alpha_ordinal(ratings) if ratings else None

    dims_bad = set()
    for item in rubric["items"]:
        d = disc.get(item["id"])
        if d is not None and d < rubric["gates"]["discrimination_min"]:
            dims_bad.add(item["dim"])
    # A dimension is untrustworthy only when *every* one of its items fails.
    by_dim = defaultdict(list)
    for item in rubric["items"]:
        by_dim[item["dim"]].append(item["id"])
    untrustworthy = [d for d in dims_bad
                     if all(disc.get(i) is not None
                            and disc[i] < rubric["gates"]["discrimination_min"]
                            for i in by_dim[d])]
    return {
        "krippendorff_alpha": round(alpha, 3) if alpha is not None else None,
        "n_rated_units": len(ratings),
        "mean_vote_spread": round(sum(spreads) / len(spreads), 3) if spreads else None,
        "any_dimension_untrustworthy": bool(untrustworthy),
        "untrustworthy_dimensions": untrustworthy,
    }


def stub_judge(prompt: str, provider: str | None = None) -> str:
    """Deterministic offline judge for --synthetic.

    It only reacts to corruption that is *structurally* visible in the rendered
    text (duplicated days, impossible travel, foreign recollections). It cannot
    detect swapped personas, rewired social ties or stripped events -- those
    items will therefore show low discrimination in synthetic runs, which is a
    property of this stub, not of the rubric. Its job is to prove the plumbing
    works end to end, not to produce meaningful scores.
    """
    rng = random.Random(hashlib.sha256((prompt + str(provider)).encode()).hexdigest()[:8])
    markers = [
        "记不清了",                       # N1
        "远郊分部", "600分钟",             # N7
        '"all_flat": true',               # N7
        '"grounded_ratio": 0.0',          # N1
    ]
    corrupted = any(m in prompt for m in markers)
    if not corrupted and "### 第" in prompt:
        blocks = [b.strip() for b in prompt.split("### 第")[1:]]
        bodies = [b.split("\n", 1)[-1] for b in blocks]
        corrupted = len(bodies) >= 3 and len(set(bodies)) == 1   # N4
    score = 0 if corrupted else rng.choice([1, 2, 2])
    return json.dumps({"score": score, "evidence": ["（stub judge 证据占位）"],
                       "reasoning": "stub", "abstain": False}, ensure_ascii=False)
