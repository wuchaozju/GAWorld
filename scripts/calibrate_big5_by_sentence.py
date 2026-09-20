#!/usr/bin/env python3
"""Per-sentence attribution — the input-side fix for the calibrator's bleed.

The one-shot calibrator hands the model a whole paragraph and names one
dimension: *"is there evidence for C in here?"* The paragraph contains
sentences written for all five dimensions at once, and "does this sentence
count as C evidence" has no hard boundary — so the model answers yes. Measured
against ground truth on 51 residents it marked **225** cells evidenced when the
generator had written **155**, and the 70 extras correlate **r = -0.01** with
truth while carrying a re-scoring sd of 1.49.

Four output-side filters were tried and all failed (proposal
``2026-08-22-calibrator-cross-dimension-bleed.md`` §3-4). The reason they must:
the bled evidence is **real text from the paragraph**, quoted exactly — 11
fabricated cells quote the source at grounding 1.00, including an A scored 7.0
on a sentence written for E. No property of the quote can separate them.

This script asks a different question. One sentence at a time::

    which of the five dimensions does THIS sentence bear on, if any?
    direction and strength?

and then aggregates per dimension. A dimension no sentence claimed is
``unstated`` — **derived from the aggregation, not self-reported by the model**.
That is the same move the corpus rewrite made: turn the property you care about
into a structural fact rather than something you measure afterwards and hope.

It is also cheaper: 160 sentences x 3 repeats = 480 calls against the current
5 dimensions x 51 agents x 3 = 765.

Usage::

    python scripts/calibrate_big5_by_sentence.py --dry-run    # costs nothing
    python scripts/calibrate_big5_by_sentence.py --self-test  # costs nothing
    python scripts/calibrate_big5_by_sentence.py              # ~480 calls
    python scripts/calibrate_big5_by_sentence.py --analyse-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gaworld.personality.traits import DIMENSION_NAMES_ZH, DIMENSIONS  # noqa: E402
from gaworld.sim.agents_loader import parse_profile  # noqa: E402

# --------------------------------------------------------------------------
# Pre-registered acceptance criteria (proposal section 6.2). Printed before the
# first call is spent; not to be edited once a run has started.
# --------------------------------------------------------------------------

#: The generator's authoring floor: dimensions below this were never written.
FLAT_Z = 0.5

REPEATS = 3
SCALE_MIDPOINT = 4.0

CRITERIA = {
    "r_written_min": 0.79,      # must not be worse than the one-shot scorer
    "precision_min": 0.90,      # the point of the exercise: 68% today
    "recall_min": 0.85,         # not bought by throwing the signal away
    "bias_max": 0.20,           # today A +0.39 / O -0.33 / N -0.29
}

CHECKPOINT = "output/traits/by_sentence.jsonl"

#: Self-test only: how often a clean scorer notices a dimension the sentence
#: really carries. Not a claim about the real model — a knob for asking "if the
#: scorer were this good, would the criteria pass?"
HIT_RATE = 0.7

#: Same anchors as the one-shot calibrator, so a difference in result is a
#: difference in *method* rather than in wording.
from scripts.calibrate_big5 import ANCHOR_DESCRIPTIONS  # noqa: E402

PROMPT = """你在为一项社会仿真研究做人格编码。下面是一位虚构居民行为描述中的**一句话**。

这句话：
{sentence}

大五人格的五个维度，各自的两端是：
{anchors}

请判断：**这一句话**能说明其中哪些维度？

要求：
1) 只看这一句。不要推测句子之外的事，也不要脑补这个人的其他方面。
2) 一句话可以同时说明两个维度，也可以**一个都不说明**——
   「一个都不说明」是很常见的正常答案，不是失败。请不要为了填满而勉强归类。
3) 对每个你认为成立的维度，给 1-7 分（1 = 强烈偏向低端，7 = 强烈偏向高端），
   并**从这句话里原样摘出**支撑你判断的片段。

输出严格的 JSON，不要任何其他文字：
{{"dims": [{{"dim": "<o|c|e|a|n>", "score": <1-7 整数>, "quote": "<句中原文，20 字以内>"}}]}}
没有任何维度成立时输出 {{"dims": []}}。"""


def build_anchor_text() -> str:
    lines = []
    for dim in DIMENSIONS:
        low, high = ANCHOR_DESCRIPTIONS[dim]
        lines.append(f"- {dim}（{DIMENSION_NAMES_ZH[dim]}）：1 分 = {low}；7 分 = {high}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------

def split_sentences(paragraph: str) -> list[str]:
    """Split on Chinese sentence enders, dropping fragments too short to judge."""
    parts = re.split(r"[。；！？\n]+", str(paragraph or ""))
    return [p.strip() for p in parts if len(p.strip()) >= 6]


def load_corpus(path: str) -> dict[int, list[str]]:
    text = Path(path).read_text(encoding="utf-8")
    out: dict[int, list[str]] = {}
    for match in re.finditer(r"## Profile (\d+)｜.*?(?=\n## Profile |\Z)", text, re.S):
        parsed = parse_profile(match.group(0))
        tendencies = str(parsed.get("behavior_tendencies", "") or "").strip()
        if tendencies:
            out[int(match.group(1))] = split_sentences(tendencies)
    return out


def load_truth(path: str) -> dict[int, dict[str, float]]:
    import csv

    return {
        int(row["id"]): {dim: float(row[dim]) for dim in DIMENSIONS}
        for row in csv.DictReader(open(path, encoding="utf-8-sig"))
    }


# --------------------------------------------------------------------------
# Aggregation — where ``unstated`` becomes a structural fact
# --------------------------------------------------------------------------

def aggregate(claims: list[dict[str, Any]], repeats: int) -> dict[str, Any]:
    """Per-dimension score for one agent, from that agent's sentence claims.

    A dimension is ``stated`` when at least ``min_votes`` of the repeats claimed
    it on at least one sentence. Requiring a majority of *repeats* rather than a
    majority of *sentences* is deliberate: one vivid sentence is legitimate
    evidence, three coin-flips on the same sentence are not.
    """
    min_votes = repeats // 2 + 1
    by_dim: dict[str, list[float]] = defaultdict(list)
    votes: dict[str, Counter] = defaultdict(Counter)
    quotes: dict[str, list[str]] = defaultdict(list)
    for claim in claims:
        dim = claim["dim"]
        by_dim[dim].append(float(claim["score"]) - SCALE_MIDPOINT)
        votes[dim][claim["sentence_index"]] += 1
        if claim.get("quote"):
            quotes[dim].append(str(claim["quote"]))
    out: dict[str, Any] = {}
    for dim in DIMENSIONS:
        strong = [idx for idx, n in votes[dim].items() if n >= min_votes]
        if not strong:
            out[dim] = {"stated": False, "raw": 0.0, "sentences": 0, "quotes": []}
            continue
        kept = [
            float(c["score"]) - SCALE_MIDPOINT
            for c in claims
            if c["dim"] == dim and c["sentence_index"] in strong
        ]
        out[dim] = {
            "stated": True,
            "raw": statistics.mean(kept) if kept else 0.0,
            "sentences": len(strong),
            "quotes": quotes[dim][:3],
        }
    return out


def to_z(per_agent: dict[int, dict[str, Any]]) -> dict[int, dict[str, float]]:
    """Scale raw deviations to z, anchored so unstated is exactly 0.0.

    Same convention as ``calibrate_big5.to_scores``: the midpoint is the origin
    and the spread comes from the *stated* cells only, so a dimension nobody
    mentioned lands on the population mean instead of being pushed off it.
    """
    scaled: dict[int, dict[str, float]] = {}
    for dim in DIMENSIONS:
        raws = [
            v[dim]["raw"] for v in per_agent.values()
            if v[dim]["stated"] and v[dim]["raw"] is not None
        ]
        rms = math.sqrt(sum(r * r for r in raws) / len(raws)) if raws else 1.0
        rms = rms or 1.0
        for agent_id, dims in per_agent.items():
            scaled.setdefault(agent_id, {})
            scaled[agent_id][dim] = (dims[dim]["raw"] / rms) if dims[dim]["stated"] else 0.0
    return scaled


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else 0.0


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def analyse(corpus, truth, claims_by_agent, repeats) -> int:
    per_agent = {aid: aggregate(claims_by_agent.get(aid, []), repeats) for aid in corpus}
    zs = to_z(per_agent)

    written = {(a, d) for a in corpus for d in DIMENSIONS if abs(truth[a][d]) >= FLAT_Z}
    stated = {(a, d) for a in corpus for d in DIMENSIONS if per_agent[a][d]["stated"]}

    print("\n" + "=" * 68)
    print("逐句归因 · 结果")
    print("=" * 68)

    tp = len(stated & written)
    fp = len(stated - written)
    precision = tp / len(stated) if stated else 0.0
    recall = tp / len(written) if written else 0.0
    print(f"\n【判有证据】{len(stated)} 格（真写了 {len(written)} 格）")
    print(f"  真的写了 {tp}，凭空 {fp}")
    print(f"  精确率 {precision:.0%}（判据 ≥ {CRITERIA['precision_min']:.0%}，一次性打分器 68%）")
    print(f"  召回率 {recall:.0%}（判据 ≥ {CRITERIA['recall_min']:.0%}）")

    xs = [truth[a][d] for a, d in sorted(written)]
    ys = [zs[a][d] for a, d in sorted(written)]
    r = pearson(xs, ys)
    print(f"\n【刻意写了的 {len(written)} 格】r = {r:.3f}"
          f"（判据 ≥ {CRITERIA['r_written_min']}，一次性打分器 0.79）")
    print(f"  {'维度':>4} {'n':>4} {'r':>8} {'偏移':>8}")
    worst_bias = 0.0
    for dim in DIMENSIONS:
        cells = [a for a in corpus if (a, dim) in written]
        if len(cells) < 5:
            continue
        dr = pearson([truth[a][dim] for a in cells], [zs[a][dim] for a in cells])
        bias = statistics.mean([zs[a][dim] - truth[a][dim] for a in cells])
        worst_bias = max(worst_bias, abs(bias))
        print(f"  {dim:>4} {len(cells):>4} {dr:>+8.3f} {bias:>+8.3f}")

    checks = [
        ("主判据 r", r >= CRITERIA["r_written_min"]),
        ("精确率", precision >= CRITERIA["precision_min"]),
        ("召回率", recall >= CRITERIA["recall_min"]),
        ("最大偏移", worst_bias <= CRITERIA["bias_max"]),
    ]
    print("\n" + "-" * 68)
    for name, ok in checks:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print("-" * 68)
    if all(ok for _, ok in checks):
        print("逐句归因通过：可以把导入路径切到它上面。")
    else:
        print("未全部通过。**不要**据此切换导入路径；把没过的那条写进提案再谈。")
    return 0


# --------------------------------------------------------------------------
# Zero-cost checks
# --------------------------------------------------------------------------

def dry_run(corpus, truth, args) -> int:
    counts = [len(v) for v in corpus.values()]
    print("=" * 68)
    print("逐句归因 · 预演（零调用）")
    print("=" * 68)
    print(f"  居民 {len(corpus)}，句子合计 {sum(counts)}"
          f"（中位 {statistics.median(counts):.0f}，min {min(counts)}，max {max(counts)}）")
    print(f"  调用数 = {sum(counts)} × {args.repeats} = **{sum(counts) * args.repeats}**"
          f"（一次性打分器 765）")

    thin = sorted(a for a, s in corpus.items() if len(s) <= 2)
    print(f"\n  只有 1-2 句的居民 {len(thin)} 位：{thin}")
    print("  对他们逐句 ≈ 整段，串味风险照旧——结果里会单独标出来（提案 D3）。")

    written = {(a, d) for a in corpus for d in DIMENSIONS if abs(truth[a][d]) >= FLAT_Z}
    print(f"\n  真值：刻意写了 {len(written)} 格，未写 {len(corpus) * 5 - len(written)} 格")
    print(f"  上限：即便归因完美，精确率也受限于「一句话确实能说明几个维度」——")
    print(f"  生成器平均每人写 {len(written) / len(corpus):.1f} 个维度，"
          f"而每人平均 {statistics.mean(counts):.1f} 句。")
    print("\n下一步：--self-test 验读数链路，再去掉 --dry-run。")
    return 0


def _fake_llm(corpus, truth, leak: float, seed: int):
    """A scorer that reads the sentence it is given, and (optionally) bleeds.

    ``leak`` is the probability of also claiming a dimension the generator never
    wrote — i.e. exactly the defect being measured. leak=0 is the ideal scorer;
    leak=0.5 reproduces something like today's behaviour. If the harness cannot
    tell those apart it cannot judge the real run either.
    """
    def _call(prompt, task=None, agent_id=None, provider=None):
        match = re.search(r"这句话：\n(.+?)\n", prompt, re.S)
        sentence = match.group(1).strip() if match else ""
        aid = next((a for a, ss in corpus.items() if any(s == sentence for s in ss)), None)
        digest = hashlib.blake2b(f"{seed}|{aid}|{sentence}".encode(), digest_size=8).digest()
        rng = random.Random(int.from_bytes(digest, "big"))
        dims = []
        if aid is not None:
            real = [d for d in DIMENSIONS if abs(truth[aid][d]) >= FLAT_Z]
            # A clean scorer sees a dimension in a sentence often but not
            # always -- the first draft of this fake picked exactly one real
            # dimension per sentence, which capped recall below the criterion
            # in the *positive* control and would have made a passing method
            # look like a failing one.
            for dim in real:
                if rng.random() < HIT_RATE:
                    z = truth[aid][dim]
                    score = max(1, min(7, round(SCALE_MIDPOINT + z * 1.2)))
                    dims.append({"dim": dim, "score": score, "quote": sentence[:12]})
            for dim in DIMENSIONS:
                if dim not in real and rng.random() < leak:
                    dims.append({"dim": dim, "score": rng.choice([2, 3, 5, 6]),
                                 "quote": sentence[:12]})
        return json.dumps({"dims": dims}, ensure_ascii=False)
    return _call


def self_test(corpus, truth, args) -> int:
    print("=" * 68)
    print("逐句归因 · 自检（假打分器，零调用）")
    print("=" * 68)
    ok = True
    for label, leak, expect_precision in (
        ("正对照：干净的打分器（leak=0）", 0.0, True),
        ("负对照：串味的打分器（leak=0.5）", 0.5, False),
    ):
        print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")
        fake = _fake_llm(corpus, truth, leak, args.seed)
        claims = defaultdict(list)
        for aid, sentences in corpus.items():
            for idx, sentence in enumerate(sentences):
                for _ in range(args.repeats):
                    parsed = json.loads(fake(PROMPT.format(sentence=sentence, anchors="")))
                    for entry in parsed.get("dims", []):
                        claims[aid].append({**entry, "sentence_index": idx})
        analyse(corpus, truth, claims, args.repeats)
        per_agent = {a: aggregate(claims.get(a, []), args.repeats) for a in corpus}
        written = {(a, d) for a in corpus for d in DIMENSIONS if abs(truth[a][d]) >= FLAT_Z}
        stated = {(a, d) for a in corpus for d in DIMENSIONS if per_agent[a][d]["stated"]}
        precision = len(stated & written) / len(stated) if stated else 0.0
        passed = precision >= CRITERIA["precision_min"]
        verdict = "符合预期" if passed == expect_precision else "**不符合预期**"
        print(f"\n>> 自检判定：精确率 {precision:.0%} → "
              f"{'PASS' if passed else 'FAIL'}，{verdict}")
        ok = ok and (passed == expect_precision)
    print("\n" + "=" * 68)
    print("自检通过：干净的打分器能过判据，串味的过不了。"
          if ok else "自检未通过——这个 harness 判不了真跑的结果，不要拿它去花钱。")
    return 0 if ok else 1


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/hangzhou_profiles_with_names.md")
    parser.add_argument("--truth", default="data/agents_big5.csv")
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--analyse-only", action="store_true")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    truth = load_truth(args.truth)
    if not corpus:
        print("语料里没有「人格与行为倾向」段落——检查 --corpus")
        return 1

    print("预先写死的判据（跑之前印出来，跑完不许改）：")
    print(f"  刻意写了的格子 r ≥ {CRITERIA['r_written_min']}（一次性打分器 0.79）")
    print(f"  stated 精确率 ≥ {CRITERIA['precision_min']:.0%}（现状 68%）")
    print(f"  真信号召回 ≥ {CRITERIA['recall_min']:.0%}")
    print(f"  每维系统偏移 |bias| ≤ {CRITERIA['bias_max']}"
          f"（现状 A +0.39 / O −0.33 / N −0.29）\n")

    if args.self_test:
        return self_test(corpus, truth, args)
    if args.dry_run:
        return dry_run(corpus, truth, args)

    done: dict[tuple[int, int, int], str] = {}
    if (args.resume or args.analyse_only) and os.path.exists(args.checkpoint):
        for line in open(args.checkpoint, encoding="utf-8"):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            done[(row["agent"], row["sentence_index"], row["rep"])] = row["response"]

    if not args.analyse_only:
        from gaworld.core.runner import parallel_map
        from gaworld.llm.providers import call_llm

        anchors = build_anchor_text()
        jobs = [
            (aid, idx, rep, PROMPT.format(sentence=sentence, anchors=anchors))
            for aid, sentences in corpus.items()
            for idx, sentence in enumerate(sentences)
            for rep in range(args.repeats)
            if (aid, idx, rep) not in done
        ]
        print(f"待跑 {len(jobs)} 次调用（断点已有 {len(done)} 条）")
        os.makedirs(os.path.dirname(args.checkpoint) or ".", exist_ok=True)
        handle = open(args.checkpoint, "a", encoding="utf-8")

        def _one(job):
            aid, idx, rep, prompt = job
            try:
                return (aid, idx, rep, str(call_llm(prompt, task="big5_sentence",
                                                    agent_id=aid)), "")
            except Exception as exc:  # noqa: BLE001
                return (aid, idx, rep, "", str(exc))

        errors = 0
        for aid, idx, rep, response, error in parallel_map(
                _one, jobs, max_workers=args.workers, label="by-sentence"):
            if error:
                errors += 1
                continue
            done[(aid, idx, rep)] = response
            handle.write(json.dumps({"agent": aid, "sentence_index": idx, "rep": rep,
                                     "response": response}, ensure_ascii=False) + "\n")
        handle.close()
        if errors:
            print(f"WARNING: {errors} 次调用失败（--resume 可续跑）")

    claims: dict[int, list[dict[str, Any]]] = defaultdict(list)
    unparsed = 0
    for (aid, idx, _rep), response in done.items():
        start, end = response.find("{"), response.rfind("}")
        parsed = None
        if start >= 0 and end > start:
            try:
                parsed = json.loads(response[start:end + 1])
            except (ValueError, TypeError):
                parsed = None
        if not isinstance(parsed, dict):
            unparsed += 1
            continue
        for entry in parsed.get("dims") or []:
            if isinstance(entry, dict) and entry.get("dim") in DIMENSIONS:
                claims[aid].append({
                    "dim": entry["dim"],
                    "score": entry.get("score", SCALE_MIDPOINT),
                    "quote": entry.get("quote", ""),
                    "sentence_index": idx,
                })
    if unparsed:
        print(f"解析失败 {unparsed} / {len(done)}")
    return analyse(corpus, truth, claims, args.repeats)


if __name__ == "__main__":
    raise SystemExit(main())
