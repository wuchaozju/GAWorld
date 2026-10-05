"""Human anchor calibration for Track R (design doc §5.3, roadmap P4).

A judge's score means something only if people reading the same sample
against the same rubric line would give the same score. This module builds
the set people annotate, stores their labels, and turns them into the
numbers that gate Track R:

* **human–human** ordinal Krippendorff α — below 0.7 the rubric wording is
  ambiguous, and no judge can be calibrated against it;
* **human–judge** Spearman ρ and quadratic-weighted κ, per annotator — below
  0.6 the judge ensemble does not read the rubric the way people do.

Until a calibration for the current rubric passes, every Track R scorecard
stays UNVERIFIED (``scorecard_block`` → ``aggregate._trust_gate``).

A set lives in ``results/rubric_calibration/<set_id>/``::

    set.json             what annotators see: the rendered sample, the rubric line, program facts
    key.json             what they must not: the unit, real or corrupted, the rule's own score
    labels/<name>.json   one file per annotator
    judge.json           the judge ensemble's verdicts on exactly the same tasks
    analysis.json / .md

About a third of the tasks are corrupted with one of the item's own ablation
operators (§5.4), blind. That spreads the samples over the 0–2 scale — a set
of uniformly decent samples gives α no variance to work with — and it checks
the operators themselves: if people cannot tell a corrupted sample either,
the operator is broken, not the judge.

Rule items are included too. Their "machine" score is the rule's, and the
agreement is reported apart from the judge's: a rule people disagree with is
a measurement question (R4.1's travel-time reading was one).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path

from . import ablate, loader, renderer
from . import judge as judge_mod
from .aggregate import krippendorff_alpha_ordinal, quadratic_weighted_kappa
from .rules import FACT_ITEMS, RULE_ITEMS
from .sampler import build_units

CALIBRATION_DIR = Path(__file__).resolve().parents[1] / "results" / "rubric_calibration"

#: Design doc §5.3. Kept here rather than in rubrics.json: editing that file
#: re-hashes the rubric, and these are thresholds on the calibration, not
#: rubric text.
GATES = {
    "human_alpha_min": 0.7,
    "human_judge_min": 0.6,
    "min_tasks": 20,
    "min_annotators": 2,
}
DEFAULT_N = 30
ABLATED_SHARE = 1 / 3
JUDGED_CHECKERS = ("llm", "hybrid")

_NAME_RE = re.compile(r"[^0-9A-Za-z_\-一-鿿]+")


# ───────────────────────── building a set ─────────────────────────

def item_hash(item: dict) -> str:
    """Changes whenever an item's wording or anchors change: labels on the old text are stale."""
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def _machine_and_facts(item: dict, unit: dict, data: dict, min_days: int) -> tuple[int | None, dict]:
    iid = item["id"]
    if iid in RULE_ITEMS:
        fn = RULE_ITEMS[iid][0]
        res = fn(unit, min_days=min_days) if iid == "R2.1" else fn(unit)
        return (None if res.get("abstain") else res.get("score")), res.get("facts") or {}
    if iid in FACT_ITEMS:
        fn = FACT_ITEMS[iid][0]
        prior = data["episodes"].get(unit.get("agent_id"), [])
        pre = fn(unit, prior) if iid == "R1.1" else fn(unit)
        return None, pre.get("facts") or {}
    return None, {}


def build_set(data: dict, rubric: dict, *, n: int = DEFAULT_N, seed: int = 7, sample_seed: int = 42,
              min_days: int = 30, ablated_share: float = ABLATED_SHARE, source: str = "") -> tuple[dict, dict]:
    """Draw ``n`` tasks, stratified over the dimensions the run has data for.

    Round-robin over dimensions, then over items within a dimension, so no
    dimension or item dominates. Returns ``(set_doc, key_doc)``.
    """
    rng = random.Random(seed)
    caps = data.setdefault("capabilities", loader.capabilities(data))
    units = build_units(data, seed=sample_seed, min_days=min_days)["units"]

    pools: dict[str, list[tuple[dict, list[dict]]]] = defaultdict(list)
    for item in rubric["items"]:
        if any(not caps.get(c) for c in item.get("requires", [])):
            continue
        candidates = [u for u in units if u["kind"] == item["unit"]]
        if candidates:
            pools[item["dim"]].append((item, rng.sample(candidates, len(candidates))))

    picks: list[tuple[dict, dict]] = []
    turn = dict.fromkeys(pools, 0)
    while len(picks) < n and any(units_left for entries in pools.values() for _, units_left in entries):
        for dim in sorted(pools):
            entries = [entry for entry in pools[dim] if entry[1]]
            if not entries or len(picks) >= n:
                continue
            item, remaining = entries[turn[dim] % len(entries)]
            turn[dim] += 1
            picks.append((item, remaining.pop()))

    corruptible = [i for i, (item, _) in enumerate(picks)
                   if any(op in rubric.get("ablations", {}) for op in item.get("ablations", []))]
    to_corrupt = set(rng.sample(corruptible, min(len(corruptible), round(len(picks) * ablated_share))))

    tasks, key = [], {}
    for index, (item, unit) in enumerate(picks):
        shown, operator = unit, None
        if index in to_corrupt:
            ops = [op for op in item.get("ablations", []) if op in rubric["ablations"]]
            op = rng.choice(ops)
            corrupted = ablate.apply(op, unit, data, seed=rng.randrange(1 << 30))
            # An operator that leaves the rendered text unchanged corrupts
            # nothing a reader could see; the task stays a real one.
            if renderer.render(corrupted) != renderer.render(unit):
                shown, operator = corrupted, op
        machine, facts = _machine_and_facts(item, shown, data, min_days)
        task_id = f"T{index + 1:02d}"
        tasks.append({
            "task_id": task_id,
            "item_id": item["id"],
            "dim": item["dim"],
            "checker": item["checker"],
            "proposition": item["proposition"],
            "anchors": item.get("anchors", {}),
            "failure_modes": item.get("failure_modes", []),
            "sample": renderer.render(shown),
            "facts": facts if item["checker"] != "rule" else {},
        })
        key[task_id] = {"unit_id": unit["unit_id"], "source": "ablated" if operator else "real",
                        "operator": operator, "rule_score": machine if item["checker"] == "rule" else None}

    dims = defaultdict(int)
    for task in tasks:
        dims[task["dim"]] += 1
    set_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{rubric['rubric_hash'][:6]}"
    set_doc = {
        "set_id": set_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rubric_version": rubric.get("rubric_version"),
        "rubric_hash": rubric["rubric_hash"],
        "item_hashes": {item["id"]: item_hash(item) for item, _ in picks},
        "source": source,
        "run_mode": data.get("run_mode", "unknown"),
        "seed": seed,
        "sample_seed": sample_seed,
        "n_requested": n,
        "n_tasks": len(tasks),
        "dims": dict(sorted(dims.items())),
        "dims_without_data": sorted(set(rubric["dimensions"]) - set(dims)),
        "tasks": tasks,
    }
    return set_doc, {"set_id": set_id, "tasks": key}


# ───────────────────────── storage ─────────────────────────

def annotator_slug(name: str) -> str:
    slug = _NAME_RE.sub("_", str(name or "").strip()).strip("_")[:40]
    if not slug:
        raise ValueError("标注者名字不能为空")
    return slug


def _set_dir(set_id: str, root: Path) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_\-]+", str(set_id or "")):
        raise ValueError(f"校准集 id 不合法：{set_id!r}")
    return Path(root) / set_id


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def save_set(set_doc: dict, key_doc: dict, root: Path = CALIBRATION_DIR) -> Path:
    folder = _set_dir(set_doc["set_id"], root)
    _write(folder / "set.json", set_doc)
    _write(folder / "key.json", key_doc)
    return folder


def load_set(set_id: str, root: Path = CALIBRATION_DIR) -> tuple[dict, dict]:
    folder = _set_dir(set_id, root)
    set_doc = _read(folder / "set.json")
    if not set_doc:
        raise FileNotFoundError(f"没有这个校准集：{set_id}")
    return set_doc, _read(folder / "key.json", {"tasks": {}})


def load_labels(set_id: str, root: Path = CALIBRATION_DIR) -> dict[str, dict]:
    """``annotator name -> {task_id: {"score", "note", "at"}}``."""
    out = {}
    for path in sorted((_set_dir(set_id, root) / "labels").glob("*.json")):
        doc = _read(path, {})
        if isinstance(doc, dict) and doc.get("annotator"):
            out[doc["annotator"]] = doc.get("labels") or {}
    return out


def save_label(set_id: str, annotator: str, task_id: str, score, note: str = "",
               root: Path = CALIBRATION_DIR) -> dict:
    """``score`` is 0, 1, 2, or ``None`` for「记录里没有能判断的信息」."""
    set_doc, _ = load_set(set_id, root)
    if task_id not in {t["task_id"] for t in set_doc["tasks"]}:
        raise ValueError(f"校准集里没有任务 {task_id}")
    if score is not None and score not in (0, 1, 2):
        raise ValueError("分数只能是 0 / 1 / 2，或留空表示无法判断")
    path = _set_dir(set_id, root) / "labels" / f"{annotator_slug(annotator)}.json"
    doc = _read(path, {}) or {}
    doc["annotator"] = str(annotator).strip()
    doc.setdefault("labels", {})[task_id] = {"score": score, "note": str(note or "")[:300],
                                              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _write(path, doc)
    return doc


def save_judge(set_id: str, judge_doc: dict, root: Path = CALIBRATION_DIR) -> None:
    _write(_set_dir(set_id, root) / "judge.json", judge_doc)


def load_judge(set_id: str, root: Path = CALIBRATION_DIR) -> dict | None:
    return _read(_set_dir(set_id, root) / "judge.json")


def list_sets(root: Path = CALIBRATION_DIR) -> list[dict]:
    """Newest first, each with what a panel needs to pick one."""
    out = []
    for folder in sorted(Path(root).glob("*/set.json"), reverse=True):
        doc = _read(folder) or {}
        if not doc.get("set_id"):
            continue
        labels = load_labels(doc["set_id"], root)
        analysis = _read(folder.parent / "analysis.json") or {}
        out.append({
            "set_id": doc["set_id"], "created_at": doc.get("created_at"), "n_tasks": doc.get("n_tasks"),
            "rubric_version": doc.get("rubric_version"), "rubric_hash": doc.get("rubric_hash"),
            "dims": doc.get("dims"), "dims_without_data": doc.get("dims_without_data"),
            "source": doc.get("source"),
            "annotators": {name: sum(1 for v in marks.values() if v) for name, marks in labels.items()},
            "judged": (folder.parent / "judge.json").exists(),
            "gate": analysis.get("gate"),
        })
    return out


# ───────────────────────── judging ─────────────────────────

def judge_set(set_doc: dict, providers: list[str], *, samples_per_judge: int = 3, call=None) -> dict:
    """The judge ensemble on exactly the tasks people label (llm / hybrid items)."""
    verdicts = {}
    for task in set_doc["tasks"]:
        if task["checker"] not in JUDGED_CHECKERS:
            continue
        item = {"id": task["item_id"], "proposition": task["proposition"],
                "anchors": task["anchors"], "failure_modes": task["failure_modes"]}
        verdicts[task["task_id"]] = judge_mod.judge_item(
            item, task["sample"], task.get("facts") or None,
            providers=providers, samples_per_judge=samples_per_judge, call=call)
    return {"set_id": set_doc["set_id"], "providers": list(providers), "samples_per_judge": samples_per_judge,
            "rubric_hash": set_doc["rubric_hash"], "judged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verdicts": verdicts}


# ───────────────────────── analysis ─────────────────────────

def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank correlation with average ranks for ties; ``None`` when either side is constant."""
    if len(a) < 3 or len(a) != len(b):
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def _round(value, digits=3):
    return None if value is None else round(float(value), digits)


def machine_scores(set_doc: dict, key_doc: dict, judge_doc: dict | None) -> dict[str, int | None]:
    verdicts = (judge_doc or {}).get("verdicts") or {}
    out = {}
    for task in set_doc["tasks"]:
        tid = task["task_id"]
        if task["checker"] == "rule":
            out[tid] = ((key_doc.get("tasks") or {}).get(tid) or {}).get("rule_score")
        else:
            verdict = verdicts.get(tid) or {}
            out[tid] = None if verdict.get("abstain") else verdict.get("score")
    return out


def _agreement(tasks: list[dict], human: dict[str, dict], machine: dict[str, int | None]) -> dict:
    pairs = [((human.get(t["task_id"]) or {}).get("score"), machine.get(t["task_id"])) for t in tasks]
    pairs = [(h, m) for h, m in pairs if h is not None and m is not None]
    if not pairs:
        return {"n": 0, "spearman": None, "qwk": None}
    hs, ms = [p[0] for p in pairs], [p[1] for p in pairs]
    return {"n": len(pairs), "spearman": _round(spearman(hs, ms)),
            "qwk": _round(quadratic_weighted_kappa(hs, ms))}


def _mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def analyze(set_doc: dict, key_doc: dict, labels: dict[str, dict], judge_doc: dict | None = None,
            *, gates: dict | None = None) -> dict:
    gates = {**GATES, **(gates or {})}
    tasks = set_doc["tasks"]
    keys = key_doc.get("tasks") or {}
    names = sorted(labels)
    task_ids = [t["task_id"] for t in tasks]
    complete = [n for n in names if all(tid in labels[n] for tid in task_ids)]

    rows = [[(labels[n].get(tid) or {}).get("score") for n in names] for tid in task_ids]
    double = sum(1 for row in rows if sum(v is not None for v in row) >= 2)
    alpha = krippendorff_alpha_ordinal(rows) if names else None

    machine = machine_scores(set_doc, key_doc, judge_doc)
    judged = [t for t in tasks if t["checker"] in JUDGED_CHECKERS]
    ruled = [t for t in tasks if t["checker"] == "rule"]
    agreement = {
        "judge": {n: _agreement(judged, labels[n], machine) for n in names},
        "rule": {n: _agreement(ruled, labels[n], machine) for n in names},
    }
    summary = {}
    for group, by_name in agreement.items():
        summary[group] = {
            metric: _round(_mean([row[metric] for row in by_name.values()]))
            for metric in ("spearman", "qwk")
        }

    human_mean = {tid: _mean([v for v in row if v is not None]) for tid, row in zip(task_ids, rows, strict=True)}
    real = [human_mean[tid] for tid in task_ids if (keys.get(tid) or {}).get("source") == "real"]
    corrupted = [human_mean[tid] for tid in task_ids if (keys.get(tid) or {}).get("source") == "ablated"]
    ablation_check = {"n_real": sum(v is not None for v in real), "n_ablated": sum(v is not None for v in corrupted),
                      "human_mean_real": _round(_mean(real)), "human_mean_ablated": _round(_mean(corrupted))}
    if ablation_check["human_mean_real"] is not None and ablation_check["human_mean_ablated"] is not None:
        ablation_check["gap"] = _round((ablation_check["human_mean_real"] - ablation_check["human_mean_ablated"]) / 2)

    items: dict[str, dict] = {}
    for task, row in zip(tasks, rows, strict=True):
        entry = items.setdefault(task["item_id"], {"dim": task["dim"], "checker": task["checker"], "n_tasks": 0,
                                                   "n_double": 0, "n_disagree": 0, "gaps": [], "human": [],
                                                   "machine": []})
        scored = [v for v in row if v is not None]
        entry["n_tasks"] += 1
        entry["human"] += scored
        if len(scored) >= 2:
            entry["n_double"] += 1
            entry["n_disagree"] += int(max(scored) - min(scored) >= 1)
        m = machine.get(task["task_id"])
        if m is not None:
            entry["machine"].append(m)
            if scored:
                entry["gaps"].append(abs(statistics.fmean(scored) - m))
    queue = []
    for iid, entry in items.items():
        gap = _mean(entry.pop("gaps"))
        entry["human_mean"] = _round(_mean(entry.pop("human")))
        entry["machine_mean"] = _round(_mean(entry.pop("machine")))
        entry["mean_abs_gap"] = _round(gap)
        reasons = []
        if entry["n_double"] and entry["n_disagree"] * 2 >= entry["n_double"]:
            reasons.append("标注者之间常有分歧：档位描述可能有歧义")
        if gap is not None and gap >= 1.0:
            reasons.append("机器分与人平均差一档以上")
        if reasons:
            queue.append({"item_id": iid, "reasons": reasons})

    reasons, status = [], "ok"
    if len(complete) < gates["min_annotators"]:
        status, reasons = "incomplete", [f"{len(complete)}/{gates['min_annotators']} 位标注者完成了全部任务"]
    elif double < gates["min_tasks"]:
        status, reasons = "incomplete", [f"只有 {double} 个任务有两人以上打分，至少要 {gates['min_tasks']} 个"]
    elif alpha is None or alpha < gates["human_alpha_min"]:
        status = "fail"
        reasons = [f"人-人一致性 α={'—' if alpha is None else f'{alpha:.2f}'} 低于 {gates['human_alpha_min']}："
                   "rubric 表述有歧义，先改 rubric 再校准 judge"]
    elif judged and not (judge_doc or {}).get("verdicts"):
        status, reasons = "incomplete", ["还没有 judge 分数：python rubric_calibrate.py --judge"]
    elif judged:
        low = [f"{metric} {summary['judge'][metric]:.2f}" if summary["judge"][metric] is not None else f"{metric} —"
               for metric in ("spearman", "qwk")
               if summary["judge"][metric] is None or summary["judge"][metric] < gates["human_judge_min"]]
        if low:
            status = "fail"
            reasons = [f"judge 与人的一致性不足（{'、'.join(low)}，门槛 {gates['human_judge_min']}）"]

    return {
        "set_id": set_doc["set_id"],
        "rubric_version": set_doc.get("rubric_version"),
        "rubric_hash": set_doc.get("rubric_hash"),
        "judge_providers": (judge_doc or {}).get("providers") or [],
        "computed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_tasks": len(tasks),
        "dims": set_doc.get("dims"),
        "dims_without_data": set_doc.get("dims_without_data"),
        "annotators": {n: sum(1 for tid in task_ids if tid in labels[n]) for n in names},
        "complete_annotators": complete,
        "n_double_scored": double,
        "human_alpha": _round(alpha),
        "agreement": agreement,
        "agreement_summary": summary,
        "ablation_check": ablation_check,
        "items": dict(sorted(items.items())),
        "rewrite_queue": queue,
        "thresholds": gates,
        "gate": {"status": status, "reasons": reasons},
    }


def save_analysis(analysis: dict, root: Path = CALIBRATION_DIR) -> None:
    folder = _set_dir(analysis["set_id"], root)
    _write(folder / "analysis.json", analysis)
    (folder / "analysis.md").write_text(render_markdown(analysis), encoding="utf-8")


def run_analysis(set_id: str, root: Path = CALIBRATION_DIR) -> dict:
    set_doc, key_doc = load_set(set_id, root)
    analysis = analyze(set_doc, key_doc, load_labels(set_id, root), load_judge(set_id, root))
    save_analysis(analysis, root)
    return analysis


def latest_analysis(root: Path = CALIBRATION_DIR, rubric_hash: str | None = None) -> dict | None:
    """The newest analysis for this rubric if there is one, else the newest at all
    (so the gate can say it is stale rather than that it is missing)."""
    found = [_read(path) for path in sorted(Path(root).glob("*/analysis.json"), reverse=True)]
    found = [doc for doc in found if isinstance(doc, dict)]
    if rubric_hash:
        matching = [doc for doc in found if doc.get("rubric_hash") == rubric_hash]
        if matching:
            return matching[0]
    return found[0] if found else None


def scorecard_block(analysis: dict | None, rubric_hash: str, providers: list[str] | None = None) -> dict:
    """What a Track R scorecard carries about its calibration. ``status == "ok"``
    is the only state that lets the trust gate reach OK."""
    if not analysis:
        return {"status": "missing", "reason": "未做人类锚点校准（P4）：python rubric_calibrate.py --build 后由两人标注"}
    block = {"set_id": analysis.get("set_id"), "human_alpha": analysis.get("human_alpha"),
             "judge": (analysis.get("agreement_summary") or {}).get("judge"),
             "judge_providers": analysis.get("judge_providers") or []}
    if analysis.get("rubric_hash") != rubric_hash:
        return {**block, "status": "stale",
                "reason": f"人类校准基于另一版 rubric（hash {analysis.get('rubric_hash')}），改过 rubric 要重做校准"}
    gate = analysis.get("gate") or {}
    if gate.get("status") != "ok":
        return {**block, "status": gate.get("status") or "fail",
                "reason": "人类校准未通过：" + "；".join(gate.get("reasons") or ["原因未记录"])}
    if providers and sorted(providers) != sorted(block["judge_providers"]):
        return {**block, "status": "other_judges",
                "reason": f"本次 judge（{'、'.join(providers)}）与校准时的（{'、'.join(block['judge_providers'])}）不同"}
    return {**block, "status": "ok", "reason": ""}


# ───────────────────────── report ─────────────────────────

def render_markdown(analysis: dict) -> str:
    gate = analysis.get("gate") or {}
    summary = analysis.get("agreement_summary") or {}
    lines = [f"# Track R 人类锚点校准 · {analysis.get('set_id')}", "",
             f"- rubric 版本：`{analysis.get('rubric_version')}`（hash `{analysis.get('rubric_hash')}`）",
             f"- judges：`{'、'.join(analysis.get('judge_providers') or []) or '（未跑）'}`",
             f"- 任务：{analysis.get('n_tasks')} 个，按维度 {analysis.get('dims')}"
             + (f"；本次 run 没有数据的维度：{'、'.join(analysis['dims_without_data'])}"
                if analysis.get("dims_without_data") else ""),
             f"- 标注者：{analysis.get('annotators')}（完成全部任务：{'、'.join(analysis.get('complete_annotators') or []) or '无'}）",
             f"- **结论：{gate.get('status')}**" + (f"（{'；'.join(gate.get('reasons') or [])}）" if gate.get("reasons") else ""),
             "", "## 一致性", "",
             "| 指标 | 值 | 门槛 |", "|---|---|---|",
             f"| 人-人 Krippendorff α（序数） | {analysis.get('human_alpha')} | ≥ {analysis['thresholds']['human_alpha_min']} |",
             f"| 人-judge Spearman ρ（各标注者平均） | {(summary.get('judge') or {}).get('spearman')} | ≥ {analysis['thresholds']['human_judge_min']} |",
             f"| 人-judge 加权 κ（QWK，各标注者平均） | {(summary.get('judge') or {}).get('qwk')} | ≥ {analysis['thresholds']['human_judge_min']} |",
             f"| 人-规则 Spearman ρ / QWK（只报告） | {(summary.get('rule') or {}).get('spearman')} / {(summary.get('rule') or {}).get('qwk')} | — |",
             f"| 两人以上打分的任务 | {analysis.get('n_double_scored')} | ≥ {analysis['thresholds']['min_tasks']} |"]
    check = analysis.get("ablation_check") or {}
    lines += ["", "## 被破坏的样本人能看出来吗", "",
              f"真实样本人均 {check.get('human_mean_real')}（{check.get('n_real')} 个），被破坏样本 {check.get('human_mean_ablated')}"
              f"（{check.get('n_ablated')} 个）" + (f"，差 {check['gap']}（0–1 尺度）" if check.get("gap") is not None else "") + "。",
              "差距很小说明连人也分不出——那是破坏算子没破坏到点子上，不是 judge 的问题。"]
    lines += ["", "## 逐 item", "", "| item | 维度 | checker | 任务 | 两人分歧 | 人均 | 机器均 | 平均差 |",
              "|---|---|---|---|---|---|---|---|"]
    for iid, entry in (analysis.get("items") or {}).items():
        lines.append(f"| {iid} | {entry['dim']} | {entry['checker']} | {entry['n_tasks']} | {entry['n_disagree']}/{entry['n_double']} "
                     f"| {entry['human_mean']} | {entry['machine_mean']} | {entry['mean_abs_gap']} |")
    if analysis.get("rewrite_queue"):
        lines += ["", "## 重写队列", ""] + [f"- **{row['item_id']}**：{'；'.join(row['reasons'])}"
                                         for row in analysis["rewrite_queue"]]
    return "\n".join(lines) + "\n"


__all__ = [
    "CALIBRATION_DIR",
    "GATES",
    "analyze",
    "annotator_slug",
    "build_set",
    "item_hash",
    "judge_set",
    "latest_analysis",
    "list_sets",
    "load_judge",
    "load_labels",
    "load_set",
    "render_markdown",
    "run_analysis",
    "save_analysis",
    "save_judge",
    "save_label",
    "save_set",
    "scorecard_block",
    "spearman",
]
