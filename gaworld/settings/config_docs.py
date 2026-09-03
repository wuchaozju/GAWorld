"""Per-key documentation for the CONFIG tree, for the dashboard 配置 panel.

The config tree has ~600 leaves spread across the fragments in this package.
A hand-written catalogue for all of them would be longer than the settings
modules themselves and would go stale the first time someone adds a knob, so
the help text comes from two sources merged at read time:

* **The comments already sitting above each key in ``gaworld/settings/*.py``.**
  Those comments *are* this project's config documentation — extracting them
  costs one AST walk and can never drift from the code it describes. A key
  gets the comment block immediately above it, or its trailing inline comment.
* **A curated override table** (:data:`MANUAL_HELP`) for the knobs an operator
  actually reaches for, where the source comment is missing, English-only, or
  written for a maintainer rather than for the person turning the dial.

Manual text wins over extracted text. Following the convention already set by
``site/dashboard/external.js``: a help string says *what changes if you change
this*, not what the key is named. "仿真天数：仿真的天数" is worth nothing.

Labels are resolved full-path-first, then by last segment, because the same
leaf name means different things in different subtrees (``timeout`` under a
provider is an HTTP timeout; ``enabled`` is everywhere).
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from functools import lru_cache
from pathlib import Path
from typing import Any

from .behavior import human_realism_settings, intervention_settings, news_settings
from .economy import economy_settings
from .environment import environment_settings
from .family import family_settings
from .integrations import integration_settings
from .llm import llm_settings
from .personality import personality_settings
from .runtime import simulation_settings

_SETTINGS_DIR = Path(__file__).resolve().parent

#: Longest help string served to the browser. Some source comments are
#: multi-paragraph design notes; a tooltip that fills the viewport is worse
#: than a truncated one.
_MAX_HELP_CHARS = 420


# ---------------------------------------------------------------------------
# Sections — one per config fragment, so the grouping cannot drift from the
# code. ``build_default_config`` composes exactly these, in this order.
# ---------------------------------------------------------------------------

#: ``(id, module, factory, title, help)``. ``factory`` is called to learn which
#: top-level CONFIG keys belong to the section.
SECTIONS: tuple[tuple[str, str, Any, str, str], ...] = (
    (
        "simulation",
        "runtime",
        simulation_settings,
        "仿真运行",
        "一次运行的骨架：跑几天、跑哪些居民、时间怎么推进、记忆存哪、日程有多大概率被打乱。"
        "改这里等于换一次实验的设定，不影响正在跑的那一轮。",
    ),
    (
        "llm",
        "llm",
        llm_settings,
        "语言模型",
        "智能体用哪个大模型思考。providers 是可选的后端清单，routing 决定实际派给谁；"
        "密钥不在这里，在下面的「环境变量」里。",
    ),
    (
        "environment",
        "environment",
        environment_settings,
        "环境与感知",
        "居民能感知到的世界：所在地点挤不挤、异常事件算不算异常、外部环境服务从哪拿天气"
        "和新闻、多机之间怎么中继。",
    ),
    (
        "news",
        "behavior",
        news_settings,
        "新闻与主动检索",
        "居民从外界读到什么：刷新闻的概率、主动上网搜索的频率和搜索引擎、抓回来的正文"
        "有多少会写进记忆。",
    ),
    (
        "intervention",
        "behavior",
        intervention_settings,
        "推荐与干预评估",
        "信息流实验用的一层：推荐条数、毒性/不实内容的抑制阈值、立场更新速度。全部是"
        "确定性计算，不额外调模型。",
    ),
    (
        "human_realism",
        "behavior",
        human_realism_settings,
        "人的真实性",
        "让居民像人：兴趣会成长也会遗忘、目标分三层并定期复盘、习惯靠重复养成、"
        "疲劳饥饿会打断计划。",
    ),
    (
        "economy",
        "economy",
        economy_settings,
        "经济系统",
        "钱的规则：个税、社保、消费结构、投资收益、信贷、宏观周期。改的是下一次运行的"
        "规则；要动正在跑的那一轮，去「外部系统 → 货币系统」排干预。",
    ),
    (
        "family",
        "family",
        family_settings,
        "家庭与户",
        "谁结了婚、谁还单身、谁跟父母住、谁在带娃。婚姻状态按年龄段抽样，家庭再决定日程里"
        "的接送与晚饭、账上的育儿与赡养开销、以及一家人共担的突发事件。改的是下一次运行。",
    ),
    (
        "personality",
        "personality",
        personality_settings,
        "大五人格",
        "每个居民的开放性/尽责性/外向性/宜人性/神经质。三条通道可以分别开关：rules 影响"
        "动作选择与打断阈值，prompt 把人格写成行为描述进决策提示词，voice 只影响日记文风。"
        "分开是为了能区分「决策变了」和「文风变了」。",
    ),
    (
        "integrations",
        "integrations",
        integration_settings,
        "扩展与真实工作",
        "仿真往外接的部分：自定义扩展钩子、多人协作会话、以及把「工作」类活动派给本地"
        "适配器真的产出文件的 real_work 子系统。",
    ),
)

#: Top-level CONFIG keys that exist only because ``data/environment_config.json``
#: injects them — no Python fragment declares them, so :func:`section_index`
#: cannot place them. They are the weather/news generator settings, and users
#: look for those under 环境, not in a catch-all bucket.
SECTION_EXTRA_KEYS: dict[str, tuple[str, ...]] = {
    "environment": (
        "external_environment",
        "external_environment_service",
        "environment",
    ),
}


# ---------------------------------------------------------------------------
# Curated overrides
# ---------------------------------------------------------------------------

#: Full dotted path -> help text. Wins over the extracted source comment.
MANUAL_HELP: dict[str, str] = {
    # ---- 仿真运行 ----
    "agent_ids": "参与本次仿真的居民编号。留一个数字 N 表示取前 N 位居民；写成列表就是精确指定这几位。人越多，一天的 LLM 调用越多。",
    "sim_days": "跑几个仿真日。天数直接决定总成本和总时长。",
    "seconds_per_day": "一个仿真日折算成多少真实秒。只在「实时等待」打开时才真的等；关掉时它只影响回放动画的节奏。",
    "simulate_realtime": "打开后仿真会按真实时间等待，像看直播；关掉则以 CPU/模型能跑多快就跑多快。做实验一般关掉。",
    "print_agent_profile": "开跑前把每位居民的人物设定打印到终端。调试用，日志会很长。",
    "time_step_minutes": "日内推进的时间粒度。留空表示只在日程写明的时刻推进；填 60 就是每小时一步——步长越小，一天的 LLM 调用越多。",
    "time_grid_snap": "把所有人的日程都对齐到上面的时间格。不开时，总时刻数是「网格 ∪ 每个人自己的时间点」，人一多刻数就爆炸；开了就固定在 1440/步长，这是 100 人以上跑得起的前提。代价是日内时间会被挪动。",
    "long_run": "长时段快进：一步压缩成一条简报（每人每步一次调用），跳过日内循环。60/600 天这种尺度必须开，代价是日内细节全部消失。步长可以是天、月、年。",
    "long_run.enabled": "打开快进模式。跑 60 天以上时不开基本跑不完。",
    "long_run.unit": "一步代表多长时间：day / month / year。选 month 就是一个月一条阶段简报，选 year 就是一年一条——跑十年这种尺度只能用粗粒度（10 年 × 50 人：按年 500 次调用，按天 18 万次）。仿真天数照常推进，变的只是认知粒度。选 month/year 会**自动打开快进**（enabled 不必再勾）：没有「按月的日内时刻循环」这种东西，不自动打开就等于闷头按天跑完整个跨度。",
    "long_run.brief_llm": "简报用模型写（贵、有细节）还是按规则拼（零调用、干巴）。",
    "long_run.max_state_delta": "快进时单步状态最多变化多少。防止一天之内情绪从 0.2 跳到 0.9；按月/按年步长会自动放宽（×2 / ×3），因为变化是整段累计的。",
    "long_run.randomness": "快进期间的随机程度：越高，突发事件越频繁、状态波动越大。0 = 完全确定，同种子必然复现。粗粒度下突发事件的期望个数按步长天数放大。",
    "long_run.brief_max_chars": "每条日简报的字数上限，超了会被截断。",
    "long_run.period_brief_max_chars": "月度简报的字数上限；年度简报按 1.5 倍算。",
    "long_run.hook_chunk_days": "粗粒度下，日边界钩子（经济结算、兴趣衰减、家庭开销）每多少天补跑一次。上限 30，保证一个区块最多跨一次月结算——否则跑一年只会扣一天房租。",
    "calendar": "仿真日历：从哪天开始、开局是周几、哪几天算周末。周末会改变日程模板和外出概率。",
    "calendar.start_date": "开局日期。填 today 表示用今天的真实日期。",
    "calendar.start_weekday": "第 1 天是周几。会连带决定后面哪些天落在周末。",
    "calendar.weekend_days": "哪几天算周末。周末的日程模板和活动权重与工作日不同。",
    "external_rag": "把外部资料喂给居民的通道：开局灌一批背景信息，运行中还可以持续吸收。",
    "external_rag.top_k": "每次回忆时最多召回几条外部资料。调大会挤占提示词里留给个人记忆的位置。",
    "external_rag.bootstrap": "开跑前给每位居民灌一批背景资料，避免第一天所有人都像刚出生。",
    "external_rag.runtime_absorb": "运行中每到日界再抓一小批与当前成长目标相关的新资料。默认关，开了会增加联网请求。",
    "background": "整个世界的时代背景，会进入每一次思考的提示词。改它等于换一个社会环境设定。",
    "csv_path": "居民初始状态表（九个 0–1 变量）。改路径等于换一批人。",
    "md_path": "居民人物设定文档。Agent Studio 编辑的就是这个文件。",
    "map_path": "虚拟地图定义文件，仅在 map_mode = virtual 时使用。",
    "map_mode": "用程序生成的网格地图（virtual），还是真实杭州的 OSM 路网（real）。real 更真实，但需要先跑脚本把地图数据抓下来。",
    "real_map_path": "真实地图数据包路径，仅在 map_mode = real 时使用。缺文件会退回虚拟地图。",
    "stateful": "跨轮次保留记忆。关掉后每次运行都从空白记忆开始，适合做干净的对照实验。",
    "memory_dir": "记忆与向量库的落盘目录。换目录等于换一套记忆，旧的还在。",
    "log_dir": "运行日志目录。",
    "diary_output_dir": "每位居民每天的日记输出目录。",
    "environment_output_dir": "环境事件的输出目录。",
    "visualization": "轨迹可视化：是否记录每帧位置、写到哪、多久刷一次盘。",
    "visualization.flush_every_frames": "攒够多少帧才写一次文件。调小更实时但磁盘写得更频繁。",
    "environment_config_path": "环境配置文件的位置。注意：这个文件会在最后再覆盖一次 CONFIG，所以它里面写了的项，改上面的没用。",
    "memory_model_version": "记忆格式版本号。它一变就说明旧记忆不兼容，需要先 reset 一次。",
    "require_clean_reset_on_memory_model_change": "记忆格式变了却没重置时直接报错，而不是拿旧记忆硬跑出一堆诡异结果。",
    "vector_db_path": "记忆向量库文件。删掉它等于清空全部长期记忆。",
    "vector_db_dim": "向量维度。改了之后旧库不可用，必须重建。",
    "vector_db_top_k": "每次检索返回几条记忆。调大提示词更长、更贵。",
    "vector_db_max_chars": "单条记忆入库时的字数上限。",
    "vector_db_embedding_provider": "怎么把文字变成向量：hash 是零依赖但很粗糙的哈希词袋；llm 调用模型的 embedding 接口，检索质量高但每条都要花钱。",
    "memory": "记忆机制：回忆时怎么打分、多久整理一次、什么时候开始遗忘。",
    "memory.salience_weight": "回忆打分时把「这件事有多重要」和「过去多久」算进去，而不是只看文字相似度。关掉即退回纯相似度。",
    "memory.decay_halflife_days": "记忆权重的半衰期（天）。越小，越容易只想起最近的事。",
    "memory.growth_boost": "和当前成长目标相关的记忆会被排到更前面。",
    "memory.consolidation": "定期把最近的零散经历总结成一条长期记忆，模拟「睡一觉整理一下」。",
    "memory.decay": "定期把很久没想起、又不重要的记忆删掉，防止记忆库无限膨胀。",
    "memory.skill_consolidation": "定期把反复做成的事沉淀成一条私人技能。",
    "skills": "技能库：公共技能从哪读，要不要塞进思考和工作提示词，一次最多塞几条。",
    "policy_events": "预先排好的政策事件。到点自动触发，用来做「有政策 / 无政策」对照实验。",
    "life_events": "针对个人的生活事件队列。仿真跑着的时候也能从面板往里加，下一个 tick 就会被消费。",
    "life_events.severity_state_amplify": "事件严重度对状态冲击的放大系数。0 = 不论多严重，状态影响都一样。",
    "life_events.reshape": "严重事件当天直接改写后面的日程，而不是只掷一次「要不要改计划」的骰子——不然一个高承诺度的活动总会赢，出了大事人还在照常上班。",
    "life_events.aftermath": "严重事件的余波会延续好几天并逐日衰减，作为「你还没缓过来」写进后面几天的计划约束。",
    "routine_change": "居民有多大概率临时偏离既定日程。",
    "routine_change.enabled": "关掉后所有人严格照日程执行，像上了发条。",
    "routine_change.base_chance": "没有任何事发生时，每个时刻临时改计划的基础概率。",
    "routine_change.event_boost": "身边发生事件时，改计划概率往上加多少。",
    "routine_change.policy_boost": "有政策事件时，改计划概率往上加多少。",
    "routine_change.max_chance": "改计划概率的上限，防止叠加到「几乎必然乱套」。",
    "routine_change.randomness": "总的「日程有多松」旋钮，0–1。越高越随性：高承诺活动更容易被放弃、无端的躁动更多。0 = 严格按调好的默认值走。睡觉时段不受影响。",
    "routine_change.severity_pivot": "事件严重度超过这个值才开始推动改计划。低于它的小事按 0 计。",
    "daily_planning": "每天早上怎么排当天的日程。",
    "daily_planning.autoregressive": "以昨天的实际安排为底稿排今天，变化会一天天累积；关掉则每天回到固定模板，等于每天重置人生。",
    "daily_planning.flexible.min_anchor_match": "新排的日程至少要有多大比例贴着基准锚点才被接受，否则打回基准。调低 = 日子更自由但也更飘。",
    "spontaneity": "自发性：会不会突然冒出念头、临时起意做点别的。压力、疲劳、饥饿都会把这些概率往上推。",
    "concurrency": "并行度。默认串行以保证同种子可复现；开并行会快，但日内顺序不再严格一致。",
    "concurrency.day_routine_workers": "每日日程生成阶段的并发线程数。受限于模型服务端的并发能力。",
    # ---- 语言模型 ----
    "llm": "多后端模型配置：providers 是可用后端清单，routing 决定哪个任务派给谁。",
    "llm.providers": "可用的模型后端清单。密钥通过环境变量注入，不写在这里。",
    "llm.routing": "任务怎么派给模型。",
    "llm.routing.default": "没有单独指定的任务都用这个后端。它决定了绝大部分成本。",
    "llm.routing.tasks": "给个别任务单独指定后端，比如把排日程这种量大又不需要聪明的活派给便宜的本地模型。",
    "model_name": "旧版单模型字段，只在没走 llm.routing 的老代码路径上生效。",
    "ollama_url": "旧版 Ollama 地址，只在没走 llm.routing 的老代码路径上生效。",
    "llm_timeout": "旧版全局超时（秒）。新代码用各 provider 自己的 timeout。",
    # ---- 环境 ----
    "local_physical": "居民对当前所在地点的感知：挤不挤、开没开门。关掉后人对周围环境一无所知。",
    "anomaly": "什么才算「异常」。普通的下雨和小幅行情波动不算；极端天气、突发事故、高严重度事件才算。这里只调「怎么判定异常」，判定之后反应有多大是写死在行为代码里的。",
    "distributed": "多机联跑：本机负责哪些居民、对端有哪些、消息怎么中继。单机跑用不到。",
    # ---- 新闻 ----
    "news.enabled": "关掉后居民完全不看新闻，外部世界对他们不可见。",
    "news.use_cache_first": "优先用缓存的新闻而不是每次真的联网。省时间省配额，代价是内容不新。",
    "news.daily_chance": "每位居民每天看新闻的概率。",
    "news.max_reads_per_day": "每人每天最多读几条，防止一个人刷一整天。",
    "news.info_seek": "主动检索：不只是被动刷到，还会自己去搜。这是联网请求的大头。",
    "news.info_seek.engines": "按顺序尝试的搜索引擎。x 需要配 Token，没配会被静默跳过。",
    # ---- 干预 ----
    "intervention.enabled": "关掉后推荐与干预这一层完全不参与，信息流按原样呈现。",
    "intervention.exposure_control": "把毒性/不实内容的曝光压下去。阈值越低压得越狠。",
    "intervention.stance.alpha": "立场更新的惯性：越接近 1 越不容易被单条内容说服。",
    # ---- 人的真实性 ----
    "interests": "兴趣与技能成长：会新增、会练熟，也会因为长期不碰而退步。",
    "interests.decay": "长期不练的兴趣会掉级。grace_days 是宽限期，练得越多越不容易忘。",
    "interests.evolution": "兴趣本身会换：老的退役，新的从朋友那里「传染」过来。",
    "goals": "三层目标（人生 / 长期 / 短期），它是每日日程的上游——日程排什么，取决于当前目标是什么。",
    "goals.review_interval_days": "隔多少天做一次目标复盘。复盘会调用模型，间隔越短越贵。",
    "goals.event_review_severity": "严重度超过这个值的事件会立刻触发一次计划外复盘，不等到下个周期。",
    "goals.max_reviews_per_day": "每个仿真日最多做几次周期性复盘（事件触发的不受限）。超出的人排到第二天，防止大规模人口在同一天集体烧钱。",
    "human_realism": "经验积累与习惯/需求动力学的总开关及其参数。",
    "human_realism.llm.max_extra_calls_per_agent_day": "为了「更真实」每人每天最多额外调用几次模型。这是成本闸门。",
    "human_realism.memory.recall": "各个环节（计划、行动、反思、采访）各召回几条记忆。全都调大 = 提示词全面变长。",
    "human_realism.behavior.habit_learning_rate": "习惯养成的速度。越大，重复几次就固化成习惯。",
    "human_realism.behavior.habit_min_occurrences": "同一情境重复几次才算习惯。设成 1 的话，一次意外也会被当成习惯。",
    "human_realism.behavior.inertia_weight": "惯性权重：越大越倾向于继续做正在做的事。",
    "human_realism.behavior.decision_noise": "决策噪声：越大越不可预测，也越不像有稳定人格。",
    "human_realism.behavior.commitment_weights": "高/中/低承诺度的活动各有多难被打断。",
    "human_realism.behavior.need_weights": "精力、饥饿、社交需求三者谁更容易打断当前活动。",
    "dynamic_behavior": "自发冲动、偶遇、需求打断、环境触发的临时改变——关掉后人会显得很按部就班。",
    # ---- 集成 ----
    "extensions": "自定义扩展钩子，写成 \"模块:函数\"。strict 打开时钩子加载失败会直接终止，而不是静默跳过。",
    "collaboration": "多人协作会话（讨论、合作任务）的并发数、上下文长度和重试次数。",
    "collaboration.max_concurrent_sessions": "同时进行的协作会话数。每个会话都在烧模型调用，这是成本闸门。",
    "collaboration.discussion.default_rounds": "一场讨论默认几轮。轮数直接乘上参与人数等于总调用数。",
    "real_work": "真实工作执行：把「工作」类活动派给本地适配器，真的产出代码/文案/设计文件到 artifacts_dir。",
    "real_work.enabled": "关掉后「工作」只是日程上的一个词，不会产出任何文件。",
    "real_work.max_concurrent_tasks": "同时执行的真实任务数。",
    "real_work.task_timeout_seconds": "单个任务的超时。卡住的任务会在这之后被放弃。",
    "real_work.market": "模拟的接活市场：居民可以去浏览并接任务。",
    "real_work.external_hooks": "把任务转发到外部 webhook 或 MCP 服务。留空表示只在本地跑。",
    # ---- 经济 ----
    "economy": "钱的全套规则。这里改的是下一次运行的初始条件；要动正在跑的那一轮，去「外部系统 → 货币系统」排一次干预。",
    "economy.enabled": "关掉后居民没有账户、不发工资也不花钱，经济这一层完全不参与。",
    "economy.hours_per_step": "一个仿真步折算多少工时。它同时决定挣多少和花多少，改动会等比放大整个经济的节奏。",
    "economy.initial_savings_months_min": "开局存款下限，按「几个月的支出」算。和上限一起决定了开局的贫富起点。",
    "economy.initial_savings_months_max": "开局存款上限，按「几个月的支出」算。",
    "economy.inheritance_enabled": "让一部分人开局就有家底。关掉后所有人从同一条起跑线出发，贫富差距只能靠仿真过程拉开。",
    "economy.tax": "个人所得税。brackets 是税率表，每行 [本级上限, 税率, 速算扣除数]，最后一行的上限是无穷大。",
    "economy.tax.monthly_exemption": "每月起征点，收入减掉它之后才计税。",
    "economy.social_insurance": "五险一金的个人缴纳比例。它直接从工资里扣，是「税前工资」和「到手工资」的主要差额。",
    "economy.spending": "怎么花钱。engel_curve 是收入越高、食品占比越低的经验曲线，每行 [收入, 食品占比, 储蓄率]。",
    "economy.investment": "投资收益模型：各类资产的均值/波动，以及保守/稳健/激进三种组合画像。",
    "economy.credit": "信贷：能借多少（按月收入的倍数）、年利率多少。利率越高，欠债的人越难翻身。",
    "economy.macro": "宏观周期：扩张 → 顶峰 → 收缩 → 谷底循环。不同阶段的涨薪和裁员概率不一样。",
    "economy.macro.initial_inflation_rate": "年通胀率。注意它只作用在支出侧——工资不跟涨，所以长期跑下来居民会越来越买不起东西。",
    "economy.macro.initial_unemployment_rate": "一个景气指标，本身不会让谁丢工作；真正决定裁员的是各阶段的 layoff_risk。",
    "economy.shocks": "个体层面的意外：裁员、涨薪、医疗急症。概率是每人每期的。",
    "economy.routing": "居民花出去的钱流向谁：商户的劳动分成进企业池，房租进房东，其余按规则分配。",
    "economy.friend_loans": "熟人之间借钱的规则：最多欠几个月、出借方要留多少缓冲、有多大意愿借。",
    "economy.sectors": "企业池 / 政府池 / 银行池的初始余额。这三个池子加上所有居民账户构成系统总货币，正常情况下总量守恒。",
    "economy.rent_income_ratio": "房租占收入的比例，是大多数居民最大的一笔固定支出。",
    "economy.income_seek_threshold": "资产低到什么程度就开始主动找钱。越高，居民越早为钱发愁。",
    # ---- 外部环境生成器（来自 environment_config.json）----
    "external_environment": "每天生成天气、行情、政策、科技新闻的那台机器。这些事件会进入每位居民当天的情境。注意：这一整棵子树由 data/environment_config.json 提供，它在最后覆盖 CONFIG——在这里改会被它盖掉。",
    "external_environment.generator.mode": "用 LLM 编事件（更多样、要花钱）还是按规则从事件池里抽（免费、重复度高）。",
    "external_environment.natural": "天气与极端天气。极端天气会被判定为异常，可能直接打乱当天日程。",
    "external_environment.economic": "行情波动与宏观新闻。波动超过阈值才会被播报成一条新闻。",
    "external_environment.political": "政策事件。政策会提高全员改变日程的概率。",
    "external_environment.intraday": "日内突发：不在早上一次性生成，而是白天随机插进来，最容易打断正在进行的活动。",
    "external_environment_service": "从外部服务拿环境事件，而不是本机生成。多机联跑时让所有节点看到同一个世界。",
    "external_environment_service.fallback_to_empty": "服务不通时当作「今天没事发生」继续跑，而不是让整轮仿真失败。",
    "environment": "旧版环境事件（保留兼容）。新逻辑在 external_environment 里；两边都开会同时产生事件。",
    # ---- 家庭与户 ----
    "family": "家庭系统总开关。关掉就回到改动前的状态：所有居民都是单身，日程和账目里没有家人。",
    "family.seed": "换一个数字就重抽一批家庭。同一个种子下，同一位居民每次运行都是同一个家。",
    "family.overrides_path": "在「智能体工作台 → 社交·关系」里手工指定的家庭存在这个文件里。家庭每次运行都会重新生成，这个文件里的记录优先于自动抽样，所以手工指定的家庭不会被冲掉。删掉文件就等于全部恢复自动生成。",
    "family.marital_status_bands": "每个年龄段里未婚/已婚/离异/丧偶各占多少。这张表决定了「有多少人还是单身」——想让全城更晚婚，把 25-34 段的 never 调高。",
    "family.pairing.in_sim_pair_share": "多少比例的已婚居民，配偶是名单里的另一位居民（而不是场外的人）。注意：从一座千万人口的城市里抽几十个人，他们互为夫妻的真实概率约等于 0——这个值是为了让家庭互动发生在仿真内部而做的取舍，不是人口学事实。调到 0 就是人口学纯净的跑法：所有配偶都在场外。",
    "family.pairing.max_age_gap": "两位居民能配成夫妻的最大年龄差。调小了能配上的对数会变少，剩下的人会拿到场外配偶。",
    "family.fertility.p_any_child": "各年龄段「至少有一个孩子」的概率。整体调低就是一次低生育率实验——孩子少了，日程里的接送和账上的育儿开销会跟着一起变。",
    "family.fertility.coresident_child_max_age": "超过这个岁数的孩子算已经独立搬出去：还是亲人，但不再共居、不再产生带娃责任和开销。",
    "family.coresidence.with_parents_local": "本地户籍的未婚居民有多少和父母同住。外地户籍走下面那个值，两者差距很大是刻意的。",
    "family.coresidence.multigen_with_young_child": "有学龄前孩子时，老人搬来同住帮忙带的概率。三代同堂在中国城市多半是「有人得看孩子」带来的，不是凭空的户型占比。",
    "family.duties.max_per_day": "一天最多往日程提示里塞几条家庭责任。调大了日程会被家务填满，调到 0 等于只保留家庭关系、不影响日程。",
    "family.finance.pooling_rate": "伴侣手头紧时，另一方最多拿出自己富余现金的多大比例去补。这是两人账户之间的转账，不凭空产生钱。",
    "family.finance.child_cost_monthly": "每个孩子每月的花销（托育、学费、杂项）。这笔钱按收入在家里挣钱的人之间分摊，走的是经济模块正常的支出通道。",
    # ---- 大五人格 ----
    "personality.channels": "人格从哪几条路影响居民，可以分别关掉。rules 是确定性规则（动作选择、打断阈值、消费倾向、情绪基线），零调用且可复现；prompt 在决策提示词里额外加一两句本场景相关的行为锚句；voice 只进日记。分成三条是为了能回答「到底是决策变了还是文风变了」——全开时这个问题无解。\n\nprompt 默认关，依据是 A4 消融臂（1,632 次调用，提案 §15）：87 格配对探针，结构化选择朝锚句方向移动的只有 48/87（判据 52），反向锚句判别臂 16/30，两项都不达标。原因不是锚句没进模型——与分类器无关的文本相似度检验显示 anchor 与 plain 的输出确实比同条件两次采样更不像（Cohen d = 0.29），模型读了；是它没把选择推到决策循环看得见的方向。而人格进提示词这件事本身已由语料重写完成：每位居民的「人格与行为倾向」段落**不在这条通道上，无论开关都会渲染**，独立打分器能从中把分数读回来（r = 0.79）。锚句是在那之上再加一句所有同极人共用的泛泛话，89.8% 重复段落已写的维度，成本约 36 tokens/次。要做 A4 对照或想试更强的配置，把它打开即可。",
    "action_space.activities_per_call": "一次动作生成调用最多问几个活动。这个数不是拍的：848 条真实响应里，单个活动块中位 193 字、p75 215 字，而 provider 默认 512 token 的输出上限只放得下约 916 字——4 个活动正好卡在边上（实测 37.5% 被截断），6 个以上必然装不下。而真实一天有 10 个不重复活动，所以不分批的那次调用从来就不可能成功：它只能救回前 4 个，重试再撞同一堵墙。取 3 是给啰嗦的智能体留一档余量。分批不比原来贵——10 个活动分 4 次都成功，对比原来 2 次失败之后每个活动还要各补一次。",
    "personality.profile_path": "每位居民的五个人格分数（z 分，正数偏高、负数偏低）。由 scripts/calibrate_big5.py 从人物设定里的「性格与情绪特征」离线标定一次后冻结在这里，运行时只读不改：每次开跑都重新打分既费钱，也会让同一个种子的两次运行对不上。文件不在时改用人群先验采样。",
    "personality.strength": "人格总开关的力度。所有通道一起缩放，调到 0 等于人格不起作用但数据还在（可以拿来做对照组），调到 1 以上会让人格盖过情境。",
    "personality.style_fit_amplitude": "人格在「选哪个动作」里占多大权重。参照系是旁边已有的权重项：成长动机 0.6、习惯惯性约 0.9。调过 0.9 人格就和习惯一样强了，那不符合人格只解释一到两成行为差异的实证量级。改完先跑 scripts/big5_effect_ceiling.py 看隐含相关落没落在 0.10-0.40。",
    "personality.modifier_band": "乘性调节的上下限。这类调节作用在每个时间步都会复合的小概率上（打断、冲动、偶遇），所以band 刻意留窄——放宽会在几十步之后失控。",
    "personality.residual_ratio": "每个人身上与人格无关的个体差异有多大。设成 0 会让人格与行为变成精确映射，观测窗口一长相关就趋近 1，那时测到的是天数不是人格。",
    "personality.prompt.render_midpoint": "一个维度要多突出才会被写进提示词。这不是硬阈值：写不写按概率抽，刚好卡在中点的人是五五开，越极端越必然被写。用硬阈值会把连续的人格切成高/中/低三类，还在阈值处留一个跳变。",
    "personality.prompt.render_spread": "上面那个概率的过渡带宽度。调小就接近硬阈值，调大则连普通人也会被描述几句。",
    "personality.prompt.floor_z": "低于这个 |z| 就完全不写，无论上面的概率算出多少。和写入门槛的分工不同：那个决定「多突出才值得一提」，这个决定「这个人到底有没有偏向」。它也是 prompt 通道两种定位的分界——0.25 时锚句大多在重复「人格与行为倾向」段落已经写过的维度（段落写 |z| ≥ 0.5），0.5 时锚句只补段落没写的空档。",
    "personality.prompt.max_dims": "每段提示词最多写几条人格描述。这些提示词本来就有十几段上下文，人格写多了会把当天的处境挤掉——人格压过处境正是最常见的失真。",
    "personality.emotion_baseline": "给情绪一个属于个人的基准线。原先的情绪传染只把人往邻居的平均情绪上拉、没有任何东西把他拉回自己，跑久了全城情绪会收敛成一个数——个体差异被抹平。神经质要能起作用，必须先修这里。",
    "personality.emotion_baseline.contagion_weight": "被周围人情绪带走的速度。原来写死是 0.1，调低后个人基线才拉得回来。",
    "personality.emotion_baseline.recovery_rate": "每一步往自己的情绪基准线回多少，和上面的传染强度是同一根天平的两头。越大情绪越有韧性，越小越容易被周围人带走。",
    "personality.sampling": "没有标定文件时怎么现场生成人格。合成人口走的就是这条路——它的性格描述本身是由压力和表达倾向拼出来的模板，拿去反向打分只会把状态变量原样捞回来，等于什么信息都没加。",
    "personality.sampling.correlations": "五个维度之间的相关。人格维度并不正交：神经质与其余四维负相关，宜人性/尽责性/外向性之间弱正相关。全填 0 会造出现实中不存在的人（比如又极度神经质又极度情绪稳定的组合）。",
    "personality.sampling.rescale": "抽完之后把人群拉回均值 0、标准差 1。五十来个人的样本，均值本身就有约 0.14 个标准差的抖动，不拉回来整座城可能系统性偏内向或偏焦虑，而这会被误读成一个发现。",
    "family.finance.elder_support_monthly": "给不同住的老人每月寄多少赡养费。父母年龄到了下面那个阈值才开始算。",
    "family.events.daily_probability": "每户每天发生一件家庭事件的概率（孩子发烧、夫妻吵架、家庭聚餐……）。事件会同时落到全家人身上。",
    "family.events.contagion_weight": "同住家人之间情绪和压力的互相影响强度。它是「向对方靠拢」而不是凭空加减：全家都平静时不会产生任何漂移。调到 0 就关掉传染。",
    "family.cohabitation": "未婚但住在一起的那部分人。他们拿到的是「伴侣」而不是「配偶」，也不会有共同子女。",
    "family.cohabitation.share": "这个年龄区间内的未婚居民里，有多少和伴侣同居。",
    "family.pairing": "怎么给已婚居民找配偶。同性伴侣未建模；实在配不上的人会拿到一位场外配偶，而不是被退回单身。",
    "family.pairing.prefer_in_sim": "先尝试在参与仿真的居民之间配对。关掉之后所有配偶都在场外，家里就不会有另一个会自己行动的人。",
    "family.pairing.spouse_age_gap_mean": "场外配偶比本人大几岁（男方年长为正）。仿真内配对用的是两人的真实年龄，不受这个值影响。",
    "family.pairing.same_district_bonus": "两人住在同一个城区时，配成夫妻的加权。调高会让夫妻更集中在同一片区。",
    "family.fertility": "谁有孩子、有几个、孩子多大。这几个旋钮直接决定了日程里的接送和账上的育儿开销。",
    "family.fertility.p_second_child": "已经有一个孩子的家庭再生第二个的比例。",
    "family.fertility.p_third_child": "已经有两个孩子的家庭再生第三个的比例。",
    "family.fertility.parent_age_at_first_birth": "父母生头胎时的年龄区间。孩子的岁数是从这里倒推的，所以调高会让孩子整体偏小。",
    "family.coresidence": "谁和谁住在一起。同住是关键：只有共居的家人才会共享住处、产生日常照料、互相传染情绪。",
    "family.coresidence.with_parents_migrant": "外地户籍的未婚居民和父母同住的比例。默认远低于本地户籍，这是刻意的。",
    "family.coresidence.shared_rental_share": "既不和父母住、也没有伴侣的未婚居民里，有多少是合租而不是独居。合租的人在家里至少还有个室友。",
    "family.coresidence.multigen_base": "没有幼儿时，老人搬来同住的概率。",
    "family.coresidence.young_child_max_age": "多大以内算「需要有人全天看着」的幼儿。它同时影响三代同堂的概率和托育开销。",
    "family.coresidence.elder_with_child_age": "居民本人到了这个岁数，就可能反过来和成年子女同住。",
    "family.coresidence.elder_with_child_share": "到龄老人里有多少真的和成年子女住在一起。",
    "family.duties": "家庭责任怎么进日程：接送、陪写作业、照料老人、回家吃晚饭。工作日和周末给的是不同的责任。",
    "family.duties.school_age_max": "多大以内的孩子还需要接送和陪写作业。超过这个岁数只剩下「关心学业」这类轻责任。",
    "family.duties.preschool_age_max": "多大以内算学龄前。学龄前的孩子最费时间也最费钱，还会拉高老人来同住帮忙的概率。",
    "family.duties.elder_care_age": "同住的老人到了这个岁数就会产生实打实的照料责任（吃药、陪诊），而不只是一起吃饭。",
    "family.finance": "家里的钱：养孩子、养老人，以及伴侣之间互相补窟窿。所有流水都守恒，不会凭空产生或消失。",
    "family.finance.preschool_extra_monthly": "学龄前孩子在基础开销之外每月多花的钱（托班、看护）。",
    "family.finance.elder_support_min_age": "父母到了这个岁数才开始需要赡养费。",
    "family.finance.coresident_elder_monthly": "同住老人每月的花销。比寄出去的赡养费低，但不是零。",
    "family.finance.shared_rent_discount": "多人同住时，一个人实际承担的房租相当于独居的百分之多少。",
    "family.finance.spouse_bailout_enabled": "一方现金见底时，另一方先补上，而不是让他先去借钱。关掉之后夫妻就是各花各的。",
    "family.finance.dual_income_security_bonus": "家里有第二份收入时，每天给经济安全感加多少。数值很小，靠的是长期累积的倾向而不是一次性冲击。",
    "family.finance.sole_earner_stress": "独自养家时每天增加多少压力，按照护负担放大。",
    "family.events": "家庭里发生的事，以及一家人情绪的互相影响。",
    "family.events.contagion_enabled": "是否让同住家人之间的情绪和压力互相影响。",
    "family.events.remote_contagion_weight": "不同住的家人（外地的成年子女、前任）的影响强度。默认比同住低一个数量级。",
}

#: Full dotted path (or bare last segment) -> Chinese label. Full path wins.
LABELS: dict[str, str] = {
    # 通用
    "enabled": "启用", "output_dir": "输出目录", "cache_path": "缓存文件", "timeout": "超时(秒)",
    "url": "地址", "base_url": "地址", "host": "监听地址", "port": "端口", "seed": "随机种子",
    "mode": "模式", "model": "模型", "type": "类型", "api_key": "密钥（明文）",
    "api_key_env": "密钥环境变量", "api_key_envs": "密钥环境变量候选", "max_tokens": "最大 token",
    "temperature": "温度", "stream": "流式输出", "max_chars": "最大字数", "top_k": "召回条数",
    "randomness": "随机性", "max_items": "条目上限", "state_path": "状态文件", "description": "说明",
    "every_days": "间隔天数", "lookback_days": "回看天数", "min_age_days": "最小年龄(天)",
    "max_outputs": "产出上限", "min_episodes": "最少经历数", "floor": "下限", "daily_rate": "每日速率",
    "grace_days": "宽限天数", "adopt_chance": "采纳概率", "retire_after_days": "闲置退役天数",
    "max_new_per_day": "每日新增上限", "salience_floor": "重要度下限", "interval_minutes": "间隔(分钟)",
    "max_per_day": "每日上限", "trigger_salience": "触发重要度", "hint_chars": "提示长度",
    # 仿真
    "agent_ids": "参与居民", "sim_days": "仿真天数", "seconds_per_day": "每天秒数",
    "simulate_realtime": "实时等待", "print_agent_profile": "打印人物设定",
    "time_step_minutes": "时间步长(分钟)", "time_grid_snap": "对齐时间格",
    "long_run": "长时段快进", "brief_llm": "简报用 LLM", "max_state_delta": "单步状态变化上限",
    "brief_max_chars": "日简报字数上限", "unit": "步长单位",
    "period_brief_max_chars": "阶段简报字数上限", "hook_chunk_days": "日钩子补跑区块(天)",
    "action_space": "动作空间生成", "activities_per_call": "每次调用问几个活动",
    # 大五人格
    "personality": "大五人格", "channels": "生效通道", "rules": "规则通道", "prompt": "提示词通道",
    "voice": "文风通道", "profile_path": "人格分数表", "strength": "总力度",
    "style_fit_amplitude": "动作偏好幅度", "modifier_band": "乘性调节上限",
    "residual_ratio": "个体差异比例", "render_midpoint": "写入门槛", "render_spread": "门槛过渡带",
    "strong_z": "强描述阈值", "max_dims": "每段最多几条", "floor_z": "不写下限",
    "emotion_baseline": "情绪基准线",
    "contagion_weight": "情绪传染强度", "recovery_rate": "回归速率",
    "n_recovery_slope": "神经质·回归放缓", "n_baseline_slope": "神经质·基线下移",
    "e_baseline_slope": "外向性·基线上移",
    "sampling": "先验采样", "correlations": "维度间相关",
    "rescale": "采样后重标定",
    "calendar": "日历", "start_date": "开局日期", "start_weekday": "开局星期", "weekend_days": "周末",
    "background": "时代背景", "csv_path": "居民状态表", "md_path": "人物设定文档",
    "map_path": "虚拟地图", "map_mode": "地图模式", "real_map_path": "真实地图数据",
    "stateful": "跨轮保留记忆", "memory_dir": "记忆目录", "log_dir": "日志目录",
    "diary_output_dir": "日记目录", "environment_output_dir": "环境输出目录",
    "visualization": "轨迹可视化", "site_path": "页面路径", "flush_every_frames": "刷盘帧间隔",
    "environment_config_path": "环境配置文件", "memory_model_version": "记忆格式版本",
    "require_clean_reset_on_memory_model_change": "格式变更强制重置",
    "vector_db_path": "向量库文件", "vector_db_dim": "向量维度", "vector_db_top_k": "向量召回条数",
    "vector_db_max_chars": "单条入库字数上限", "vector_db_embedding_provider": "向量化方式",
    "memory": "记忆机制", "salience_weight": "重要度加权", "decay_halflife_days": "衰减半衰期(天)",
    "growth_boost": "成长相关加权", "growth_boost_strength": "成长加权强度",
    "consolidation": "记忆整理", "decay": "遗忘", "skill_consolidation": "技能沉淀",
    "skills": "技能库", "global_dir": "公共技能目录", "inject_into_cognition": "注入思考提示词",
    "inject_into_work_brief": "注入工作简报", "max_per_prompt": "每次提示词最多注入",
    "policy_events": "预设政策事件", "life_events": "生活事件队列", "event_dir": "事件目录",
    "events_file": "事件文件", "severity_state_amplify": "严重度放大系数",
    "reshape": "当天日程改写", "severity_threshold": "严重度阈值", "window_minutes": "影响窗口(分钟)",
    "aftermath": "事件余波", "min_severity": "最小严重度", "decay_per_day": "每日衰减",
    "min_residual": "残留下限", "max_age_days": "最长持续(天)", "state_pressure_scale": "状态压力系数",
    "routine_change": "日程偏离", "base_chance": "基础概率", "event_boost": "事件加成",
    "policy_boost": "政策加成", "max_chance": "概率上限", "severity_pivot": "严重度支点",
    "event_trigger_scale": "事件触发系数", "event_trigger_cap": "事件触发上限",
    "daily_planning": "每日排程", "anchor_minutes": "锚点粒度(分钟)",
    "random_delay_max_minutes": "随机延迟上限(分钟)", "autoregressive": "以昨天为底稿",
    "flexible": "弹性日程", "min_items": "最少条目", "max_items_": "最多条目",
    "max_time_shift_minutes": "最大挪动(分钟)", "min_gap_minutes": "最小间隔(分钟)",
    "allow_insertions": "允许插入新活动", "min_anchor_match": "锚点贴合下限",
    "spontaneity": "自发性", "base_thought_chance": "冒念头基础概率",
    "max_thought_chance": "冒念头概率上限", "social_boost": "社交加成",
    "low_self_control_boost": "自控力低加成", "stress_boost": "压力加成",
    "fatigue_boost": "疲劳加成", "hunger_boost": "饥饿加成",
    "impulse_activity_chance": "冲动行为概率", "random_action_chance": "随机行为概率",
    "max_override_bonus": "覆盖加成上限",
    "concurrency": "并行度", "day_routine_workers": "日程生成并发数",
    "external_rag": "外部信息注入", "bootstrap": "冷启动注入", "use_seed_script": "使用种子脚本",
    "only_when_empty": "仅在为空时", "profile_items": "画像条数", "web_items": "网络条数",
    "use_web_search": "使用联网搜索", "prefer_cached_news": "优先用缓存新闻",
    "max_chars_per_item": "单条最大字数", "runtime_absorb": "运行中持续吸收",
    "daily_quota_per_agent": "每人每日配额",
    # 环境 / 感知
    "local_physical": "本地环境感知", "crowd_busy_ratio": "拥挤阈值", "crowd_packed_ratio": "爆满阈值",
    "inject_into_perception": "注入感知上下文", "crowd_anomaly_ratio": "异常拥挤阈值",
    "crowd_anomaly_jump": "拥挤突增阈值",
    "anomaly": "异常判定", "intraday_threshold": "日内突发阈值",
    "distributed": "分布式中继", "cluster": "集群名", "node_id": "节点 ID",
    "local_agent_ids": "本地居民", "peer_agent_ids": "对端居民", "send_probability": "发送概率",
    "max_outbound_per_step": "每步最多外发", "max_inbound_per_step": "每步最多接收",
    "message_max_chars": "消息最大字数", "fail_fast": "失败即停", "relay": "中继客户端",
    "server": "中继服务端", "max_messages": "消息上限", "use_llm": "使用 LLM 生成",
    # 新闻
    "news": "新闻与检索", "sources_path": "源清单", "use_cache_first": "优先用缓存",
    "daily_chance": "每日阅读概率", "max_reads_per_day": "每日最多阅读",
    "memory_excerpt_chars": "写入记忆的摘录长度", "user_agent": "User-Agent",
    "info_seek": "主动检索", "base_daily_chance": "每日基准概率", "max_seeks_per_day": "每日最多检索",
    "preferred_sites_per_agent": "每人偏好站点数", "prefer_source_visit_ratio": "直访源站比例",
    "engines": "搜索引擎", "max_results": "结果条数", "content_timeout": "正文超时",
    "content_max_chars": "正文最大字数", "x_mcp": "X / MCP", "bearer_token_env": "Token 环境变量",
    "min_interval_seconds": "最小间隔(秒)", "cooldown_on_429_seconds": "429 冷却(秒)",
    "cache_ttl_seconds": "缓存 TTL(秒)", "contextual_keywords": "上下文关键词",
    "contextual_max_keywords": "关键词上限", "event_driven": "事件驱动检索",
    "max_extra_seeks_per_day": "每日额外检索上限", "stress_threshold": "压力阈值",
    "curiosity_threshold": "好奇阈值", "trigger_chance_on_event": "触发概率",
    # 干预
    "intervention": "推荐与干预", "recommendation": "推荐", "source_weights": "来源权重",
    "relational": "熟人来源", "personalized": "个性化来源", "headline": "头条来源",
    "exposure_control": "曝光抑制", "toxicity_threshold": "毒性阈值",
    "misinformation_threshold": "不实内容阈值", "suppression_factor": "抑制强度",
    "stance": "立场更新", "alpha": "惯性系数", "positive_keywords": "正面词",
    "negative_keywords": "负面词", "toxicity_keywords": "毒性词",
    "misinformation_keywords": "不实内容词", "objectives": "目标权重",
    "cross_viewpoint_weight": "跨观点权重", "engagement_weight": "互动权重",
    "toxicity_penalty_weight": "毒性惩罚权重", "misinformation_penalty_weight": "不实惩罚权重",
    # 人的真实性
    "interests": "兴趣与成长", "daily_insert_chance": "每日新增概率", "weekend_boost": "周末加成",
    "progress_minutes_per_step": "每步进度(分钟)", "evolution": "兴趣更替",
    "goals": "目标体系", "review_interval_days": "复盘间隔(天)",
    "event_review_severity": "事件触发复盘阈值", "max_life_goals": "人生目标上限",
    "max_long_term": "长期目标上限", "max_short_term": "短期目标上限",
    "max_daily_progress_delta": "单日进度上限", "review_log_keep": "复盘记录保留条数",
    "relevance_floor": "相关度下限", "relevance_cap": "相关度上限",
    "max_reviews_per_day": "每日复盘上限",
    "human_realism": "人的真实性", "max_extra_calls_per_agent_day": "每人每日额外调用上限",
    "max_episodes_per_agent": "每人经历上限", "daily_consolidation_top_k": "每日整理条数",
    "salience_threshold": "重要度阈值", "decay_half_life_days": "衰减半衰期(天)",
    "recall": "回忆", "base_top_k": "基础召回", "max_top_k": "召回上限",
    "planning_top_k": "计划时召回", "action_top_k": "行动时召回",
    "reflection_top_k": "反思时召回", "interview_top_k": "采访时召回",
    "surface_min_score": "浮现最低分", "effect_scale": "影响系数", "review": "回顾",
    "behavior": "行为动力学", "habit_learning_rate": "习惯养成速度",
    "habit_min_occurrences": "成为习惯的最少次数", "inertia_weight": "惯性权重",
    "decision_noise": "决策噪声", "fatigue_work_gain": "工作疲劳增速",
    "fatigue_sleep_recovery": "睡眠恢复", "self_control_recovery": "自控力恢复",
    "time_pressure_decay": "时间压力衰减", "commitment_weights": "承诺度权重",
    "high": "高", "medium": "中", "low": "低", "avoidance_bonus_scale": "回避加成系数",
    "need_weights": "需求权重", "energy": "精力", "hunger": "饥饿", "social_need": "社交",
    "dynamic_behavior": "动态行为",
    # 集成
    "extensions": "扩展钩子", "strict": "严格模式", "hooks": "钩子表",
    "collaboration": "协作会话", "sessions_dir": "会话目录",
    "max_concurrent_sessions": "并发会话上限", "max_context_events": "上下文事件上限",
    "step_retries": "步骤重试次数", "discussion": "讨论", "default_rounds": "默认轮数",
    "min_rounds": "最少轮数", "max_rounds": "最多轮数",
    "real_work": "真实工作执行", "queue_path": "任务队列", "artifacts_dir": "产物目录",
    "capabilities_cache": "能力缓存", "max_concurrent_tasks": "并发任务上限",
    "task_timeout_seconds": "任务超时(秒)", "tick_ingest_limit": "每 tick 摄入上限",
    "adapters": "适配器", "web_design": "网页设计", "code": "编码",
    "write_pytest": "同时写测试", "content": "文案", "teaching": "教学",
    "market": "接活市场", "seed_path": "种子文件", "store_path": "存储文件",
    "browse_top_k": "浏览条数", "max_taken_per_agent_per_day": "每人每日接单上限",
    "browse_probability_base": "浏览基础概率", "expire_after_sim_days": "过期天数",
    "auto_replenish": "自动补货", "replenish_threshold": "补货阈值",
    "external_hooks": "外部钩子", "webhook_url": "Webhook 地址", "mcp_server": "MCP 服务",
    # LLM
    "llm": "语言模型", "providers": "可用后端", "routing": "任务路由",
    "default": "默认后端", "tasks": "按任务指定", "model_name": "旧版模型名",
    "ollama_url": "旧版 Ollama 地址", "llm_timeout": "旧版超时(秒)",
    "authorization_scheme": "鉴权方式", "authorization_retry_schemes": "鉴权重试方式",
    "include_x_api_key": "附带 x-api-key",
    # 经济（与 site/dashboard/external.js 的标签表保持一致）
    "economy": "经济 / 货币系统", "currency": "币种",
    "tax": "个人所得税", "monthly_exemption": "月起征点",
    "default_special_deduction": "专项附加扣除", "brackets": "税率表 [上限, 税率, 速算扣除]",
    "social_insurance": "社会保险（个人缴纳比例）", "pension_rate": "养老", "medical_rate": "医疗",
    "unemployment_rate": "失业", "work_injury_rate": "工伤", "maternity_rate": "生育",
    "housing_fund_rate": "公积金（个人）", "housing_fund_employer_rate": "公积金（单位）",
    "base_cap": "缴费基数上限", "base_floor": "缴费基数下限",
    "spending": "消费", "engel_curve": "恩格尔曲线 [收入, 食品占比, 储蓄率]",
    "budget_template": "预算分配模板", "income_elasticity": "收入弹性", "daily_variance": "日波动",
    "investment": "投资", "asset_returns": "资产收益 [均值, 波动]", "portfolio_profiles": "组合画像",
    "auto_save_enabled": "自动储蓄", "checking_buffer_months": "活期缓冲月数",
    "market_correlation": "市场共同因子相关度",
    "credit": "信贷", "credit_limit_months": "授信月数", "annual_interest_rate": "年利率",
    "hardship_liquidity_months": "困难期流动性月数", "min_spend_factor": "最低消费系数",
    "macro": "宏观周期", "initial_inflation_rate": "初始通胀率",
    "initial_unemployment_rate": "初始失业率", "cycle_phase_duration_days": "阶段时长区间（天）",
    "phases": "阶段顺序", "phase_effects": "各阶段效应", "income_mult": "收入乘数",
    "expense_mult": "支出乘数", "layoff_risk": "裁员概率", "raise_chance": "涨薪概率",
    "industry_conditions": "行业景气度", "expansion": "扩张期", "peak": "顶峰期",
    "contraction": "收缩期", "trough": "谷底期",
    "conservative": "保守型", "moderate": "稳健型", "aggressive": "激进型",
    "shocks": "冲击事件", "layoff_base_prob": "裁员基准概率", "raise_base_prob": "涨薪基准概率",
    "medical_emergency_prob": "医疗急症概率", "medical_cost_range": "医疗支出区间",
    "year_end_bonus_enabled": "年终奖", "year_end_bonus_months": "年终奖月数",
    "economy.routing": "支付路由", "merchant_labor_share": "商户劳动分成",
    "landlord_share": "房东分成", "landlord_keywords": "房东关键词",
    "friend_loans": "熟人借贷", "max_outstanding_months": "最大未偿月数",
    "lender_buffer_months": "出借方缓冲月数", "willingness_factor": "出借意愿系数",
    "sectors": "部门池初始余额", "initial_firms_balance": "企业池",
    "initial_government_balance": "政府池", "initial_bank_balance": "银行池",
    "initial_savings_months_min": "初始存款下限（月）",
    "initial_savings_months_max": "初始存款上限（月）",
    "inheritance_enabled": "启用继承/家庭资产", "inheritance_base_probability": "继承基准概率",
    "inheritance_age_peak_low": "继承年龄峰值下限", "inheritance_age_peak_high": "继承年龄峰值上限",
    "inheritance_ratio_min": "继承倍数下限", "inheritance_ratio_max": "继承倍数上限",
    "inheritance_hukou_bonus": "户籍加成", "hours_per_step": "每步小时数",
    "work_days_per_month": "月工作日", "work_hours_per_day": "日工作小时",
    "rent_income_ratio": "房租收入比", "daily_utilities_cost": "日水电",
    "base_living_cost_per_hour": "基础生活成本/小时", "min_hourly_income": "最低时薪",
    "income_volatility": "收入波动", "target_work_hours_per_day": "目标工时",
    "asset_safety_days": "资产安全天数", "income_seek_threshold": "求财阈值",
    "income_seek_probability_scale": "求财概率系数", "income_seek_activities": "求财行为词",
    "expense_ranges": "各类支出区间",
    # 外部环境生成器
    "external_environment": "外部环境生成器", "max_events_per_tick": "每 tick 最多事件数",
    "generator": "生成方式", "history_days": "回看天数",
    "natural": "自然事件", "daily_weather_chance": "每日天气概率",
    "extreme_chance": "极端天气概率", "weather_states": "天气状态与权重",
    "extreme_events": "极端事件池", "economic": "经济事件",
    "daily_market_volatility": "市场日波动", "daily_market_drift": "市场日漂移",
    "market_news_threshold_pct": "行情播报阈值(%)", "macro_event_chance": "宏观事件概率",
    "macro_events": "宏观事件池", "political": "政策事件",
    "daily_policy_chance": "每日政策概率", "technology": "科技事件",
    "daily_tech_chance": "每日科技概率", "tech_events": "科技事件池",
    "intraday": "日内突发", "natural_shock_chance": "自然突发概率",
    "economic_shock_chance": "经济突发概率", "political_shock_chance": "政策突发概率",
    "technology_shock_chance": "科技突发概率",
    "environment": "旧版环境事件（兼容）", "event_chance": "事件概率",
    "natural_events": "自然事件池", "social_events": "社会事件池",
    "external_environment_service": "外部环境服务（客户端）",
    "fallback_to_empty": "不可用时降级为空",
    "environment_server": "外部环境服务（本机服务端）",
    # 家庭与户
    "family": "家庭与户", "overrides_path": "手工指定的家庭（文件）",
    "marital_status_bands": "婚姻状态分布（按年龄段）",
    "cohabitation": "未婚同居", "age_min": "起始年龄", "age_max": "结束年龄", "share": "比例",
    "pairing": "配偶匹配", "prefer_in_sim": "优先在仿真内配对",
    "in_sim_pair_share": "仿真内配对比例", "max_age_gap": "最大年龄差",
    "spouse_age_gap_mean": "夫妻年龄差均值", "same_district_bonus": "同区加权",
    "fertility": "生育", "p_any_child": "有孩子的概率（按年龄段）",
    "p_second_child": "生二孩概率", "p_third_child": "生三孩概率",
    "parent_age_at_first_birth": "初育年龄区间", "coresident_child_max_age": "子女同住年龄上限",
    "coresidence": "共居", "with_parents_local": "本地户籍与父母同住",
    "with_parents_migrant": "外地户籍与父母同住", "shared_rental_share": "合租比例",
    "multigen_base": "三代同堂基础概率", "multigen_with_young_child": "有幼儿时三代同堂概率",
    "young_child_max_age": "幼儿年龄上限", "elder_with_child_age": "老人投靠子女年龄",
    "elder_with_child_share": "老人与子女同住比例",
    "duties": "家庭责任", "school_age_max": "学龄年龄上限", "preschool_age_max": "学龄前年龄上限",
    "elder_care_age": "需照护的老人年龄",
    "family.finance": "家庭财务", "pooling_rate": "伴侣互助比例",
    "child_cost_monthly": "每孩月开销", "preschool_extra_monthly": "学龄前额外月开销",
    "elder_support_monthly": "赡养费（月）", "elder_support_min_age": "开始赡养的年龄",
    "coresident_elder_monthly": "同住老人月开销", "shared_rent_discount": "合租房租折扣",
    "spouse_bailout_enabled": "伴侣补现金缺口", "dual_income_security_bonus": "双职工安全感加成",
    "sole_earner_stress": "独自养家压力",
    "family.events": "家庭事件", "daily_probability": "每户每日事件概率",
    "contagion_enabled": "启用户内情绪传染", "contagion_weight": "同住传染强度",
    "remote_contagion_weight": "异地家人传染强度",
}


# ---------------------------------------------------------------------------
# Source-comment extraction
# ---------------------------------------------------------------------------


def _comment_maps(source: str) -> tuple[dict[int, str], dict[int, str]]:
    """Split a module's comments into standalone-line and trailing-inline maps."""
    standalone: dict[int, str] = {}
    inline: dict[int, str] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            text = tok.string.lstrip("#").strip()
            if not text:
                continue
            target = standalone if tok.line.lstrip().startswith("#") else inline
            target[tok.start[0]] = text
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}, {}
    return standalone, inline


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Section banners like "---- Tax ----" head a group; they read as noise in
    # a tooltip attached to one key.
    text = re.sub(r"^-{2,}\s*|\s*-{2,}$", "", text).strip()
    if len(text) > _MAX_HELP_CHARS:
        text = text[: _MAX_HELP_CHARS - 1].rstrip() + "…"
    return text


def _comment_for(lineno: int, standalone: dict[int, str], inline: dict[int, str]) -> str:
    """The comment block directly above ``lineno``, else its inline comment."""
    block: list[str] = []
    cursor = lineno - 1
    while cursor in standalone:
        block.append(standalone[cursor])
        cursor -= 1
    if block:
        return _clean(" ".join(reversed(block)))
    return _clean(inline.get(lineno, ""))


def _walk_dict(
    node: ast.Dict,
    prefix: str,
    out: dict[str, str],
    standalone: dict[int, str],
    inline: dict[int, str],
) -> None:
    for key_node, value_node in zip(node.keys, node.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        path = f"{prefix}.{key_node.value}" if prefix else key_node.value
        text = _comment_for(key_node.lineno, standalone, inline)
        if text and path not in out:
            out[path] = text
        if isinstance(value_node, ast.Dict):
            _walk_dict(value_node, path, out, standalone, inline)


@lru_cache(maxsize=1)
def source_help() -> dict[str, str]:
    """Extract ``path -> comment`` for every key literal in the settings fragments.

    Silently yields whatever it can: a parse failure in one module must not take
    down the whole 配置 panel, since the help text is a nicety and the values are
    not.
    """
    out: dict[str, str] = {}
    for _id, module, factory, _title, _help in SECTIONS:
        path = _SETTINGS_DIR / f"{module}.py"
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        standalone, inline = _comment_maps(source)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name != factory.__name__:
                continue
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict):
                    _walk_dict(stmt.value, "", out, standalone, inline)
    return out


# ---------------------------------------------------------------------------
# Public resolution
# ---------------------------------------------------------------------------


def help_for(path: str) -> str:
    """Help text for a dotted config path. Manual text wins over source comments."""
    if path in MANUAL_HELP:
        return MANUAL_HELP[path]
    return source_help().get(path, "")


def label_for(path: str) -> str:
    """Chinese label for a dotted config path, falling back to the raw key."""
    if path in LABELS:
        return LABELS[path]
    last = path.rsplit(".", 1)[-1]
    return LABELS.get(last, last)


def section_index() -> dict[str, str]:
    """Map every top-level CONFIG key to the section id that owns it."""
    index: dict[str, str] = {}
    for section_id, _module, factory, _title, _help in SECTIONS:
        for key in factory():
            index.setdefault(key, section_id)
    for section_id, keys in SECTION_EXTRA_KEYS.items():
        for key in keys:
            index.setdefault(key, section_id)
    return index


def section_meta() -> list[dict[str, str]]:
    """Ordered section descriptors for the panel's navigation."""
    return [
        {"id": section_id, "title": title, "help": help_text}
        for section_id, _module, _factory, title, help_text in SECTIONS
    ]


__all__ = [
    "LABELS",
    "MANUAL_HELP",
    "SECTIONS",
    "help_for",
    "label_for",
    "section_index",
    "section_meta",
    "source_help",
]
