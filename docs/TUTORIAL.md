# GAWorld 用户教程

本教程面向第一次使用 GAWorld 的用户，目标是让你在 10 分钟内完成一次可复现的仿真运行。

## 1. 准备环境

建议使用 Python 3.10+。

在项目根目录执行：

```bash
pip install -r requirements.txt
```

## 2. 配置 LLM（必须）

GAWorld 运行时需要至少一个可用的 LLM Provider。请先编辑 `config.py`，并选择一种方式：

1. 本地 Ollama（离线/本地模型）
2. OpenAI（云端）
3. Anthropic 兼容接口（云端或代理）

如果使用 OpenAI 或 Anthropic，请先设置环境变量：

```bash
export OPENAI_API_KEY="your_key_here"
# 或
export ANTHROPIC_API_KEY="your_key_here"
```

然后在 `config.py` 中让 `routing.default` 指向你已配置完成的 provider（例如 `openai_gpt` 或 `ollama_qwen`）。

## 3. 第一次运行仿真

```bash
python generative_city_sim.py run
```

运行后会在 `output/` 下生成日志、记忆和图表。

想跑**长期模拟**（如 60/600 天）可加 `--fast-forward` 开启**长时段快进**：每天压缩成每个智能体一条日简报（每 agent 每天 1 次 LLM 调用），跳过日内时刻循环，状态/目标/关系仍近似推进。`long_run.randomness`（0–1）越高，突发事件越频繁、波动越大：

```bash
python generative_city_sim.py run --sim-days 600 --fast-forward
```

要跑**数年到数十年**，把一步做大——一个月或一整年压缩成每人一条阶段简报。调用量按**步数**算而不是天数：50 人跑 10 年，按年 500 次，按天 18.25 万次。

```bash
python generative_city_sim.py run --sim-years 10       # 一年一步
python generative_city_sim.py run --sim-months 24      # 一个月一步
```

（Dashboard 工具栏也可勾选「长时段快进」、选「步长单位」并拖动「随机性」滑杆；选月/年后左边的时长字段会变成「仿真月数 / 仿真年数」。详见 [TUTORIAL.v2 §3.1](./TUTORIAL.v2.md#31-长时段快进fast-forward跑-10--60--600-天) 与 [§3.2](./TUTORIAL.v2.md#32-大跨度模拟以月年为时间单位)。）

重点查看：

- `output/logs/`：运行日志
- `output/memory/`：Agent 记忆与状态
- `output/memory/agent_<id>_growth.json`：Agent 的兴趣爱好、计划发展技能和练习进度
- `output/state/agent_state_history.csv`：状态时间序列
- `output/intervention/intervention_metrics.csv`：PolicySim 风格干预指标
- `output/network/social_network.png`：社交网络图

## 4. 重置并重新开始

如果你改了关键配置（如记忆模型版本）或想从 Day 1 重新开始：

```bash
python generative_city_sim.py reset
```

再执行：

```bash
python generative_city_sim.py run
```

## 5. 访谈单个 Agent

直接提问：

```bash
python generative_city_sim.py interview --agent-id 31 --question "你今天为什么选择这个行动？"
```

批量问题（每行一个问题）：

```bash
python generative_city_sim.py interview --agent-id 31 --questions-file questions.txt
```

## 6. 注入外部信息（可选）

给某个 Agent 添加一条外部知识：

```bash
python generative_city_sim.py rag-add \
  --agent-id 31 \
  --text "周末更倾向于骑行和逛书店" \
  --timestamp "2026-02-18 09:30" \
  --source "manual"
```

从文件导入：

```bash
python generative_city_sim.py rag-import \
  --agent-id 31 \
  --file output/test_extra_info.txt \
  --source "profile_notes"
```

## 7. 事件对照实验（推荐）

在“有事件/无事件”两条分支并行运行并比较：

```bash
python generative_city_sim.py compare-event \
  --event-name "临时交通限行" \
  --event-description "主干道限行导致通勤时间上升并影响出行决策" \
  --event-day 2 \
  --event-time 09:00 \
  --sim-days 3 \
  --llm-provider openai_gpt \
  --seed 42
```

输出会写入 `output/comparisons/<时间戳_事件名>/`。

重点查看：

- `comparison_summary.md`：常规状态指标和 PolicySim 干预指标摘要
- `comparison_metrics.csv`：所有指标的 baseline / event / delta 明细
- `with_event/intervention/intervention_metrics.csv`：有事件分支的干预评估时间序列
- `without_event/intervention/intervention_metrics.csv`：无事件分支的干预评估时间序列

默认干预评估不会调用额外 API。它会在每个 step 构造关系推荐、个性化推荐和公共议题 feed，
再记录 `stance_score`、`toxicity_score`、`misinformation_risk`、
`cross_viewpoint_exposure` 和 `intervention_reward`。

### 7.1 两个以上分支：平行世界

要比的不止"有 / 无"，而是**几种强度**，或者想知道两段历史**从哪一步开始**分开，
就用平行世界——一次实验最多 8 个世界，共用同一批居民和同一个种子，只有事件不同：

```bash
python generative_city_sim.py parallel-worlds --spec worlds.json
```

控制台「**平行世界**」页签是它的交互式版本：左边加世界、加事件，右边看分叉图、
逐指标走向、偏离曲线和「谁被改变了」。已有的 `compare-event` 结果也会自动出现在那里。

⚠️ 做结论前先跑一个**安慰剂世界**（一个没有实质影响的事件）量出噪声底噪——
LLM 驱动的认知有随机性，配置相同的两个世界也不会跑出完全相同的历史。
完整教程见[平行世界教程](PARALLEL_WORLDS_TUTORIAL.md)。

## 8. 生成新城市地图（可选）

```bash
python scripts/generate_citymap.py --description "a small city with about 1000 residents, in east china"
```

默认会更新 `data/citymap.md`。

## 9. 常见问题

1. 报错 API key 缺失  
请检查环境变量是否设置，且 `config.py` 使用了对应 provider。

2. 运行很慢  
在 `config.py` 中降低 `sim_days`、减少 `agent_ids`，或减少额外 LLM 调用配置。

如果只想关闭干预评估，在 `config.py` 中设置 `intervention.enabled = False`。

如果只想关闭兴趣爱好与技能成长系统，在 `config.py` 或 `dashboard_config.json` 中设置 `interests.enabled = False`。

3. 修改配置后行为异常  
先执行 `python generative_city_sim.py reset`，再重新运行。

## 10. 一条最短上手路径

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your_key_here"
python generative_city_sim.py run
```

如果你只想先验证流程可跑通，按上面 3 条命令执行即可。

## 11. 想模拟几百人？

上面的个体模式适合几十个 agent。人口上到几百，每天的 LLM 调用会变成十万量级，
这时用**群体模式**：把人口划分成群体，每群每天只花 1 次 LLM 调用，
同时每天挑一小批个体按完整保真度运行。

```bash
# 造一座 500 人的小镇（不写文件，只看结果）
python -m gaworld.population --preset cn_county_town --size 500 --seed 42 --check

# 按群体模拟 7 天（零 LLM 成本）
python -m gaworld.group --size 500 --days 7 --no-llm

# 验证这个近似能回答哪类研究问题
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7
```

第三条是关键：群体模式**不是**对所有研究问题都适用，验证门会直接告诉你哪类能答、哪类不能。
Dashboard 里对应「人口与群体」页签。完整教程见
[群体模拟教程](GROUP_SIMULATION_TUTORIAL.md)。

## 12. 想改的不是某个人，是整个世界？

通胀几个点、政府池有没有钱、今天下不下雨、外部信息从哪来——这些都不属于任何一个 agent，
但往往正是实验里你要操纵的东西。

```bash
python generative_city_sim.py dashboard --port 8766
# http://127.0.0.1:8766/console → 「外部系统」页签
```

三个子面板（货币系统 / 外部环境 / 对外服务）都是左边观察、右边编辑。要分清两种"改"：
改**配置**下一次运行才生效，适合做对照实验；排一条**干预**则由跑着的仿真在下一个日边界
消费，适合临时制造一次衰退或财政刺激。完整教程见
[外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md)。

## 13. 想让居民有家庭？

默认就有。跑起来之后控制台会打印 `👪 家庭结构已生成：…`——按年龄段抽出来的婚姻状态，
匹配得上的居民在仿真内配成夫妻并共享同一个住处，配不上的补场外家人，
子女和同住长辈随之生成。家庭会进日程（接送、陪写作业、回家吃晚饭）、
进账本（育儿与赡养开销）、也会以整家为单位发生事件。

想改整体分布（婚配率、生育率、共居比例），去 Dashboard 的「配置」→「家庭与户」；
想精确指定某个人的家庭（"让 12 号和 27 号是夫妻，有一个 5 岁女儿"），
去「Agent Studio ↗」第 5 步「社交 · 关系」。后者写成覆盖项，跨运行生效。

⚠️ 日程有缓存：改完家庭想看到日程真的变化，先 `reset` 再 `run`。

完整说明见[完整教程 5.7 节](TUTORIAL.v2.md#57-家庭与户)与[家庭系统设计](FAMILY_DESIGN.md)。

## 14. 想让居民有性格？

默认就有。每位居民带一组**离线生成好的**大五（OCEAN）人格分，运行时只读
`data/agents_big5.csv`，**一次运行内不漂移**。它通过三条可分别开关的通道起作用：

- `rules`：动作选择里多一个「性格倾向」权重项，并微调打断阈值、自发冲动、搭话概率、
  决策噪声、消费/储蓄倾向，还给情绪加一条属于个人的基准线（确定性、零 token）；
- `prompt`：把人格写成第二人称的行为锚句，注入日程、日内活动调整、目标推导、
  新闻反应四类提示词——只写行为，不写数字和维度名；
- `voice`：同样的锚句只进日记提示词，用来把"文风变了"和"决策变了"分开归因。

想做对照组，把 `personality.strength` 设成 `0`：人格数据还在，但不起作用；
整个关掉是 `personality.enabled = False`。没有人格数据的 agent、或被关掉的通道，
行为与加这个子系统之前逐位一致。本次运行实际生效的分数写在
`output/traits/agent_traits.csv`。

人格分是一次性的离线产物（没有这份文件时会退回人群先验采样）。
生成的方向是**先采样五维分数，再据此写人物设定里的行为描述**——
从「性格与情绪特征」那段文字反推分数的老做法不成立：那段中位数只有 20 字，
而五个个体级状态变量就写在同一份 profile 里，反推出来的只是那几个数字的回声。

```bash
python scripts/author_personality.py --agents 1-5 --dry-run   # 看提示词与采样分数，不花钱
python scripts/author_personality.py --agents 1-5             # 试水，写 output/traits/authored_preview.md
python scripts/author_personality.py --apply                  # 全量，自动备份 .v1.md，写 md + CSV
python scripts/big5_collinearity.py --annotate                # 必跑：标出与已有状态变量重叠的维度
python scripts/big5_effect_ceiling.py                         # 复核幅度
```

`--apply` 会把旧语料备份到 `data/hangzhou_profiles_with_names.v1.md`，
并给每份 profile 加一个 `人格与行为倾向` 字段；提示词里从此渲染这一段，
而不是旧的「性格与情绪特征」行（两者对 9 位居民自相矛盾）。
`scripts/calibrate_big5.py` 还在，用于给外部导入的 agent 打分、以及作对照组校验打分器。

当前语料下五个维度**全部 51/51 有分**，共线性最差调整 R² 为 0.05（此前 0.77 不合格），
五维的效应都可以单独立论。人物设定没描述到的维度会取**恰好 0**（无倾向、也不会写进提示词），
和闸门标出的「与已有变量重叠」的维度一起，在每次运行启动时打印出来——
当前语料两类都是空的。

完整说明见[完整教程 5.8 节](TUTORIAL.v2.md#58-大五人格)。

## 15. 想扩展 GAWorld？

所有子系统都运行在微内核插件接口上：写一个 `gaworld.kernel.Plugin`
子类 + `CONFIG["plugins"]` 一行声明即可加新子系统，不用改核心代码；
认知管线（感知 → 计划 → 行动 → 反思等 12 阶段）的消融与定制也只是
改 `CONFIG["pipeline"]`。完整指南见
[插件作者指南](PLUGIN_AUTHORING.md)与[完整教程第 18 章](TUTORIAL.v2.md#18-微内核插件架构扩展-gaworld)。
