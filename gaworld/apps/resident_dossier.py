"""The resident dossier — the brief a writer gets before touching a life.

Two dashboard features write long-form documents about one resident: the
autobiography (``gaworld.apps.autobiography_api``, what has already happened)
and the life prediction (``gaworld.apps.life_prediction_api``, what is yet to
come). Both start from the same evidence — identity, Big Five, the narrative
profile, the nine state variables, goals, memory, relationships, finance and
the life events so far — and both need that evidence in the same shape, so it
lives here rather than being copied between the two writers.

Three public functions:

* :func:`gather` — read everything the dashboard knows about one resident.
* :func:`format` — turn that into the compact, structured briefing a model
  call reads.
* :func:`safe_text` — stringify one value without letting it blow the prompt.

The module is deliberately read-only: it never writes to a resident's memory
or files.
"""

from __future__ import annotations

import json
from typing import Any

from gaworld.apps import residents
from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG

_LOG = get_logger("gaworld.dashboard.dossier")


def safe_text(value: Any, limit: int = 4000) -> str:
    """Stringify, strip control noise and cap the length.

    A single multi-line diary entry, an unfiltered memory dump or an
    accidentally-blob memory item must not blow the prompt context; each
    contributor is hard-capped so the assembled prompt stays inside budget.
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\x00", "")
    if len(text) > limit:
        text = text[:limit] + "\n…(已截断)…\n"
    return text.strip()


def gather(agent_id: int) -> dict[str, Any]:
    """Collect every signal the studio panel knows about this resident.

    Imports stay local so a tiny request (``/api/agents/<id>/big5``) does not
    pay for the prompt-formatting helpers.

    ``residents`` is the new home of the agent-detail loader (moved out of
    ``dashboard_server``); the old name there now raises a deliberate
    ``AttributeError`` to catch stale callers.
    """
    detail = residents.agent_detail(agent_id) or {}
    identity = detail.get("identity") or {}

    big5 = None
    try:
        big5 = residents.agent_big5(agent_id)
    except Exception:
        _LOG.warning("dossier: could not read big5 for agent %s", agent_id, exc_info=True)

    finance = detail.get("finance_state") or {}
    social = detail.get("social") or {}
    goals = detail.get("goals") or {}
    home = detail.get("home") or {}

    long_term = ((detail.get("memory") or {}).get("long_term")) or []
    habits = ((detail.get("memory") or {}).get("habits")) or []
    intentions = ((detail.get("memory") or {}).get("intentions")) or {}
    schedule = ((detail.get("memory") or {}).get("schedule")) or []

    life_events: list[dict[str, Any]] = []
    try:
        from gaworld.events.life import list_life_events

        all_events = list_life_events(CONFIG, include_consumed=True) or []
        for ev in all_events:
            try:
                if int(ev.get("agent_id") or ev.get("resident_id") or 0) == int(agent_id):
                    life_events.append(ev)
            except (TypeError, ValueError):
                continue
    except Exception:
        _LOG.warning("dossier: could not read life events for agent %s", agent_id, exc_info=True)

    return {
        "identity": identity,
        "profile_text": detail.get("profile_text") or "",
        "big5": big5,
        "state": detail.get("state") or {},
        "finance": finance,
        "social": social,
        "goals": goals,
        "home": home,
        "memory": {
            "long_term": long_term,
            "habits": habits,
            "intentions": intentions,
            "schedule": schedule,
        },
        "life_events": life_events,
    }


def format(materials: dict[str, Any]) -> str:
    """Turn the gathered signals into a compact, structured briefing.

    The LLM is told to write in the voice of a biographer; the briefing is
    the dossier that biographer has on their clipboard.
    """
    identity = materials["identity"] or {}
    big5 = materials["big5"] or {}
    state = materials["state"] or {}
    big5_values = big5.get("values") or {}
    big5_authored = big5.get("authored") or {}
    big5_paragraph = big5.get("paragraph") or ""
    big5_consistency = big5.get("consistency")

    lines: list[str] = []
    lines.append("# 居民档案（写自传用）")
    lines.append("")
    lines.append(f"- 编号：{identity.get('id') or '?'}")
    lines.append(f"- 姓名：{identity.get('name') or '?'}")
    lines.append(f"- 性别：{identity.get('gender') or '?'}")
    lines.append(f"- 年龄：{identity.get('age') or '?'}")
    lines.append(f"- 户籍：{identity.get('hukou') or '?'}")
    lines.append(f"- 现居地：{identity.get('residence') or '?'}")

    if state:
        lines.append("")
        lines.append("## 当前状态变量（0–1，越大越强）")
        for key, value in state.items():
            try:
                lines.append(f"- {key}: {float(value):.2f}")
            except (TypeError, ValueError):
                continue

    if big5_values:
        lines.append("")
        lines.append("## Big Five 大五人格（z 分）")
        names_zh = big5.get("names") or {}
        for dim, z in big5_values.items():
            label = names_zh.get(dim) or dim
            authored = big5_authored.get(dim) if isinstance(big5_authored, dict) else None
            authored_str = f"（自述：{float(authored):+.2f}）" if authored is not None else ""
            try:
                lines.append(f"- {label} ({dim}): {float(z):+.2f}{authored_str}")
            except (TypeError, ValueError):
                continue
        if big5_paragraph:
            lines.append("")
            lines.append("### 人设心理段落")
            lines.append(big5_paragraph)
        if big5_consistency is not None:
            lines.append("")
            try:
                lines.append(f"### 自述 vs 实测一致性: {float(big5_consistency):.2f}")
            except (TypeError, ValueError):
                pass

    profile_text = materials.get("profile_text") or ""
    if profile_text:
        lines.append("")
        lines.append("## 叙事档案（Markdown）")
        lines.append(safe_text(profile_text, limit=4000))

    goals = materials.get("goals") or {}
    if goals:
        lines.append("")
        lines.append("## 三层目标")
        for tier in ("long_term", "medium_term", "short_term"):
            items = goals.get(tier) or []
            if items:
                lines.append(f"### {tier}")
                for item in items:
                    title = item.get("title") if isinstance(item, dict) else str(item)
                    progress = item.get("progress") if isinstance(item, dict) else None
                    domain = item.get("domain") if isinstance(item, dict) else None
                    meta = ""
                    if progress is not None:
                        try:
                            meta += f" 进度={float(progress) * 100:.0f}%"
                        except (TypeError, ValueError):
                            pass
                    if domain:
                        meta += f" 领域={domain}"
                    lines.append(f"- {title}{meta}")

    memory = materials.get("memory") or {}
    long_term = memory.get("long_term") or []
    if long_term:
        lines.append("")
        lines.append(f"## 长期记忆（共 {len(long_term)} 条，按时间倒序给出最多 30 条）")
        items = list(long_term)
        items.sort(key=lambda m: m.get("time") or m.get("day") or 0, reverse=True)
        for item in items[:30]:
            text = safe_text(item.get("text") if isinstance(item, dict) else item, limit=400)
            day = item.get("day") if isinstance(item, dict) else None
            when = item.get("time") if isinstance(item, dict) else None
            ts = ""
            if day is not None or when is not None:
                ts = f"[{day or ''}{' ' + when if when else ''}] "
            lines.append(f"- {ts}{text}")

    habits = memory.get("habits") or []
    if habits:
        lines.append("")
        lines.append("## 习惯")
        for item in habits[:20]:
            lines.append(f"- {safe_text(item.get('text') if isinstance(item, dict) else item, limit=200)}")

    intentions = memory.get("intentions") or {}
    if intentions:
        lines.append("")
        lines.append("## 当前意图")
        if isinstance(intentions, dict):
            for key, value in list(intentions.items())[:20]:
                lines.append(f"- {key}: {safe_text(value, limit=200)}")
        else:
            for item in list(intentions)[:20]:
                lines.append(f"- {safe_text(item, limit=200)}")

    schedule = memory.get("schedule") or []
    if schedule:
        lines.append("")
        lines.append("## 今日日程")
        for item in schedule[:20]:
            lines.append(f"- {safe_text(item.get('text') if isinstance(item, dict) else item, limit=200)}")

    social = materials.get("social") or {}
    if social:
        lines.append("")
        lines.append("## 社交关系")
        relations = social.get("relations") if isinstance(social, dict) else None
        if isinstance(relations, list):
            for rel in relations[:20]:
                if not isinstance(rel, dict):
                    lines.append(f"- {safe_text(rel, limit=200)}")
                    continue
                name = rel.get("name", "？")
                role = rel.get("role", "")
                tier = rel.get("tier", "")
                closeness = rel.get("closeness")
                trust = rel.get("trust")
                bits = [f"{name}"]
                if role:
                    bits.append(f"角色={role}")
                if tier:
                    bits.append(f"圈层={tier}")
                if closeness is not None:
                    try:
                        bits.append(f"亲密度={float(closeness):.2f}")
                    except (TypeError, ValueError):
                        pass
                if trust is not None:
                    try:
                        bits.append(f"信任={float(trust):.2f}")
                    except (TypeError, ValueError):
                        pass
                lines.append(f"- {' | '.join(bits)}")

    finance = materials.get("finance") or {}
    if finance:
        lines.append("")
        lines.append("## 财务画像")
        for key in ("income_monthly", "expense_monthly", "savings", "debt", "job_label"):
            if key in finance:
                lines.append(f"- {key}: {safe_text(finance.get(key), limit=200)}")

    life_events = materials.get("life_events") or []
    if life_events:
        lines.append("")
        lines.append(f"## 生命事件（共 {len(life_events)} 条）")
        for ev in life_events[:30]:
            if not isinstance(ev, dict):
                lines.append(f"- {safe_text(ev, limit=200)}")
                continue
            label = ev.get("template_key") or ev.get("key") or ev.get("title") or "事件"
            day = ev.get("triggered_day") or ev.get("day")
            when = f"[{day}] " if day is not None else ""
            lines.append(f"- {when}{label}")

    return "\n".join(lines)


__all__ = ["format", "gather", "safe_text"]
