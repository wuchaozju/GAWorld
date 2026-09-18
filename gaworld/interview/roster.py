"""Who is available to interview, across every city on disk.

The pool is deliberately read from the *bundles* rather than from the running
config. A city bundle is self-contained (``data/cities/<slug>/agents.csv`` +
``profiles.md``) and only one city is config-selected at a time, so building
the roster through the simulator's globals would show the residents of
exactly one city and make "跨城市" impossible by construction.

That has a consequence worth naming: this module reads the CSV and the
Markdown directly, with tolerant regexes, and never calls ``build_agent``.
It is a *catalogue*, not a simulation — it must not need a map, a memory
store, or a vector DB to tell you that 绍兴柯桥 has 80 residents. The real
agent, with its memory, is built later inside the per-city child process that
actually asks the questions.

Only the attributes that survive on disk can be breakdown axes. Notably
``industry`` cannot: it lives on the in-memory ``Person`` during synthesis and
is never written to the CSV or the profile, so offering it as an axis here
would silently bucket everyone into ``industry=none``. The axes below are the
ones that are really there.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from gaworld.group.cohort import MIN_COHORT_SIZE, partition_cohorts
from gaworld.interview.schema import Respondent
from gaworld.logging_setup import get_logger
from gaworld.population.schema import STATE_VAR_KEYS

_LOG = get_logger("gaworld.interview.roster")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Cohort axes offered by the panel — every one of them derivable from the
#: state CSV alone. See the module docstring on why ``industry`` is absent.
AVAILABLE_COHORT_AXES: tuple[str, ...] = ("age_band", "hukou", "gender", "district")

#: Default partition for a group interview. Age drives life stage, hukou
#: drives entitlement and belonging — the two axes a city survey most often
#: wants to cut by, and coarse enough to keep cohort counts (and therefore
#: cost) low.
DEFAULT_COHORT_AXES: tuple[str, ...] = ("age_band", "hukou")

#: The unnamed default world — the repo's own Hangzhou population, used when
#: no city bundle is selected. Its slug is the empty string throughout, which
#: is also what ``dashboard_config.json`` holds when no city is chosen.
DEFAULT_CITY_LABEL = "默认世界"

_PROFILE_SPLIT_RE = re.compile(r"^##\s*Profile\s*(\d+)\s*[｜|]\s*(.+)$", re.MULTILINE)
_JOB_RE = re.compile(r"\*\*职业与工作节奏\*\*：(.+)")


def _bundle(slug: str):
    from gaworld.city.bundle import CityNotFoundError, resolve_city

    try:
        return resolve_city(slug)
    except (CityNotFoundError, OSError, ValueError):
        return None


def _default_paths() -> tuple[Path, Path]:
    """CSV and profile paths for the default world, straight from config.

    Read at call time: the dashboard tests repoint these, and a module-level
    capture would grab the real ``data/`` before the patch landed.
    """
    from gaworld.settings import CONFIG

    csv_path = str(CONFIG.get("csv_path") or "data/hangzhou_agents_state_init.csv")
    md_path = str(CONFIG.get("md_path") or "data/hangzhou_profiles_with_names.md")
    return _abs(csv_path), _abs(md_path)


def _abs(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def city_paths(slug: str) -> tuple[Path, Path]:
    """``(agents.csv, profiles.md)`` for ``slug``; ``""`` = default world."""
    if not str(slug or "").strip():
        return _default_paths()
    bundle = _bundle(slug)
    if bundle is None:
        raise ValueError(f"找不到城市 {slug!r}")
    return bundle.state_csv_path, bundle.profiles_md_path


def _jobs_by_id(md_path: Path) -> dict[int, str]:
    """Occupation text per agent id, or ``{}`` when the file is unusable.

    Free text, not a taxonomy — shown to the user so they can tell two
    residents apart in the picker, never used as a breakdown axis.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    jobs: dict[int, str] = {}
    matches = list(_PROFILE_SPLIT_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end]
        job = _JOB_RE.search(block)
        if job:
            jobs[int(match.group(1))] = job.group(1).strip()[:60]
    return jobs


def load_population(slug: str) -> list[dict[str, Any]]:
    """Agent-shaped dicts for one city, read straight from its bundle.

    The shape matches what :func:`gaworld.group.cohort.partition_cohorts`
    expects (``id``, the axis attributes, and a ``state`` mapping), so the
    same rows serve both the individual picker and the cohort partition.
    """
    csv_path, md_path = city_paths(slug)
    if not csv_path.exists():
        return []
    jobs = _jobs_by_id(md_path)
    people: list[dict[str, Any]] = []
    # utf-8-sig: every population CSV in this repo carries a BOM, and reading
    # it as plain utf-8 turns the first column name into "﻿id".
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                agent_id = int(str(row.get("id") or "").strip())
            except (TypeError, ValueError):
                continue
            state = {}
            for key in STATE_VAR_KEYS:
                try:
                    state[key] = float(row.get(key, 0.5))
                except (TypeError, ValueError):
                    state[key] = 0.5
            try:
                age = int(float(row.get("age") or 0))
            except (TypeError, ValueError):
                age = 0
            people.append(
                {
                    "id": agent_id,
                    "name": str(row.get("name") or f"#{agent_id}").strip(),
                    "gender": str(row.get("gender") or "未知").strip(),
                    "age": age,
                    "hukou": str(row.get("hukou") or "未知").strip(),
                    "residence": str(row.get("residence") or "").strip(),
                    "job": jobs.get(agent_id, ""),
                    "state": state,
                }
            )
    return people


def _demographics(person: dict[str, Any], slug: str) -> dict[str, str]:
    from gaworld.group.cohort import COHORT_AXES

    return {
        "city": slug or "default",
        "age_band": str(COHORT_AXES["age_band"](person)),
        "gender": person.get("gender") or "未知",
        "hukou": person.get("hukou") or "未知",
        "district": str(COHORT_AXES["district"](person)),
    }


def agent_respondents(slug: str, agent_ids: list[int] | None = None) -> list[Respondent]:
    """Individual residents of ``slug``, optionally filtered to ``agent_ids``."""
    wanted = {int(i) for i in agent_ids} if agent_ids else None
    respondents: list[Respondent] = []
    for person in load_population(slug):
        if wanted is not None and person["id"] not in wanted:
            continue
        demographics = _demographics(person, slug)
        # City-qualified, because populations are generated from the same name
        # pool: a cross-city survey routinely picks two 闫然s, and a transcript
        # that lists both as "闫然（35岁·男）" is unreadable.
        label = f"{person['name']}（{person['age']}岁·{person['gender']}）"
        if slug:
            label = f"{slug}·{label}"
        respondents.append(
            Respondent(
                kind="agent",
                city=slug,
                ref=str(person["id"]),
                label=label,
                demographics=demographics,
                size=1,
            )
        )
    return respondents


def cohort_respondents(
    slug: str,
    *,
    axes: list[str] | None = None,
    cohort_ids: list[str] | None = None,
) -> list[Respondent]:
    """Group agents for ``slug``: one respondent per cohort of its population.

    The returned respondents carry their member ids, which is what lets the
    child process rebuild the exact group the user picked without repeating
    (and possibly disagreeing with) this partition.
    """
    people = load_population(slug)
    if not people:
        return []
    chosen = tuple(axes) if axes else DEFAULT_COHORT_AXES
    unknown = [axis for axis in chosen if axis not in AVAILABLE_COHORT_AXES]
    if unknown:
        raise ValueError(f"不支持的群体划分维度：{unknown}；可用：{list(AVAILABLE_COHORT_AXES)}")
    cohorts = partition_cohorts(people, axes=chosen, min_size=MIN_COHORT_SIZE)
    wanted = set(cohort_ids or [])
    respondents: list[Respondent] = []
    for cohort in cohorts:
        if wanted and cohort.id not in wanted:
            continue
        demographics = {"city": slug or "default"}
        for axis, value in zip(cohort.axes, cohort.key, strict=True):
            demographics[axis] = str(value)
        respondents.append(
            Respondent(
                kind="cohort",
                city=slug,
                ref=cohort.id,
                label=cohort.label(),
                demographics=demographics,
                size=cohort.size,
                members=list(cohort.members),
            )
        )
    return respondents


def city_catalogue() -> list[dict[str, Any]]:
    """Every interviewable city, with its population size.

    The default world comes first and always exists; bundles follow in slug
    order. A bundle with no population is listed with ``count: 0`` rather
    than hidden, so a user who just created a city can see why it has nobody
    to interview.
    """
    from gaworld.city.bundle import list_cities

    entries: list[dict[str, Any]] = []
    default_csv, _ = _default_paths()
    entries.append(
        {
            "slug": "",
            "name": DEFAULT_CITY_LABEL,
            "count": len(load_population("")) if default_csv.exists() else 0,
        }
    )
    for bundle in list_cities():
        try:
            count = len(load_population(bundle.slug))
        except (OSError, ValueError) as exc:
            _LOG.warning("roster: skipping city %s (%s)", bundle.slug, exc)
            continue
        entries.append({"slug": bundle.slug, "name": bundle.display_name, "count": count})
    return entries


def roster(cities: list[str] | None = None, *, axes: list[str] | None = None) -> dict[str, Any]:
    """The picker payload: individuals and cohorts for the named cities.

    ``cities`` defaults to every city on disk. Individuals are returned as
    plain rows (not respondents) because the panel needs a few extra display
    fields — job text, age — that a respondent does not carry.
    """
    catalogue = city_catalogue()
    known = {entry["slug"] for entry in catalogue}
    selected = [slug for slug in (cities or [entry["slug"] for entry in catalogue]) if slug in known]
    chosen_axes = list(axes or DEFAULT_COHORT_AXES)
    payload: dict[str, Any] = {
        "cities": catalogue,
        "axes": list(AVAILABLE_COHORT_AXES),
        "selected_axes": chosen_axes,
        "groups": [],
    }
    for slug in selected:
        people = load_population(slug)
        try:
            cohorts = cohort_respondents(slug, axes=chosen_axes)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        payload["groups"].append(
            {
                "slug": slug,
                "name": next((c["name"] for c in catalogue if c["slug"] == slug), slug),
                "agents": [
                    {
                        "ref": str(person["id"]),
                        "name": person["name"],
                        "age": person["age"],
                        "gender": person["gender"],
                        "hukou": person["hukou"],
                        "job": person["job"],
                        "district": _demographics(person, slug)["district"],
                        "age_band": _demographics(person, slug)["age_band"],
                    }
                    for person in people
                ],
                "cohorts": [respondent.to_dict() for respondent in cohorts],
            }
        )
    return payload


__all__ = [
    "AVAILABLE_COHORT_AXES",
    "DEFAULT_CITY_LABEL",
    "DEFAULT_COHORT_AXES",
    "agent_respondents",
    "city_catalogue",
    "city_paths",
    "cohort_respondents",
    "load_population",
    "roster",
]
