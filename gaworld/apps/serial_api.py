"""Dashboard backend for 连续剧 (Serial Drama), the playground's fifteenth game.

The user picks a handful of residents, names a *theme* (one of the built-in
genres or a free-form subject), and the model writes a multi-episode drama
script where every named character is one of those residents. The output is
**shot cards** — not prose chapters. Each shot has the fields a video
generation model (Kling / Sora / Veo / Hailuo / Vidu) actually needs:
location, time of day, shot type, characters present, an English / Chinese
visual prompt, optional dialogue, estimated seconds, and a transition tag.

Three things worth knowing before reading the code:

* **A shot card is the unit, not a paragraph.** A novel sells word count;
  a serial sells *one continuous shot*. The chapter here is the **episode**,
  and an episode is ``shots`` (4–10 per episode by default). Every prompt
  the model writes is structured JSON, so the back end can hand a clean
  ``shots.json`` straight to the next pipeline without re-parsing prose.

* **Two planning calls + one per-episode call.** ``premise → episode
  outline → episode``. Splitting the planning keeps the cast locked and
  the per-episode shot list under the prompt budget. A second, much cheaper
  call writes a marketing logline after the last episode.

* **Persona fidelity over cinematographic cleverness.** Same idea as
  :mod:`gaworld.apps.novel_api`: a resident's age, job, voice, and values
  must show up in how their character acts and speaks on screen. A shot that
  puts a 65-year-old retiree doing parkour is a failure we test for.

Conventions follow :mod:`gaworld.apps.novel_api`: a background job with
progress, in-memory state, injectable LLM entry points (``planner_fn`` /
``episode_fn`` / ``logline_fn``), and nothing ever written back to a city
bundle.
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

_LOG = get_logger("gaworld.dashboard.serial_api")

#: Cast size. Same ceiling as the novel writer: six voices already stress the
#: prompt budget on every per-episode call.
MIN_AGENTS = 2
MAX_AGENTS = 6

#: Episodes per season. Two is barely a pilot; eight is a short web-drama.
MIN_EPISODES = 2
MAX_EPISODES = 8
DEFAULT_EPISODES = 4

#: Shots per episode. Four is a montage; ten is a tight TV beat. The model
#: writes one shot per JSON object, so this is the per-call cost driver.
MIN_SHOTS_PER_EPISODE = 3
MAX_SHOTS_PER_EPISODE = 12
DEFAULT_SHOTS_PER_EPISODE = 6

#: Episode length budget, in *seconds* of screen time (sum of shot seconds).
#: 60 s ≈ a one-minute short; 180 s ≈ a sitcom episode minus credits.
MIN_EPISODE_SECONDS = 30
MAX_EPISODE_SECONDS = 600
DEFAULT_EPISODE_SECONDS = 120

#: Per-shot duration cap (seconds). Most text-to-video models land in the
#: 5–10 s range per generation; we keep the cap generous so longer mood
#: shots can stitch, but a runaway model is clipped.
MIN_SHOT_SECONDS = 2
MAX_SHOT_SECONDS = 30
DEFAULT_SHOT_SECONDS = 6

#: Visual style presets — the "look" of the show (cinematic language), not
#: the theme. Themes live in :data:`THEME_PRESETS`.
STYLE_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "realistic_cn",
        "title": "国产写实剧",
        "emoji": "🎬",
        "text": (
            "国产家庭 / 都市剧质感。自然光、生活化场景、台词贴近日常,情绪克制,"
            "不刻意制造戏剧性。镜头以中景和近景为主,人物说话带生活的毛边。"
        ),
        "shot_style": "中近景为主,自然光,手持微晃,色调偏暖灰",
    },
    {
        "id": "cinematic",
        "title": "电影质感",
        "emoji": "🎞️",
        "text": ("电影级构图,讲究光影与色彩,镜头语言细腻。适合严肃题材,安静场景里有情绪张力,对白精炼。"),
        "shot_style": "电影级构图,浅景深,冷暖对比,固定机位与缓慢推拉",
    },
    {
        "id": "short_drama",
        "title": "竖屏短剧",
        "emoji": "📱",
        "text": (
            "竖屏短剧节奏——开场 3 秒抓人,每 5–8 秒一个反转或情绪点,"
            "台词短促、冲突密集。适合直接喂可灵 / Sora 竖屏生成。"
        ),
        "shot_style": "竖屏 9:16,特写 + 反应镜头,节奏快,字幕可叠",
    },
    {
        "id": "docu",
        "title": "纪录 / 旁观",
        "emoji": "🎙️",
        "text": ("旁观者视角,采访 + 跟拍质感。减少情节推演,关注人物当下状态。适合心理 / 现实议题。"),
        "shot_style": "跟拍长镜头,环境声保留,人物直视或回避镜头",
    },
    {
        "id": "warm",
        "title": "温暖日常",
        "emoji": "☀️",
        "text": ("以邻里、家庭、小店为底,关心普通人的小决定与小挣扎。镜头节奏慢一点,允许留白。"),
        "shot_style": "自然光,中景为主,留白多,色调偏暖",
    },
)


#: Theme presets. ``text`` is a brief that seeds the planner; ``tone`` is
#: a single sentence that lands in every episode prompt.
THEME_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "family_secret",
        "title": "家庭秘密",
        "tone": "一个家庭里埋了很久的秘密,在某个普通下午被掀开一角。",
        "prompt_seed": "围绕一个家庭成员的过往秘密,看其他人在知道/不知道之间的张力。",
    },
    {
        "id": "neighborhood",
        "title": "小区风云",
        "tone": "同一栋楼里的几户人家,因为一件小事开始互相牵连。",
        "prompt_seed": "聚焦小区/邻里关系,围绕一个公共事件(停车、装修、宠物、谣言)展开。",
    },
    {
        "id": "reunion",
        "title": "同学重聚",
        "tone": "毕业十年后的一次聚会,每个人带着没说出口的近况回来。",
        "prompt_seed": "同学/老友重聚,过去的选择 vs 现在的处境,对话里见差距。",
    },
    {
        "id": "small_business",
        "title": "小店风波",
        "tone": "一家小店的经营危机,把合伙人的关系推到临界。",
        "prompt_seed": "围绕一家小店(咖啡馆/书店/修理铺),合作、债务、亲情混在一起。",
    },
    {
        "id": "missing_person",
        "title": "失踪 / 寻找",
        "tone": "一个人突然消失,留下的人各自拼凑他/她最后的样子。",
        "prompt_seed": "围绕'失踪/寻找'主线,通过不同人的回忆拼出失踪者。",
    },
    {
        "id": "returning_home",
        "title": "返乡",
        "tone": "一个离开家乡多年的人回来,发现自己已经和这里格格不入。",
        "prompt_seed": "返乡题材,看人物与故土、亲人、同学之间微妙的距离感。",
    },
    {
        "id": "wedding",
        "title": "婚礼前夜",
        "tone": "一场婚礼前的 24 小时,各家各怀心事。",
        "prompt_seed": "婚礼前夜到婚礼当天,不同人对这场婚姻的复杂情感。",
    },
    {
        "id": "rent_dispute",
        "title": "合租矛盾",
        "tone": "两个本不相干的人因为一间房被绑在一起。",
        "prompt_seed": "合租/同住关系,从陌生到熟悉(或破裂)的全过程。",
    },
    {
        "id": "mystery_lite",
        "title": "轻悬疑",
        "tone": "一件小事好像不对劲,几个人各自有版本。",
        "prompt_seed": "轻悬疑题材,不血腥,看人物在'不确定'里的反应与选择。",
    },
    {
        "id": "open",
        "title": "自定义主题",
        "tone": "",
        "prompt_seed": "",
    },
)


def list_styles() -> list[dict[str, str]]:
    return [dict(item) for item in STYLE_PRESETS]


def list_themes() -> list[dict[str, str]]:
    return [dict(item) for item in THEME_PRESETS]


def style_by_id(style_id: str) -> dict[str, str] | None:
    for item in STYLE_PRESETS:
        if item["id"] == style_id:
            return item
    return None


def theme_by_id(theme_id: str) -> dict[str, str] | None:
    for item in THEME_PRESETS:
        if item["id"] == theme_id:
            return item
    return None


def resolve_style(style_id: str, custom: dict[str, str] | None = None) -> dict[str, str]:
    """Pick a style: one from the bank, or the caller's own.

    A ``custom`` block must carry ``text``; ``shot_style`` is optional.
    """
    if custom:
        text = str(custom.get("text") or "").strip()
        if not text:
            raise ValueError("自定义视觉风格要写点内容")
        shot_style = str(custom.get("shot_style") or "中近景为主,自然光").strip()
        return {
            "id": "custom",
            "title": str(custom.get("title") or "自定义视觉风格").strip() or "自定义视觉风格",
            "text": text,
            "shot_style": shot_style,
        }
    found = style_by_id(str(style_id or ""))
    if found is None:
        raise ValueError(f"没有这个视觉风格:{style_id or '（未选）'}")
    return dict(found)


def resolve_theme(theme_id: str, custom: dict[str, str] | None = None) -> dict[str, str]:
    """Pick a theme: built-in or the caller's own.

    A ``custom`` block must carry ``tone``; ``prompt_seed`` is optional.
    """
    if custom:
        tone = str(custom.get("tone") or "").strip()
        if not tone:
            raise ValueError("自定义主题要写一句话讲清核心情境(tone)")
        seed = str(custom.get("prompt_seed") or tone).strip()
        return {
            "id": "custom",
            "title": str(custom.get("title") or "自定义主题").strip() or "自定义主题",
            "tone": tone,
            "prompt_seed": seed,
        }
    found = theme_by_id(str(theme_id or ""))
    if found is None:
        raise ValueError(f"没有这个主题:{theme_id or '（未选）'}")
    return dict(found)


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
        cards.append(
            {
                "agent_id": int(agent_id),
                "name": person["name"],
                "age": person.get("age", ""),
                "gender": person.get("gender", ""),
                "job": person.get("job", ""),
                "residence": person.get("residence", ""),
                "profile_md": profile_block(city, int(agent_id)),
            }
        )
    # Mirror novel_api: trim to keep prompt budget under control on long runs.
    for card in cards:
        card["persona_short"] = persona_block(card)[:1200]
    return cards


def _cast_block(cards: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for card in cards:
        lines.append(
            f"【角色】{card['name']}（#{card['agent_id']}，{card['age']}岁，{card['gender']}，{card['job'] or '—'}）"
        )
        short = card.get("persona_short") or ""
        if short:
            lines.append(short)
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_planner_llm(prompt: str) -> str:
    """Planner (premise + episode outline). Lower temp for stable structure."""
    return _call_llm(prompt, task="games.serial.plan", temperature=0.5)


def _default_episode_llm(prompt: str) -> str:
    """Shot-card writer per episode. Warmer for cinematic variety."""
    return _call_llm(prompt, task="games.serial.episode", temperature=0.75)


def _default_logline_llm(prompt: str) -> str:
    """Logline / cover copy. Low temp for stable copy."""
    return _call_llm(prompt, task="games.serial.logline", temperature=0.4)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _premise_prompt(
    theme: dict[str, str],
    style: dict[str, str],
    cards: list[dict[str, Any]],
    user_brief: str,
) -> str:
    return (
        "你是一位电视剧编剧,正在为一个由真实居民档案做主演的连续剧定调。\n"
        "档案里的人一定要全部出现在剧里——每个名字都必须承担一个功能,不能丢掉任何一个。\n\n"
        f"【视觉风格】{style['title']}:{style['text']}\n"
        f"【镜头语言】{style['shot_style']}\n"
        f"【主题】{theme['title']}:{theme['tone']}\n"
        f"【主题提示】{theme['prompt_seed']}\n"
        f"【用户补充设定(可空)】{user_brief.strip() or '（无）'}\n\n"
        f"【已锁定的主角团(不能增减)】\n{_cast_block(cards)}\n\n"
        "请给出:\n"
        " - 1 句话的 *premise*(核心情境 + 核心冲突,要能撑起一整季)。\n"
        " - 给每个居民分配一个**叙事功能**(主角 / 推动情节 / 对手 / 见证者 / 润滑剂),"
        "用一两句话讲他/她在整季开头→结尾的变化或不变。\n"
        " - 整季的情绪弧线 *arc*(三句话以内,讲清从开篇到结尾情绪怎么走)。\n\n"
        "只输出一个 JSON 对象,不要任何解释:\n"
        "{\n"
        '  "premise": "一句话核心情境",\n'
        '  "cast": [{"agent_id": <int>, "role": "<五类之一>", "arc": "一两句话弧线"}],\n'
        '  "arc": "整季情绪弧线,三句话内"\n'
        "}"
    )


def _outline_prompt(
    premise: str,
    arc: str,
    locked_cast: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    theme: dict[str, str],
    style: dict[str, str],
    episodes: int,
    seconds_per_episode: int,
) -> str:
    cast_lines = []
    for entry in locked_cast:
        card = next((c for c in cards if c["agent_id"] == entry["agent_id"]), None)
        if not card:
            continue
        cast_lines.append(f"- {card['name']}(#{entry['agent_id']})——{entry['role']}:{entry['arc']}")
    return (
        "你是一位电视剧编剧,现在为已经定了角色的一部剧编排分集大纲。\n"
        f"【视觉风格】{style['title']}:{style['text']}\n"
        f"【镜头语言】{style['shot_style']}\n"
        f"【主题】{theme['title']}:{theme['tone']}\n\n"
        f"【核心情境】{premise}\n"
        f"【整季弧线】{arc}\n\n"
        f"【角色分配(已锁)】\n" + "\n".join(cast_lines) + "\n\n"
        f"【集数】{episodes} 集。\n"
        f"【单集目标时长】约 {seconds_per_episode} 秒(由镜头秒数累加)。\n\n"
        "请把整季拆成每集:\n"
        " - episode: 1-based 集号\n"
        " - title: 集名(尽量具体不抽象,带情绪)\n"
        " - logline: 一句话讲清这一集发生了什么、关键反转是什么\n"
        " - characters: 本集出场的角色编号(agent_id)列表\n"
        " - hook_to_next: 一句话讲清本集末尾给下一集留下的钩子\n\n"
        "约束:\n"
        " - 第 1 集要把核心情境立起来;最后一集要收束(不一定是圆满,但要有变化)。\n"
        " - 主线角色(主角/对手/推动情节)至少贯穿 70% 的集数。\n"
        " - 不要把所有高潮都堆在最后一集;中间集要有 1 个转折或 1 个情绪峰值。\n"
        " - 每集至少 2 个角色出场。\n\n"
        "只输出一个 JSON 对象,不要任何解释:\n"
        "{\n"
        '  "episodes": [\n'
        '    {"episode": <int>, "title": "<标题>", "logline": "<一句话>", "characters": [<agent_id>, ...], "hook_to_next": "<一句话>"}\n'
        "  ]\n"
        "}"
    )


def _episode_prompt(
    episode: dict[str, Any],
    episode_index: int,
    total_episodes: int,
    cards: list[dict[str, Any]],
    theme: dict[str, str],
    style: dict[str, str],
    premise: str,
    arc: str,
    shots_per_episode: int,
    seconds_per_episode: int,
    prior_loglines: list[str],
    recent_shot_prompts: list[str],
) -> str:
    by_id = {c["agent_id"]: c for c in cards}
    cast_lines = []
    for cid in episode.get("characters", []):
        card = by_id.get(int(cid))
        if card:
            cast_lines.append(
                f"- {card['name']}(#{card['agent_id']}, {card['job'] or '—'})\n  {card['persona_short']}"
            )

    prior_block = ""
    if prior_loglines:
        prior_block = "【前情提要(逐集 logline)】\n" + "\n".join(
            f"第{i + 1}集: {line}" for i, line in enumerate(prior_loglines)
        )

    recent_block = ""
    if recent_shot_prompts:
        # Keep at most 4 of the most recent shot prompts so the model avoids
        # repeating the same beat verbatim.
        sample = recent_shot_prompts[-4:]
        recent_block = "【上一集末尾的镜头(避免重复)】\n" + "\n".join(f"- {p}" for p in sample)

    return (
        f"你是一位电视剧编剧,正在写第{episode_index}集 / 共{total_episodes}集的镜头脚本。\n"
        f"【视觉风格】{style['title']}:{style['text']}\n"
        f"【镜头语言】{style['shot_style']}\n"
        f"【主题】{theme['title']}:{theme['tone']}\n\n"
        f"【整季核心情境】{premise}\n"
        f"【整季弧线】{arc}\n\n"
        f"【本集梗概】{episode.get('logline', '')}\n"
        f"【集末钩子】{episode.get('hook_to_next', '')}\n\n"
        f"【本集出场角色档案】\n" + "\n\n".join(cast_lines) + "\n\n"
        f"【本集镜头预算】{shots_per_episode} 个镜头,合计约 {seconds_per_episode} 秒。\n\n"
        f"{prior_block}\n"
        f"{recent_block}\n\n"
        "请按顺序给出本集的镜头脚本,每个镜头是一个 JSON 对象。\n"
        "字段约定:\n"
        " - shot: 1-based 镜头序号(从 1 开始)\n"
        ' - location: <str> 场景(如"小区楼下便利店"、"老王家的厨房")\n'
        ' - time: <str> 时间(如"白天"、"傍晚"、"夜里十一点")\n'
        ' - shot_type: <str> 镜头类型(如"特写"、"中景"、"全景"、"俯视"、"手持跟拍"、"对话双人中近景")\n'
        " - characters: [<agent_id>, ...] 出场角色,只能从本集出场列表里挑\n"
        " - visual_prompt: <str> 给视频生成模型的画面描述,80–180 字,中文。必须具体(场景、光线、镜头运动、人物状态),不要抽象。\n"
        ' - dialogue: <str|[]> 该镜头的台词,可以是单条字符串或数组 [{character: <agent_id>, line: "..."}];无台词留空数组\n'
        " - sound: <str> 环境声 / 配乐提示,一句话即可\n"
        " - duration: <int> 该镜头秒数(2–30 之间整数)\n"
        ' - transition: <str> 与下一个镜头的转场("cut","dissolve","fade","match_cut","wipe" 之一)\n\n'
        "硬性要求:\n"
        f" - 共 {shots_per_episode} 个镜头;最后一个用 shot={shots_per_episode} 收尾。\n"
        f" - 所有 duration 之和 ≈ {seconds_per_episode} 秒(允许 ±10%)。\n"
        " - visual_prompt 不能含模型外第三人称说教、不能含'本章完'类元叙述。\n"
        " - 台词必须符合出场角色的档案(年龄、职业、口吻、价值观),不要让他们说通用台词。\n"
        " - 不要给视觉描述加引号或加标题;直接写一段连续画面。\n"
        " - 整集输出一个 JSON 对象,顶层字段是 ``shots``,不要任何前后解释文字。\n\n"
        "只输出一个 JSON 对象,结构如下:\n"
        "{\n"
        '  "shots": [\n'
        "    { /* shot 1 ... */ },\n"
        "    { /* shot 2 ... */ }\n"
        "  ]\n"
        "}"
    )


def _logline_prompt(serial: dict[str, Any]) -> str:
    sample = "\n".join(
        f"第{ep['episode']}集《{ep.get('title', '')}》({sum(int(s.get('duration', 0)) for s in ep.get('shots', []))}秒):{ep.get('logline', '')[:120]}"
        for ep in serial.get("episodes", [])[:5]
    )
    return (
        "你是一位发行编辑,要为一部已经写完的连续剧写一段**剧情简介 / 卖点文案**(120–200 字)。\n"
        "要求:\n"
        " - 不要剧透结局的关键反转;可以暗示张力。\n"
        " - 写出这部剧的核心冲突和值得看的理由。\n"
        " - 不要使用'一部……的剧''引人入胜'之类的套话。\n\n"
        f"【剧名暂定】{serial.get('title', '未命名')}\n"
        f"【主题】{serial.get('theme_title', '')}\n"
        f"【视觉风格】{serial.get('style_title', '')}\n"
        f"【角色】" + "、".join(c["name"] for c in serial.get("cast", [])) + "\n\n"
        f"【分集梗概示例】\n{sample}\n\n"
        "只输出简介正文,不要标题、不要'简介:'。"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


_SHOT_TRANSITIONS = {"cut", "dissolve", "fade", "match_cut", "wipe"}


def _parse_premise(raw: str, picked_ids: list[int]) -> dict[str, Any]:
    payload = first_json_object(raw)
    picked_set = {int(i) for i in picked_ids}
    cast = payload.get("cast") if isinstance(payload, dict) else None
    cleaned: list[dict[str, Any]] = []
    if isinstance(cast, list):
        for entry in cast:
            if not isinstance(entry, dict):
                continue
            try:
                agent_id = int(entry.get("agent_id"))
            except (TypeError, ValueError):
                continue
            if agent_id not in picked_set:
                continue
            cleaned.append(
                {
                    "agent_id": agent_id,
                    "role": str(entry.get("role") or "见证者").strip(),
                    "arc": str(entry.get("arc") or "").strip()[:200],
                }
            )
    if not cleaned:
        cleaned = [{"agent_id": aid, "role": "见证者", "arc": "作为剧中的一员出现"} for aid in picked_ids]
    return {
        "premise": str(payload.get("premise") or "").strip()[:300],
        "cast": cleaned,
        "arc": str(payload.get("arc") or "").strip()[:400],
    }


def _parse_outline(raw: str, picked_ids: list[int], episodes: int) -> list[dict[str, Any]]:
    payload = first_json_object(raw)
    rows = payload.get("episodes") if isinstance(payload, dict) else None
    cleaned: list[dict[str, Any]] = []
    picked_set = {int(i) for i in picked_ids}
    if not isinstance(rows, list):
        rows = []
    for index, entry in enumerate(rows, start=1):
        if not isinstance(entry, dict):
            continue
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
            clean_ids = list(picked_set)
        cleaned.append(
            {
                "episode": int(entry.get("episode") or index),
                "title": str(entry.get("title") or f"第{index}集").strip()[:60],
                "logline": str(entry.get("logline") or "").strip()[:200],
                "characters": clean_ids,
                "hook_to_next": str(entry.get("hook_to_next") or "").strip()[:200],
            }
        )
    if not cleaned:
        # Defensive fallback — same shape so the per-episode loop never crashes.
        per_chars = list(picked_set)
        cleaned = [
            {
                "episode": i,
                "title": f"第{i}集",
                "logline": "",
                "characters": per_chars,
                "hook_to_next": "",
            }
            for i in range(1, episodes + 1)
        ]
    # Trim or pad to the requested number of episodes.
    if len(cleaned) > episodes:
        cleaned = cleaned[:episodes]
    while len(cleaned) < episodes:
        i = len(cleaned) + 1
        cleaned.append(
            {
                "episode": i,
                "title": f"第{i}集",
                "logline": "",
                "characters": list(picked_set),
                "hook_to_next": "",
            }
        )
    return cleaned


def _parse_episode(raw: str, episode: dict[str, Any], shots_per_episode: int) -> list[dict[str, Any]]:
    """Read shot cards. Repair loose JSON and missing fields silently."""
    payload = first_json_object(raw)
    rows = payload.get("shots") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = []
    cleaned: list[dict[str, Any]] = []
    for index, entry in enumerate(rows, start=1):
        if not isinstance(entry, dict):
            continue
        characters = entry.get("characters") or []
        if not isinstance(characters, list):
            characters = []
        clean_ids: list[int] = []
        for cid in characters:
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            if cid_int in {int(c) for c in episode.get("characters", [])} and cid_int not in clean_ids:
                clean_ids.append(cid_int)
        if not clean_ids:
            clean_ids = list({int(c) for c in episode.get("characters", [])})
        dialogue = entry.get("dialogue")
        if isinstance(dialogue, str):
            dialogue_payload: Any = dialogue.strip()
        elif isinstance(dialogue, list):
            dialogue_payload = [
                {
                    "character": int(item.get("character"))
                    if isinstance(item, dict) and str(item.get("character", "")).isdigit()
                    else item.get("character")
                    if isinstance(item, dict)
                    else None,
                    "line": str(item.get("line") or "").strip() if isinstance(item, dict) else "",
                }
                for item in dialogue
                if isinstance(item, dict)
            ]
        else:
            dialogue_payload = []
        try:
            duration = int(entry.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        duration = max(MIN_SHOT_SECONDS, min(duration, MAX_SHOT_SECONDS))
        transition = str(entry.get("transition") or "cut").strip().lower()
        if transition not in _SHOT_TRANSITIONS:
            transition = "cut"
        cleaned.append(
            {
                "shot": int(entry.get("shot") or index),
                "location": str(entry.get("location") or "未指定场景").strip()[:80],
                "time": str(entry.get("time") or "白天").strip()[:40],
                "shot_type": str(entry.get("shot_type") or "中景").strip()[:40],
                "characters": clean_ids,
                "visual_prompt": str(entry.get("visual_prompt") or "").strip()[:600],
                "dialogue": dialogue_payload,
                "sound": str(entry.get("sound") or "").strip()[:120],
                "duration": duration,
                "transition": transition,
            }
        )
    if not cleaned:
        # Hard fallback: one empty shot so the episode still has something to show.
        cleaned = [
            {
                "shot": 1,
                "location": "未指定",
                "time": "白天",
                "shot_type": "中景",
                "characters": list({int(c) for c in episode.get("characters", [])}),
                "visual_prompt": "",
                "dialogue": [],
                "sound": "",
                "duration": DEFAULT_SHOT_SECONDS,
                "transition": "cut",
            }
        ]
    # Renumber sequentially so the front end always sees shot 1..N.
    for index, shot in enumerate(cleaned, start=1):
        shot["shot"] = index
    # Trim / pad to the requested shot count.
    if len(cleaned) > shots_per_episode:
        cleaned = cleaned[:shots_per_episode]
    while len(cleaned) < shots_per_episode:
        i = len(cleaned) + 1
        cleaned.append(
            {
                "shot": i,
                "location": "续接上一镜头",
                "time": "同前",
                "shot_type": "中景",
                "characters": list({int(c) for c in episode.get("characters", [])}),
                "visual_prompt": "",
                "dialogue": [],
                "sound": "",
                "duration": DEFAULT_SHOT_SECONDS,
                "transition": "cut",
            }
        )
    return cleaned


# ---------------------------------------------------------------------------
# Episodes / Shot dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Shot:
    shot: int
    location: str = ""
    time: str = ""
    shot_type: str = ""
    characters: list[int] = field(default_factory=list)
    visual_prompt: str = ""
    dialogue: Any = ""
    sound: str = ""
    duration: int = DEFAULT_SHOT_SECONDS
    transition: str = "cut"

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot": self.shot,
            "location": self.location,
            "time": self.time,
            "shot_type": self.shot_type,
            "characters": list(self.characters),
            "visual_prompt": self.visual_prompt,
            "dialogue": self.dialogue,
            "sound": self.sound,
            "duration": self.duration,
            "transition": self.transition,
        }


@dataclass
class Episode:
    episode: int
    title: str = ""
    logline: str = ""
    characters: list[int] = field(default_factory=list)
    hook_to_next: str = ""
    shots: list[Shot] = field(default_factory=list)
    total_seconds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode": self.episode,
            "title": self.title,
            "logline": self.logline,
            "characters": list(self.characters),
            "hook_to_next": self.hook_to_next,
            "shots": [s.to_dict() for s in self.shots],
            "total_seconds": self.total_seconds,
        }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

_JOBS = JobStore("serial")


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    _JOBS.reset()


def list_runs() -> list[dict[str, Any]]:
    """Finished serials still in memory, newest first."""
    rows: list[dict[str, Any]] = []
    for row in _JOBS.results():
        result = row.get("result") or {}
        stats = result.get("stats") or {}
        rows.append(
            {
                "job_id": row["job_id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "title": result.get("title", ""),
                "theme_id": result.get("theme_id"),
                "style_id": result.get("style_id"),
                "episodes": stats.get("episodes"),
                "shots": stats.get("shots"),
                "total_seconds": stats.get("total_seconds"),
                "created_at": result.get("created_at"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# The serial
# ---------------------------------------------------------------------------


def run_serial(
    *,
    city: str,
    agent_ids: list[int],
    theme_id: str = "open",
    theme_custom: dict[str, str] | None = None,
    style_id: str = "realistic_cn",
    style_custom: dict[str, str] | None = None,
    episodes: int = DEFAULT_EPISODES,
    shots_per_episode: int = DEFAULT_SHOTS_PER_EPISODE,
    seconds_per_episode: int = DEFAULT_EPISODE_SECONDS,
    title_hint: str = "",
    user_brief: str = "",
    cards: list[dict[str, Any]] | None = None,
    planner_fn: Callable[[str], str] | None = None,
    episode_fn: Callable[[str], str] | None = None,
    logline_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Plan, write, and summarise a serial. One call per episode."""
    progress = progress or (lambda p, m: None)
    agent_ids = [int(i) for i in (agent_ids or [])]
    if len(agent_ids) < MIN_AGENTS:
        raise ValueError(f"至少选 {MIN_AGENTS} 个居民当主演")
    if len(agent_ids) > MAX_AGENTS:
        raise ValueError(f"主演最多 {MAX_AGENTS} 人")
    episodes = max(MIN_EPISODES, min(int(episodes or DEFAULT_EPISODES), MAX_EPISODES))
    shots_per_episode = max(
        MIN_SHOTS_PER_EPISODE,
        min(int(shots_per_episode or DEFAULT_SHOTS_PER_EPISODE), MAX_SHOTS_PER_EPISODE),
    )
    seconds_per_episode = max(
        MIN_EPISODE_SECONDS,
        min(int(seconds_per_episode or DEFAULT_EPISODE_SECONDS), MAX_EPISODE_SECONDS),
    )
    theme = resolve_theme(theme_id, theme_custom)
    style = resolve_style(style_id, style_custom)

    if cards is None:
        cards = _load_personas(city, agent_ids)

    planner = planner_fn or _default_planner_llm
    episode_llm = episode_fn or _default_episode_llm
    logline_llm = logline_fn or _default_logline_llm

    progress(0.04, "正在定调(主题 + 主角弧线)…")
    premise_raw = planner(_premise_prompt(theme, style, cards, user_brief))
    parsed_premise = _parse_premise(premise_raw, agent_ids)
    premise = parsed_premise["premise"] or theme["tone"] or "（核心情境待补）"
    arc = parsed_premise["arc"] or ""
    locked_cast = parsed_premise["cast"]

    progress(0.12, f"正在编排 {episodes} 集大纲…")
    outline_raw = planner(
        _outline_prompt(premise, arc, locked_cast, cards, theme, style, episodes, seconds_per_episode)
    )
    outline_list = _parse_outline(outline_raw, agent_ids, episodes)

    written: list[Episode] = []
    prior_loglines: list[str] = []
    recent_shot_prompts: list[str] = []
    episode_window = max(0.0, 1.0 - 0.16 - 0.05)

    for index, meta in enumerate(outline_list):
        episode = Episode(
            episode=int(meta["episode"]),
            title=str(meta.get("title") or f"第{index + 1}集"),
            logline=str(meta.get("logline") or ""),
            characters=list(meta.get("characters") or agent_ids),
            hook_to_next=str(meta.get("hook_to_next") or ""),
        )
        progress(
            0.16 + episode_window * (index / max(1, len(outline_list))) * 0.92,
            f"第{episode.episode} 集《{episode.title}》",
        )
        prompt = _episode_prompt(
            episode=episode.to_dict(),
            episode_index=episode.episode,
            total_episodes=len(outline_list),
            cards=cards,
            theme=theme,
            style=style,
            premise=premise,
            arc=arc,
            shots_per_episode=shots_per_episode,
            seconds_per_episode=seconds_per_episode,
            prior_loglines=prior_loglines,
            recent_shot_prompts=recent_shot_prompts,
        )
        try:
            raw = episode_llm(prompt)
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("serial episode %s failed: %s", episode.episode, exc)
            raw = ""
        shots = _parse_episode(raw, episode.to_dict(), shots_per_episode)
        episode.shots = [Shot(**shot) for shot in shots]
        episode.total_seconds = sum(s.duration for s in episode.shots)
        written.append(episode)
        prior_loglines.append(episode.logline or f"第{episode.episode}集:{episode.title}")
        recent_shot_prompts.extend(s.visual_prompt for s in episode.shots if s.visual_prompt)

    progress(0.96, "正在写发行文案…")
    draft = {
        "title": title_hint.strip() or "",
        "cast": [
            {
                "agent_id": c["agent_id"],
                "name": next(
                    (card["name"] for card in cards if card["agent_id"] == c["agent_id"]), f"#{c['agent_id']}"
                ),
                "role": c["role"],
                "arc": c["arc"],
            }
            for c in locked_cast
        ],
        "episodes": [ep.to_dict() for ep in written],
        "theme_title": theme["title"],
        "style_title": style["title"],
    }
    try:
        logline = str(logline_llm(_logline_prompt(draft))).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("serial logline failed: %s", exc)
        logline = ""

    progress(0.99, "正在收尾…")
    serial = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "title": title_hint.strip() or _title_from_premise(premise) or theme["title"],
        "logline": logline,
        "premise": premise,
        "arc": arc,
        "theme_id": theme["id"],
        "theme_title": theme["title"],
        "style_id": style["id"],
        "style_title": style["title"],
        "style_shot": style.get("shot_style", ""),
        "cast": draft["cast"],
        "episodes": [ep.to_dict() for ep in written],
        "user_brief": user_brief.strip(),
        "shots_per_episode": shots_per_episode,
        "seconds_per_episode": seconds_per_episode,
        "stats": _stats(written),
        "created_at": time.time(),
    }
    return serial


def _title_from_premise(premise: str) -> str:
    text = str(premise or "").strip()
    if not text:
        return ""
    head = re.split(r"[。!?\n]", text, maxsplit=1)[0].strip()
    return head[:24]


def _stats(episodes: list[Episode]) -> dict[str, Any]:
    total_shots = sum(len(ep.shots) for ep in episodes)
    total_seconds = sum(ep.total_seconds for ep in episodes)
    character_appearances: dict[int, int] = {}
    for ep in episodes:
        for shot in ep.shots:
            for cid in shot.characters:
                character_appearances[int(cid)] = character_appearances.get(int(cid), 0) + 1
    return {
        "episodes": len(episodes),
        "shots": total_shots,
        "total_seconds": total_seconds,
        "avg_shot_seconds": round(total_seconds / max(1, total_shots)),
        "character_appearances": character_appearances,
    }


# ---------------------------------------------------------------------------
# Run entrypoint
# ---------------------------------------------------------------------------


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then start the serial-writing job."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if len(agent_ids) < MIN_AGENTS:
        raise ValueError(f"至少选 {MIN_AGENTS} 个居民当主演")
    if len(agent_ids) > MAX_AGENTS:
        raise ValueError(f"主演最多 {MAX_AGENTS} 人")
    episodes = int(payload.get("episodes") or DEFAULT_EPISODES)
    if episodes < MIN_EPISODES or episodes > MAX_EPISODES:
        raise ValueError(f"集数要在 {MIN_EPISODES}–{MAX_EPISODES} 之间")
    shots_per_episode = int(payload.get("shots_per_episode") or DEFAULT_SHOTS_PER_EPISODE)
    if shots_per_episode < MIN_SHOTS_PER_EPISODE or shots_per_episode > MAX_SHOTS_PER_EPISODE:
        raise ValueError(f"单集镜头数要在 {MIN_SHOTS_PER_EPISODE}–{MAX_SHOTS_PER_EPISODE} 之间")
    seconds_per_episode = int(payload.get("seconds_per_episode") or DEFAULT_EPISODE_SECONDS)
    if seconds_per_episode < MIN_EPISODE_SECONDS or seconds_per_episode > MAX_EPISODE_SECONDS:
        raise ValueError(f"单集时长要在 {MIN_EPISODE_SECONDS}–{MAX_EPISODE_SECONDS} 秒之间")

    theme_id = str(payload.get("theme_id") or "open")
    theme_custom = payload.get("theme_custom") if isinstance(payload.get("theme_custom"), dict) else None
    style_id = str(payload.get("style_id") or "realistic_cn")
    style_custom = payload.get("style_custom") if isinstance(payload.get("style_custom"), dict) else None
    # Fail fast on unknown ids — better a 400 now than a dead job.
    resolve_theme(theme_id, theme_custom)
    resolve_style(style_id, style_custom)

    return _JOBS.run(
        lambda progress: run_serial(
            city=city,
            agent_ids=agent_ids,
            theme_id=theme_id,
            theme_custom=theme_custom,
            style_id=style_id,
            style_custom=style_custom,
            episodes=episodes,
            shots_per_episode=shots_per_episode,
            seconds_per_episode=seconds_per_episode,
            title_hint=str(payload.get("title_hint") or ""),
            user_brief=str(payload.get("user_brief") or ""),
            progress=progress,
        )
    )


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/serial/ branch.
# ---------------------------------------------------------------------------


def _one(query: dict[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/serial/catalogue":
            return {
                "styles": list_styles(),
                "themes": list_themes(),
                "min_agents": MIN_AGENTS,
                "max_agents": MAX_AGENTS,
                "min_episodes": MIN_EPISODES,
                "max_episodes": MAX_EPISODES,
                "default_episodes": DEFAULT_EPISODES,
                "min_shots_per_episode": MIN_SHOTS_PER_EPISODE,
                "max_shots_per_episode": MAX_SHOTS_PER_EPISODE,
                "default_shots_per_episode": DEFAULT_SHOTS_PER_EPISODE,
                "min_episode_seconds": MIN_EPISODE_SECONDS,
                "max_episode_seconds": MAX_EPISODE_SECONDS,
                "default_episode_seconds": DEFAULT_EPISODE_SECONDS,
                "min_shot_seconds": MIN_SHOT_SECONDS,
                "max_shot_seconds": MAX_SHOT_SECONDS,
                "default_shot_seconds": DEFAULT_SHOT_SECONDS,
            }, 200
        if path == "/api/games/serial/agents":
            city = _one(query, "city")
            from gaworld.apps.games_api import list_agents

            return {"agents": list_agents(city)}, 200
        if path == "/api/games/serial/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/serial/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("serial GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/serial/run":
            return {"job_id": start_run(payload)}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("serial POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "DEFAULT_EPISODES",
    "DEFAULT_EPISODE_SECONDS",
    "DEFAULT_SHOTS_PER_EPISODE",
    "MAX_AGENTS",
    "MIN_AGENTS",
    "STYLE_PRESETS",
    "THEME_PRESETS",
    "Episode",
    "Shot",
    "handle_get",
    "handle_post",
    "job_status",
    "list_runs",
    "list_styles",
    "list_themes",
    "reset_jobs",
    "resolve_style",
    "resolve_theme",
    "run_serial",
    "start_run",
    "style_by_id",
    "theme_by_id",
]
