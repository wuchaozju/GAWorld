"""Populate a city bundle with agents.

Three ways in, all writing the same two files the simulator already reads
(``agents.csv`` + ``profiles.md`` inside the bundle):

``add_population``  bulk-synthesise residents via :mod:`gaworld.population`
``add_agent``       append one hand-specified agent
``migrate_agent``   copy an agent out of another bundle (or the default
                    ``data/`` corpus) and re-home it here

Where an agent physically lives and works is *not* stored in these files —
``gaworld.sim._location.assign_agent_locations`` picks real map nodes at
startup.  The ``residence`` column is narrative ("区·板块"), so the only thing
that has to follow the destination city is which districts it names.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
from pathlib import Path
from typing import Any

from gaworld.city.bundle import CityBundle
from gaworld.city.procedural import districts_from_spec
from gaworld.logging_setup import get_logger
from gaworld.population.generate import generate_population
from gaworld.population.schema import CSV_COLUMNS, STATE_VAR_KEYS, normalize_spec
from gaworld.population.synth import RESIDENCE_SUFFIXES
from gaworld.population.writer import render_profiles_markdown, render_state_csv

_LOG = get_logger("gaworld.city.agents")

#: Separates the profile blocks in a profiles Markdown file.
_PROFILE_SPLIT = re.compile(r"(?=^## Profile )", re.M)

#: The residence clause of a 基础信息 line. Mirrors the pattern
#: ``gaworld.sim.agents_loader.parse_profile`` reads with, so it matches both
#: the hand-authored corpus ("居住西湖区。") and generated profiles
#: ("居住于余杭·商品房。") — a literal string replace matches neither reliably.
_RESIDENCE_CLAUSE = re.compile(r"(居住(?:于)?)(.+?)([，。])")


class AgentError(RuntimeError):
    """Raised when agents could not be added to a bundle."""


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------

def city_districts(city: CityBundle) -> list[str]:
    """District names the city actually has, for narrative residences.

    Prefers the real map's node districts when the bundle has one, because
    those are genuine local place names; otherwise falls back to the hub
    districts declared in the procedural spec.
    """
    if city.map_mode == "real" and city.real_map_path.exists():
        try:
            data = json.loads(city.real_map_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        names = []
        for feature in data.get("features", []):
            properties = feature.get("properties") or {}
            if (feature.get("geometry") or {}).get("type") != "Point":
                continue
            if properties.get("kind") != "hub":
                continue
            name = str(properties.get("district") or properties.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
        if names:
            return names

    if city.virtual_map_path.exists():
        districts = districts_from_spec(city.virtual_map_path.read_text(encoding="utf-8"))
        if districts:
            return districts
    return [city.name]


# ---------------------------------------------------------------------------
# Existing-file IO
# ---------------------------------------------------------------------------

def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
    # utf-8-sig: the simulator reads the state CSV with a BOM-aware codec.
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")


def _profile_blocks(text: str) -> tuple[str, list[str]]:
    """Split a profiles Markdown file into ``(header, blocks)``."""
    parts = _PROFILE_SPLIT.split(text)
    if not parts:
        return "", []
    if parts[0].lstrip().startswith("## Profile "):
        return "", [part for part in parts if part.strip()]
    return parts[0], [part for part in parts[1:] if part.strip()]


def _max_id(rows: list[dict[str, str]]) -> int:
    best = 0
    for row in rows:
        try:
            best = max(best, int(row.get("id", 0)))
        except (TypeError, ValueError):
            continue
    return best


def _renumber_block(block: str, new_id: int) -> str:
    return re.sub(r"^## Profile \d+｜", f"## Profile {new_id:02d}｜", block, count=1)


def rewrite_residence(block: str, residence: str) -> tuple[str, str]:
    """Point a profile's residence clause at *residence*.

    Returns ``(new_block, previous_residence)``; the block is returned
    unchanged when it has no recognisable residence clause.
    """
    match = _RESIDENCE_CLAUSE.search(block)
    if not match:
        return block, ""
    previous = match.group(2)
    # A function replacement avoids re-interpreting backslashes or group
    # references that happen to appear in a place name.
    updated = _RESIDENCE_CLAUSE.sub(
        lambda m: f"{m.group(1)}{residence}{m.group(3)}", block, count=1
    )
    return updated, previous


def _sync_count(city: CityBundle) -> int:
    """Recount the CSV and write the total back into the manifest."""
    count = len(_read_rows(city.state_csv_path))
    population = city.manifest.setdefault("population", {})
    population["count"] = count
    population["state_csv"] = city.state_csv_path.name
    population["profiles_md"] = city.profiles_md_path.name
    return count


# ---------------------------------------------------------------------------
# Bulk synthesis
# ---------------------------------------------------------------------------

def add_population(
    city: CityBundle,
    *,
    size: int = 100,
    preset: str = "cn_county_town",
    seed: int | None = None,
    replace: bool = False,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Synthesise *size* residents into *city*.

    With ``replace=False`` (the default) the new batch is appended and its ids
    continue from the existing maximum.  Note that an appended batch forms its
    own households and social graph — it is not woven into the earlier one — so
    prefer a single larger generation when the whole city should be connected.

    ``size`` is clamped by :func:`normalize_spec` to the range the IPF sampler
    stays well-conditioned over (currently 20–5000).  The returned dict reports
    both ``requested`` and the ``added`` count so a caller asking for 8 people
    can see that it actually got 20.
    """
    districts = city_districts(city)
    raw: dict[str, Any] = {
        "preset": preset,
        "size": int(size),
        "name": city.slug,
        "geography": {"district_weights": {district: 1.0 / len(districts) for district in districts}},
    }
    if seed is not None:
        raw["seed"] = int(seed)
    if overrides:
        raw.update(overrides)

    spec = normalize_spec(raw)
    result = generate_population(spec)
    if not result.ok:
        blocking = [f.to_dict() for f in result.findings if getattr(f, "level", "") == "error"]
        raise AgentError(f"population generation failed validation: {blocking or result.findings}")

    new_csv = render_state_csv(result.people)
    new_md = render_profiles_markdown(spec, result.people, result.households)

    if replace or not city.state_csv_path.exists():
        city.state_csv_path.write_text(new_csv, encoding="utf-8-sig")
        city.profiles_md_path.write_text(new_md, encoding="utf-8")
        added = len(result.people)
        offset = 0
    else:
        existing_rows = _read_rows(city.state_csv_path)
        offset = _max_id(existing_rows)
        fresh_rows = list(csv.DictReader(io.StringIO(new_csv)))
        for row in fresh_rows:
            row["id"] = str(int(row["id"]) + offset)
        _write_rows(city.state_csv_path, existing_rows + fresh_rows)

        header, old_blocks = _profile_blocks(city.profiles_md_path.read_text(encoding="utf-8"))
        _, new_blocks = _profile_blocks(new_md)
        renumbered = [
            _renumber_block(block, offset + index + 1) for index, block in enumerate(new_blocks)
        ]
        city.profiles_md_path.write_text(header + "".join(old_blocks + renumbered), encoding="utf-8")
        added = len(fresh_rows)

    (city.directory / "population_manifest.json").write_text(
        json.dumps(result.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = _sync_count(city)
    city.record("population.add", added=added, total=total, preset=preset, seed=spec.seed, replace=replace)
    city.save()
    _LOG.info("added %d residents to %s (total %d)", added, city.slug, total)
    return {
        "requested": int(size),
        "added": added,
        "total": total,
        "seed": spec.seed,
        "findings": [f.to_dict() for f in result.findings],
    }


# ---------------------------------------------------------------------------
# Single agent
# ---------------------------------------------------------------------------

def _default_state(rng: random.Random) -> dict[str, float]:
    return {key: round(rng.uniform(0.35, 0.70), 2) for key in STATE_VAR_KEYS}


def _render_single_profile(agent_id: int, fields: dict[str, Any]) -> str:
    """One profile block in the exact shape ``parse_profile`` expects.

    The ``**基础信息**：…，NN岁，…居住…，`` punctuation is a parsing contract,
    not decoration — see ``gaworld/sim/agents_loader.py``.
    """
    state = fields["state"]
    income = fields.get("income_monthly") or 0
    income_text = f"月收入约 {income:,.0f} 元" if income else "目前没有工资性收入"
    return (
        f"\n## Profile {agent_id:02d}｜{fields['name']}\n"
        f"**基础信息**：{fields['gender']}，{fields['age']}岁，{fields['hukou']}户籍，"
        f"居住于{fields['residence']}。\n\n"
        f"**教育与收入背景**：{fields['education']}学历，{income_text}。\n\n"
        f"**职业与工作节奏**：{fields['job']}\n\n"
        f"**性格与情绪特征**：{fields['personality']}\n\n"
        f"**日常生活与生活习惯**：{fields['daily_life']}\n\n"
        f"**社交网络情况**：新迁入居民，当前社会关系较少。\n\n"
        f"**价值观与公共事务态度**：{fields['values']}\n\n"
        f"**研究增强变量初始化**：\n"
        f"- policy_sensitivity：{state['policy_sensitivity']:.2f}\n"
        f"- platform_dependence：{state['platform_dependence']:.2f}\n"
        f"- risk_preference：{state['risk_preference']:.2f}\n"
        f"- voice_propensity：{state['voice_propensity']:.2f}\n"
        f"- mobility_intent：{state['mobility_intent']:.2f}\n\n"
        f"**核心状态变量**：emotion {state['emotion']:.2f}｜stress {state['stress']:.2f}｜"
        f"econ_security {state['econ_security']:.2f}｜city_identity {state['city_identity']:.2f}\n"
        f"\n---\n"
    )


def add_agent(
    city: CityBundle,
    *,
    name: str,
    age: int,
    gender: str = "女",
    job: str = "自由职业",
    hukou: str = "本地",
    residence: str | None = None,
    education: str = "本科",
    income_monthly: float = 0.0,
    personality: str = "性格平和，情绪起伏不大，遇事偏向先观察再行动。",
    daily_life: str = "作息规律，日常以工作、家务和少量社交为主。",
    values: str = "对公共事务关注有限，除非直接影响到自己的生活才会去了解。",
    state: dict[str, float] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Append one agent to *city* and return its assigned id."""
    label = str(name or "").strip()
    if not label:
        raise AgentError("an agent name is required")

    rng = random.Random(seed if seed is not None else hash(label) & 0xFFFFFFFF)
    if not residence:
        districts = city_districts(city)
        residence = f"{rng.choice(districts)}·{rng.choice(RESIDENCE_SUFFIXES)}"

    resolved_state = dict(_default_state(rng))
    if state:
        resolved_state.update({k: float(v) for k, v in state.items() if k in STATE_VAR_KEYS})

    rows = _read_rows(city.state_csv_path)
    agent_id = _max_id(rows) + 1
    rows.append(
        {
            "id": str(agent_id),
            "name": label,
            "gender": gender,
            "age": str(int(age)),
            "hukou": hukou,
            "residence": residence,
            **{key: f"{resolved_state[key]:.2f}" for key in STATE_VAR_KEYS},
        }
    )
    _write_rows(city.state_csv_path, rows)

    fields = {
        "name": label,
        "gender": gender,
        "age": int(age),
        "hukou": hukou,
        "residence": residence,
        "education": education,
        "income_monthly": float(income_monthly),
        "job": job,
        "personality": personality,
        "daily_life": daily_life,
        "values": values,
        "state": resolved_state,
    }
    block = _render_single_profile(agent_id, fields)
    if city.profiles_md_path.exists():
        city.profiles_md_path.write_text(
            city.profiles_md_path.read_text(encoding="utf-8").rstrip("\n") + "\n" + block,
            encoding="utf-8",
        )
    else:
        header = f"# {city.name} 生成式智能体 Profiles\n\n---\n"
        city.profiles_md_path.write_text(header + block, encoding="utf-8")

    total = _sync_count(city)
    city.record("agent.add", agent_id=agent_id, name=label, total=total)
    city.save()
    _LOG.info("added agent %s (#%d) to %s", label, agent_id, city.slug)
    return {"id": agent_id, "name": label, "residence": residence, "total": total}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def migrate_agent(
    city: CityBundle,
    agent_id: int,
    *,
    source_csv: Path | str,
    source_md: Path | str,
    rehome: bool = True,
    seed: int | None = None,
) -> dict[str, Any]:
    """Copy agent *agent_id* out of a source corpus and into *city*.

    The agent keeps its state variables and biography but is given a new id in
    the destination bundle.  With ``rehome=True`` its ``residence`` is rewritten
    to a district the destination city actually has, so the profile does not
    claim it lives in a place that is not on the map.
    """
    source_rows = _read_rows(Path(source_csv))
    match = next((row for row in source_rows if str(row.get("id")) == str(agent_id)), None)
    if match is None:
        raise AgentError(f"agent {agent_id} not found in {source_csv}")

    source_text = Path(source_md).read_text(encoding="utf-8")
    _, blocks = _profile_blocks(source_text)
    prefix = f"## Profile {int(agent_id):02d}｜"
    block = next((b for b in blocks if b.lstrip().startswith(prefix)), None)
    if block is None:
        raise AgentError(f"no profile block for agent {agent_id} in {source_md}")

    row = dict(match)
    if rehome:
        rng = random.Random(seed if seed is not None else int(agent_id))
        districts = city_districts(city)
        new_residence = f"{rng.choice(districts)}·{rng.choice(RESIDENCE_SUFFIXES)}"
        row["residence"] = new_residence
        # The profile's own clause is the source of truth for the old value —
        # the CSV and the prose disagree in the hand-authored corpus.
        block, _ = rewrite_residence(block, new_residence)

    rows = _read_rows(city.state_csv_path)
    new_id = _max_id(rows) + 1
    row["id"] = str(new_id)
    rows.append(row)
    _write_rows(city.state_csv_path, rows)

    block = _renumber_block(block, new_id)
    if not block.startswith("\n"):
        block = "\n" + block
    if city.profiles_md_path.exists():
        city.profiles_md_path.write_text(
            city.profiles_md_path.read_text(encoding="utf-8").rstrip("\n") + "\n" + block,
            encoding="utf-8",
        )
    else:
        header = f"# {city.name} 生成式智能体 Profiles\n\n---\n"
        city.profiles_md_path.write_text(header + block, encoding="utf-8")

    total = _sync_count(city)
    city.record(
        "agent.migrate",
        source_id=int(agent_id),
        agent_id=new_id,
        name=row.get("name", ""),
        rehomed=bool(rehome),
        total=total,
    )
    city.save()
    _LOG.info("migrated agent %s → #%d in %s", agent_id, new_id, city.slug)
    return {"id": new_id, "source_id": int(agent_id), "name": row.get("name", ""), "total": total}


__all__ = [
    "AgentError",
    "add_agent",
    "add_population",
    "city_districts",
    "migrate_agent",
    "rewrite_residence",
]
