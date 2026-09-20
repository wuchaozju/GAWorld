"""Serialise a generated population into the files the simulator already reads.

The whole point of this format-matching exercise is that ``build_agent`` in
``generative_city_sim.py`` needs *no* changes: it wants one CSV row plus one
``## Profile NN｜Name`` Markdown block per agent, and that is exactly what
comes out of here.

Two details are easy to get wrong and both are load-bearing:

* the state CSV is read with ``encoding="utf-8-sig"``, so it must carry a BOM;
* ``parse_profile`` (``gaworld/sim/agents_loader.py``) extracts fields with
  regexes against the ``**基础信息**：…，NN岁，…居住…，`` shape, so the
  punctuation in the profile template is part of the contract.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

from gaworld.population.network import HouseholdRecord, WorkplaceRecord
from gaworld.population.schema import CSV_COLUMNS, STATE_VAR_KEYS, PopulationSpec
from gaworld.population.synth import Person

#: Phrase pools for the narrative sections. Generated profiles are templated
#: rather than LLM-authored: 500 LLM calls to write biographies would cost more
#: than the simulation they seed, and the fields ``parse_profile`` actually
#: reads are structural anyway.
_PERSONALITY = {
    "low_stress": "性格平和，情绪起伏不大，遇事偏向先观察再行动。",
    "high_stress": "对压力敏感，容易在工作节点和账单周期前后出现焦虑。",
    "outgoing": "外向健谈，习惯用社交排解情绪，朋友圈活跃。",
    "reserved": "偏内向，倾向独处消化情绪，很少主动表达不满。",
}
_DAILY = {
    "employed": "工作日节奏规律，通勤与工作占据主要时段；周末用于补觉、家务和少量社交。",
    "gig": "接单时间不固定，收入随单量波动，作息随平台高峰调整。",
    "student": "以学校课程和课后作业为主，周末有兴趣班或与同学活动。",
    "retired": "作息规律早起，日常以买菜、散步、社区活动和照看家人为主。",
    "unemployed": "白天时间较空，主要用于找工作、临时兼职和处理家事。",
    "homemaker": "以家庭照料为主，日常围绕采买、做饭和接送家人展开。",
}
_VALUES = {
    "high_voice": "关注公共事务，遇到不合理的情况会通过投诉或社交平台发声。",
    "low_voice": "对公共事务关注有限，除非直接影响到自己的生活才会去了解。",
}


def _profile_block(person: Person, household: HouseholdRecord | None) -> str:
    """One ``## Profile NN｜Name`` block matching the existing corpus format."""
    state = person.state
    personality_bits = [
        _PERSONALITY["high_stress"] if state["stress"] > 0.6 else _PERSONALITY["low_stress"],
        _PERSONALITY["outgoing"] if state["voice_propensity"] > 0.5 else _PERSONALITY["reserved"],
    ]
    if person.age < 18:
        daily_key = "student"
    elif person.employment == "employed":
        daily_key = "gig" if person.is_gig else "employed"
    elif person.age >= 65:
        daily_key = "retired"
    elif person.employment == "unemployed":
        daily_key = "unemployed"
    else:
        daily_key = "homemaker"

    if person.income_monthly > 0:
        income_text = f"月收入约 {person.income_monthly:,.0f} 元"
    else:
        income_text = "目前没有工资性收入"

    if household is not None:
        household_label = {
            "single": "独居",
            "couple": "与伴侣同住",
            "nuclear": "与配偶及子女同住",
            "single_parent": "单亲家庭，与子女同住",
            "multigen": "三代同堂",
            "shared_rental": "与室友合租",
        }.get(household.type, "与家人同住")
        social_text = (
            f"{household_label}（{len(household.member_ids)} 人户）；"
            f"当前在模拟内共有 {len(person.relationships)} 条社会关系。"
        )
    else:
        social_text = f"当前在模拟内共有 {len(person.relationships)} 条社会关系。"

    values_text = _VALUES["high_voice"] if state["voice_propensity"] > 0.5 else _VALUES["low_voice"]

    return (
        f"\n## Profile {person.id:02d}｜{person.name}\n"
        f"**基础信息**：{person.gender}，{person.age}岁，{person.hukou}户籍，"
        f"居住于{person.residence}。\n\n"
        f"**教育与收入背景**：{person.education}学历，{income_text}。\n\n"
        f"**职业与工作节奏**：{person.job}\n\n"
        f"**性格与情绪特征**：{''.join(personality_bits)}\n\n"
        f"**日常生活与生活习惯**：{_DAILY[daily_key]}\n\n"
        f"**社交网络情况**：{social_text}\n\n"
        f"**价值观与公共事务态度**：{values_text}\n\n"
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


def render_state_csv(people: list[Person]) -> str:
    """Rows in the exact column order of ``data/hangzhou_agents_state_init.csv``."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for person in people:
        writer.writerow(
            [
                person.id,
                person.name,
                person.gender,
                person.age,
                person.hukou,
                person.residence,
                *[f"{person.state[key]:.2f}" for key in STATE_VAR_KEYS],
            ]
        )
    return buffer.getvalue()


def render_profiles_markdown(
    spec: PopulationSpec, people: list[Person], households: list[HouseholdRecord]
) -> str:
    household_by_id = {h.id: h for h in households}
    header = (
        f"# {spec.name} 生成式智能体 Profiles（{len(people)}人）\n\n"
        f"> 由 `gaworld.population` 依据参数化人口规格自动生成"
        f"（preset={spec.preset}，seed={spec.seed}）。所有人物均为虚构。\n"
        f"> 结构与 `data/hangzhou_profiles_with_names.md` 一致，可直接被 `build_agent` 读取。\n\n"
        f"---\n"
    )
    blocks = [_profile_block(person, household_by_id.get(person.household_id)) for person in people]
    return header + "".join(blocks)


def build_manifest(
    spec: PopulationSpec,
    people: list[Person],
    households: list[HouseholdRecord],
    workplaces: list[WorkplaceRecord],
    report: dict[str, Any],
    findings: list[Any],
) -> dict[str, Any]:
    """Reproducibility record: spec, seeds, fit quality, validation outcome."""
    return {
        "generator": "gaworld.population",
        "schema_version": "1.0",
        "spec": spec.to_dict(),
        "counts": {
            "people": len(people),
            "households": len(households),
            "workplaces": len(workplaces),
            "household_types": dict(Counter(h.type for h in households)),
        },
        "report": report,
        "findings": [f.to_dict() for f in findings],
    }


def write_population(
    output_dir: Path | str,
    spec: PopulationSpec,
    people: list[Person],
    households: list[HouseholdRecord],
    workplaces: list[WorkplaceRecord],
    report: dict[str, Any],
    findings: list[Any],
) -> dict[str, Path]:
    """Write CSV + Markdown + manifest; return the paths actually written."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    csv_path = directory / f"{spec.name}_state_init.csv"
    md_path = directory / f"{spec.name}_profiles.md"
    manifest_path = directory / f"{spec.name}_manifest.json"

    # utf-8-sig: the simulator reads the state CSV with a BOM-aware codec.
    csv_path.write_text(render_state_csv(people), encoding="utf-8-sig")
    md_path.write_text(render_profiles_markdown(spec, people, households), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            build_manifest(spec, people, households, workplaces, report, findings),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"state_csv": csv_path, "profiles_md": md_path, "manifest": manifest_path}


__all__ = [
    "build_manifest",
    "render_profiles_markdown",
    "render_state_csv",
    "write_population",
]
