"""Dashboard backend for Population Studio and group-mode simulation.

A *delegate* module, not more routes bolted into ``dashboard_server.py``: that
file is already ~1400 lines with a 60-branch if/elif routing chain, and the
group tier is a self-contained subsystem. ``dashboard_server`` gains six lines
of forwarding; everything else lives here.

Two design points worth stating, because both were mistakes waiting to happen:

**Path constants are read from ``dashboard_server`` at call time**, not
imported at module load. The existing dashboard tests work by monkeypatching
``ds.STATE_CSV_PATH`` onto a temp directory, and a ``from … import
STATE_CSV_PATH`` here would capture the real path before the patch lands and
quietly write into the user's ``data/`` during a test run.

**Generation and simulation are jobs, not request handlers.** Building 500
residents takes seconds and a group run takes longer; doing that inline would
hang the browser. The pattern follows the existing ``RUN_STATE`` precedent —
start a worker, return an id, poll for progress — rather than inventing a
third convention.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.population")

#: job id → job record. Bounded by :data:`_MAX_JOBS`; a dashboard left open for
#: a week should not accumulate every population it ever generated.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 20


# ---------------------------------------------------------------------------
# Job plumbing
# ---------------------------------------------------------------------------


def _new_job(kind: str) -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        # Drop the oldest finished jobs once we exceed the cap. Running jobs are
        # never evicted — losing the handle to work still in flight would leave
        # the UI polling an id that no longer exists.
        finished = [
            (record["started_at"], key) for key, record in _JOBS.items() if record["status"] != "running"
        ]
        while len(_JOBS) > _MAX_JOBS and finished:
            finished.sort()
            _, oldest = finished.pop(0)
            _JOBS.pop(oldest, None)
    return job_id


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is not None:
            record.update(fields)


def _run_in_background(job_id: str, work: Any) -> None:
    def runner() -> None:
        try:
            result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            _update_job(
                job_id,
                status="done",
                progress=1.0,
                message="完成",
                result=result,
                finished_at=time.time(),
            )
        except Exception as exc:
            _LOG.exception("population/group job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                finished_at=time.time(),
            )

    threading.Thread(target=runner, name=f"job-{job_id}", daemon=True).start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if not record:
            return None
        # `parse_constant` turns NaN/Infinity into null. Not cosmetic: the L2
        # detail carries a ratio of two Moran's I values that is NaN whenever
        # the reference signal sits under the noise floor, and Python emits a
        # bare `NaN` token that `JSON.parse` rejects outright — so one such key
        # made the browser throw away the *entire* verdict response.
        return json.loads(json.dumps(record, ensure_ascii=False), parse_constant=lambda _: None)


# ---------------------------------------------------------------------------
# Schema — served so the panel never re-declares the knobs
# ---------------------------------------------------------------------------


def _as_plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def population_schema() -> dict[str, Any]:
    """The panel's parameter contract, generated from the dataclasses.

    Served rather than duplicated in JavaScript. The nine state variables are
    currently declared twice already (``dashboard_server.STATE_VAR_KEYS`` and
    ``site/dashboard/studio.js``), and those two have to be kept in sync by
    hand; this endpoint exists so the population knobs never join them.
    """
    from gaworld.population import schema as pop_schema

    defaults = pop_schema.normalize_spec({})
    return {
        "version": "1.0",
        "presets": sorted(pop_schema.PRESETS),
        "state_var_keys": list(pop_schema.STATE_VAR_KEYS),
        "industries": list(pop_schema.INDUSTRIES),
        "education_levels": list(pop_schema.EDUCATION_LEVELS),
        "hukou_labels": list(pop_schema.HUKOU_LABELS),
        "cohort_axes": sorted(_cohort_axes()),
        "cohort_axis_labels": COHORT_AXIS_LABELS,
        "household_type_labels": HOUSEHOLD_TYPE_LABELS,
        "labels": LABELS,
        "preset_descriptions": PRESET_DESCRIPTIONS,
        "providers": _providers(),
        "defaults": defaults.to_dict(),
        "ranges": {
            "size": {"min": 20, "max": 5000},
            "days": {"min": 1, "max": 90},
            "materialization_budget": {"min": 0, "max": 500},
            "audit_fraction": {"min": 0.0, "max": 0.25},
            "network_coupling": {"min": 0.0, "max": 2.0},
        },
        "notes": {
            "network_coupling": (
                "群内零均值的社交图耦合项：cohort 层保留均值，社交图决定群内谁动得多。"
                "0 = 关闭（Phase 3 的 L2 未通过状态）。0.7 是针对验证门参照过程标定的，"
                "换成真实 LLM 个体层需重新标定。"
            ),
            "materialization_budget": (
                "每天按完整个体保真度运行的人数。群体层几乎不花钱，总成本几乎完全由这个数决定。"
            ),
        },
    }


def _cohort_axes() -> list[str]:
    from gaworld.group.cohort import COHORT_AXES

    return list(COHORT_AXES)


def _providers() -> list[dict[str, Any]]:
    """Configured LLM backends, so the panel's model picker is real.

    Falls back to an empty list rather than raising: a provider registry that
    cannot be read should degrade the picker, not break the whole panel.
    """
    try:
        from gaworld.llm.providers import available_providers

        return list(available_providers())
    except Exception:  # a broken LLM config must not break the whole panel
        _LOG.warning("could not read the LLM provider registry", exc_info=True)
        return []


#: Human-readable label for each cohort axis. The raw names are fine in code
#: and useless in a UI.
COHORT_AXIS_LABELS: dict[str, str] = {
    "age_band": "年龄段 Age band",
    "industry": "行业 Industry",
    "hukou": "户籍 Hukou",
    "employment": "就业状态 Employment",
    "gender": "性别 Gender",
    "district": "居住区 District",
}

#: Household type in Chinese. The roster lists one row per generated resident,
#: and ``shared_rental`` in a Chinese table is an identifier leaking into the
#: UI. Served for the same reason as the knob schema: the panel must not keep
#: its own copy of an enum declared in ``gaworld.population.schema``.
HOUSEHOLD_TYPE_LABELS: dict[str, str] = {
    "single": "独居",
    "couple": "夫妻二人",
    "nuclear": "核心家庭",
    "single_parent": "单亲家庭",
    "multigen": "三代同堂",
    "shared_rental": "合租",
}

#: Bilingual labels for everything the panel displays, keyed by the internal
#: name. Served from here for the same reason as the knob schema: the panel had
#: started drifting into a mix of Chinese for some metrics and raw English
#: identifiers for others, and a label map that lives in two places drifts
#: again. ``zh`` is the human name, ``en`` is the identifier a reader will meet
#: in the code, the CSV header and the papers.
LABELS: dict[str, dict[str, str]] = {
    # nine state variables
    "emotion": {"zh": "情绪", "en": "emotion"},
    "stress": {"zh": "压力", "en": "stress"},
    "econ_security": {"zh": "经济安全感", "en": "econ_security"},
    "city_identity": {"zh": "城市认同", "en": "city_identity"},
    "policy_sensitivity": {"zh": "政策敏感度", "en": "policy_sensitivity"},
    "platform_dependence": {"zh": "平台依赖", "en": "platform_dependence"},
    "risk_preference": {"zh": "风险偏好", "en": "risk_preference"},
    "voice_propensity": {"zh": "发声倾向", "en": "voice_propensity"},
    "mobility_intent": {"zh": "迁移意愿", "en": "mobility_intent"},
    # target-vs-achieved metrics
    "median_age": {"zh": "中位年龄", "en": "median_age"},
    "share_under_18": {"zh": "未成年人占比", "en": "share_under_18"},
    "share_over_65": {"zh": "65 岁以上占比", "en": "share_over_65"},
    "migrant_share": {"zh": "外地户籍占比", "en": "migrant_share"},
    "employment_rate": {"zh": "就业率", "en": "employment_rate"},
    "tertiary_rate": {"zh": "大专以上学历", "en": "tertiary_rate"},
    "income_median": {"zh": "月收入中位数", "en": "income_median"},
    "income_gini": {"zh": "收入差距（基尼）", "en": "income_gini"},
    "household_mean_size": {"zh": "户均人数", "en": "household_mean_size"},
    "share_single_person": {"zh": "独居家庭占比", "en": "share_single_person"},
    "share_multigen": {"zh": "三代同堂占比", "en": "share_multigen"},
    "share_shared_rental": {"zh": "合租家庭占比", "en": "share_shared_rental"},
    "mean_degree": {"zh": "人均社交关系数", "en": "mean_degree"},
    # cost / run stats
    "population": {"zh": "居民数", "en": "population"},
    "cohorts": {"zh": "群体数", "en": "cohorts"},
    "group_llm_calls": {"zh": "实际模型调用", "en": "group_llm_calls"},
    "individual_agent_days": {"zh": "详细模拟人-天", "en": "individual_agent_days"},
    "savings_factor": {"zh": "成本对比", "en": "savings_factor"},
    "max_residual_l1": {"zh": "误差信号", "en": "max_residual_l1"},
    # validation layers
    "L1": {"zh": "整体分布", "en": "L1 distributional"},
    "L2": {"zh": "邻里影响", "en": "L2 network"},
    "L3": {"zh": "边缘人群", "en": "L3 tails"},
    "L4": {"zh": "政策反应", "en": "L4 causal"},
}

#: What each preset actually is. Shown when the user selects it — a bare
#: identifier like "college_town" tells them nothing about what they are
#: about to generate.
PRESET_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "cn_county_town": {
        "title": "中国县城 / 普通城区",
        "summary": "最接近“平均”的一座小城：中位年龄 36 岁，就业率 68%，月收入中位数 6500 元，服务业和贸易占一半以上。",
        "use_when": "不确定选什么时就用它——它是其余预设的基准线。",
    },
    "cn_tier1_district": {
        "title": "一线城市城区",
        "summary": "年轻、高学历、互联网与金融密集：中位年龄 34 岁，高等教育率 52%，月收入中位数 11000 元，外来人口 55%，合租比例高。",
        "use_when": "想研究高流动性、高房租压力、平台经济相关的问题。",
    },
    "aging_community": {
        "title": "老龄化社区",
        "summary": "中位年龄 52 岁，65 岁以上占 34%，就业率仅 42%，医疗与服务业占比高，收入低且更平均。",
        "use_when": "想研究养老、医疗负担、代际同住、退休后社交收缩。",
    },
    "college_town": {
        "title": "大学城",
        "summary": "极年轻且高学历：中位年龄 27 岁，高等教育率 80%，教育行业占三分之一，45% 的人合租，收入低但差距小。",
        "use_when": "想研究青年群体、合租与流动、校园周边的信息传播。",
    },
    "us_suburb": {
        "title": "美国式郊区",
        "summary": "家庭为主：少儿占 23%，自有住房 72%，户均 2.5 人，外来人口少，但收入差距最大（基尼 0.48）。",
        "use_when": "想研究家庭结构、通勤、以及不平等较高的社区。",
    },
    "custom": {
        "title": "自定义",
        "summary": "从当前参数出发，任何一个旋钮被改动后都会自动切到这里。",
        "use_when": "你已经知道自己要什么。",
    },
}


# ---------------------------------------------------------------------------
# Population: feasibility preview + generation
# ---------------------------------------------------------------------------


def preview_population(payload: dict[str, Any]) -> dict[str, Any]:
    """Pure-maths feasibility check. Cheap enough to run on every keystroke.

    Generates nobody — this is the "your knobs contradict each other, and here
    is which one to move" path, which has to answer instantly to be useful
    while the user is still dragging a slider.
    """
    from gaworld.population.schema import (
        check_feasibility,
        household_size_bounds,
        median_age_bounds,
        normalize_spec,
    )

    spec = normalize_spec(payload.get("spec") or payload)
    issues = [issue.to_dict() for issue in check_feasibility(spec)]
    low, high = household_size_bounds(spec)
    min_median, max_median = median_age_bounds(spec)
    return {
        "spec": spec.to_dict(),
        "issues": issues,
        "has_errors": any(i["level"] == "error" for i in issues),
        "bounds": {
            "household_mean_size": {"min": low, "max": high},
            "median_age": {"min": min_median, "max": max_median},
        },
    }


def start_population_job(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.population.schema import normalize_spec

    spec = normalize_spec(payload.get("spec") or payload)
    # Resolve the write target *before* the job starts, so a rejected path is a
    # 400 on the request rather than a 202 followed by a failure the caller only
    # discovers by polling. Validation that happens inside the worker is
    # validation the client cannot act on.
    resolved_out = _output_dir(payload) if payload.get("write") else None
    job_id = _new_job("pop")

    def work(report: Any) -> dict[str, Any]:
        from gaworld.population.generate import generate_population
        from gaworld.population.report import worst_gaps

        report(0.1, f"正在合成 {spec.size} 位居民…")
        result = generate_population(spec)
        report(0.8, "正在校验…")
        payload_out: dict[str, Any] = {
            "spec": spec.to_dict(),
            "report": result.report,
            "feasibility": [i.to_dict() for i in result.feasibility],
            "findings": [f.to_dict() for f in result.findings],
            "ok": result.ok,
            "worst_gaps": worst_gaps(result.report),
            "people": [
                {
                    "id": p.id,
                    "name": p.name,
                    "gender": p.gender,
                    "age": p.age,
                    "hukou": p.hukou,
                    "residence": p.residence,
                    "job": p.job,
                    "industry": p.industry,
                    "employment": p.employment,
                    "income_monthly": p.income_monthly,
                    "household_type": p.household_type,
                    "state": p.state,
                }
                for p in result.people
            ],
        }
        if resolved_out:
            report(0.9, "正在写出文件…")
            written = result.write(resolved_out)
            payload_out["written"] = _describe_written(written)
        _remember_population(job_id, result)
        return payload_out

    _run_in_background(job_id, work)
    return {"job_id": job_id, "status": "running"}


def _output_dir(payload: dict[str, Any]) -> str:
    """Resolve the write target, refusing to escape the repository.

    The dashboard serves ``REPO_ROOT`` statically and accepts this path from
    the browser, so an unchecked value would be an arbitrary-write hole. The
    collaboration endpoints already guard their paths this way.
    """
    import os

    from gaworld.apps import dashboard_server as ds

    raw = str(payload.get("out_dir") or "output/population").strip()
    root = os.path.realpath(ds.REPO_ROOT)
    target = os.path.realpath(os.path.join(root, raw))
    if not (target == root or target.startswith(root + os.sep)):
        raise ValueError("out_dir 必须位于仓库目录内")
    return target


#: How many lines of each written file to inline as a preview. Enough to see
#: the header plus a few real rows; not so much that the JSON payload balloons.
_PREVIEW_LINES = 12


def _describe_written(written: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn written paths into something the browser can actually open.

    The dashboard already serves ``REPO_ROOT`` statically, so a repo-relative
    URL is directly clickable — returning only an absolute filesystem path
    leaves the user to go hunting in a file manager. A short inline preview is
    included as well, because "did it write what I expected?" is the question
    immediately after "where is it?".
    """
    import os

    from gaworld.apps import dashboard_server as ds

    root = os.path.realpath(ds.REPO_ROOT)
    labels = {
        "state_csv": ("状态表 State CSV", "每人一行：id、姓名、年龄、户籍、住处 + 九个状态变量"),
        "profiles_md": ("人物志 Profiles", "每人一段自然语言画像，仿真器读它来了解这个人"),
        "manifest": ("生成记录 Manifest", "完整参数、拟合报告、校验结果——复现这批人靠它"),
    }
    out: list[dict[str, Any]] = []
    for key, path in written.items():
        real = os.path.realpath(str(path))
        rel = os.path.relpath(real, root) if real.startswith(root + os.sep) else None
        label, hint = labels.get(key, (key, ""))
        try:
            size = os.path.getsize(real)
        except OSError:
            size = 0
        out.append(
            {
                "key": key,
                "label": label,
                "hint": hint,
                "path": str(path),
                # Forward slashes: this becomes a URL, and the handler serves
                # POSIX-style paths regardless of host OS.
                "url": ("/" + rel.replace(os.sep, "/")) if rel else None,
                "bytes": size,
                "preview": _preview_lines(real),
            }
        )
    return out


def _preview_lines(path: str) -> str:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            lines = []
            for index, line in enumerate(handle):
                if index >= _PREVIEW_LINES:
                    lines.append("…")
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines)
    except OSError as exc:
        return f"（无法读取预览：{exc}）"


#: The most recent generated population, kept so a group run can follow a
#: generation without the browser shipping 500 agent records back to us.
_LAST_POPULATION: dict[str, Any] = {}


def _remember_population(job_id: str, result: Any) -> None:
    _LAST_POPULATION.clear()
    _LAST_POPULATION.update(
        {
            "job_id": job_id,
            # The whole result, kept so a download can be rendered later
            # (:func:`export_population`) without regenerating the population —
            # the flattened ``agents`` below drop the education, job, household
            # and relationship fields the profile Markdown is built from.
            "generated": result,
            "agents": [
                {
                    "id": p.id,
                    "name": p.name,
                    "age": p.age,
                    "gender": p.gender,
                    "hukou": p.hukou,
                    "industry": p.industry,
                    "employment": p.employment,
                    "residence": p.residence,
                    "district": p.district,
                    "state": dict(p.state),
                }
                for p in result.people
            ],
            "neighbours": {int(k): list(v) for k, v in result.neighbours.items()},
        }
    )


# ---------------------------------------------------------------------------
# Download the generated agents
# ---------------------------------------------------------------------------

#: ``format`` → (filename suffix, MIME type, needs a BOM). Same three artefacts
#: as writing to disk, so a download is a drop-in replacement for
#: ``CONFIG["csv_path"]`` / ``CONFIG["md_path"]``.
_EXPORT_FORMATS: dict[str, tuple[str, str, bool]] = {
    # utf-8-sig: the simulator reads the state CSV BOM-aware, and Excel needs
    # the BOM to open Chinese names without mojibake.
    "csv": ("state_init.csv", "text/csv; charset=utf-8", True),
    "md": ("profiles.md", "text/markdown; charset=utf-8", False),
    "json": ("manifest.json", "application/json; charset=utf-8", False),
}


def export_population(fmt: str) -> dict[str, Any]:
    """Render the last generated population as a file the browser can save.

    Rendering happens here rather than in the panel so the CSV column order and
    the profile template stay declared once, in ``gaworld.population.writer``.
    Nothing is written to disk: this is the "let me look at these agents / take
    them with me" path, separate from the deliberate save in step 5.
    """
    from gaworld.population.writer import (
        build_manifest,
        render_profiles_markdown,
        render_state_csv,
    )

    result = _LAST_POPULATION.get("generated")
    if result is None:
        raise ValueError("还没有生成人口，请先在「人口结构」步骤生成。")
    if fmt not in _EXPORT_FORMATS:
        raise ValueError(f"不支持的导出格式：{fmt}")

    suffix, content_type, bom = _EXPORT_FORMATS[fmt]
    if fmt == "csv":
        content = render_state_csv(result.people)
    elif fmt == "md":
        content = render_profiles_markdown(result.spec, result.people, result.households)
    else:
        content = json.dumps(
            build_manifest(
                result.spec,
                result.people,
                result.households,
                result.workplaces,
                result.report,
                result.findings,
            ),
            ensure_ascii=False,
            indent=2,
        )
    return {
        "format": fmt,
        "filename": f"{result.spec.name}_{suffix}",
        "content_type": content_type,
        "bom": bom,
        "bytes": len(content.encode("utf-8")),
        "content": content,
    }


# ---------------------------------------------------------------------------
# Group simulation
# ---------------------------------------------------------------------------


def start_group_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Run group mode over the last generated population (or a fresh one)."""
    from gaworld.population.schema import normalize_spec

    source = str(payload.get("source") or "last")
    if source == "last" and not _LAST_POPULATION.get("agents"):
        return {"error": "还没有生成人口，请先在「人口结构」步骤生成。"}

    spec = normalize_spec(payload.get("spec") or {})
    days = max(1, min(90, int(payload.get("days", 7) or 7)))
    budget = max(0, min(500, int(payload.get("materialization_budget", 20) or 0)))
    audit = max(0.0, min(0.25, float(payload.get("audit_fraction", 0.03) or 0.0)))
    coupling = max(0.0, min(2.0, float(payload.get("network_coupling", 0.0) or 0.0)))
    use_llm = bool(payload.get("use_llm", False))
    provider = str(payload.get("provider") or "").strip() or None
    axes = payload.get("cohort_axes") or None
    focal = [int(i) for i in (payload.get("focal_ids") or []) if str(i).strip()]

    job_id = _new_job("group")

    def work(report: Any) -> dict[str, Any]:
        import copy

        from gaworld.group.driver import GroupRunConfig, render_day_block, run_group_simulation

        if source == "last":
            agents = copy.deepcopy(_LAST_POPULATION["agents"])
            neighbours = _LAST_POPULATION["neighbours"]
        else:
            report(0.05, "正在合成人口…")
            from gaworld.population.generate import generate_population

            generated = generate_population(spec)
            agents = [
                {
                    "id": p.id,
                    "name": p.name,
                    "age": p.age,
                    "gender": p.gender,
                    "hukou": p.hukou,
                    "industry": p.industry,
                    "employment": p.employment,
                    "residence": p.residence,
                    "district": p.district,
                    "state": dict(p.state),
                }
                for p in generated.people
            ]
            neighbours = {int(k): list(v) for k, v in generated.neighbours.items()}

        report(0.2, f"{len(agents)} 人，正在划分群体…")
        cfg = GroupRunConfig(
            days=days,
            cohort_axes=tuple(axes) if axes else None,
            materialization_budget=budget,
            audit_fraction=audit,
            focal_ids=focal,
            use_llm=use_llm,
            seed=int(payload.get("seed", 1) or 1),
            network_coupling=coupling,
        )
        llm_fn = None
        if use_llm:
            from gaworld.llm import providers as llm_providers

            if provider:
                # Honour the panel's choice explicitly. Falling back to the
                # config's routing here would make the model picker a lie.
                def llm_fn(prompt: str, task: str | None = None, agent_id: Any = None) -> str:
                    return str(
                        llm_providers.call_llm(prompt, task=task, agent_id=agent_id, provider=provider)
                    )

            else:
                llm_fn = llm_providers.call_llm

        report(0.3, f"正在运行 {days} 天群体模拟…")
        result = run_group_simulation(
            agents, cfg, llm_fn=llm_fn, neighbours=neighbours if coupling > 0 else None
        )
        report(0.9, "正在汇总…")
        return {
            "cost": result.cost_summary(),
            "cohorts": [
                {
                    "id": c.id,
                    "label": c.label(),
                    "size": c.size,
                    "centroid": c.centroid,
                    "dispersion": c.dispersion,
                    "memory": c.memory[-3:],
                }
                for c in result.cohorts
            ],
            "days": [d.to_dict() for d in result.days],
            "day_blocks": [render_day_block(result, d.day) for d in result.days],
            "max_residual_l1": max((d.max_residual_l1 for d in result.days), default=0.0),
            "network_coupling": coupling,
            "provider": provider,
            "used_llm": use_llm,
        }

    _run_in_background(job_id, work)
    return {"job_id": job_id, "status": "running"}


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------


def start_validation_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the L1-L4 gate from the panel.

    Exposed in the UI because the gate's verdict is the thing that says *which
    research questions* a group run can answer. Reading a cost saving without
    it invites treating group mode as a free lunch.
    """
    from gaworld.population.schema import normalize_spec

    spec = normalize_spec(payload.get("spec") or {})
    days = max(1, min(60, int(payload.get("days", 14) or 14)))
    budget = max(0, min(500, int(payload.get("materialization_budget", 20) or 0)))
    coupling = max(0.0, min(2.0, float(payload.get("network_coupling", 0.0) or 0.0)))
    job_id = _new_job("validate")

    def work(report: Any) -> dict[str, Any]:
        from gaworld.group.validate import render_verdict, run_validation

        if _LAST_POPULATION.get("agents"):
            import copy

            agents = copy.deepcopy(_LAST_POPULATION["agents"])
            neighbours = _LAST_POPULATION["neighbours"]
        else:
            report(0.05, "正在合成人口…")
            from gaworld.population.generate import generate_population

            generated = generate_population(spec)
            agents = [
                {
                    "id": p.id,
                    "name": p.name,
                    "age": p.age,
                    "gender": p.gender,
                    "hukou": p.hukou,
                    "industry": p.industry,
                    "employment": p.employment,
                    "residence": p.residence,
                    "district": p.district,
                    "state": dict(p.state),
                }
                for p in generated.people
            ]
            neighbours = {int(k): list(v) for k, v in generated.neighbours.items()}

        report(0.2, "正在跑配对实验（多种子）…")
        verdict = run_validation(
            agents,
            neighbours,
            days=days,
            seed=int(payload.get("seed", 1) or 1),
            materialization_budget=budget,
            network_coupling=coupling,
        )
        return {"verdict": verdict.to_dict(), "text": render_verdict(verdict)}

    _run_in_background(job_id, work)
    return {"job_id": job_id, "status": "running"}


# ---------------------------------------------------------------------------
# Routing surface consumed by dashboard_server
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    if path == "/api/population/schema":
        return population_schema(), 200
    if path.startswith("/api/population/jobs/"):
        record = job_status(path.rsplit("/", 1)[-1])
        if record is None:
            return {"error": "Unknown job"}, 404
        return record, 200
    if path == "/api/population/export":
        # ``query`` comes from ``parse_qs``: every value is a list.
        raw = (query or {}).get("format") or ["csv"]
        fmt = str(raw[0] if isinstance(raw, list) else raw)
        try:
            return export_population(fmt), 200
        except ValueError as exc:
            return {"error": str(exc)}, 400
    if path == "/api/population/last":
        agents = _LAST_POPULATION.get("agents") or []
        return {"count": len(agents), "job_id": _LAST_POPULATION.get("job_id")}, 200
    return {"error": "Unknown population endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/population/preview":
            return preview_population(payload), 200
        if path == "/api/population/generate":
            return start_population_job(payload), 202
        if path == "/api/population/group-run":
            result = start_group_job(payload)
            return result, (400 if "error" in result else 202)
        if path == "/api/population/validate":
            return start_validation_job(payload), 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown population endpoint"}, 404


__all__ = [
    "export_population",
    "handle_get",
    "handle_post",
    "job_status",
    "population_schema",
    "preview_population",
    "start_group_job",
    "start_population_job",
    "start_validation_job",
]
