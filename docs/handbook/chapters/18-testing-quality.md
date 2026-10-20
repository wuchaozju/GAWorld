# 第 18 章　测试与质量门

写插件、改行为、动默认配置——这三件事都会让「以前跑出来的结果」变得不可信。这一章讲这个仓库用什么办法拦住这种退化，以及你要为改动承担什么。

## 18.1 两套测试：冒烟与全量

```bash
pytest --suite core    # 冒烟套件，约 30 秒，跑主仿真路径
pytest --suite full    # 全量
pytest tests           # 等价于全量
```

`--suite` 由 `tests/conftest.py` 实现：core 套件只跑 `tests/suites/core.txt` 里列出的节点 id，其余被 deselect。

这里有个设计值得知道：**core.txt 里的陈旧项会让整次运行失败**。如果你重命名了一个测试却忘了更新 core.txt，`pytest --suite core` 会直接报 `UsageError: tests/suites/core.txt lists tests that do not exist`。这是故意的——它保证冒烟套件不会因为改名而悄悄少测一个。

常用标记：

| 标记 | 含义 |
|---|---|
| `integration` | 跨仿真组件的集成测试 |
| `slow` | 会起子进程或完整导入仿真器；`pytest -m "not slow"` 可以跳过它们求快 |

## 18.2 行数预算：主循环不许变胖

`generative_city_sim.py` 和 `run_simulation` 有**只减不增**的行数上限，写在 `tests/line_budget.json`：

```json
{
  "generative_city_sim.py": {
    "lines": 4264,
    "functions": { "run_simulation": 1359 }
  }
}
```

`tests/test_line_budget.py` 会在超过时失败。规则是「上限只能往下走」：把代码搬出主文件会降低计数，这时要在同一次改动里把上限也调低；当你比上限低 50 行以上时，测试会提示你顺手再降一降。

这条预算的真正含义是**架构约束**：仿真主循环只能是一个骨架。新功能一律写成插件（第 15 章），不许往主文件里加内联逻辑。

## 18.3 Lint 棘轮：只许变好

仓库带了一批历史遗留的 ruff 发现和未格式化文件，`ruff check .` 每次都会红，但红得没有信息量。所以 CI 跑的是**棘轮**而不是全量检查：

```bash
python scripts/lint_ratchet.py --base origin/main   # CI：和目标分支比
python scripts/lint_ratchet.py                       # 本地：和 HEAD 比，检查未提交的改动
python scripts/lint_ratchet.py --update-baseline     # 清理之后把总数基线调低
```

它检查三件事：

1. **改过的 Python 文件不能有更多的 ruff 发现**——基线上有 3 个，改完还有 3 个可以，变成 4 个不行。新文件必须**零发现**。
2. **基线上格式化的文件改完仍要格式化**；新文件必须已格式化。基线上就没格式化的老文件，不会因为改了一行就被强行 `ruff format`。
3. **全仓库总数不得超过 `scripts/lint_baseline.json`**（只在基线记录的 ruff 版本下检查，新版 ruff 可能引入新规则）；当总数下降时用 `--update-baseline` 记录新基线。

其它工具：`ruff format --check .`（格式）、`black .`（行宽 110）、`mypy gaworld`（`gaworld/` 树严格类型检查，其它目录只是建议）。

## 18.4 Epoch：让「结果不可比」变成一件可声明的事

这是本仓库最特别的一个机制，也是做研究时最该懂的一个。

**问题**：如果你改了默认配置下的任何行为，那么以前跑出来的结果和以后跑出来的结果就**不能直接比较**了——但这一点无法从产物里看出来。

**做法**：`gaworld/core/comparability.py` 维护一条只增不重编号的 Epoch 记录。每一次「改变了默认配置下产出」的改动，都要追加一条：

```python
Epoch(11, "2026-10-10",
      "真实工作（默认开）接单时在整个技能库里按任务搜索技能写进简报……",
      ("work", "skills", "memory", "cognition"),
      "gaworld/work/skill_lookup.py; tests/test_skill_search.py"),
```

每条记四个东西：**编号**、**生效日期**、**改了什么**、**影响了哪些量**、**写在哪**。

当前 Epoch 是 **11**。前几条能看出这类改动的性质：Epoch 1 是「经济子系统的 hook 注册在失效的模块名下——此前经济模块在仿真里根本没有运行」；Epoch 2 是货币系统改造；Epoch 7 是「加薪 / 裁员概率按月解释（此前按天抽）」。

**什么时候必须加**：

- 改了**默认配置**下跑出来的结果，让早先的运行不再可比 → 必须加
- 只是**新增了一个默认关闭的可选开关** → 不需要加

**加完之后会发生什么**：运行、compare-event 目录和平行世界实验都会被打上 Epoch 标记；**复现池化、研究结论判定和 bench gate 都拒绝跨 Epoch 合并**。也就是说，系统会主动拦住你把 Epoch 7 的结果和 Epoch 11 的结果放进同一个统计里。

## 18.5 测试环境是隔离的

`tests/conftest.py` 的第一件事就是**把测试套件和开发者本地的 dashboard 配置隔开**。它不会读你真实的 `dashboard_config.json`，也不会往你真实的 `output/` 里写东西。

这不是细节：否则跑一次测试就可能污染你正在分析的那次运行产物。测试用 manifest 记录自己写过什么，跑完清掉。

## 18.6 新代码的交付清单

改了代码之后，下面这几条是仓库自己要求的：

| 项 | 命令 | 判据 |
|---|---|---|
| 测试 | `pytest --suite core` | 冒烟套件全绿 |
| 全量测试 | `pytest --suite full` | 全绿 |
| 覆盖率 | `pytest --cov=gaworld --cov-fail-under=80` | CI 用 80% 作为门槛 |
| Lint 棘轮 | `python scripts/lint_ratchet.py --base origin/<target>` | 没有新增发现，仓库总数没上升 |
| 格式 | `ruff format --check .` / `black .` | 新文件必须已格式化 |
| 类型 | `mypy gaworld` | `gaworld/` 树无新错误 |
| 行数预算 | `pytest tests/test_line_budget.py` | 没超；搬出代码要同时下调上限 |
| 可比性 | 判断是否需要追加 `Epoch` | 改了默认产出就加 |
| 文档 | 改了路由就登记 `gaworld/apps/openapi.py` | `tests/test_openapi.py` 会对未登记路由失败 |

**新代码必须带测试**，这是硬要求，不在清单里商量。

## 18.7 写测试的取向

仓库自己定的规矩很实在：

- 测试放在 `tests/` 下，文件名 `test_*.py`
- **优先用轻量、可复现的测试**：mock 掉 `call_llm` 的模型调用，避免真实网络 IO
- 不要依赖真实模型返回的文本来断言——模型会改写措辞。断言**结构**、**数量**、**方向**，不断言具体句子
- 跑得慢的测试打上 `slow` 标记，别让冒烟套件超时

如果你在写插件，参考 `docs/PLUGIN_AUTHORING.md` 末尾的「可运行的参考实现」，以及 `gaworld/core/comparability.py` 里每条 Epoch 引用的那些测试文件——它们示范了「一个行为变更怎么被钉住」。

## 18.8 提交与协作

- 提交信息用简短的小写祈使句（历史如此，例如 `updated`、`sync`、`requirement`）
- PR 要写清：范围摘要、配置变更、避免或忽略了哪些运行时产物
- `output/` 的内容通常不进版本库

## 18.9 本章小结

- 两套测试：`pytest --suite core` 是约 30 秒的冒烟，`--suite full` 是全量；core.txt 里的陈旧项会直接让运行失败。
- 行数预算只减不增，是「主循环不许变胖」的架构约束，不是风格偏好。
- Lint 走棘轮：改过的文件不许变差，仓库总数不许上升。
- **Epoch** 是这个仓库最该懂的机制：改了默认产出就追加一条，系统会拒绝跨 Epoch 合并结果。
- 测试环境与本地配置隔离，跑测试不会污染你的运行产物。
- 交付清单：测试、覆盖率、棘轮、格式、类型、预算、Epoch、文档登记。

## 18.10 动手练习

1. **跑一次质量门**（约 15 分钟）
   ```bash
   pytest --suite core
   python scripts/lint_ratchet.py
   python3 -c "from gaworld.core.comparability import CURRENT_EPOCH, EPOCHS; print(CURRENT_EPOCH); [print(e.number, e.affects, e.change[:40]) for e in EPOCHS]"
   ```
   **验收标准**：说出当前 Epoch 是几，并挑一条 Epoch 记录，判断它是否属于「改了默认配置下产出」——这是你自己改动时也要回答的问题。

2. **让一次改动被正确记账**（约 30 分钟）
   在一个副本里改一处**默认开启**的行为（比如某个插件的默认参数），跑一次仿真前后对比产物，确认这属于需要追加 Epoch 的改动；然后把 Epoch 记录写进 `gaworld/core/comparability.py`（**只在你自己的分支上做，别改主分支**）。
   **验收标准**：能说清「改动前后的哪个量变了」，并给这条 Epoch 写出 affects 元组里该填哪几个量。
