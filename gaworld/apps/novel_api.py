"""Dashboard backend for 小说局 (Novel Writer), the playground's eighth game.

The user picks a handful of residents, hands in an outline and a target word
count, and the model writes a short novel where every named character is one of
those residents. Their persona (occupation, age, voice, values) shapes who
they become in the story; the outline decides what happens.

Three things worth knowing before reading the code:

* **Cast and outline are planned in two separate calls.** A single call that
  does both tends to compress the cast into whatever the outline already names
  — a hand-written outline says "the elderly male neighbour" and the cast list
  quietly drops the female neighbour. Two calls keep the user-supplied set
  fixed and put the model's plot-filling where it belongs.

* **Each chapter is one LLM call.** Cost is the honest answer here: a 10 000-
  character novel with 8 chapters is 1 (cast) + 1 (outline) + 8 (chapters) + 1
  (summary) = 11 calls, which is already heavy enough to need a background
  job and a progress bar. Splitting one chapter into "by scene" lets a long
  chapter (~8 000 chars) hold itself together, but it is not free, and the
  default budget leaves it off.

* **Character fidelity > prose polish.** The persona block goes into every
  chapter prompt, the cast is locked, and a chapter that drops a named
  character is the failure mode we test for. Model flavour text is its own
  problem and not this module's.

Conventions follow :mod:`gaworld.apps.rumor_api`: a background job with
progress, in-memory state, injectable LLM entry points (``answer_fn`` /
``summary_fn``), and nothing ever written back to a city bundle.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.game_jobs import JobStore
from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.novel_api")

#: Residents in one cast. Six voices already strain the budget; a 12-person
#: ensemble means every chapter names most of them and the prompt gets long
#: faster than the story does.
MAX_AGENTS = 6
MIN_AGENTS = 2

#: Target word count, in Chinese characters (mixed CN/EN is fine; we measure
#: the same way the prompt asks).
MIN_TARGET_WORDS = 1000
MAX_TARGET_WORDS = 80_000
DEFAULT_TARGET_WORDS = 10_000

#: A single chapter is one LLM call; the prompt budget per call is the limit.
#: Splitting one chapter into scenes is supported via ``chunks``, but capped
#: so the back end stays predictable.
MIN_CHUNKS_PER_CHAPTER = 1
MAX_CHUNKS_PER_CHAPTER = 3
DEFAULT_CHUNKS_PER_CHAPTER = 1

#: How many recent chapters we re-attach verbatim (vs. one-line summary).
#: Zero means everything is a one-liner; more than two eats the prompt budget.
RECENT_CHAPTERS_VERBATIM = 1

#: Persona block per character. Long enough to keep voice, short enough that
#: six of them still fit alongside the chapter instructions.
CHARACTER_PERSONA_CHARS = 800

# ---------------------------------------------------------------------------
# Style presets — a small, opinionated set, deliberately
# ---------------------------------------------------------------------------

#: Style presets. ``text`` is the writer's voice; ``point_of_view`` is the
#: narration default (one of ``第三人称``, ``第一人称轮换``, ``全知视角``).
STYLE_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "realistic",
        "title": "现实主义",
        "emoji": "🌍",
        "text": "贴近日常生活的笔法，场景具体，节奏不紧不松。人物说话带他们真实身份的口吻；事件可信，不依赖巧合推进。",
        "point_of_view": "第三人称",
    },
    {
        "id": "warm",
        "title": "温暖日常",
        "emoji": "☀️",
        "text": "以邻里、家庭、小店为底,关心普通人的小决定与小挣扎。结尾不必圆满,但基调是温柔的。",
        "point_of_view": "第三人称",
    },
    {
        "id": "mystery",
        "title": "悬疑",
        "emoji": "🔍",
        "text": "一件事没人说得清,几条线索各自走,真相在最后合拢。视角克制,氛围略冷,人物动机模糊比清晰更常见。",
        "point_of_view": "全知视角",
    },
    {
        "id": "drama",
        "title": "都市情感",
        "emoji": "🌆",
        "text": "围绕关系和选择的拉扯,人物在压力下的真实反应,对话密度高,内心戏克制。",
        "point_of_view": "第一人称轮换",
    },
    {
        "id": "comedy",
        "title": "轻喜",
        "emoji": "😄",
        "text": "节奏明快,误会和巧合可以多一点,对话讲机锋,人物性格鲜明,结局不必惊天动地但要有回味。",
        "point_of_view": "第三人称",
    },
)


def list_styles() -> list[dict[str, str]]:
    return [dict(item) for item in STYLE_PRESETS]


def style_by_id(style_id: str) -> dict[str, str] | None:
    for item in STYLE_PRESETS:
        if item["id"] == style_id:
            return item
    return None


def resolve_style(style_id: str, custom: dict[str, str] | None = None) -> dict[str, str]:
    """Pick a style: one from the bank, or the caller's own.

    A ``custom`` block must carry both ``text`` and ``point_of_view``.
    """
    if custom:
        text = str(custom.get("text") or "").strip()
        pov = str(custom.get("point_of_view") or "").strip()
        if not text:
            raise ValueError("自定义风格要写点内容")
        if not pov:
            pov = "第三人称"
        return {"id": "custom", "title": str(custom.get("title") or "自定义风格").strip() or "自定义风格", "text": text, "point_of_view": pov}
    found = style_by_id(str(style_id or ""))
    if found is None:
        raise ValueError(f"没有这个风格：{style_id or '（未选）'}")
    return dict(found)


# ---------------------------------------------------------------------------
# Word counting
# ---------------------------------------------------------------------------

_CN_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def count_words(text: str) -> int:
    """Word count for a Chinese novel.

    A Chinese character counts as one word; an English run between
    non-letters counts as one word per whitespace split. The point is to
    keep a single number a human recognises, not to linguistically accurate.
    """
    text = str(text or "")
    if not text.strip():
        return 0
    chinese = len(_CN_CHAR_PATTERN.findall(text))
    # Strip CJK runs before splitting on whitespace; what is left is the EN/digit.
    non_cjk = _CN_CHAR_PATTERN.sub(" ", text)
    english = len([w for w in non_cjk.split() if w])
    return chinese + english


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


def _load_personas(city: str, agent_ids: list[int]) -> list[dict[str, Any]]:
    """Persona cards for the cast, in the order they were picked."""
    from gaworld.apps.games_api import persona_block
    from gaworld.interview.roster import load_population, profile_block

    by_id = {int(p["id"]): p for p in load_population(city)}
    cards: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        person = by_id.get(int(agent_id))
        if person is None:
            raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
        profile = profile_block(city, int(agent_id))
        card = {
            "agent_id": int(agent_id),
            "name": person["name"],
            "age": person.get("age", ""),
            "gender": person.get("gender", ""),
            "job": person.get("job", ""),
            "residence": person.get("residence", ""),
            "profile_md": profile,
        }
        # A trimmed block for prompts — the full block runs into the budget fast
        # when six cast members ride along on every call.
        full = persona_block(card)
        card["persona_short"] = full[:CHARACTER_PERSONA_CHARS]
        cards.append(card)
    return cards


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_author_llm(prompt: str) -> str:
    """The model writing the novel. Higher temperature than the judges."""
    return _call_llm(prompt, task="games.novel", temperature=0.85)


def _default_structure_llm(prompt: str) -> str:
    """Cast + outline planner. Lower temperature for stable structure."""
    return _call_llm(prompt, task="games.novel.structure", temperature=0.4)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _cast_block(cards: list[dict[str, Any]]) -> str:
    """The cast as a single block — characters never get reshuffled across
    calls once the cast is locked."""
    lines: list[str] = []
    for card in cards:
        lines.append(
            f"【角色】{card['name']}（#{card['agent_id']}，{card['age']}岁，{card['gender']}，{card['job'] or '—'}）"
        )
        short = card["persona_short"]
        if short:
            lines.append(short)
    return "\n\n".join(lines)


def _cast_prompt(outline: str, target_words: int, style: dict[str, str], cards: list[dict[str, Any]]) -> str:
    return (
        "你是一位小说编辑,正在为一部由真实居民档案做主角的小说分配角色。\n"
        "档案里的人一定要全部出现在小说里——每个名字都必须承担一个功能,不能丢掉任何一个。\n\n"
        f"【作者风格】{style['title']}：{style['text']}\n"
        f"【目标字数】约 {target_words} 字(中文字符),允许 ±10%。\n"
        f"【作者给出的故事大纲】\n{outline.strip() or '（大纲留白,请你自行设计一条完整故事线,但要用上下面所有人）'}\n\n"
        f"【已锁定的主角团(不能增减)】\n{_cast_block(cards)}\n\n"
        "请给每个人分配一个**叙事功能**——他/她在故事里担任什么角色,贯穿全文的弧线是什么。\n"
        "功能类别请用这些中的一个:主角 / 推动情节 / 见证者 / 对手 / 润滑剂。\n"
        "【主角】只能有一个,且必须是档案里那位最容易被读者跟随的——通常是中年、有牵绊的人。\n"
        "【对手】可以没有,可以有一个——是主角面对的阻力,不一定坏,只是立场不同。\n"
        "其余角色承担必要的剧情钩子和情感密度。\n\n"
        "只输出一个 JSON 对象,不要任何解释:\n"
        '{\n'
        '  "cast": [\n'
        '    {"agent_id": <int>, "role": "<五类之一>", "arc": "一两句话讲清他/她在故事开头→结尾的变化或不变"}\n'
        '  ],\n'
        '  "premise": "一两句话讲清这部小说的核心情境和核心冲突"\n'
        "}"
    )


def _outline_prompt(
    cast_result: dict[str, Any],
    outline: str,
    target_words: int,
    style: dict[str, str],
    cards: list[dict[str, Any]],
) -> str:
    cast_lines = []
    for entry in cast_result.get("cast", []):
        card = next((c for c in cards if c["agent_id"] == entry["agent_id"]), None)
        if not card:
            continue
        cast_lines.append(
            f"- {card['name']}（#{entry['agent_id']}）——{entry['role']}：{entry['arc']}"
        )
    premise = str(cast_result.get("premise") or "").strip()
    return (
        f"你是一位小说编辑,现在为已经定了角色的一部小说编排章节大纲。\n"
        f"【作者风格】{style['title']}：{style['text']}\n"
        f"【视角】{style['point_of_view']}\n"
        f"【目标字数】约 {target_words} 字(中文字符)。\n\n"
        f"【核心情境】{premise}\n\n"
        f"【作者大纲】\n{outline.strip() or '（请自行设计完整故事线,保证从头到尾是一个完整的故事,不要片段拼贴）'}\n\n"
        f"【角色分配（已锁）】\n" + "\n".join(cast_lines) + "\n\n"
        "请把故事拆成 8–15 章,每章标一个标题(尽量具体不抽象)、一句话梗概、目标字数、"
        "本章出现的角色编号列表。\n"
        "约束:\n"
        f" - 所有章节的 target_words 加起来应在 {target_words - target_words // 10}–{target_words + target_words // 10} 之间。\n"
        " - 每章至少出现一位角色;主线角色(主角/对手/推动情节)至少贯穿 60% 的章节。\n"
        " - 第一章要把核心情境立起来;最后一章要有收束(不一定是圆满,但要有变化)。\n"
        " - 不要把所有高潮都堆在中后;第三章之前要有第一个转折或第一个钩子。\n\n"
        "只输出一个 JSON 对象,不要任何解释:\n"
        '{\n'
        '  "chapters": [\n'
        '    {"chapter": <1-based int>, "title": "<标题>", "summary": "<一句话梗概>", "target_words": <int>, "characters": [<agent_id>, ...]}\n'
        '  ]\n'
        "}"
    )


def _chapter_prompt(
    chapter_meta: dict[str, Any],
    cards: list[dict[str, Any]],
    style: dict[str, str],
    premise: str,
    recent_summaries: list[tuple[int, str]],
    recent_chapters: list[tuple[int, str]],
    prior_chapter_text: str,
) -> str:
    """One chapter, given the cast, premise, prior summaries, and one prior chapter verbatim."""
    by_id = {c["agent_id"]: c for c in cards}
    cast_lines = []
    for cid in chapter_meta.get("characters", []):
        card = by_id.get(int(cid))
        if card:
            cast_lines.append(
                f"- {card['name']}（#{card['agent_id']}, {card['job'] or '—'}）\n  {card['persona_short']}"
            )
    summary_lines = "\n".join(f"第{idx}章：{summary}" for idx, summary in recent_summaries) or "（这是第一章）"

    prior_block = ""
    if recent_chapters:
        prior_block = "【前文（最新一章原文,供你接文）】\n" + "\n\n".join(
            f"第{idx}章：\n{text}" for idx, text in recent_chapters
        )

    return (
        f"你正在写一部小说的第{chapter_meta['chapter']}章。\n"
        f"【作者风格】{style['title']}：{style['text']}\n"
        f"【视角】{style['point_of_view']}\n"
        f"【核心情境】{premise}\n\n"
        f"【本章梗概】{chapter_meta.get('summary', '')}\n"
        f"【本章目标字数】约 {chapter_meta.get('target_words', 1500)} 字(中文字符),允许 ±15%。\n\n"
        f"【本章出场角色档案】\n" + "\n\n".join(cast_lines) + "\n\n"
        f"【前文梗概(用于衔接)】\n{summary_lines}\n\n"
        f"{prior_block}\n"
        "【写作要求】\n"
        " - 严格按上面出场角色的档案来写——他们的职业、年龄、口吻、性格都要在对话和行为里显出来,不能变成通用角色。\n"
        " - 对话要带具体身份感:让一个 65 岁的退休者和一个 25 岁的便利店店员说话不一样。\n"
        " - 场景要落地:具体地点、具体物件、具体时间(不一定要写出,但要能用上)。\n"
        " - 这一章的标题**不要写在正文里**(它会自动加)。\n"
        " - 不要写'本章完'、'未完待续'、作者署名之类。\n"
        " - 不要用 markdown 标题、分隔线、加粗;正文用段落。\n"
        " - 不要总结、不要复述、不要反思上一章;直接开始本章。\n"
        " - 本章人物最少出场 2 次(对话/直接行动/被其他人议论,任一即可)。\n\n"
        "现在开始正文:"
    )


def _summary_prompt(novel: dict[str, Any]) -> str:
    chapters = novel.get("chapters", [])
    cast = novel.get("cast", [])
    sample = "\n".join(
        f"第{c['chapter']}章《{c['title']}》（{c.get('word_count', 0)}字）:{c.get('text', '')[:200]}…"
        for c in chapters[:5]
    )
    return (
        "你是一位出版编辑,要为一篇已经写完的小说写一段**封面简介**(150–250 字)。\n"
        "要求:\n"
        " - 不要剧透结局的解法或关键反转;可以暗示张力。\n"
        " - 写出核心冲突和这部小说值得读的理由。\n"
        " - 不要使用「一部……的小说」「引人入胜」之类的套话。\n\n"
        f"【书名暂定】{novel.get('title', '未命名')}\n"
        f"【角色】" + "、".join(c["name"] for c in cast) + "\n\n"
        f"【章节开头示例】\n{sample}\n\n"
        "只输出简介正文,不要标题、不要'简介：'。"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_cast(raw: str) -> dict[str, Any]:
    payload = first_json_object(raw)
    if not payload:
        return {"cast": [], "premise": str(raw or "").strip()[:300]}
    cast = payload.get("cast") or []
    if not isinstance(cast, list):
        cast = []
    cleaned: list[dict[str, Any]] = []
    for entry in cast:
        if not isinstance(entry, dict):
            continue
        try:
            agent_id = int(entry.get("agent_id"))
        except (TypeError, ValueError):
            continue
        cleaned.append(
            {
                "agent_id": agent_id,
                "role": str(entry.get("role") or "见证者").strip(),
                "arc": str(entry.get("arc") or "").strip()[:200],
            }
        )
    return {
        "cast": cleaned,
        "premise": str(payload.get("premise") or "").strip()[:300],
    }


def _parse_outline(raw: str, picked_ids: list[int]) -> list[dict[str, Any]]:
    """Read a chapter outline. Repair loose JSON and missing fields silently."""
    payload = first_json_object(raw)
    chapters = payload.get("chapters") or []
    if not isinstance(chapters, list):
        chapters = []
    cleaned: list[dict[str, Any]] = []
    picked_set = {int(i) for i in picked_ids}
    for index, entry in enumerate(chapters, start=1):
        if not isinstance(entry, dict):
            continue
        try:
            target = int(entry.get("target_words") or 1500)
        except (TypeError, ValueError):
            target = 1500
        target = max(300, min(target, 8000))
        characters = entry.get("characters") or []
        if not isinstance(characters, list):
            characters = []
        clean_ids: list[int] = []
        for cid in characters:
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            if cid_int in picked_set and cid_int not in clean_ids:
                clean_ids.append(cid_int)
        if not clean_ids:
            clean_ids = list(picked_set)  # never let a chapter have no cast
        cleaned.append(
            {
                "chapter": int(entry.get("chapter") or index),
                "title": str(entry.get("title") or f"第{index}章").strip()[:60],
                "summary": str(entry.get("summary") or "").strip()[:300],
                "target_words": target,
                "characters": clean_ids,
            }
        )
    if not cleaned:
        # Defensive default if the model flat-out failed to return an outline.
        total = DEFAULT_TARGET_WORDS
        per = max(800, total // 8)
        cleaned = [
            {
                "chapter": i,
                "title": f"第{i}章",
                "summary": "",
                "target_words": per,
                "characters": list(picked_set),
            }
            for i in range(1, 9)
        ]
    return cleaned


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

_JOBS = JobStore("novel")


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    _JOBS.reset()


def list_runs() -> list[dict[str, Any]]:
    """Finished novels still in memory, newest first."""
    rows = []
    for row in _JOBS.results():
        result = row["result"] or {}
        stats = result.get("stats") or {}
        rows.append(
            {
                "job_id": row["job_id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "title": result.get("title", ""),
                "target_words": result.get("target_words"),
                "actual_words": stats.get("total_words"),
                "chapters": len(result.get("chapters", [])),
                "created_at": result.get("created_at"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# The novel
# ---------------------------------------------------------------------------


@dataclass
class Chapter:
    chapter: int
    title: str = ""
    summary: str = ""
    target_words: int = 1500
    characters: list[int] = field(default_factory=list)
    text: str = ""
    word_count: int = 0
    #: Per-character presence score, 0–100. The share of the chapter's
    #: Chinese characters that sit inside a paragraph mentioning that
    #: character by name (their full name in the cast). 0 means they were
    #: listed but the text did not actually engage them.
    presence: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter,
            "title": self.title,
            "summary": self.summary,
            "target_words": self.target_words,
            "characters": list(self.characters),
            "text": self.text,
            "word_count": self.word_count,
            "presence": dict(self.presence),
        }


def _chapter_summary(chapter: Chapter) -> str:
    """A one-line summary used in the next chapter's prompt."""
    text = chapter.text or ""
    snippet = text[:200].replace("\n", " ").strip()
    return f"{chapter.title}：{snippet}"


def _allocate_budgets(outline: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    """Ensure per-chapter targets sum to roughly *target*.

    A common model failure: every chapter reports 1500 words regardless of how
    big the user asked for. Normalize here, then trust the model to hit the
    new target.
    """
    planned = sum(int(c.get("target_words") or 1500) for c in outline)
    if planned <= 0:
        return outline
    scale = target / planned
    cleaned: list[dict[str, Any]] = []
    for entry in outline:
        scaled = max(300, round((entry.get("target_words") or 1500) * scale))
        new_entry = dict(entry)
        new_entry["target_words"] = scaled
        cleaned.append(new_entry)
    # Round-off correction: dump the remainder on the last chapter.
    diff = target - sum(c["target_words"] for c in cleaned)
    if cleaned and diff:
        cleaned[-1]["target_words"] = max(300, cleaned[-1]["target_words"] + diff)
    return cleaned


def run_novel(
    *,
    city: str,
    agent_ids: list[int],
    outline: str,
    target_words: int,
    style_id: str = "realistic",
    style_custom: dict[str, str] | None = None,
    chunks_per_chapter: int = DEFAULT_CHUNKS_PER_CHAPTER,
    title_hint: str = "",
    cards: list[dict[str, Any]] | None = None,
    author_fn: Callable[[str], str] | None = None,
    structure_fn: Callable[[str], str] | None = None,
    summary_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Plan, write, and summarise a novel. One background call per chapter."""
    progress = progress or (lambda p, m: None)
    agent_ids = [int(i) for i in (agent_ids or [])]
    if len(agent_ids) < MIN_AGENTS:
        raise ValueError(f"至少选 {MIN_AGENTS} 个居民当主角")
    if len(agent_ids) > MAX_AGENTS:
        raise ValueError(f"主角团最多 {MAX_AGENTS} 人")
    target = max(MIN_TARGET_WORDS, min(int(target_words or DEFAULT_TARGET_WORDS), MAX_TARGET_WORDS))
    style = resolve_style(style_id, style_custom)

    if cards is None:
        cards = _load_personas(city, agent_ids)

    author = author_fn or _default_author_llm
    structure = structure_fn or _default_structure_llm
    summary = summary_fn or (lambda prompt: _call_llm(prompt, task="games.novel.summary", temperature=0.5))

    name_lookup: dict[int, str] = {int(card["agent_id"]): str(card["name"]) for card in cards}

    progress(0.02, "正在分配角色…")
    cast_raw = structure(_cast_prompt(outline, target, style, cards))
    cast_result = _parse_cast(cast_raw)
    # Lock the cast to the picked agent_ids; never add a phantom character.
    picked_set = set(agent_ids)
    locked_cast = [c for c in cast_result["cast"] if c["agent_id"] in picked_set]
    if locked_cast:
        locked_cast.sort(key=lambda c: agent_ids.index(c["agent_id"]))
    else:
        # Defensive fallback: every picked resident is a 见证者 if the model failed.
        locked_cast = [{"agent_id": aid, "role": "见证者", "arc": "作为故事的一部分出现"} for aid in agent_ids]
    premise = cast_result["premise"] or "（核心情境待补）"

    progress(0.10, "正在编排章节大纲…")
    outline_raw = structure(_outline_prompt({"cast": locked_cast, "premise": premise}, outline, target, style, cards))
    outline_list = _parse_outline(outline_raw, agent_ids)
    outline_list = _allocate_budgets(outline_list, target)

    progress(0.18, f"准备写 {len(outline_list)} 章…")

    written: list[Chapter] = []
    recent_summaries: list[tuple[int, str]] = []
    recent_chapters: list[tuple[int, str]] = []
    prior_chapter_text = ""

    chapter_window = max(1.0 - 0.18 - 0.05, 0.01)
    for index, meta in enumerate(outline_list):
        chapter = Chapter(
            chapter=int(meta["chapter"]),
            title=str(meta.get("title") or f"第{index + 1}章"),
            summary=str(meta.get("summary") or ""),
            target_words=int(meta.get("target_words") or 1500),
            characters=list(meta.get("characters") or agent_ids),
        )
        progress(
            0.18 + chapter_window * (index / max(1, len(outline_list))) * 0.85,
            f"第{chapter.chapter}章《{chapter.title}》",
        )
        prompt = _chapter_prompt(
            chapter_meta={"chapter": chapter.chapter, "summary": chapter.summary, "target_words": chapter.target_words, "characters": chapter.characters},
            cards=cards,
            style=style,
            premise=premise,
            recent_summaries=recent_summaries[-3:],
            recent_chapters=recent_chapters[-RECENT_CHAPTERS_VERBATIM:],
            prior_chapter_text=prior_chapter_text,
        )
        try:
            raw = author(prompt)
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("novel chapter %s failed: %s", chapter.chapter, exc)
            raw = ""
        chapter.text = str(raw).strip()
        chapter.word_count = count_words(chapter.text)
        chapter.presence = compute_presence(chapter, name_lookup)
        written.append(chapter)
        recent_summaries.append((chapter.chapter, _chapter_summary(chapter)))
        recent_chapters.append((chapter.chapter, chapter.text))
        prior_chapter_text = chapter.text

    progress(0.95, "正在写封面简介…")
    novel_draft = {
        "title": title_hint.strip() or f"《{premise[:6]}》" if premise else "",
        "chapters": [c.to_dict() for c in written],
        "cast": [{"agent_id": c["agent_id"], "name": next((card["name"] for card in cards if card["agent_id"] == c["agent_id"]), f"#{c['agent_id']}"), "role": c["role"], "arc": c["arc"]} for c in locked_cast],
        "premise": premise,
    }
    try:
        back_cover = str(summary(_summary_prompt(novel_draft))).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("novel summary failed: %s", exc)
        back_cover = ""

    progress(0.98, "正在收尾…")

    stats = _stats(written, target, locked_cast)
    novel = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "title": title_hint.strip() or _title_from_premise(premise) or "未命名",
        "back_cover": back_cover,
        "premise": premise,
        "outline": [c.to_dict() for c in written],
        "chapters": [c.to_dict() for c in written],
        "cast": novel_draft["cast"],
        "style": style,
        "target_words": target,
        "stats": stats,
        "co_occurrences": compute_co_occurrences(written),
        "created_at": time.time(),
    }
    return novel


def _title_from_premise(premise: str) -> str:
    text = str(premise or "").strip()
    if not text:
        return ""
    # A pick-≤400-char first sentence, no period.
    head = re.split(r"[。!?\n]", text, maxsplit=1)[0].strip()
    return head[:24]


def compute_presence(chapter: Chapter, name_lookup: dict[int, str]) -> dict[str, int]:
    """Per-character presence in this chapter, 0–100.

    "Presence" is the share of Chinese characters that sit inside a paragraph
    mentioning the character by name. It is deliberately approximate: a chapter
    that mentions 闫然 once and is otherwise about her scores ~100, a chapter
    that lists her but only sets her up scores near 0.

    The metric is computed on the model output (not on the prompt) so it is
    a real signal of how the model actually wrote the chapter.
    """
    text = str(chapter.text or "")
    if not text.strip():
        return {str(cid): 0 for cid in chapter.characters}

    presence: dict[str, int] = {}
    for cid in chapter.characters:
        name = name_lookup.get(int(cid), "")
        if not name:
            presence[str(cid)] = 0
            continue
        # Find paragraphs that mention the name, sum their character counts.
        occupied = 0
        for paragraph in re.split(r"[\r\n]+", text):
            if name in paragraph:
                occupied += len(_CN_CHAR_PATTERN.findall(paragraph))
        # Soft cap: score 100 once a quarter of the chapter sits in name-mentioning paragraphs.
        score = min(100, round(occupied * 400 / max(1, chapter.word_count)))
        presence[str(cid)] = score
    return presence


def compute_co_occurrences(chapters: list[Chapter]) -> list[dict[str, Any]]:
    """How often two cast members share a chapter.

    Output rows: ``{"a": <agent_id>, "b": <agent_id>, "count": <int>}``.
    Symmetric: ``(a, b)`` and ``(b, a)`` are not duplicated — pair the lower
    id first. Sorted by descending count then by id.
    """
    pair_counts: dict[tuple[int, int], int] = {}
    for ch in chapters:
        ids = sorted({int(cid) for cid in ch.characters})
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                key = (ids[i], ids[j])
                pair_counts[key] = pair_counts.get(key, 0) + 1
    rows = [
        {"a": a, "b": b, "count": n}
        for (a, b), n in pair_counts.items()
    ]
    rows.sort(key=lambda row: (-row["count"], row["a"], row["b"]))
    return rows


def _stats(chapters: list[Chapter], target: int, cast: list[dict[str, Any]]) -> dict[str, Any]:
    total_words = sum(c.word_count for c in chapters)
    on_target = target > 0 and abs(total_words - target) <= max(300, target // 5)
    character_appearances: dict[int, int] = {}
    for ch in chapters:
        for cid in ch.characters:
            character_appearances[int(cid)] = character_appearances.get(int(cid), 0) + 1
    named_appearances = dict(character_appearances)
    return {
        "chapters": len(chapters),
        "target_words": target,
        "total_words": total_words,
        "on_target": on_target,
        "avg_chapter_words": round(total_words / max(1, len(chapters))),
        "character_appearances": named_appearances,
    }


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then start the novel-writing job."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if len(agent_ids) < MIN_AGENTS:
        raise ValueError(f"至少选 {MIN_AGENTS} 个居民当主角")
    if len(agent_ids) > MAX_AGENTS:
        raise ValueError(f"主角团最多 {MAX_AGENTS} 人")
    outline = str(payload.get("outline") or "").strip()
    if not outline:
        raise ValueError("先填一段故事大纲")
    target_words = int(payload.get("target_words") or DEFAULT_TARGET_WORDS)
    if target_words < MIN_TARGET_WORDS or target_words > MAX_TARGET_WORDS:
        raise ValueError(f"目标字数要在 {MIN_TARGET_WORDS}–{MAX_TARGET_WORDS} 之间")
    style_id = str(payload.get("style_id") or "realistic")
    style_custom = payload.get("style_custom") if isinstance(payload.get("style_custom"), dict) else None
    # Fail fast on an unknown style: better a 400 now than a dead job.
    resolve_style(style_id, style_custom)

    return _JOBS.run(
        lambda progress: run_novel(
            city=city,
            agent_ids=agent_ids,
            outline=outline,
            target_words=target_words,
            style_id=style_id,
            style_custom=style_custom,
            chunks_per_chapter=int(payload.get("chunks_per_chapter") or DEFAULT_CHUNKS_PER_CHAPTER),
            title_hint=str(payload.get("title_hint") or ""),
            progress=progress,
        )
    )


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/novel/ branch.
# ---------------------------------------------------------------------------


def _one(query: dict[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


def _ids(query: dict[str, Any], key: str) -> list[int]:
    raw = query.get(key)
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    out: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/novel/catalogue":
            return {
                "styles": list_styles(),
                "min_agents": MIN_AGENTS,
                "max_agents": MAX_AGENTS,
                "min_target_words": MIN_TARGET_WORDS,
                "max_target_words": MAX_TARGET_WORDS,
                "default_target_words": DEFAULT_TARGET_WORDS,
                "default_chunks_per_chapter": DEFAULT_CHUNKS_PER_CHAPTER,
                "max_chunks_per_chapter": MAX_CHUNKS_PER_CHAPTER,
            }, 200
        if path == "/api/games/novel/agents":
            city = _one(query, "city")
            from gaworld.apps.games_api import list_agents

            return {"agents": list_agents(city)}, 200
        if path == "/api/games/novel/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/novel/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("novel GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/novel/run":
            return {"job_id": start_run(payload)}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("novel POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "DEFAULT_TARGET_WORDS",
    "MAX_AGENTS",
    "MAX_TARGET_WORDS",
    "MIN_AGENTS",
    "MIN_TARGET_WORDS",
    "STYLE_PRESETS",
    "Chapter",
    "count_words",
    "handle_get",
    "handle_post",
    "job_status",
    "list_runs",
    "list_styles",
    "reset_jobs",
    "resolve_style",
    "run_novel",
    "start_run",
    "style_by_id",
]

