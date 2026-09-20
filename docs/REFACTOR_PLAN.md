# GAWorld 重构方案（诊断 + 分阶段执行计划）

> 状态：等待 review。这是诊断报告与执行计划，**尚未动代码**。

---

## 一、关键认知

**这个项目不是"从零重构"，而是处在已经启动的 S1/S2 迁移中途。**

证据：

- `gaworld/__init__.py` 自我描述："The legacy flat layout still owns most of the codebase. The `gaworld` package is the new home for cross-cutting concerns introduced by the S1/S2 refactor."
- `docs/PROJECT_STRUCTURE.md`："GAWorld is mid-migration from a flat script layout to a package layout."
- `gaworld/` 已包含 `core/`、`apps/`、`io/`、`llm/`、`settings/`、`work/` 六个子域。
- 迁移规约已定：legacy 模块 `from gaworld import ...`，反之不行；新增代码进 `gaworld/`。
- `tests/` 下 46 个测试文件——已有安全网，允许带测试重构。

**结论**：正确策略 = **加速并完成既有迁移**，并在迁移过程中顺便修掉性能、鲁棒性、耦合三类问题。**不要另起炉灶**。

---

## 二、现状盘点

| 维度 | 数据 |
|---|---|
| Python 总规模 | ~35,400 行（排除 backup/site/pycache） |
| `gaworld/` 子包 | ~3,800 行，已模块化 |
| 根目录 legacy 文件 | 20 个 `.py`，约 19,000 行 |
| 测试 | 46 个 `test_*.py`，46k+ 行（含 fixtures） |
| 文档 | README 中英双语 / AGENTS.md / CHANGELOG.md / docs/ 9 篇 |

### 体量最大的几个文件（按行数）

| 文件 | 行数 | 性质 | 状态 |
|---|---:|---|---|
| `generative_city_sim.py` | **8,044** | 8 个逻辑段拼成的过程式巨石（0 个 class，223 个顶层函数） | 待拆分 |
| `economy_module.py` | 1,662 | 个人财务 / 税收 / 宏观周期 | 已模块化，可直接迁入 `gaworld/economy/` |
| `dynamic_behavior.py` | 1,174 | 中断引擎 / 自发性 / 社交链 / 事件响应 | 已模块化，迁入 `gaworld/behavior/` |
| `city_map_system.py` | 1,105 | 地图 / 路径 / 交通成本 / 类目匹配 | 迁入 `gaworld/world/` |
| `social_network.py` | 913 | 关系网络构建与演化 | 迁入 `gaworld/social/` |
| `environment.py` | 692 | 外部环境事件接入 | 迁入 `gaworld/env/`（与现 `gaworld/io/` 区分） |
| `memory_store.py` | 661 | 长期记忆 / 向量索引持久化 | 迁入 `gaworld/memory/` |
| `human_realism.py` | 590 | 意图 / 习惯 / 记忆整合 | 迁入 `gaworld/cognition/` |

### `generative_city_sim.py` 内部结构（已有段落 banner）

```
L  35  Utils（时间网格、清洗、JSON 解析、随机种子等）
L 251  Params（CONFIG 解包、AGENT_IDS 等模块级常量）
L 1450  Policy 事件加载
L 1596  Profile 解析（CSV + Markdown）
L 1918  社交网络构建
L 1951  Map & Location（位置推断 / 通勤记忆 / 移动）
L 2475  Schedule & Action（日程生成 / 动作选择 / 短暂念头）
L 5144  Policy effect inference
L 5176  Cognition（社会语境 / 推理）
L 5398  Social influence（情绪扩散）
L 5418  State update
L 5546  Long-term memory（每日摘要、压缩、回顾）
L 5668  Main loop（run_simulation —— 单函数 1,370 行，含 13 个 `for agent in agents`）
L 7114  Entry（CLI argparse + dispatch）
```

`run_simulation()` 1,370 行是单文件最大问题——已经把现成的段落标好了，但没切。

---

## 三、问题清单（按严重度）

### P0 — 必须打掉

1. **`generative_city_sim.py` 体量失控**
   单文件 8k 行、单函数 1.37k 行，IDE 卡顿、code review 困难、合并冲突高发、新成员上手难度高。
   *根因*：13 个 `for agent in agents` 循环全堆在 `run_simulation()` 内，相位职责（perception / planning / action / reflection / memory）没有结构分离。

2. **根目录 9 个 legacy 大模块尚未迁入 `gaworld/`**
   迁移规约已定，但 60% 的代码量还在根目录。新代码引用路径混乱（`from config import` vs `from gaworld.settings import`）。

### P1 — 应该打掉

3. **性能：13 个独立 `for agent in agents` 通道**
   每个 tick 对 agent 列表扫 13 遍，缓存不亲和、并发机会被切碎。其中至少 4 个可合并；2 个含 LLM 调用应该用现有 `parallel_map` 包装。

4. **鲁棒性：`except Exception:` 26 处**
   不算多但都聚集在 LLM/HTTP/IO 边界（worker.py 4 处、generative_city_sim.py 3 处、llm_providers.py 2 处、社交网络 2 处）。这些位置应该换成**针对性异常类型 + 结构化重试**，并把吞掉的错误以 `logger.warning` 留痕。

5. **模块级可变状态 37 处**
   主要是 `CONFIG` 解包到模块级常量（`AGENT_IDS = ...` `MAP_PATH = ...`）。测试时无法注入、影响重入。需要收敛到一个 `SimContext` 对象里按需读。

### P2 — 顺手收掉

6. **`call_llm` 在循环里散落 25 次（generative_city_sim 内部）**
   有些可以批处理 / 并行；有些受 schedule 顺序约束不能动。需要逐个判定。

7. **`gaworld/llm/__init__.py` 是空的**，但 `llm_providers.py` 在根目录——预备好的迁移位置没填。

8. **文档落后于代码现状**
   `PROJECT_STRUCTURE.md` 没列出 `dynamic_behavior` 等近期新增；`README.md` "Project Structure" 段列的是 legacy 路径，没体现 `gaworld/` 子包。

---

## 四、目标架构

```
gaworld/
├── __init__.py
├── settings/         # 已有：CONFIG 装配
├── config.py         # 已有：typed config 适配
├── env_loader.py     # 已有
├── logging_setup.py  # 已有
├── core/             # 已有：Agent dataclass、parallel_map
│   ├── agent.py
│   ├── runner.py
│   └── context.py    # 【新】SimContext（替代模块级常量）
├── io/               # 已有：http_guard、web_scrape
├── llm/              # 已有但空 → 迁入 llm_providers.py 内容
│   ├── providers.py
│   └── router.py
├── memory/           # 【新】← memory_store.py
├── world/            # 【新】← city_map_system.py
├── env/              # 【新】← environment.py（外部环境对接）
├── social/           # 【新】← social_network.py
├── economy/          # 【新】← economy_module.py
├── behavior/         # 【新】← dynamic_behavior.py
├── cognition/        # 【新】← human_realism.py + 部分认知函数
├── interests.py      # 已有
├── work/             # 已有
├── apps/             # 已有
└── sim/              # 【新核心】← 拆分 generative_city_sim.py
    ├── pipeline.py        # 主循环 = 多阶段管线
    ├── phases/
    │   ├── perception.py
    │   ├── planning.py
    │   ├── action.py
    │   ├── reflection.py
    │   └── memory_phase.py
    ├── agents_loader.py   # build_agent / profile 解析
    ├── schedule.py        # 日程生成 / 适配
    ├── policy.py          # Policy 事件
    └── cli.py             # argparse 入口
```

根目录的 `generative_city_sim.py` 保留为**薄壳 CLI**（< 50 行，调用 `gaworld.sim.cli:main`），其他 legacy 根模块全部变成 1 行 `from gaworld.<x> import *` 兼容 shim，逐步在下一个版本里删除。

---

## 五、分阶段执行计划

每个阶段都有**明确的可验证成功标准**——测试全过 + 静态指标达标。每阶段独立可 review、独立可回滚。

### 阶段 0：基线快照（半小时）

- 跑全量 `pytest tests/`，记录通过数 / 时长 / 覆盖率
- 跑 `ruff check .` 记 baseline
- 用 `cProfile` 跑一次 `--days 2 --agents 3` 短模拟，存基线 profile
- **成功标准**：报告里有 3 个数字——测试 N pass / lint M warnings / sim T 秒

### 阶段 1：拆 `generative_city_sim.py` 巨石 — 不改语义

按现有 banner 把 11 段抽到 `gaworld/sim/` 各文件。每段一次 commit。原文件 `import *` 回来以保兼容。

- 阶段 1a: utils + time_grid → `gaworld/sim/_utils.py`
- 阶段 1b: profile 加载 → `gaworld/sim/agents_loader.py`
- 阶段 1c: schedule → `gaworld/sim/schedule.py`
- 阶段 1d: policy 事件 → `gaworld/sim/policy.py`
- 阶段 1e: action choice → `gaworld/sim/action.py`
- 阶段 1f: cognition + social_influence + state_update → `gaworld/sim/cognition.py`
- 阶段 1g: long-term memory ops → `gaworld/sim/memory_ops.py`
- 阶段 1h: `run_simulation` 拆成 `Pipeline.run()` + 5 个 phase → `gaworld/sim/pipeline.py` + `gaworld/sim/phases/`
- 阶段 1i: CLI 入口 → `gaworld/sim/cli.py`

**成功标准（每个子阶段）**：`pytest tests/` 全部通过、跑 `--days 1` 与基线输出 byte-equal（或 diff 在已知非确定性范围内）。

### 阶段 2：迁 legacy 大模块进 `gaworld/`

每个模块一次 commit。物理位置移动 + 根目录留 `from gaworld.<x> import *` 兼容 shim。

- 2a: `memory_store.py` → `gaworld/memory/`
- 2b: `city_map_system.py` → `gaworld/world/`
- 2c: `environment.py` → `gaworld/env/`
- 2d: `social_network.py` → `gaworld/social/`
- 2e: `economy_module.py` → `gaworld/economy/`
- 2f: `dynamic_behavior.py` → `gaworld/behavior/`
- 2g: `human_realism.py` → `gaworld/cognition/`
- 2h: `llm_providers.py` → `gaworld/llm/providers.py`（`gaworld/llm/__init__.py` 已就位）

**成功标准**：所有测试通过 + 根目录只剩 `generative_city_sim.py`（薄壳）、`config.py`（shim）、几个一次性脚本。

### 阶段 3：性能优化（基于阶段 0 的 profile，按数据决策）

- 3a: 合并可合并的 `for agent in agents` 通道（先用 profile 验证收益）
- 3b: `parallel_map` 包装两处含 LLM 的循环
- 3c: profile 高频字符串清洗函数（`_clean_env_context` / `_clean_reflection`），如显著则预编译正则 / LRU 缓存
- 3d: 复用 networkx 子图 / 距离查询的缓存

**成功标准**：相同输入下，模拟单步时间相对基线 **下降 ≥ 20%**，且测试输出不变。

### 阶段 4：鲁棒性收紧

- 4a: 把 26 处 `except Exception:` 替换成针对性异常（`requests.HTTPError`、`json.JSONDecodeError`、`KeyError`、`TimeoutError` ……）
- 4b: 在 LLM/HTTP 边界加 `tenacity` 风格指数退避重试（项目已有 `http_guard.py`，复用它）
- 4c: 模块级常量收敛到 `gaworld/core/context.SimContext`，老接口保留为属性代理
- 4d: 默认日志级别下，所有静默吞掉的 except 至少 `logger.warning` 一行

**成功标准**：`ruff` 的 `B902/B904` 类警告为 0；测试新增至少 3 个故障注入用例（断网 / LLM 超时 / JSON 损坏）全过。

### 阶段 5：文档刷新

- 5a: 更新 `README.md` 与 `README.zh-CN.md` 的 Project Structure 段
- 5b: 重写 `docs/PROJECT_STRUCTURE.md`，反映迁移完成后的最终布局
- 5c: 在 `CHANGELOG.md` 追加 `## [Unreleased] — 2026-05 — S3 完成迁移` 章节，列出移动 map（每个旧路径 → 新路径）
- 5d: 更新 `AGENTS.md` 的「New cross-cutting code lives under gaworld/」（提到迁移基本完成）
- 5e: 在 `gaworld/sim/pipeline.py` 顶端写一段架构说明 docstring

**成功标准**：两份 README 关于结构的描述与实际文件树一致；任何被外部引用的 import 路径都在文档里有交叉引用。

---

## 六、风险与缓解

| 风险 | 缓解 |
|---|---|
| 外部脚本 / 实验 import 旧路径 | 根目录留 shim（`from gaworld.<x> import *`）一个版本，CHANGELOG 标 deprecation |
| 8k 行文件 git rename 检测失败 | 每个子阶段单独 commit，commit message 写明物理移动 |
| 测试虽多但未必覆盖所有路径 | 每阶段都跑全量；性能阶段加 `--days 1 --agents 3` 端到端冒烟比对 |
| 时间预算 | 一次对话肯定做不完；每个子阶段独立可交付、可中断、可继续 |

---

## 七、Review 要点（请你定）

1. **阶段顺序对吗？** 我的判断：先拆巨石（1）、再迁 legacy（2），是因为巨石内部模块对 legacy 有 ~80 处依赖，先拆出去再换"被依赖端"的位置更安全。如果你更看重早收性能，3 可以提前到 2 之前。
2. **`gaworld/sim/` 子结构 OK 吗？** 你想要 `phases/` 这种细粒度，还是 `pipeline.py` 一个文件即可？
3. **`gaworld/` 下还要拆出 `world/`、`env/`、`cognition/`、`memory/` 等吗？** 还是合成 `gaworld/domain/` 一个总命名空间？
4. **兼容 shim 保留几个版本？** 默认我留 1 个 minor 版本，CHANGELOG 标 deprecation，下个版本删。
5. **跑测试需要外部 LLM 吗？** 我看到 `tests/fixtures/mock_llm.py`——是否所有路径都被 mock 覆盖？阶段 0 我会确认。

---

## 八、下一步

确认 / 调整方案后，我从**阶段 0：基线快照**开始，每完成一个子阶段汇报一次。
