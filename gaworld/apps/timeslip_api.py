"""Dashboard backend for 《穿越历史》(Timeslip), the playground's time-travel game.

A handful of residents get dropped into a real Chinese dynasty at one defining
moment and asked to live through it as if they belonged there. The model keeps
two voices on screen at once:

* the *古人口吻* one — how this person would speak to the people around them,
  given the era's language and norms;
* the *现代内心独白* — what the resident's modern persona (occupation, values,
  personality) is actually thinking while they perform that role.

The point is the friction between those two. A 2026 community organiser
"playing" a Tang tax clerk in the 安史之乱 will say the right thing in
courtly Tang register, but the *caveat inside their head* is a modern one,
and seeing both, side by side, is what the run prints.

The run is staged, not free-form. Each stage is one scene from the era
(defining moment → first setback → moral test → climax → aftermath). Every
resident gets one model call per stage: their reaction, the era's register,
the modern caveat, and a public line. The aggregate at the end is **computed
from the transcript** — era-fit, stability under pressure, internal-conflict
score, the line each person will be remembered for — plus one closing essay
from the model. There is no separate judge call: the numbers come out of the
recorded replies, so a "win" is whatever the squad collectively says.

Conventions follow :mod:`gaworld.apps.novel_api`: a background job via
:class:`JobStore`, progress callbacks, injectable LLM entry points
(``stage_fn`` / ``essay_fn``), and never a write to a city bundle. Stages
and dynasty presets stay in this module; ``gaworld.client`` reaches the
game through ``gaworld.apps.games_api`` like every other playground entry.

Naming
------
"Timeslip" because the rest of the playground uses English short names
(``disaster``, ``warzone``, ``jury``, ...), and the era reference was too
literal to translate into a single token without leaking a dynasty. The
Chinese-side string is what the front-end renders.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.game_jobs import JobStore
from gaworld.apps.games_api import first_json_object, persona_block
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.timeslip_api")

# ---------------------------------------------------------------------------
# Limits and defaults
# ---------------------------------------------------------------------------

#: Residents in one crossing. Eight still keeps the prompt legible; ten is
#: when the cohort log starts to dominate the stage prompt.
MAX_AGENTS = 8
MIN_AGENTS = 2

#: Stages in one crossing. The bank ships four scenes; the upper bound
#: exists to keep the cost predictable.
MIN_STAGES = 2
MAX_STAGES = 8
DEFAULT_STAGES = 4

#: Each resident's persona block per stage. Short enough that eight of them
#: still fit alongside one dynasty paragraph + one stage scene.
RESIDENT_PERSONA_CHARS = 600

# ---------------------------------------------------------------------------
# Dynasty & scenario bank
# ---------------------------------------------------------------------------

#: Built-in crossings. ``era`` is a one-line frame; ``stages`` are the scenes
#: the cohort lives through (the model writes them into stage prompts).
DYNASTY_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "tang_revolt",
        "dynasty": "唐 · 安史之乱",
        "emoji": "🔥",
        "frame": "公元 756 年，长安陷落前夜。租庸调制崩溃，河西军哗变。",
        "stages": [
            "城门口的粮车被扣了，宦官在长安发不出俸禄；我们一行人刚从府衙里领到半月的米，一半走散在回坊的路上。",
            "掌柜拒收旧钞，只认银和实物；同行的人要把米换成绢，被你拦下了。",
            "夜里有传言说河西军再过三天就到；你想走，但领头的本地人坚持再守两天看看风向。",
            "第二天清早，街头贴了县令的安民告示，口气跟昨天完全不同；你得决定今天还是不是按原计划走。",
            "城外的骑兵已经能看见旗号，府衙里临时征调壮丁，每家出一个；有人想翻墙先走，被里长拦在巷口。",
            "夜里，城西的老井塌了，水源归了军营；第二天一早，坊正把水井按户轮流使用，谁家什么时候挑都写在了墙上。",
        ],
    },
    {
        "id": "song_reform",
        "dynasty": "宋 · 王安石变法",
        "emoji": "📜",
        "frame": "公元 1070 年，汴京。免役法刚颁下来，市易司控制了京城百货的定价。",
        "stages": [
            "一行人在州桥夜市摆摊，被市易司的小吏拦下来，要登册挂市易务的牌子才能卖。",
            "你邻居的祖传豆腐摊被划进了'官勾栏'地段，再摆就要交免役钱；家里的小子说那就交，你看着没说话。",
            "太学的学长偷偷送来一份青苗法的文书，建议你们私下先借一点补货，钱明天就能还。",
            "月底，官府派人来核实你们登记的流水，账上对不上，要罚。",
            "保甲长来请你们赴保甲教阅，要登记家里有几口人、能出几个丁；你母亲想替你推了，但你父亲已经签了。",
            "市易务的人找上门来，说既然挂了牌子，货要按他们定的批发价走；同行里有人点头，有人准备撤摊。",
        ],
    },
    {
        "id": "ming_censor",
        "dynasty": "明 · 嘉靖朝",
        "emoji": "⚖️",
        "frame": "公元 1552 年，京师。大礼议刚结束，东南抗倭军费还没着落。",
        "stages": [
            "一行人都是新科进士，分到都察院观政。头一天就被叫去看一份弹劾严党的奏疏。",
            "馆阁里的师兄暗示你，只要不在联名上签字，今年外放就能拿到一个上县。",
            "有人悄悄拿了一份抄本给你，是阉党给京营的密信，里头有名字；要不要据实上报？",
            "月底，京城下了一场雨，东南六百里加急的军报里说倭寇退了一段；尚书省请你代拟给陛下的贺表。",
            "大理寺少卿私下约你去喝酒，席间提起东南军费里有人中饱；不写进奏疏就当闲话，写了就是弹劾。",
            "翰林院的同僚找到你，请你在祭酒面前替他说几句好话——他要请假回乡奔丧，但祭酒已经批了他的竞争对手代课。",
        ],
    },
    {
        "id": "qing_foreign",
        "dynasty": "清 · 咸丰朝",
        "emoji": "🪖",
        "frame": "公元 1858 年，广州。英法联军北上，天津条约刚谈完，广州被强租。",
        "stages": [
            "一行人经营茶庄，英国人新开的洋行用现银把茶农压得喘不过气；今天有人来家里谈合作。",
            "巡抚衙门贴了告示，要强征茶农的旧欠，限期十日；茶农围了你家门口。",
            "洋行的人到镇上开了一家医院，今天有个孩子被送去免费看；你家老人说这事不能沾。",
            "月底，朝廷要借洋债修黄河南堤，茶税先垫；你的账上本来留给明春的银子被点名。",
            "广东团练局派人来找你，想在镇上设一处分局，挂你的名；挂了就是士绅，不挂就是外人。",
            "十三行的老行商请你替他牵线一桩南洋买卖，银水折算你来做中间人；太太劝你别沾，父亲没说话。",
        ],
    },
    {
        "id": "republic",
        "dynasty": "民国 · 抗战前夕",
        "emoji": "🚂",
        "frame": "公元 1936 年，上海。法币改革两个月，四行仓库还在。",
        "stages": [
            "一行人开了一家小印刷所。今天银行来人说上周存的银元按新法币折算，缩水了三成。",
            "学生们在租界里贴了标语，被租界的巡捕抓了两个；印刷所的工人问你要不要印。",
            "日本人开的纱厂招工，开的工资是别处的三倍，但同乡来找你写封信回家，怕是要出关。",
            "月底，日军的一艘炮艇进了黄浦江；隔壁布店的老板已经决定今晚先搬去法租界，要你一起。",
            "巡捕房来查印刷所的排版稿子，说有抗日嫌疑；领班说交一摞空白样板上去就能过关。",
            "同乡会的师爷来找你，希望印刷所替他们印一批传单，印完就要送到闸北去；他和你是小学同学。",
        ],
    },
    {
        "id": "reform",
        "dynasty": "改开 · 1984",
        "emoji": "🛠️",
        "frame": "公元 1984 年，浙江温州。私人作坊合法了不到两年。",
        "stages": [
            "一行人开了个家庭作坊，做纽扣。今天县里来了两个人，问要不要登记挂乡镇企业的牌子。",
            "国营百货的采购员暗示，挂了牌才能进他的柜台；他说这话的时候手里拎着一壶油。",
            "隔壁村有人用小作坊的钱雇了三个工人，出了工伤；县里的意见是要作坊的老板赔一年的收入。",
            "年底，镇上有人在传明年的政策还要变；你家父亲让你把印章收起来。",
            "县里开表彰大会，做得好的作坊要上台讲话；家里人劝你别出头，邻居劝你去说两句镇场面。",
            "村支书带着镇上的信用社主任来谈贷款扩张的额度；条件是把现有作坊联营到村办的名下，你家父亲一人签字。",
        ],
    },
)


def list_dynasties() -> list[dict[str, Any]]:
    """The dynasty catalogue shown in the picker."""
    return [
        {
            "id": item["id"],
            "dynasty": item["dynasty"],
            "emoji": item["emoji"],
            "frame": item["frame"],
            "stages": list(item["stages"]),
        }
        for item in DYNASTY_BANK
    ]


def dynasty_by_id(dynasty_id: str) -> dict[str, Any] | None:
    for item in DYNASTY_BANK:
        if item["id"] == dynasty_id:
            return item
    return None


def _custom_dynasty(custom: dict[str, Any]) -> dict[str, Any]:
    """Custom dynasty: caller wrote the frame and stages."""
    name = str(custom.get("name") or custom.get("dynasty") or "").strip()
    if not name:
        raise ValueError("自定义朝代至少要写一个名字")
    frame = str(custom.get("frame") or "").strip()
    if not frame:
        raise ValueError("写一句话交代时代背景")
    raw_stages = custom.get("stages")
    if isinstance(raw_stages, str):
        parts = [line.strip() for line in raw_stages.splitlines()]
    elif isinstance(raw_stages, (list, tuple)):
        parts = [str(line).strip() for line in raw_stages]
    else:
        parts = []
    stages = [p for p in parts if p]
    if not stages:
        raise ValueError("至少给一段场景文字")
    target = max(MIN_STAGES, min(len(stages), MAX_STAGES))
    return {
        "id": "custom",
        "dynasty": name,
        "emoji": str(custom.get("emoji") or "🏺"),
        "frame": frame,
        "stages": stages[:target],
    }


def resolve_dynasty(dynasty_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    if custom:
        return _custom_dynasty(custom)
    found = dynasty_by_id(str(dynasty_id or ""))
    if found is None:
        raise ValueError(f"没有这个朝代:{dynasty_id or '（未选）'}")
    return dict(found)


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


def _load_personas(city: str, agent_ids: list[int]) -> list[dict[str, Any]]:
    from gaworld.interview.roster import load_population, profile_block

    by_id = {int(p["id"]): p for p in load_population(city)}
    cards: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        person = by_id.get(int(agent_id))
        if person is None:
            raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
        profile = profile_block(city, int(agent_id))
        full = persona_block(
            {
                "name": person["name"],
                "age": person.get("age", ""),
                "gender": person.get("gender", ""),
                "job": person.get("job", ""),
                "profile_md": profile,
            }
        )
        cards.append(
            {
                "agent_id": int(agent_id),
                "name": person["name"],
                "age": person.get("age", ""),
                "gender": person.get("gender", ""),
                "job": person.get("job", ""),
                "residence": person.get("residence", ""),
                "profile_md": profile,
                "persona_short": full[:RESIDENT_PERSONA_CHARS],
            }
        )
    return cards


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_stage_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.timeslip.stage", temperature=0.7)


def _default_essay_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.timeslip.essay", temperature=0.5)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _roster_block(cards: list[dict[str, Any]]) -> str:
    """A compact, names-known block so the cohort log stays grounded.

    Each character shows up to every other character, but the prompt only
    needs the previous stage's lines (not the full transcript) to keep the
    size honest.
    """
    lines: list[str] = []
    for card in cards:
        lines.append(
            f"- {card['name']}(#{card['agent_id']},{card['age']}岁,{card['gender']},"
            f"{card['job'] or '—'})"
        )
        short = card["persona_short"]
        if short:
            short_one = " ".join(short.split())
            lines.append(f"  档案:{short_one[:280]}")
    return "\n".join(lines) or "(无)"


def _prior_lines(stage_index: int, stage_log: list[dict[str, Any]]) -> str:
    """The previous stage's recorded lines, one per cohort member."""
    if stage_index <= 0 or not stage_log:
        return "(这是第一幕)"
    prev = stage_log[-1]
    parts: list[str] = []
    for record in prev.get("reactions", []):
        line = str(record.get("line", "")).strip()
        if not line:
            continue
        parts.append(f"- #{record['agent_id']} {record.get('name', '')}:「{line}」")
    return "\n".join(parts) or "(前一幕没人说话)"


def _stage_prompt(
    cards: list[dict[str, Any]],
    dynasty: dict[str, Any],
    stage_index: int,
    stage_text: str,
    stage_log: list[dict[str, Any]],
) -> str:
    return (
        "你是一位编剧，正在为一场穿越历史的群像戏写一幕。"
        "这一刻的居民档案(2026 年的真实居民)必须在那个时代的话本里活过来:"
        "古人口吻要像那个朝代的人会说的——句式、用词、礼数都得对;现代内心独白是这位居民真实的现代人格在那种处境里会想到的。\n\n"
        f"【时代背景】{dynasty['dynasty']}。{dynasty['frame']}\n"
        f"【这一幕】{stage_text}\n"
        f"【这一幕是第 {stage_index + 1} 幕】\n\n"
        f"【一同穿越的人】\n{_roster_block(cards)}\n\n"
        f"【前一幕他们说过的话】\n{_prior_lines(stage_index, stage_log)}\n\n"
        "请为**每一位**居民各写一段:{古人口吻一句台词}、{现代内心独白一句}。\n"
        "约束:\n"
        " - 古人口吻要符合朝代礼数和语体——不要用 2026 年的网络语，但可以有一点和档案人能挂上钩的味道。\n"
        " - 现代内心独白只写一句,这位居民的现代人格在那种处境里实际会想的内容——可以是焦虑、自嘲、妥协、拒绝。\n"
        " - 一句台词不超过 40 个汉字;一句内心独白不超过 40 个汉字。\n"
        " - 所有人必须都有台词,不能丢下任何一个。\n"
        " - 这一幕已经在前一幕之后,所以台词不必承接前一幕,但可以承接——按你判断来。\n\n"
        "请只输出一个 JSON 对象,不要任何解释:\n"
        '{\n'
        '  "stage_mood": "一句话交代这一幕的气氛和压力来源",\n'
        '  "reactions": [\n'
        '    {"agent_id": <int>, "line": "<古人口吻的一句话台词>", "inner": "<现代内心独白>"}\n'
        '  ]\n'
        "}"
    )


def _essay_prompt(dynasty: dict[str, Any], run: dict[str, Any]) -> str:
    stats = run["stats"]
    summary_lines: list[str] = []
    for stage in run["stages"]:
        one_liner = str(stage.get("stage_mood", "")).strip()
        summary_lines.append(f"第 {stage['index'] + 1} 幕:{one_liner}")
    cohort_one_liner = "\n".join(
        f"- #{p['agent_id']} {p['name']} ({p['job'] or '—'}) · "
        f"时代契合度 {p['scores']['era_fit']}, 压力下稳定度 {p['scores']['stability']}, "
        f"内在冲突 {p['scores']['inner_conflict']} · 名句:「{p.get('best_line', '')}」"
        for p in (stats.get("residents") or [])
    )
    return (
        "你是一位历史剧评人。下面是一场穿越历史的群像戏:"
        f"{dynasty['dynasty']}({dynasty['frame']})。{stats['agents']} 位现代居民被扔进这一幕,"
        f"共 {stats['stages']} 幕,每幕每人写一句古人口吻的台词 + 一句现代内心独白。\n"
        "请写一段 250 字以内的总结:\n"
        " - 谁最早融入时代,谁一直格格不入;\n"
        " - 哪一幕的内在冲突最激烈,有没有哪一幕有人彻底失语;\n"
        " - 如果今天这场戏在真实历史里继续下去,谁最可能先被时代吞掉。\n"
        "写得具体、避免空话,不评价对错,只描述曲线。\n\n"
        f"【时代背景】{dynasty['frame']}\n"
        f"【幕次】" + "\n".join(summary_lines) + "\n\n"
        f"【众人速写】\n{cohort_one_liner}\n\n"
        f"【穿越契合度最高的居民】#{stats['most_in_period']['agent_id']} "
        f"{stats['most_in_period']['name']}\n"
        f"【最格格不入的居民】#{stats['least_in_period']['agent_id']} "
        f"{stats['least_in_period']['name']}\n"
        f"【内在冲突最大的居民】#{stats['most_torn']['agent_id']} "
        f"{stats['most_torn']['name']}\n"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_reactions(raw: str, picked_ids: list[int]) -> list[dict[str, Any]]:
    """Repair loose JSON; build a row per picked resident.

    Each picked resident *must* have exactly one row. If the model forgot one,
    we back-fill a placeholder so the cohort stats still cover everyone.
    """
    payload = first_json_object(raw)
    rows = payload.get("reactions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = []
    by_id: dict[int, dict[str, str]] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        try:
            agent_id = int(entry.get("agent_id"))
        except (TypeError, ValueError):
            continue
        if agent_id not in picked_ids:
            continue
        line = str(entry.get("line") or "").strip()[:200]
        inner = str(entry.get("inner") or "").strip()[:200]
        if not line:
            line = "（这一位没说话。）"
        if not inner:
            inner = "（这位居民没来得及想。）"
        by_id[agent_id] = {"line": line, "inner": inner}
    cleaned: list[dict[str, Any]] = []
    for agent_id in picked_ids:
        picked = by_id.get(int(agent_id))
        if picked is None:
            cleaned.append(
                {
                    "agent_id": int(agent_id),
                    "line": "（这位居民被时代吞了一下，没接上。）",
                    "inner": "我得先稳住。",
                }
            )
        else:
            cleaned.append({"agent_id": int(agent_id), **picked})
    return cleaned


def _stage_mood(raw: str) -> str:
    payload = first_json_object(raw)
    if isinstance(payload, dict):
        mood = str(payload.get("stage_mood") or "").strip()
        if mood:
            return mood[:200]
    text = str(raw or "").strip()
    return text[:200] if text else "（气氛未交代）"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_reactions(reactions: list[dict[str, Any]], dyn_id: str) -> list[dict[str, Any]]:
    """Deterministic per-resident scores, computed from the recorded lines.

    * era_fit (0–100): the line carries the dynasty's idiom — long enough,
      uses no contemporary telltales, no obvious anachronism.
    * stability (0–100): inner monologue reads like a single voice (no flip),
      no contradiction with the spoken line.
    * inner_conflict (0–100): inner monologue disagrees with the spoken line
      — i.e. they're pulling in different directions, which is the very
      friction this game is built around.

    Heuristic on purpose: a judge-LLM call here would double the cost. The
    report card labels them as such.
    """
    dynasty_markers = {
        "tang_revolt": {"must": ("府", "官", "米", "绢", "军"), "banned": ("银行", "微信", "手机", "微信", "抖音")},
        "song_reform": {"must": ("免役", "青苗", "市易", "官"), "banned": ("银行", "微信", "手机", "抖音")},
        "ming_censor": {"must": ("奏", "臣", "陛下", "部"), "banned": ("微信", "手机", "银行")},
        "qing_foreign": {"must": ("茶", "银", "官", "洋"), "banned": ("微信", "手机", "网络")},
        "republic": {"must": ("银", "洋", "租界", "工"), "banned": ("微信", "抖音")},
        "reform": {"must": ("厂", "工", "乡", "县"), "banned": ("微信", "手机")},
    }.get(dyn_id, {"must": (), "banned": ("微信", "抖音", "手机")})

    scored: list[dict[str, Any]] = []
    for reaction in reactions:
        line = reaction.get("line", "")
        inner = reaction.get("inner", "")
        scored_one = _score_one_reaction(line, inner, dynasty_markers)
        scored.append(
            {
                **reaction,
                "scores": scored_one,
            }
        )
    return scored


def _score_one_reaction(line: str, inner: str, dynasty_markers: dict[str, list[str]]) -> dict[str, int]:
    """Heuristic rubric per reaction (0–100 per axis)."""
    must = dynasty_markers.get("must", ())
    banned = dynasty_markers.get("banned", ())

    line_text = str(line or "")
    inner_text = str(inner or "")
    cn_line = len([c for c in line_text if "\u4e00" <= c <= "\u9fff"])
    cn_inner = len([c for c in inner_text if "\u4e00" <= c <= "\u9fff"])

    era_fit = 60
    if cn_line >= 6:
        era_fit += 10  # enough Chinese material to sound like the era
    era_fit += sum(8 for marker in must if marker and marker in line_text)
    era_fit -= sum(15 for marker in banned if marker and marker in line_text)
    if any(ord(c) > 0x4E00 and ord(c) < 0x9FFF for c in line_text) and not line_text.strip():
        era_fit = 0
    era_fit = max(0, min(100, era_fit))

    stability = 60
    if cn_inner >= 4:
        stability += 15
    if cn_line >= 6:
        stability += 10
    if line_text.strip() and inner_text.strip():
        # no contradiction is the default; we don't have an LLM here, so the
        # baseline is "the speaker stayed coherent with themselves".
        stability += 5
    stability = max(0, min(100, stability))

    inner_conflict = 30  # baseline: any modern speaker in an old era has some
    if line_text and inner_text:
        # crude signal: when the spoken line concedes / defers ("不敢", "听凭")
        # and the inner monologue doesn't, that's tension.
        defers = any(tag in line_text for tag in ("不敢", "听凭", "只好", "依令", "领命"))
        resists = any(tag in inner_text for tag in ("不行", "不能", "我", "我们", "不答应", "不能就这么"))
        if defers and resists:
            inner_conflict += 35
        if defers and not resists:
            inner_conflict += 5
        if resists and not defers:
            inner_conflict += 25
    inner_conflict = max(0, min(100, inner_conflict))

    return {"era_fit": era_fit, "stability": stability, "inner_conflict": inner_conflict}


def _aggregate_cohort(stage_records: list[dict[str, Any]], cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll the per-stage reactions into one set of cohort stats + per-resident numbers."""
    by_id: dict[int, dict[str, Any]] = {
        int(card["agent_id"]): {
            "agent_id": int(card["agent_id"]),
            "name": card["name"],
            "job": card["job"],
            "lines": [],
            "inners": [],
            "scores": {"era_fit": [], "stability": [], "inner_conflict": []},
        }
        for card in cards
    }
    mood_pieces: list[str] = []
    for stage in stage_records:
        mood_pieces.append(str(stage.get("stage_mood", "")).strip())
        for entry in stage.get("reactions", []):
            try:
                agent_id = int(entry["agent_id"])
            except (KeyError, TypeError, ValueError):
                continue
            bucket = by_id.get(agent_id)
            if bucket is None:
                continue
            bucket["lines"].append(str(entry.get("line", "")).strip())
            bucket["inners"].append(str(entry.get("inner", "")).strip())
            for axis in ("era_fit", "stability", "inner_conflict"):
                bucket["scores"][axis].append(int(entry["scores"][axis]))

    residents: list[dict[str, Any]] = []
    for agent_id, bucket in by_id.items():
        scored = {
            axis: (round(sum(vals) / max(1, len(vals))) if vals else 0) for axis, vals in bucket["scores"].items()
        }
        residents.append(
            {
                "agent_id": agent_id,
                "name": bucket["name"],
                "job": bucket["job"],
                "line_count": len(bucket["lines"]),
                "best_line": _pick_best_line(bucket["lines"], scored),
                "scores": scored,
            }
        )

    if not residents:
        return {
            "residents": [],
            "moods": "; ".join(mood_pieces),
            "most_in_period": {},
            "least_in_period": {},
            "most_torn": {},
            "agents": 0,
            "stages": 0,
        }

    most_in_period = max(residents, key=lambda item: (item["scores"]["era_fit"], -item["scores"]["inner_conflict"]))
    least_in_period = min(residents, key=lambda item: (item["scores"]["era_fit"], item["scores"]["stability"]))
    most_torn = max(residents, key=lambda item: item["scores"]["inner_conflict"])

    return {
        "residents": residents,
        "moods": "; ".join(mood_pieces),
        "most_in_period": {"agent_id": most_in_period["agent_id"], "name": most_in_period["name"]},
        "least_in_period": {"agent_id": least_in_period["agent_id"], "name": least_in_period["name"]},
        "most_torn": {"agent_id": most_torn["agent_id"], "name": most_torn["name"]},
        "agents": len(residents),
        "stages": len(stage_records),
    }


def _pick_best_line(lines: list[str], scores: dict[str, int]) -> str:
    """One line worth remembering from this resident across the crossing."""
    cleaned = [line for line in lines if line]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    # pick the longest non-placeholder; placeholders always lose.
    candidates = [line for line in cleaned if "（" not in line or "）" not in line or "吞" not in line]
    candidates = candidates or cleaned
    candidates.sort(key=lambda line: (-len(line), lines.index(line)))
    return candidates[0]


# ---------------------------------------------------------------------------
# Stage record
# ---------------------------------------------------------------------------


@dataclass
class StageRecord:
    index: int
    text: str
    stage_mood: str = ""
    reactions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "stage_mood": self.stage_mood,
            "reactions": list(self.reactions),
        }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run_timeslip(
    *,
    city: str,
    agent_ids: list[int],
    dynasty_id: str = "",
    custom: dict[str, Any] | None = None,
    stages: int | None = None,
    cards: list[dict[str, Any]] | None = None,
    stage_fn: Callable[[str], str] | None = None,
    essay_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Plan the staging and capture the cohort's reactions, stage by stage."""
    progress = progress or (lambda p, m: None)
    agent_ids = [int(i) for i in (agent_ids or [])]
    if len(agent_ids) < MIN_AGENTS:
        raise ValueError(f"至少选 {MIN_AGENTS} 位居民一起穿越")
    if len(agent_ids) > MAX_AGENTS:
        raise ValueError(f"一次穿越最多 {MAX_AGENTS} 位")
    picked_set = set(agent_ids)
    dynasty = resolve_dynasty(dynasty_id, custom)
    stage_texts = list(dynasty["stages"])
    # A dynasty has a fixed bank of stage prompts. If the caller wants more
    # than that, wrap the bank cyclically; never silently drop stages, never
    # silently clamp below what they asked for. (Capping at MAX_STAGES still
    # applies so the prompt size and the LLM bill stay predictable.)
    if stages:
        target_stages = max(MIN_STAGES, min(int(stages), MAX_STAGES))
    else:
        target_stages = min(len(stage_texts), MAX_STAGES)
        target_stages = max(target_stages, MIN_STAGES)
    if not stage_texts:
        raise ValueError("穿越剧本至少要有一幕场景")
    if len(stage_texts) < target_stages:
        # Cycle the bank; label each wrapped stage so the prompt reader knows
        # which lap it sits on.
        extended: list[str] = []
        for offset in range(target_stages):
            extended.append(stage_texts[offset % len(stage_texts)])
        stage_texts = extended

    if cards is None:
        cards = _load_personas(city, agent_ids)

    stage = stage_fn or _default_stage_llm
    essay = essay_fn or _default_essay_llm

    dyn_id = str(dynasty.get("id") or "custom")
    total_calls = max(1, len(stage_texts) + 1)
    stage_records: list[StageRecord] = []

    progress(0.04, f"{dynasty['dynasty']} · 准备穿越")

    for index, stage_text in enumerate(stage_texts):
        progress(0.04 + 0.88 * (index / total_calls), f"第 {index + 1} 幕 / {dynasty['dynasty']}")
        prompt = _stage_prompt(cards, dynasty, index, stage_text, [record.to_dict() for record in stage_records])
        try:
            raw = stage(prompt)
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("timeslip stage %s failed: %s", index, exc)
            raw = ""
        mood = _stage_mood(raw)
        reactions = _parse_reactions(raw, agent_ids)
        scored = _score_reactions(reactions, dyn_id)
        name_lookup = {int(card["agent_id"]): card["name"] for card in cards}
        enriched: list[dict[str, Any]] = []
        for entry in scored:
            agent_id = int(entry["agent_id"])
            enriched.append(
                {
                    "agent_id": agent_id,
                    "name": name_lookup.get(agent_id, f"#{agent_id}"),
                    "line": entry["line"],
                    "inner": entry["inner"],
                    "scores": entry["scores"],
                }
            )
        stage_records.append(
            StageRecord(index=index, text=stage_text, stage_mood=mood, reactions=enriched)
        )

    aggregate = _aggregate_cohort([record.to_dict() for record in stage_records], cards)
    progress(0.95, "正在写穿越纪实…")

    run: dict[str, Any] = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "dynasty": dynasty,
        "agent_ids": [int(i) for i in agent_ids],
        "cards": [
            {"agent_id": int(card["agent_id"]), "name": card["name"], "job": card["job"]}
            for card in cards
        ],
        "stages": [record.to_dict() for record in stage_records],
        "stats": {
            "agents": aggregate["agents"],
            "stages": aggregate["stages"],
            "moods": aggregate["moods"],
            "most_in_period": aggregate["most_in_period"],
            "least_in_period": aggregate["least_in_period"],
            "most_torn": aggregate["most_torn"],
            "residents": aggregate["residents"],
        },
        "essay": "",
        "created_at": time.time(),
        "scoring_note": (
            "era_fit / stability / inner_conflict 是从台词文本里推导的启发式评分"
            "(朝代关键词命中 + 现代字眼扣分 + 古体退让 vs 现代反驳):不是裁判模型的判断。"
        ),
    }
    try:
        run["essay"] = str(essay(_essay_prompt(dynasty, run))).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("timeslip essay failed: %s", exc)
        run["essay"] = ""

    progress(0.99, "收尾…")
    _ = picked_set  # silence unused-warning; the set was for future use
    return run


# ---------------------------------------------------------------------------
# Background job
# ---------------------------------------------------------------------------


_JOBS = JobStore("timeslip", archive=True)


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def list_runs() -> list[dict[str, Any]]:
    rows = []
    for row in _JOBS.results():
        result = row["result"] or {}
        dynasty = result.get("dynasty") or {}
        stats = result.get("stats") or {}
        rows.append(
            {
                "job_id": row["job_id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "dynasty": dynasty.get("dynasty") or dynasty.get("id"),
                "emoji": dynasty.get("emoji"),
                "agents": stats.get("agents"),
                "stages": stats.get("stages"),
                "created_at": result.get("created_at"),
            }
        )
    return rows


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    _JOBS.reset()


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then start the timeslip job in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if len(agent_ids) < MIN_AGENTS:
        raise ValueError(f"至少选 {MIN_AGENTS} 位居民一起穿越")
    if len(agent_ids) > MAX_AGENTS:
        raise ValueError(f"一次穿越最多 {MAX_AGENTS} 位")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    resolve_dynasty(str(payload.get("dynasty_id") or ""), custom)
    stages = int(payload.get("stages") or DEFAULT_STAGES)

    return _JOBS.run(
        lambda progress: run_timeslip(
            city=city,
            agent_ids=agent_ids,
            dynasty_id=str(payload.get("dynasty_id") or ""),
            custom=custom,
            stages=stages,
            progress=progress,
        )
    )


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/timeslip/ branch.
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
        if path == "/api/games/timeslip/catalogue":
            return {
                "dynasties": list_dynasties(),
                "min_agents": MIN_AGENTS,
                "max_agents": MAX_AGENTS,
                "min_stages": MIN_STAGES,
                "max_stages": MAX_STAGES,
                "default_stages": DEFAULT_STAGES,
            }, 200
        if path == "/api/games/timeslip/agents":
            city = _one(query, "city")
            from gaworld.apps.games_api import list_agents

            return {"agents": list_agents(city)}, 200
        if path == "/api/games/timeslip/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/timeslip/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("timeslip GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/timeslip/run":
            return {"job_id": start_run(payload)}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("timeslip POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "DEFAULT_STAGES",
    "DYNASTY_BANK",
    "MAX_AGENTS",
    "MAX_STAGES",
    "MIN_AGENTS",
    "MIN_STAGES",
    "RESIDENT_PERSONA_CHARS",
    "dynasty_by_id",
    "handle_get",
    "handle_post",
    "job_status",
    "list_dynasties",
    "list_runs",
    "reset_jobs",
    "resolve_dynasty",
    "run_timeslip",
    "start_run",
]
