"""LLM judging: prompt construction, structured parsing, multi-judge ensemble.

Hard constraints implemented here (design doc §5):
  * empty ``evidence`` forces ``abstain`` -- a score with no quoted evidence is
    an impression, not a judgement, and is discarded;
  * ``reasoning`` is length-capped so the judge cannot argue itself into a score;
  * per (item, unit) the ensemble takes the **median** across judges, and each
    judge is sampled ``n`` times with the mode taken, both to resist outliers.
"""

import json
import re
import statistics
import sys
from pathlib import Path

PROMPT_TEMPLATE = """你是一名严格的行为科学评审。下面给你一份**人物行为记录**和**一条评分标准**。

请只针对这一条标准打分。规则：

1. 打分为 0 / 1 / 2 三档，严格对照下面给出的档位描述，不要用你自己的标准。
2. **必须**从记录原文中摘出支持你打分的片段放进 `evidence`（1-3 条，每条不超过 60 字）。
3. 如果记录里根本没有能判断这条标准的信息，输出 `"abstain": true`，不要猜。
4. 文笔好坏、语言是否优美**不计分**。只看这条标准问的那件事。
5. `reasoning` 不超过 60 字。

## 评分标准 {item_id}
命题：{proposition}

档位：
- 0 分：{a0}
- 1 分：{a1}
- 2 分：{a2}

已知的典型失败模式（命中即应压低分数）：{failure_modes}
{facts_block}
## 待评记录

{sample}

## 输出

只输出一个 JSON 对象，不要有其他文字：
{{"score": 0|1|2, "evidence": ["原文片段", ...], "reasoning": "≤60字", "abstain": false}}
"""


def build_prompt(item: dict, sample: str, facts: dict | None = None) -> str:
    facts_block = ""
    if facts:
        facts_block = ("\n## 已由程序核算出的客观事实（可直接采信，不必自行统计）\n\n"
                       + json.dumps(facts, ensure_ascii=False, indent=2)[:2000] + "\n")
    anchors = item.get("anchors", {})
    return PROMPT_TEMPLATE.format(
        item_id=item["id"], proposition=item["proposition"],
        a0=anchors.get("0", ""), a1=anchors.get("1", ""), a2=anchors.get("2", ""),
        failure_modes="；".join(item.get("failure_modes", [])) or "（无）",
        facts_block=facts_block, sample=sample,
    )


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_response(text: str) -> dict:
    """Parse the judge reply; anything unparseable becomes an abstain."""
    m = _JSON_RE.search(text or "")
    if not m:
        return {"score": None, "abstain": True, "evidence": [],
                "reasoning": "judge 输出无法解析为 JSON"}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"score": None, "abstain": True, "evidence": [],
                "reasoning": "judge 输出 JSON 非法"}

    evidence = [str(e)[:120] for e in (data.get("evidence") or []) if str(e).strip()]
    score = data.get("score")
    if not isinstance(score, int) or score not in (0, 1, 2):
        score = None
    # Evidence-binding rule: no quote -> no score.
    abstain = bool(data.get("abstain")) or score is None or not evidence
    return {"score": None if abstain else score, "abstain": abstain,
            "evidence": evidence[:3], "reasoning": str(data.get("reasoning") or "")[:120]}


def _call_llm(prompt: str, provider: str | None):
    """Resolve gaworld's LLM router lazily so rule-only runs need no config."""
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from gaworld.llm.providers import call_llm  # noqa: PLC0415
    return call_llm(prompt, task="rubric_judge", provider=provider)


def judge_item(item: dict, sample: str, facts: dict | None, *,
               providers: list[str], samples_per_judge: int = 3,
               call=None) -> dict:
    """Run the ensemble for one (item, unit). Returns the aggregated verdict
    plus every raw vote, so disagreement is inspectable after the fact."""
    call = call or _call_llm
    prompt = build_prompt(item, sample, facts)
    votes = []
    for provider in providers:
        per_provider = []
        for _ in range(samples_per_judge):
            try:
                parsed = parse_response(call(prompt, provider))
            except Exception as exc:  # provider errors must not kill the run
                parsed = {"score": None, "abstain": True, "evidence": [],
                          "reasoning": f"调用失败：{type(exc).__name__}"}
            per_provider.append(parsed)
        scored = [v["score"] for v in per_provider if not v["abstain"]]
        votes.append({
            "provider": provider,
            "score": statistics.mode(scored) if scored else None,
            "abstain": not scored,
            "evidence": next((v["evidence"] for v in per_provider if not v["abstain"]), []),
            "reasoning": next((v["reasoning"] for v in per_provider if not v["abstain"]), ""),
            "raw": per_provider,
        })

    valid = [v["score"] for v in votes if v["score"] is not None]
    if not valid:
        return {"score": None, "abstain": True, "evidence": [],
                "reasoning": "全部 judge 弃权或调用失败", "votes": votes}
    return {
        "score": int(statistics.median_low(sorted(valid))),
        "abstain": False,
        "evidence": next((v["evidence"] for v in votes if v["evidence"]), []),
        "reasoning": next((v["reasoning"] for v in votes if v["reasoning"]), ""),
        "votes": votes,
        "vote_spread": max(valid) - min(valid),
    }
