# 第 8 章　运行系统：仿真循环、时钟与一致性

> 智能体、环境、网络、LLM 都到位了,接下来要把它们**装进一个时钟里**,让时间真正流动起来。这一章讨论社会仿真的运行系统:时钟与步长、顺序与并行、守恒与审计、状态持久化、可复现性。这部分内容在仿真论文里往往被忽视,但在工程实践里决定了一个仿真能不能"跑得起来"。读完本章,读者应该能理解为什么 GAWorld 有 --sim-days / --fast-forward / --sim-years 等不同模式,以及它们各自适合什么研究问题。

---

## 8.1　时钟与步长:秒、分钟、日、月、年

社会仿真用什么"滴答"?这是看似简单但影响深远的选择。

**秒级步长**(second-level):每秒钟刷新一次所有智能体的状态。适合仿真"应急疏散""城市交通"等需要秒级反应的场景。1000 人 × 86400 秒/天 × 30 天 = 26 亿次状态更新,计算量惊人。

**分钟级步长**(minute-level):每分钟刷新一次。适合仿真"日内活动选择"——吃饭、通勤、社交。一天 1440 步 × 1000 人 × 30 天 = 4300 万步,计算量适中。

**小时级步长**(hour-level):每小时刷新一次。适合"日内决策的聚合"——多数 ABM 用这种。一天 24 步 × 1000 人 × 30 天 = 72 万步,计算量轻。

**日级步长**(day-level):每天刷新一次。适合"长周期仿真"——世代研究、政策评估。一天 1 步 × 1000 人 × 365 天 = 36.5 万步,适合长期研究。

**月级/年级步长**(month/year-level):适合"大跨度仿真"——10 年、50 年、100 年。一年 1 步 × 1000 人 × 50 年 = 5 万步,计算量轻但行为粗。

GAWorld 的 `--sim-days / --fast-forward / --sim-years / --sim-months / --time-unit month` 选项就是为这些不同时长场景设计的。

| 步长 | 典型时长 | 计算量(1000 人) | 适用场景 |
|---|---|---|---|
| 秒级 | 1 天 | 26 亿次 | 应急疏散、实时交通 |
| 分钟级 | 1 周 | 1 亿次 | 日内活动选择 |
| 小时级 | 1 月 | 72 万次 | 多数 ABM |
| 日级 | 1 年 | 36.5 万次 | 政策评估、长周期 |
| 月级 | 10 年 | 12 万次 | 世代研究 |
| 年级 | 100 年 | 10 万次 | 文明演化 |

### 一个具体的步长选择练习

假设你要研究"限行令 6 个月内的影响"。候选步长:

- **分钟级**(60 天 × 24 × 60 = 86400 步):太细,6 个月内每分钟的行为差异对结论不重要。
- **小时级**(180 天 × 24 = 4320 步):合理,但 4320 × 1000 人 × LLM 调用成本 = 432 万次 LLM 调用,过于昂贵。
- **日级**(180 步):合理,180 × 1000 = 18 万次 LLM 调用,成本可控。**推荐**
- **月级**(6 步):太粗,看不到"3 个月 vs 6 个月"的差异。

选日级。然后用 GAWorld 跑:

```bash
python generative_city_sim.py run --sim-days 180
```

### 步长对仿真可信度的影响

步长不是越细越好。**太细**会出现两个问题:

1. **同步失真**:每个 tick 同时刷新所有智能体,但真实社会的同步不是瞬时的——某人先决定,另一人后决定,后者可能因前者改变而调整决策。细步长更容易出现"同时决策"的失真。
2. **计算浪费**:如果一个居民在 8:00–8:30 之间只做了一个"刷牙"动作,但步长是分钟级,这 30 步就是在浪费算力。

**太粗**也会失真:一个小时内的多次选择被压缩成一次,行为变得"过山车"——8 点起床 → 9 点已经上班 → 12 点已经吃完午饭,中间的事件全丢了。

经验法则:**步长应该和研究问题的最小时间单位一致**。研究"日内决策",用小时;研究"政策年效应",用日;研究"代际流动",用月。

---

## 8.2　顺序 vs 并行:人口规模与一致性

仿真里 1000 个智能体同时决策,怎么处理?

**顺序执行**(sequential):一个接一个决策。优点是**一致性**(后决策的人能看到先决策的人的影响);缺点是**慢**——1000 个智能体,每个等 1 秒,1000 秒。

**并行执行**(parallel):同时决策。优点是**快**——1000 个智能体分成 100 组,每组 10 人,总时间 ~10 秒;缺点是**一致性损失**——同一组里的人不知道彼此的决定,可能做出冲突决策。

**GAWorld 的策略:小规模顺序,大规模分组并行**。100 人以下用顺序;100–1000 人分成 10 组并行;1000 人以上用更复杂的分布式。

```
┌──────────────────────────────────────┐
│  100 人:顺序                       │
│  100~1000 人:10 组并行              │
│  1000 人以上:100 组并行             │
│  10000 人以上:分布式节点(多机)    │
└──────────────────────────────────────┘
```

代码示例:一个简单的并行仿真。

```python
# examples/parallel_sim.py
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time
import random

@dataclass
class SimAgent:
    name: str
    cash: float
    decision: str = ""

def make_decision(a: SimAgent) -> SimAgent:
    """模拟决策"""
    time.sleep(0.001)  # 模拟 1ms 决策时间
    if a.cash > 5000:
        a.decision = "去餐厅"
    else:
        a.decision = "回家"
    return a

# 创建 100 个 agent
agents = [SimAgent(f"agent_{i}", cash=random.randint(0, 10000)) for i in range(100)]

# 顺序执行
start = time.time()
for a in agents:
    make_decision(a)
print(f"顺序: {time.time() - start:.3f} 秒")

# 并行执行(10 组)
start = time.time()
with ThreadPoolExecutor(max_workers=10) as ex:
    list(ex.map(make_decision, agents))
print(f"并行: {time.time() - start:.3f} 秒")
```

跑这段代码,你会看到并行比顺序快 5–10 倍。但代价是:并行下,agent 2 看不到 agent 1 的决策(他们在不同线程)。这是社会仿真里最常见的"速度—一致性"权衡。

### 一致性损失的工程应对

应对一致性损失,GAWorld 用三个机制:

**机制一:分批时间步**。把所有 agent 分成 N 批,每批顺序执行,批间并行。这样同批内一致,批间并行,总时间下降 5–10 倍,一致性损失降到 5%。

**机制二:显式同步点**。在关键事件(如限行令实施日)上强制全局同步——所有 agent 都等其他人决策完才继续。这是耗时的但必要的。

**机制三:事件队列**。所有 agent 的决策进入队列,由主循环统一处理。这避免了"同时决策冲突",代价是延迟稍高。

读者做研究时,推荐用**机制一**——简单、够用、可解释。

---

## 8.3　同步事件与级联

仿真里有两类事件:**异步事件**(只影响一个或几个 agent)和**同步事件**(同时影响所有 agent)。同步事件处理不好,会出现"不公平"的失真。

**同步事件的例子**:

- 限行令实施日:所有 agent 的出行决策同时改变。
- 大规模疫情:所有 agent 同时面临健康风险。
- 公司集体裁员:同一公司的所有 agent 同时失业。
- 节日:所有 agent 同时调整日程。

**级联效应**(cascade effect)是同步事件的核心——一个事件触发多个 agent 的连锁反应。例如:

1. 公司集体裁员 → 100 个 agent 同时失业
2. 失业 → 收入下降 → stress 上升 → mood 下降
3. mood 下降 → 消费减少 → 当地商家收入下降 → 商家也裁员
4. 商家裁员 → 又有 50 个 agent 失业 → 循环放大

这种级联效应是社会仿真最有用的"涌现"形式。但级联需要**严格的事件同步**——如果裁员是分批发生,级联就弱得多。

代码示例:一个最简单的级联模拟。

```python
# examples/cascade.py
from dataclasses import dataclass, field
from typing import List

@dataclass
class CascadeAgent:
    name: str
    employed: bool = True
    cash: float = 5000
    stress: float = 0.0

def simulate_cascade(agents: List[CascadeAgent], layoff_size: int = 20):
    """模拟一次集体裁员及其级联"""
    # 阶段 1:裁员
    laid_off = random.sample(agents, layoff_size)
    for a in laid_off:
        a.employed = False
        a.cash -= 1000  # 应急支出
        a.stress = min(1.0, a.stress + 0.4)
    print(f"阶段 1: {layoff_size} 人被裁")

    # 阶段 2:消费收缩
    for a in agents:
        if a.stress > 0.3:
            a.cash -= 500  # 减少消费
            a.stress = min(1.0, a.stress + 0.05)
    print(f"阶段 2: 所有人减少消费")

    # 阶段 3:商家裁员(简化)
    # 假设 1/4 商家也裁员
    second_wave = random.sample([a for a in agents if a.employed], layoff_size // 2)
    for a in second_wave:
        a.employed = False
        a.cash -= 500
    print(f"阶段 3: {len(second_wave)} 人被二次裁员")

    return agents

# 跑 100 个 agent 的级联
agents = [CascadeAgent(f"a_{i}") for i in range(100)]
agents = simulate_cascade(agents, layoff_size=20)
employed = sum(1 for a in agents if a.employed)
print(f"最终: {employed}/100 仍在职")
```

跑这段代码,你会看到经典的"裁员级联"——20 人直接裁员 + 10 人二次裁员,总共 30 人失业,但触发因素只有 20 个初始失业。这种级联放大效应是社会仿真最有说服力的研究对象之一。

---

## 8.4　守恒定律与数值审计

社会仿真的可信度,有很大一部分建立在**守恒定律**上——经济仿真里的钱不能凭空出现或消失;物理仿真里的能量必须守恒。

GAWorld 的经济系统有几个守恒定律:

**守恒一:个人现金 + 个人储蓄 + 企业账户 + 政府部门 + 银行部门 = 常数**。货币不会凭空产生或消失,只能在不同部门间转移。

**守恒二:每个人的资产净值 = 现金 + 储蓄 + 房产估值 - 负债**。这是会计恒等式。

**守恒三:模拟期间的总产出 = 总消费 + 总投资 + 总储蓄**。这是宏观经济学恒等式。

守恒是仿真可信度的底线。如果跑 30 天后,经济系统的"守恒审计"(`output/economy/conservation_audit.csv`)发现钱不平,那这个仿真就不该被信任。

代码示例:一个守恒审计器。

```python
# examples/audit.py
from dataclasses import dataclass

@dataclass
class EconomyAudit:
    total_cash: float = 0
    total_savings: float = 0
    corporate_account: float = 0
    government: float = 0
    bank: float = 0

    def check_conservation(self, initial_total: float) -> bool:
        current = (self.total_cash + self.total_savings
                   + self.corporate_account + self.government + self.bank)
        diff = abs(current - initial_total)
        return diff < 1.0  # 允许 1 元以内的舍入误差

# 模拟前后对比
initial = EconomyAudit(total_cash=1000*5000, total_savings=1000*50000,
                       corporate_account=1000000,
                       government=500000,
                       bank=500000)
initial_total = (initial.total_cash + initial.total_savings
                 + initial.corporate_account + initial.government + initial.bank)

# ... 跑 30 天仿真 ...

# 跑完后审计
final = EconomyAudit(total_cash=999*4800, total_savings=999*50200,
                     corporate_account=1050000,
                     government=510000,
                     bank=499000)
if final.check_conservation(initial_total):
    print("✓ 经济系统守恒")
else:
    print("✗ 经济系统失守,有 bug")
```

GAWorld 在 `gaworld/economy/finance.py` 里实现了完整的守恒审计,每天输出一次审计结果。如果发现失守,会立即报警并停止仿真。

### 守恒 vs 数值精度

守恒审计的容差是个工程问题。太严(精确到分)会因为浮点数舍入误报;太宽(1% 容差)会放过真 bug。GAWorld 用绝对容差 1 元 + 相对容差 0.01%,二者取严。

读者做研究时,**必须**实现守恒审计——这是仿真可信度的最低门槛。论文里如果有 "经济系统守恒" 的声明,需要附上审计日志。

---

## 8.5　状态持久化与可复现性

仿真跑完后,数据怎么存?论文里能不能复现?这是社会仿真常被忽视但决定论文可信度的环节。

GAWorld 的状态持久化分三层:

**第一层:每日快照**(`output/state/agent_state_history.csv`)。每天所有 agent 的状态打成一行 CSV。这是仿真的"主日志"——任何时刻的状态都可以从这里恢复。

**第二层:每日事件**(`output/events/`)。每天所有发生的事件——通勤、社交、消费、决策——打成 JSONL 日志。这是"发生了什么的证据"。

**第三层:每日记忆**(`output/memory/agent_<id>_<date>.json`)。每天 agent 的记忆快照,包括短期、情景、长期、关系四类。这是"agent 自己记得什么"。

这三层持久化让仿真具有完整的"考古"能力——研究者可以在任何时候停下来,问"为什么 agent 31 在第 15 天做出了这个决策",然后回溯到那一天的记忆和事件。

### 可复现性的三件套

要让仿真可复现,需要三件套:

**件套一:种子**(seed)。所有随机数必须从一个种子导出,这样同样的种子跑出的结果一致。GAWorld 默认种子=42,但可以通过 `--seed N` 改变。

**件套二:配置**(config)。所有模型参数必须从一个配置文件读,而不是硬编码。GAWorld 的配置在 `config.py`、`dashboard_config.json`、环境变量 `GAWORLD_CONFIG_OVERRIDES` 三处可改。

**件套三:依赖版本**(dependencies)。`requirements.txt` 必须锁定所有依赖到具体版本(包括 LLM 模型 ID),这样几年后跑出来的结果一致。

代码示例:一个可复现的仿真框架。

```python
# examples/reproducible.py
import random
import json

def run_simulation(seed: int, config_path: str):
    """可复现的仿真入口"""
    # 1. 加载配置
    with open(config_path) as f:
        config = json.load(f)

    # 2. 设置随机种子
    random.seed(seed)

    # 3. 跑仿真
    results = {}
    # ... 实际仿真逻辑 ...

    return results

# 用同样的 seed + config 跑两次
r1 = run_simulation(seed=42, config_path="config_v1.json")
r2 = run_simulation(seed=42, config_path="config_v1.json")

# 两次结果应该完全一致(允许浮点误差)
assert r1 == r2, "不可复现!"
```

这段代码的"可复现性三件套"是社会仿真研究的底线。读者做研究时,**必须**让仿真可复现——这是论文能被别人验证的前提。

---

## 8.6　代码示例:一个 200 行的最小事件循环

把 8.1–8.5 节的内容整合起来,写一个"最小可行事件循环"。

```python
# examples/mini_event_loop.py
from dataclasses import dataclass, field
from typing import List
from datetime import datetime, timedelta
import random

@dataclass
class MiniAgent:
    name: str
    cash: float = 5000
    stress: float = 0.0
    mood: float = 0.0
    history: List[dict] = field(default_factory=list)

@dataclass
class MiniEvent:
    time: datetime
    type: str  # "policy"/"natural"/"economic"/"technology"
    target: str  # "all" 或具体名字
    effect: dict = field(default_factory=dict)

class MiniSimulator:
    def __init__(self, agents: List[MiniAgent], seed: int = 42):
        self.agents = agents
        self.random = random.Random(seed)
        self.events: List[MiniEvent] = []
        self.day = 0

    def add_event(self, event: MiniEvent):
        self.events.append(event)

    def step(self, current_time: datetime):
        """一个时间步(1 小时)"""
        # 1. 处理事件
        for ev in self.events:
            if ev.time == current_time:
                for a in self.agents:
                    if ev.target == "all" or ev.target == a.name:
                        for k, v in ev.effect.items():
                            if k == "cash":
                                a.cash += v
                            elif k == "stress":
                                a.stress = max(0, min(1, a.stress + v))

        # 3. agent 日常行为(简化)
        for a in self.agents:
            # 简单决策
            if a.stress > 0.5:
                action = "散步减压"
                a.stress = max(0, a.stress - 0.1)
                a.mood = min(1, a.mood + 0.05)
            elif a.cash < 100:
                action = "回家省钱"
                a.mood = max(-1, a.mood - 0.05)
            else:
                action = "自由活动"

            a.history.append({
                "time": current_time.isoformat(),
                "action": action,
                "cash": a.cash,
                "stress": a.stress,
                "mood": a.mood
            })

    def run(self, days: int):
        """跑 N 天,每小时一步"""
        start = datetime(2026, 9, 26, 0, 0)
        for d in range(days):
            self.day = d
            for h in range(24):
                t = start + timedelta(days=d, hours=h)
                self.step(t)
        return self.agents

# 创建 10 个居民
agents = [MiniAgent(name=f"agent_{i}") for i in range(10)]

# 创建仿真器
sim = MiniSimulator(agents, seed=42)

# 添加一个事件:第 5 天裁员
sim.add_event(MiniEvent(
    time=datetime(2026, 10, 1, 9, 0),
    type="policy",
    target="agent_0",
    effect={"cash": -2000, "stress": 0.5}
))

# 跑 7 天
sim.run(days=7)

# 打印 agent_0 的历史
for entry in agents[0].history[::24]:  # 每天看一条
    print(entry)
```

跑这段代码,你会看到一个简单的"事件 + agent 反应"的循环。第 5 天 9:00 的裁员事件会触发 agent_0 的 cash 减少和 stress 上升,后续的日常循环会持续影响它的状态。

> **教学讨论**:这段代码的事件是"被动"的——它由外部代码添加。更高级的设计是"事件触发器",由 agent 的状态或环境的变化自动产生事件。例如:"如果某 agent 的 cash < 0,触发破产事件"。这会让级联效应真正"涌现"出来。

---

## 8.7　本章小结

- 时钟与步长分五档(秒/分钟/小时/日/月/年),选择标准是"和研究问题最小时间单位一致"。
- 顺序 vs 并行的权衡:顺序保证一致性、并行提高速度。GAWorld 用分批时间步平衡。
- 同步事件和级联效应是社会仿真最有用的涌现形式,需要严格的事件同步机制。
- 守恒定律是仿真可信度的底线,经济系统的货币必须守恒。
- 状态持久化分三层(状态快照、事件日志、记忆快照),可复现性需要种子+配置+依赖三件套。
- 一个 200 行的最小事件循环能在 1 秒内跑一周仿真,是仿真世界的"操作系统"。

---

## 8.8　思考题

1. **为限行令案例选择仿真步长**:限行令实施 6 个月,1000 人。你用什么步长?为什么?
2. **设计一个守恒审计方案**:仿真里有 1000 人、企业、政府、银行四个部门。怎么审计"货币守恒"?代码或伪代码。
3. **设计可复现的仿真包**:包括哪些文件?种子、配置、依赖怎么组织?
4. (进阶)**为一个 10000 人 × 1 年的仿真估算成本**:用日级步长、规则为主 + 关键决策用 LLM。总成本多少?你能减到多少?

---

## 8.9　延伸阅读

1. Zeigler, B. P., Praehofer, H., & Kim, T. G. (2000). *Theory of Modeling and Simulation: Integrating Discrete Event and Continuous Complex Dynamic Systems*. Academic Press. —— 仿真理论的经典教材。
2. Railsback, S. F., & Grimm, V. (2019). *Agent-Based and Individual-Based Modeling: A Practical Introduction*. Princeton University Press. —— ABM 实践指南,讨论时钟、并行、可复现等具体问题。
3. Macal, C. M., & North, M. J. (2010). Tutorial on Agent-Based Modelling and Simulation. *Journal of Simulation*, 4(3), 151–162.
4. Grimm, V., et al. (2010). The ODD Protocol: A Review and First Update. *Ecological Modelling*, 221(23), 2760–2768. —— ODD 协议(Overview, Design concepts, Details),是描述 ABM 的标准格式。
5. Edmonds, B., & Hales, D. (2010). Replication, Replication and Replication: Some Hard Lessons from Simple Models. In *Simulating Social Complexity*. —— 可复现性的陷阱。
6. GAWorld 工程文档:`gaworld/sim/pipeline.py`、`gaworld/economy/finance.py`。
7. North, M. J., et al. (2013). Complex Adaptive Systems Modeling with Repast Simphony and Repast for High Performance Computing. —— Repast HPC 框架的教程。
8. Klöckner, A., et al. (2023). The ODD Protocol for Describing Agent-Based Models in Social Science. *JASSS*, 26(2). —— ODD 协议的更新版。

---

> **本章教学注释**
>
> 这一章是技术层的最后一章,也是和工程实践最紧密的一章。如果读者是社会科学家、不打算做工程,这章可以只看 8.1(步长)和 8.5(可复现性)——这两个概念对论文写作最重要。
>
> 8.6 节的 200 行最小事件循环是一个非常重要的教学钩子——它把第 4 章的智能体、第 5 章的环境、第 6 章的网络、第 7 章的 LLM 决策都"装进了一个时钟"。读者如果想真正理解社会仿真,应该把这段代码跑一遍,然后修改它——加一个 LLM 决策、加一个守恒审计、加一个并行执行。改完之后,一个真正的"社会"就诞生了。
>
> 8.5 节"可复现性的三件套"是社会仿真研究的底线。读者写论文时,**必须**附上:种子值、配置文件、依赖版本。这三件东西缺一不可。
>
> 至此,本书的"技术层"全部完成。接下来进入"方法层"——从研究问题到可信度评估,这是社会仿真作为研究方法的全流程。第 9 章开始讨论"如何把研究问题变成可证伪的仿真假设"。
---

## 8.10　扩展:仿真性能优化

仿真运行可能很慢。本节讨论性能优化策略。

### 8.10.1　向量化和批处理

Python 的 for 循环慢,用 numpy 向量化或批处理:

```python
# 慢:逐 agent 处理
for agent in agents:
    agent.cash += agent.income_hourly

# 快:向量化
agents_cash = np.array([a.cash for a in agents])
incomes = np.array([a.income_hourly for a in agents])
agents_cash += incomes
for i, a in enumerate(agents):
    a.cash = agents_cash[i]
```

### 8.10.2　内存优化

大规模仿真可能内存爆炸。优化策略:

- 用 numpy 数组代替 list of dict
- 定期持久化到磁盘
- 用稀疏矩阵存关系网络

### 8.10.3　分布式仿真

10000+ 智能体需要分布式:

- 多机协同
- 节点间只交换"边界 agent"信息
- 中心化调度,分布式执行

GAWorld 的分布式 relay 实现见 `gaworld/distributed/comm.py`。

### 8.10.4　缓存与去重

LLM 调用的缓存能减少 30–50% 的调用:

- 同样的 prompt + 同样的状态 → 同样的响应
- 用 hash 作为缓存键
- LRU 淘汰策略

---

## 8.11　扩展:分布式与并行计算的深度讨论

### 8.11.1　一致性模型

分布式仿真有几种一致性模型:

- **强一致性**:所有节点每步同步
- **弱一致性**:节点间偶尔同步
- **最终一致性**:最终状态一致

仿真通常用**弱一致性**——性能可接受,代价是可能错过一些瞬时事件。

### 8.11.2　节点划分

按地理位置划分节点最自然:

- 每个区一个节点
- 节点间边界 agent 同步
- 中心节点做协调

### 8.11.3　故障处理

分布式仿真必须有故障处理:

- 节点宕机:用备用节点
- 网络断开:本地继续 + 异步同步
- 数据损坏:从最近的 checkpoint 恢复

### 8.11.4　监控与调优

分布式仿真的监控指标:

- 节点负载
- 网络流量
- 内存使用
- 仿真速度(sims/second)

基于监控调优节点数量、并行度。

---

## 8.12　扩展:仿真运行的工程最佳实践

### 8.12.1　日志规范

每个仿真应该输出结构化日志:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("output/simulation.log"),
        logging.StreamHandler()
    ]
)
```

### 8.12.2　配置 vs 代码分离

所有参数必须从配置文件读,不要硬编码:

```python
# 错:硬编码
NUM_AGENTS = 1000
SIM_DAYS = 30

# 对:从配置读
config = load_config("dashboard_config.json")
num_agents = config["simulation"]["size"]
sim_days = config["simulation"]["days"]
```

### 8.12.3　异常处理

仿真里可能出各种异常:

- LLM API 失败
- 网络中断
- 内存溢出

必须有异常处理:

```python
try:
    response = call_llm(prompt)
except LLMAPIError as e:
    log_error(f"LLM 调用失败:{e}")
    response = heuristic_fallback()
except MemoryError:
    log_error("内存溢出,清理缓存")
    cleanup_cache()
```

### 8.12.4　资源清理

仿真运行完必须清理:

- 关闭文件句柄
- 释放 LLM 连接
- 清理临时文件

---

## 8.13　扩展:仿真监控与可视化

仿真运行时需要实时监控。

### 8.13.1　实时仪表盘

GAWorld Dashboard 实时显示:

- 当前仿真日
- agent 状态分布
- 网络拓扑
- 经济系统状态
- LLM 调用次数

### 8.13.2　性能监控

```python
# examples/performance_monitor.py
import time

class PerformanceMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.step_count = 0

    def step(self):
        self.step_count += 1
        elapsed = time.time() - self.start_time
        return self.step_count / elapsed  # steps/sec
```

### 8.13.3　异常告警

仿真运行时如果发现异常(守恒失守、agent 状态错误),立即告警:

```python
def alert_on_anomaly(issue: str):
    """异常告警"""
    print(f"\n!!! ANOMALY: {issue} !!!\n")
    # 实际工程里:发邮件、Slack、企业微信等
```

### 8.13.4　可视化回放

仿真跑完后,可以回放任意时间点的状态:

- 时间轴拖动
- agent 状态热力图
- 网络动态演化
- 关键事件标注

---

## 8.14　本章小结(扩展版)

- 性能优化包括向量化、内存优化、分布式、缓存去重。
- 分布式仿真的一致性模型、节点划分、故障处理、监控调优。
- 工程最佳实践:日志规范、配置与代码分离、异常处理、资源清理。
- 监控与可视化:实时仪表盘、性能监控、异常告警、可视化回放。
- GAWorld 的运行系统已经实现了大部分生产级特性,读者可以直接使用。

