"""Turn an enterprise's user file into an anonymised, downloadable agent pack.

Pipeline::

    file (CSV / xlsx / JSONL)
      → parse + column mapping        (reused from gaworld.apps.import_api)
      → anonymise                     (this module)
      → render agents                 (same profile shape city.agents writes)
      → zip: agents.csv, profiles.md, agents.jsonl, report.json, README.md

What happens to each recognised field:

* **dropped** — ``phone`` / ``email`` / ``id_card`` / ``company`` / ``residence``
  and every column the mapping does not recognise (allow-list, not block-list).
* **replaced** — ``name`` becomes a unique pseudonym, ``hometown`` a fictional
  place; the residence is re-drawn from the target city's districts.
* **coarsened** — ``monthly_income`` is rounded to the nearest 500.
* **scrubbed** — free text (``personality`` / ``daily_life`` / ``values``) has the
  row's own identifying values and any e-mail, ID number, phone number or long
  digit run replaced by a placeholder. Names of *other* people inside free text
  cannot be detected without NER; pass ``drop_free_text=True`` when that matters.

The salt behind the pseudonyms is random per run unless given, and is never
written into the pack, so pseudonyms cannot be reversed by re-running the tool.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import secrets
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gaworld.apps.import_api import (
    _FAKE_CITY_POOL,
    _FAKE_NAME_POOL,
    _hash_to_index,
    _normalise_hukou,
    normalise_rows,
    parse_upload,
    suggest_mapping,
)
from gaworld.city.agents import _render_single_profile
from gaworld.population.schema import CSV_COLUMNS, STATE_VAR_KEYS
from gaworld.population.synth import RESIDENCE_SUFFIXES

#: Recognised but never carried into an agent. ``id`` is already removed by
#: ``normalise_rows`` (agents are renumbered); listed so reports say so.
DROPPED_FIELDS: tuple[str, ...] = ("id", "phone", "email", "id_card", "company", "residence")
FREE_TEXT_FIELDS: tuple[str, ...] = ("personality", "daily_life", "values")

#: Order matters: e-mail and 18-digit IDs before the phone / digit-run patterns
#: that would otherwise eat part of them.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[邮箱]"),
    ("id_card", re.compile(r"(?<![\dA-Za-z])\d{17}[\dXx](?![\dA-Za-z])"), "[证件号]"),
    ("phone", re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"), "[电话]"),
    ("number", re.compile(r"\d[\d\s-]{5,}\d"), "[号码]"),
)

#: The same neutral fill-ins ``gaworld.city.agents.add_agent`` uses.
_DEFAULT_TEXT = {
    "personality": "性格平和，情绪起伏不大，遇事偏向先观察再行动。",
    "daily_life": "作息规律，日常以工作、家务和少量社交为主。",
    "values": "对公共事务关注有限，除非直接影响到自己的生活才会去了解。",
}

_GENDER_ALIASES = {
    "男": "男",
    "男性": "男",
    "m": "男",
    "male": "男",
    "man": "男",
    "女": "女",
    "女性": "女",
    "f": "女",
    "female": "女",
    "woman": "女",
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def prepare(
    path: Path, overrides: dict[str, str] | None = None
) -> tuple[list[str], dict[str, str], list[dict[str, str]]]:
    """Read *path* and map its columns. Returns ``(headers, mapping, rows)``.

    ``overrides`` wins over the suggested mapping; map a header to ``""`` to
    force-drop it.
    """
    _, headers, raw_rows = parse_upload(path.name, "", path.read_bytes())
    mapping = suggest_mapping(headers)
    for header, field in (overrides or {}).items():
        if header not in mapping:
            raise ValueError(f"文件中没有列「{header}」，现有列：{', '.join(headers)}")
        mapping[header] = field
    return headers, mapping, normalise_rows(raw_rows, mapping)


# ---------------------------------------------------------------------------
# Anonymisation
# ---------------------------------------------------------------------------


def _scrub(text: str, literals: dict[str, str], hits: Counter[str]) -> str:
    # Longest first, so "杭州市西湖区" is replaced before "杭州" could split it.
    for value in sorted(literals, key=len, reverse=True):
        if value in text:
            hits["literal"] += text.count(value)
            text = text.replace(value, literals[value])
    for label, pattern, placeholder in _PII_PATTERNS:
        text, count = pattern.subn(placeholder, text)
        hits[label] += count
    return text


def _pseudonym(name: str, salt: str, used: set[str]) -> str:
    """A pseudonym unique within this run; probes the pool on collision."""
    pool = _FAKE_NAME_POOL
    start = _hash_to_index(salt, "name", name, modulo=len(pool))
    for step in range(len(pool)):
        candidate = pool[(start + step) % len(pool)]
        if candidate not in used:
            used.add(candidate)
            return candidate
    candidate = f"{pool[start]}{len(used) + 1}"  # more people than the pool holds
    used.add(candidate)
    return candidate


def anonymise(
    rows: list[dict[str, str]],
    *,
    salt: str,
    drop_free_text: bool = False,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Return ``(clean_rows, scrub_counts)``; rows are canonical-keyed."""
    hits: Counter[str] = Counter()
    used: set[str] = set()
    out: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        clean = dict(row)
        literals: dict[str, str] = {}
        for field in DROPPED_FIELDS:
            value = (clean.pop(field, "") or "").strip()
            if len(value) >= 2:
                literals[value] = "某处"
        real_name = (clean.get("name") or "").strip()
        fake_name = _pseudonym(real_name or f"row-{index}", salt, used)
        clean["name"] = fake_name
        if len(real_name) >= 2:
            literals[real_name] = fake_name
        hometown = (clean.get("hometown") or "").strip()
        if hometown:
            fake = _FAKE_CITY_POOL[_hash_to_index(salt, "hometown", hometown, modulo=len(_FAKE_CITY_POOL))]
            clean["hometown"] = fake
            if len(hometown) >= 2:
                literals[hometown] = fake
        for field in FREE_TEXT_FIELDS:
            if drop_free_text:
                clean.pop(field, None)
            elif clean.get(field):
                clean[field] = _scrub(clean[field], literals, hits)
        out.append(clean)
    return out, dict(hits)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _to_agent(
    agent_id: int, row: dict[str, str], rng: random.Random, districts: list[str], imputed: Counter[str]
) -> dict[str, Any]:
    age = _as_float(row.get("age"))
    if age is None or not 0 <= age <= 100:
        imputed["age"] += 1
        age = 35
    gender = _GENDER_ALIASES.get((row.get("gender") or "").strip().lower())
    if gender is None:
        imputed["gender"] += 1
        gender = rng.choice(("男", "女"))

    income = _as_float(row.get("monthly_income"))
    income = round(income / 500) * 500 if income is not None and income >= 0 else None
    education = (row.get("education") or "").strip()
    edu_text = f"{education}学历" if education else "学历未提供"
    income_text = f"月收入约 {income:,.0f} 元" if income else "收入情况未提供"

    industry = (row.get("industry") or "").strip()
    employment = (row.get("employment") or "").strip()
    job = "，".join(part for part in (f"{industry}行业" if industry else "", employment) if part)

    state: dict[str, float] = {}
    for key in STATE_VAR_KEYS:
        value = _as_float(row.get(key))
        if value is None or not 0 <= value <= 1:
            value = round(rng.uniform(0.35, 0.70), 2)
        state[key] = value

    texts = {}
    for field in FREE_TEXT_FIELDS:
        texts[field] = (row.get(field) or "").strip()
        if not texts[field]:
            imputed[field] += 1
            texts[field] = _DEFAULT_TEXT[field]

    hometown = row.get("hometown")
    return {
        "id": agent_id,
        "name": row["name"],
        "gender": gender,
        "age": int(age),
        "hukou": _normalise_hukou(row.get("hukou")),
        "residence": f"{rng.choice(districts)}·{rng.choice(RESIDENCE_SUFFIXES)}",
        "education": education,
        "income_monthly": income or 0.0,
        "education_income": f"{edu_text}，{income_text}。",
        "industry": industry,
        "employment": employment,
        "job": (job or "职业信息未提供") + "。",
        "social_network": f"家乡在{hometown}。" if hometown else "社会关系信息未提供。",
        **texts,
        "state": state,
    }


def _state_csv(agents: list[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for agent in agents:
        writer.writerow(
            {
                "id": agent["id"],
                "name": agent["name"],
                "gender": agent["gender"],
                "age": agent["age"],
                "hukou": agent["hukou"],
                "residence": agent["residence"],
                "employment": agent["employment"],
                "industry": agent["industry"],
                "monthly_income": f"{agent['income_monthly']:.0f}" if agent["income_monthly"] else "",
                **{key: f"{agent['state'][key]:.2f}" for key in STATE_VAR_KEYS},
            }
        )
    return buffer.getvalue()


_README = """# GAWorld 智能体包

由 `python -m gaworld.enterprise` 从企业用户数据匿名化生成。

| 文件 | 内容 |
|---|---|
| `agents.csv` | 居民状态表（GAWorld `csv_path` 格式） |
| `profiles.md` | 居民人物设定（GAWorld `md_path` 格式） |
| `agents.jsonl` | 每行一个智能体的完整字段，便于其他系统读取 |
| `report.json` | 列映射、被删除的列、补全与脱敏统计（不含任何原始值） |

在 GAWorld 中使用：把两个文件放进仓库，并在 `dashboard_config.json` 中设置
`"csv_path": "<路径>/agents.csv", "md_path": "<路径>/profiles.md"`。

姓名为化名，住址按目标城市区划重新抽取，电话/邮箱/证件号/单位已删除，
收入按 500 元取整。自由文本中他人姓名无法完全识别，请在分发前人工抽查。
"""


def build_package(
    source: Path,
    output: Path,
    *,
    overrides: dict[str, str] | None = None,
    districts: list[str] | None = None,
    salt: str | None = None,
    seed: int = 0,
    drop_free_text: bool = False,
    title: str = "企业用户",
) -> dict[str, Any]:
    """Run the whole pipeline and write the zip. Returns the report."""
    headers, mapping, rows = prepare(source, overrides)
    if not rows:
        raise ValueError("文件中没有任何数据行")
    clean, scrubbed = anonymise(rows, salt=salt or secrets.token_hex(16), drop_free_text=drop_free_text)

    rng = random.Random(seed)
    imputed: Counter[str] = Counter()
    agents = [_to_agent(i, row, rng, districts or ["城区"], imputed) for i, row in enumerate(clean, 1)]

    profiles = f"# {title} 生成式智能体 Profiles\n\n---\n" + "".join(
        _render_single_profile(agent["id"], agent) for agent in agents
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_rows": len(rows),
        "agents": len(agents),
        "columns": {
            h: (mapping[h] if mapping[h] and mapping[h] not in DROPPED_FIELDS else "dropped") for h in headers
        },
        "free_text": "dropped" if drop_free_text else "scrubbed",
        "scrubbed": scrubbed,
        "imputed": {k: v for k, v in imputed.items() if v},
        "salt": "provided" if salt else "random (not stored)",
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        # utf-8-sig: the simulator reads the state CSV with a BOM-aware codec.
        zf.writestr("agents.csv", _state_csv(agents).encode("utf-8-sig"))
        zf.writestr("profiles.md", profiles)
        zf.writestr("agents.jsonl", "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in agents))
        zf.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        zf.writestr("README.md", _README)
    return report
