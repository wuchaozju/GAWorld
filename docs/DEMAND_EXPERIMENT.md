# 需求估计提示词实验

**模块**：`gaworld/experiments/` · **CLI**：`python -m gaworld.experiments` · **测试**：`tests/test_experiments_demand.py`

复现 Gui & Toubia (2025)《The Challenge of Using LLMs to Simulate Human Behavior: A Causal
Inference Perspective》(arXiv:2312.15524) 的需求估计实验，并加入两个只有 GAWorld 能跑的
**智能体 arm**。

---

## 1. 论文在讲什么

盲化（blinding）是人类实验的常规做法：被试不知道自己在实验里。但 LLM 被试和它所处的情境
是**被提示词当场造出来的**——当研究者不指定"上次买这个东西花了多少钱""旁边竞品多少钱"时，
模型会拿它唯一能看到的线索去补全这些空白，而那个线索恰恰是**被随机化的处理变量**。

结果：价格一动，本应固定的前处理变量跟着动，unconfoundedness 被破坏（论文 Figure 1），
需求曲线变成倒 U 而不是单调下降（Figure 2）。

把协变量写进提示词能减轻混淆，但会引入 focalism：被明确点出来的变量变得人为显著，
模拟出的顾客退化成"价格 ≤ 竞品价就买"的阶跃函数（Figure 4），生态效度崩掉。

论文给出的解法是 **unblinding**：在 system prompt 里直接说明随机化设计和价格的抽取分布。

## 2. 五个 arm

| arm | 被试 | 协变量来源 | 对应论文 |
|---|---|---|---|
| `blind` | 无 | 无 | Prompt 5 + Prompt 1/2，基线 |
| `covariate` | 居民（仅人口学） | **写进提示词**（收入、竞品价、上次价） | §3 / Figure 3–4 |
| `unblinded` | 无 | 无 | Prompt 6 |
| `agent` | GAWorld 居民 | **世界状态**（记忆价、货架竞品价、预算压力） | 本项目新增 |
| `agent_unblinded` | GAWorld 居民 | 世界状态 | 本项目新增 |

`agent` 与 `covariate` 拿到的是**同一批数值**，区别只在进入决策的通道：

- `covariate`：`你的基本情况：…，月收入约 7403 元。同一货架上竞品价格是 35.52 元。`
- `agent`：`你记得上次在这里买它花了 32.84 元。旁边的百事可乐标着 35.52 元。这个月手头有点紧。`

预算永远以**定性短语**出现（`gaworld/experiments/arms.py::_budget_phrase`），不给数字——
一旦给了数字，模型就会拿它跟价格做算术，那正是 focalism 失败的样子。

## 3. 关键的识别性质

`world_context(subject, product, seed)` **签名里没有价格**
（`gaworld/experiments/subjects.py`）。随机数流的 key 是 `seed:ctx:subject_id:product_id`，
因此同一个 (居民, 商品) 在 11 个价格点上拿到的前处理状态**逐位相同**。
这就是 do(price) 用状态实现，而不是用一句"请保持其他条件不变"实现。

`tests/test_experiments_demand.py::TestWorldContextIsPreTreatment` 守住这条性质。

另一条守恒律：**elicit 问题里绝不能出现它自己的答案**。所有 arm（包括 agent arm）在问
"上次多少钱"时都会把这三个变量从提示词里摘掉，否则测的就不是混淆而是复读。

## 3.5 `elicit` 斜率**不是** agent arm 的成绩单

容易读错的一点，写在这里避免重复踩：

`elicit` 问题在所有 arm 里都会摘掉被问的三个变量，所以 agent arm 的 elicit 斜率测的是
"**不供给**协变量时，光靠人设和情境接地，模型自行想象的历史价格还会不会跟着处理价格走"。
这是一个有意义的诊断，但它不是 agent arm 的主张。

agent arm 的主张在 `purchase` 上：协变量是**供给**的，且 `world_context` 构造上与处理独立，
模型不需要从价格反推。那条路径上的混淆是被**设计消除**的，不需要用数据去测。

需要用数据去测的是**代价**——论文说消混淆必然换来 focalism（Figure 4 的阶跃退化）。
所以真正的证伪点是 `agent` vs `covariate` 的需求曲线形状，由
`analysis.focalism()` 给出两个读数：

- `step_rule_agreement`：符合"价格 ≤ 竞品价就买"的比例。真实消费者也常常符合它，
  所以**只能跨 arm 比较**，不能对绝对阈值判定。
- `transition_width`：购买概率严格落在 5%–95% 之间的相对价格带宽度。
  阶跃函数宽度为 0，异质消费者会给出一条平缓的斜坡。**这个才是有区分度的量。**

### 判定标准

1. **消混淆**：构造性成立，`TestWorldContextIsPreTreatment` 守住，无需数据。
2. **生态效度**：`agent` 的 `transition_width` 应显著大于 `covariate`。
   若两者都接近 0，说明 agent arm 同样退化，**没有缓解论文的两难**，应当如实报告。
3. **接地是否够用**：`agent` 的 elicit 斜率若仍显著大于 0，说明人设接地不足以替代 unblinding，
   该推荐的配置是 `agent_unblinded`。

## 4. 两个问句

- `elicit`（论文 Prompt 1 / 附录 Prompt 7、8）：诊断。让模型填 `last_price, competitor_price,
  shelf_life_days`，看它们对处理价格的斜率。**正确答案是 0**。
  用 `--elicit-fields last_price` 可以退回论文原始的单变量形态。
- `purchase`（论文 Prompt 2）：估计量。购买 / 不购买 → 需求曲线。

## 5. 怎么跑

```bash
# 先看成本，不发任何调用
python -m gaworld.experiments --dry-run --draws 50

# 冒烟：1 个商品、1 位居民、两个问句、两个 arm = 44 次调用
python -m gaworld.experiments --name smoke --product-limit 1 --subject-limit 1 \
    --arms blind agent --provider minimax

# 只重新分析，不花 token
python -m gaworld.experiments --analyze-only --name smoke
```

输出在 `output/experiments/<name>/`：`results.jsonl`（每次调用一行，含原始文本）、
`summary.json`、`report.md`。中断后重跑会自动续跑；失败的格子会在续跑时重试。

### 成本

`--draws` 只作用于**无被试的 arm**（变异只能来自采样温度，所以要论文的 50 次）；
`--subject-draws` 作用于**有被试的 arm**（变异已经来自居民本身，默认 1 次）。
这两个如果合成一个参数，agent arm 会变成 `居民数 × draws` 倍，全量设计会从 14 万次膨胀到 100 万次。

全量（40 商品 × 11 价格 × 2 问句 × 20 居民，`--draws 50`）：

| arm | 调用数 |
|---|---|
| `blind` / `unblinded` | 各 44,000 |
| `covariate` / `agent` / `agent_unblinded` | 各 17,600 |
| 合计 | 140,800 |

跑全量前务必先 `--dry-run`。

## 6. 首次冒烟的结果（n=1 商品 / 1 居民 / 1 draw，MiniMax-M2.7）

| arm | 变量 | 斜率 | r |
|---|---|---|---|
| `blind` | last_price | +0.798 | +0.96 |
| `agent` | last_price | +0.381 | +0.75 |

论文 Figure 1 的混淆在中文语境、非 GPT 模型上**一次就复现出来了**：盲化提示下模型自述的
"上次购买价"几乎完全跟着当前随机价格走。给居民人设和情境后斜率大约减半，但**远不到 0**——
说明人设接地本身不足以消除混淆，这也正是论文主张要靠 unblinding 而不是靠更丰富的 persona 的理由。

⚠️ 这是 11 个数据点的轶事，不是估计。任何结论都要在全量或至少几百次调用后再下。

## 7. 已知限制

1. **没有人类基准数据**。论文那份 1000 人 Prolific 调查是美国 CPG 场景，与本模块的中文商品目录
   不可比，因此**算不出论文式的 MAE 表**。当前能做的是：arm 之间的相对比较、需求曲线的形状检验
   （单调下降 vs 倒 U）、混淆斜率。要补 MAE 就得自己跑一次中文问卷。
2. **`agent_embedded` arm 未实现**。让居民在仿真运行中的某一天真正走进超市回答，
   生态效度最高，但需要挂到日循环上（`gaworld/kernel` 的 `perception.compose` 钩子），
   且必须跑完整仿真才能测。目前是留出的扩展点，不是已交付能力。
3. **世界状态是种子化生成的，不是从已有 run 的记忆里读的**。`last_paid` 由
   `seed:ctx:subject:product` 抽出，满足"前处理且与处理独立"，但它不等于该居民真实经历过的
   购买记录。接 `gaworld/memory/store.py` 是自然的下一步。
4. **未接入 GAWorld-Bench**。可以作为一条新 track 挂进 `benchmark/gaworld_bench.py` 的
   scorecard，目前尚未接。

## 8. 附带的内核改动

`gaworld/llm/providers.py` 的三个 provider、`LLMRouter.call` 和 `call_llm` 新增了
`system=` / `temperature=` 两个逐调用覆盖参数，默认 `None` = 完全维持原行为。
没有它，论文 Prompt 5 vs 6 的对比无法作为真正的 system message 实现，温度也会被
provider 配置钉死在 0.2，采样变异直接消失。

Router 只在调用方显式设置时才转发这两个参数，因此仍然只接受 `call(prompt)` 的旧 provider
对象不受影响（`tests/test_gaworld_llm_fallback.py::TestPerCallOverrides`）。
