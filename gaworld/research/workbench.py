"""Turn a research idea or a social-science paper into a GAWorld study plan.

The user brings a question ("does a rent subsidy change who neighbours talk
to?") or a paper (its abstract, or the whole text). The model brings nothing
of its own about GAWorld: the platform's capability catalogue is read from
``docs/FEATURES.md`` at call time and handed over in the prompt, so the plan
can only cite features that exist, under the names the console uses. When the
catalogue changes, the plans change with it — nothing here has to be kept in
step by hand.

    idea / paper text
      (paper only, optional) → digest prompt → theory / method / variables /
        findings / questions / hypotheses, which the user reviews and edits
      → prompt = capability catalogue + material (+ confirmed digest) + a fixed JSON schema
      → LLM answers as JSON
      → validated into a :class:`ResearchPlan`
      → rendered to Markdown for download

As in :mod:`gaworld.city.imagine`, the model emits **JSON, not the document**.
A parsed object can be checked field by field and rendered the same way every
time; free-form prose cannot. Everything after the parse is defensive: a
missing section costs the user an empty heading, not a failed analysis.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from gaworld.city.knowledge import _parse_json_object, _utcnow
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.research.workbench")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: The capability catalogue the model plans against. A relative path so tests
#: (and a checkout moved elsewhere) find it through ``PROJECT_ROOT``.
CATALOGUE_PATH = "docs/FEATURES.md"

#: Where finished plans live, relative to the project root. Like interview
#: sessions, deliberately not under any one city's run root: a study plan
#: belongs to no city until someone runs it.
PLANS_DIRNAME = "output/research"

KINDS = ("idea", "paper")
LANGUAGES = ("zh-CN", "en")
VERDICTS = ("high", "medium", "low")

#: Input ceiling in characters. A full paper is ~60k; past this the tail is
#: references and appendices, and the model's context is better spent on the
#: catalogue than on a bibliography.
MAX_MATERIAL_CHARS = 80_000
MAX_CATALOGUE_CHARS = 60_000
MAX_TITLE_CHARS = 160

#: Output budget for one plan. The provider's configured default suits a
#: single agent turn; a whole study design with a dozen steps needs more or
#: gets truncated mid-JSON.
PLAN_MAX_TOKENS = 12_000

#: The paper read-through is a fraction of a plan: no catalogue, no design.
DIGEST_MAX_TOKENS = 3_000

#: A plan offers a few alternative designs, one of them recommended. More
#: than this and the model starts padding them out with near-duplicates.
MAX_DESIGNS = 4

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class ResearchError(ValueError):
    """Bad input or an unusable model answer, phrased for the user."""


@dataclass
class ResearchPlan:
    """One analysis: what the study is, and how GAWorld would run it."""

    id: str
    kind: str
    title: str
    language: str
    provider: str
    created_at: str
    summary: str = ""
    research_questions: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    paper_digest: dict[str, Any] = field(default_factory=dict)
    feasibility: dict[str, Any] = field(default_factory=dict)
    capability_map: list[dict[str, str]] = field(default_factory=list)
    #: The recommended design — what a study compiles unless told otherwise.
    #: Always ``designs[recommended_design]`` when ``designs`` is non-empty;
    #: plans saved before alternatives existed have only this.
    design: dict[str, Any] = field(default_factory=dict)
    designs: list[dict[str, Any]] = field(default_factory=list)
    recommended_design: int = 0
    steps: list[dict[str, Any]] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)
    estimated_cost: dict[str, str] = field(default_factory=dict)
    #: The material as analysed (possibly truncated), kept so a saved plan can
    #: be re-read next to what it answered.
    material: str = ""
    material_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchPlan":
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in (data or {}).items() if key in known})


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PLATFORM_NOTE = """GAWorld 是一个生成式智能体城市社会仿真平台：
- 每位居民（agent）由大模型驱动，有身份、九维状态变量（压力、情绪、财务等）、大五人格、记忆（短期/情景/长期/关系）、Dunbar 分层社交网络、兴趣与技能成长、家庭与户、经济账本（收入/消费/信贷/货币守恒）。
- 城市可从真实地名生成（OSM 路网）或凭描述虚构；人口可按人口学参数合成几百到上千人；群体（cohort）模式可低成本模拟大规模人群。
- 事件层可注入政策/环境/人生事件；平行世界与 compare-event 提供同种子、只改一件事的反事实对照；采访与群体采访可在任意时刻向居民提问；长时段快进可跑数月数年。
- 所有产物落在 output/ 下的 CSV/JSONL/Markdown，结果分析面板可读状态轨迹、经济、社交网络、事件时间线。
- 认知管线可消融/替换阶段，插件体系可加子系统，运行时可干预状态与配置。"""

_PROMPT = """你是 GAWorld 平台的研究方法顾问，熟悉社会科学的研究设计（因果推断、准实验、代理人建模、计算社会科学）。请阅读下面的研究材料，判断它能否、以及如何用 GAWorld 的功能来实现，并给出一份可执行的实施方案。

## 平台概况
{platform}

## GAWorld 功能目录（唯一可引用的功能清单；来自 docs/FEATURES.md）
{catalogue}

## 研究材料（类型：{kind_label}）
标题：{title}

{material}
{truncated_note}
{confirmed}
## 你的任务
1. 提炼研究问题与可检验假设；材料若是论文，先概括其理论、方法、关键变量与主要发现。
2. 判断用 GAWorld 复现/延伸这项研究的可行性，说明依据。
3. 把研究的每一项需要（被试、干预、测量、时间跨度、对照……）映射到功能目录里**确实存在**的功能，并写明入口（CLI 命令 / 控制台页签 / 配置项）。不要发明目录里没有的功能；目录做不到的写进 gaps，并给出替代做法。
4. 给出 2 到 3 种思路不同的实验设计（例如：忠实复现原研究 / 只检验核心机制的简化版 / 延伸到新情境或新干预；或采用不同的因果识别策略），每种都要具体：城市、人口规模与结构、agent 设定、时间跨度与步长、实验条件（对照组与处理组各改什么）、事件表、测量指标（对应到 output/ 下的产物或面板）。写明每种的优势与短板，并指出推荐哪一种。
5. 列出可以照做的实施步骤（按推荐的设计），尽量给出命令或面板操作。
6. 说明结果可信度的检验方式（多种子、安慰剂对照、剂量反应、与论文原结论对比等）。
7. 估算模型调用量级与运行成本。

## 输出要求
- 语言：{language_label}。
- 只输出一个 JSON 对象，不要解释，不要 Markdown 围栏以外的文字。格式：
{{
  "title": "方案标题（30 字以内）",
  "summary": "一段话概括这项研究以及用 GAWorld 实现它的核心思路（150 字以内）",
  "research_questions": ["研究问题 1", "研究问题 2"],
  "hypotheses": ["H1：…", "H2：…"],
  "paper_digest": {{"theory": "理论框架", "method": "原研究方法与数据", "key_variables": ["自变量", "因变量", "调节/中介变量"], "findings": "主要发现"}},
  "feasibility": {{"score": 0到100的整数, "verdict": "high|medium|low", "rationale": "依据（100 字以内）"}},
  "capability_map": [
    {{"need": "研究需要什么", "feature": "功能目录里的功能名", "how": "怎么用它满足这个需要", "entry": "CLI / 页签 / 配置项"}}
  ],
  "designs": [
    {{
      "name": "设计名（15 字以内，如「忠实复现」「机制检验」）",
      "approach": "这种设计的思路与因果识别策略（100 字以内）",
      "strengths": "优势",
      "weaknesses": "短板与风险",
      "city": "用哪座城市、怎么来",
      "population": "人口规模、结构、生成方式",
      "agents": "agent 层面的关键设定（人格、家庭、职业分布……）",
      "timeline": "仿真时长、步长单位、是否快进",
      "conditions": [{{"name": "条件名", "manipulation": "相对基准改了什么"}}],
      "events": ["注入的事件或政策"],
      "measures": [{{"name": "指标名", "operationalization": "怎么从仿真里算出来", "source": "output 文件 / 面板"}}]
    }}
  ],
  "recommended": 推荐的设计在 designs 里的下标（从 0 开始的整数）,
  "steps": [
    {{"title": "步骤名", "detail": "做什么、注意什么", "commands": ["可直接执行的命令（没有就空数组）"], "panel": "对应的控制台页签（没有就空字符串）"}}
  ],
  "validation": ["可信度检验 1", "可信度检验 2"],
  "gaps": [{{"limitation": "GAWorld 做不到或做不好的地方", "workaround": "替代做法或需要新写的插件"}}],
  "estimated_cost": {{"llm_calls": "调用量级的估算与算法", "note": "对运行时长 / 模型选择的建议"}}
}}
- paper_digest 只在材料是论文时填写，否则给空对象。
- designs 给 2 到 3 个，彼此要有实质区别，不要只改人口规模或天数。
- capability_map 至少 4 条，steps 至少 5 步，每一步都要能落到具体操作。"""

_CONFIRMED = """
## 已确认的论文解读（研究者已审阅，以此为准）
{digest}
paper_digest、research_questions、hypotheses 三项请原样沿用上面的内容，实验设计要围绕这些假设展开。
"""

_DIGEST_PROMPT = """你是社会科学方法论专家。请仔细阅读下面这篇论文，为后续用代理人仿真复现它做准备，提炼出它的核心内容。

## 论文
标题：{title}

{material}
{truncated_note}

## 输出要求
- 语言：{language_label}。
- 只输出一个 JSON 对象，不要解释。格式：
{{
  "title": "论文标题（材料里有就照抄，没有就概括，40 字以内）",
  "paper_digest": {{
    "theory": "理论框架与核心论点",
    "method": "研究方法、样本/数据、识别策略",
    "key_variables": ["自变量：…", "因变量：…", "调节/中介变量：…"],
    "findings": "主要发现（尽量带上效应方向与大小）"
  }},
  "research_questions": ["适合用仿真检验的研究问题 1", "…"],
  "hypotheses": ["H1：可检验、有方向的假设", "…"]
}}
- 只依据论文内容，不要补充论文里没有的发现；论文没交代的写「未说明」。
- hypotheses 要能在仿真里对照检验：写清楚干预是什么、结果变量往哪个方向变。"""

_KIND_LABELS = {"idea": "研究想法", "paper": "论文"}
_LANGUAGE_LABELS = {"zh-CN": "简体中文", "en": "English"}
_TRUNCATED_NOTE = "（材料超出长度上限，以上为截断后的前 {n} 个字符。）"


def load_catalogue(root: Path | None = None) -> str:
    """The capability catalogue as the prompt will see it.

    Read at call time rather than at import so an edit to ``FEATURES.md``
    reaches the next analysis without a server restart — the whole point of
    grounding on the file is that the file is the truth.
    """
    path = (root or PROJECT_ROOT) / CATALOGUE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        _LOG.warning("capability catalogue missing at %s", path)
        return ""
    return text[:MAX_CATALOGUE_CHARS]


def normalize_request(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a workbench request, raising :class:`ResearchError` on bad input."""
    payload = payload if isinstance(payload, dict) else {}
    kind = str(payload.get("kind") or "idea").strip().lower()
    if kind not in KINDS:
        raise ResearchError(f"材料类型只能是 {' / '.join(KINDS)}，收到的是 {kind!r}")
    material = str(payload.get("text") or "").strip()
    if not material:
        raise ResearchError("请先写下研究想法，或粘贴论文内容")
    truncated = len(material) > MAX_MATERIAL_CHARS
    if truncated:
        material = material[:MAX_MATERIAL_CHARS]
    language = str(payload.get("language") or "zh-CN").strip()
    if language not in LANGUAGES:
        language = "zh-CN"
    title = str(payload.get("title") or "").strip().replace("\n", " ")[:MAX_TITLE_CHARS]
    return {
        "kind": kind,
        "title": title,
        "text": material,
        "truncated": truncated,
        "language": language,
        "provider": str(payload.get("provider") or "").strip()[:64],
        # Only a paper has a read-through to confirm; an idea's is ignored.
        "digest": _confirmed_digest(payload.get("digest")) if kind == "paper" else None,
    }


def _confirmed_digest(value: Any) -> dict[str, Any] | None:
    """A digest the user reviewed, or ``None`` when there is nothing in it."""
    if not isinstance(value, dict):
        return None
    confirmed = {
        "paper_digest": _paper_digest(value.get("paper_digest")),
        "research_questions": _strings(value.get("research_questions")),
        "hypotheses": _strings(value.get("hypotheses")),
    }
    return confirmed if any(confirmed.values()) else None


def _digest_text(digest: dict[str, Any]) -> str:
    paper = digest.get("paper_digest") or {}
    parts: list[str] = []
    for label, key in (("理论框架", "theory"), ("方法与数据", "method"), ("主要发现", "findings")):
        if paper.get(key):
            parts.append(f"- {label}：{paper[key]}")
    if paper.get("key_variables"):
        parts.append("- 关键变量：" + "；".join(paper["key_variables"]))
    for label, key in (("研究问题", "research_questions"), ("假设", "hypotheses")):
        if digest.get(key):
            parts.append(f"{label}：\n" + "\n".join(f"- {item}" for item in digest[key]))
    return "\n".join(parts)


def build_prompt(request: dict[str, Any], catalogue: str) -> str:
    title = request.get("title") or ("（未命名）" if request.get("language") != "en" else "(untitled)")
    truncated_note = (
        _TRUNCATED_NOTE.format(n=MAX_MATERIAL_CHARS) if request.get("truncated") else ""
    )
    return _PROMPT.format(
        platform=_PLATFORM_NOTE,
        catalogue=catalogue or "（功能目录不可用：请只依据平台概况作答，并在 gaps 中说明。）",
        kind_label=_KIND_LABELS.get(request["kind"], request["kind"]),
        title=title,
        material=request["text"],
        truncated_note=truncated_note,
        confirmed=_CONFIRMED.format(digest=_digest_text(request["digest"])) if request.get("digest") else "",
        language_label=_LANGUAGE_LABELS.get(request.get("language", "zh-CN"), "简体中文"),
    )


def build_digest_prompt(request: dict[str, Any]) -> str:
    return _DIGEST_PROMPT.format(
        title=request.get("title") or "（未命名）",
        material=request["text"],
        truncated_note=_TRUNCATED_NOTE.format(n=MAX_MATERIAL_CHARS) if request.get("truncated") else "",
        language_label=_LANGUAGE_LABELS.get(request.get("language", "zh-CN"), "简体中文"),
    )


def digest_paper(payload: dict[str, Any], *, llm_fn: Callable[[str], str]) -> dict[str, Any]:
    """Step one for a paper: read it, without planning anything yet.

    The answer goes back to the user to correct before it steers the design —
    a misread method or an invented finding is cheaper to fix here than after
    three designs have been built on it. Nothing is saved; the confirmed
    digest travels with the analyse request and lands in the plan.
    """
    request = normalize_request({**(payload if isinstance(payload, dict) else {}), "kind": "paper"})
    try:
        raw = llm_fn(build_digest_prompt(request))
    except Exception as exc:  # surfaced to the user as-is
        raise ResearchError(f"模型调用失败：{exc}") from exc
    answer = _parse_json_object(raw)
    if not answer:
        raise ResearchError("模型没有返回可解析的论文解读")
    digest = _confirmed_digest(answer)
    if digest is None:
        raise ResearchError("模型没有从论文里读出内容")
    return {
        "title": _text(answer.get("title"), MAX_TITLE_CHARS) or request["title"],
        **digest,
        "truncated": request["truncated"],
    }


# ---------------------------------------------------------------------------
# Parsing the answer
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value).strip()[:limit]


def _strings(value: Any, limit: int = 20) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = [_text(item, 600) for item in value]
    return [item for item in out if item][:limit]


def _records(value: Any, keys: tuple[str, ...], limit: int = 30) -> list[dict[str, Any]]:
    """Objects with exactly *keys*, dropping entries that carry none of them."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        record = {key: _text(item.get(key), 1200) for key in keys}
        if any(record.values()):
            out.append(record)
    return out


def _feasibility(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    try:
        score = int(round(float(value.get("score"))))
    except (TypeError, ValueError):
        score = -1
    score = max(0, min(100, score)) if score >= 0 else -1
    verdict = str(value.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        # Derive one from the score rather than show a blank badge; the score
        # is the model's own number, so this invents nothing.
        verdict = "high" if score >= 70 else "medium" if score >= 40 else "low" if score >= 0 else ""
    return {"score": score, "verdict": verdict, "rationale": _text(value.get("rationale"), 800)}


def _design(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    return {
        "city": _text(value.get("city"), 800),
        "population": _text(value.get("population"), 800),
        "agents": _text(value.get("agents"), 800),
        "timeline": _text(value.get("timeline"), 800),
        "conditions": _records(value.get("conditions"), ("name", "manipulation"), limit=12),
        "events": _strings(value.get("events"), limit=20),
        "measures": _records(value.get("measures"), ("name", "operationalization", "source"), limit=20),
    }


def _designs(answer: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """The alternative designs and which one is recommended.

    An answer in the old single-``design`` shape still parses, as one design.
    An out-of-range recommendation falls back to the first design rather than
    failing the plan.
    """
    out: list[dict[str, Any]] = []
    raw = answer.get("designs")
    if isinstance(raw, list):
        for item in raw[:MAX_DESIGNS]:
            if not isinstance(item, dict):
                continue
            design = {
                "name": _text(item.get("name"), 120),
                "approach": _text(item.get("approach"), 800),
                "strengths": _text(item.get("strengths"), 800),
                "weaknesses": _text(item.get("weaknesses"), 800),
                **_design(item),
            }
            if any(design.values()):
                out.append(design)
    if not out:
        legacy = _design(answer.get("design"))
        if any(legacy.values()):
            out.append({"name": "", "approach": "", "strengths": "", "weaknesses": "", **legacy})
    try:
        recommended = int(answer.get("recommended") or 0)
    except (TypeError, ValueError):
        recommended = 0
    if not 0 <= recommended < len(out):
        recommended = 0
    return out, recommended


def _steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[:30]:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        step = {
            "title": _text(item.get("title"), 200),
            "detail": _text(item.get("detail"), 1500),
            "commands": _strings(item.get("commands"), limit=8),
            "panel": _text(item.get("panel"), 80),
        }
        if step["title"] or step["detail"]:
            out.append(step)
    return out


def _paper_digest(value: Any) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    digest = {
        "theory": _text(value.get("theory"), 1000),
        "method": _text(value.get("method"), 1000),
        "key_variables": _strings(value.get("key_variables"), limit=15),
        "findings": _text(value.get("findings"), 1000),
    }
    return digest if any(digest.values()) else {}


def plan_from_answer(
    answer: dict[str, Any], request: dict[str, Any], *, provider: str = "", plan_id: str | None = None
) -> ResearchPlan:
    """Validate a parsed model answer into a plan. Raises on an empty one."""
    steps = _steps(answer.get("steps"))
    capability_map = _records(answer.get("capability_map"), ("need", "feature", "how", "entry"))
    summary = _text(answer.get("summary"), 1500)
    if not (steps or capability_map or summary):
        raise ResearchError("模型没有返回可用的方案内容")
    title = _text(answer.get("title"), MAX_TITLE_CHARS) or request.get("title") or ""
    if not title:
        title = "研究方案" if request.get("language") != "en" else "Research plan"
    cost = answer.get("estimated_cost") if isinstance(answer.get("estimated_cost"), dict) else {}
    designs, recommended = _designs(answer)
    # A digest the user confirmed outranks the model's restatement of it.
    confirmed = request.get("digest") or {}
    return ResearchPlan(
        id=plan_id or new_plan_id(),
        kind=request["kind"],
        title=title,
        language=request.get("language", "zh-CN"),
        provider=provider,
        created_at=_utcnow(),
        summary=summary,
        research_questions=confirmed.get("research_questions") or _strings(answer.get("research_questions")),
        hypotheses=confirmed.get("hypotheses") or _strings(answer.get("hypotheses")),
        paper_digest=(confirmed.get("paper_digest") or _paper_digest(answer.get("paper_digest")))
        if request["kind"] == "paper"
        else {},
        feasibility=_feasibility(answer.get("feasibility")),
        capability_map=capability_map,
        design=dict(designs[recommended]) if designs else {},
        designs=designs,
        recommended_design=recommended,
        steps=steps,
        validation=_strings(answer.get("validation")),
        gaps=_records(answer.get("gaps"), ("limitation", "workaround"), limit=15),
        estimated_cost={"llm_calls": _text(cost.get("llm_calls"), 600), "note": _text(cost.get("note"), 600)},
        material=request["text"],
        material_truncated=bool(request.get("truncated")),
    )


def analyze(
    payload: dict[str, Any],
    *,
    llm_fn: Callable[[str], str],
    catalogue: str | None = None,
    provider: str = "",
) -> ResearchPlan:
    """Run one analysis. ``llm_fn`` takes the prompt and returns the raw text.

    The caller owns provider selection (so the API layer can route through
    :func:`gaworld.llm.providers.call_llm` and tests can hand in a stub).
    """
    request = normalize_request(payload)
    prompt = build_prompt(request, load_catalogue() if catalogue is None else catalogue)
    try:
        raw = llm_fn(prompt)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as-is
        raise ResearchError(f"模型调用失败：{exc}") from exc
    answer = _parse_json_object(raw)
    if not answer:
        raise ResearchError("模型没有返回可解析的 JSON 方案")
    plan = plan_from_answer(answer, request, provider=provider)
    _LOG.info(
        "research plan %s: kind=%s steps=%d features=%d feasibility=%s",
        plan.id, plan.kind, len(plan.steps), len(plan.capability_map), plan.feasibility.get("verdict"),
    )
    return plan


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

_LABELS = {
    "zh-CN": {
        "kind_idea": "研究想法", "kind_paper": "论文", "model": "模型", "created": "生成时间",
        "feasibility": "可行性", "summary": "概要", "digest": "论文摘要", "theory": "理论框架",
        "method": "方法与数据", "variables": "关键变量", "findings": "主要发现",
        "questions": "研究问题", "hypotheses": "假设", "map": "功能映射",
        "need": "研究需要", "feature": "GAWorld 功能", "how": "用法", "entry": "入口",
        "design": "实验设计", "city": "城市", "population": "人口", "agents": "Agent 设定",
        "timeline": "时间跨度", "conditions": "实验条件", "events": "事件", "measures": "测量指标",
        "measure_name": "指标", "operationalization": "操作化", "source": "来源",
        "steps": "实施步骤", "panel": "页签", "validation": "可信度检验", "gaps": "局限与替代",
        "limitation": "局限", "workaround": "替代做法", "cost": "成本估算", "calls": "模型调用",
        "note": "建议", "material": "原始材料", "truncated": "（已截断）", "routed": "按配置路由",
        "scale": "分", "design_n": "设计", "recommended": "推荐", "approach": "思路",
        "strengths": "优势", "weaknesses": "短板",
    },
    "en": {
        "kind_idea": "Research idea", "kind_paper": "Paper", "model": "Model", "created": "Generated",
        "feasibility": "Feasibility", "summary": "Summary", "digest": "Paper digest", "theory": "Theory",
        "method": "Method & data", "variables": "Key variables", "findings": "Findings",
        "questions": "Research questions", "hypotheses": "Hypotheses", "map": "Capability map",
        "need": "Need", "feature": "GAWorld feature", "how": "How", "entry": "Entry point",
        "design": "Study design", "city": "City", "population": "Population", "agents": "Agent setup",
        "timeline": "Timeline", "conditions": "Conditions", "events": "Events", "measures": "Measures",
        "measure_name": "Measure", "operationalization": "Operationalization", "source": "Source",
        "steps": "Implementation steps", "panel": "Panel", "validation": "Validity checks",
        "gaps": "Limitations & workarounds", "limitation": "Limitation", "workaround": "Workaround",
        "cost": "Cost estimate", "calls": "LLM calls", "note": "Advice", "material": "Source material",
        "truncated": "(truncated)", "routed": "routed by config", "scale": "/100",
        "design_n": "Design", "recommended": "recommended", "approach": "Approach",
        "strengths": "Strengths", "weaknesses": "Weaknesses",
    },
}


def _cell(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _render_design(lines: list[str], design: dict[str, Any], L: dict[str, str]) -> None:
    for key in ("approach", "strengths", "weaknesses", "city", "population", "agents", "timeline"):
        if design.get(key):
            lines.append(f"- **{L[key]}**: {design[key]}")
    if design.get("conditions"):
        lines += ["", f"**{L['conditions']}**", ""]
        for cond in design["conditions"]:
            lines.append(f"- **{cond.get('name')}**: {cond.get('manipulation')}")
    if design.get("events"):
        lines += ["", f"**{L['events']}**", ""] + [f"- {event}" for event in design["events"]]
    if design.get("measures"):
        lines += [
            "", f"**{L['measures']}**", "",
            f"| {L['measure_name']} | {L['operationalization']} | {L['source']} |",
            "|---|---|---|",
        ]
        for measure in design["measures"]:
            lines.append(
                f"| {_cell(measure.get('name'))} | {_cell(measure.get('operationalization'))} | {_cell(measure.get('source'))} |"
            )
    lines.append("")


def render_markdown(plan: ResearchPlan) -> str:
    """The downloadable document for one plan."""
    L = _LABELS.get(plan.language, _LABELS["zh-CN"])
    lines: list[str] = [f"# {plan.title}", ""]
    meta = [
        f"{L['kind_' + plan.kind] if plan.kind in KINDS else plan.kind}",
        f"{L['model']}: {plan.provider or L['routed']}",
        f"{L['created']}: {plan.created_at}",
    ]
    feas = plan.feasibility or {}
    if feas.get("verdict"):
        score = f" {feas['score']}{L['scale']}" if isinstance(feas.get("score"), int) and feas["score"] >= 0 else ""
        meta.append(f"{L['feasibility']}: {feas['verdict']}{score}")
    lines.append(" · ".join(meta))
    lines.append("")
    if plan.summary:
        lines += [f"## {L['summary']}", "", plan.summary, ""]
    if feas.get("rationale"):
        lines += [f"**{L['feasibility']}**: {feas['rationale']}", ""]

    digest = plan.paper_digest or {}
    if digest:
        lines += [f"## {L['digest']}", ""]
        for key, label in (("theory", "theory"), ("method", "method"), ("findings", "findings")):
            if digest.get(key):
                lines.append(f"- **{L[label]}**: {digest[key]}")
        if digest.get("key_variables"):
            lines.append(f"- **{L['variables']}**: " + "; ".join(digest["key_variables"]))
        lines.append("")

    if plan.research_questions:
        lines += [f"## {L['questions']}", ""] + [f"{i}. {q}" for i, q in enumerate(plan.research_questions, 1)] + [""]
    if plan.hypotheses:
        lines += [f"## {L['hypotheses']}", ""] + [f"- {h}" for h in plan.hypotheses] + [""]

    if plan.capability_map:
        lines += [
            f"## {L['map']}", "",
            f"| {L['need']} | {L['feature']} | {L['how']} | {L['entry']} |",
            "|---|---|---|---|",
        ]
        for row in plan.capability_map:
            lines.append(
                f"| {_cell(row.get('need'))} | {_cell(row.get('feature'))} | {_cell(row.get('how'))} | {_cell(row.get('entry'))} |"
            )
        lines.append("")

    designs = plan.designs or ([plan.design] if any((plan.design or {}).values()) else [])
    if designs:
        lines += [f"## {L['design']}", ""]
        for index, design in enumerate(designs):
            if len(designs) > 1:
                head = f"### {L['design_n']} {index + 1}"
                if design.get("name"):
                    head += f"：{design['name']}" if plan.language != "en" else f": {design['name']}"
                if index == plan.recommended_design:
                    head += f"（{L['recommended']}）" if plan.language != "en" else f" ({L['recommended']})"
                lines += [head, ""]
            _render_design(lines, design, L)
    if plan.steps:
        lines += [f"## {L['steps']}", ""]
        for index, step in enumerate(plan.steps, 1):
            head = f"### {index}. {step.get('title') or ''}".rstrip()
            if step.get("panel"):
                head += f"  ({L['panel']}: {step['panel']})"
            lines += [head, ""]
            if step.get("detail"):
                lines += [step["detail"], ""]
            if step.get("commands"):
                lines += ["```bash"] + list(step["commands"]) + ["```", ""]

    if plan.validation:
        lines += [f"## {L['validation']}", ""] + [f"- {item}" for item in plan.validation] + [""]
    if plan.gaps:
        lines += [f"## {L['gaps']}", ""]
        for gap in plan.gaps:
            lines.append(f"- **{L['limitation']}**: {gap.get('limitation')}")
            if gap.get("workaround"):
                lines.append(f"  - {L['workaround']}: {gap['workaround']}")
        lines.append("")
    cost = plan.estimated_cost or {}
    if cost.get("llm_calls") or cost.get("note"):
        lines += [f"## {L['cost']}", ""]
        if cost.get("llm_calls"):
            lines.append(f"- **{L['calls']}**: {cost['llm_calls']}")
        if cost.get("note"):
            lines.append(f"- **{L['note']}**: {cost['note']}")
        lines.append("")
    if plan.material:
        suffix = f" {L['truncated']}" if plan.material_truncated else ""
        lines += [f"## {L['material']}{suffix}", "", "> " + plan.material.replace("\n", "\n> "), ""]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def plans_root() -> Path:
    return PROJECT_ROOT / PLANS_DIRNAME


def new_plan_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def plan_path(plan_id: str) -> Path:
    """Path for ``plan_id``, validated against traversal — the id comes from a URL."""
    if not _SAFE_ID_RE.match(str(plan_id or "")):
        raise ResearchError(f"非法的方案 id：{plan_id!r}")
    return plans_root() / f"{plan_id}.json"


def save_plan(plan: ResearchPlan) -> Path:
    path = plan_path(plan.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.to_dict()
    payload["markdown"] = render_markdown(plan)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def load_plan(plan_id: str) -> dict[str, Any] | None:
    path = plan_path(plan_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _LOG.warning("unreadable research plan %s", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def list_plans() -> list[dict[str, Any]]:
    """Newest first: what the history rail shows, without the bodies."""
    root = plans_root()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not data.get("id"):
            continue
        out.append(
            {
                "id": data["id"],
                "title": data.get("title") or "",
                "kind": data.get("kind") or "",
                "provider": data.get("provider") or "",
                "created_at": data.get("created_at") or "",
                "verdict": (data.get("feasibility") or {}).get("verdict") or "",
                "score": (data.get("feasibility") or {}).get("score"),
                "steps": len(data.get("steps") or []),
                "designs": len(data.get("designs") or []) or (1 if data.get("design") else 0),
            }
        )
    out.sort(key=lambda item: item["created_at"], reverse=True)
    return out


def delete_plan(plan_id: str) -> bool:
    path = plan_path(plan_id)
    if not path.exists():
        return False
    path.unlink()
    return True


__all__ = [
    "DIGEST_MAX_TOKENS",
    "KINDS",
    "LANGUAGES",
    "MAX_DESIGNS",
    "MAX_MATERIAL_CHARS",
    "PLAN_MAX_TOKENS",
    "ResearchError",
    "ResearchPlan",
    "analyze",
    "build_digest_prompt",
    "build_prompt",
    "delete_plan",
    "digest_paper",
    "list_plans",
    "load_catalogue",
    "load_plan",
    "normalize_request",
    "plan_from_answer",
    "render_markdown",
    "save_plan",
]
