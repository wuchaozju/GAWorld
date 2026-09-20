#!/usr/bin/env python3
"""What is left for the ``prompt`` channel to do, measured without an API call.

The anchor sentences were designed when the only personality text in a decision
prompt was the hand-written ``性格与情绪特征`` line — a 20-character label that,
as the control arm showed, encodes the sampled scores at r = 0.17. Since the
corpus rewrite the prompt also carries an authored ``人格与行为倾向`` paragraph
that encodes them at r = 0.79. That changes what the anchors can claim, and the
size of the change is arithmetic, not an experiment:

* the generator writes a dimension into the paragraph when ``|z| >= FLAT_Z``
* an anchor renders for that dimension when ``|z| >= floor_z``, probabilistically

so every rendered anchor is either **covered** (the paragraph already describes
that dimension, in this person's own concrete setting, and the anchor restates
it in a sentence shared with everyone at the same pole) or **marginal** (the
paragraph is silent, and the anchor is the only place the dimension appears).

Only the marginal share can be new information. The covered share may still be
worth its tokens — repetition raises salience, and scene-specific emphasis is
what the anchors were built for — but that is a much smaller claim, and it is
the one the A4 arm has to test. This script sizes the question; it does not
answer it.

Usage::

    python scripts/big5_prompt_coverage.py [--profiles data/agents_big5.csv]
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gaworld.personality.anchors import ANCHORS, SCENES, anchor_lines  # noqa: E402
from gaworld.personality.traits import DIMENSIONS, PROMPT_DEFAULTS  # noqa: E402

#: ``scripts/author_personality.py``'s authoring floor. Imported by value rather
#: than by reference because that script is a one-shot corpus tool and importing
#: it would pull in an LLM client.
FLAT_Z = 0.5

PROMPT_SCENES = [name for name, (channel, _) in SCENES.items() if channel == "prompt"]
_LABEL_TO_DIM = {label: dim for dim, (label, _) in ANCHORS.items()}


def load_agents(path: str, knobs: dict[str, float] | None = None) -> list[dict]:
    agents = []
    for row in csv.DictReader(open(path, encoding="utf-8")):
        record = {dim: float(row[dim]) for dim in DIMENSIONS}
        record["channels"] = ["rules", "prompt", "voice"]
        if knobs:
            record["prompt"] = dict(knobs)
        agents.append({"id": int(row["id"]), "name": row["name"], "ext": {"big_five": record}})
    return agents


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default="data/agents_big5.csv")
    parser.add_argument("--floor-z", type=float, default=None,
                        help="sweep the anchor floor; default is the built-in %.2f"
                             % PROMPT_DEFAULTS["floor_z"])
    args = parser.parse_args()

    knobs = None
    if args.floor_z is not None:
        knobs = dict(PROMPT_DEFAULTS)
        knobs["floor_z"] = args.floor_z
    agents = load_agents(args.profiles, knobs)
    print(f"居民 {len(agents)} 位，prompt 场景 {len(PROMPT_SCENES)} 个"
          f"（段落写入门槛 |z| >= {FLAT_Z}，锚句门槛 |z| >= "
          f"{(knobs or PROMPT_DEFAULTS)['floor_z']}）\n")

    print("== 维度分布 ==")
    print(f"{'维度':>4} {'段落已写':>10} {'仅锚句可能写':>14} {'两者都不写':>12}")
    for dim in DIMENSIONS:
        zs = [abs(a["ext"]["big_five"][dim]) for a in agents]
        floor = (knobs or PROMPT_DEFAULTS)["floor_z"]
        print(f"{dim:>4} {sum(z >= FLAT_Z for z in zs):>10}"
              f" {sum(floor <= z < FLAT_Z for z in zs):>14}"
              f" {sum(z < floor for z in zs):>12}")

    print("\n== 锚句实际渲染 ==")
    print(f"{'场景':>9} {'维度':>7} {'有锚句的人':>11} {'条数':>6} {'重复段落':>9} {'新信息':>8}")
    total = covered = marginal = 0
    for scene in PROMPT_SCENES:
        _, dims = SCENES[scene]
        n_with = n_lines = cov = marg = 0
        for agent in agents:
            lines = anchor_lines(agent, dims, channel="prompt")
            n_with += bool(lines)
            n_lines += len(lines)
            for line in lines:
                dim = _LABEL_TO_DIM[line.split("：", 1)[0]]
                if abs(agent["ext"]["big_five"][dim]) >= FLAT_Z:
                    cov += 1
                else:
                    marg += 1
        total += n_lines
        covered += cov
        marginal += marg
        print(f"{scene:>9} {'+'.join(dims):>7} {n_with:>11} {n_lines:>6} {cov:>9} {marg:>8}")
    print(f"{'合计':>9} {'':>7} {'':>11} {total:>6} {covered:>9} {marginal:>8}")
    if total:
        print(f"\n重复占 {covered / total:.1%}，新信息占 {marginal / total:.1%}")

    print("\n== 模板多样性 ==")
    counter: Counter[str] = Counter()
    for agent in agents:
        for scene in PROMPT_SCENES:
            for line in anchor_lines(agent, SCENES[scene][1], channel="prompt"):
                counter[line] += 1
    print(f"{total} 条锚句来自 {len(counter)} 个不同句子"
          f"（模板上限 {len(ANCHORS) * 4} 句）")
    for line, count in counter.most_common(5):
        print(f"  ×{count:>3}  {line}")

    print("\n== token 成本 ==")
    lengths = [
        len("\n".join(anchor_lines(a, SCENES[s][1], channel="prompt")))
        for a in agents for s in PROMPT_SCENES
    ]
    nonzero = [n for n in lengths if n]
    print(f"锚块字符数：含空块均值 {statistics.mean(lengths):.1f}，"
          f"非空块均值 {statistics.mean(nonzero) if nonzero else 0:.1f}，"
          f"最大 {max(lengths)}")
    print(f"中文约 1 字 ≈ 1 token → 每次决策提示词平均多 ~{statistics.mean(lengths):.0f} tokens")

    print("\n== 逐人覆盖 ==")
    per = Counter(
        sum(bool(anchor_lines(a, SCENES[s][1], channel="prompt")) for s in PROMPT_SCENES)
        for a in agents
    )
    for k in sorted(per):
        print(f"  {k}/{len(PROMPT_SCENES)} 个场景有锚句：{per[k]} 人")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
