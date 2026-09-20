#!/usr/bin/env python3
"""A4 — does the anchor block change decisions *after* the paragraph already did?

The corpus rewrite made the prompt channel's original job obsolete. Anchors were
designed when the only personality text in a decision prompt was the hand-written
``性格与情绪特征`` label, which encodes the sampled scores at r = 0.17. The prompt
now also carries an authored ``人格与行为倾向`` paragraph that encodes them at
r = 0.79, written in each resident's own concrete setting. Measured without an
API call (``scripts/big5_prompt_coverage.py``), 89.8% of the 303 rendered anchor
lines restate a dimension that paragraph already covers, drawn from a pool of 20
shared sentences, at ~36 tokens per decision prompt.

So the question this script answers is not "does personality reach the model" --
that is settled -- but the much smaller one that is left:

    after the paragraph has said it in this person's own words, does one more
    sentence of *generic* pole-talk, positioned as this-decision emphasis, move
    the structured choice?

Design: a paired prompt probe, not a simulation arm. Anchors are a prompt-level
intervention, so the marginal push can be read directly, at roughly a twentieth
of what a full Track F arm costs.

Three conditions per cell, differing **only** in the anchor block (the paragraph
is present in all three, and the script asserts the prompts are otherwise
byte-identical before spending anything):

``plain``    channels.prompt off -- paragraph only
``anchor``   production behaviour -- paragraph + this scene's anchor lines
``placebo``  the same anchor lines with the *opposite* pole substituted

The placebo arm is what separates "this text did something" from "more text did
something": it holds position, length and register fixed and flips only the
claim. Without it a positive result is indistinguishable from a token-count
effect. It runs on a seeded subsample because it only has to establish a sign
reversal, not estimate one precisely.

Readout -- structured output only, never prose, and never a judgement of mine:

* phrases are tagged by ``gaworld.sim._schedule._action_style_tags``, the same
  keyword classifier ``choose_action`` itself uses at the decision site;
* direction comes from ``gaworld.personality.traits.STYLE_LOADINGS``, the same
  table that drives the rules channel.

Using the production classifier is a deliberate limit on what can be claimed and
the reason the limit is acceptable: if an anchor moves the model's wording in a
way ``_action_style_tags`` cannot see, the rules channel cannot see it either,
so it cannot reach a decision. A null here is a null *for the decision loop*,
which is the question -- it is not a claim that the prose is unchanged. That is
the ``voice`` channel's business and A3's.

Per cell, for one sampled output, with ``rendered`` the (dim, z) pairs the
anchor block actually names::

    p_s = fraction of phrases carrying style tag s
    raw_s = sum over rendered of STYLE_LOADINGS[s][dim] * z
    A     = sum over s of p_s * raw_s

and ``delta = mean_K A(anchor) - mean_K A(plain)``. The primary test is a sign
test on ``delta``, which is deliberately robust: a handful of cells with large
|z| dominate the magnitude of A but contribute one vote each.

Usage::

    python scripts/big5_prompt_ablation.py --dry-run     # costs nothing, run first
    python scripts/big5_prompt_ablation.py               # ~1.6k calls
    python scripts/big5_prompt_ablation.py --resume      # continue after a stop
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
from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gaworld.personality.anchors import ANCHORS, SCENES, anchor_lines  # noqa: E402
from gaworld.personality.traits import (  # noqa: E402
    DIMENSIONS,
    PROMPT_DEFAULTS,
    STYLE_LOADINGS,
)
from gaworld.sim._schedule import _action_style_tags  # noqa: E402

# --------------------------------------------------------------------------
# Pre-registered acceptance criteria. Printed before the first call is spent,
# and not to be edited once a run has started -- the whole point of writing
# them here is that they cannot be chosen after seeing the numbers.
# --------------------------------------------------------------------------

#: Samples per condition per cell. Raising this buys per-cell precision, which
#: is what the sign test needs; see ``--dry-run``'s power table.
K_SAMPLES = 8

#: One-sided alpha for the sign test.
ALPHA = 0.05

#: Cells in the placebo subsample.
PLACEBO_CELLS = 30

#: S-tier ceiling from ``big5_effect_ceiling.py`` / proposal section 7.3. An
#: anchor that pushes trait/behaviour correlation past this is not a success:
#: personality outranking the situation is the caricature failure mode.
CEILING_MAX_R = 0.30

#: One pre-registered (dimension -> style) pair per dimension: the style each
#: dimension loads on most heavily in ``STYLE_LOADINGS``.
#:
#: The first draft of this gate scanned every (condition, dimension, style)
#: combination and took the max |r|. The negative control caught it: on pure
#: noise the max of ~16 correlations reached 0.331 at n=33 and the gate fired
#: FAIL in a condition with, by construction, no effect at all. A maximum over
#: a scan is not an effect size, it is a multiple-comparisons artefact.
CEILING_PAIRS = {"c": "progress", "e": "social", "n": "restorative",
                 "o": "progress", "a": "social"}

#: Cells needed before a correlation is judged at all.
CEILING_MIN_N = 20

#: Scenes probed, and the production entry point whose prompt is captured.
PROBE_SCENES = ("routine", "action")

#: The dimensions this arm can actually speak about: the union of the probed
#: scenes' dimensions. ``routine`` is (c, e) and ``action`` is (c, n), so the
#: answer A4 returns is evidence about **C, E and N only**. O and A are out of
#: scope here -- they would need the ``goals`` (o, c) or ``news`` (o, n) scenes,
#: whose outputs the style classifier reads far less cleanly. Stated up front
#: rather than left to be noticed as empty rows in the results table.
PROBED_DIMS = tuple(sorted({d for s in PROBE_SCENES for d in SCENES[s][1]}))

#: Fixed for every cell, so the only thing varying between cells is the person.
PROBE_ACTIVITIES = ["工作", "午餐", "下班后", "晚上"]

#: State keys the profiles' init CSV does not carry. Constant for everyone, so
#: they add no between-cell confound, and identical across conditions, so they
#: cannot touch the paired comparison.
STATE_FILLERS = {
    "energy": 0.65, "hunger": 0.35, "social_need": 0.45,
    "fatigue_debt": 0.3, "self_control": 0.55, "time_pressure": 0.4,
}

CHECKPOINT = "output/traits/a4_samples.jsonl"


# --------------------------------------------------------------------------
# Cells
# --------------------------------------------------------------------------

def _load_states(path: str) -> dict[int, dict[str, float]]:
    import csv

    out: dict[int, dict[str, float]] = {}
    with open(path, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            state = dict(STATE_FILLERS)
            for key in ("emotion", "stress", "econ_security"):
                try:
                    state[key] = float(row[key])
                except (KeyError, TypeError, ValueError):
                    pass
            out[int(row["id"])] = state
    return out


def _load_corpus(path: str) -> dict[int, dict[str, Any]]:
    import re

    from gaworld.sim.agents_loader import parse_profile

    text = Path(path).read_text(encoding="utf-8")
    out: dict[int, dict[str, Any]] = {}
    for match in re.finditer(r"## Profile (\d+)｜.*?(?=\n## Profile |\Z)", text, re.S):
        out[int(match.group(1))] = parse_profile(match.group(0))
    return out


def build_cells(args: argparse.Namespace) -> list[dict[str, Any]]:
    """One cell per (agent, scene) where the anchor block is non-empty.

    Cells where nothing renders are excluded on purpose: with no anchor the two
    conditions are the same prompt, so including them would pad the sign test
    with guaranteed ties and understate the effect.
    """
    import csv

    corpus = _load_corpus(args.corpus)
    states = _load_states(args.states)
    cells: list[dict[str, Any]] = []
    with open(args.profiles, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            agent_id = int(row["id"])
            profile = corpus.get(agent_id, {})
            record = {dim: float(row[dim]) for dim in DIMENSIONS}
            record["channels"] = ["rules", "prompt", "voice"]
            record["prompt"] = dict(PROMPT_DEFAULTS)
            agent = {
                "id": agent_id,
                "name": row["name"],
                "age": profile.get("age", 35),
                "job": profile.get("job", ""),
                "personality": profile.get("personality", ""),
                "behavior_tendencies": profile.get("behavior_tendencies", ""),
                "daily_life": profile.get("daily_life", ""),
                "values": profile.get("values", ""),
                "state": states.get(agent_id, dict(STATE_FILLERS)),
                "episodes": [],
                "ext": {"big_five": record},
            }
            for scene in PROBE_SCENES:
                dims = SCENES[scene][1]
                lines = anchor_lines(agent, dims, channel="prompt")
                if not lines:
                    continue
                rendered = []
                for line in lines:
                    label = line.split("：", 1)[0]
                    dim = next(d for d, (lab, _) in ANCHORS.items() if lab == label)
                    rendered.append({"dim": dim, "z": record[dim], "line": line})
                cells.append({
                    "key": f"{agent_id}:{scene}",
                    "agent": agent,
                    "scene": scene,
                    "rendered": rendered,
                })
    return cells


# --------------------------------------------------------------------------
# Prompt capture
# --------------------------------------------------------------------------

class _Captured(Exception):
    def __init__(self, prompt: str) -> None:
        super().__init__("captured")
        self.prompt = prompt


def _capture(builder) -> str:
    """Run a real prompt builder and grab the string it would have sent."""

    def _stub(prompt, *a, **kw):
        raise _Captured(prompt)

    with patch("gaworld.llm.providers.call_llm", _stub), \
            patch("gaworld.cognition.realism.call_llm", _stub), \
            patch("gaworld.sim._action._llm_providers.call_llm", _stub):
        try:
            builder()
        except _Captured as captured:
            return captured.prompt
    raise RuntimeError("builder returned without calling the LLM")


def build_prompt(cell: dict[str, Any], condition: str) -> str:
    """The production prompt for this cell, under one of the three conditions.

    ``plain`` gates the channel off at the record, exactly the way the operator
    would; ``placebo`` edits the captured string, because there is no
    configuration that produces a mirrored anchor and inventing one in
    ``anchors.py`` would put a research artefact into production code.
    """
    agent = json.loads(json.dumps(cell["agent"]))  # deep copy, plain data
    if condition == "plain":
        agent["ext"]["big_five"]["channels"] = ["rules", "voice"]

    scene = cell["scene"]
    if scene == "routine":
        from gaworld.cognition import realism

        prompt = _capture(lambda: realism.build_daily_intentions(
            agent, [], {}, {"remaining": 1}, "无"))
    elif scene == "action":
        from gaworld.sim import _action

        prompt = _capture(lambda: _action._llm_generate_actions(
            agent, list(PROBE_ACTIVITIES)))
    else:
        raise ValueError(scene)

    if condition == "placebo":
        for item in cell["rendered"]:
            prompt = prompt.replace(item["line"], _flip(item), 1)
    return prompt


def _flip(item: dict[str, Any]) -> str:
    """The same anchor sentence at the opposite pole and the same strength."""
    label, poles = ANCHORS[item["dim"]]
    mild, strong = poles["low" if item["z"] > 0 else "high"]
    was_strong = item["line"] != f"{label}：{poles['high' if item['z'] > 0 else 'low'][0]}"
    return f"{label}：{strong if was_strong else mild}"


def verify_pairs(cells: list[dict[str, Any]]) -> list[str]:
    """The two conditions must differ by the anchor lines and nothing else.

    Without this the experiment is unfalsifiable: any difference elsewhere --
    a re-sampled memory hit, a timestamp, a re-ordered dict -- would be
    attributed to the anchors.
    """
    problems: list[str] = []
    for cell in cells:
        plain = build_prompt(cell, "plain")
        anchor = build_prompt(cell, "anchor")
        lines = [item["line"] for item in cell["rendered"]]
        rebuilt = anchor
        for line in lines:
            if line not in rebuilt:
                problems.append(f"{cell['key']}: anchor line missing from prompt")
                break
            rebuilt = rebuilt.replace("\n" + line, "", 1)
        if rebuilt != plain:
            problems.append(f"{cell['key']}: prompts differ beyond the anchor block")
    return problems


# --------------------------------------------------------------------------
# Readout
# --------------------------------------------------------------------------

#: Every complete JSON string literal. Used only on the salvage path below.
_JSON_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def extract_phrases(scene: str, response: str) -> list[str]:
    """Structured fields only, salvaging responses the provider truncated.

    The first version returned nothing when ``json.loads`` failed, and the real
    run lost 354 of 1632 samples that way -- 0% of the ``routine`` scene and
    **40%** of ``action``, whose prompt asks for four activities of five to ten
    actions each and runs into the provider's output cap. Every one of the 354
    was a well-formed object cut off mid-list, never an empty or malformed
    response (length 618-993, median 914, zero empties).

    Dropping them is not the neutral choice it looks like. It selects on output
    length, and length is not independent of content. Salvaging the complete
    leading entries keeps all 1632, and the recovery rate is near-identical
    across the three conditions (plain 40.1%, anchor 43.5%, placebo 41.7%), so
    it cannot manufacture a difference between them.

    This was added *after* the first analysis, which is a thing to be careful
    about, so: the acceptance criteria are untouched, the change is blind to
    outcome by construction, and both the pre-salvage and post-salvage numbers
    are reported in the proposal rather than one quietly replacing the other.
    """
    text = str(response or "")
    start = text.find("{")
    end = text.rfind("}")
    parsed: Any = None
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            parsed = None
    if not isinstance(parsed, dict):
        return _salvage_phrases(text)
    phrases: list[str] = []
    if scene == "routine":
        for key in ("priorities", "avoidances", "growth_focus"):
            value = parsed.get(key)
            if isinstance(value, list):
                phrases.extend(str(v).strip() for v in value if str(v).strip())
        for key in ("target_social", "target_recovery"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                phrases.append(value.strip())
    else:
        for value in parsed.values():
            if isinstance(value, list):
                phrases.extend(str(v).strip() for v in value if str(v).strip())
    return phrases


def _salvage_phrases(text: str) -> list[str]:
    """List elements from a truncated object: strings not followed by a colon."""
    out: list[str] = []
    for match in _JSON_STRING.finditer(text or ""):
        if text[match.end():match.end() + 4].lstrip().startswith(":"):
            continue  # a key, not a value
        value = match.group(1).strip()
        if value:
            out.append(value)
    return out


def alignment(phrases: list[str], rendered: list[dict[str, Any]]) -> float | None:
    """``sum_s p_s * raw_s`` -- None when there was nothing to classify."""
    if not phrases:
        return None
    counts: Counter[str] = Counter()
    for phrase in phrases:
        for tag in _action_style_tags(phrase):
            counts[tag] += 1
    total = float(len(phrases))
    score = 0.0
    for style, loadings in STYLE_LOADINGS.items():
        raw = sum(loadings.get(item["dim"], 0.0) * item["z"] for item in rendered)
        if raw:
            score += (counts.get(style, 0) / total) * raw
    return score


def style_proportions(phrases: list[str]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for phrase in phrases:
        for tag in _action_style_tags(phrase):
            counts[tag] += 1
    total = float(len(phrases)) or 1.0
    return {style: counts.get(style, 0) / total for style in STYLE_LOADINGS}


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

def sign_test_threshold(n: int, alpha: float = ALPHA) -> int:
    """Smallest k with P(X >= k | Binomial(n, 0.5)) <= alpha. Exact, not normal."""
    if n <= 0:
        return 0
    for k in range(n, -1, -1):
        tail = sum(math.comb(n, i) for i in range(k, n + 1)) / (2.0 ** n)
        if tail > alpha:
            return k + 1
    return 0


def binom_tail(k: int, n: int) -> float:
    if n <= 0:
        return 1.0
    return sum(math.comb(n, i) for i in range(k, n + 1)) / (2.0 ** n)


def fisher_lower_bound(r: float, n: int, alpha: float = ALPHA) -> float:
    """One-sided lower confidence bound on |r|.

    The gate asks whether the effect *exceeds* the band, so a point estimate is
    the wrong instrument: at these sample sizes it crosses 0.30 on noise alone.
    Failing only when the lower bound clears the band means the run has to show
    the excess, not merely fail to rule it out.
    """
    r = abs(r)
    if n < 4 or r >= 1.0:
        return r
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    critical = 1.645 if abs(alpha - 0.05) < 1e-9 else 1.96
    return max(0.0, math.tanh(z - critical * se))


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else 0.0


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def load_checkpoint(path: str) -> dict[tuple[str, str, int], str]:
    done: dict[tuple[str, str, int], str] = {}
    if not os.path.exists(path):
        return done
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            done[(row["key"], row["condition"], row["rep"])] = row["response"]
    return done


def run_samples(cells, args, done):
    from gaworld.core.runner import parallel_map
    from gaworld.llm.providers import call_llm

    rng = random.Random(args.seed)
    placebo_keys = set()
    if len(cells) > PLACEBO_CELLS:
        placebo_keys = {c["key"] for c in rng.sample(cells, PLACEBO_CELLS)}
    else:
        placebo_keys = {c["key"] for c in cells}

    jobs = []
    for cell in cells:
        conditions = ["plain", "anchor"]
        if cell["key"] in placebo_keys:
            conditions.append("placebo")
        for condition in conditions:
            prompt = build_prompt(cell, condition)
            for rep in range(args.k):
                if (cell["key"], condition, rep) in done:
                    continue
                jobs.append((cell, condition, rep, prompt))

    print(f"待跑 {len(jobs)} 次调用"
          f"（已有断点 {len(done)} 条，placebo 子样本 {len(placebo_keys)} 格）")
    if not jobs:
        return done

    handle = open(args.checkpoint, "a", encoding="utf-8")

    def _one(job):
        cell, condition, rep, prompt = job
        try:
            response = call_llm(prompt, task="a4_ablation", agent_id=cell["agent"]["id"])
        except Exception as exc:  # noqa: BLE001 -- one bad call must not kill 1.6k
            return (cell["key"], condition, rep, "", str(exc))
        return (cell["key"], condition, rep, str(response), "")

    results = parallel_map(_one, jobs, max_workers=args.workers, label="a4")
    errors = 0
    for key, condition, rep, response, error in results:
        if error:
            errors += 1
            continue
        done[(key, condition, rep)] = response
        handle.write(json.dumps(
            {"key": key, "condition": condition, "rep": rep, "response": response},
            ensure_ascii=False) + "\n")
    handle.close()
    if errors:
        print(f"WARNING: {errors} 次调用失败（已跳过，--resume 可续跑）")
    return done


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def analyse(cells, done, args) -> int:
    by_key = {cell["key"]: cell for cell in cells}
    deltas: dict[str, dict[str, float]] = {}
    unparsed = 0
    total = 0
    for cell in cells:
        means: dict[str, float] = {}
        for condition in ("plain", "anchor", "placebo"):
            scores = []
            for rep in range(args.k):
                response = done.get((cell["key"], condition, rep))
                if response is None:
                    continue
                total += 1
                phrases = extract_phrases(cell["scene"], response)
                if not phrases:
                    unparsed += 1
                    continue
                value = alignment(phrases, cell["rendered"])
                if value is not None:
                    scores.append(value)
            if scores:
                means[condition] = statistics.mean(scores)
        if "plain" in means and "anchor" in means:
            entry = {"delta": means["anchor"] - means["plain"]}
            if "placebo" in means:
                entry["placebo"] = means["placebo"] - means["plain"]
            deltas[cell["key"]] = entry

    print("\n" + "=" * 68)
    print("A4 结果")
    print("=" * 68)
    if total:
        print(f"样本 {total} 条，其中结构化解析失败 {unparsed} 条（{unparsed / total:.1%}）")
    print(f"可比对的格子 {len(deltas)} / {len(cells)}")

    verdicts = []

    # -- primary: sign test ------------------------------------------------
    print("\n【主判据】结构化选择朝锚句方向移动")
    values = [d["delta"] for d in deltas.values()]
    ties = sum(1 for v in values if v == 0.0)
    effective = [v for v in values if v != 0.0]
    n = len(effective)
    k = sum(1 for v in effective if v > 0)
    threshold = sign_test_threshold(n)
    p_value = binom_tail(k, n)
    print(f"  同向 {k} / {n}（平局 {ties} 格已剔除），"
          f"单侧符号检验判据 k >= {threshold}，p = {p_value:.4f}")
    if effective:
        print(f"  delta 中位数 {statistics.median(effective):+.4f}，"
              f"均值 {statistics.mean(effective):+.4f}")
    primary = k >= threshold
    verdicts.append(("主判据", primary))
    print(f"  → {'达标' if primary else '未达标'}")

    # -- ceiling -----------------------------------------------------------
    print(f"\n【上限判据】效应量不得超过 S 档带宽 |r| <= {CEILING_MAX_R}")
    print(f"  逐维度看预先指定的主载荷配对，n >= {CEILING_MIN_N} 才判，"
          f"且只在单侧 95% 下界越界时才算超出")
    print(f"  本臂覆盖的维度：{'/'.join(d.upper() for d in PROBED_DIMS)}"
          f"（routine=c,e + action=c,n）。O 与 A 不在本臂范围内。")
    print(f"  {'维度':>4} {'配对':>18} {'n':>4} {'plain r':>9} "
          f"{'anchor r':>10} {'下界':>7}")
    ceiling = True
    for dim in PROBED_DIMS:
        style = CEILING_PAIRS[dim]
        row = {}
        n_cells = 0
        for condition in ("plain", "anchor"):
            xs, ys = [], []
            for cell in cells:
                if not any(item["dim"] == dim for item in cell["rendered"]):
                    continue
                phrases: list[str] = []
                for rep in range(args.k):
                    response = done.get((cell["key"], condition, rep))
                    if response:
                        phrases.extend(extract_phrases(cell["scene"], response))
                if not phrases:
                    continue
                xs.append(cell["agent"]["ext"]["big_five"][dim])
                ys.append(style_proportions(phrases)[style])
            row[condition] = pearson(xs, ys)
            n_cells = max(n_cells, len(xs))
        bound = fisher_lower_bound(row.get("anchor", 0.0), n_cells)
        judged = n_cells >= CEILING_MIN_N
        over = judged and bound > CEILING_MAX_R
        ceiling = ceiling and not over
        mark = "  超出" if over else ("" if judged else "  n 不足，不判")
        print(f"  {dim:>4} {dim + '->' + style:>18} {n_cells:>4} "
              f"{row.get('plain', 0.0):>+9.3f} {row.get('anchor', 0.0):>+10.3f} "
              f"{bound:>7.3f}{mark}")
    verdicts.append(("上限判据", ceiling))
    print(f"  → {'达标' if ceiling else '超出：人格压过处境'}")

    # -- placebo -----------------------------------------------------------
    print("\n【判别臂】反向锚句应当把 delta 推向反面")
    placebo = [d["placebo"] for d in deltas.values() if "placebo" in d]
    p_eff = [v for v in placebo if v != 0.0]
    if p_eff:
        neg = sum(1 for v in p_eff if v < 0)
        print(f"  反向 {neg} / {len(p_eff)}，"
              f"中位数 {statistics.median(p_eff):+.4f}，"
              f"p = {binom_tail(neg, len(p_eff)):.4f}")
        discriminant = neg >= sign_test_threshold(len(p_eff))
    else:
        print("  没有可用的 placebo 样本")
        discriminant = False
    verdicts.append(("判别臂", discriminant))
    print(f"  → {'达标' if discriminant else '未达标'}")

    # -- what it means for D5 ---------------------------------------------
    print("\n" + "-" * 68)
    for name, ok in verdicts:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print("-" * 68)
    if primary and ceiling and discriminant:
        print("D5 → prompt 通道默认 **开**：场景强调有可测且不过界的边际效应。")
    elif primary and not ceiling:
        print("D5 → 先别开。有效应但超出 S 档带宽，属于人格压过处境；")
        print("     应先把 max_dims 降到 1 或抬高 render_midpoint 再测。")
    elif primary and not discriminant:
        print("D5 → 先别开。主判据过了但反向锚句没有把 delta 推回去，")
        print("     说明量到的可能是「多了一段文字」而不是「多了这段文字」。")
    else:
        print("D5 → prompt 通道默认 **关**。段落已经把分数编码进去（对照臂 r = 0.79），")
        print("     锚句 89.8% 在重复段落已写的维度、只有 20 个模板句，")
        print("     而它的边际推动在本判据下量不出来。36 tokens/次是实打实的成本。")
    return 0 if primary or True else 1


# --------------------------------------------------------------------------
# Dry run: everything that can be established without spending a call
# --------------------------------------------------------------------------

def dry_run(cells, args) -> int:
    print("=" * 68)
    print("A4 预演（零调用）")
    print("=" * 68)
    per_scene = Counter(cell["scene"] for cell in cells)
    for scene in PROBE_SCENES:
        print(f"  {scene:>8}: {per_scene[scene]} 格")
    n_cells = len(cells)
    placebo_n = min(PLACEBO_CELLS, n_cells)
    calls = n_cells * 2 * args.k + placebo_n * args.k
    print(f"  合计 {n_cells} 格 × 2 条件 × K={args.k}"
          f" + placebo {placebo_n} 格 × K={args.k} = **{calls} 次调用**")

    print("\n-- 提示词配对完整性（两版必须只差锚句）--")
    problems = verify_pairs(cells)
    if problems:
        for line in problems[:10]:
            print(f"  FAIL {line}")
        print(f"  共 {len(problems)} 处不一致 —— 不修好不能跑，"
              f"否则任何差异都会被算到锚句头上")
        return 1
    print(f"  {n_cells}/{n_cells} 格通过：两版逐字节只差锚句行")

    print("\n-- 反向锚句抽样 --")
    for cell in cells[:3]:
        for item in cell["rendered"]:
            print(f"  {cell['key']:>10} {item['dim']} z={item['z']:+.2f}")
            print(f"        正: {item['line']}")
            print(f"        反: {_flip(item)}")

    print("\n-- 判据的可检出效应量（模拟，不是预测）--")
    threshold = sign_test_threshold(n_cells)
    print(f"  n={n_cells} 时符号检验判据为 k >= {threshold}"
          f"（{threshold / n_cells:.1%}）")
    print(f"  {'真实效应 d (以单样本 sd 为单位)':>32} {'每格判对率':>10} {'检出功效':>10}")
    rng = random.Random(args.seed)
    for d in (0.0, 0.15, 0.3, 0.5, 0.8):
        hits = 0
        trials = 400
        per_cell_rate = 0.0
        for _ in range(trials):
            k = 0
            for _cell in range(n_cells):
                a = statistics.mean(rng.gauss(d, 1.0) for _ in range(args.k))
                b = statistics.mean(rng.gauss(0.0, 1.0) for _ in range(args.k))
                if a - b > 0:
                    k += 1
            per_cell_rate += k / n_cells
            hits += k >= threshold
        print(f"  {d:>32.2f} {per_cell_rate / trials:>10.1%} {hits / trials:>10.1%}")
    print("\n  读法：d 是锚句在**单次采样**尺度上的真实推动。K 越大每格越准，")
    print("  功效曲线越陡。d=0 那行是假阳率，应当在 alpha 附近。")
    print(f"\n-- 本臂能回答哪些维度 --")
    print(f"  覆盖 {'/'.join(d.upper() for d in PROBED_DIMS)}"
          f"（routine=(c,e) + action=(c,n)）；**O 与 A 不在范围内**。")
    print("  它们要靠 goals=(o,c) 或 news=(o,n)，而那两个场景的输出"
          "结构化标签读得远没有这两个干净。D5 若据此拍板，")
    print("  就是按 C/E/N 的证据拍的——这句话应当跟着结论一起写出来。")
    print("\n下一步：先跑 --self-test 确认读数链路，再去掉 --dry-run。")
    return 0


# --------------------------------------------------------------------------
# Self-test: does the readout chain detect an effect that is really there,
# and stay quiet when it is not?
# --------------------------------------------------------------------------

#: Phrases chosen so that ``_action_style_tags`` gives each exactly one tag.
#: Checked by the self-test itself rather than trusted.
_FAKE_PHRASES = {
    "progress": ["推进手头的方案", "整理这周的材料", "确认明天的安排"],
    "maintain": ["按原计划继续", "照常走例行那套", "维持现在的节奏"],
    "avoidant": ["刷手机拖延一会", "发呆放空一阵", "晚点再说"],
    "social": ["联系一个老同学", "回消息约个时间", "找人聊天"],
    "restorative": ["回家睡一觉", "午休一下", "散步半小时"],
    "quick": ["先快速过一遍", "顺手就把它带过去"],
}


def _fake_llm(strength: float, seed: int):
    """An LLM whose style mix responds to the anchor's *pole* by construction.

    Keying on the pole rather than on the agent's z is what makes the placebo
    arm meaningful: flip the sentence and the fake flips with it, exactly as a
    model that is actually reading the anchor would.
    """
    counter = {"n": 0}

    def _call(prompt, task=None, agent_id=None, provider=None):
        counter["n"] += 1
        # blake2b, not hash(): PYTHONHASHSEED randomises str hashing, and a
        # self-test whose verdict moves between runs is not a control.
        digest = hashlib.blake2b(
            f"{seed}|{agent_id}|{counter['n']}|{prompt}".encode(), digest_size=8
        ).digest()
        rng = random.Random(int.from_bytes(digest, "big"))
        raw = dict.fromkeys(STYLE_LOADINGS, 0.0)
        for dim, (label, poles) in ANCHORS.items():
            for pole, sentences in poles.items():
                for sentence in sentences:
                    if f"{label}：{sentence}" in prompt:
                        sign = 1.0 if pole == "high" else -1.0
                        for style, loadings in STYLE_LOADINGS.items():
                            raw[style] += loadings.get(dim, 0.0) * sign
        styles = list(STYLE_LOADINGS)
        weights = [math.exp(strength * raw[s]) for s in styles]
        def _draw(k):
            out = []
            for _ in range(k):
                style = rng.choices(styles, weights=weights)[0]
                out.append(rng.choice(_FAKE_PHRASES[style]))
            return out
        if "每日意图生成器" in prompt:
            return json.dumps({
                "priorities": _draw(3), "avoidances": _draw(2),
                "target_social": _draw(1)[0], "target_recovery": _draw(1)[0],
                "growth_focus": [],
            }, ensure_ascii=False)
        return json.dumps({a: _draw(6) for a in PROBE_ACTIVITIES}, ensure_ascii=False)

    return _call


def self_test(cells, args) -> int:
    """Positive and negative control on the whole chain, with no API key.

    A harness that cannot detect a planted effect proves nothing when it
    reports a null, and one that finds an effect in pure noise proves nothing
    when it reports a hit. Both directions have to be shown, and shown before
    the real run rather than as an excuse afterwards.
    """
    print("=" * 68)
    print("A4 自检（假 LLM，零调用）")
    print("=" * 68)

    print("\n-- 短语标签纯度 --")
    bad = []
    for style, phrases in _FAKE_PHRASES.items():
        for phrase in phrases:
            tags = _action_style_tags(phrase)
            if tags != {style}:
                bad.append((phrase, style, sorted(tags)))
    if bad:
        for phrase, want, got in bad:
            print(f"  FAIL {phrase!r}: 期望 {{{want}}}，实得 {got}")
        return 1
    print(f"  {sum(len(v) for v in _FAKE_PHRASES.values())} 条短语标签唯一且正确")

    ok = True
    for label, strength, expect_pass in (
        ("正对照（植入真实效应）", 0.9, True),
        ("负对照（零效应，纯噪声）", 0.0, False),
    ):
        print(f"\n{'=' * 68}\n{label}  strength={strength}\n{'=' * 68}")
        done = {}
        fake = _fake_llm(strength, args.seed)
        placebo_keys = {c["key"] for c in random.Random(args.seed).sample(
            cells, min(PLACEBO_CELLS, len(cells)))}
        for cell in cells:
            conditions = ["plain", "anchor"]
            if cell["key"] in placebo_keys:
                conditions.append("placebo")
            for condition in conditions:
                prompt = build_prompt(cell, condition)
                for rep in range(args.k):
                    done[(cell["key"], condition, rep)] = fake(
                        prompt, agent_id=cell["agent"]["id"])
        analyse(cells, done, args)
        values = [
            v for v in (
                _delta_only(cells, done, args)
            ) if v != 0.0
        ]
        k = sum(1 for v in values if v > 0)
        passed = k >= sign_test_threshold(len(values))
        verdict = "符合预期" if passed == expect_pass else "**不符合预期**"
        print(f"\n>> 自检判定：主判据 {'PASS' if passed else 'FAIL'}，{verdict}")
        ok = ok and (passed == expect_pass)

    print("\n" + "=" * 68)
    print("自检通过：读数链路既能测出植入的效应，也不会在纯噪声里造出效应。"
          if ok else "自检未通过——不要拿这个 harness 去花钱。")
    return 0 if ok else 1


def _delta_only(cells, done, args) -> list[float]:
    out = []
    for cell in cells:
        means = {}
        for condition in ("plain", "anchor"):
            scores = []
            for rep in range(args.k):
                response = done.get((cell["key"], condition, rep))
                if response is None:
                    continue
                phrases = extract_phrases(cell["scene"], response)
                value = alignment(phrases, cell["rendered"]) if phrases else None
                if value is not None:
                    scores.append(value)
            if scores:
                means[condition] = statistics.mean(scores)
        if len(means) == 2:
            out.append(means["anchor"] - means["plain"])
    return out


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", default="data/agents_big5.csv")
    parser.add_argument("--corpus", default="data/hangzhou_profiles_with_names.md")
    parser.add_argument("--states", default="data/hangzhou_agents_state_init.csv")
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--k", type=int, default=K_SAMPLES)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260821)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true",
                        help="正/负对照，用假 LLM 验证读数链路，零调用")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--analyse-only", action="store_true")
    args = parser.parse_args()

    cells = build_cells(args)
    if not cells:
        print("没有可用的格子——检查 --profiles / --corpus 路径")
        return 1

    print("预先写死的判据（跑之前印出来，跑完不许改）：")
    print(f"  主判据  符号检验单侧 alpha={ALPHA}，同向格数 >= "
          f"{sign_test_threshold(len(cells))}/{len(cells)}")
    print(f"  上限    最大 |r| <= {CEILING_MAX_R}（S 档带宽）")
    print(f"  判别臂  反向锚句需把 delta 推向反面（{PLACEBO_CELLS} 格子样本）")
    print()

    if args.self_test:
        return self_test(cells, args)
    if args.dry_run:
        return dry_run(cells, args)

    done = load_checkpoint(args.checkpoint) if (args.resume or args.analyse_only) else {}
    if not args.analyse_only:
        problems = verify_pairs(cells)
        if problems:
            print(f"提示词配对检查失败 {len(problems)} 处，拒绝开跑：")
            for line in problems[:10]:
                print(f"  {line}")
            return 1
        os.makedirs(os.path.dirname(args.checkpoint) or ".", exist_ok=True)
        done = run_samples(cells, args, done)
    return analyse(cells, done, args)


if __name__ == "__main__":
    raise SystemExit(main())
