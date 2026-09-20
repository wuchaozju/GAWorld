# 家庭系统设计（Family / Household Subsystem）

> 代码：`gaworld/family/`；配置：`CONFIG["family"]`（`gaworld/settings/family.py`）；
> 手工指定的家庭：`data/family_overrides.json`（`gaworld/family/overrides.py`）。
> 面板：配置 → 家庭与户、主面板「家庭结构」卡片、智能体工作台第 5 步的家庭编辑面板
> （后端 `gaworld/apps/family_api.py`）。
> 测试：`tests/test_family{,_integration,_overrides}.py`、`tests/test_dashboard_family.py`、
> `site/dashboard/{family-card,studio-family}.test.js`。

## 1. 为什么要做

改动之前，仿真里**所有 51 个 agent 事实上都是单身**：

- `data/hangzhou_profiles_with_names.md` 里几乎没有婚育描述（全文只有 1 处相关词）；
- `build_agent()` 没有任何家庭字段，agent dict 里不存在"家人"这个概念；
- `gaworld/social/network.py` 虽然有 `spouse` / `child` / `parent` 这些 kin 角色，
  但它们只出现在 **每个 agent 各自 LLM 生成的"场外 ghost 名单"** 里。
  这套名单的确定性 fallback `_heuristic_ghosts()` 只播种"父母 + 兄弟姐妹 + 老同学"，
  **从不生成配偶或子女**；而且 A 的配偶和 B 没有任何关系——家庭在全局是不一致的；
- 每个 agent 的 `locations["home"]` 独立分配，经济模块每人一本独立账本：
  **没有共居，没有共同预算**。

`gaworld/population/` 里已有一套真正的户（household）合成器，但它只服务合成人口和
group 模式，主仿真用不到，而且它产出的只是一张亲属边的图，不涉及日程、钱和事件。

## 2. 采用的模型：混合（in-sim 配对 + 场外补齐）

| 方案 | 取舍 |
|---|---|
| 只在仿真内配对 | 最真实的互动，但 51 人异质抽样能配成的家庭很少，多数人仍单身 |
| 只做场外 ghost 家庭 | 改动最小，但家人不会作为独立个体行动 |
| **混合（已采用）** | 年龄/居住区匹配得上的配成 in-sim 夫妻（共居、可互动、情绪互相传染），配不上的由全局一致的 household 注册表补场外家人 |

关键诚实声明写在 `pairing.in_sim_pair_share`（默认 `0.6`）的注释里：
**从 1200 万人的城市里抽 51 个人，他们互为夫妻的真实概率约等于 0**。
在仿真内配对是为了买到"家庭内互动"这个建模收益，不是人口学事实。
想要人口学纯净的跑法，把这个值调到 `0.0`，所有配偶都会变成场外 ghost。

## 3. 分配算法（`gaworld/family/assign.py`）

顺序刻意是**先状态、后结构**：

1. **婚姻状态**：按 `年龄段 × 性别` 的四类分布（未婚/已婚/离异/丧偶）采样；
2. **配对**：已婚（和未婚同居）的 agent 之间做确定性贪心匹配
   （年龄差 ≤ `max_age_gap`，同区加分，配额由 `in_sim_pair_share` 控制），
   剩下的人生成场外配偶；
3. **子女 → 同住长辈**：依赖已经建成的夫妻；
4. **家庭类型是读出来的，不是选出来的**。

第 4 点是重点。`gaworld/population/network.py` 用很长的注释记录过一个失效模式：
先按"户型占比"旋钮规划户数、再往里填人，一旦户型旋钮和年龄金字塔打架，
就会有一方**静默地输掉**（要 26% 核心家庭、但镇上只有 80 个小孩，
于是家庭户饿死、剩下的成年人全变独居户）。这里把顺序反过来：
八种户型（独居/合租/与父母同住/未婚同居/夫妻二人/核心家庭/单亲/三代同堂）
是分配结果的**读数**，因此不可能和任何东西矛盾。

**确定性**：每次随机抽取都来自 `Random(f"{seed}::{agent_id}::{stream}")` 的具名子流
（和 `gaworld.population.synth.derive_rng` 同样的理由）。加一个 agent、
或者调生育率旋钮，**不会**把其他人的婚姻重新洗牌。

**父母**：所有人都有父母。同住的父母在建户时产生；不同住的父母由 `_attach_remote_parents`
补齐，按父母的推算年龄抽存活率。键名沿用 `g_father` / `g_mother`——
和场外名单 bootstrap 用的是同一套键，所以两边说的是**同一个人**而不是两个人。

## 4. 落到"生活"的四层

### P0 结构与关系（`ties.py`）

家庭不是另一张社交图，而是现有社交图里最强的那部分。所以家庭关系写成
`gaworld.social.network.ensure_relationship_schema` 认识的普通关系记录，
kin 角色自动继承那个模块的衰减率、义务基线和 Dunbar 保护。

已有关系只会被**加强不会被降级**：一个既是配偶又是社交邻居的 agent，
保留仿真已经挣到的 closeness，只补上角色、渠道和义务下限。

`reconcile_ghost_kin()` 负责清理矛盾：LLM 生成的场外名单会给一个
按人口学判定为单身的 agent 编一个配偶，也会给已经 in-sim 结婚的人编第二个配偶。
**一个关系字典里有两个互相矛盾的配偶，比没有配偶更糟**，所以这类 ghost 被删除
（只删 `spouse/partner/child/ex/roommate` 这几个本模块拥有的角色；
编出来的母亲、老同学不动）。同时 `_build_backstory_prompt` 也会把家庭状况告诉 LLM——
prompt 省 token，代码保证一致性。

新增了一个 `roommate` 角色到 `ROLE_CONFIG`：合租是杭州年轻租客的默认居住形态，
而室友是一个单身 agent 在家里唯一会见到的人。

### P1 共居与家庭日程（`duties.py`）

- **共居**：同户的 in-sim agent 共享同一个 `locations["home"]` 节点。
  这一步是"家庭"和"两个地址相同的陌生人"的分界线——共享 home 之后，
  现有的 co-location 循环才会真的产生家庭互动。
- **日程**：`daily_duties()` 产出中文责任短语（接送幼儿园、陪写作业、照料同住老人、
  给父母打电话、和伴侣一起吃晚饭……），区分工作日/周末，按同住人口生成。
- **`care_load()`** 是 0..1 的照护负担标量，供状态层和财务层消费——
  "两个小孩加一个 80 岁老人"要真的花掉时间、钱和情绪，而不只是出现在叙述里。
  有同住伴侣时负担乘 0.62（分担），单亲全额承担。

### P2 家庭共同财务（`finance.py`）

现有经济模块把"一个 agent = 一张资产负债表"，这对家庭恰好是错的：
父母的可支配收入不是工资减去自己的消费，而是刨掉孩子之后剩下的；
夫妻不会一个一个地陷入财务困境。

两个机制，**都守恒**（本仓库的货币系统逐元记账）：

- `charge_dependants()` 通过经济模块自己的支出路径给家庭记账（教育 / 医疗两个类目），
  钱像普通消费一样进入 firms 池。为此在 `gaworld/economy/finance.py` 新增了一个
  公开入口 `charge_external_expense()`。
  分摊按**收入**而不是余额：挣两倍的人担两倍，不挣钱的伴侣不担。
- `settle_couple()` 在两个 in-sim agent 的账户之间转账——纯转移，总额不变。
  注意这是"互相补窟窿"而不是"合并账户"：更接近中国城市夫妻实际的理财方式，
  也对经济模块其他部分的扰动最小。

共享/分摊的边界很讲究：夫妻**共享**子女和同住的老人
（两人的记录里是同一批 ghost，重复计算会让学费翻倍），
但**各自**赡养自己的父母，所以赡养费按人求和。

### P3 家庭事件与情绪传染（`events.py`）

两种机制，容易混淆，这里明确分开：

- **事件**是离散且**共享**的。孩子发烧是**一个**事件，同一个 tick 同时落到父母两人身上——
  这正是现有的按 agent 独立生成的 ghost 事件表达不了的东西，也是"家庭值得建模成户
  而不是 profile 上的装饰"的根本理由。事件被投递进现有的人生事件队列
  （`agent_ids` 带上全部同住成员），因此免费继承记忆写入、余波衰减和面板时间线。
  模板按家庭构成 gating：没有孩子的 agent 抽不到"孩子发烧"。
- **传染**是连续且不对称的。作为**收敛项** `w * (对方 − 自己)` 施加：
  一个人人都平静的家不会凭空产生漂移；同住的权重比异地家人高一个数量级。

## 5. 钩子接线（`plugin.py`）

| 钩子 | 做什么 | 为什么是这个点 |
|---|---|---|
| `agents.built` | 建户、写 `agent["family"]`、共享 home | 必须在任何东西读 agent 之前；也是改写 `locations["home"]` 唯一安全的时刻（还没人移动） |
| `on_simulation_start` | 写入亲属关系边、清理矛盾 ghost | `agents.built` 之后仿真会**重置/重载** `agent["relationships"]` 再去问 LLM 要场外名单；写早了会被静默丢弃 |
| `on_day_start` | 投递家庭事件 | 事件在当天 tick 中被 drain |
| `on_day_end`（priority `-10`） | 家庭记账、伴侣补窟窿、预算算**明天**的家庭责任 | 经济插件 priority 0，家庭要在它结完账之后；日程是在 `on_day_start` **之前**生成的，所以责任要提前一天算好 |
| `perception.sections` | 家庭状况 + 此刻谁在家 | 只影响感知 prompt 内部段落，不污染环境上下文 |
| `state.effects` | 户内情绪传染 | 在社会影响与状态更新之前 |

插件是**降级而不是失败**：没有经济运行时就不记账，没有事件队列就不发事件，
家庭仍然出现在 prompt 和关系里。`requires` 故意留空——声明依赖会让缺少经济模块时
整个插件被停用，那是拿一个能用的功能去换一个严格的边界。

## 6. Web 界面

四处，按"必要性"而不是"好看"来选的。

### 6.1 配置面板：家庭与户（必须）

`site/dashboard/settings.html` 不是手写的，它由 `gaworld/settings/config_docs.py` 的
`SECTIONS` 注册表生成，tooltip 由一次 AST 遍历从 `gaworld/settings/*.py` 的注释里抽出来。
**把配置片段加进 `defaults.py` 却不注册到 `config_docs.py`，结果是整个子系统在浏览器里
完全不存在**——从 Python 看一切正常。所以 `family` 注册成独立分区，
并为操作者真正会去拧的旋钮写了中文 `MANUAL_HELP`（源码注释是英文的，
半中半英的分区读起来像 bug）。

`tests/test_dashboard_family.py::test_every_config_fragment_has_a_panel_section`
是这条的回归闸：**任何**没被分区认领的顶层配置键都会让它失败，
下一个人加子系统时不会再踩同一个坑。

保存路径不需要额外工作：`settings_api.save_config` 按有效配置逐键强制类型，
`family` 现在在 `build_default_config()` 里，连 `p_any_child` 这种"列表套字典"
也能原样往返（有测试锁着）。

### 6.2 主面板「家庭结构」卡片

在「人物设定」旁边，两段：

- **概览**：户数 / 仿真内夫妻数 / 有子女人数 / 单身占比，加一条户型分布条。
  单身故意显示成 `14/51` 而不是 `14`——光一个数会被读成"14 户"。
- **详情**：跟着当前选中的居民走。婚姻状态与户型标签、家庭叙述、
  同住成员与不同住的家人分两组列出（同住的左边有绿色竖条），
  以及这一轮累计的养育/赡养支出。

数据来自 `GET /api/family/overview`（`gaworld/apps/family_api.py`，
沿用 `population_api` 的委托模块惯例，`dashboard_server.py` 只加四行转发）。
它读的是 recorder 落盘的 `output/records/family.{summary,household,agent}.jsonl`，
**不在请求时重新推导**：重新推导需要模拟器内存里的名单，而且一旦配置在开跑之后改过，
面板显示的家庭就会和 agent 真正生活在其中的那个家庭不一致——
显示"另一个家"比显示"上一轮的家"更糟。

图表照例是手写的（这个目录没有构建步骤，引 CDN 图表库会让面板失去离线可用性）。

### 6.3 智能体工作台 → 社交·关系：家庭编辑面板

这一块和前两块有个本质区别，值得先说清楚：

**家庭在每次运行开始时按 (名单, 配置, 种子) 重新推导。** 所以在工作台里的编辑
**不能是"改结果"**——`on_simulation_start` 会把 `relationships` 覆盖掉，
编辑会在第二天早上凭空消失。面板写的是**覆盖项**（`gaworld/family/overrides.py`，
落到 `data/family_overrides.json`），分配器在**分配过程中**读取它。

覆盖项放在 `data/` 而不是 `output/`：一份被刻意指定的家庭是**源数据**，
和 profile 是一个性质，不是运行产物。

能编辑的四层：

| 项 | 三态语义 |
|---|---|
| 婚姻状态 | 空 = 按年龄段抽样；否则固定为未婚/已婚/离异/丧偶 |
| 伴侣 | 自动 / **无伴侣**（即使状态是已婚也不生成）/ 指定一位仿真内居民 / 填一个场外人物 |
| 子女 | 未勾选 = 按生育率抽样；勾选后空列表 = **固定为没有孩子**；否则逐个指定 |
| 同住长辈 | 同上 |

**三态是承重的**：`null`（抽样）和 `[]`（固定为没有）必须区分开。
把两者合并，"这对夫妻没有孩子"就会被静默变成"给他们生几个"，
而操作者要等一次运行之后才发现。前端的 `familyDraftToOverride` 和后端的
`normalize_override` 两侧都有测试锁着这一点。

**指定仿真内配偶是对另一个人的声明**，所以：双向生效、两人共享住处、
原本和对方配对的居民自动退回场外配偶（有测试）、并且**绕过年龄差限制**
（操作者是在故意覆盖人口学，匹配器不该偷偷否决）。两条互相矛盾的指定
按 agent id 从小到大解析，`cross_check()` 把冲突显式报到面板上——
静默地丢掉一条比报错更糟。

踩到并修掉的一个坑：指定**场外**配偶时，agent 仍然留在贪心匹配池里，
于是被匹配给了仿真内的另一个人，覆盖被静默忽略。现在这类 agent 也会退出匹配池。

面板读的是 `GET /api/family/preview`——它**故意重新推导**，
和 6.2 的卡片刚好相反。两者问的不是同一个问题：卡片问"这一轮跑的是什么家庭"，
编辑器问"我保存之后，下一轮会变成什么"。盲改、隔一天才发现，
正是编辑面板存在的理由。

### 6.4 文档面板

`site/dashboard/docs.js` 的清单是手写数组，加了本文档。
`tests/test_dashboard_docs.py` 会验证清单里每个路径都真实存在。

### 6.5 测试

- `tests/test_dashboard_family.py`（21 项）：配置分区回归闸、tooltip 中文覆盖、
  保存往返、API 的空/正常/重跑追加/脏行/404 各条路径、前端接线与转义。
- `site/dashboard/family-card.test.js`（6 项，`node --test`）：把卡片那段代码
  切出来配桩 DOM 跑一遍——Python 测试读得到 `app.js` 但跑不了它，
  渲染函数里的崩溃或漏转义只有这层能看见。居民名字来自可编辑的 profile，
  是不可信文本，所以专门有一条 XSS 用例。
- `tests/test_family_integration.py::test_the_dashboard_api_can_read_what_the_run_recorded`：
  真跑一轮再用 API 读，**把"插件写出来的形状"和"面板期待的形状"对上**——
  两边各自的单元测试都绿、面板却空白，是这类改动最典型的失败方式。
- `tests/test_family_overrides.py`（25 项）：覆盖层。最重要的不是"存下来了"，
  而是**存下来的东西挺过了重新分配**——包括被抢走配偶的人仍然有配偶、
  固定的长辈不会额外再多一对异地父母、以及一次指定不会把全城重新洗牌。
- `site/dashboard/studio-family.test.js`（10 项，`node --test`）：编辑器的
  草稿 ↔ 线上格式往返（尤其是三态）与渲染转义。

### 6.6 没做

没有独立的「家庭」console tab（户列表、关系图、事件时间线）。
家庭结构本来是张图比表格好读的东西，但那是另一个 Population Studio 量级的工作。

⚠️ **面板没有在真实浏览器里点过**——dashboard server 在沙箱、浏览器在本机，网络不通。
交互路径需本地 `python -m gaworld.apps.dashboard_server` 手工验证。

## 7. 对既有代码的改动（尽量小）

| 文件 | 改动 |
|---|---|
| `generative_city_sim.py` | 三处 prompt 的 `profile_text` 各加一行「家庭状况」；daily-routine prompt 加 `{family_duty_text}` 段和一条要求；周末改写 prompt 加一条要求 |
| `gaworld/economy/finance.py` | 新增公开函数 `charge_external_expense()` |
| `gaworld/social/network.py` | `ROLE_CONFIG` 增加 `roommate`；场外名单 prompt 增加 `family` 字段与"不要另编配偶/子女"的约束 |
| `gaworld/settings/defaults.py` | 装配 `family_settings()` |
| `gaworld/settings/config_docs.py` | 注册「家庭与户」分区 + 中文标签与 tooltip |
| `gaworld/plugins/__init__.py` | 注册 `FamilyPlugin`（排在 `EconomyPlugin` 之后） |
| `gaworld/apps/dashboard_server.py` | `RECORDS_DIR` 常量 + `/api/family` 的 GET/POST 转发 |
| `site/dashboard/{index.html,app.js,styles.css,docs.js,locales/*}` | 家庭卡片 + 文档清单条目 + 中英文案 |
| `site/dashboard/{studio.js,studio.css}` | 工作台第 5 步的家庭编辑面板 |

`agent["family"]`（渲染好的一行家庭叙述）放在顶层，和 `personality` / `daily_life`
并列——它是 prompt 会渲染的 **profile 属性**，不是插件账本；
结构化账本在 `agent["ext"]["family"]` 里。

## 8. 常用旋钮

```python
CONFIG["family"]["enabled"] = False                      # 整个关掉，回到全员单身
CONFIG["family"]["pairing"]["in_sim_pair_share"] = 0.0   # 人口学纯净：配偶全在场外
CONFIG["family"]["fertility"]["p_any_child"] = [...]     # 低生育率政策实验
CONFIG["family"]["events"]["contagion_weight"] = 0.0     # 关掉户内情绪传染
CONFIG["family"]["finance"]["enabled"] = False           # 只要关系和日程，不要记账
CONFIG["family"]["seed"] = 20260813                      # 换一批家庭
# data/family_overrides.json：工作台里手工指定的家庭，优先于抽样；删掉即全部恢复自动
```

## 9. 已知边界

- **同性伴侣未建模**：配对只在异性之间进行，配不上的人退化为场外配偶而不是被迫单身。
- **家庭结构在一次 run 内是静态的**：没有结婚/离婚/生育改变 household 的动态过程。
  `family_child_*` 之类的事件只是事件，不会真的往户里加人。
  这是 P4 的事（要接 `remove_agent` 那类日边界变更机制）。
- **子女和长辈始终是 ghost**：他们不进认知管线，没有自己的日程。
  他们通过责任、开销和事件影响 agent，但不会自己去上学。
- **`in_sim_pair_share` 是建模旋钮不是事实**（见 §2）。
- 户型占比是分配的**结果**，因此不能直接对着一份户型统计表标定；
  想改户型分布，改的是婚姻/生育/共居这三组旋钮。
