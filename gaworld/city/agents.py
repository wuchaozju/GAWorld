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
from gaworld.city.knowledge import CityProfile
from gaworld.city.locale import load_locale
from gaworld.city.procedural import districts_from_spec, seed_from_name
from gaworld.city.region import load_region
from gaworld.logging_setup import get_logger
from gaworld.population.generate import generate_population
from gaworld.population.schema import (
    CSV_COLUMNS,
    PRESETS,
    STATE_VAR_KEYS,
    EducationWork,
    normalize_spec,
)
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

#: The default daily-life sentence for a hand-added resident. Kept as a named
#: constant because it doubles as the marker for "the caller did not write
#: this person's day" — see :func:`add_agent`.
_DEFAULT_DAILY_LIFE = "作息规律，日常以工作、家务和少量社交为主。"

#: The daily-life line of a profile block. Non-greedy up to the blank line,
#: so the replacement cannot run past the section into the next one.
_DAILY_LINE = re.compile(r"(\*\*日常生活与生活习惯\*\*：)(.+?)(?=\n\n)", re.S)


def _local_habit(city: CityBundle, agent_id: int) -> str:
    """One local habit for a resident of *city*, chosen deterministically.

    The dossier's habits are the place's own — "晚饭吃笋干面"。 Which resident
    draws which habit is fixed by id, so the same city always produces the
    same residents. Only the general pool is used here: a hand-added or
    migrated resident's age and job are not always known, and a work habit
    ("骑电动车上下班") on a schoolchild reads as nonsense.
    """
    region = load_region(city)
    habits = list(region.habits) or list(region.work_habits)
    if not habits:
        return ""
    return habits[max(0, int(agent_id) - 1) % len(habits)]


def rewrite_daily_life(block: str, habit: str) -> str:
    """Append a local habit to a profile's daily-life line.

    Used when a resident moves: the person keeps their own routine but stops
    describing the food and the commute of the city they left.
    """
    addition = str(habit or "").strip()
    if not addition:
        return block
    match = _DAILY_LINE.search(block)
    if not match:
        return block
    base = match.group(2).rstrip()
    if not base.endswith(("。", "！", "？")):
        base += "。"
    return block[: match.start(2)] + f"{base}{addition}。" + block[match.end(2) :]


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
    updated = _RESIDENCE_CLAUSE.sub(lambda m: f"{m.group(1)}{residence}{m.group(3)}", block, count=1)
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
# City-shaped inputs
# ---------------------------------------------------------------------------


def _city_knowledge(city: CityBundle) -> CityProfile | None:
    """The city's economic profile, when it has one."""
    if not city.knowledge_path.exists():
        return None
    try:
        data = json.loads(city.knowledge_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return CityProfile.from_dict(data)


def _local_industry_mix(profile: CityProfile | None) -> dict[str, float]:
    """The job mix this city's industries imply, in the economy's six buckets.

    Only a **web-researched** profile qualifies. A map-derived profile folds
    every category it does not recognise into ``service``, which would put an
    entire town in the service sector — a confident answer built on a lossy
    mapping. Two categories minimum, for the same reason: one industry is not
    an economy.
    """
    if profile is None or profile.source != "web":
        return {}
    mix = profile.industry_mix()
    if len(mix) < 2:
        return {}
    return mix


def _blend_mix(base: dict[str, float], local: dict[str, float], *, weight: float = 0.65) -> dict[str, float]:
    """Blend the generic job mix with the city's own industries.

    The local mix wins the weight but never wipes the rest out: a town whose
    profile names two industries still needs teachers, doctors and shopkeepers,
    and a mix with zeroes in three categories would produce a town with no
    schools.
    """
    if not local:
        return {}
    mixed: dict[str, float] = {}
    for category in set(base) | set(local):
        mixed[category] = base.get(category, 0.0) * (1.0 - weight) + local.get(category, 0.0) * weight
    total = sum(mixed.values())
    if total <= 0:
        return {}
    return {key: round(value / total, 4) for key, value in mixed.items()}


def _preset_mix(preset: str | None) -> dict[str, float]:
    """The job mix the chosen preset starts from."""
    section = (PRESETS.get(preset or "cn_county_town", {}) or {}).get("education_work") or {}
    mix = section.get("industry_mix")
    if isinstance(mix, dict) and mix:
        return {key: float(value) for key, value in mix.items() if float(value) > 0}
    return dict(EducationWork().industry_mix)


def _merge_sections(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Merge two partial spec fragments, section by section.

    A shallow ``dict.update`` would let the region wipe out the locale's
    ``education_work`` block by replacing it wholesale with its own
    ``demography``-only fragment.
    """
    merged = dict(base)
    for section, values in (extra or {}).items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            combined = dict(merged[section])
            combined.update(values)
            merged[section] = combined
        else:
            merged[section] = values
    return merged


# ---------------------------------------------------------------------------
# Bulk synthesis
# ---------------------------------------------------------------------------


def add_population(
    city: CityBundle,
    *,
    size: int = 100,
    preset: str | None = None,
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

    The city's researched locale (``locale.json``, see
    :mod:`gaworld.city.locale`) always supplies the naming, housing and
    residency layer.  Its *demographic* suggestions are weaker: they apply only
    when ``preset`` is ``None``, because a caller who asked for
    ``aging_community`` means it, and they sit under ``overrides`` either way.

    The region's dossier (``region.json``, see :mod:`gaworld.city.region`)
    contributes the other half of "what a resident of this place is like":
    the local daily routine (food, commuting, habits), the local customs, and
    — when the city has a web-researched economic profile — the job mix its
    industries imply.  Demographic numbers from the dossier also apply only
    when ``preset`` is ``None``, for the same reason as the locale's.
    """
    locale = load_locale(city)
    region = load_region(city)
    districts = city_districts(city)
    raw: dict[str, Any] = {
        "preset": preset or "cn_county_town",
        "size": int(size),
        "name": city.slug,
        "geography": {"district_weights": {district: 1.0 / len(districts) for district in districts}},
    }
    if preset is None:
        # Safe as a shallow update: the locale only ever suggests demography /
        # education_work / income, and ``normalize_spec`` deep-merges each of
        # those partial sections onto the preset's own.
        raw.update(locale.suggested_overrides)
        # The dossier wins field by field: it was built from search evidence
        # about this place, while the locale's numbers came from one unsourced
        # model call.
        raw = _merge_sections(raw, region.suggested_overrides)
    # The job mix follows the city whether or not a preset was named: a preset
    # describes the *shape* of a population, the city describes what its
    # residents actually do for a living.
    local_mix = _local_industry_mix(_city_knowledge(city))
    if local_mix:
        mixed = _blend_mix(_preset_mix(preset), local_mix)
        if mixed:
            section = dict(raw.get("education_work") or {})
            section["industry_mix"] = mixed
            raw["education_work"] = section
    if seed is None:
        # The spec's own default is a fixed 42, which gave every city the same
        # residents id for id.  Derive it from the city instead, and from the
        # existing head count so an appended batch doesn't repeat the last one.
        existing = (
            0 if replace or not city.state_csv_path.exists() else _max_id(_read_rows(city.state_csv_path))
        )
        seed = seed_from_name(f"{city.slug}#{existing}") % (2**31)
    raw["seed"] = int(seed)
    if overrides:
        raw.update(overrides)

    spec = normalize_spec(raw)
    result = generate_population(spec, locale=locale)
    if not result.ok:
        blocking = [f.to_dict() for f in result.findings if getattr(f, "level", "") == "error"]
        raise AgentError(f"population generation failed validation: {blocking or result.findings}")

    new_csv = render_state_csv(result.people)
    new_md = render_profiles_markdown(spec, result.people, result.households, region.traits())

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
        renumbered = [_renumber_block(block, offset + index + 1) for index, block in enumerate(new_blocks)]
        city.profiles_md_path.write_text(header + "".join(old_blocks + renumbered), encoding="utf-8")
        added = len(fresh_rows)

    # The spec is recorded next to the report: the demographics and the job
    # mix are now partly the *city's* (the locale's and the region's
    # suggestions, the local industries), so a population can only be
    # reproduced from the numbers it was actually built with.
    manifest_payload = dict(result.report)
    manifest_payload["spec"] = spec.to_dict()
    (city.directory / "population_manifest.json").write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = _sync_count(city)
    city.record(
        "population.add",
        added=added,
        total=total,
        preset=spec.preset,
        locale=locale.code,
        seed=spec.seed,
        replace=replace,
    )
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

    ``education_income`` and ``social_network`` override the two lines this
    function used to state on its own authority. The defaults describe an
    ordinary new arrival, which is right for a hand-added resident and wrong
    for anyone the caller actually researched: stamping "目前没有工资性收入"
    and "新迁入居民" onto a distilled public figure is a factual claim the
    caller never made and could not previously suppress.
    """
    state = fields["state"]
    income = fields.get("income_monthly") or 0
    income_text = f"月收入约 {income:,.0f} 元" if income else "目前没有工资性收入"
    education_income = fields.get("education_income") or f"{fields['education']}学历，{income_text}。"
    social_network = fields.get("social_network") or "新迁入居民，当前社会关系较少。"
    return (
        f"\n## Profile {agent_id:02d}｜{fields['name']}\n"
        f"**基础信息**：{fields['gender']}，{fields['age']}岁，{fields['hukou']}户籍，"
        f"居住于{fields['residence']}。\n\n"
        f"**教育与收入背景**：{education_income}\n\n"
        f"**职业与工作节奏**：{fields['job']}\n\n"
        f"**性格与情绪特征**：{fields['personality']}\n\n"
        f"**日常生活与生活习惯**：{fields['daily_life']}\n\n"
        f"**社交网络情况**：{social_network}\n\n"
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
    education: str = "未知",
    student_status: str = "未知",
    income_monthly: float = 0.0,
    education_income: str = "",
    personality: str = "性格平和，情绪起伏不大，遇事偏向先观察再行动。",
    daily_life: str = _DEFAULT_DAILY_LIFE,
    values: str = "对公共事务关注有限，除非直接影响到自己的生活才会去了解。",
    social_network: str = "",
    state: dict[str, float] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Append one agent to *city* and return its assigned id."""
    label = str(name or "").strip()
    if not label:
        raise AgentError("an agent name is required")
    from gaworld.population.education import normalize_filters, sync_profile, validate_education

    attributes = normalize_filters({"education": education, "student_status": student_status})
    attributes = {key: value or "未知" for key, value in attributes.items() if key != "job"}
    validate_education(attributes["education"], attributes["student_status"], int(age))

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
            **attributes,
            "job": job,
            **{key: f"{resolved_state[key]:.2f}" for key in STATE_VAR_KEYS},
        }
    )
    _write_rows(city.state_csv_path, rows)

    # A hand-added resident gets the same local touch as a generated one, but
    # only when the caller did not write their day themselves: an explicit
    # ``daily_life`` is a deliberate statement about this person.
    if daily_life == _DEFAULT_DAILY_LIFE:
        habit = _local_habit(city, agent_id)
        if habit:
            daily_life = f"{daily_life.rstrip('。')}；{habit}"

    fields = {
        "name": label,
        "gender": gender,
        "age": int(age),
        "hukou": hukou,
        "residence": residence,
        "education": education,
        "income_monthly": float(income_monthly),
        "education_income": education_income,
        "job": job,
        "personality": personality,
        "daily_life": daily_life,
        "values": values,
        "social_network": social_network,
        "state": resolved_state,
    }
    block = sync_profile(_render_single_profile(agent_id, fields), attributes)
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
        # The old city's food and commute go with it: a resident of 临安 who
        # describes their days in the old city's terms is describing a place
        # they no longer live in.
        habit = _local_habit(city, int(agent_id))
        if habit:
            block = rewrite_daily_life(block, habit)

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
    "rewrite_daily_life",
    "rewrite_residence",
]
