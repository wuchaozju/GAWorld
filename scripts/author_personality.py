"""Author the personality paragraph *from* sampled OCEAN, instead of reading it back out.

``scripts/calibrate_big5.py`` runs text -> traits. On this corpus that direction
fails: the 性格与情绪特征 paragraphs are one-line labels (median 20 characters),
and the five person-level state variables sitting a few lines below them in the
same profile are the *same* authorial judgement written as numbers. Scoring the
prose therefore recovers the numbers — Openness correlated +0.90 with
``mobility_intent`` — and the collinearity gate rightly rejected it. Making the
paragraphs longer does not help; whoever writes them is looking at the same
person and will write the same thing at greater length.

So this script runs traits -> text:

1. **Sample** OCEAN for the whole population, independent of the state
   variables except for two deliberately retained links (see ``TILTS``).
   Independence is now a property of the sampler rather than something to be
   hoped for and measured afterwards.
2. **Generate** a behavioural paragraph that conveys those five scores, given
   the profile's immutable facts. The target behaviours come from
   ``gaworld.personality.anchors.ANCHORS`` — the very sentences the runtime
   prompt channel uses — so the profile text and the in-run anchors cannot
   drift apart.
3. **Check** each paragraph against the immutable facts in a *separate* call.
   Self-checking inside the generating call finds nothing.

Sampling covers the whole population on every run, and each agent draws from
its own stream, so ``--agents 1-5`` produces exactly the scores agent 1-5 will
have in the full run. The pilot is representative, not a rehearsal.

Usage::

    python scripts/author_personality.py --agents 1-5 --dry-run   # prompts + sampled scores, no LLM
    python scripts/author_personality.py --agents 1-5             # pilot -> output/traits/authored_preview.md
    python scripts/author_personality.py --apply                  # all 51: rewrites the profile md + the CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gaworld.personality.anchors import ANCHORS
from gaworld.personality.plugin import cholesky, correlation_matrix, rescale, sample_traits
from gaworld.personality.traits import DIMENSION_NAMES_ZH, DIMENSIONS, Z_CLIP
from gaworld.settings import CONFIG

#: ``dimension -> (state variable, target correlation)``. Only two entries,
#: because only two have a defensible basis: Openness tracks sensation seeking
#: and Extraversion tracks assertiveness, both around r = 0.3 in the
#: literature. There is no comparable published link between Conscientiousness,
#: Agreeableness or Neuroticism and *these particular* five variables, so those
#: three are sampled independently rather than given an invented one.
#:
#: Retaining a real correlation is deliberate: forcing personality to be
#: strictly orthogonal to risk preference would be less realistic than the
#: overlap it replaces. Measured headroom (n=51, adjusted R^2, gate fails at
#: 0.50): r=0.3 -> median 0.08 / p95 0.27; r=0.5 -> median 0.24 / p95 0.44.
TILTS: dict[str, tuple[str, float]] = {
    "o": ("risk_preference", 0.30),
    "e": ("voice_propensity", 0.30),
}

#: Dimensions below this |z| are left out of the paragraph entirely.
#:
#: The earlier draft required all five to be written, including a sentence
#: saying the resident is unremarkable on the flat ones. That requirement came
#: from the old text -> traits direction, where silence meant "unknown" and
#: produced the coverage hole. It does not transfer: the scores are sampled and
#: frozen in the CSV, so coverage is 100% by construction and the prose is
#: downstream of it. Writing 「他在这方面不偏不倚」 for a z of −0.10 adds words
#: and no information — and in the third pilot that padding was roughly a third
#: of every paragraph's length.
#:
#: It also aligns the profile text with the runtime anchors, which already skip
#: undistinctive dimensions (``anchors.floor_z``) for the same reason.
#:
#: At 0.5 the population averages 3.0 written dimensions (range 1–5, never 0).
FLAT_Z = 0.5

#: Above this |z| the stronger of the two anchor sentences is the target.
STRONG_Z = 1.5

IMMUTABLE_FIELDS = [
    ("name", "姓名"), ("age", "年龄"), ("job", "职业与工作节奏"),
    ("living", "居住"), ("daily_life", "日常生活与生活习惯"),
    ("values", "价值观与公共事务态度"),
]

GENERATE_PROMPT = """你在为一项社会仿真研究撰写人物设定的一个新段落。

## 这个人已经确定的事实（不可更改，你的段落不能与之矛盾）

{facts}

## 这个段落必须传达的 {count} 条行为倾向

（下面用第二人称写成，「你」指的就是上面这个人。你要改写成第三人称的
自然描述，不是逐条翻译。）

{targets}

## 要求

1. **写可观测的行为，不写标签。** 不许出现「开放性」「尽责性」「外向」「内向」「神经质」
   「宜人」这类词，也不许出现任何分数。要写的是旁人能看见的具体动作、场合、口头禅
   ——放在这个人自己的生活场景里（他的职业、他常去的地方、他会遇到的人）。
2. **不要照抄这份提示词里的任何措辞。** 上面那几条是给你的意思，不是给你的句子；
   你要用**这个人自己的**处境重新写出来。原样搬用会让 51 份设定互相撞车。
3. **不要按上面的顺序逐条写。** 揉进一段连贯的描述里，
   哪条先出现由这个人的实际情况决定，不是由列表顺序决定。
4. **只写上面列出的这 {count} 条。** 没列出来的方面这个人并不突出，
   一个字都不要提——不要补一句"他在某某方面不偏不倚"，那是凑字数。
5. **不要复述上面已有的日常生活。** 那段写的是「做什么」，你写的是「怎么做、为什么」。
   尤其不要把作息、饮食、健身这些已经写过的东西再说一遍。
6. **允许与这个人的其他设定存在张力。** 一个谨慎的人可以同时对新事物好奇——
   真人本来就这样。不要为了让人物「自洽」而把倾向往已有设定上靠。
7. **一条一句，总共 {count} 句，全段不超过 {limit} 字。**
   每句落在一个具体场景上，写完就停——不要补背景、不要展开、
   不要同一个意思换个说法再说一遍。宁可短。

只输出这一段文字本身，不要标题、不要引号、不要任何解释。"""

CHECK_PROMPT = """你在校对一份人物设定，找出**自相矛盾**的地方。

## 人物设定

{facts}

## 新增的段落

{paragraph}

## 任务

只找新增段落与上面已确定事实之间**真正的矛盾**——即两者不可能同时为真。
例如「常在深夜外出」配上「与学龄前子女同住且需要早起送园」。

不要报告以下情况（这些是有意为之，不是矛盾）：
- 性格倾向与这个人的谨慎程度／表达意愿／流动意愿不完全一致；
- 同一个人身上有张力但并非不可能同时成立的两面。

## 输出

严格的 JSON，不要任何其他文字。每一项必须**引用互相打架的那两句话**，不写推理过程：

{{"conflicts": [{{"from_facts": "<已确定事实里的原话>", "from_paragraph": "<新增段落里的原话>"}}]}}

**没有矛盾时 `conflicts` 必须是空数组** —— 不要在数组里放"未发现矛盾"
或任何说明性文字，那会被当成真的有矛盾。"""


def parse_ids(spec: str) -> list[int]:
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif chunk:
            out.append(int(chunk))
    return out


def load_profiles(md_path: str, agent_ids: list[int]) -> dict[int, dict]:
    from gaworld.sim.agents_loader import parse_profile

    with open(md_path, encoding="utf-8") as handle:
        text = handle.read()
    out: dict[int, dict] = {}
    for agent_id in agent_ids:
        match = re.search(rf"## Profile {agent_id:02d}｜.*?(?=\n## Profile |\Z)", text, re.S)
        if match:
            out[agent_id] = parse_profile(match.group(0))
    return out


def load_states(path: str) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                agent_id = int(str(row.get("id", "")).strip())
            except (TypeError, ValueError):
                continue
            values: dict[str, float] = {}
            for key, raw in row.items():
                try:
                    values[key] = float(raw)
                except (TypeError, ValueError):
                    continue
            out[agent_id] = values
    return out


def sample_population(
    ids: list[int], states: dict[int, dict[str, float]], seed: int, tilts: dict
) -> dict[int, dict[str, float]]:
    """Correlated OCEAN for every resident, tilted towards two state variables.

    ``z = r * s + sqrt(1 - r^2) * e`` keeps unit variance while giving exactly
    correlation ``r`` with the standardised state variable ``s``. It does
    perturb the within-OCEAN correlations slightly; at r = 0.3 the prior draw
    still carries 95% of the weight, and ``--dry-run`` prints both matrices so
    the distortion is visible rather than assumed.
    """
    sampling = (CONFIG.get("personality", {}) or {}).get("sampling", {}) or {}
    factor = cholesky(correlation_matrix(sampling.get("correlations", {}) or {}))
    draws = {i: sample_traits(random.Random(seed * 1000003 + i), factor) for i in ids}

    standardised: dict[str, dict[int, float]] = {}
    for _dim, (var, _r) in tilts.items():
        values = [states[i][var] for i in ids if var in states.get(i, {})]
        if len(values) < 3:
            continue
        mean = statistics.fmean(values)
        sd = statistics.stdev(values)
        if sd < 1e-9:
            continue
        standardised[var] = {i: (states[i][var] - mean) / sd for i in ids if var in states.get(i, {})}

    for dim, (var, target) in tilts.items():
        column = standardised.get(var)
        if not column:
            continue
        # Residualise the prior draw against the state variable before mixing,
        # so the realised correlation is exactly `target` rather than target
        # plus whatever the sample happened to contribute. At n=51 the standard
        # error of r is ~0.14, so without this step a 0.30 target lands
        # anywhere from 0.16 to 0.44 depending on the seed.
        subset = [i for i in ids if i in column]
        svec = [column[i] for i in subset]
        evec = [draws[i][dim] for i in subset]
        dot = sum(a * b for a, b in zip(svec, evec, strict=True))
        norm = sum(a * a for a in svec)
        resid = [e - (dot / norm) * a for a, e in zip(svec, evec, strict=True)] if norm else evec
        rsd = statistics.stdev(resid) if len(resid) > 1 else 1.0
        keep = (1.0 - target ** 2) ** 0.5
        for i, r_i in zip(subset, resid, strict=True):
            draws[i][dim] = target * column[i] + keep * (r_i / rsd if rsd > 1e-9 else 0.0)

    ordered = [draws[i] for i in ids]
    if sampling.get("rescale", True):
        rescale(ordered)
    return {i: {d: round(draws[i][d], 4) for d in DIMENSIONS} for i in ids}


def target_lines(
    values: dict[str, float], shuffle_seed: int | None = None
) -> tuple[str, int]:
    """Render the five targets using the runtime anchor sentences verbatim.

    Only the distinctive dimensions (see :data:`FLAT_Z`). Returns the rendered
    block and how many made the cut, because the prompt needs the count to set
    a sentence budget.

    Verbatim matters: these are the same strings the ``prompt`` channel injects
    during a run, so the profile paragraph and the in-run anchors describe one
    person rather than two. The topic labels (对新事物, 做事方式, …) are used
    instead of the trait names, because naming the trait invites the model to
    write the label back out — which is exactly what the output must not do.
    """
    lines = []
    for dim in DIMENSIONS:
        z = values[dim]
        if abs(z) < FLAT_Z:
            continue
        label, poles = ANCHORS[dim]
        mild, strong = poles["high" if z > 0 else "low"]
        lines.append(f"- {label}：{strong if abs(z) >= STRONG_Z else mild}")
    if shuffle_seed is not None:
        # A fixed order produces 51 paragraphs that all march O, C, E, A, N —
        # which reads as a checklist however well each sentence is written.
        # Deterministic per agent, so a re-run reproduces the same prompt.
        random.Random(shuffle_seed).shuffle(lines)
    return "\n".join(lines), len(lines)


#: Trait names the paragraph must never contain. Checked in code rather than
#: trusted to the prompt, because this is the failure mode that makes a profile
#: read as generated rather than written.
BANNED_LABELS = ["开放性", "尽责性", "外向性", "宜人性", "神经质", "外向", "内向", "尽责", "宜人"]

#: Distinctive phrases from the anchor sentences. A paragraph that reuses one
#: verbatim has translated the prompt instead of writing about this person; the
#: first pilot showed 2 of 5 doing exactly that with the same example phrase.
ECHO_SOURCES = ["新开的店", "独处超过两天", "一整天心神不宁", "别人急他不急"]

#: Upper bound on the paragraph, in characters. Not arbitrary: agent 1's
#: existing 角色资料 block is ~300 characters, so a 280-character paragraph
#: (what free generation produces) nearly doubles it — and a character sketch
#: that outweighs the day's situation is the crowding-out failure the Big Five
#: proposal set out to avoid. At 180 the block grows ~60%, which leaves the
#: situation in charge.
LENGTH_MIN, LENGTH_MAX = 90, 180

#: Problems a fresh generation can plausibly fix. Length is deliberately *not*
#: here: the second pilot regenerated all five and every retry came back over
#: the cap, two of them longer than the first attempt. Resampling a model that
#: writes long gives another long paragraph; the fix for length is compression,
#: which is a different task and one models are actually good at.
RESAMPLEABLE = ("出现人格标签", "照抄了提示词", "生成为空")

COMPRESS_PROMPT = """把下面这段人物描述压短，压到 **{limit} 字以内**。

原文：
{paragraph}

要求：
1. **原文写到的每一个行为倾向都不能丢**，压缩后仍要看得出来。
2. **保留具体的场景、地点、动作和原话**，那是这段文字唯一有价值的部分。
   要删的是铺陈、过渡、以及同一个意思的第二次表述。
3. 不要改成概括或标签。「他不太合群」这种写法是失败的，
   原文里那句带场景的写法才是要留的。
4. 只输出压缩后的段落，不要解释、不要引号、不要标题。"""


def compress(call_llm, paragraph: str, agent_id: int, limit: int, attempts: int = 3) -> str:
    """Shorten until it fits, keeping the best attempt if it never does.

    Compression converges where regeneration does not — each pass starts from
    an already-shorter text — so retrying here is worth the call. It does
    plateau, though: the third pilot saw roughly −30% on the first pass and
    almost nothing on the second, because the instruction to keep every listed
    tendency sets a content floor. Compression is the backstop; the real length
    control is asking for less in the first place (see :data:`FLAT_Z`).
    """
    best = paragraph
    for _ in range(attempts):
        reply = str(call_llm(
            COMPRESS_PROMPT.format(limit=limit, paragraph=best),
            task="personality_compress", agent_id=agent_id,
        ) or "").strip()
        if not reply:
            break
        if len(reply) < len(best):
            best = reply
        if len(best) <= limit:
            break
    return best


def check_paragraph(text: str) -> list[str]:
    """Cheap mechanical QA. Returns human-readable problems, empty if clean."""
    problems = []
    labels = [w for w in BANNED_LABELS if w in text]
    if labels:
        problems.append(f"出现人格标签：{'、'.join(labels)}")
    echoes = [w for w in ECHO_SOURCES if w in text]
    if echoes:
        problems.append(f"照抄了提示词里的措辞：{'、'.join(echoes)}")
    if len(text) > LENGTH_MAX:
        problems.append(f"{len(text)} 字，超出上限 {LENGTH_MAX}")
    elif len(text) < LENGTH_MIN:
        problems.append(f"{len(text)} 字，不足下限 {LENGTH_MIN}")
    return problems


def facts_block(profile: dict) -> str:
    return "\n".join(
        f"- {label}：{profile.get(key, '')}" for key, label in IMMUTABLE_FIELDS if profile.get(key)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--md-path", default=None)
    parser.add_argument("--states", default="data/hangzhou_agents_state_init.csv")
    parser.add_argument("--agents", default="1-51")
    parser.add_argument("--out", default="data/agents_big5.csv")
    parser.add_argument("--preview", default="output/traits/authored_preview.md")
    parser.add_argument("--seed", type=int, default=None, help="defaults to personality.sampling.seed")
    parser.add_argument("--retries", type=int, default=1,
                        help="regenerate this many times on a leaked label or copied phrase "
                             "(length is handled by compression, not by regenerating)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true",
                        help="write the paragraphs into the profile markdown and freeze the CSV "
                             "(backs the markdown up first)")
    args = parser.parse_args()

    md_path = args.md_path or CONFIG.get("md_path", "data/hangzhou_profiles_with_names.md")
    states = load_states(args.states)
    population = sorted(states)
    if not population:
        print(f"no rows in {args.states}", file=sys.stderr)
        return 1
    wanted = [i for i in parse_ids(args.agents) if i in states]
    seed = args.seed if args.seed is not None else int(
        (CONFIG.get("personality", {}) or {}).get("sampling", {}).get("seed", 20260820)
    )

    # Always sample the whole population, then select — so a pilot's scores are
    # the scores those residents will keep in the full run.
    scores = sample_population(population, states, seed, TILTS)
    profiles = load_profiles(md_path, population)

    if args.dry_run:
        print(f"population {len(population)}；本次生成 {len(wanted)} 人：{wanted}")
        print("tilts：" + "，".join(
            f"{DIMENSION_NAMES_ZH[d]}↔{v} r={r}" for d, (v, r) in TILTS.items()) + "\n")
        for var, (dim, target) in {v: (d, r) for d, (v, r) in TILTS.items()}.items():
            col = [states[i][var] for i in population]
            m, sd = statistics.fmean(col), statistics.stdev(col)
            zs = [(states[i][var] - m) / sd for i in population]
            ys = [scores[i][dim] for i in population]
            mz, my = statistics.fmean(zs), statistics.fmean(ys)
            num = sum((a - mz) * (b - my) for a, b in zip(zs, ys, strict=True))
            den = (sum((a - mz) ** 2 for a in zs) * sum((b - my) ** 2 for b in ys)) ** 0.5
            print(f"  实测 {DIMENSION_NAMES_ZH[dim]}↔{var} r = {num / den:+.2f}（目标 {target}）")
        print("\n每维标准差：" + "  ".join(
            f"{d.upper()}={statistics.stdev([scores[i][d] for i in population]):.2f}"
            for d in DIMENSIONS))
        first = wanted[0]
        print(f"\n--- 示例提示词（agent {first} {profiles[first].get('name','')}）---")
        targets, count = target_lines(scores[first], seed + first)
        print(GENERATE_PROMPT.format(
            facts=facts_block(profiles[first]), targets=targets,
            count=count, limit=LENGTH_MAX))
        written = [sum(1 for d in DIMENSIONS if abs(scores[i][d]) >= FLAT_Z) for i in wanted]
        print(f"\n本批每人要写的维度数：{written}（|z| ≥ {FLAT_Z} 才写）")
        print(f"\n计划调用：{len(wanted)} 次生成 + {len(wanted)} 次校对，"
              f"超长的另加 1–2 次压缩，标签／照抄的另加最多 {args.retries} 次重生成")
        return 0

    from gaworld.llm.providers import call_llm

    results: list[tuple[int, str, str, list[str], list[str]]] = []
    for agent_id in wanted:
        profile = profiles.get(agent_id)
        if not profile:
            print(f"  agent {agent_id}: profile 解析不到，跳过", file=sys.stderr)
            continue
        facts = facts_block(profile)
        targets, count = target_lines(scores[agent_id], seed + agent_id)
        prompt = GENERATE_PROMPT.format(
            facts=facts, targets=targets, count=count, limit=LENGTH_MAX
        )
        paragraph, problems = "", []
        # Two different faults, two different fixes. A leaked label or a copied
        # phrase is a bad sample — regenerate. Being over length is what this
        # model does — compress.
        for attempt in range(args.retries + 1):
            paragraph = str(call_llm(
                prompt, task="personality_authoring", agent_id=agent_id,
            ) or "").strip()
            problems = check_paragraph(paragraph) if paragraph else ["生成为空"]
            resampleable = [p for p in problems if any(k in p for k in RESAMPLEABLE)]
            if not resampleable:
                break
            if attempt < args.retries:
                print(f"  agent {agent_id} 重新生成（{'；'.join(resampleable)}）")

        if paragraph and len(paragraph) > LENGTH_MAX:
            before = len(paragraph)
            paragraph = compress(call_llm, paragraph, agent_id, LENGTH_MAX)
            problems = check_paragraph(paragraph)
            print(f"  agent {agent_id} 压缩 {before} → {len(paragraph)} 字"
                  + ("（仍超出）" if len(paragraph) > LENGTH_MAX else ""))

        conflicts: list[str] = []
        if paragraph:
            conflicts = check_conflicts(call_llm, facts, paragraph, agent_id)
        results.append((agent_id, profile.get("name", ""), paragraph, conflicts, problems))
        flags = "".join([
            f"  ⚠️ {len(conflicts)} 处矛盾" if conflicts else "",
            f"  ✗ {'；'.join(problems)}" if problems else "",
        ])
        print(f"agent {agent_id:>2} {profile.get('name',''):<6} {len(paragraph):>3}字{flags}")

    write_preview(args.preview, results, scores)
    print(f"\n预览写到 {args.preview}")
    bad = [r for r in results if r[4]]
    conflicted = [r for r in results if r[3]]
    if bad:
        print(f"✗ {len(bad)}/{len(results)} 份没通过机械检查（标签／照抄／字数）")
    if conflicted:
        print(f"⚠️ {len(conflicted)}/{len(results)} 份被校对标出矛盾，见预览文件末尾")
    if not bad and not conflicted:
        print("机械检查与校对都干净。")

    if args.apply:
        if len(wanted) < len(population):
            print("--apply 需要跑完整人群（去掉 --agents）", file=sys.stderr)
            return 1
        backup = md_path.replace(".md", ".v1.md")
        if not os.path.exists(backup):
            with open(md_path, encoding="utf-8") as src, open(backup, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            print(f"原始语料已备份到 {backup}")
        insert_into_markdown(md_path, results)
        write_scores_csv(args.out, results, scores)
        print(f"已写入 {md_path} 与 {args.out}")
        print("接着跑：python scripts/big5_collinearity.py --annotate")
    else:
        print("这是试水，语料未改动。确认文风后去掉 --agents 并加 --apply。")
    return 0


def check_conflicts(call_llm, facts: str, paragraph: str, agent_id: int) -> list[str]:
    """Ask for contradictions and keep only entries that actually name two statements.

    The first pilot's checker answered "整体未发现与已确定事实不可同时成立的矛盾"
    *inside* the conflicts array — a clean paragraph reported as a conflict.
    Requiring each entry to quote both sides makes that shape impossible to
    produce accidentally, and anything that still lacks a quote is dropped here.
    """
    reply = call_llm(
        CHECK_PROMPT.format(facts=facts, paragraph=paragraph),
        task="personality_conflict_check", agent_id=agent_id,
    )
    match = re.search(r"\{.*\}", str(reply or ""), re.S)
    if not match:
        return ["(校对回复不是 JSON)"]
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ["(校对回复无法解析)"]
    out = []
    for item in payload.get("conflicts") or []:
        if not isinstance(item, dict):
            continue
        left = str(item.get("from_facts", "")).strip()
        right = str(item.get("from_paragraph", "")).strip()
        if left and right:
            out.append(f"设定「{left}」 ↔ 段落「{right}」")
    return out


def write_preview(path: str, results, scores) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# 人格段落生成预览\n\n")
        handle.write("每份包含采样到的五维分数与生成的段落。分数为 z 分，正数偏高。\n\n")
        for agent_id, name, paragraph, _conflicts, problems in results:
            values = scores[agent_id]
            handle.write(f"## Profile {agent_id:02d}｜{name}\n\n")
            handle.write("| " + " | ".join(DIMENSION_NAMES_ZH[d] for d in DIMENSIONS) + " |\n")
            handle.write("|" + "---|" * len(DIMENSIONS) + "\n")
            handle.write("| " + " | ".join(f"{values[d]:+.2f}" for d in DIMENSIONS) + " |\n\n")
            handle.write(f"**人格与行为倾向**（{len(paragraph)} 字）：{paragraph}\n\n")
            if problems:
                handle.write(f"> ✗ 机械检查：{'；'.join(problems)}\n\n")
        bad = [(i, n, p) for i, n, _, _, p in results if p]
        if bad:
            handle.write("---\n\n## 机械检查没过的\n\n")
            for agent_id, name, problems in bad:
                handle.write(f"- **{agent_id:02d} {name}**：{'；'.join(problems)}\n")
        flagged = [(i, n, c) for i, n, _, c, _ in results if c]
        if flagged:
            handle.write("\n---\n\n## 校对标出的矛盾\n\n")
            for agent_id, name, conflicts in flagged:
                handle.write(f"- **{agent_id:02d} {name}**\n")
                for conflict in conflicts:
                    handle.write(f"  - {conflict}\n")


def insert_into_markdown(md_path: str, results) -> None:
    """Add the new field after 性格与情绪特征, leaving that line untouched.

    The old field stays because four subsystems keyword-match against it
    (``dynamic.py``'s archetype table and ``is_extrovert``, ``finance.py``'s
    wealth drive, ``_heuristic_schedule``'s sleep-pattern hints). Rewriting it
    would change all four at the same time as personality lands, and the two
    effects could never be told apart afterwards.
    """
    with open(md_path, encoding="utf-8") as handle:
        text = handle.read()
    for agent_id, _name, paragraph, _conflicts, _problems in results:
        if not paragraph:
            continue
        pattern = rf"(## Profile {agent_id:02d}｜.*?\*\*性格与情绪特征\*\*：.*?\n)"
        text = re.sub(
            pattern, rf"\1\n**人格与行为倾向**：{paragraph}\n", text, count=1, flags=re.S
        )
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_scores_csv(path: str, results, scores) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "name", *DIMENSIONS, "source", "unstated", "redundant"])
        for agent_id, name, _paragraph, _conflicts, _problems in results:
            values = scores[agent_id]
            writer.writerow([
                agent_id, name,
                *[max(-Z_CLIP, min(Z_CLIP, values[d])) for d in DIMENSIONS],
                "sampled_authored", "", "",
            ])


if __name__ == "__main__":
    raise SystemExit(main())
