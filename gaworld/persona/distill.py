"""Turn a dossier into a persona: identity, seeds, and a thinking framework.

Two model calls, not one. The first builds the **档案** — who this person is,
in the fields Agent Studio already writes (basics, job, education/income,
daily life, social network, values). The second builds the **思维框架** —
mental models, decision heuristics, expression DNA, anti-patterns, honest
boundaries — plus the numeric seeds (nine state variables, Big Five z scores).

Splitting them costs one extra call and buys two things: each prompt stays
small enough that the model answers it rather than summarising it, and the UI
can show real progress across two stages instead of one long stall. It also
mirrors ``nuwa``'s own split between research review (Phase 1.5) and synthesis
(Phase 2).

The framework schema is ordered **shortest field first, mental models last**,
which is not cosmetic. The answer is the longest thing this pipeline asks for,
and a local model runs out of room part-way through it more often than not.
Whatever is cut off is cut off the *end*, so the order decides what survives:
with the models first, one truncated answer cost every state seed, the voice
and the anti-patterns; with them last, the same truncation costs one mental
model. :func:`parse_json_object` closes the brackets on what did arrive.

The sourcing rule is inherited from :mod:`gaworld.city.knowledge` and stated in
both prompts: **only what the evidence supports**. Empty is a legal answer;
invention is not. What the model could not ground is reported back as
``unknown_fields`` and surfaced in the panel, so the operator fills it in
rather than discovering a fabrication three simulated months later.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from gaworld.logging_setup import get_logger
from gaworld.persona.research import Dossier
from gaworld.population.schema import STATE_VAR_KEYS

_LOG = get_logger("gaworld.persona.distill")

SCHEMA_VERSION = "1.0"

BIG5_DIMENSIONS: tuple[str, ...] = ("o", "c", "e", "a", "n")

#: Big Five scores are z scores. The Studio sliders clamp to ±2.5 and so does
#: the seed writer, so a model that answers "3.0 — extremely open" lands at the
#: same place the panel would have put it.
BIG5_LIMIT = 2.5

#: How much evidence before the persona is presented as more than a sketch.
#: Below the floor the panel says "证据不足" and the profile says so too — the
#: alternative is a confident-looking resident built from four search snippets.
CONFIDENCE_PAGES = (3, 1)  # (high, medium) — full pages read


@dataclass
class MentalModel:
    """A lens this person reuses across domains."""

    name: str = ""
    gist: str = ""
    evidence: list[str] = field(default_factory=list)
    limits: str = ""


@dataclass
class Heuristic:
    """A decision rule, stated as 如果X，则Y."""

    rule: str = ""
    example: str = ""


@dataclass
class VoiceDNA:
    """How the person talks — the part that survives paraphrase."""

    sentences: str = ""
    vocabulary: str = ""
    rhythm: str = ""
    humor: str = ""
    certainty: str = ""
    phrases: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([self.sentences, self.vocabulary, self.rhythm, self.humor, self.certainty, self.phrases])


@dataclass
class PersonaProfile:
    """A real person, as far as the open web supports the claim."""

    name: str = ""
    slug: str = ""
    subject: str = ""  # what the operator typed
    mode: str = "name"  # name | url
    summary: str = ""

    # -- the fields Agent Studio seeds a resident with ----------------------
    gender: str = "未知"
    age: int = 40
    hukou: str = "未知"
    residence: str = ""
    job: str = ""
    education_income: str = ""
    daily_life: str = ""
    personality: str = ""
    social_network: str = ""
    values: str = ""

    # -- the thinking framework (nuwa's Phase 2 output) ---------------------
    mental_models: list[MentalModel] = field(default_factory=list)
    heuristics: list[Heuristic] = field(default_factory=list)
    voice: VoiceDNA = field(default_factory=VoiceDNA)
    values_ranked: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    tensions: list[str] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)

    # -- numeric seeds ------------------------------------------------------
    state: dict[str, float] = field(default_factory=dict)
    big5: dict[str, float] = field(default_factory=dict)

    # -- provenance ---------------------------------------------------------
    sources: list[dict[str, str]] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)
    evidence_pages: int = 0
    evidence_items: int = 0
    confidence: str = "low"  # high | medium | low
    #: Set when the framework call itself failed, as opposed to the evidence
    #: being too thin to support one. Rendered so the operator can retry.
    framework_error: str = ""
    built_at: str = ""
    schema_version: str = SCHEMA_VERSION
    #: Set once the persona has been deployed as a resident, so the panel can
    #: say "已落地为 #83" instead of offering to create a second copy.
    agent_id: int | None = None

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mental_models"] = [asdict(m) for m in self.mental_models]
        data["heuristics"] = [asdict(h) for h in self.heuristics]
        data["voice"] = asdict(self.voice)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PersonaProfile":
        raw = dict(data or {})
        models = [
            MentalModel(
                name=_text(item.get("name"), 60),
                gist=_text(item.get("gist"), 200),
                evidence=_lines(item.get("evidence"), 4, 200),
                limits=_text(item.get("limits"), 200),
            )
            for item in raw.pop("mental_models", []) or []
            if isinstance(item, dict) and _text(item.get("name"), 60)
        ]
        heuristics = [
            Heuristic(rule=_text(item.get("rule"), 160), example=_text(item.get("example"), 200))
            for item in raw.pop("heuristics", []) or []
            if isinstance(item, dict) and _text(item.get("rule"), 160)
        ]
        voice_raw = raw.pop("voice", None) or {}
        voice = VoiceDNA(
            sentences=_text(voice_raw.get("sentences"), 120),
            vocabulary=_text(voice_raw.get("vocabulary"), 120),
            rhythm=_text(voice_raw.get("rhythm"), 120),
            humor=_text(voice_raw.get("humor"), 120),
            certainty=_text(voice_raw.get("certainty"), 120),
            phrases=_lines(voice_raw.get("phrases"), 6, 40),
        )
        known = {f for f in cls.__dataclass_fields__ if f not in ("mental_models", "heuristics", "voice")}
        kwargs = {key: value for key, value in raw.items() if key in known}
        kwargs["state"] = clamp_state(kwargs.get("state"))
        kwargs["big5"] = clamp_big5(kwargs.get("big5"))
        kwargs["age"] = _age(kwargs.get("age"))
        profile = cls(**kwargs)
        profile.mental_models = models
        profile.heuristics = heuristics
        profile.voice = voice
        return profile

    # -- derived ------------------------------------------------------------

    @property
    def has_framework(self) -> bool:
        return bool(self.mental_models or self.heuristics or not self.voice.is_empty())

    def identity_payload(self) -> dict[str, Any]:
        """The identity half, in the shape ``_create_agent`` expects."""
        return {
            "name": self.name,
            "gender": self.gender or "未知",
            "age": _age(self.age),
            "hukou": self.hukou or "未知",
            "residence": self.residence or "杭州",
            "job": self.job or "待补充",
            "personality": self.personality or "待补充",
            "daily_life": self.daily_life or "待补充",
            "values": self.values or "待补充",
            "education_income": self.education_income or "待补充",
            "social_network": self.social_network or "待补充",
        }


# ---------------------------------------------------------------------------
# Coercion helpers — every field the model returns passes through one of these
# ---------------------------------------------------------------------------

def _text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()[:limit]


def _lines(value: Any, count: int, limit: int) -> list[str]:
    if isinstance(value, str):
        value = [value]
    out = []
    for item in list(value or [])[: max(0, count)]:
        text = _text(item, limit)
        if text:
            out.append(text)
    return out


def _age(value: Any, default: int = 40) -> int:
    try:
        age = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(16, min(95, age))


def clamp_state(values: Any) -> dict[str, float]:
    """Nine [0,1] seeds, defaulting to the neutral 0.5 the Studio uses."""
    raw = values if isinstance(values, dict) else {}
    out: dict[str, float] = {}
    for key in STATE_VAR_KEYS:
        try:
            number = float(raw.get(key))
        except (TypeError, ValueError):
            number = 0.55 if key == "emotion" else 0.5
        out[key] = round(max(0.0, min(1.0, number)), 2)
    return out


def clamp_big5(values: Any) -> dict[str, float]:
    raw = values if isinstance(values, dict) else {}
    out: dict[str, float] = {}
    for dim in BIG5_DIMENSIONS:
        try:
            number = float(raw.get(dim))
        except (TypeError, ValueError):
            number = 0.0
        out[dim] = round(max(-BIG5_LIMIT, min(BIG5_LIMIT, number)), 2)
    return out


def _close_unbalanced(blob: str) -> str:
    """Close a JSON object that stops in the middle, or return ``""``.

    The framework answer is the longest thing this pipeline asks a model for —
    three mental models with quoted evidence runs past three thousand
    characters — and a cut-off answer is unparseable by one bracket. Rather
    than throw the whole distillation away, shut the open brackets and let the
    partial framework through; what is missing is missing, which the panel
    already knows how to render.
    """
    stack: list[str] = []
    in_string = escaped = False
    for ch in blob:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if not stack and not in_string:
        return ""  # balanced already — the parse failed for some other reason
    patched = blob + ('"' if in_string else "")
    patched = re.sub(r"[,\s]*$", "", patched)
    return patched + "".join(reversed(stack))


def parse_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model answer.

    Same shape as ``gaworld.city.knowledge._parse_json_object``: models fence
    their JSON about half the time and prepend a sentence the other half. This
    one also repairs an answer that was cut off mid-object.
    """
    if not isinstance(text, str) or not text.strip():
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    blob = fenced.group(1) if fenced else ""
    if not blob:
        match = re.search(r"\{.*\}", text, re.S)
        blob = match.group(0) if match else ""
    if not blob:
        # No closing brace anywhere: take everything from the first one and let
        # the repair below decide whether it can be salvaged.
        start = text.find("{")
        blob = text[start:] if start >= 0 else ""
    for candidate in (blob, _close_unbalanced(blob)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _ask_json(llm_fn: Callable[[str], str], prompt: str, *, attempts: int = 2) -> dict[str, Any]:
    """Ask for a JSON answer, once more if the first one does not parse.

    Worth the extra call: the model these prompts actually reach is whatever
    the router falls back to, and a local model asked for a long structured
    answer gets it right most of the time rather than every time. One retry
    turns "the framework came back empty" from routine into rare.
    """
    for attempt in range(1, max(1, attempts) + 1):
        parsed = parse_json_object(llm_fn(prompt) or "")
        if parsed:
            return parsed
        _LOG.warning("persona: unparseable model answer (attempt %d/%d)", attempt, attempts)
    return {}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def confidence_for(dossier: Dossier) -> str:
    high, medium = CONFIDENCE_PAGES
    if dossier.page_count >= high:
        return "high"
    if dossier.page_count >= medium:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_DOSSIER_PROMPT = """你在为一个社会仿真系统建立**真实人物档案**。根据下面的公开检索材料，填写此人的基本信息。

对象：{name}

检索材料：
{evidence}

硬性要求：
- **只使用材料中出现的信息**，不要凭常识、印象或同名者补充；材料没提到的字段写空字符串 ""。
- 不确定的数字（年龄、收入）宁可留空，也不要估一个看起来合理的数。
- 如果材料明显讲的是同名的另一个人或与此人无关，把 `off_topic` 设为 true。
- 所有描述用第三人称中文陈述句，每字段 60-120 字。

只输出 JSON：
{{
  "off_topic": false,
  "name": "此人的常用名",
  "summary": "一句话说明此人是谁（40字以内）",
  "gender": "男/女/未知",
  "age": 45,
  "hukou": "户籍或籍贯，未知就写\\"未知\\"",
  "residence": "常住城市或地区",
  "job": "职业与工作节奏",
  "education_income": "教育背景与收入水平（材料没提就写空）",
  "daily_life": "日常生活与习惯（材料没提就写空）",
  "personality": "性格与情绪特征",
  "social_network": "社交关系与所处圈层",
  "values": "价值观与公共事务态度",
  "unknown_fields": ["材料不足、你留空了的字段名"]
}}"""

_STYLE_PROMPT = """你在提炼一个真实人物的**表达方式、价值观与仿真参数**。

对象：{name}
档案：{summary}

检索材料：
{evidence}

规则：
- 只使用材料支持的判断，材料没提到的字段留空字符串或空数组。
- 反模式 = 此人明确反对的做法。矛盾就保留矛盾，不要和稀泥。
- boundaries = 这份蒸馏**做不到**什么（信息截止、公开表达与真实想法的差距、材料偏向某一时期等）。
- 每个字符串 40 字以内。

仿真种子：
- state 是 9 个 [0,1] 变量，0.5 为中性。按材料推断此人相对于普通人的位置，没依据的维度就给 0.5。
- big5 是五个 z 分数，范围 -2.5 到 2.5，0 为平均水平。

只输出 JSON：
{{
  "state": {{"emotion": 0.5, "stress": 0.5, "econ_security": 0.5, "city_identity": 0.5,
             "policy_sensitivity": 0.5, "platform_dependence": 0.5, "risk_preference": 0.5,
             "voice_propensity": 0.5, "mobility_intent": 0.5}},
  "big5": {{"o": 0.0, "c": 0.0, "e": 0.0, "a": 0.0, "n": 0.0}},
  "voice": {{
    "sentences": "句式偏好", "vocabulary": "高频词与专属术语", "rhythm": "先结论还是先铺垫",
    "humor": "幽默方式，或\\"不幽默\\"", "certainty": "「我不确定」型还是「很明显」型",
    "phrases": ["口头禅或标志性短语"]
  }},
  "values_ranked": ["核心价值，按重要性排序，3-5条"],
  "anti_patterns": ["此人明确反对的行为或思维方式，2-5条"],
  "tensions": ["价值观之间的内在冲突，0-3条"],
  "lineage": ["受谁影响、与谁同路，0-5条"],
  "boundaries": ["这份蒸馏的局限，2-4条"]
}}"""

_MODELS_PROMPT = """你在提炼一个真实人物的**心智模型**——不是他说过什么，而是他**怎么想**。

对象：{name}
档案：{summary}

检索材料：
{evidence}

提炼规则：
- 心智模型 = 此人在**两个以上不同话题**里反复使用的同一套看法。只在一个场合出现过的，降级成决策启发式；材料撑不起来的，直接不写。
- 宁少勿多：**最多 3 个**有证据的模型，远好于 7 个凑数的。材料不足时给 0-2 个。
- 每个模型的 evidence 最多 2 条、每条 40 字以内，引用材料中的具体事实，不要整段照抄原文。
- 决策启发式写成「如果X，则Y」，最多 4 条。
- gist 与 limits 各 40 字以内。

只输出 JSON：
{{
  "mental_models": [
    {{"name": "模型名", "gist": "一句话说明", "evidence": ["材料中的具体依据"], "limits": "这个模型在什么情况下失效"}}
  ],
  "heuristics": [{{"rule": "如果X，则Y", "example": "对应的具体事例"}}]
}}"""


class DistillError(RuntimeError):
    """Raised when the dossier cannot support a persona at all."""


def distill(
    dossier: Dossier,
    *,
    llm_fn: Callable[[str], str],
    slugify_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> PersonaProfile:
    """Dossier → :class:`PersonaProfile`.

    Raises :class:`DistillError` when the evidence is empty or the model says
    the material is about somebody else — both are cases where returning a
    half-filled persona would be worse than failing, because the operator would
    have no way to tell it apart from a real one.
    """
    if dossier.is_empty:
        raise DistillError(
            f"没有检索到关于「{dossier.name or dossier.subject}」的可用材料。"
            "百科没有词条，搜索引擎也没给出可读结果（抓取到的多是结果页自身的链接）。"
            "可以直接填这个人的主页/访谈页网址，或换一个更完整的姓名。"
        )

    def note(fraction: float, message: str) -> None:
        if progress:
            progress(fraction, message)

    evidence = dossier.brief()
    name = dossier.name or dossier.subject

    note(0.1, "建立档案…")
    facts = _ask_json(llm_fn, _DOSSIER_PROMPT.format(name=name, evidence=evidence))
    if not facts:
        raise DistillError("模型没有返回可解析的档案，请重试或换一个模型")
    if facts.get("off_topic") is True:
        raise DistillError(f"检索到的材料与「{name}」无关，请改用更具体的姓名或直接给出网址")

    resolved = _text(facts.get("name"), 40) or name
    summary = _text(facts.get("summary"), 120) or "（无）"

    note(0.45, "提炼表达与参数…")
    style = _ask_json(llm_fn, _STYLE_PROMPT.format(name=resolved, summary=summary, evidence=evidence))
    note(0.7, "提炼心智模型…")
    models = _ask_json(llm_fn, _MODELS_PROMPT.format(name=resolved, summary=summary, evidence=evidence))
    framework = {**style, **models}

    # An empty framework has two very different causes, and the panel must not
    # blame the wrong one: thin evidence is a fact about the sources, while an
    # unusable model answer is a fact about this run and worth retrying.
    missing = [
        label
        for label, ok in (("表达与参数", bool(style)), ("心智模型", bool(models)))
        if not ok
    ]
    framework_error = (
        f"模型没有返回可解析的{ '、'.join(missing) }，可以重试一次。" if missing else ""
    )
    if framework_error:
        _LOG.warning("persona framework incomplete for %s: %s", resolved, missing)

    slugify = slugify_fn or _default_slugify
    profile = PersonaProfile.from_dict(
        {
            "name": resolved,
            "slug": slugify(resolved),
            "subject": dossier.subject,
            "mode": dossier.mode,
            "summary": _text(facts.get("summary"), 120),
            "gender": _text(facts.get("gender"), 8) or "未知",
            "age": facts.get("age"),
            "hukou": _text(facts.get("hukou"), 40) or "未知",
            "residence": _text(facts.get("residence"), 40),
            "job": _text(facts.get("job"), 300),
            "education_income": _text(facts.get("education_income"), 300),
            "daily_life": _text(facts.get("daily_life"), 300),
            "personality": _text(facts.get("personality"), 300),
            "social_network": _text(facts.get("social_network"), 300),
            "values": _text(facts.get("values"), 300),
            "mental_models": framework.get("mental_models") or [],
            "heuristics": framework.get("heuristics") or [],
            "voice": framework.get("voice") or {},
            "values_ranked": _lines(framework.get("values_ranked"), 5, 60),
            "anti_patterns": _lines(framework.get("anti_patterns"), 5, 80),
            "tensions": _lines(framework.get("tensions"), 3, 100),
            "lineage": _lines(framework.get("lineage"), 5, 60),
            "boundaries": _lines(framework.get("boundaries"), 4, 120),
            "state": framework.get("state"),
            "big5": framework.get("big5"),
            "sources": dossier.sources(),
            "unknown_fields": _lines(facts.get("unknown_fields"), 12, 40),
            "evidence_pages": dossier.page_count,
            "evidence_items": len(dossier.documents),
            "confidence": confidence_for(dossier),
            "framework_error": framework_error,
            "built_at": _utcnow(),
        }
    )
    profile.boundaries = _default_boundaries(profile)
    note(0.95, f"完成：{len(profile.mental_models)} 个心智模型")
    return profile


#: Two limits hold for every persona this pipeline produces, whatever the model
#: wrote: the evidence is public-only, and it is a snapshot. They are appended
#: rather than left to the prompt so they cannot be optimised away by a model
#: that found a lot of material and felt confident.
def _default_boundaries(profile: PersonaProfile) -> list[str]:
    fixed = [
        f"仅基于 {profile.evidence_items} 条公开材料（全文 {profile.evidence_pages} 篇）蒸馏，公开表达与真实想法可能有差距。",
        f"信息截止到 {profile.built_at[:10]}，此后的观点变化不在其中。",
    ]
    if profile.confidence == "low":
        fixed.append("证据量偏低，本画像应当作草稿，落地前请人工复核。")
    return [b for b in profile.boundaries if b not in fixed] + fixed


def _default_slugify(name: str) -> str:
    from gaworld.city.bundle import slugify

    return slugify(name)
