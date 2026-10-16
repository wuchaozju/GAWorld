# 第 23 章　GAWorld 工程实操手册

> **教学说明**:本章是 2026 年 GAWorld 平台的工程实操手册。前几章(4-8、20)介绍了通用的 ABM 理论,本章聚焦于**用 GAWorld 真正运行一个研究项目**所需的具体命令、配置、调试技巧、扩展点。
>
> 读者对象:已经决定用 GAWorld 的研究者。
>
> 工具版本:GAWorld v0.6+ (2026 年 Q3)
>
> 注意:代码会随版本变化,具体以 `gaworld --help` 输出为准。

---

## 23.1　GAWorld 平台速览

### 23.1.1　平台架构

```
GAWorld/
├── generative_city_sim.py     # CLI 入口
├── gaworld/                    # 核心包
│   ├── core/                   # 仿真循环、agent 基础
│   ├── city/                   # 城市生成
│   ├── behavior/               # 行为模块
│   ├── cognition/              # 认知模块
│   ├── personality/            # OCEAN 人格
│   ├── interests/              # 兴趣
│   ├── family/                 # 家庭关系
│   ├── economy/                # 经济
│   ├── environment/            # 环境
│   ├── events/                 # 事件
│   ├── world/                  # 世界地图
│   ├── interventions/          # 干预
│   ├── llm/                    # LLM 接口
│   ├── memory/                 # 记忆
│   ├── apps/                   # Dashboard 等
│   └── settings/               # 配置
├── examples/                    # 示例
├── data/                        # 数据
└── output/                      # 仿真输出
```

### 23.1.2　核心概念

- **智能体(Agent)**:仿真里一个人,带身份、状态、记忆、决策
- **城市(City)**:一个仿真世界,从真实地名生成
- **Tick**:仿真最小时间单位(可配置为分钟/小时/天)
- **Day**:智能体一天的活动循环
- **事件(Event)**:在某些 tick 触发的全城市/局部影响
- **干预(Intervention)**:研究者主动触发的扰动
- **采访(Interview)**:对智能体的结构化访谈

### 23.1.3　一个最简仿真流程

```python
# 1. 准备数据
python -m gaworld.city "绍兴柯桥" --size 1000

# 2. 跑仿真
python generative_city_sim.py run --sim-days 30

# 3. 看结果
python generative_city_sim.py dashboard
```

---

## 23.2　CLI 命令速查

### 23.2.1　城市生成

```bash
# 从真实地名生成
python -m gaworld.city "杭州西湖" --size 2000
python -m gaworld.city "柳溪村" --offline --scale tiny

# 列出已有城市
python -m gaworld.city list

# 删除城市
python -m gaworld.city delete <name> --yes
```

参数:
- `--size`:智能体数量,默认 1000
- `--offline`:不联网,纯程序生成
- `--scale`:tiny / small / medium / large / xlarge
- `--seed`:随机种子,默认 42

### 23.2.2　仿真运行

```bash
# 标准运行
python generative_city_sim.py run

# 指定参数
python generative_city_sim.py run --sim-days 180 --seed 42

# 快进模式
python generative_city_sim.py run --sim-days 600 --fast-forward

# 长期
python generative_city_sim.py run --sim-years 10 --time-unit month

# 选 LLM
python generative_city_sim.py run --llm gpt-4o-mini
```

参数:
- `--sim-days`:仿真天数
- `--sim-years` / `--sim-months`:用年/月作为时间单位
- `--time-unit`:minute / hour / day / week / month / year
- `--fast-forward`:快进模式,只生成 daily brief
- `--seed`:随机种子
- `--llm`:指定 LLM 模型

### 23.2.3　干预与实验

```bash
# 政策干预
python generative_city_sim.py intervene policy_limit_weekday \
    --day 45 --rules "周一1&6"

# 灾害
python generative_city_sim.py intervene disaster_earthquake \
    --magnitude 6.5 --epicenter "柯桥区中心"

# 看干预记录
python generative_city_sim.py intervention list
```

### 23.2.4　采访与调查

```bash
# 单智能体采访
python generative_city_sim.py interview --agent-id 31 --question "你支持限行吗?"

# 多智能体采访
python -m gaworld.interview --spec round.json --out answers.json

# 看采访结果
python generative_city_sim.py interview show --round-id r_2026_09_26
```

### 23.2.5　平行世界

```bash
# 跑 N 个平行世界
python generative_city_sim.py run --parallel-worlds 6 --sim-days 180

# 对比世界
python generative_city_sim.py compare-event \
    --event "限行令" --day 45

# 报告
python generative_city_sim.py parallel-worlds report
```

### 23.2.6　Dashboard 与可视化

```bash
# 启动 Dashboard
python generative_city_sim.py dashboard

# 启动可视化
python generative_city_sim.py serve-viz --port 8000

# 分布式 Dashboard
python generative_city_sim.py serve-distributed --host 0.0.0.0
```

### 23.2.7　其他常用命令

```bash
# 重置仿真
python generative_city_sim.py reset

# 编译 agent 决策 prompt
python generative_city_sim.py compile-prompt --agent-id 31

# 导出数据
python generative_city_sim.py export --format parquet

# 看日志
python generative_city_sim.py logs --day 45
```

---

## 23.3　配置文件结构

### 23.3.1　三层优先级

```
环境变量(GAWORLD_CONFIG_OVERRIDES)  ← 最高
dashboard_config.json                  ← 中等
gaworld/settings/defaults.py            ← 最低
```

### 23.3.2　dashboard_config.json 示例

```json
{
  "city": "shaoxing_keqiao",
  "llm": {
    "default": "gpt-4o-mini",
    "tasks": {
      "daily_decision": "gpt-4o-mini",
      "interview_analysis": "gpt-4",
      "disaster_response": "gpt-4o"
    }
  },
  "simulation": {
    "default_seed": 42,
    "default_sim_days": 30,
    "fast_forward_threshold_days": 60
  },
  "memory": {
    "consolidation_threshold": 10,
    "decay_half_life_days": 7
  },
  "economy": {
    "currency_unit": "CNY",
    "conservation_audit": true
  }
}
```

### 23.3.3　常用覆盖项

| 配置项 | 默认 | 用途 |
|---|---|---|
| `simulation.default_seed` | 42 | 随机种子 |
| `simulation.default_sim_days` | 30 | 仿真天数 |
| `memory.consolidation_threshold` | 10 | 记忆合并阈值 |
| `memory.decay_half_life_days` | 7 | 记忆半衰期 |
| `economy.conservation_audit` | true | 经济守恒检查 |
| `social.decay_rate_per_day` | 0.01 | 关系衰减率 |
| `personality.big5_enabled` | true | 大五人格开关 |

完整覆盖项见附录 C。

### 23.3.4　环境变量覆盖

```bash
# 一次性覆盖
export GAWORLD_CONFIG_OVERRIDES='{"llm":{"default":"gpt-4"}}'

# 跑仿真
python generative_city_sim.py run
```

---

## 23.4　项目目录结构

### 23.4.1　新项目初始化

```bash
mkdir my_study
cd my_study

# 复制 GAWorld 模板
cp -r /path/to/GAWorld/{generative_city_sim.py,gaworld,examples,requirements.txt} .

# 创建自己的配置
cp dashboard_config.json.example my_config.json

# 创建 README
echo "# My Study" > README.md
```

### 23.4.2　目录组织最佳实践

```
my_study/
├── README.md
├── dashboard_config.json     # 默认配置
├── configs/                   # 实验配置
│   ├── exp_001_baseline.json
│   ├── exp_002_policy.json
│   └── exp_003_chaos.json
├── data/                      # 仿真数据
│   ├── shaoxing_keqiao/
│   └── results/
├── analysis/                  # 分析脚本
│   ├── plot.py
│   └── stat.py
├── papers/                    # 论文
│   ├── draft.md
│   └── figures/
├── output/                    # 仿真输出
└── gaworld/                   # 链接到 GAWorld 核心
```

### 23.4.3　配置版本控制

```bash
# 配置入 git
git add dashboard_config.json configs/
git commit -m "exp_001 baseline config"

# 实验数据不进 git
echo "output/" >> .gitignore
echo "data/results/" >> .gitignore

# 配置快照随运行自动保存
ls output/run_2026_09_26_*/config.json
```

---

## 23.5　调试技巧

### 23.5.1　仿真卡死的诊断

```bash
# 1. 看进程
ps aux | grep generative_city_sim

# 2. 看 CPU/内存
top -pid <pid>

# 3. 看日志
tail -f output/run_*/logs/sim.log

# 4. 看 LLM 调用统计
grep "LLM call" output/run_*/logs/sim.log | wc -l
```

### 23.5.2　决策不合理的诊断

```bash
# 1. 看特定 agent 的决策
python generative_city_sim.py logs --day 45 --agent-id 31

# 2. 看决策的 prompt
python generative_city_sim.py compile-prompt --agent-id 31

# 3. 跑小规模对照
python generative_city_sim.py run --sim-days 7 --seed 42
```

### 23.5.3　LLM 调用过慢的诊断

```bash
# 1. 看 LLM 响应时间
grep "LLM latency" output/run_*/logs/sim.log | tail -20

# 2. 切换快模型
python generative_city_sim.py run --llm gpt-4o-mini

# 3. 启用缓存
# 在 config 里设 cache.enabled = true
```

### 23.5.4　结果异常的诊断

```bash
# 1. 跑相同 seed 复现
python generative_city_sim.py run --seed 42 --sim-days 30
python generative_city_sim.py run --seed 42 --sim-days 30

# 2. 对比不同 seed
for seed in 1 2 3 4 5; do
  python generative_city_sim.py run --seed $seed --sim-days 30
done

# 3. 看 agent-level 数据
python -c "
import pandas as pd
df = pd.read_parquet('output/run_*/data/agents.parquet')
print(df.describe())
"
```

---

## 23.6　扩展 GAWorld

### 23.6.1　添加自定义智能体决策

```python
# gaworld/behavior/my_decision.py
from gaworld.core.agent import Agent

class MyDecision:
    """自定义决策"""
    
    def decide(self, agent: Agent, context: dict) -> dict:
        # 你的决策逻辑
        return {"action": "shop", "location": "mall"}
```

```python
# 注册到 gaworld/behavior/plugin.py
def register_decisions():
    from gaworld.behavior.my_decision import MyDecision
    return {
        "my_decision": MyDecision(),
    }
```

### 23.6.2　添加自定义事件

```python
# gaworld/events/my_event.py
from gaworld.events.base import Event

class MyEvent(Event):
    """自定义事件"""
    
    def apply(self, world):
        # 你的事件逻辑
        world.economy.boost(percentage=0.1)
```

### 23.6.3　添加自定义 LLM provider

```python
# gaworld/llm/my_provider.py
from gaworld.llm.base import LLMProvider

class MyProvider(LLMProvider):
    def call(self, prompt, **kwargs):
        # 你的 API 调用
        response = requests.post(...)
        return response.json()
```

```python
# gaworld/llm/providers.py
LLM_PROVIDERS = {
    "my_provider": MyProvider(),
    # ... 其他
}
```

### 23.6.4　添加自定义输出格式

```python
# gaworld/output/my_format.py
from gaworld.output.base import OutputFormat

class MyFormat(OutputFormat):
    def save(self, data, path):
        # 你的输出逻辑
        ...
```

---

## 23.7　性能优化

### 23.7.1　LLM 成本控制

| 策略 | 节省 | 实现难度 |
|---|---|---|
| 用更便宜模型 | 50-90% | 易 |
| Prompt 压缩 | 20-40% | 中 |
| 批量调用 | 30-50% | 中 |
| 缓存 | 50-90%(重复 prompt) | 易 |
| 本地模型 | 80-99% | 难 |

### 23.7.2　内存优化

```python
# 启用流式数据
config.simulation.streaming = True

# 压缩状态历史
config.memory.archive_threshold = 30  # 30 天后归档

# 清理日志
config.logs.retention_days = 7
```

### 23.7.3　并行化

```python
# 启用多进程
config.performance.parallel_workers = 16

# 启用分布式
python generative_city_sim.py run --distributed --nodes 4
```

### 23.7.4　批量化 LLM 调用

```python
# 在 config 里
config.llm.batching.enabled = true
config.llm.batching.max_size = 10
config.llm.batching.wait_seconds = 5
```

---

## 23.8　常见错误与解决方案

### 23.8.1　"out of memory"

**错误**:`MemoryError` 或卡死

**解决**:
- 减小 `simulation.size`
- 启用 `streaming = True`
- 增加 `memory.archive_threshold`

### 23.8.2　"LLM timeout"

**错误**:`openai.APITimeoutError`

**解决**:
- 重试:在 config 设 `llm.retry_count = 3`
- 换模型:`gpt-4o-mini` 比 `gpt-4` 快 5 倍
- 改 prompt:简短 prompt 更快

### 23.8.3　"决策不合理"

**问题**:智能体行为看起来不真实

**诊断**:
- 看 prompt 是否明确"这是什么场景"
- 看 agent 状态是否合理
- 看 LLM 是否被 prompt 误导

**解决**:
- 改 prompt:加具体例子
- 加约束:用 JSON 输出 + 后处理
- 多模型对照:用 Claude 对照 GPT

### 23.8.4　"结果不可复现"

**问题**:同 seed 不同结果

**原因**:
- LLM 决策不稳定
- 时间戳不同
- 系统负载不同

**解决**:
- 固定 LLM 模型版本
- 固定随机种子
- 用 temperature=0

### 23.8.5　"找不到输出文件"

**解决**:
```bash
# 找最近一次仿真
ls -t output/run_*/ | head -3

# 找特定数据
find output/ -name "agents.parquet" | head -5
```

---

## 23.9　最佳实践

### 23.9.1　研究项目的"五个阶段"

**阶段一:原型(1 周)**
- 100 个智能体
- 7 天仿真
- 验证思路

**阶段二:校准(2 周)**
- 1000 个智能体
- 30 天仿真
- 与真实数据校准

**阶段三:实验(2-4 周)**
- 多次仿真(5+ seeds)
- 多参数扫描
- 记录所有配置

**阶段四:分析(2 周)**
- 统计检验
- 异质性分析
- 稳健性检验

**阶段五:报告(2 周)**
- 写论文
- 配 release
- 公开数据

### 23.9.2　代码组织

```python
# 实验脚本
# experiments/exp_001_baseline.py
from gaworld import Simulation

def run_experiment():
    sim = Simulation(config="configs/exp_001.json")
    sim.run(sim_days=30)
    sim.save_results("results/exp_001/")

if __name__ == "__main__":
    run_experiment()
```

### 23.9.3　实验记录

```python
# experiments/manifest.py
import json
from datetime import datetime

def record_manifest(config, results):
    return {
        "timestamp": datetime.now().isoformat(),
        "config": config.to_dict(),
        "results_summary": results.summary(),
        "git_commit": get_git_commit(),
    }
```

### 23.9.4　可视化

```python
# 用 matplotlib
import matplotlib.pyplot as plt

def plot_income_distribution(df):
    plt.hist(df['income'], bins=50)
    plt.title('Income Distribution')
    plt.xlabel('Income (CNY)')
    plt.ylabel('Count')
    plt.savefig('figures/income.png')
```

---

## 23.10　教学路线建议

### 23.10.1　本科生路线(1-2 周)

1. 装好 GAWorld,跑通最简示例
2. 改一两个配置,看结果变化
3. 写一份"我做了什么"的报告

### 23.10.2　研究生路线(1-2 月)

1. 跑通完整仿真
2. 设计自己的实验
3. 写预注册协议
4. 跑实验
5. 分析结果
6. 写论文初稿

### 23.10.3　工程师路线(2-4 周)

1. 读源码,理解架构
2. 写一个自定义决策模块
3. 写一个自定义事件
4. 接入自定义 LLM
5. 性能优化

### 23.10.4　团队路线(2-3 月)

1. 多人协作(配置管理、代码 review)
2. 大规模分布式仿真
3. Dashboard 自定义
4. 集成业务系统
5. 上线运维

---

## 23.11　2026 年最新进展

### 23.11.1　LLM 模型升级

- 2026 Q1:支持 GPT-4o 全功能
- 2026 Q2:支持 Claude 4.5
- 2026 Q3:支持 Gemini 2.5 Pro
- 2026 Q4:支持本地 Ollama 大模型

### 23.11.2　性能提升

- 仿真速度从 1000 智能体/小时 → 10000 智能体/小时
- LLM 调用成本降低 60%
- 内存使用降低 40%

### 23.11.3　新功能

- **智能体多人协同**:智能体之间能沟通、协作
- **多模态智能体**:支持图像、音频输入
- **数字孪生**:支持实时数据流接入
- **联邦学习**:支持跨组织协作

### 23.11.4　已知局限

- 大规模(> 10K 智能体)仍较慢
- 长期(> 1 年)仿真 LLM 成本高
- 多模态仿真仍在实验阶段

---

## 23.12　教学总结

GAWorld 是个**工程级社会仿真平台**,目标是让研究者:

1. 快速原型(1 周跑通)
2. 严肃研究(支持预注册、可复现)
3. 规模化(支持分布式)
4. 可扩展(支持自定义模块)

**核心建议**:

- 从小规模开始
- 用 git 管理配置
- 记录所有实验
- 公开可复现数据
- 关注 LLM 成本

学生做研究时,GAWorld 是"工具",不是"目标"——研究价值来自研究问题,不是来自仿真。

---

## 23.13　附录:常见快捷操作

```bash
# 一键跑完一个研究项目
bash scripts/run_study.sh my_study

# 一键生成论文草稿
bash scripts/paper_draft.sh

# 一键 Dashboard
python generative_city_sim.py dashboard --open
```

完整 CLI 速查见附录 B,配置参考见附录 C。
