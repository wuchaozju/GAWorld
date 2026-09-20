"""Unit -> de-identified, length-capped text for the judge.

Two jobs, both bias controls (design doc §5.2):
  * strip anything that tells the judge this is a simulation ("agent", numeric
    ids, "仿真"), which otherwise shifts scores in a hard-to-predict direction;
  * cap every unit at the same budget so long samples don't win on length.
"""

import json
import re

# Rough CJK-aware budget: 1 char ≈ 1 token for Chinese, so cap on characters.
BUDGETS = {"agent_day": 4500, "trajectory": 9000, "dyad": 4500,
           "world_slice": 6000, "cohort": 4500}

_DEID = [
    (re.compile(r"agent[_\s-]?(\d+)", re.I), lambda m: f"受访者{_letter(int(m.group(1)))}"),
    (re.compile(r"仿真|模拟世界|生成式智能体|AI\s*agent", re.I), "记录"),
]


def _letter(n: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return letters[n % 26] + (str(n // 26) if n >= 26 else "")


def deidentify(text: str) -> str:
    for pattern, repl in _DEID:
        text = pattern.sub(repl, text)
    return text


def _cap(text: str, budget: int) -> str:
    """Keep the head and tail; drop the middle, which is where redundancy lives."""
    if len(text) <= budget:
        return text
    head = int(budget * 0.65)
    tail = budget - head - 20
    return text[:head] + "\n…（中段省略）…\n" + text[-tail:]


def _episode_lines(eps: list[dict], *, verbose: bool = True) -> list[str]:
    lines = []
    for ep in eps:
        travel = ep.get("travel") or {}
        lines.append(f"- [{ep.get('time', '??:??')}] 地点：{ep.get('location', '?')}"
                     + (f"（{travel.get('mode')} {travel.get('minutes')}分钟 "
                        f"{travel.get('distance_km')}km）" if travel else ""))
        lines.append(f"  计划：{ep.get('scheduled_activity', '')}")
        lines.append(f"  实做：{ep.get('final_activity', '')}｜动作：{ep.get('action', '')}")
        if ep.get("change_reason"):
            lines.append(f"  偏离理由：{ep['change_reason']}（驱动：{ep.get('decision_driver', '')}）")
        if not verbose:
            continue
        if ep.get("need_snapshot"):
            lines.append(f"  需求：{json.dumps(ep['need_snapshot'], ensure_ascii=False)}")
        if ep.get("recollections"):
            lines.append(f"  回忆：{json.dumps(ep['recollections'], ensure_ascii=False)}")
        for key, label in (("env_events", "环境事件"), ("life_events", "生活事件")):
            if ep.get(key):
                lines.append(f"  {label}：{json.dumps(ep[key], ensure_ascii=False)}")
        if ep.get("policy_event"):
            lines.append(f"  政策事件：{ep['policy_event']}")
        if ep.get("plan_struct"):
            lines.append(f"  计划结构：{json.dumps(ep['plan_struct'], ensure_ascii=False)}")
        if ep.get("reflection"):
            lines.append(f"  反思：{ep['reflection']}")
        if ep.get("delta"):
            big = {k: round(v, 3) for k, v in ep["delta"].items()
                   if isinstance(v, (int, float)) and abs(v) >= 0.05}
            if big:
                lines.append(f"  状态变化：{json.dumps(big, ensure_ascii=False)}")
    return lines


def render(unit: dict) -> str:
    kind = unit["kind"]
    if kind == "agent_day":
        parts = [f"## 单日记录（第 {unit['day']} 天）"]
        if unit.get("profile"):
            parts.append("### 人物背景\n" + unit["profile"][:1200])
        parts.append("### 当日事件序列")
        parts += _episode_lines(unit["episodes"])
        if unit.get("diary"):
            parts.append("### 当日自述\n" + unit["diary"])
    elif kind == "trajectory":
        parts = [f"## 长期轨迹（共 {len({int(e.get('day') or 0) for e in unit['episodes']})} 天）"]
        if unit.get("profile"):
            parts.append("### 人物背景\n" + unit["profile"][:800])
        by_day: dict[int, list[dict]] = {}
        for ep in unit["episodes"]:
            by_day.setdefault(int(ep.get("day") or 0), []).append(ep)
        for day in sorted(by_day):
            parts.append(f"### 第 {day} 天")
            parts += _episode_lines(by_day[day], verbose=False)
            diary = (unit.get("diaries") or {}).get(day)
            if diary:
                parts.append("  自述：" + diary[:400].replace("\n", " "))
        if unit.get("growth"):
            parts.append("### 成长项快照\n"
                         + json.dumps(unit["growth"], ensure_ascii=False)[:1500])
    elif kind == "dyad":
        a, b = unit["pair"]
        parts = [f"## 两人互动（{_letter(a)} 与 {_letter(b)}）",
                 f"### {_letter(a)} 的视角"] + _episode_lines(unit["episodes_a"]) + \
                [f"### {_letter(b)} 的视角"] + _episode_lines(unit["episodes_b"])
    elif kind == "world_slice":
        parts = [f"## 同一天的全城横截面（第 {unit['day']} 天）"]
        for aid, eps in sorted(unit["by_agent"].items()):
            parts.append(f"### {_letter(aid)}")
            parts += _episode_lines(eps, verbose=False)
            for ep in eps[:2]:
                if ep.get("perception"):
                    parts.append(f"  感知：{str(ep['perception'])[:300]}")
    elif kind == "cohort":
        parts = [f"## 群体概览（{len(unit.get('episodes') or {})} 人）"]
        for aid, eps in sorted((unit.get("episodes") or {}).items()):
            days = sorted({int(e.get("day") or 0) for e in eps})
            parts.append(f"- {_letter(aid)}：{len(eps)} 条记录，覆盖第 {days[:5]}… 天")
    else:
        parts = [json.dumps(unit, ensure_ascii=False)]

    return _cap(deidentify("\n".join(parts)), BUDGETS.get(kind, 4500))
