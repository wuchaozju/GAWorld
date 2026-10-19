"""Dashboard backend for 《这是我的战争》 (Warzone), the playground's sixth game.

The warzone sandbox tests what people do when a group is trapped together
and a shared stockpile is shrinking faster than anyone would like. Every
in-game day has the same loop:

* **propose** — each resident names who gets how much of every resource,
  given the day's text and what has already gone wrong;
* **vote** — the same residents vote yes / no / abstain on each proposal
  (others' proposals are summarised in the prompt, so consensus costs no
  extra LLM call);
* **settle** — the highest-voted proposal is applied, the inventory and the
  residents' statuses update, and the day text is logged.

The point of the game is not "who wins" — it is the curve of *moral
pressure*: how the proposals drift, who is sacrificed, when the group
breaks. The aggregate is computed deterministically from the proposals and
the votes: Gini over per-resident food rations, mortality, dissent rate,
average moral distress, plus a closing essay from one model call.

Conventions follow :mod:`gaworld.apps.disaster_api`: a background job with
progress, an in-memory store, every LLM entry point injectable
(``proposal_fn`` / ``vote_fn`` / ``essay_fn``) so tests never touch a
provider, and never a write to a city bundle.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gaworld.apps.game_jobs import JobStore
from gaworld.apps.games_api import first_json_object, load_persona, persona_block
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.warzone_api")

# ---------------------------------------------------------------------------
# Limits (cost-shaped; one round is agents × days × 2 + 1 LLM calls).
# ---------------------------------------------------------------------------

#: 居民上限,同灾害模式。一个 7 天围困跑到一半就够用户喝杯咖啡了。
MAX_AGENTS = 8
#: 一局多少天。7 是默认起步,够看见完整的道德崩盘曲线。
DEFAULT_DAYS = 7
#: 资源种类。每个局共享一个真实仓库,逐日结余。
RESOURCES: tuple[str, ...] = ("食物", "药品", "燃料", "守卫时间")
#: 居民健康度的最大生命值。归零即死亡,对该居民之后几天不再提议/投票。
MAX_HEALTH = 5
#: 一个居民在没有专属物资情况下每天衰减的健康点。基线是 1。
DAILY_HUNGER = 1
#: 每个提案的规模上限 —— 防止模型在一次 LLM 调用里塞进整本战争史。条目多说明资源分配数量。
MAX_PLAN_ROWS = 12

OTHER_PLAN = "其他方案"

# ---------------------------------------------------------------------------
# Built-in scenarios (类似灾害模式的 DISASTER_BANK)。
# ---------------------------------------------------------------------------

#: 4 个内置剧本 + 用户的自定义。每天是一段情境文字(日期已写明),剧本自带
#: 仓库初始清单(随天数下降的基础物资)。这样同一段文字能在任何城市开打。
WARZONE_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "siege",
        "name": "围城战",
        "emoji": "🏰",
        "summary": "一座小城被围得水泄不通,仓库一天天见底",
        "days": [
            "第 1 天: 围城第三周。电没了,水是井里一桶一桶摇上来的。仓库还有些米、面、几盒抗生素、"
            "过冬的煤,外加一把老猎枪和两个愿意守夜的人。最紧要的问题是:今天怎么分。",
            "第 2 天: 一发流弹把顶楼的窗户震碎了。一个孩子开始发烧,大夫说再没有青霉素会转肺炎。"
            "井水也变少了,有传言城外的部队想劝降。",
            "第 3 天: 一队人从前一道城门缝里钻进来,带着哭声。仓库还能撑,但谁都知道这不是真的。"
            "今天开始,有居民提出来:要不要赶走不能劳动的人,把东西留给能打仗的。",
            "第 4 天: 昨夜的会议散得很晚。今早菜窖里发现被人搬空了一角,大家脸色都不太对。"
            "有家人在问:把老人留在城里,带不带孩子跑?还有人在讨论能不能用东街的医生换两袋米。",
            "第 5 天: 围城的军队在城墙上贴了劝降书,有的家里开始悄悄收拾东西。粮仓还剩四分之一。"
            "仓库门今晚起由值守的人轮班锁,这事成了一项新决定。",
            "第 6 天: 一发炮弹落在供销社门口,三个人没了。仓库里有人提:把剩下的煤全烧了,夜里给伤员熬药,"
            "其余的家庭挨到天亮再说。",
            "第 7 天: 清晨有人看见城外起了烟,是邻村的火,也可能是远处的村子着了。围城还没有解。"
            "仓库里还剩一点点。大家决定再坚持一天,这一天怎么过?",
        ],
        "stock": {"食物": 120, "药品": 18, "燃料": 50, "守卫时间": 30},
    },
    {
        "id": "urban",
        "name": "现代都市围困",
        "emoji": "🏙️",
        "summary": "一栋 30 层公寓楼被切断了电力与物资,12 户共享楼道仓库",
        "days": [
            "第 1 天: 凌晨电力公司发了系统公告后,整个街道的灯全灭了。电梯停了,门禁失灵。"
            "物业群里开始汇总楼下的超市还能买什么。仓库里有方便面、饮用水、几罐煤气、一盒退烧药。",
            "第 2 天: 水也停了,楼道里有人拎着桶排队接消防水。15 楼的老伯说他心脏的药吃完了。"
            "楼下的超市被抢空了。群里的提议正在分两派:集中放在一楼由志愿者管,还是各家按需自己拿。",
            "第 3 天: 楼上开始有孩子发烧。一家外卖员的妻子带着孩子走进了物业大厅,她家住在附近,"
            "已经没有吃的了。仓库要分给她吗?",
            "第 4 天: 一些住户开始往外跑,地下车库的出口塌了一半,有车也出不去。"
            "留下的家庭中,有几家开始把共享仓库的门锁换成了自家的锁。",
            "第 5 天: 物业群里传出有人私藏了两箱方便面。仓库委员会正在讨论要不要挨家挨户登记。"
            "楼顶有住户偷偷往下扔垃圾袋,差点砸到人。",
            "第 6 天: 一台应急广播从对讲机里漏出来,说三天后水电会再来。仓库里的水只剩三桶。"
            "有人提议把水全锁起来,发热的孩子先喝,有人反对。",
            "第 7 天: 最后一次楼道会议。仓库里还剩一些方便面和半盒退烧药,屋外的一切还没恢复。"
            "今天的安排将决定下一个 24 小时会不会有人上不了楼。",
        ],
        "stock": {"食物": 80, "药品": 12, "燃料": 24, "守卫时间": 24},
    },
    {
        "id": "village",
        "name": "外族入侵下的小镇",
        "emoji": "🌾",
        "summary": "小镇被扫荡过一遍,剩下的人挤在祠堂里",
        "days": [
            "第 1 天: 进村的车队两天前走了。祠堂里挤着二十来个没来得及跑的人,几袋米,一缸水,"
            "半箱从药房抢救出来的药。祠堂外是烧了一半的屋顶。",
            "第 2 天: 有人从烧毁的供销社里抬出了几桶柴油,也不知道派什么用场。"
            "老村长的儿子在废墟里翻到了半袋糖果,引发了第一次争执。",
            "第 3 天: 山上远远传来几声枪响。祠堂里的人开始愿意让放哨的人先吃饭。"
            "几个孩子哭了一夜,要登记谁家还有多少口粮还是不管?",
            "第 4 天: 一位没有跟着跑的孕妇临产。村里唯一学过接生的阿婆说她已经累得快站不住了。"
            "药只剩半盒。祠堂的妇女们把她围了起来,男人们在商量是接生还是赶路。",
            "第 5 天: 一个走失的小孩被搜救队送了回来,人不是本村的。"
            "祠堂里的米缸已经见底了。收还是不收?粮食还能不能往外分?",
            "第 6 天: 一场冷雨漏进了祠堂。有两家的家长开始悄悄教自己的孩子,大人不在了怎么办。"
            "药品要锁起来,有一半家长反对,说是应该有病就吃。",
            "第 7 天: 外面的车队没了消息,有人打听到附近的山坳里还有一户没有走的远亲。"
            "今天的决定是留下还是上路,留下的日子怎么过。",
        ],
        "stock": {"食物": 70, "药品": 10, "燃料": 20, "守卫时间": 25},
    },
    {
        "id": "exodus",
        "name": "流亡途中",
        "emoji": "🛶",
        "summary": "一船人顺流而下,厨房就是这艘船最后一点家当",
        "days": [
            "第 1 天: 渡船离港第三天。船舱底堆着大家合伙凑起来的米、腌菜、半桶柴油和几卷绷带。"
            "船老大宣布开伙前必须先把规矩定下来。",
            "第 2 天: 引擎缺油,船长决定把柴油分成三份:航行、抽水、取暖。"
            "一个老太太晕船,船上有人开始担心她的咳嗽会拖到全船。",
            "第 3 天: 一个带着两个孩子的家庭被另一条船的人追上来了,求搭个位子。"
            "船老大点了头,但船上其他人并不全同意。",
            "第 4 天: 水面出现了一段浮木,船长决定沿木改变航线,会多走一天。"
            "船上几个家长开始悄悄讲:要不要把腌菜私藏点,路上可能还有小孩饿死。",
            "第 5 天: 一个孩子得了痢疾,船员越来越害怕。船长的亲生孙女也病了。"
            "绑带不到 5 米,够谁先用?",
            "第 6 天: 夜里有人落水,救上来时膝盖磕穿了。剩下的柴油勉强够再撑一天。"
            "舱底有人在讨论:明天还有没有理由继续走下去。",
            "第 7 天: 远处已经能看见远处的河岸。船上有人提议把最后这点柴油留给返航的船夫,"
            "也有人说到了岸才要紧。今天的开支,就是这段时间的预算。",
        ],
        "stock": {"食物": 60, "药品": 8, "燃料": 16, "守卫时间": 20},
    },
)


def list_scenarios() -> list[dict[str, Any]]:
    """The catalogue shown in the picker."""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "emoji": s["emoji"],
            "summary": s["summary"],
            "days": list(s["days"]),
            "stock": dict(s["stock"]),
        }
        for s in WARZONE_BANK
    ]


def scenario_by_id(scenario_id: str) -> dict[str, Any] | None:
    for item in WARZONE_BANK:
        if item["id"] == scenario_id:
            return item
    return None


def _custom_scenario(custom: dict[str, Any]) -> dict[str, Any]:
    """``custom`` payload → bank-shaped scenario. One paragraph = one day."""
    raw_days = custom.get("days")
    if isinstance(raw_days, str):
        parts = [line.strip() for line in raw_days.splitlines()]
    elif isinstance(raw_days, (list, tuple)):
        parts = [str(line).strip() for line in raw_days]
    else:
        parts = []
    days = [p for p in parts if p]
    if not days:
        raise ValueError("自定义剧本至少要写一段情境(每行一天)")
    stock_input = custom.get("stock") if isinstance(custom.get("stock"), dict) else {}
    stock: dict[str, int] = {}
    for resource in RESOURCES:
        try:
            stock[resource] = max(0, int(stock_input.get(resource, 0)))
        except (TypeError, ValueError):
            stock[resource] = 0
    if not any(stock.values()):
        # Provide a small default so the round has *something* to argue over.
        stock = {"食物": 60, "药品": 8, "燃料": 20, "守卫时间": 20}
    return {
        "id": "custom",
        "name": str(custom.get("name") or "自定义剧本").strip() or "自定义剧本",
        "emoji": str(custom.get("emoji") or "⚔️"),
        "summary": days[0][:40],
        "days": days[:DEFAULT_DAYS],
        "stock": stock,
    }


def resolve_scenario(scenario_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    if custom:
        return _custom_scenario(custom)
    found = scenario_by_id(str(scenario_id or ""))
    if found is None:
        raise ValueError(f"没有这种剧本：{scenario_id or '（未选）'}")
    return found


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_proposal_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.warzone.proposal", temperature=0.7)


def _default_vote_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.warzone.vote", temperature=0.5)


def _default_essay_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.warzone.essay", temperature=0.4)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _roster_line(people: list[Resident] | list[dict[str, Any]], alive_only: bool = True) -> str:
    """Compact one-line-per-resident status. Accepts dataclass or dict form."""
    parts: list[str] = []
    for entry in people:
        if isinstance(entry, Resident):
            agent_id = entry.agent_id
            name = entry.name
            health = entry.health
            hunger = entry.hunger
            morale = entry.morale
            alive = entry.alive
        else:
            agent_id = entry.get("agent_id")
            name = entry.get("name", "")
            health = entry.get("health", 0)
            hunger = entry.get("hunger", 0)
            morale = entry.get("morale", 0)
            alive = entry.get("alive", True)
        if alive_only and (not alive or health <= 0):
            parts.append(f"- #{agent_id} {name}(已故)")
            continue
        parts.append(
            f"- #{agent_id} {name}(健康{health}/{MAX_HEALTH}, "
            f"饱腹{hunger}, 士气{'▮' * morale}{'▯' * (5 - morale)})"
        )
    return "\n".join(parts) or "(无)"


def _stock_line(stock: dict[str, int]) -> str:
    parts = [f"{name} {stock.get(name, 0)}" for name in RESOURCES]
    return "、".join(parts)


def _daily_cap_line(stock: dict[str, int], days_left: int) -> str:
    """Per-day ceiling in human-readable form: ``食物 ≤20, 药品 ≤3, ...``.

    The ceiling matches the ``run_warzone`` formula — ``stock //
    (days_left - 1)`` if more than one day remains, else ``stock``.
    Generous enough that a front-loaded plan on Day 1 is allowed; tight
    enough that one proposal cannot drain the stockpile.
    """
    denom = max(1, days_left - 1) if days_left > 1 else 1
    caps = {r: max(1, stock.get(r, 0) // denom) for r in RESOURCES}
    parts = [f"{name}≤{caps[name]}" for name in RESOURCES]
    return "、".join(parts)


def _proposal_prompt(
    person: Resident,
    scenario: dict[str, Any],
    day_index: int,
    day_text: str,
    stock: dict[str, int],
    alive_others: list[Resident],
    yesterday_winner: dict[str, Any] | None,
    days_left: int = 1,
) -> str:
    history = ""
    if yesterday_winner:
        rows = _format_plan_rows(yesterday_winner.get("plan") or [])
        history = (
            "\n昨天的方案(已被采用):\n"
            f"提案人:#{yesterday_winner.get('author_id')} {yesterday_winner.get('author_name', '')}\n"
            f"理由:{yesterday_winner.get('rationale', '')}\n"
            f"方案条目:\n{rows}\n"
        )
    resources = "、".join(RESOURCES)
    return (
        f"{person.persona_text}\n\n"
        f"你所在的城市陷入{scenario['name']}。今天是第 {day_index + 1} 天。\n"
        f"【今天的情况】{day_text}\n"
        f"\n公共仓库剩:{_stock_line(stock)}。\n"
        f"今天各种资源的支出上限(防止一天把仓库抽空):{_daily_cap_line(stock, days_left)}。\n"
        f"今天仓库会按你的提议分配:{resources}。\n"
        f"{history}\n"
        f"现在的居民:\n{_roster_line(alive_others)}\n\n"
        "请以你自己的处境、性格、家庭和能力,提出**一份今天怎么分**的方案。"
        "你要回答的不是'正确的方案',而是你这个人**真的**会怎么分。"
        "可以优先家人、可以给生病的孩子优先、也可以分得很平均——说出你的理由。\n\n"
        "只输出一个 JSON 对象,不要任何解释。条目最多 "
        f"{MAX_PLAN_ROWS} 个,recipient_id 用 #1 形式的居民编号或 'household'(整个家庭)或 'shared'(放入公共)。"
        "amount 是正整数,代表分配多少单位。\n"
        '格式:{"rationale": "一句话说明你的动机", '
        '"plan": [{"resource": "食物", "recipient_id": "#3", "amount": 2}, ...]}'
    )


def _format_plan_rows(plan: list[dict[str, Any]]) -> str:
    if not plan:
        return "(无条目)"
    lines = []
    for row in plan[:MAX_PLAN_ROWS]:
        resource = row.get("resource", "?")
        rid = row.get("recipient_id", "?")
        amount = row.get("amount", 0)
        lines.append(f"- {resource} → {rid}:{amount}")
    return "\n".join(lines)


def _vote_prompt(
    person: Resident,
    scenario: dict[str, Any],
    day_index: int,
    day_text: str,
    stock: dict[str, int],
    proposals: list[dict[str, Any]],
) -> str:
    """Each voter sees every proposal in compact form and backs one (or none).

    ``for`` is the 1-based proposal index the voter backs. ``choice=yes`` only
    counts when ``for`` points at a real proposal — a bare yes is treated as
    approval of the caller's own proposal.
    """
    proposal_lines = []
    for index, prop in enumerate(proposals, start=1):
        rows = _format_plan_rows(prop.get("plan") or [])
        proposal_lines.append(
            f"方案{index} —— #{prop['author_id']} {prop.get('author_name', '')}:"
            f"{prop.get('rationale', '')}\n{rows}"
        )
    proposals_block = "\n\n".join(proposal_lines) or "(无其他方案)"
    return (
        f"{person.persona_text}\n\n"
        f"第 {day_index + 1} 天的 {scenario['name']}。\n"
        f"【今天的情况】{day_text}\n"
        f"公共仓库剩:{_stock_line(stock)}。\n"
        f"今天的提案:\n{proposals_block}\n\n"
        "请以你自己真的判断,给出一个决定:**yes** 赞成其中某一份 / **no** 反对全部 / **abstain** 弃权。"
        "赞成意味着:我愿意今天按这份方案执行。反对意味着:今天都别动。弃权意味着:随大家。"
        "可以赞成他人提案、也可以赞成自己的。\n"
        "只输出一个 JSON 对象,不要解释:\n"
        '{"choice": "yes | no | abstain", "for": 1-based 提案编号(整数),仅在 choice=yes 时填,'
        '"reason": "一句话理由"}'
    )


def _essay_prompt(scenario: dict[str, Any], run: dict[str, Any]) -> str:
    stats = run["stats"]
    return (
        "你是一名社会学者。下面是一场持续 7 天的围困推演,"
        "居民们每天投票决定怎么分配共享物资。下面是他们真实的提案、投票和结局。"
        "请写一段 250 字以内的总结:谁最先让步,谁被先牺牲,哪一项资源最先耗尽,"
        "道德焦虑在第几天越过拐点,并指出谁或者哪件事让整个群体的态度反转过来。"
        "要具体,不要空话;不评价对错,只描述曲线。\n\n"
        f"剧本:{scenario['name']}\n"
        f"人数:{len(run['residents'])}\n"
        f"最终健康/饱腹/士气:\n{_roster_line(run['residents'])}\n"
        f"总死亡率:{stats['mortality'] * 100:.0f}%\n"
        f"平均道德焦虑:{stats['avg_moral_distress']:.1f}/5\n"
        f"投票分歧率(不一票):{stats['dissent_rate']:.0%}\n"
        f"基尼系数(食物分配):{stats['food_gini']:.2f}\n"
        f"最先耗尽:{stats['depleted_first'] or '（未耗尽）'}\n"
        f"最坚定建议者:#{stats['strongest_id']}\n"
        f"最被排斥居民:#{stats['most_excluded_id']}\n"
    )


# ---------------------------------------------------------------------------
# State & parsing
# ---------------------------------------------------------------------------


def _normalise_plan(raw: Any) -> list[dict[str, Any]]:
    """Drop garbage rows; keep resource + recipient + amount triples."""
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw[:MAX_PLAN_ROWS]:
        if not isinstance(item, dict):
            continue
        resource = str(item.get("resource", "")).strip()
        if resource not in RESOURCES:
            continue
        rid = str(item.get("recipient_id", "")).strip() or "shared"
        try:
            amount = int(item.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            continue
        rows.append({"resource": resource, "recipient_id": rid, "amount": amount})
    return rows


def _coerce_choice(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("yes", "y", "true", "同意", "赞成", "支持", "接受"):
        return "yes"
    if text in ("no", "n", "false", "不同意", "反对", "否决"):
        return "no"
    return "abstain"


def parse_proposal(raw: str) -> dict[str, Any]:
    """One resident's proposal. Off-shape → empty plan + fallback rationale."""
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {
            "rationale": text[:120] or "（没有返回有效内容）",
            "plan": [],
        }
    rationale = str(payload.get("rationale", "")).strip()[:200]
    return {"rationale": rationale, "plan": _normalise_plan(payload.get("plan"))}


def parse_vote(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {"choice": "abstain", "for": None, "reason": text[:120] or "（弃权）"}
    try:
        target = int(payload.get("for"))
    except (TypeError, ValueError):
        target = None
    if target is not None and target < 1:
        target = None
    return {
        "choice": _coerce_choice(payload.get("choice")),
        "for": target,
        "reason": str(payload.get("reason", "")).strip()[:200],
    }


# ---------------------------------------------------------------------------
# Citizens
# ---------------------------------------------------------------------------


@dataclass
class Resident:
    agent_id: int
    name: str
    job: str = ""
    persona_text: str = ""
    health: int = MAX_HEALTH
    hunger: int = MAX_HEALTH
    morale: int = 3
    alive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "job": self.job,
            "health": self.health,
            "hunger": self.hunger,
            "morale": self.morale,
            "alive": self.alive,
        }


def _load_residents(city: str, agent_ids: list[int]) -> list[Resident]:
    people: list[Resident] = []
    for agent_id in agent_ids:
        persona = load_persona(city, agent_id)
        people.append(
            Resident(
                agent_id=int(persona["agent_id"]),
                name=str(persona.get("name") or f"#{agent_id}"),
                job=str(persona.get("job") or ""),
                persona_text=persona_block(persona),
            )
        )
    return people


# ---------------------------------------------------------------------------
# Settlement & aggregation
# ---------------------------------------------------------------------------


def _apply_plan(
    plan: list[dict[str, Any]],
    residents_by_id: dict[int, Resident],
    stock: dict[str, int],
    *,
    daily_cap: dict[str, int] | None = None,
) -> tuple[dict[str, int], list[str]]:
    """Apply a chosen plan to the stock. Clamps each row to:

    * ``min(asked, remaining)`` — never draw more than the stock holds;
    * ``min(..., daily_cap[resource])`` — never let one day's total
      exceed the day's quota, computed from the initial stockpile and the
      days remaining. The cap protects against one generous proposal
      draining everything in a single day, which would leave Day 2+ with
      nothing to argue over.

    The reason both clamps matter: ``remaining`` prevents going negative,
    but the model is allowed to allocate huge sums to a recipient whose
    hunger/hunger_max can't absorb them — that's a no-op silently. The
    cap surfaces the model that there is a daily ceiling, both in the
    log and in the residents' actual status updates.
    """
    new_stock = dict(stock)
    distributed: list[str] = []
    for row in plan:
        resource = row["resource"]
        asked = int(row["amount"])
        rid = str(row["recipient_id"])
        remaining = new_stock.get(resource, 0)
        cap = daily_cap.get(resource) if daily_cap else None
        if remaining <= 0 or asked <= 0:
            distributed.append(f"{resource}→{rid}(仓库空了)")
            continue
        # Apply daily ceiling first so a generous row can't drain the rest
        # of the day; then clamp to what is actually left.
        if cap is not None:
            asked = min(asked, cap)
            if asked <= 0:
                distributed.append(f"{resource}→{rid}(今日已用完)")
                continue
        amount = min(asked, remaining)
        new_stock[resource] = remaining - amount
        if daily_cap is not None:
            daily_cap[resource] = max(0, daily_cap[resource] - amount)
        suffix = "" if amount == asked else f"（要{row['amount']},只给{amount}）"
        if rid == "shared" or rid == "household":
            distributed.append(f"{resource}→公共×{amount}{suffix}")
            continue
        target_id = _parse_resident_id(rid, residents_by_id)
        if target_id is None:
            distributed.append(f"{resource}→{rid}(未知居民)×{amount}{suffix}")
            continue
        person = residents_by_id[target_id]
        if not person.alive:
            distributed.append(f"{resource}→#{target_id}(已故)×{amount}{suffix}")
            continue
        if resource == "食物":
            person.hunger = min(MAX_HEALTH, person.hunger + amount)
        elif resource == "药品":
            person.health = min(MAX_HEALTH, person.health + amount // 2)
        elif resource == "燃料":
            person.morale = min(5, person.morale + (1 if amount >= 1 else 0))
        # 守卫时间:不改变任何数值,只算到日志(下一步会衰减外部威胁)
        distributed.append(f"{resource}→#{target_id}×{amount}{suffix}")
    return new_stock, distributed


def _parse_resident_id(token: str, residents_by_id: dict[int, Resident]) -> int | None:
    text = str(token or "").strip().lstrip("#")
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value in residents_by_id else None


def _tick_end_of_day(
    residents: list[Resident], stock: dict[str, int],
) -> dict[str, Any]:
    """Hunger burns health when no food lands; morale decays if no fuel."""
    deaths: list[str] = []
    total_fuel = stock.get("燃料", 0)
    for person in residents:
        if not person.alive:
            continue
        if person.hunger <= 0:
            person.health -= 1
        else:
            person.hunger = max(0, person.hunger - DAILY_HUNGER)
        if total_fuel <= 0 and person.morale > 1:
            person.morale -= 1
        if person.health <= 0:
            person.alive = False
            deaths.append(f"#{person.agent_id} {person.name}")
    return {"deaths": deaths}


def _gini(values: list[int]) -> float:
    """Standard Gini. 0 = everyone got the same, 1 = one person got everything."""
    if not values:
        return 0.0
    n = len(values)
    total = sum(values)
    if total <= 0:
        return 0.0
    sorted_values = sorted(values)
    cumulative = 0.0
    for index, value in enumerate(sorted_values, start=1):
        cumulative += index * value
    return (2 * cumulative) / (n * total) - (n + 1) / n


def _aggregate(
    proposals: list[dict[str, Any]],
    votes: list[dict[str, Any]],
    residents: list[Resident],
) -> dict[str, Any]:
    """Histogram + essay fodder for one day, or for the whole run."""
    empty_choice = sum(1 for v in votes if v["choice"] == "abstain")
    no_choice = sum(1 for v in votes if v["choice"] == "no")
    yes_choice = sum(1 for v in votes if v["choice"] == "yes")
    n = len(votes) or 1
    food_totals: dict[int, int] = {}
    for prop in proposals:
        for row in prop.get("plan", []):
            if row["resource"] != "食物":
                continue
            target_id = _parse_resident_id(row["recipient_id"], {p.agent_id: p for p in residents})
            if target_id is None:
                continue
            food_totals[target_id] = food_totals.get(target_id, 0) + int(row["amount"])
    food_values = [food_totals.get(p.agent_id, 0) for p in residents]
    return {
        "yes": yes_choice,
        "no": no_choice,
        "abstain": empty_choice,
        "dissent_rate": round((no_choice + empty_choice) / n, 2),
        "food_gini": round(_gini(food_values), 2),
        "food_values": food_totals,
        "victor_idx": _pick_victor(proposals, votes),
    }


def _pick_victor(proposals: list[dict[str, Any]], votes: list[dict[str, Any]]) -> int | None:
    """Tally per author; ties broken by author order."""
    tallies: dict[int, int] = {}
    for vote in votes:
        if vote["choice"] != "yes":
            continue
        try:
            target = int(vote.get("for"))
        except (TypeError, ValueError):
            continue
        tallies[target] = tallies.get(target, 0) + 1
    if not tallies:
        return None
    best_score = max(tallies.values())
    winners = sorted(author for author, n in tallies.items() if n == best_score)
    return winners[0]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

#: One JobStore per game.
_JOBS = JobStore("warzone", archive=True)


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def reset_jobs() -> None:
    _JOBS.reset()


def list_runs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _JOBS.results():
        result = row["result"] or {}
        stats = result.get("stats") or {}
        rows.append(
            {
                "job_id": row["job_id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "scenario": (result.get("scenario") or {}).get("name"),
                "emoji": (result.get("scenario") or {}).get("emoji"),
                "agents": len(result.get("residents") or []),
                "days": len(result.get("days") or []),
                "mortality": stats.get("mortality"),
                "created_at": result.get("created_at"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


def run_warzone(
    *,
    city: str,
    agent_ids: list[int],
    scenario_id: str = "",
    custom: dict[str, Any] | None = None,
    days: int = DEFAULT_DAYS,
    residents: list[Resident] | None = None,
    proposal_fn: Callable[[str], str] | None = None,
    vote_fn: Callable[[str], str] | None = None,
    essay_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Play one warzone round: every resident proposes & votes every day."""
    progress = progress or (lambda p, m: None)
    ids = [int(i) for i in (agent_ids or [])][:MAX_AGENTS]
    if not ids and residents is None:
        raise ValueError("先选几个居民")

    scenario = resolve_scenario(scenario_id, custom)
    day_count = max(1, min(int(days or DEFAULT_DAYS), DEFAULT_DAYS, len(scenario["days"])))
    day_texts = list(scenario["days"])[:day_count]

    people = residents if residents is not None else _load_residents(city, ids)
    if not people:
        raise ValueError("先选几个居民")
    residents_by_id = {p.agent_id: p for p in people}

    proposal = proposal_fn or _default_proposal_llm
    vote = vote_fn or _default_vote_llm

    stock: dict[str, int] = dict(scenario["stock"])
    day_records: list[dict[str, Any]] = []
    winner_history: list[dict[str, Any]] = []
    total_calls = max(1, len(people) * day_count * 2 + 1)
    step = 0

    for day_index, day_text in enumerate(day_texts):
        progress(step / total_calls * 0.92, f"第 {day_index + 1} 天 · 收集中")
        # Per-day ceiling: keep at least one day's worth of each resource
        # in reserve. One over-generous proposal cannot drain everything
        # in a single day — it would leave nothing for Day 2+ to argue
        # over. ``stock // max(1, days_left - 1)`` is generous enough that
        # a slightly front-loaded plan is allowed (e.g. feeding the sick
        # children on Day 1), but not so generous that one proposal can
        # take the whole stockpile.
        days_left = max(1, len(day_texts) - day_index)
        ceiling_denom = max(1, days_left - 1) if days_left > 1 else 1
        daily_cap = {
            resource: max(1, stock.get(resource, 0) // ceiling_denom)
            for resource in RESOURCES
        }
        day_proposals: list[dict[str, Any]] = []
        for person in people:
            if not person.alive:
                continue
            step += 1
            alive_others = [
                Resident(
                    agent_id=p.agent_id,
                    name=p.name,
                    job=p.job,
                    persona_text="",
                    health=p.health,
                    hunger=p.hunger,
                    morale=p.morale,
                    alive=p.alive,
                )
                for p in people
            ]
            prompt = _proposal_prompt(
                person, scenario, day_index, day_text, stock, alive_others,
                winner_history[-1] if winner_history else None,
                days_left=days_left,
            )
            try:
                raw = proposal(prompt)
            except Exception as exc:  # pragma: no cover - provider failure
                _LOG.warning("warzone proposal failed for #%s: %s", person.agent_id, exc)
                raw = ""
            parsed = parse_proposal(raw)
            day_proposals.append(
                {
                    "author_id": person.agent_id,
                    "author_name": person.name,
                    "rationale": parsed["rationale"],
                    "plan": parsed["plan"],
                }
            )

        progress(step / total_calls * 0.92, f"第 {day_index + 1} 天 · 表决中")
        day_votes: list[dict[str, Any]] = []
        for person in people:
            if not person.alive:
                continue
            step += 1
            prompt = _vote_prompt(
                person, scenario, day_index, day_text, stock, day_proposals
            )
            try:
                raw = vote(prompt)
            except Exception as exc:  # pragma: no cover - provider failure
                _LOG.warning("warzone vote failed for #%s: %s", person.agent_id, exc)
                raw = ""
            parsed = parse_vote(raw)
            voter_record = {"voter_id": person.agent_id, **parsed}
            # Anchor: which proposal did this voter write? Used when the
            # model returns a bare yes ("I want my plan to run today").
            for prop_idx, prop in enumerate(day_proposals):
                if prop["author_id"] == person.agent_id:
                    voter_record["voter_proposal_idx"] = prop_idx
                    break
            day_votes.append(voter_record)

        tally, best_idx, _empty = _tally_votes(day_votes, len(day_proposals))
        stock_before = dict(stock)
        if day_proposals and best_idx is not None:
            winning_proposal = day_proposals[best_idx]
            new_stock, distributed = _apply_plan(
                winning_proposal["plan"], residents_by_id, stock,
                daily_cap=daily_cap,
            )
        else:
            winning_proposal = {
                "author_id": None,
                "author_name": "（无人提议）",
                "rationale": "",
                "plan": [],
            }
            new_stock = stock
            distributed = []
        stock = new_stock
        settlement = _tick_end_of_day(people, stock)
        aggregate = _aggregate(day_proposals, day_votes, people)
        day_records.append(
            {
                "day": day_index,
                "text": day_text,
                "stock_before": stock_before,
                "proposals": day_proposals,
                "votes": day_votes,
                "winning_proposal": winning_proposal,
                "tally": tally,
                "distributed": distributed,
                "stock_after": dict(stock),
                "aggregate": {k: v for k, v in aggregate.items() if k != "victor_idx"},
                "deaths": settlement["deaths"],
            }
        )
        winner_history.append(
            {
                "author_id": winning_proposal["author_id"],
                "author_name": winning_proposal.get("author_name", ""),
                "rationale": winning_proposal.get("rationale", ""),
                "plan": winning_proposal.get("plan", []),
            }
        )

    flat = day_records

    # Aggregate over the whole run.
    alive_count = sum(1 for p in people if p.alive)
    mortality = 1 - (alive_count / max(1, len(people)))
    all_votes = [v for day in flat for v in day["votes"]]
    dissent_rate = (
        sum(1 for v in all_votes if v["choice"] != "yes") / max(1, len(all_votes))
    )
    all_food_values: dict[int, int] = {}
    for day in flat:
        for person_id, amount in (day["aggregate"].get("food_values") or {}).items():
            all_food_values[person_id] = all_food_values.get(person_id, 0) + amount
    food_gini = _gini([all_food_values.get(p.agent_id, 0) for p in people])
    # Average moral distress: 0 0-代理数字越高 = 越被排斥者(食物/药品都到不了的人)
    distress_values = [5 - min(5, all_food_values.get(p.agent_id, 0)) for p in people]
    avg_moral_distress = round(sum(distress_values) / max(1, len(distress_values)), 2)
    # Depleted first: 第一个变 0 的资源。
    depleted_first: str | None = None
    for day in flat:
        for resource in RESOURCES:
            if (day["stock_after"].get(resource, 0)) == 0 and (day["stock_before"].get(resource, 0)) > 0:
                depleted_first = resource
                break
        if depleted_first:
            break
    # Strongest: who most often proposed the winning plan.
    win_count: dict[int, int] = {}
    for day in flat:
        author_id = (day["winning_proposal"] or {}).get("author_id")
        if author_id is not None:
            win_count[author_id] = win_count.get(author_id, 0) + 1
    strongest_id = max(win_count, default=0) or 0
    most_excluded_id = (
        min(all_food_values, key=lambda k: all_food_values[k], default=0) or 0
    )

    overall = {
        "mortality": round(mortality, 2),
        "dissent_rate": round(dissent_rate, 2),
        "food_gini": round(food_gini, 2),
        "avg_moral_distress": avg_moral_distress,
        "depleted_first": depleted_first,
        "strongest_id": strongest_id,
        "most_excluded_id": most_excluded_id,
    }

    run = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "scenario": {
            "id": scenario["id"],
            "name": scenario["name"],
            "emoji": scenario["emoji"],
            "stock_initial": dict(scenario["stock"]),
        },
        "days": day_texts,
        "residents": [p.to_dict() for p in people],
        "log": flat,
        "stats": overall,
        "essay": "",
        "created_at": time.time(),
    }

    progress(0.95, "正在写战后总结…")
    try:
        essay = (essay_fn or _default_essay_llm)(_essay_prompt(scenario, run))
        run["essay"] = str(essay).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("warzone essay failed: %s", exc)
        run["essay"] = ""
    return run


def _tally_votes(
    votes: list[dict[str, Any]], proposal_count: int
) -> tuple[dict[int, int], int | None, bool]:
    """Count ``yes`` votes per proposal index. A bare ``yes`` (no ``for``)
    lands on the voter's own proposal via caller-set convention.

    Returns ``(tally, winner_idx, empty)``: ``winner_idx`` is the proposal
    with the most yes votes (ties broken by lowest index); ``empty`` is
    True when no proposal collected any vote and the round should sit out.
    """
    tally = dict.fromkeys(range(proposal_count), 0)
    for vote_record in votes:
        if vote_record.get("choice") != "yes":
            continue
        target = vote_record.get("for")
        if isinstance(target, int) and 1 <= target <= proposal_count:
            tally[target - 1] += 1
        else:
            # A bare yes counts as approval of whichever proposal the voter
            # authored; we store that as the voter's own index when known.
            voter_id = vote_record.get("voter_id")
            author_index = vote_record.get("voter_proposal_idx")
            if isinstance(author_index, int) and 0 <= author_index < proposal_count:
                tally[author_index] += 1
            elif voter_id is not None:
                # fall back: no-op; the bare yes is not lost in dissent_rate.
                _LOG.debug("warzone: bare yes from voter #%s, no proposal anchor", voter_id)
    if proposal_count <= 0 or max(tally.values(), default=0) == 0:
        return tally, None, True
    best_score = max(tally.values())
    winners = sorted(idx for idx, n in tally.items() if n == best_score)
    return tally, winners[0], False


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then play the round in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if not agent_ids:
        raise ValueError("先选几个居民")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    resolve_scenario(str(payload.get("scenario_id") or ""), custom)
    days = int(payload.get("days") or DEFAULT_DAYS)

    return _JOBS.run(
        lambda progress: run_warzone(
            city=city,
            agent_ids=agent_ids,
            scenario_id=str(payload.get("scenario_id") or ""),
            custom=custom,
            days=days,
            progress=progress,
        )
    )


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/warzone/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/warzone/catalogue":
            return {
                "scenarios": list_scenarios(),
                "max_agents": MAX_AGENTS,
                "default_days": DEFAULT_DAYS,
                "resources": list(RESOURCES),
            }, 200
        if path == "/api/games/warzone/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/warzone/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("warzone GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/warzone/run":
            return {"job_id": start_run(payload)}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("warzone POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "DEFAULT_DAYS",
    "MAX_AGENTS",
    "MAX_HEALTH",
    "MAX_PLAN_ROWS",
    "OTHER_PLAN",
    "RESOURCES",
    "WARZONE_BANK",
    "Resident",
    "handle_get",
    "handle_post",
    "job_status",
    "list_runs",
    "list_scenarios",
    "parse_proposal",
    "parse_vote",
    "reset_jobs",
    "resolve_scenario",
    "run_warzone",
    "scenario_by_id",
    "start_run",
]
