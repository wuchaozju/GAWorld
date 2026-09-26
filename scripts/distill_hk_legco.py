#!/usr/bin/env python3
"""Re-distil the Hong Kong LegCo residents of ``data/cities/香港`` from public sources.

Why this exists
---------------
Agents 101-190 of the 香港 bundle are the 90 members of the eighth Legislative
Council. They were created on 2026-09-18 through :func:`gaworld.city.agents.add_agent`
with only ``name`` / ``gender`` / ``age`` / ``job`` supplied, so every remaining
field fell back to that function's ordinary-resident defaults. All ninety ended
up with the **same four sentences**::

    教育与收入背景：本科学历，目前没有工资性收入。
    性格与情绪特征：性格平和，情绪起伏不大，遇事偏向先观察再行动。
    日常生活与生活习惯：作息规律，日常以工作、家务和少量社交为主。
    价值观与公共事务态度：对公共事务关注有限，除非直接影响到自己的生活才会去了解。

— a sitting legislator with no wage income who pays limited attention to public
affairs. Their nine state variables were ``uniform(0.35, 0.70)`` draws, so
``policy_sensitivity`` and ``voice_propensity`` averaged 0.53, indistinguishable
from a random resident. Not one of them carried a 思维框架 section, which means
no distillation output ever reached this city.

This script runs the real persona pipeline (:mod:`gaworld.persona`) per member
and writes the result back over the existing agent, rather than appending a
second copy.

Two phases, deliberately separate
---------------------------------
``distill``  research + distil each member into ``output/personas/<slug>/``.
             Slow (network + 3 model calls each), resumable, and touches
             nothing the simulator reads.
``apply``    rewrite the ``agents.csv`` row and the ``profiles.md`` block from
             what was saved. Fast, offline, re-runnable, reviewable as a diff.

The split mirrors ``gaworld.apps.persona_api``'s own rule: distilling is a
claim about a real person, and nothing about it should land in a running world
unreviewed.

Usage
-----
    python scripts/distill_hk_legco.py status
    python scripts/distill_hk_legco.py distill --ids 101,102      # trial
    python scripts/distill_hk_legco.py distill                    # all 90
    python scripts/distill_hk_legco.py apply --dry-run
    python scripts/distill_hk_legco.py apply
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gaworld.city.agents import _render_single_profile  # noqa: E402
from gaworld.city.bundle import resolve_city, slugify  # noqa: E402
from gaworld.io import legco_roster  # noqa: E402
from gaworld.persona import distill as distill_mod  # noqa: E402
from gaworld.persona import research as research_mod  # noqa: E402
from gaworld.persona import store as store_mod  # noqa: E402
from gaworld.persona.render import FRAMEWORK_HEADING, insert_block, profile_block  # noqa: E402
from gaworld.population.schema import CSV_COLUMNS, STATE_VAR_KEYS  # noqa: E402

CITY_REF = "香港"

#: Appended to the member's name before searching. Without it the engines
#: happily return a homonym — "李慧琼" alone brings back the deputy GM of a
#: coal-chemical company alongside the LegCo President — and the distiller can
#: only report that the material is about somebody else *after* the fact.
SUBJECT_SUFFIX = "香港立法會議員"

#: The relevance gate handed to :func:`research`. Every genuine source about a
#: sitting member names the body in one of these forms; the ad slots Baidu
#: returns above the real results (4399 flash games, 抖音, 爱奇艺, and a
#: 百度百科 entry for the *surname* 李) name none of them. Both character sets
#: are listed because the roster is traditional and the encyclopedia is not.
RELEVANCE_KEYWORDS = ("立法會", "立法会", "議員", "议员", "香港特區", "香港特区")

#: A Wikipedia search for a member with no article of their own lands on the
#: election that returned them — 90 biographies in one table. It passes the
#: keyword gate, reads like evidence, and is the single most likely way for one
#: member's record to be distilled into another's persona.
_NOT_A_BIOGRAPHY = re.compile(r"選舉|选举|列表|名單|名单|議會|议会$|^\d{4}年")

#: Which residents this script owns. Matched on the job line rather than an id
#: range so a re-run after the roster moves still finds the right people.
LEGCO_MARKER = re.compile(r"立法会议员|立法會議員")

#: agent id → persona slug, so ``apply`` knows which distillation belongs to
#: which resident without re-deriving it from a name that may have changed.
INDEX_PATH = REPO_ROOT / "output" / "personas" / "_hk_legco_index.json"

#: Suffixes the procedural residence sampler may attach that contradict the
#: job. A legislator in a 合租 flat is not impossible, but it was never a claim
#: anyone made — it is a leftover ``rng.choice``. The district half of the
#: string is kept: those are real mapped HK places.
IMPLAUSIBLE_SUFFIXES = ("合租", "青年公寓")
FALLBACK_SUFFIX = "自住房"

#: Written into 教育与收入背景 / 社交网络情况 when the evidence supported
#: nothing. Saying so is the point — the bug being fixed here is a template
#: that filled those lines with a confident falsehood instead.
UNKNOWN_TEXT = "公开资料未提及，待人工补充。"


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def _split_blocks(text: str) -> list[tuple[int, str, str]]:
    """``(agent_id, name, block_text)`` for every profile in the file."""
    out: list[tuple[int, str, str]] = []
    matches = list(re.finditer(r"^## Profile (\d+)｜(.+)$", text, re.M))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        out.append((int(match.group(1)), match.group(2).strip(), text[match.start():end]))
    return out


def targets(city: Any, ids: list[int] | None = None) -> list[tuple[int, str]]:
    text = city.profiles_md_path.read_text(encoding="utf-8")
    rows = [
        (agent_id, name)
        for agent_id, name, block in _split_blocks(text)
        if LEGCO_MARKER.search(block)
    ]
    if ids:
        wanted = set(ids)
        rows = [row for row in rows if row[0] in wanted]
    return rows


def _load_index() -> dict[str, str]:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_index(index: dict[str, str]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 1 — distil
# ---------------------------------------------------------------------------

def _biography_only_wiki_fn():
    """``default_wiki_fn`` with list and election articles refused."""
    inner = research_mod.default_wiki_fn()

    def lookup(name: str):
        entry = inner(name)
        if entry is not None and _NOT_A_BIOGRAPHY.search(entry.title):
            return None
        return entry

    return lookup


def distill_one(name: str, *, provider: str | None, quiet: bool = False):
    """Research and distil one member. Returns the saved ``PersonaProfile``."""
    from gaworld.apps.persona_api import _llm_fn

    legco_roster.install_ca_bundle()
    subject = f"{name} {SUBJECT_SUFFIX}"

    def note(fraction: float, message: str) -> None:
        if not quiet:
            print(f"      {fraction:4.0%} {message}", flush=True)

    dossier = research_mod.research(
        subject,
        search_fn=research_mod.default_search_fn({}),
        fetch_fn=research_mod.default_fetch_fn(),
        wiki_fn=_biography_only_wiki_fn(),
        keywords=RELEVANCE_KEYWORDS,
        progress=lambda f, m: note(0.5 * f, m),
    )

    # The Council's own record goes in front of everything the open web
    # returned. It is the only source that covers all ninety members — 73 of
    # them have no Chinese Wikipedia article at all — and it is the one that
    # carries the two facts the old template got flatly wrong: the office they
    # hold and what it pays. ``brief`` spends its budget on ``page`` documents
    # in order, so being first is what guarantees it survives truncation.
    official = legco_roster.brief_for(name)
    if official is not None:
        title, prose = official
        dossier.documents.insert(
            0,
            research_mod.Document(
                title=title,
                url="https://www.legco.gov.hk/tc/members/legco-members/members-profiles.html",
                text=prose,
                kind="page",
                query="legco-official",
            ),
        )
    else:
        print("      ⚠ 立法会官网无此人记录，仅用公开检索材料", flush=True)
    profile = distill_mod.distill(
        dossier,
        llm_fn=_llm_fn(provider or None),
        progress=lambda f, m: note(0.5 + 0.5 * f, m),
    )
    # The roster name wins over whatever the model resolved. The city writes
    # traditional characters and the encyclopedia writes simplified; renaming
    # the resident would orphan every reference the simulation already holds.
    profile.name = name
    profile.slug = slugify(name)
    store_mod.save(profile, dossier)
    return profile


def cmd_distill(args: argparse.Namespace) -> int:
    city = resolve_city(CITY_REF)
    rows = targets(city, args.ids)
    if args.limit:
        rows = rows[: args.limit]
    index = _load_index()

    done = failed = skipped = 0
    for position, (agent_id, name) in enumerate(rows, start=1):
        slug = slugify(name)
        if not args.force and store_mod.load(slug) is not None:
            index[str(agent_id)] = slug
            skipped += 1
            print(f"[{position}/{len(rows)}] #{agent_id} {name} — 已有画像，跳过", flush=True)
            continue
        print(f"[{position}/{len(rows)}] #{agent_id} {name} …", flush=True)
        started = time.time()
        # Two goes at the whole subject, not just at the JSON parse. Across a
        # ninety-member run the model returns an unusable answer for a handful
        # of them and succeeds on the identical prompt a second later; without
        # this those members would simply be missing from the result.
        profile = None
        for attempt in (1, 2):
            try:
                profile = distill_one(name, provider=args.provider, quiet=args.quiet)
                break
            except Exception as exc:  # noqa: BLE001 — one dead subject must not end the run
                print(f"      ✗ 第{attempt}次 {type(exc).__name__}: {exc}", flush=True)
                if args.traceback:
                    traceback.print_exc(limit=3)
                if attempt == 2:
                    failed += 1
        if profile is None:
            continue
        index[str(agent_id)] = profile.slug
        _save_index(index)
        done += 1
        print(
            f"      ✓ {time.time() - started:.0f}s｜证据 {profile.evidence_items} 条"
            f"（全文 {profile.evidence_pages} 篇）｜置信度 {profile.confidence}"
            f"｜心智模型 {len(profile.mental_models)}"
            + (f"｜⚠ {profile.framework_error}" if profile.framework_error else ""),
            flush=True,
        )

    _save_index(index)
    print(f"\n蒸馏完成：成功 {done}｜跳过 {skipped}｜失败 {failed}｜共 {len(rows)}")
    return 1 if failed and not done else 0


# ---------------------------------------------------------------------------
# Phase 1b — official-record-only profiles, no model involved
# ---------------------------------------------------------------------------

#: The provider refuses a prompt naming certain Hong Kong political figures —
#: ``input new_sensitive (1026)`` / ``output new_sensitive (1027)``, HTTP 500 —
#: deterministically, so retrying the same model never helps. Those members
#: still must not keep the ordinary-resident template, which asserts two things
#: the Council's own record disproves. This phase writes what the record
#: actually says and nothing else: no model, no mental models, and the gaps
#: labelled as gaps.
OFFICIAL_ONLY_NOTE = "官方简历未载，模型因内容策略拒绝处理本人题材，待人工补充。"


def _median_state_by_constituency() -> dict[str, dict[str, float]]:
    """Per-constituency-type medians of the members that *were* distilled.

    A role baseline taken from this very dataset rather than from judgement:
    the three groups separate the way the institution does — directly elected
    members score highest on ``voice_propensity``, functional-constituency
    members highest on ``econ_security`` — and every figure traces to a
    distillation that had the Council's record plus whatever the open web
    added.
    """
    import statistics

    index = _load_index()
    table = legco_roster.roster()
    groups: dict[str, list[dict[str, float]]] = {}
    for slug in index.values():
        profile = store_mod.load(slug)
        if profile is None or not profile.state:
            continue
        key = table.get(profile.name) or table.get(legco_roster.NAME_ALIASES.get(profile.name, ""))
        if not key:
            continue
        kind = (legco_roster.member_record(key) or {}).get("constituency_type") or ""
        if kind:
            groups.setdefault(kind, []).append(profile.state)
    return {
        kind: {key: round(statistics.median([s[key] for s in states]), 2) for key in STATE_VAR_KEYS}
        for kind, states in groups.items()
        if len(states) >= 5
    }


def _official_state(kind: str, name: str, baselines: dict[str, dict[str, float]]) -> dict[str, float]:
    """The group baseline, nudged per person so seventeen agents are not one.

    The nudge is ±0.04, derived from the name so it is stable across re-runs.
    It is cosmetic by design: identical state vectors would make these
    residents behave as a single actor in the simulation, and anything larger
    would be modelling a person the evidence does not describe.
    """
    import hashlib

    base = baselines.get(kind) or baselines.get("選舉委員會") or {key: 0.5 for key in STATE_VAR_KEYS}
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    out: dict[str, float] = {}
    for offset, key in enumerate(STATE_VAR_KEYS):
        jitter = (digest[offset] / 255.0 - 0.5) * 0.08
        out[key] = round(max(0.0, min(1.0, base.get(key, 0.5) + jitter)), 2)
    return out


def cmd_official(args: argparse.Namespace) -> int:
    from gaworld.persona.distill import PersonaProfile

    city = resolve_city(CITY_REF)
    rows = targets(city, args.ids)
    index = _load_index()
    baselines = _median_state_by_constituency()
    table = legco_roster.roster()
    print("界别基线（取自已蒸馏成员的中位数）：")
    for kind, state in sorted(baselines.items()):
        print(f"  {kind}: voice {state['voice_propensity']:.2f}｜policy {state['policy_sensitivity']:.2f}"
              f"｜econ {state['econ_security']:.2f}")

    written = 0
    for agent_id, name in rows:
        slug = slugify(name)
        if not args.force and store_mod.load(index.get(str(agent_id)) or slug) is not None:
            continue
        key = table.get(name) or table.get(legco_roster.NAME_ALIASES.get(name, ""))
        record = legco_roster.member_record(key) if key else {}
        official = legco_roster.brief_for(name)
        if not record or official is None:
            print(f"#{agent_id} {name} — 立法会官网无记录，跳过")
            continue

        kind = record.get("constituency_type") or ""
        seat = record.get("constituency") or kind or "未列"
        party = "、".join(legco_roster._listed(record.get("party"))) or "無黨派"
        occupation = "、".join(legco_roster._listed(record.get("occupation"))) or "未列"
        quals = "；".join(legco_roster._listed(record.get("qualification"))) or "官方简历未列"
        tier, monthly = legco_roster._salary_tier(record, key)
        links = legco_roster._listed(record.get("homepage"))

        profile = PersonaProfile(
            name=name,
            slug=slug,
            subject=f"{name} {SUBJECT_SUFFIX}",
            mode="name",
            summary=f"香港特區第八屆立法會議員（{seat}），{party}。",
            gender="",
            age=0,
            hukou="香港",
            residence="香港",
            job=(
                f"香港特別行政區第八屆立法會議員（任期自2026年1月1日起），{kind}／{seat}，"
                f"所屬政治團體：{party}；本職：{occupation}。須出席立法會及委員會會議、"
                f"審議法案與撥款，並處理選區／界別事務。"
            ),
            education_income=(
                f"{quals}。{tier}，每月酬金港幣 {monthly:,} 元，另享每年港幣 "
                f"{legco_roster.MEDICAL_ALLOWANCE_HKD:,} 元醫療津貼，任滿酬金為任內酬金總額的 15%"
                "（立法會秘書處《議員酬金及工作開支償還款額最高限額》，2026年1月）"
            ),
            personality=OFFICIAL_ONLY_NOTE,
            daily_life=(
                "於立法會綜合大樓辦事處及地區辦事處工作，按立法會會期出席大會與委員會會議，"
                "其餘時間處理選區／界別事務。"
            ),
            social_network=(
                f"所屬政治團體：{party}；經{kind}進入立法會，與同界別議員及選民／業界構成職務關係網絡。"
                + (f"公開帳號：{'、'.join(links)}。" if links else "")
            ),
            values=(
                "官方简历未载个人价值观表述。其职务本身即以公共事务为业："
                "须出席立法会及委员会会议、审议法案与拨款，并处理选区／界别事务。"
            ),
            state=_official_state(kind, name, baselines),
            big5={},
            sources=[{
                "title": official[0],
                "url": "https://www.legco.gov.hk/tc/members/legco-members/members-profiles.html",
                "kind": "page",
            }],
            unknown_fields=["age", "gender", "personality", "daily_life", "values"],
            evidence_pages=1,
            evidence_items=1,
            confidence="low",
            framework_error="模型因内容策略拒绝本人题材，本画像仅由立法会官方简历直接生成，未经蒸馏。",
            built_at=_utcnow(),
        )
        profile.boundaries = [
            "本画像仅由立法会官网的官方简历直接生成，未经模型蒸馏。",
            "因此没有心智模型、决策启发式与表达方式——这些需要本人的发言或访谈文本。",
            "状态变量取自同界别已蒸馏议员的中位数，是角色基线而非本人特征。",
            "年龄、性别、性格、日常生活沿用原有名册或标注为未载。",
        ]
        store_mod.save(profile)
        index[str(agent_id)] = slug
        written += 1
        print(f"#{agent_id} {name} ✓ {kind}／{seat}｜{party}｜月酬 {monthly:,}")

    _save_index(index)
    print(f"\n官方简历直写完成：{written} 人。")
    return 0


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Phase 2 — apply
# ---------------------------------------------------------------------------

def _residence(current: str, profile: Any) -> str:
    """Keep the mapped district, drop a suffix the job contradicts."""
    district, _, suffix = str(current or "").partition("·")
    if not district:
        return str(profile.residence or current or "")
    if suffix in IMPLAUSIBLE_SUFFIXES:
        return f"{district}·{FALLBACK_SUFFIX}"
    return current


def _grounded_age(row: dict[str, str], profile: Any) -> int:
    """The distilled age only when the evidence actually carried one.

    ``PersonaProfile._age`` substitutes 40 for anything unparseable, so a model
    that found no birth year returns a confident-looking forty. The roster age
    already in the CSV came from the original research pass and is right more
    often, so it wins unless the distillation says otherwise: ``unknown_fields``
    is the model's own report of what it could not ground.
    """
    if "age" in (profile.unknown_fields or []):
        return int(row["age"])
    age = int(profile.age or 0)
    return age if 16 <= age <= 95 else int(row["age"])


def _income_clause(name: str) -> str:
    """A salary sentence ``agents_loader._extract_income`` can actually read.

    The distilled prose states the remuneration the way the Council does —
    「每月酬金港幣 108,790 元」— and the loader's regex only matches
    ``月收入…元``, so all ninety profiles parsed to ``None`` and the economy
    went back to inventing a salary from the job text. Appending one normalised
    clause fixes that without rewriting a shared parser that every other city's
    corpus also goes through. The HKD original stays in the sentence: the
    converted figure is what the simulation spends, the official one is what a
    reader can check.
    """
    table = legco_roster.roster()
    # Two different keys, and mixing them silently costs the President her
    # salary tier: ``roster_name`` is what ``_salary_tier`` matches on, while
    # ``member_id`` is the LASS id the record is fetched with.
    roster_name = name if name in table else legco_roster.NAME_ALIASES.get(name, "")
    member_id = table.get(roster_name)
    if not member_id:
        return ""
    record = legco_roster.member_record(member_id)
    if not record:
        return ""
    tier, monthly_hkd = legco_roster._salary_tier(record, roster_name)
    cny = legco_roster.monthly_income_cny(monthly_hkd)
    return (
        f"按{tier}酬金计，月收入约 {cny:,} 元"
        f"（官方数额为港币 {monthly_hkd:,} 元／月，按 1 港元≈{legco_roster.HKD_TO_CNY} 元折算）。"
    )


def _fields(agent_id: int, row: dict[str, str], profile: Any) -> dict[str, Any]:
    education_income = (profile.education_income or "").strip()
    if education_income and not education_income.endswith(("。", "！", "？")):
        education_income += "。"
    clause = _income_clause(row["name"])
    if clause and "月收入" not in education_income:
        education_income = (education_income + clause) if education_income else clause
    social_network = (profile.social_network or "").strip()
    if social_network and not social_network.endswith(("。", "！", "？")):
        social_network += "。"
    return {
        "name": row["name"],
        "gender": profile.gender if profile.gender in ("男", "女") else row["gender"],
        "age": _grounded_age(row, profile),
        "hukou": row["hukou"],
        "residence": _residence(row["residence"], profile),
        "education": "本科",
        "income_monthly": 0.0,
        "education_income": education_income or UNKNOWN_TEXT,
        "job": profile.job or "香港特区立法会议员。",
        "personality": profile.personality or UNKNOWN_TEXT,
        "daily_life": profile.daily_life or UNKNOWN_TEXT,
        "values": profile.values or UNKNOWN_TEXT,
        "social_network": social_network or UNKNOWN_TEXT,
        "state": profile.state,
    }


def _render(agent_id: int, fields: dict[str, Any], profile: Any) -> str:
    """The replacement block: rendered profile + the distilled framework."""
    block = _render_single_profile(agent_id, fields).lstrip("\n")
    framework = profile_block(profile)
    if framework:
        block = insert_block(block, framework)
    return block.rstrip("\n") + "\n\n"


def cmd_apply(args: argparse.Namespace) -> int:
    city = resolve_city(CITY_REF)
    rows = targets(city, args.ids)
    index = _load_index()

    with city.state_csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    by_id = {int(row["id"]): row for row in csv_rows}
    text = city.profiles_md_path.read_text(encoding="utf-8")

    applied = missing = 0
    for agent_id, name in rows:
        slug = index.get(str(agent_id)) or slugify(name)
        profile = store_mod.load(slug)
        if profile is None:
            missing += 1
            print(f"#{agent_id} {name} — 无画像，跳过（先跑 distill）")
            continue
        row = by_id.get(agent_id)
        if row is None:
            missing += 1
            print(f"#{agent_id} {name} — CSV 无此行，跳过")
            continue

        fields = _fields(agent_id, row, profile)
        row["gender"] = fields["gender"]
        row["age"] = str(fields["age"])
        row["residence"] = fields["residence"]
        for key in STATE_VAR_KEYS:
            row[key] = f"{fields['state'][key]:.2f}"

        pattern = re.compile(
            rf"^## Profile {agent_id}｜.*?(?=^## Profile |\Z)", re.M | re.S
        )
        if not pattern.search(text):
            missing += 1
            print(f"#{agent_id} {name} — profiles.md 无此段，跳过")
            continue
        text = pattern.sub(lambda _m: _render(agent_id, fields, profile), text, count=1)
        applied += 1
        if args.verbose:
            print(f"#{agent_id} {name} ✓ 置信度 {profile.confidence}")

    if args.dry_run:
        print(f"\n[dry-run] 将更新 {applied} 人，跳过 {missing} 人。未写入任何文件。")
        return 0

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in csv_rows:
        writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
    city.state_csv_path.write_text(buffer.getvalue(), encoding="utf-8-sig")
    city.profiles_md_path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")

    city.record("agent.redistill", count=applied, source="persona", scope="legco")
    city.save()
    print(f"\n已更新 {applied} 人，跳过 {missing} 人。")
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    city = resolve_city(CITY_REF)
    rows = targets(city, args.ids)
    text = city.profiles_md_path.read_text(encoding="utf-8")
    blocks = {agent_id: block for agent_id, _name, block in _split_blocks(text)}

    have = framed = 0
    buckets: dict[str, int] = {}
    for agent_id, name in rows:
        profile = store_mod.load(slugify(name))
        if profile is not None:
            have += 1
            buckets[profile.confidence] = buckets.get(profile.confidence, 0) + 1
        if FRAMEWORK_HEADING in blocks.get(agent_id, ""):
            framed += 1
    print(f"城市：{city.name}（{city.directory}）")
    print(f"立法会议员：{len(rows)} 人")
    print(f"已蒸馏画像：{have} 份" + (f"（{buckets}）" if buckets else ""))
    print(f"profiles.md 中已带思维框架：{framed} 人")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ids", type=lambda s: [int(x) for x in s.split(",") if x.strip()],
                        help="只处理这些 agent id，逗号分隔")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("distill", help="检索并蒸馏（慢，联网）")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--force", action="store_true", help="已有画像也重跑")
    run.add_argument("--provider", default=None)
    run.add_argument("--quiet", action="store_true", help="不打印每一步进度")
    run.add_argument("--traceback", action="store_true")
    run.set_defaults(func=cmd_distill)

    write = sub.add_parser("apply", help="把画像写回城市（快，离线）")
    write.add_argument("--dry-run", action="store_true")
    write.add_argument("--verbose", action="store_true")
    write.set_defaults(func=cmd_apply)

    plain = sub.add_parser("official", help="只用立法会官方简历直写（不调模型）")
    plain.add_argument("--force", action="store_true", help="已有画像也覆盖")
    plain.set_defaults(func=cmd_official)

    show = sub.add_parser("status", help="看进度")
    show.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
