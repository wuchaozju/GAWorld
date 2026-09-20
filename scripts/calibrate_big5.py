"""Calibrate OCEAN z scores for the Hangzhou residents, once, offline.

Reads the narrative ``**性格与情绪特征**`` paragraph (plus 日常生活 and 价值观
for context) out of ``data/hangzhou_profiles_with_names.md`` and writes
``data/agents_big5.csv``. The simulator never runs this: 51 residents x 5
dimensions x 3 repeats is ~765 LLM calls, and re-scoring at boot would both
cost that every run and make two runs of the same seed disagree.

Four choices here exist to keep the scores from being an elaborate restatement
of what the profile already says:

**One dimension per call.** Asking for all five at once produces halo — a
profile that reads "positive" scores high on everything. Each call sees the
profile and one dimension's anchors, and never sees the other four scores.

**Three independent repeats, median.** Single-shot LLM ratings are noisy at
the +-1 point level; the median of three is stable without pretending to more
precision than the source text supports. The per-call raw scores are kept in
the audit CSV so a suspicious median can be traced.

**A 1-7 rating, not a z score.** Models are poor at producing calibrated
standard scores directly and good at picking a point between two described
anchors. The rating is converted here.

**"Not stated" is explicit, and lands on exactly zero.** A profile that says
nothing about Openness must be able to say so rather than being pushed to the
midpoint by default. This is also why the conversion is anchored on the scale
midpoint rather than on the sample mean: the prompt *defines* 4 as "neither
pole is evident", so 4 is a known neutral point, not something to be estimated
from a sample that is mostly non-responses. Centring on the sample mean instead
turns "we do not know" into a small non-zero score — which then feeds the
decision loop and renders anchor sentences, i.e. the simulation asserting a
trait the source text never claimed. Scores are scaled by the spread of the
*stated* ratings, so the residents the profiles actually describe keep their
relative distance from each other.

Usage::

    python scripts/calibrate_big5.py --dry-run     # prompts + coverage, no LLM
    python scripts/calibrate_big5.py               # ~765 calls, writes the CSV
    python scripts/calibrate_big5.py --review      # print the N/E rows for manual check
    python scripts/calibrate_big5.py --from-audit output/traits/calibration_audit.csv
                                                   # re-derive the CSV from a previous
                                                   # run's raw scores, no LLM
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gaworld.personality.traits import DIMENSION_NAMES_ZH, DIMENSIONS, Z_CLIP
from gaworld.settings import CONFIG
from gaworld.sim.agents_loader import parse_profile

#: ``dimension -> (low anchor, high anchor)``. Written as observable behaviour,
#: not as the trait's name, because the profiles describe what people do.
ANCHOR_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "o": (
        "只走熟悉的路线、认准的做法很少改、对没试过的东西没兴趣",
        "主动找新鲜事物、爱试没试过的做法、对陌生领域好奇",
    ),
    "c": (
        "计划容易落空、事情往后拖、桌面和日程都比较乱",
        "提前排好顺序、说到做到、被打断也会补回来",
    ),
    "e": (
        "回避热闹场合、独处恢复精力、社交后会累",
        "主动搭话、喜欢有人的场合、独处久了会闷",
    ),
    "a": (
        "说话直接、有分歧当场讲、不太迁就别人",
        "先替别人考虑、难以拒绝、遇到分歧先让一步",
    ),
    "n": (
        "情绪很稳、出了岔子照常吃睡、别人急他不急",
        "容易往坏处想、一件小事影响一整天、情绪起落大",
    ),
}

PROMPT = """你在为一项社会仿真研究做人格编码。下面是一位虚构居民的人物设定片段。

人物设定：
{profile}

请只评估一个维度：{dim_zh}。

评分锚点（1-7 分）：
1 分 = {low}
7 分 = {high}
4 分 = 两端都不明显，或材料中看不出来

要求：
- 只依据上面的材料，不要脑补材料里没有的信息。
- 如果材料完全没有涉及这个维度，把 stated 设为 false，score 仍填 4。
- 不要考虑这个人是否讨人喜欢、是否成功——只判断上面这一个维度。

输出严格的 JSON，不要任何其他文字：
{{"score": <1-7 的整数>, "stated": <true 或 false>, "evidence": "<材料中支持你打分的原话，20 字以内>"}}"""

REPEATS = 3


def load_profiles(md_path: str, agent_ids: list[int]) -> dict[int, dict]:
    with open(md_path, encoding="utf-8") as handle:
        text = handle.read()
    out: dict[int, dict] = {}
    for agent_id in agent_ids:
        match = re.search(rf"## Profile {agent_id:02d}｜.*?(?=\n## Profile |\Z)", text, re.S)
        if not match:
            continue
        block = match.group(0)
        parsed = parse_profile(block)
        # Mirror gaworld.personality.anchors.personality_line: when the corpus
        # has an authored 人格与行为倾向 paragraph, that IS the personality
        # material and the legacy label is not shown alongside it.
        #
        # Scoring the paragraph *alone* is deliberate. 日常生活 and 价值观 were
        # included back when the personality line was a 20-character label and
        # every scrap of text helped; now they would drag the old authorial
        # intent — the same intent that produced the state variables — back into
        # a measurement whose entire purpose is to be independent of it.
        tendencies = str(parsed.get("behavior_tendencies", "") or "").strip()
        if tendencies:
            parsed["_context"] = f"人格与行为倾向：{tendencies}"
        else:
            parsed["_context"] = "\n".join(filter(None, [
                f"性格与情绪特征：{parsed.get('personality', '')}",
                f"日常生活与生活习惯：{parsed.get('daily_life', '')}",
                f"价值观与公共事务态度：{parsed.get('values', '')}",
            ]))
        out[agent_id] = parsed
    return out


def build_prompt(profile: dict, dim: str) -> str:
    low, high = ANCHOR_DESCRIPTIONS[dim]
    return PROMPT.format(
        profile=profile["_context"], dim_zh=DIMENSION_NAMES_ZH[dim], low=low, high=high
    )


def parse_rating(text: str) -> tuple[float | None, bool, str]:
    match = re.search(r"\{.*\}", str(text or ""), re.S)
    if not match:
        return None, False, ""
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, False, ""
    try:
        score = float(payload.get("score"))
    except (TypeError, ValueError):
        return None, False, ""
    if not 1.0 <= score <= 7.0:
        return None, False, ""
    return score, bool(payload.get("stated", True)), str(payload.get("evidence", ""))[:40]


#: The prompt's own definition of "neither pole is evident". Used as the
#: neutral point instead of the sample mean — see the module docstring.
SCALE_MIDPOINT = 4.0


def to_scores(
    raw: dict[int, dict[str, float]],
    stated: dict[int, dict[str, bool]],
) -> dict[int, dict[str, float]]:
    """Turn 1-7 ratings into signed scores centred on the scale midpoint.

    An unstated dimension yields exactly ``0.0``, which is the whole point:
    downstream, zero means "no personality signal" and is treated as the
    identity by every channel, so a resident the profiles never describe on
    some dimension is never *told* they are anything on it.

    The scale is the RMS deviation of the stated ratings from the midpoint,
    not the population SD. Using the population SD would let the number of
    non-responses set the spread — with 40 of 51 residents unstated on
    Agreeableness, the handful who *are* described would be squeezed towards
    the middle purely because everyone else abstained.
    """
    ids = sorted(raw)
    out: dict[int, dict[str, float]] = {i: {} for i in ids}
    for dim in DIMENSIONS:
        deviations = [raw[i][dim] - SCALE_MIDPOINT for i in ids if stated[i][dim]]
        rms = math.sqrt(sum(d * d for d in deviations) / len(deviations)) if deviations else 0.0
        for i in ids:
            if not stated[i][dim] or rms < 1e-9:
                out[i][dim] = 0.0
                continue
            score = (raw[i][dim] - SCALE_MIDPOINT) / rms
            out[i][dim] = round(max(-Z_CLIP, min(Z_CLIP, score)), 4)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--md-path", default=None, help="defaults to CONFIG['md_path']")
    parser.add_argument("--out", default="data/agents_big5.csv")
    parser.add_argument("--audit", default="output/traits/calibration_audit.csv")
    parser.add_argument("--agents", default="1-51", help="e.g. 1-51 or 3,7,9")
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--dry-run", action="store_true",
                        help="print one prompt and the profile coverage, spend nothing")
    parser.add_argument("--review", action="store_true",
                        help="print the N and E rows of an existing CSV for manual checking")
    parser.add_argument("--compare", default=None, metavar="TRUTH_CSV",
                        help="after scoring, report how well the result recovers a known score "
                             "file (the control arm: re-read what the generator wrote and see "
                             "whether an independent scorer lands on the same numbers)")
    parser.add_argument("--from-audit", default=None, metavar="PATH",
                        help="re-derive the CSV from a previous run's raw scores instead of "
                             "calling the LLM again (the audit file holds every rating)")
    args = parser.parse_args()

    agent_ids: list[int] = []
    for chunk in args.agents.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            agent_ids.extend(range(int(lo), int(hi) + 1))
        elif chunk:
            agent_ids.append(int(chunk))

    if args.compare and os.path.abspath(args.compare) == os.path.abspath(args.out):
        print(f"--compare 的对象就是 --out 要覆盖的文件（{args.out}）。\n"
              "把 --out 指到别处，例如 output/traits/recalibrated.csv。", file=sys.stderr)
        return 1

    md_path = args.md_path or CONFIG.get("md_path", "data/hangzhou_profiles_with_names.md")
    profiles = load_profiles(md_path, agent_ids)
    if not profiles:
        print(f"no profiles parsed from {md_path}", file=sys.stderr)
        return 1

    if args.review:
        return review(args.out)

    if args.dry_run:
        first = min(profiles)
        print(f"parsed {len(profiles)} profiles from {md_path}")
        print(f"planned calls: {len(profiles)} x {len(DIMENSIONS)} x {args.repeats} = "
              f"{len(profiles) * len(DIMENSIONS) * args.repeats}\n")
        print(f"--- example prompt (agent {first}, 外向性) ---")
        print(build_prompt(profiles[first], "e"))
        missing = [i for i, p in profiles.items() if not p.get("personality")]
        if missing:
            print(f"\nWARNING: no 性格与情绪特征 paragraph for agents {missing}")
        return 0

    if args.from_audit:
        raw, stated = read_audit(args.from_audit)
        if not raw:
            print(f"no usable rows in {args.from_audit}", file=sys.stderr)
            return 1
        write_scores(args.out, raw, stated, profiles)
        return 0

    from gaworld.llm.providers import call_llm

    raw: dict[int, dict[str, float]] = {}
    stated: dict[int, dict[str, bool]] = {}
    audit_rows: list[list] = []
    for agent_id in sorted(profiles):
        profile = profiles[agent_id]
        raw[agent_id] = {}
        stated[agent_id] = {}
        for dim in DIMENSIONS:
            prompt = build_prompt(profile, dim)
            scores: list[float] = []
            stated_flags: list[bool] = []
            for repeat in range(args.repeats):
                reply = call_llm(prompt, task="big5_calibration", agent_id=agent_id)
                score, said, evidence = parse_rating(reply)
                audit_rows.append([agent_id, profile.get("name", ""), dim, repeat,
                                   "" if score is None else score, said, evidence])
                if score is not None:
                    scores.append(score)
                    stated_flags.append(said)
            if not scores:
                print(f"  agent {agent_id} {dim}: no parseable rating, treating as unstated",
                      file=sys.stderr)
                scores = [SCALE_MIDPOINT]
                stated_flags = [False]
            raw[agent_id][dim] = statistics.median(scores)
            stated[agent_id][dim] = any(stated_flags)
        print(f"agent {agent_id:>2} {profile.get('name', ''):<10} "
              + "  ".join(f"{d.upper()}={raw[agent_id][d]:.1f}" for d in DIMENSIONS))

    os.makedirs(os.path.dirname(args.audit) or ".", exist_ok=True)
    with open(args.audit, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "name", "dim", "repeat", "score", "stated", "evidence"])
        writer.writerows(audit_rows)
    print(f"wrote {args.audit}")

    write_scores(args.out, raw, stated, profiles)
    if args.compare:
        compare_against(args.out, args.compare)
    else:
        print("next: python scripts/calibrate_big5.py --review              # manual pass over N and E")
        print("      python scripts/big5_collinearity.py --annotate       # required: fills `redundant`")
    return 0


def read_audit(path: str):
    """Rebuild the per-agent medians and stated flags from an audit CSV.

    Every rating the model produced is already on disk, so re-deriving the
    scores after a change to :func:`to_scores` costs nothing and cannot drift
    from what was actually asked.
    """
    scores: dict[int, dict[str, list[float]]] = {}
    flags: dict[int, dict[str, list[bool]]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                agent_id = int(str(row.get("id", "")).strip())
                value = float(row.get("score") or "")
            except (TypeError, ValueError):
                continue
            dim = str(row.get("dim", "")).strip()
            if dim not in DIMENSIONS:
                continue
            scores.setdefault(agent_id, {}).setdefault(dim, []).append(value)
            flags.setdefault(agent_id, {}).setdefault(dim, []).append(
                str(row.get("stated", "")).strip().lower() == "true"
            )
    raw: dict[int, dict[str, float]] = {}
    stated: dict[int, dict[str, bool]] = {}
    for agent_id, per_dim in scores.items():
        raw[agent_id] = {}
        stated[agent_id] = {}
        for dim in DIMENSIONS:
            values = per_dim.get(dim) or [SCALE_MIDPOINT]
            raw[agent_id][dim] = statistics.median(values)
            stated[agent_id][dim] = any(flags.get(agent_id, {}).get(dim) or [False])
    return raw, stated


def write_scores(out_path, raw, stated, profiles) -> None:
    """Convert, write the CSV, and report how much of it is actually evidenced."""
    values = to_scores(raw, stated)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        # `redundant` is written empty on purpose: it is a property of this
        # score set versus the state variables, so it has to be recomputed by
        # scripts/big5_collinearity.py --annotate after every calibration.
        # Leaving a stale flag behind would be worse than having none.
        writer.writerow(["id", "name", *DIMENSIONS, "source", "unstated", "redundant"])
        for agent_id in sorted(values):
            missing = "|".join(d for d in DIMENSIONS if not stated[agent_id][d])
            writer.writerow([agent_id, (profiles.get(agent_id) or {}).get("name", ""),
                             *[values[agent_id][d] for d in DIMENSIONS],
                             "llm_median3", missing, ""])

    total = len(values)
    print(f"\nwrote {out_path} ({total} agents)")
    print("coverage — how many residents the profiles actually describe on each dimension:")
    for dim in DIMENSIONS:
        described = sum(1 for i in values if stated[i][dim])
        bar = "#" * round(20 * described / max(1, total))
        print(f"  {dim.upper()} {DIMENSION_NAMES_ZH[dim]:<4} {described:>2}/{total} {bar}")
    weak = [d.upper() for d in DIMENSIONS
            if sum(1 for i in values if stated[i][d]) < 0.30 * total]
    if weak:
        print(f"WARNING: {', '.join(weak)} is evidenced for under 30% of residents. "
              "Those residents sit at exactly 0 — no behavioural tilt, no anchor sentence "
              "— which is the honest reading, but it also means personality does very "
              "little on those dimensions. Fix the source profiles, not this file.")


def _read_scores(path: str) -> dict[int, dict]:
    out: dict[int, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                agent_id = int(str(row.get("id", "")).strip())
            except (TypeError, ValueError):
                continue
            values: dict = {}
            for dim in DIMENSIONS:
                try:
                    values[dim] = float(row.get(dim, 0.0) or 0.0)
                except (TypeError, ValueError):
                    values[dim] = 0.0
            values["_unstated"] = str(row.get("unstated", "") or "")
            out[agent_id] = values
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    return num / den if den > 1e-12 else 0.0


def compare_against(scored_path: str, truth_path: str) -> None:
    """The control arm: did an independent reader recover the authored score?

    This is the only check that reaches the *semantics*. The zero-cost keyword
    proxy can tell that a paragraph is about socialising; it cannot tell that
    「她说"我今晚有安排"」 is a refusal. Correlations are Pearson, which is
    scale-free — the two files use different units by construction (the scorer
    anchors on the 1-7 midpoint, the truth file is a z score) and only the
    ordering is being compared.

    Reported twice: over everyone, and over the residents whose paragraph
    actually mentions that dimension. The second is the fair number — the
    generator only writes dimensions with |z| >= 0.5, so for the rest there is
    nothing in the text to recover and both files sit near zero there.
    """
    scored, truth = _read_scores(scored_path), _read_scores(truth_path)
    ids = sorted(set(scored) & set(truth))
    if len(ids) < 10:
        print(f"只有 {len(ids)} 位居民能对上，样本太小", file=sys.stderr)
        return

    print(f"\n=== 对照臂：重标 {scored_path} vs 真值 {truth_path}（n={len(ids)}）===")
    print(f"{'维度':<8}{'全部 r':>9}{'有证据 r':>11}{'有证据数':>10}   生成时写了几人")
    print("-" * 62)
    for dim in DIMENSIONS:
        xs = [truth[i][dim] for i in ids]
        ys = [scored[i][dim] for i in ids]
        ev = [i for i in ids if dim not in scored[i]["_unstated"].split("|")]
        r_ev = (_pearson([truth[i][dim] for i in ev], [scored[i][dim] for i in ev])
                if len(ev) >= 3 else 0.0)
        written = sum(1 for i in ids if abs(truth[i][dim]) >= 0.5)
        print(f"{dim.upper()} {DIMENSION_NAMES_ZH[dim]:<5}{_pearson(xs, ys):>9.2f}"
              f"{r_ev:>11.2f}{len(ev):>10}{written:>14}")

    total_ev = sum(1 for i in ids for d in DIMENSIONS if d not in scored[i]["_unstated"].split("|"))
    total_written = sum(1 for i in ids for d in DIMENSIONS if abs(truth[i][d]) >= 0.5)
    print(f"\n打分器认为「有证据」的格子 {total_ev}，生成时实际写进去的 {total_written}。")
    print("读法：有证据 r 高 = 生成器确实把分数编码进了行为描述，且独立读者读得回来。")
    print("      全部 r 会被没写的维度稀释，本身不是失败信号。")


def review(path: str) -> int:
    """Print N and E sorted, so the two dimensions under manual review read as a ranking."""
    if not os.path.exists(path):
        print(f"{path} not found — run the calibration first", file=sys.stderr)
        return 1
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for dim in ("n", "e"):
        print(f"\n=== {DIMENSION_NAMES_ZH[dim]} ({dim.upper()}) 从高到低 ===")
        for row in sorted(rows, key=lambda r: -float(r[dim])):
            flag = " [材料未提及]" if dim in (row.get("unstated") or "") else ""
            print(f"  {float(row[dim]):+.2f}  {row['id']:>3} {row['name']}{flag}")
    print("\n改法：直接编辑 CSV 里的数字（z 分，正数偏高）。source 列改成 manual 以便日后追溯。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
